"""SST pipeline orchestrator and capability implementation."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Any, Callable

from autocapture.indexing.factory import build_indexes
from autocapture_nx.kernel.canonical_json import CanonicalJSONError, dumps as canonical_dumps
from autocapture_nx.kernel.derived_records import extract_text_payload, derived_text_record_id
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.providers import capability_providers

from .action import infer_action
from .compliance import redact_artifacts, redact_text, redact_value
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
from .utils import clamp_bbox, hash_canonical, norm_text, ts_utc_to_ms


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


_STAGE_NAMES: tuple[str, ...] = (
    "ingest.frame",
    "temporal.segment",
    "preprocess.normalize",
    "preprocess.tile",
    "ocr.onnx",
    "vision.vlm",
    "layout.assemble",
    "extract.table",
    "extract.spreadsheet",
    "extract.code",
    "extract.chart",
    "ui.parse",
    "track.cursor",
    "build.state",
    "match.ids",
    "build.delta",
    "infer.action",
    "compliance.redact",
    "persist.bundle",
    "index.text",
)

_STAGE_POLICY_DEFAULT: dict[str, Any] = {
    "enabled": True,
    "provider_ids": tuple(),
    "fanout": True,
    "max_providers": 0,
}


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
        self._stage_hooks = self._cap("processing.stage.hooks")
        self._post_index = self._cap("index.postprocess")
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

        seg_payload = {
            "run_id": run_id,
            "record_id": record_id,
            "ts_ms": ts_ms,
            "phash": normalized.phash,
            "prev_phash": prev_phash,
            "prev_downscaled": prev_downscaled,
            "image_rgb": normalized.image_rgb,
            "d_stable": int(self._sst_cfg["d_stable"]),
            "d_boundary": int(self._sst_cfg["d_boundary"]),
            "diff_threshold_bp": int(self._sst_cfg["diff_threshold_bp"]),
            "segment_downscale_px": int(self._sst_cfg["segment_downscale_px"]),
            "boundary": decision.boundary,
            "boundary_reason": decision.reason,
            "phash_distance": decision.phash_distance,
            "diff_score_bp": decision.diff_score_bp,
        }
        frame_width = int(normalized.width)
        frame_height = int(normalized.height)
        frame_bbox = (0, 0, frame_width, frame_height)
        self._run_stage_hooks(
            stage="temporal.segment",
            payload=seg_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        override = seg_payload.get("boundary_override")
        if override is not False and isinstance(seg_payload.get("boundary"), bool):
            phash_distance = decision.phash_distance
            diff_score_bp = decision.diff_score_bp
            raw_phash = seg_payload.get("phash_distance")
            raw_diff = seg_payload.get("diff_score_bp")
            if isinstance(raw_phash, int):
                phash_distance = raw_phash
            if isinstance(raw_diff, int):
                diff_score_bp = raw_diff
            decision = SegmentDecision(
                bool(seg_payload.get("boundary")),
                str(seg_payload.get("boundary_reason") or decision.reason),
                phash_distance,
                diff_score_bp,
            )
        downscaled_value = seg_payload.get("downscaled")
        if isinstance(downscaled_value, tuple):
            downscaled = downscaled_value

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
        frame_width = int(normalized.width)
        frame_height = int(normalized.height)
        stage_payload: dict[str, Any] = {
            "run_id": run_id,
            "record_id": record_id,
            "ts_ms": ts_ms,
            "frame_bbox": frame_bbox,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "image_sha256": normalized.image_sha256,
            "phash": normalized.phash,
            "boundary": decision.boundary,
            "boundary_reason": decision.reason,
            "record": record,
            "window_title": window_title,
            "frame_bytes": frame_bytes,
            "allow_ocr": bool(allow_ocr),
            "allow_vlm": bool(allow_vlm),
        }
        if prev_ctx:
            stage_payload["prev_record_id"] = prev_ctx.record_id
        if prev_ctx and isinstance(prev_ctx.state, dict):
            stage_payload["prev_state"] = prev_ctx.state
        if prev_ctx and isinstance(prev_ctx.cursor, dict):
            stage_payload["cursor_prev"] = prev_ctx.cursor

        self._run_stage_hooks(
            stage="ingest.frame",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        self._run_stage_hooks(
            stage="preprocess.normalize",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        focus_tokens: list[dict[str, Any]] | None = None
        if self._sst_cfg.get("tile_refine_enabled") and prev_ctx and isinstance(prev_ctx.state, dict):
            prev_tokens = prev_ctx.state.get("tokens")
            if isinstance(prev_tokens, list):
                focus_tokens = prev_tokens
        patches = tile_image(
            normalized.image_rgb,
            tile_max_px=int(self._sst_cfg["tile_max_px"]),
            overlap_px=int(self._sst_cfg["tile_overlap_px"]),
            add_full_frame=bool(self._sst_cfg["tile_add_full_frame"]),
            focus_tokens=focus_tokens,
            focus_conf_bp=int(self._sst_cfg.get("tile_refine_low_conf_bp", 0) or 0),
            focus_padding_px=int(self._sst_cfg.get("tile_refine_padding_px", 24) or 0),
            focus_max_patches=int(self._sst_cfg.get("tile_refine_max_patches", 0) or 0),
            focus_cluster_gap_px=int(self._sst_cfg.get("tile_refine_cluster_gap_px", 48) or 0),
        )
        baseline_patches = patches
        stage_payload["patches"] = baseline_patches
        self._run_stage_hooks(
            stage="preprocess.tile",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        patches = stage_payload.get("patches", baseline_patches)
        if not isinstance(patches, list):
            diagnostics.append({"kind": "sst.stage_hook_invalid_patches", "stage": "preprocess.tile"})
            patches = baseline_patches

        tokens, ocr_diag, raw_tokens = run_ocr_tokens(
            patches=patches,
            ocr_capability=self._ocr,
            frame_width=frame_width,
            frame_height=frame_height,
            full_frame_bytes=frame_bytes if isinstance(frame_bytes, (bytes, bytearray)) else None,
            min_conf_bp=int(self._sst_cfg["ocr_min_conf_bp"]),
            nms_iou_bp=int(self._sst_cfg["ocr_nms_iou_bp"]),
            max_tokens=int(self._sst_cfg["ocr_max_tokens"]),
            max_patches=int(self._sst_cfg["ocr_max_patches"]),
            prefer_full_frame=bool(self._sst_cfg.get("ocr_prefer_full_frame", True)),
            allow_ocr=allow_ocr,
            should_abort=should_abort,
            deadline_ts=deadline_ts,
        )
        diagnostics.extend(ocr_diag.items)
        tokens = _sanitize_tokens(
            tokens,
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="ocr.onnx",
            provider_id_hint="ocr.engine",
        )
        raw_tokens = _sanitize_tokens(
            raw_tokens,
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="ocr.onnx.raw",
            provider_id_hint="ocr.engine",
        )
        tokens_raw = _merge_token_lists(raw_tokens, tokens)
        stage_payload["tokens"] = tokens
        stage_payload["tokens_raw"] = tokens_raw
        self._run_stage_hooks(
            stage="ocr.onnx",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        tokens = _tokens_from_payload(
            stage_payload,
            fallback=tokens,
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="ocr.onnx",
            provider_id_hint="stage_hook",
        )
        raw_payload = stage_payload.get("tokens_raw", tokens_raw)
        if isinstance(raw_payload, list):
            tokens_raw = _sanitize_tokens(
                raw_payload,
                frame_width=frame_width,
                frame_height=frame_height,
                diagnostics=diagnostics,
                stage="ocr.onnx.raw",
                provider_id_hint="stage_hook",
            )
            stage_payload["tokens_raw"] = tokens_raw
        vlm_tokens = _sanitize_tokens(
            self._vlm_tokens(
                frame_width,
                frame_height,
                frame_bytes,
                allow_vlm,
                should_abort,
                deadline_ts,
                run_id=run_id,
                source_id=record_id,
            ),
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="vision.vlm",
            provider_id_hint="vision.extractor",
        )
        tokens.extend(vlm_tokens)
        tokens_raw = _merge_token_lists(tokens_raw, vlm_tokens)
        stage_payload["tokens"] = tokens
        stage_payload["tokens_raw"] = tokens_raw
        self._run_stage_hooks(
            stage="vision.vlm",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        tokens = _tokens_from_payload(
            stage_payload,
            fallback=tokens,
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="vision.vlm",
            provider_id_hint="stage_hook",
        )
        tokens = _stable_tokens(tokens)
        stage_payload["tokens"] = tokens
        tokens_raw = _merge_token_lists(tokens_raw, tokens)
        stage_payload["tokens_raw"] = tokens_raw
        ocr_tokens = len(tokens)

        layout_tokens = _layout_tokens(tokens)
        text_lines, text_blocks = assemble_layout(
            layout_tokens,
            line_y_threshold_px=int(self._sst_cfg["layout_line_y_px"]),
            block_gap_px=int(self._sst_cfg["layout_block_gap_px"]),
            align_tolerance_px=int(self._sst_cfg["layout_align_tol_px"]),
        )
        stage_payload["tokens"] = layout_tokens
        stage_payload["text_lines"] = text_lines
        stage_payload["text_blocks"] = text_blocks
        self._run_stage_hooks(
            stage="layout.assemble",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        tokens = _tokens_from_payload(
            stage_payload,
            fallback=layout_tokens,
            frame_width=frame_width,
            frame_height=frame_height,
            diagnostics=diagnostics,
            stage="layout.assemble",
            provider_id_hint="stage_hook",
        )
        tokens = _stable_tokens(tokens)
        layout_tokens = _layout_tokens(tokens)
        # Re-run layout after hooks so token line/block ids stay coherent.
        text_lines, text_blocks = assemble_layout(
            layout_tokens,
            line_y_threshold_px=int(self._sst_cfg["layout_line_y_px"]),
            block_gap_px=int(self._sst_cfg["layout_block_gap_px"]),
            align_tolerance_px=int(self._sst_cfg["layout_align_tol_px"]),
        )
        stage_payload["tokens"] = layout_tokens
        stage_payload["text_lines"] = text_lines
        stage_payload["text_blocks"] = text_blocks
        ocr_tokens = len(layout_tokens)
        tokens = layout_tokens
        tokens_raw = _merge_token_lists(tokens_raw, tokens)
        stage_payload["tokens_raw"] = tokens_raw

        tables = extract_tables(
            tokens=tokens,
            state_id="pending",
            min_rows=int(self._sst_cfg["table_min_rows"]),
            min_cols=int(self._sst_cfg["table_min_cols"]),
            max_cells=int(self._sst_cfg["table_max_cells"]),
            row_gap_px=int(self._sst_cfg["table_row_gap_px"]),
            col_gap_px=int(self._sst_cfg["table_col_gap_px"]),
        )
        baseline_tables = tables
        stage_payload["tables"] = baseline_tables
        self._run_stage_hooks(
            stage="extract.table",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        tables = stage_payload.get("tables", baseline_tables)
        if not isinstance(tables, list):
            diagnostics.append({"kind": "sst.stage_hook_invalid_tables", "stage": "extract.table"})
            tables = baseline_tables
        stage_payload["tables"] = tables

        spreadsheets = extract_spreadsheets(
            tokens=tokens,
            tables=tables,
            state_id="pending",
            header_scan_rows=int(self._sst_cfg["sheet_header_scan_rows"]),
        )
        baseline_spreadsheets = spreadsheets
        stage_payload["spreadsheets"] = baseline_spreadsheets
        self._run_stage_hooks(
            stage="extract.spreadsheet",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        spreadsheets = stage_payload.get("spreadsheets", baseline_spreadsheets)
        if not isinstance(spreadsheets, list):
            diagnostics.append({"kind": "sst.stage_hook_invalid_spreadsheets", "stage": "extract.spreadsheet"})
            spreadsheets = baseline_spreadsheets
        stage_payload["spreadsheets"] = spreadsheets

        code_blocks = extract_code_blocks(
            tokens=tokens,
            text_lines=text_lines,
            state_id="pending",
            min_keywords=int(self._sst_cfg["code_min_keywords"]),
            image_rgb=normalized.image_rgb,
            detect_caret=bool(self._sst_cfg.get("code_detect_caret", False)),
            detect_selection=bool(self._sst_cfg.get("code_detect_selection", False)),
        )
        baseline_code_blocks = code_blocks
        stage_payload["code_blocks"] = baseline_code_blocks
        self._run_stage_hooks(
            stage="extract.code",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        code_blocks = stage_payload.get("code_blocks", baseline_code_blocks)
        if not isinstance(code_blocks, list):
            diagnostics.append({"kind": "sst.stage_hook_invalid_code_blocks", "stage": "extract.code"})
            code_blocks = baseline_code_blocks
        stage_payload["code_blocks"] = code_blocks

        charts = extract_charts(
            tokens=tokens,
            state_id="pending",
            min_ticks=int(self._sst_cfg["chart_min_ticks"]),
        )
        baseline_charts = charts
        stage_payload["charts"] = baseline_charts
        self._run_stage_hooks(
            stage="extract.chart",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        charts = stage_payload.get("charts", baseline_charts)
        if not isinstance(charts, list):
            diagnostics.append({"kind": "sst.stage_hook_invalid_charts", "stage": "extract.chart"})
            charts = baseline_charts
        stage_payload["charts"] = charts

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
        baseline_element_graph = element_graph
        stage_payload["element_graph"] = baseline_element_graph
        self._run_stage_hooks(
            stage="ui.parse",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        element_graph = stage_payload.get("element_graph", baseline_element_graph)
        if not isinstance(element_graph, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_element_graph", "stage": "ui.parse"})
            element_graph = baseline_element_graph
        stage_payload["element_graph"] = element_graph

        cursor = track_cursor(record, frame_width, frame_height)
        baseline_cursor = cursor
        stage_payload["cursor"] = baseline_cursor
        self._run_stage_hooks(
            stage="track.cursor",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        cursor = stage_payload.get("cursor", baseline_cursor)
        if cursor is not None and not isinstance(cursor, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_cursor", "stage": "track.cursor"})
            cursor = baseline_cursor
        stage_payload["cursor"] = cursor

        state = build_state(
            run_id=run_id,
            frame_id=record_id,
            ts_ms=ts_ms,
            phash=normalized.phash,
            image_sha256=normalized.image_sha256,
            frame_index=int(record.get("frame_index", 0) or 0),
            width=frame_width,
            height=frame_height,
            tokens=tokens,
            tokens_raw=tokens_raw,
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
        baseline_state = state
        stage_payload["state"] = baseline_state
        self._run_stage_hooks(
            stage="build.state",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        state = stage_payload.get("state", baseline_state)
        if not isinstance(state, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_state", "stage": "build.state"})
            state = baseline_state
        stage_payload["state"] = state

        state = match_ids(prev_ctx.state if prev_ctx else None, state)
        baseline_state = state
        stage_payload["state"] = baseline_state
        self._run_stage_hooks(
            stage="match.ids",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        state = stage_payload.get("state", baseline_state)
        if not isinstance(state, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_state", "stage": "match.ids"})
            state = baseline_state
        stage_payload["state"] = state

        delta_event = build_delta(
            prev_state=prev_ctx.state if prev_ctx else None,
            state=state,
            bbox_shift_px=int(self._sst_cfg["delta_bbox_shift_px"]),
            table_match_iou_bp=int(self._sst_cfg["delta_table_match_iou_bp"]),
        )
        baseline_delta_event = delta_event
        stage_payload["delta_event"] = baseline_delta_event
        self._run_stage_hooks(
            stage="build.delta",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        delta_event = stage_payload.get("delta_event", baseline_delta_event)
        if delta_event is not None and not isinstance(delta_event, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_delta", "stage": "build.delta"})
            delta_event = baseline_delta_event
        stage_payload["delta_event"] = delta_event

        action_event = infer_action(
            delta_event=delta_event,
            cursor_prev=prev_ctx.cursor if prev_ctx else None,
            cursor_curr=cursor,
            prev_state=prev_ctx.state if prev_ctx else None,
            state=state,
        )
        baseline_action_event = action_event
        stage_payload["action_event"] = baseline_action_event
        self._run_stage_hooks(
            stage="infer.action",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        action_event = stage_payload.get("action_event", baseline_action_event)
        if action_event is not None and not isinstance(action_event, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_action", "stage": "infer.action"})
            action_event = baseline_action_event
        stage_payload["action_event"] = action_event

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
        baseline_state = state
        baseline_delta_event = delta_event
        baseline_action_event = action_event
        stage_payload["state"] = baseline_state
        stage_payload["delta_event"] = baseline_delta_event
        stage_payload["action_event"] = baseline_action_event

        self._run_stage_hooks(
            stage="compliance.redact",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        state = stage_payload.get("state", baseline_state)
        delta_event = stage_payload.get("delta_event", baseline_delta_event)
        action_event = stage_payload.get("action_event", baseline_action_event)
        if not isinstance(state, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_state", "stage": "compliance.redact"})
            state = baseline_state
        if delta_event is not None and not isinstance(delta_event, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_delta", "stage": "compliance.redact"})
            delta_event = baseline_delta_event
        if action_event is not None and not isinstance(action_event, dict):
            diagnostics.append({"kind": "sst.stage_hook_invalid_action", "stage": "compliance.redact"})
            action_event = baseline_action_event

        # Re-apply redaction after hooks to prevent re-introducing sensitive text.
        state_redacted, delta_event, action_event, compliance_post = redact_artifacts(
            state=state,
            delta_event=delta_event,
            action_event=action_event,
            enabled=bool(self._sst_cfg["redact_enabled"]),
            denylist_app_hints=list(self._sst_cfg["redact_denylist"]),
        )
        if compliance_post.get("redactions") or compliance_post.get("dropped"):
            diagnostics.append({"kind": "sst.compliance_post", **compliance_post})
        if state_redacted is None:
            diagnostics.append({"kind": "sst.dropped"})
            return _HeavyResult(0, 0, ocr_tokens, tuple(diagnostics), None, cursor, tuple())
        state = state_redacted
        stage_payload["state"] = state
        stage_payload["delta_event"] = delta_event
        stage_payload["action_event"] = action_event
        if "extra_docs" not in stage_payload:
            stage_payload["extra_docs"] = []

        self._run_stage_hooks(
            stage="index.text",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        extra_docs = _collect_extra_docs(stage_payload, diagnostics=diagnostics, stage="index.text")
        stage_payload["extra_docs"] = extra_docs

        self._run_stage_hooks(
            stage="persist.bundle",
            payload=stage_payload,
            diagnostics=diagnostics,
            run_id=run_id,
            record_id=record_id,
            frame_bbox=frame_bbox,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        persisted = stage_payload.get("persisted") if isinstance(stage_payload.get("persisted"), dict) else None
        extra_docs = _collect_extra_docs(stage_payload, diagnostics=diagnostics, stage="persist.bundle", fallback=extra_docs)
        extra_docs, extra_redactions = _redact_extra_docs(extra_docs, enabled=bool(self._sst_cfg["redact_enabled"]))
        if extra_redactions:
            diagnostics.append({"kind": "sst.extra_doc_redactions", "redactions": extra_redactions})

        if persisted and persisted.get("handled"):
            derived_records = int(persisted.get("derived_records", 0))
            indexed_docs = int(persisted.get("indexed_docs", 0))
            derived_ids = tuple(persisted.get("derived_ids", ()) or ())
            diagnostics.append(
                {
                    "kind": "sst.persist",
                    "derived_records": derived_records,
                    "indexed_docs": indexed_docs,
                    "boundary": decision.boundary,
                    "extra_docs": len(extra_docs),
                    "plugin": "persist.bundle",
                }
            )
            return _HeavyResult(
                derived_records,
                indexed_docs,
                ocr_tokens,
                tuple(diagnostics),
                state,
                cursor,
                derived_ids,
            )

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
            extra_docs=extra_docs,
        )
        diagnostics.append(
            {
                "kind": "sst.persist",
                "derived_records": stats.derived_records,
                "indexed_docs": stats.indexed_docs,
                "boundary": decision.boundary,
                "extra_docs": len(extra_docs),
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

    def _unwrap_target(self, cap: Any) -> Any:
        target = cap
        if getattr(type(target), "target", None) is not None:
            try:
                target = target.target
            except Exception:
                return cap
        return target

    def _stage_policy(self, stage: str) -> dict[str, Any]:
        policies = self._sst_cfg.get("stage_providers", {})
        policy = policies.get(stage) if isinstance(policies, dict) else None
        merged = dict(_STAGE_POLICY_DEFAULT)
        if isinstance(policy, dict):
            merged.update(policy)
        if (not isinstance(policies, dict) or stage not in policies) and hasattr(self._unwrap_target(self._stage_hooks), "fanout"):
            try:
                merged["fanout"] = bool(getattr(self._unwrap_target(self._stage_hooks), "fanout"))
            except Exception:
                merged["fanout"] = merged.get("fanout", True)
        merged["provider_ids"] = tuple(str(pid) for pid in merged.get("provider_ids", ()) if str(pid))
        try:
            merged["max_providers"] = int(merged.get("max_providers", 0) or 0)
        except Exception:
            merged["max_providers"] = 0
        merged["fanout"] = bool(merged.get("fanout", True))
        merged["enabled"] = bool(merged.get("enabled", True))
        return merged

    def _stage_providers(self, stage: str, diagnostics: list[dict[str, Any]]) -> tuple[dict[str, Any], list[tuple[str, Any]]]:
        if self._stage_hooks is None:
            return dict(_STAGE_POLICY_DEFAULT), []
        policy = self._stage_policy(stage)
        if not policy["enabled"]:
            return policy, []
        target = self._unwrap_target(self._stage_hooks)
        providers: list[tuple[str, Any]] = []
        try:
            if hasattr(target, "items"):
                providers = list(target.items())
            else:
                providers = [("processing.stage.hooks", self._stage_hooks)]
        except Exception as exc:
            diagnostics.append({"kind": "sst.stage_hook_error", "stage": stage, "error": str(exc)})
            return policy, []
        filtered: list[tuple[str, Any]] = []
        for provider_id, provider in providers:
            if not _provider_supports_stage(provider, stage, diagnostics, provider_id=str(provider_id)):
                continue
            filtered.append((str(provider_id), provider))
        providers = filtered
        provider_ids = policy.get("provider_ids", ())
        if provider_ids:
            allowed = set(provider_ids)
            providers = [item for item in providers if item[0] in allowed]
            if not providers:
                diagnostics.append(
                    {
                        "kind": "sst.stage_hook_no_allowed_providers",
                        "stage": stage,
                        "provider_ids": sorted(allowed),
                    }
                )
                return policy, []
        max_providers = int(policy.get("max_providers", 0) or 0)
        if max_providers > 0:
            providers = providers[:max_providers]
        return policy, providers

    def _run_stage_hooks(
        self,
        *,
        stage: str,
        payload: dict[str, Any],
        diagnostics: list[dict[str, Any]],
        run_id: str,
        record_id: str,
        frame_bbox: tuple[int, int, int, int],
        frame_width: int,
        frame_height: int,
    ) -> dict[str, Any]:
        policy, providers = self._stage_providers(stage, diagnostics)
        if not providers:
            return payload
        applied: list[str] = []
        for provider_id, provider in providers:
            run_stage = getattr(provider, "run_stage", None)
            if not callable(run_stage):
                diagnostics.append(
                    {"kind": "sst.stage_hook_missing_run_stage", "stage": stage, "provider_id": provider_id}
                )
                continue
            snapshot = copy.deepcopy(payload)
            try:
                result = run_stage(stage, snapshot)
            except Exception as exc:
                diagnostics.append({"kind": "sst.stage_hook_error", "stage": stage, "provider_id": provider_id, "error": str(exc)})
                continue
            if result is None:
                continue
            if not isinstance(result, dict):
                diagnostics.append(
                    {
                        "kind": "sst.stage_hook_invalid_result",
                        "stage": stage,
                        "provider_id": provider_id,
                        "result_type": type(result).__name__,
                    }
                )
                continue
            metrics = result.pop("metrics", None)
            if isinstance(metrics, dict) and metrics:
                diagnostics.append(
                    {
                        "kind": "sst.stage_hook_metrics",
                        "stage": stage,
                        "provider_id": provider_id,
                        "metrics": metrics,
                    }
                )
            diag_items = result.pop("diagnostics", None)
            if isinstance(diag_items, list):
                for item in diag_items:
                    if isinstance(item, dict):
                        diagnostics.append(
                            {
                                "kind": "sst.stage_hook_diag",
                                "stage": stage,
                                "provider_id": provider_id,
                                "detail": item,
                            }
                        )
            prepared = _prepare_stage_result(
                stage=stage,
                result=result,
                provider_id=provider_id,
                run_id=run_id,
                record_id=record_id,
                frame_bbox=frame_bbox,
                frame_width=frame_width,
                frame_height=frame_height,
                diagnostics=diagnostics,
            )
            prepared = _filter_canonical_keys(prepared, stage=stage, provider_id=provider_id, diagnostics=diagnostics)
            if not prepared:
                continue
            _merge_payload(payload, prepared, provider_id=provider_id, stage=stage, diagnostics=diagnostics)
            applied.append(provider_id)
            if not policy.get("fanout", True):
                break
        if applied:
            diagnostics.append({"kind": "sst.stage_hook", "stage": stage, "providers": applied})
        return payload

    def _vlm_tokens(
        self,
        frame_width: int,
        frame_height: int,
        frame_bytes: bytes,
        allow_vlm: bool,
        should_abort: ShouldAbortFn | None,
        deadline_ts: float | None,
        *,
        run_id: str | None = None,
        source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not allow_vlm or self._vlm is None:
            return []

        def _provider_priority(provider_id: str) -> int:
            low = str(provider_id or "").strip().casefold()
            score = 0
            if "vllm" in low or "localhost" in low or "openai" in low:
                score += 60
            if "transformers" in low or "qwen" in low or "internvl" in low or "mai" in low:
                score += 20
            if "stub" in low or "basic" in low or "toy" in low or "heuristic" in low:
                score -= 40
            return score

        providers = capability_providers(self._vlm, "vision.extractor")
        providers.sort(key=lambda pair: (-_provider_priority(pair[0]), str(pair[0])))

        tokens: list[dict[str, Any]] = []
        for provider_id, provider in providers:
            if should_abort and should_abort():
                break
            if deadline_ts is not None and time.time() >= deadline_ts:
                break
            text = ""
            try:
                text = extract_text_payload(provider.extract(frame_bytes))
            except Exception:
                text = ""
            if not text:
                text = self._cached_vlm_text(
                    provider_id=str(provider_id),
                    run_id=run_id,
                    source_id=source_id,
                )
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

    def _cached_vlm_text(self, *, provider_id: str, run_id: str | None, source_id: str | None) -> str:
        if self._metadata is None:
            return ""
        if not run_id or not source_id:
            return ""
        try:
            record_id = derived_text_record_id(
                kind="vlm",
                run_id=str(run_id),
                provider_id=str(provider_id),
                source_id=str(source_id),
                config=self._config if isinstance(self._config, dict) else {},
            )
            payload = self._metadata.get(record_id)
            if not isinstance(payload, dict):
                return ""
            text = payload.get("text")
            if not text:
                text = payload.get("text_normalized")
            return str(text or "")
        except Exception:
            return ""

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
        post_fn = self._post_index_text
        self._persistence = SSTPersistence(
            metadata=self._metadata,
            event_builder=self._events,
            index_text=index_fn,
            post_index=post_fn,
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

    def _post_index_text(self, doc_id: str, text: str) -> None:
        """Optional post-index fanout (late interaction, extra embeddings, etc)."""
        if not text:
            return
        cap = self._post_index
        if cap is None:
            return
        for provider_id, provider in capability_providers(cap, "index.postprocess"):
            _ = provider_id
            try:
                if hasattr(provider, "process_doc"):
                    provider.process_doc(doc_id, text)
                elif callable(provider):
                    provider(doc_id, text)
            except Exception as exc:
                self._log(f"sst.post_index_error[{doc_id}]: {exc}")

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


def _provider_supports_stage(provider: Any, stage: str, diagnostics: list[dict[str, Any]], *, provider_id: str) -> bool:
    stages_fn = getattr(provider, "stages", None)
    if not callable(stages_fn):
        return True
    try:
        stages = stages_fn()
    except Exception as exc:
        diagnostics.append(
            {"kind": "sst.stage_hook_stage_error", "stage": stage, "provider_id": provider_id, "error": str(exc)}
        )
        return False
    if not isinstance(stages, (list, tuple, set)):
        diagnostics.append(
            {
                "kind": "sst.stage_hook_stage_invalid",
                "stage": stage,
                "provider_id": provider_id,
                "stages_type": type(stages).__name__,
            }
        )
        return False
    allowed = {str(item).strip() for item in stages if str(item).strip()}
    if not allowed:
        return True
    return stage in allowed


def _tokens_from_payload(
    payload: dict[str, Any],
    *,
    fallback: list[dict[str, Any]],
    frame_width: int,
    frame_height: int,
    diagnostics: list[dict[str, Any]],
    stage: str,
    provider_id_hint: str,
) -> list[dict[str, Any]]:
    raw = payload.get("tokens", fallback)
    if not isinstance(raw, list):
        diagnostics.append(
            {
                "kind": "sst.stage_hook_invalid_tokens",
                "stage": stage,
                "provider_id": provider_id_hint,
                "tokens_type": type(raw).__name__,
            }
        )
        raw = fallback
    tokens = _sanitize_tokens(
        raw,
        frame_width=frame_width,
        frame_height=frame_height,
        diagnostics=diagnostics,
        stage=stage,
        provider_id_hint=provider_id_hint,
    )
    payload["tokens"] = tokens
    return tokens


def _collect_extra_docs(
    payload: dict[str, Any],
    *,
    diagnostics: list[dict[str, Any]],
    stage: str,
    fallback: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    raw = payload.get("extra_docs", fallback or [])
    if not isinstance(raw, list):
        diagnostics.append(
            {"kind": "sst.stage_hook_invalid_extra_docs", "stage": stage, "docs_type": type(raw).__name__}
        )
        raw = fallback or []
    docs = [doc for doc in raw if isinstance(doc, dict)]
    dropped = len(raw) - len(docs)
    if dropped:
        diagnostics.append({"kind": "sst.stage_hook_extra_docs_dropped", "stage": stage, "dropped": dropped})
    return docs


def _redact_extra_docs(extra_docs: list[dict[str, Any]], *, enabled: bool) -> tuple[list[dict[str, Any]], int]:
    if not enabled:
        return list(extra_docs), 0
    redactions = 0
    out: list[dict[str, Any]] = []
    for doc in extra_docs:
        if not isinstance(doc, dict):
            continue
        text = str(doc.get("text", ""))
        red_text, count_text = redact_text(text, enabled=enabled)
        meta = doc.get("meta", {})
        red_meta, count_meta = redact_value(meta, enabled=enabled)
        redactions += int(count_text) + int(count_meta)
        next_doc = dict(doc)
        next_doc["text"] = red_text
        next_doc["meta"] = red_meta if isinstance(red_meta, dict) else {}
        out.append(next_doc)
    return out, redactions


def _prepare_stage_result(
    *,
    stage: str,
    result: dict[str, Any],
    provider_id: str,
    run_id: str,
    record_id: str,
    frame_bbox: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    out = dict(result)
    if "tokens" in out:
        tokens_raw = out.get("tokens")
        if isinstance(tokens_raw, list):
            sanitized_tokens = _sanitize_tokens(
                tokens_raw,
                frame_width=frame_width,
                frame_height=frame_height,
                diagnostics=diagnostics,
                stage=stage,
                provider_id_hint=provider_id,
            )
            out["tokens"] = sanitized_tokens
            if "tokens_raw" not in out:
                out["tokens_raw"] = list(sanitized_tokens)
        else:
            diagnostics.append(
                {
                    "kind": "sst.stage_hook_invalid_tokens",
                    "stage": stage,
                    "provider_id": provider_id,
                    "tokens_type": type(tokens_raw).__name__,
                }
            )
            out.pop("tokens", None)
    if "extra_docs" in out:
        docs_raw = out.get("extra_docs")
        if isinstance(docs_raw, list):
            out["extra_docs"] = _sanitize_extra_docs(
                docs_raw,
                stage=stage,
                provider_id=provider_id,
                run_id=run_id,
                record_id=record_id,
                frame_bbox=frame_bbox,
                frame_width=frame_width,
                frame_height=frame_height,
                diagnostics=diagnostics,
            )
        else:
            diagnostics.append(
                {
                    "kind": "sst.stage_hook_invalid_extra_docs",
                    "stage": stage,
                    "provider_id": provider_id,
                    "docs_type": type(docs_raw).__name__,
                }
            )
            out.pop("extra_docs", None)
    return out


def _filter_canonical_keys(
    result: dict[str, Any],
    *,
    stage: str,
    provider_id: str,
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_allow = {
        "preprocess.normalize": {"image_rgb"},
        "preprocess.tile": {"patches"},
    }.get(stage, set())
    out: dict[str, Any] = {}
    for key, value in result.items():
        key_str = str(key)
        if key_str in raw_allow:
            out[key_str] = value
            continue
        try:
            canonical_value, dropped = _canonicalize_value(value)
        except CanonicalJSONError as exc:
            diagnostics.append(
                {
                    "kind": "sst.stage_hook_noncanonical",
                    "stage": stage,
                    "provider_id": provider_id,
                    "key": key_str,
                    "error": str(exc),
                }
            )
            continue
        if dropped:
            diagnostics.append(
                {
                    "kind": "sst.stage_hook_noncanonical_dropped",
                    "stage": stage,
                    "provider_id": provider_id,
                    "key": key_str,
                    "dropped": dropped,
                }
            )
        out[key_str] = canonical_value
    return out


def _canonicalize_value(value: Any) -> tuple[Any, int]:
    dropped = 0
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key in sorted(value.keys(), key=lambda k: str(k)):
            try:
                canonical_value, sub_dropped = _canonicalize_value(value[key])
            except CanonicalJSONError:
                dropped += 1
                continue
            dropped += sub_dropped
            out[str(key)] = canonical_value
        return out, dropped
    if isinstance(value, list):
        out_list: list[Any] = []
        for item in value:
            try:
                canonical_item, sub_dropped = _canonicalize_value(item)
            except CanonicalJSONError:
                dropped += 1
                continue
            dropped += sub_dropped
            out_list.append(canonical_item)
        return out_list, dropped
    if isinstance(value, tuple):
        out_items: list[Any] = []
        for item in value:
            try:
                canonical_item, sub_dropped = _canonicalize_value(item)
            except CanonicalJSONError:
                dropped += 1
                continue
            dropped += sub_dropped
            out_items.append(canonical_item)
        return tuple(out_items), dropped
    if isinstance(value, float):
        raise CanonicalJSONError("Floats are not permitted in canonical JSON")
    try:
        canonical_dumps(value)
    except Exception as exc:
        raise CanonicalJSONError(str(exc)) from exc
    return value, dropped


def _sanitize_tokens(
    tokens: list[Any],
    *,
    frame_width: int,
    frame_height: int,
    diagnostics: list[dict[str, Any]],
    stage: str,
    provider_id_hint: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dropped = 0
    invalid_text = 0
    invalid_bbox = 0
    provider_default = provider_id_hint or "stage_hook"
    for idx, token in enumerate(tokens):
        if not isinstance(token, dict):
            dropped += 1
            continue
        text_raw = str(token.get("text", ""))
        norm = norm_text(str(token.get("norm_text", text_raw)))
        bbox_raw = token.get("bbox")
        bbox = _coerce_bbox(bbox_raw, frame_width=frame_width, frame_height=frame_height)
        flags_raw = token.get("flags", {})
        flags: dict[str, Any] = dict(flags_raw) if isinstance(flags_raw, dict) else {}
        if not norm:
            invalid_text += 1
            flags["invalid_text"] = True
        if bbox is None:
            invalid_bbox += 1
            flags["bbox_invalid"] = True
            bbox = (0, 0, 0, 0)
        provider_id = str(token.get("provider_id") or provider_default)
        patch_id = str(token.get("patch_id") or "full_frame")
        confidence_bp = _coerce_bp(token.get("confidence_bp", token.get("confidence", 0)))
        token_id = str(token.get("token_id") or "").strip()
        if not token_id:
            seed = {
                "text": norm,
                "bbox": bbox,
                "provider_id": provider_id,
                "patch_id": patch_id,
            }
            try:
                digest = hash_canonical(seed)[:12]
            except Exception:
                digest = hash_canonical({"text": norm, "provider_id": provider_id})[:12]
            token_id = encode_record_id_component(f"hook-{provider_id}-{digest}")
        monospace_likely = bool(flags.get("monospace_likely", False))
        is_number = bool(flags.get("is_number", False))
        source = str(token.get("source") or "stage_hook")
        next_token: dict[str, Any] = {
            "token_id": token_id,
            "text": text_raw,
            "norm_text": norm,
            "bbox": bbox,
            "confidence_bp": confidence_bp,
            "source": source,
            "flags": {
                "monospace_likely": monospace_likely,
                "is_number": is_number,
                "invalid_text": bool(flags.get("invalid_text", False)),
                "bbox_invalid": bool(flags.get("bbox_invalid", False)),
                "low_confidence": bool(flags.get("low_confidence", False)),
            },
            "provider_id": provider_id,
            "patch_id": patch_id,
        }
        line_id = token.get("line_id")
        if line_id:
            next_token["line_id"] = str(line_id)
        block_id = token.get("block_id")
        if block_id:
            next_token["block_id"] = str(block_id)
        out.append(next_token)
    if dropped:
        diagnostics.append(
            {
                "kind": "sst.stage_hook_tokens_sanitized",
                "stage": stage,
                "provider_id": provider_id_hint,
                "dropped": dropped,
                "kept": len(out),
            }
        )
    if invalid_text or invalid_bbox:
        diagnostics.append(
            {
                "kind": "sst.stage_hook_tokens_invalid",
                "stage": stage,
                "provider_id": provider_id_hint,
                "invalid_text": invalid_text,
                "invalid_bbox": invalid_bbox,
            }
        )
    return out


def _sanitize_extra_docs(
    docs: list[Any],
    *,
    stage: str,
    provider_id: str,
    run_id: str,
    record_id: str,
    frame_bbox: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dropped = 0
    for doc in docs:
        if not isinstance(doc, dict):
            dropped += 1
            continue
        text = str(doc.get("text", "")).strip()
        if not text:
            dropped += 1
            continue
        doc_kind = str(doc.get("doc_kind", "extra") or "extra").strip() or "extra"
        meta = doc.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        provider_value = str(doc.get("provider_id") or provider_id)
        stage_value = str(doc.get("stage") or stage)
        confidence_bp = _coerce_bp(doc.get("confidence_bp", 8000))
        bboxes = _sanitize_bboxes(doc.get("bboxes") or doc.get("bbox"), frame_bbox, frame_width, frame_height)
        doc_id = str(doc.get("doc_id", "")).strip()
        if not doc_id:
            meta_hash = ""
            try:
                meta_hash = hash_canonical(meta)[:8]
            except Exception:
                meta_hash = ""
            seed = {
                "text": text,
                "doc_kind": doc_kind,
                "provider_id": provider_value,
                "stage": stage_value,
                "record_id": record_id,
                "meta_hash": meta_hash,
            }
            try:
                digest = hash_canonical(seed)[:16]
            except Exception:
                digest = hash_canonical({"text": text, "provider_id": provider_value})[:16]
            component = encode_record_id_component(f"{provider_value}-{digest}")
            doc_id = f"{run_id}/derived.sst.text/extra/{component}"
        out.append(
            {
                "doc_id": doc_id,
                "text": text,
                "doc_kind": doc_kind,
                "meta": meta,
                "provider_id": provider_value,
                "stage": stage_value,
                "confidence_bp": confidence_bp,
                "bboxes": bboxes,
            }
        )
    if dropped:
        diagnostics.append(
            {
                "kind": "sst.stage_hook_extra_docs_sanitized",
                "stage": stage,
                "provider_id": provider_id,
                "dropped": dropped,
                "kept": len(out),
            }
        )
    return out


def _coerce_bbox(value: Any, *, frame_width: int, frame_height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1 = int(round(float(value[0])))
        y1 = int(round(float(value[1])))
        x2 = int(round(float(value[2])))
        y2 = int(round(float(value[3])))
    except Exception:
        return None
    return clamp_bbox((x1, y1, x2, y2), width=frame_width, height=frame_height)


def _sanitize_bboxes(
    raw: Any,
    frame_bbox: tuple[int, int, int, int],
    frame_width: int,
    frame_height: int,
) -> tuple[tuple[int, int, int, int], ...]:
    boxes: list[tuple[int, int, int, int]] = []
    if isinstance(raw, (list, tuple)) and raw:
        first = raw[0]
        if isinstance(first, (list, tuple)) and len(first) == 4:
            for item in raw:
                bbox = _coerce_bbox(item, frame_width=frame_width, frame_height=frame_height)
                if bbox is not None:
                    boxes.append(bbox)
        else:
            bbox = _coerce_bbox(raw, frame_width=frame_width, frame_height=frame_height)
            if bbox is not None:
                boxes.append(bbox)
    if not boxes:
        boxes.append(
            clamp_bbox(frame_bbox, width=frame_width, height=frame_height)
        )
    return tuple(boxes)


def _coerce_bp(value: Any) -> int:
    try:
        bp = int(round(float(value)))
    except Exception:
        bp = 0
    if bp < 0:
        return 0
    if bp > 10000:
        return 10000
    return bp


def _merge_payload(
    base: dict[str, Any],
    update: dict[str, Any],
    *,
    provider_id: str,
    stage: str,
    diagnostics: list[dict[str, Any]],
) -> None:
    replace_keys_by_stage: dict[str, set[str]] = {
        "ui.parse": {"element_graph"},
    }
    replace_keys = replace_keys_by_stage.get(stage, set())
    for key, value in update.items():
        if key in replace_keys:
            base[key] = value
            continue
        if key not in base:
            base[key] = value
            continue
        existing = base[key]
        if isinstance(existing, dict) and isinstance(value, dict):
            _merge_payload(existing, value, provider_id=provider_id, stage=stage, diagnostics=diagnostics)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            base[key] = _dedupe_list(existing + value)
            continue
        if existing == value:
            continue
        shadow = _shadow_key(key, base, provider_id)
        base[shadow] = value
        diagnostics.append(
            {
                "kind": "sst.stage_hook_conflict",
                "stage": stage,
                "provider_id": provider_id,
                "key": key,
                "shadow_key": shadow,
            }
        )


def _shadow_key(key: str, base: dict[str, Any], provider_id: str) -> str:
    suffix = provider_id.replace(".", "_")
    candidate = f"{key}__{suffix}"
    if candidate not in base:
        return candidate
    idx = 2
    while True:
        next_candidate = f"{candidate}_{idx}"
        if next_candidate not in base:
            return next_candidate
        idx += 1


def _dedupe_list(items: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = _canonical_key(item)
        if key is None:
            out.append(item)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _canonical_key(item: Any) -> str | None:
    try:
        return canonical_dumps(item)
    except Exception:
        return None


def _sst_config(config: dict[str, Any]) -> dict[str, Any]:
    processing = config.get("processing", {}) if isinstance(config, dict) else {}
    sst = processing.get("sst", {}) if isinstance(processing, dict) else {}
    storage_cfg = config.get("storage", {}) if isinstance(config, dict) else {}
    raw_first_local = bool(storage_cfg.get("raw_first_local", True))

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

    stage_cfg = sst.get("stage_providers", {})
    if not isinstance(stage_cfg, dict):
        stage_cfg = {}

    def _stage_policy(stage: str) -> dict[str, Any]:
        raw = stage_cfg.get(stage, {})
        policy = dict(_STAGE_POLICY_DEFAULT)
        if isinstance(raw, dict):
            policy.update(raw)
        provider_ids = raw.get("provider_ids", []) if isinstance(raw, dict) else []
        if not isinstance(provider_ids, (list, tuple)):
            provider_ids = []
        policy["provider_ids"] = tuple(str(pid) for pid in provider_ids if str(pid))
        policy["fanout"] = bool(policy.get("fanout", True))
        policy["enabled"] = bool(policy.get("enabled", True))
        try:
            max_providers = int(policy.get("max_providers", 0) or 0)
        except Exception:
            max_providers = 0
        policy["max_providers"] = max(0, max_providers)
        return policy

    stages = set(_STAGE_NAMES) | {str(stage) for stage in stage_cfg.keys()}
    stage_policies = {stage: _stage_policy(stage) for stage in sorted(stages)}
    if raw_first_local:
        compliance_policy = stage_policies.get("compliance.redact")
        if isinstance(compliance_policy, dict):
            compliance_policy["enabled"] = False

    ui_parse_cfg = sst.get("ui_parse", {}) if isinstance(sst.get("ui_parse", {}), dict) else {}
    ui_parse = {
        "enabled": bool(ui_parse_cfg.get("enabled", True)),
        "mode": str(ui_parse_cfg.get("mode", "detector")),
        "max_providers": int(ui_parse_cfg.get("max_providers", 1) or 0),
        "fallback_detector": bool(ui_parse_cfg.get("fallback_detector", True)),
    }

    cursor_cfg = sst.get("cursor_detect", {}) if isinstance(sst.get("cursor_detect", {}), dict) else {}
    scales = cursor_cfg.get("scales", [0.75, 1.0, 1.25])
    if not isinstance(scales, (list, tuple)):
        scales = [1.0]

    def _float_bp(value: Any, default: float) -> int:
        try:
            val = float(value)
        except Exception:
            val = float(default)
        if val > 1.5:
            return int(round(val))
        return int(round(val * 10000))

    cursor_detect = {
        "enabled": bool(cursor_cfg.get("enabled", False)),
        "threshold_bp": _float_bp(cursor_cfg.get("threshold", 0.65), 0.65),
        "stride_px": int(cursor_cfg.get("stride_px", 4) or 0),
        "downscale_bp": _float_bp(cursor_cfg.get("downscale", 0.5), 0.5),
        "scales_bp": tuple(_float_bp(scale, 1.0) for scale in scales),
    }

    temporal_cfg = sst.get("temporal_segment", {}) if isinstance(sst.get("temporal_segment", {}), dict) else {}
    temporal_segment = {"mode": str(temporal_cfg.get("mode", "shadow"))}

    persist_cfg = sst.get("persist", {}) if isinstance(sst.get("persist", {}), dict) else {}
    persist = {"mode": str(persist_cfg.get("mode", "shadow"))}

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
        "tile_refine_enabled": _bool("tile_refine_enabled", False),
        "tile_refine_low_conf_bp": _int("tile_refine_low_conf_bp", 6500),
        "tile_refine_padding_px": _int("tile_refine_padding_px", 24),
        "tile_refine_max_patches": _int("tile_refine_max_patches", 12),
        "tile_refine_cluster_gap_px": _int("tile_refine_cluster_gap_px", 48),
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
        "code_detect_caret": _bool("code_detect_caret", False),
        "code_detect_selection": _bool("code_detect_selection", False),
        "chart_min_ticks": _int("chart_min_ticks", 2),
        "delta_bbox_shift_px": _int("delta_bbox_shift_px", 24),
        "delta_table_match_iou_bp": _int("delta_table_match_iou_bp", 3000),
        "redact_enabled": _bool("redact_enabled", True) and not raw_first_local,
        "redact_denylist": tuple(str(x) for x in denylist if x),
        "stage_providers": stage_policies,
        "ui_parse": ui_parse,
        "cursor_detect": cursor_detect,
        "temporal_segment": temporal_segment,
        "persist": persist,
        "schema_version": _int("schema_version", 1),
    }


def _should_heavy(cfg: dict[str, Any], decision: SegmentDecision, should_abort: ShouldAbortFn | None, deadline_ts: float | None) -> bool:
    if cfg["heavy_always"]:
        return True
    if should_abort and should_abort():
        return False
    if deadline_ts is not None and time.time() >= deadline_ts:
        return False
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


def _layout_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for token in tokens:
        if not token.get("norm_text"):
            continue
        flags = token.get("flags") if isinstance(token.get("flags"), dict) else {}
        if isinstance(flags, dict) and flags.get("bbox_invalid", False):
            continue
        out.append(token)
    return out


def _merge_token_lists(base: list[dict[str, Any]], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {t.get("token_id") for t in base if t.get("token_id")}
    out = list(base)
    for token in extra:
        tid = token.get("token_id")
        if tid and tid in seen:
            continue
        if tid:
            seen.add(tid)
        out.append(token)
    return out
