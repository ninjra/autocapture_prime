"""SST pipeline orchestrator and capability implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.ids import encode_record_id_component

from .action import infer_action
from .compliance import redact_artifacts
from .delta import build_delta
from .extract import (
    extract_charts,
    extract_code_blocks,
    extract_spreadsheets,
    extract_tables,
    parse_ui_elements,
    run_ocr_tokens,
    track_cursor,
)
from .image import normalize_image, tile_image
from .layout import assemble_layout
from .match import match_ids
from .persist import SSTPersistence, config_hash
from .segment import SegmentDecision, decide_boundary
from .state import build_state
from .utils import hash_canonical, norm_text, ts_utc_to_ms


ShouldAbortFn = Callable[[], bool]


@dataclass(frozen=True)
class SSTPipelineResult:
    record_id: str
    boundary: bool
    boundary_reason: str
    heavy_ran: bool
    derived_records: int
    indexed_docs: int
    ocr_tokens: int
    derived_ids: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]


@dataclass
class _PrevContext:
    record_id: str
    phash: str
    downscaled: tuple[int, ...]
    state: dict[str, Any] | None
    cursor: dict[str, Any] | None


class SSTPipeline:
    """Deterministic vision-only screen semantic trace pipeline."""

    def __init__(self, system: Any, *, extractor_id: str, extractor_version: str) -> None:
        self._system = system
        self._config = getattr(system, "config", {}) if system is not None else {}
        self._sst_cfg = _sst_config(self._config)
        self._extractor_id = extractor_id
        self._extractor_version = extractor_version
        self._metadata = self._cap("storage.metadata")
        self._ocr = self._cap("ocr.engine")
        self._vlm = self._cap("vision.extractor")
        self._events = self._cap("event.builder")
        self._logger = self._cap("observability.logger")
        self._lexical = None
        self._vector = None
        self._indexes_ready = False
        self._config_hash = config_hash(self._sst_cfg)
        self._persistence: SSTPersistence | None = None
        self._prev_by_run: dict[str, _PrevContext] = {}

    def process_record(
        self,
        *,
        record_id: str,
        record: dict[str, Any],
        frame_bytes: bytes,
        allow_ocr: bool,
        allow_vlm: bool,
        should_abort: ShouldAbortFn | None,
        deadline_ts: float | None,
    ) -> SSTPipelineResult:
        diagnostics: list[dict[str, Any]] = []
        if self._metadata is None:
            diagnostics.append({"kind": "sst.missing_metadata"})
            return SSTPipelineResult(record_id, False, "missing_metadata", False, 0, 0, 0, tuple(), tuple(diagnostics))
        if not self._sst_cfg["enabled"]:
            diagnostics.append({"kind": "sst.disabled"})
            return SSTPipelineResult(record_id, False, "disabled", False, 0, 0, 0, tuple(), tuple(diagnostics))

        run_id = _run_id(self._config, record_id)
        ts_ms = ts_utc_to_ms(record.get("ts_utc") or record.get("ts_start_utc"))
        window_title = _window_title(record)

        try:
            normalized = normalize_image(
                frame_bytes,
                strip_alpha=bool(self._sst_cfg["strip_alpha"]),
                phash_size=int(self._sst_cfg["phash_size"]),
                phash_downscale=int(self._sst_cfg["phash_downscale"]),
            )
        except Exception as exc:
            diagnostics.append({"kind": "sst.normalize_error", "error": str(exc)})
            return SSTPipelineResult(record_id, False, "normalize_error", False, 0, 0, 0, tuple(), tuple(diagnostics))

        prev_ctx = self._prev_by_run.get(run_id)
        prev_phash = prev_ctx.phash if prev_ctx else None
        prev_downscaled = prev_ctx.downscaled if prev_ctx else None
        decision, downscaled = decide_boundary(
            phash=normalized.phash,
            prev_phash=prev_phash,
            image_rgb=normalized.image_rgb,
            prev_downscaled=prev_downscaled,
            d_stable=int(self._sst_cfg["d_stable"]),
            d_boundary=int(self._sst_cfg["d_boundary"]),
            diff_threshold_bp=int(self._sst_cfg["diff_threshold_bp"]),
            downscale_px=int(self._sst_cfg["segment_downscale_px"]),
        )

        derived_records = 0
        indexed_docs = 0
        ocr_tokens = 0
        derived_ids: list[str] = []
        frame_bbox = (0, 0, normalized.width, normalized.height)

        persist = self._ensure_persistence()
        try:
            frame_stats = persist.persist_frame(
                run_id=run_id,
                record_id=record_id,
                ts_ms=ts_ms,
                width=normalized.width,
                height=normalized.height,
                image_sha256=normalized.image_sha256,
                phash=normalized.phash,
                boundary=decision.boundary,
                boundary_reason=decision.reason,
                phash_distance=decision.phash_distance,
                diff_score_bp=decision.diff_score_bp,
            )
            derived_records += frame_stats.derived_records
            derived_ids.extend(frame_stats.derived_ids)
        except Exception as exc:  # pragma: no cover - defensive
            diagnostics.append({"kind": "sst.persist_frame_error", "error": str(exc)})

        heavy_ran = False
        heavy_result = _HeavyResult(0, 0, 0, tuple(), None, None, tuple())
        if _should_heavy(self._sst_cfg, decision, should_abort, deadline_ts):
            heavy_ran = True
            heavy_result = self._heavy_pass(
                run_id=run_id,
                record_id=record_id,
                record=record,
                frame_bytes=frame_bytes,
                ts_ms=ts_ms,
                window_title=window_title,
                normalized=normalized,
                decision=decision,
                frame_bbox=frame_bbox,
                allow_ocr=allow_ocr,
                allow_vlm=allow_vlm,
                prev_ctx=prev_ctx,
                should_abort=should_abort,
                deadline_ts=deadline_ts,
            )
            derived_records += heavy_result.derived_records
            indexed_docs += heavy_result.indexed_docs
            ocr_tokens += heavy_result.ocr_tokens
            derived_ids.extend(heavy_result.derived_ids)
            diagnostics.extend(heavy_result.diagnostics)

        prev_state = prev_ctx.state if prev_ctx else None
        prev_cursor = prev_ctx.cursor if prev_ctx else None
        next_ctx = _PrevContext(
            record_id=record_id,
            phash=normalized.phash,
            downscaled=downscaled,
            state=prev_state,
            cursor=prev_cursor,
        )
        if heavy_ran and heavy_result.state:
            next_ctx.state = heavy_result.state
            next_ctx.cursor = heavy_result.cursor
        self._prev_by_run[run_id] = next_ctx

        return SSTPipelineResult(
            record_id=record_id,
            boundary=decision.boundary,
            boundary_reason=decision.reason,
            heavy_ran=heavy_ran,
            derived_records=derived_records,
            indexed_docs=indexed_docs,
            ocr_tokens=ocr_tokens,
            derived_ids=tuple(derived_ids),
            diagnostics=tuple(diagnostics),
        )

    def _heavy_pass(
        self,
        *,
        run_id: str,
        record_id: str,
        record: dict[str, Any],
        frame_bytes: bytes,
        ts_ms: int,
        window_title: str | None,
        normalized,
        decision: SegmentDecision,
        frame_bbox: tuple[int, int, int, int],
        allow_ocr: bool,
        allow_vlm: bool,
        prev_ctx: _PrevContext | None,
        should_abort: ShouldAbortFn | None,
        deadline_ts: float | None,
    ) -> "_HeavyResult":
        diagnostics: list[dict[str, Any]] = []
        patches = tile_image(
            normalized.image_rgb,
            tile_max_px=int(self._sst_cfg["tile_max_px"]),
            overlap_px=int(self._sst_cfg["tile_overlap_px"]),
            add_full_frame=bool(self._sst_cfg["tile_add_full_frame"]),
        )
        tokens, ocr_diag = run_ocr_tokens(
            patches=patches,
            ocr_capability=self._ocr,
            frame_width=normalized.width,
            frame_height=normalized.height,
            min_conf_bp=int(self._sst_cfg["ocr_min_conf_bp"]),
            nms_iou_bp=int(self._sst_cfg["ocr_nms_iou_bp"]),
            max_tokens=int(self._sst_cfg["ocr_max_tokens"]),
            max_patches=int(self._sst_cfg["ocr_max_patches"]),
            allow_ocr=allow_ocr,
            should_abort=should_abort,
            deadline_ts=deadline_ts,
        )
        diagnostics.extend(ocr_diag.items)
        tokens.extend(self._vlm_tokens(normalized.width, normalized.height, frame_bytes, allow_vlm, should_abort, deadline_ts))
        tokens = _stable_tokens(tokens)
        ocr_tokens = len(tokens)

        text_lines, text_blocks = assemble_layout(
            tokens,
            line_y_threshold_px=int(self._sst_cfg["layout_line_y_px"]),
            block_gap_px=int(self._sst_cfg["layout_block_gap_px"]),
            align_tolerance_px=int(self._sst_cfg["layout_align_tol_px"]),
        )
        tables = extract_tables(
            tokens=tokens,
            state_id="pending",
            min_rows=int(self._sst_cfg["table_min_rows"]),
            min_cols=int(self._sst_cfg["table_min_cols"]),
            max_cells=int(self._sst_cfg["table_max_cells"]),
            row_gap_px=int(self._sst_cfg["table_row_gap_px"]),
            col_gap_px=int(self._sst_cfg["table_col_gap_px"]),
        )
        spreadsheets = extract_spreadsheets(
            tokens=tokens,
            tables=tables,
            state_id="pending",
            header_scan_rows=int(self._sst_cfg["sheet_header_scan_rows"]),
        )
        code_blocks = extract_code_blocks(
            tokens=tokens,
            text_lines=text_lines,
            state_id="pending",
            min_keywords=int(self._sst_cfg["code_min_keywords"]),
        )
        charts = extract_charts(
            tokens=tokens,
            state_id="pending",
            min_ticks=int(self._sst_cfg["chart_min_ticks"]),
        )

        element_graph = parse_ui_elements(
            state_id="pending",
            frame_bbox=frame_bbox,
            tokens=tokens,
            text_blocks=text_blocks,
            tables=tables,
            spreadsheets=spreadsheets,
            code_blocks=code_blocks,
            charts=charts,
        )
        cursor = track_cursor(record, normalized.width, normalized.height)

        state = build_state(
            run_id=run_id,
            frame_id=record_id,
            ts_ms=ts_ms,
            phash=normalized.phash,
            width=normalized.width,
            height=normalized.height,
            tokens=tokens,
            element_graph=element_graph,
            text_lines=text_lines,
            text_blocks=text_blocks,
            tables=tables,
            spreadsheets=spreadsheets,
            code_blocks=code_blocks,
            charts=charts,
            cursor=cursor,
            window_title=window_title,
        )
        state = match_ids(prev_ctx.state if prev_ctx else None, state)
        delta_event = build_delta(
            prev_state=prev_ctx.state if prev_ctx else None,
            state=state,
            bbox_shift_px=int(self._sst_cfg["delta_bbox_shift_px"]),
            table_match_iou_bp=int(self._sst_cfg["delta_table_match_iou_bp"]),
        )
        action_event = infer_action(
            delta_event=delta_event,
            cursor_prev=prev_ctx.cursor if prev_ctx else None,
            cursor_curr=cursor,
            prev_state=prev_ctx.state if prev_ctx else None,
            state=state,
        )

        state_redacted, delta_event, action_event, compliance_metrics = redact_artifacts(
            state=state,
            delta_event=delta_event,
            action_event=action_event,
            enabled=bool(self._sst_cfg["redact_enabled"]),
            denylist_app_hints=list(self._sst_cfg["redact_denylist"]),
        )
        diagnostics.append({"kind": "sst.compliance", **compliance_metrics})
        if state_redacted is None:
            diagnostics.append({"kind": "sst.dropped"})
            return _HeavyResult(0, 0, ocr_tokens, tuple(diagnostics), None, cursor, tuple())
        state = state_redacted

        persist = self._ensure_persistence()
        stats = persist.persist_state_bundle(
            run_id=run_id,
            record_id=record_id,
            state=state,
            image_sha256=normalized.image_sha256,
            frame_bbox=frame_bbox,
            prev_record_id=prev_ctx.record_id if prev_ctx else None,
            delta_event=delta_event,
            action_event=action_event,
        )
        diagnostics.append(
            {
                "kind": "sst.persist",
                "derived_records": stats.derived_records,
                "indexed_docs": stats.indexed_docs,
                "boundary": decision.boundary,
            }
        )
        return _HeavyResult(
            stats.derived_records,
            stats.indexed_docs,
            ocr_tokens,
            tuple(diagnostics),
            state,
            cursor,
            stats.derived_ids,
        )

    def _vlm_tokens(
        self,
        frame_width: int,
        frame_height: int,
        frame_bytes: bytes,
        allow_vlm: bool,
        should_abort: ShouldAbortFn | None,
        deadline_ts: float | None,
    ) -> list[dict[str, Any]]:
        if not allow_vlm or self._vlm is None:
            return []
        providers = []
        target = self._vlm
        if hasattr(target, "target"):
            target = getattr(target, "target")
        if hasattr(target, "items"):
            try:
                providers = list(target.items())
            except Exception:
                providers = []
        if not providers:
            providers = [("vision.extractor", self._vlm)]

        tokens: list[dict[str, Any]] = []
        for provider_id, provider in providers:
            if should_abort and should_abort():
                break
            if deadline_ts is not None and time.time() >= deadline_ts:
                break
            try:
                text = str(provider.extract(frame_bytes).get("text", ""))
            except Exception:
                continue
            text = norm_text(text)
            if not text:
                continue
            token_id = encode_record_id_component(f"vlm-{provider_id}-{hash_canonical(text)[:12]}")
            tokens.append(
                {
                    "token_id": token_id,
                    "text": text,
                    "norm_text": text,
                    "bbox": (0, 0, frame_width, frame_height),
                    "confidence_bp": 6000,
                    "source": "vlm",
                    "flags": {"monospace_likely": False, "is_number": False},
                    "provider_id": provider_id,
                    "patch_id": "full_frame",
                }
            )
        return tokens

    def _cap(self, name: str) -> Any | None:
        if hasattr(self._system, "has") and self._system.has(name):
            return self._system.get(name)
        if isinstance(self._system, dict):
            return self._system.get(name)
        return None

    def _ensure_persistence(self) -> SSTPersistence:
        if self._persistence is not None:
            return self._persistence
        self._ensure_indexes()
        index_fn = self._index_text
        self._persistence = SSTPersistence(
            metadata=self._metadata,
            event_builder=self._events,
            index_text=index_fn,
            extractor_id=self._extractor_id,
            extractor_version=self._extractor_version,
            config_hash=self._config_hash,
            schema_version=int(self._sst_cfg["schema_version"]),
        )
        return self._persistence

    def _ensure_indexes(self) -> None:
        if self._indexes_ready:
            return
        self._indexes_ready = True
        if not isinstance(self._config, dict) or not self._config:
            return
        try:
            self._lexical, self._vector = build_indexes(self._config, logger=self._log)
        except Exception as exc:
            self._lexical = None
            self._vector = None
            self._log(f"sst.index_init_failed: {exc}")

    def _index_text(self, doc_id: str, text: str) -> None:
        if not text:
            return
        if self._lexical is not None:
            try:
                self._lexical.index(doc_id, text)
            except Exception as exc:
                self._log(f"sst.index_lexical_error[{doc_id}]: {exc}")
        if self._vector is not None:
            try:
                self._vector.index(doc_id, text)
            except Exception as exc:
                self._log(f"sst.index_vector_error[{doc_id}]: {exc}")

    def _log(self, msg: str) -> None:
        if self._logger is None:
            return
        try:
            self._logger.log("sst.pipeline", {"message": msg})
        except Exception:
            return


@dataclass(frozen=True)
class _HeavyResult:
    derived_records: int
    indexed_docs: int
    ocr_tokens: int
    diagnostics: tuple[dict[str, Any], ...]
    state: dict[str, Any] | None
    cursor: dict[str, Any] | None
    derived_ids: tuple[str, ...]


def _sst_config(config: dict[str, Any]) -> dict[str, Any]:
    processing = config.get("processing", {}) if isinstance(config, dict) else {}
    sst = processing.get("sst", {}) if isinstance(processing, dict) else {}

    def _int(name: str, default: int) -> int:
        try:
            return int(sst.get(name, default))
        except Exception:
            return default

    def _bool(name: str, default: bool) -> bool:
        val = sst.get(name, default)
        return bool(val)

    denylist = sst.get("redact_denylist", [])
    if not isinstance(denylist, list):
        denylist = []

    return {
        "enabled": _bool("enabled", True),
        "strip_alpha": _bool("strip_alpha", True),
        "phash_size": _int("phash_size", 8),
        "phash_downscale": _int("phash_downscale", 32),
        "d_stable": _int("d_stable", 4),
        "d_boundary": _int("d_boundary", 12),
        "diff_threshold_bp": _int("diff_threshold_bp", 1800),
        "segment_downscale_px": _int("segment_downscale_px", 64),
        "heavy_on_boundary": _bool("heavy_on_boundary", True),
        "heavy_always": _bool("heavy_always", False),
        "tile_max_px": _int("tile_max_px", 1024),
        "tile_overlap_px": _int("tile_overlap_px", 64),
        "tile_add_full_frame": _bool("tile_add_full_frame", True),
        "ocr_min_conf_bp": _int("ocr_min_conf_bp", 3500),
        "ocr_nms_iou_bp": _int("ocr_nms_iou_bp", 7000),
        "ocr_max_tokens": _int("ocr_max_tokens", 4000),
        "ocr_max_patches": _int("ocr_max_patches", 64),
        "layout_line_y_px": _int("layout_line_y_px", 12),
        "layout_block_gap_px": _int("layout_block_gap_px", 28),
        "layout_align_tol_px": _int("layout_align_tol_px", 48),
        "table_min_rows": _int("table_min_rows", 2),
        "table_min_cols": _int("table_min_cols", 2),
        "table_max_cells": _int("table_max_cells", 2500),
        "table_row_gap_px": _int("table_row_gap_px", 18),
        "table_col_gap_px": _int("table_col_gap_px", 36),
        "sheet_header_scan_rows": _int("sheet_header_scan_rows", 2),
        "code_min_keywords": _int("code_min_keywords", 1),
        "chart_min_ticks": _int("chart_min_ticks", 2),
        "delta_bbox_shift_px": _int("delta_bbox_shift_px", 24),
        "delta_table_match_iou_bp": _int("delta_table_match_iou_bp", 3000),
        "redact_enabled": _bool("redact_enabled", True),
        "redact_denylist": tuple(str(x) for x in denylist if x),
        "schema_version": _int("schema_version", 1),
    }


def _should_heavy(cfg: dict[str, Any], decision: SegmentDecision, should_abort: ShouldAbortFn | None, deadline_ts: float | None) -> bool:
    if should_abort and should_abort():
        return False
    if deadline_ts is not None and time.time() >= deadline_ts:
        return False
    if cfg["heavy_always"]:
        return True
    if not cfg["heavy_on_boundary"]:
        return False
    return bool(decision.boundary)


def _run_id(config: dict[str, Any], record_id: str) -> str:
    if "/" in record_id:
        return record_id.split("/", 1)[0]
    runtime = config.get("runtime", {}) if isinstance(config, dict) else {}
    run_id = runtime.get("run_id")
    return str(run_id or "run")


def _window_title(record: dict[str, Any]) -> str | None:
    window_ref = record.get("window_ref")
    if isinstance(window_ref, dict):
        title = window_ref.get("title") or window_ref.get("window_title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    window = record.get("window")
    if isinstance(window, dict):
        title = window.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def _stable_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = [t for t in tokens if t.get("norm_text")]
    tokens.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], t["bbox"][2], t["token_id"]))
    # Deduplicate by id while preserving order.
    out = []
    seen = set()
    for token in tokens:
        tid = token["token_id"]
        if tid in seen:
            continue
        seen.add(tid)
        out.append(token)
    return out
