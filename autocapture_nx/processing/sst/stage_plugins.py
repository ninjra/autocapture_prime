"""SST stage plugin implementations derived from the SST plugin suite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

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
from .plugin_base import PluginInput, PluginMeta, PluginOutput, RunContext
from .segment import decide_boundary
from .state import build_state
from .utils import clamp_bbox, hash_canonical, sha256_bytes
from .pipeline import _sst_config, _stable_tokens

try:  # pragma: no cover - optional guard
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - optional guard
    Image = None
    ImageOps = None


@dataclass(frozen=True)
class _CursorTemplate:
    name: str
    mask: tuple[str, ...]

    @property
    def width(self) -> int:
        return len(self.mask[0]) if self.mask else 0

    @property
    def height(self) -> int:
        return len(self.mask)


_CURSOR_TEMPLATES: tuple[_CursorTemplate, ...] = (
    _CursorTemplate(
        "arrow",
        (
            "100000000000",
            "110000000000",
            "111000000000",
            "111100000000",
            "111110000000",
            "111111000000",
            "111111100000",
            "111111110000",
            "111111111000",
            "111111111100",
            "111111111110",
            "111111111111",
            "111111110000",
            "111011100000",
            "110001100000",
            "100000100000",
        ),
    ),
    _CursorTemplate(
        "ibeam",
        (
            "00111100",
            "00111100",
            "00011000",
            "00011000",
            "00011000",
            "00011000",
            "00011000",
            "00011000",
            "00011000",
            "00111100",
            "00111100",
        ),
    ),
    _CursorTemplate(
        "hand",
        (
            "00111000",
            "01111100",
            "11111110",
            "11111110",
            "11111110",
            "11111110",
            "11111110",
            "11111110",
            "11111110",
            "01111100",
            "00111000",
        ),
    ),
    _CursorTemplate(
        "resize",
        (
            "1000001",
            "1100011",
            "0111110",
            "0011100",
            "0011100",
            "0111110",
            "1100011",
            "1000001",
        ),
    ),
)


class SSTStagePluginBase(PluginBase):
    meta: PluginMeta
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    stage_names: tuple[str, ...] = ()

    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        self._config = context.config if isinstance(context.config, dict) else {}
        self._sst_cfg = _sst_config(self._config)

    def capabilities(self) -> dict[str, Any]:
        return {"processing.stage.hooks": self}

    def stages(self) -> list[str]:
        return list(self.stage_names)

    def run_stage(self, stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if stage not in self.stage_names:
            return None
        items = dict(payload)
        ctx = RunContext(
            run_id=str(items.get("run_id") or "run"),
            ts_ms=int(items.get("ts_ms") or 0),
            config=self._config,
            stores=self._build_stores(),
            logger=self.context.logger,
        )
        output = self._run_safe(PluginInput(items=items), ctx)
        result: dict[str, Any] = {}
        if output.items:
            if self.provides:
                allowed = set(self.provides)
                filtered = {key: value for key, value in output.items.items() if key in allowed}
                result.update(filtered)
            else:
                result.update(output.items)
        if output.metrics:
            result["metrics"] = _quantize_metrics(output.metrics)
        if output.diagnostics:
            result["diagnostics"] = list(output.diagnostics)
        return result

    def _run_safe(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        missing = [key for key in self.requires if key not in inp.items]
        diagnostics: list[dict[str, Any]] = []
        if missing:
            diagnostics.append(
                {
                    "kind": "sst.plugin_missing_inputs",
                    "plugin": self.meta.id,
                    "missing": tuple(missing),
                }
            )
            return PluginOutput(items={}, metrics={}, diagnostics=diagnostics)
        return self.run(inp, ctx)

    def _build_stores(self) -> dict[str, Any]:
        def _cap(name: str) -> Any | None:
            try:
                return self.context.get_capability(name)
            except Exception:
                return None

        return {
            "metadata": _cap("storage.metadata"),
            "event_builder": _cap("event.builder"),
            "ocr": _cap("ocr.engine"),
            "vlm": _cap("vision.extractor"),
        }

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:  # pragma: no cover - interface
        ctx.logger(
            f"sst.plugin.noop: {self.meta.id} run not implemented for stages {self.stage_names or ()}"
        )
        return PluginOutput(
            items={},
            metrics={},
            diagnostics=[
                {
                    "kind": "sst.plugin_noop",
                    "plugin": self.meta.id,
                    "stages": list(self.stage_names or ()),
                }
            ],
        )


class PreprocessNormalizePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="preprocess.normalize", version="0.1.0")
    provides = ("image_rgb", "image_sha256", "phash", "width", "height")
    stage_names = ("preprocess.normalize",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        image_rgb = items.get("image_rgb")
        width = items.get("width")
        height = items.get("height")
        image_sha256 = items.get("image_sha256")
        phash = items.get("phash")
        metrics: dict[str, float] = {}
        diagnostics: list[dict[str, Any]] = []

        if image_rgb is not None and width is None and hasattr(image_rgb, "size"):
            try:
                width, height = image_rgb.size
            except Exception:
                width = None
                height = None

        needs_compute = image_rgb is None or not phash or not image_sha256 or not width or not height
        if needs_compute:
            image_bytes = items.get("image_bytes") or items.get("frame_bytes")
            if not isinstance(image_bytes, (bytes, bytearray)):
                diagnostics.append({"kind": "sst.normalize_missing_bytes", "plugin": self.meta.id})
                return PluginOutput(items={}, metrics=metrics, diagnostics=diagnostics)
            normalized = normalize_image(
                bytes(image_bytes),
                strip_alpha=bool(self._sst_cfg["strip_alpha"]),
                phash_size=int(self._sst_cfg["phash_size"]),
                phash_downscale=int(self._sst_cfg["phash_downscale"]),
            )
            image_rgb = normalized.image_rgb
            width = normalized.width
            height = normalized.height
            image_sha256 = normalized.image_sha256
            phash = normalized.phash
        else:
            if not image_sha256:
                image_bytes = items.get("image_bytes") or items.get("frame_bytes")
                if isinstance(image_bytes, (bytes, bytearray)):
                    image_sha256 = sha256_bytes(bytes(image_bytes))
            if not phash:
                diagnostics.append({"kind": "sst.normalize_missing_phash", "plugin": self.meta.id})

        width_val = int(width or 0)
        height_val = int(height or 0)
        if width_val <= 0 or height_val <= 0:
            diagnostics.append({"kind": "sst.normalize_invalid_dims", "plugin": self.meta.id})
        if not isinstance(phash, str) or len(phash) != 64:
            diagnostics.append({"kind": "sst.normalize_invalid_phash", "plugin": self.meta.id})

        metrics["normalize.width"] = float(width_val)
        metrics["normalize.height"] = float(height_val)
        out: dict[str, Any] = {
            "image_rgb": image_rgb,
            "image_sha256": str(image_sha256 or ""),
            "phash": str(phash or ""),
            "width": width_val,
            "height": height_val,
        }
        return PluginOutput(items=out, metrics=metrics, diagnostics=diagnostics)


class PreprocessTilePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="preprocess.tile", version="0.1.0")
    provides = ("patches",)
    stage_names = ("preprocess.tile",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        image_rgb = items.get("image_rgb")
        if image_rgb is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.tile_missing_image", "plugin": self.meta.id}])

        patches = items.get("patches") if isinstance(items.get("patches"), list) else None
        if patches is None:
            tokens = _tokens_from_items(items)
            focus_tokens = tokens if self._sst_cfg.get("tile_refine_enabled") else None
            patches = tile_image(
                image_rgb,
                tile_max_px=int(self._sst_cfg["tile_max_px"]),
                overlap_px=int(self._sst_cfg["tile_overlap_px"]),
                add_full_frame=bool(self._sst_cfg["tile_add_full_frame"]),
                focus_tokens=focus_tokens,
                focus_conf_bp=int(self._sst_cfg.get("tile_refine_low_conf_bp", 0) or 0),
                focus_padding_px=int(self._sst_cfg.get("tile_refine_padding_px", 24) or 0),
                focus_max_patches=int(self._sst_cfg.get("tile_refine_max_patches", 0) or 0),
                focus_cluster_gap_px=int(self._sst_cfg.get("tile_refine_cluster_gap_px", 48) or 0),
            )
        sorted_patches = _sorted_patches(patches)
        diagnostics: list[dict[str, Any]] = []
        if not _patch_ids_unique(sorted_patches):
            diagnostics.append({"kind": "sst.tile_duplicate_patch_id", "plugin": self.meta.id})
        if not bool(self._sst_cfg.get("tile_add_full_frame", True)):
            if not _patches_cover_frame(sorted_patches, image_rgb):
                diagnostics.append({"kind": "sst.tile_coverage_incomplete", "plugin": self.meta.id})
        return PluginOutput(items={"patches": sorted_patches}, metrics={}, diagnostics=diagnostics)


class OcrOnnxPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="ocr.onnx", version="0.1.0")
    provides = ("tokens", "tokens_raw")
    stage_names = ("ocr.onnx",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        diagnostics: list[dict[str, Any]] = []
        metrics: dict[str, float] = {}
        tokens = _tokens_from_items(items)
        tokens_raw: list[dict[str, Any]] = []
        if tokens:
            sorted_tokens = _sorted_tokens(tokens)
            tokens_raw = list(sorted_tokens)
        else:
            patches_raw = items.get("patches")
            patches = cast(list[dict[str, Any]], list(patches_raw)) if isinstance(patches_raw, list) else []
            frame_width = int(items.get("frame_width") or 0)
            frame_height = int(items.get("frame_height") or 0)
            allow_ocr = bool(items.get("allow_ocr", True))
            filtered_tokens, ocr_diag, raw_tokens = run_ocr_tokens(
                patches=patches,
                ocr_capability=ctx.stores.get("ocr"),
                frame_width=frame_width,
                frame_height=frame_height,
                min_conf_bp=int(self._sst_cfg["ocr_min_conf_bp"]),
                nms_iou_bp=int(self._sst_cfg["ocr_nms_iou_bp"]),
                max_tokens=int(self._sst_cfg["ocr_max_tokens"]),
                max_patches=int(self._sst_cfg["ocr_max_patches"]),
                allow_ocr=allow_ocr,
                should_abort=None,
                deadline_ts=None,
            )
            diagnostics.extend(ocr_diag.items)
            sorted_tokens = _sorted_tokens(filtered_tokens)
            tokens_raw = list(raw_tokens)

        if sorted_tokens:
            avg_conf = sum(int(t.get("confidence_bp", 0)) for t in sorted_tokens) / (10000.0 * len(sorted_tokens))
            metrics["ocr.tokens"] = float(len(sorted_tokens))
            metrics["ocr.avg_conf"] = float(avg_conf)
        return PluginOutput(
            items={
                "tokens": sorted_tokens,
                "text_tokens": sorted_tokens,
                "tokens_raw": tokens_raw,
                "text_tokens_raw": tokens_raw,
            },
            metrics=metrics,
            diagnostics=diagnostics,
        )


class LayoutAssemblePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="layout.assemble", version="0.1.0")
    requires = ("tokens",)
    provides = ("text_lines", "text_blocks")
    stage_names = ("layout.assemble",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        tokens = _tokens_from_items(inp.items)
        if not tokens:
            return PluginOutput(items={"text_lines": [], "text_blocks": []}, metrics={}, diagnostics=[{"kind": "sst.layout_missing_tokens", "plugin": self.meta.id}])
        text_lines, text_blocks = assemble_layout(
            tokens,
            line_y_threshold_px=int(self._sst_cfg["layout_line_y_px"]),
            block_gap_px=int(self._sst_cfg["layout_block_gap_px"]),
            align_tolerance_px=int(self._sst_cfg["layout_align_tol_px"]),
        )
        return PluginOutput(items={"text_lines": text_lines, "text_blocks": text_blocks}, metrics={}, diagnostics=[])


class ExtractTablePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="extract.table", version="0.1.0")
    requires = ("tokens",)
    provides = ("tables",)
    stage_names = ("extract.table",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        tokens = _tokens_from_items(items)
        tables = extract_tables(
            tokens=tokens,
            state_id="pending",
            min_rows=int(self._sst_cfg["table_min_rows"]),
            min_cols=int(self._sst_cfg["table_min_cols"]),
            max_cells=int(self._sst_cfg["table_max_cells"]),
            row_gap_px=int(self._sst_cfg["table_row_gap_px"]),
            col_gap_px=int(self._sst_cfg["table_col_gap_px"]),
            element_graph=items.get("element_graph"),
            frame_bbox=items.get("frame_bbox"),
        )
        cells = sum(len(t.get("cells", ())) for t in tables)
        metrics = {"table.count": float(len(tables)), "table.cells": float(cells)}
        return PluginOutput(items={"tables": tables}, metrics=metrics, diagnostics=[])


class ExtractSpreadsheetPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="extract.spreadsheet", version="0.1.0")
    requires = ("tokens",)
    provides = ("spreadsheets",)
    stage_names = ("extract.spreadsheet",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        tokens = _tokens_from_items(inp.items)
        tables_raw = inp.items.get("tables")
        tables = cast(list[dict[str, Any]], list(tables_raw)) if isinstance(tables_raw, list) else []
        spreadsheets = extract_spreadsheets(
            tokens=tokens,
            tables=tables,
            state_id="pending",
            header_scan_rows=int(self._sst_cfg["sheet_header_scan_rows"]),
        )
        return PluginOutput(items={"spreadsheets": spreadsheets}, metrics={}, diagnostics=[])


class ExtractCodePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="extract.code", version="0.1.0")
    requires = ("tokens",)
    provides = ("code_blocks",)
    stage_names = ("extract.code",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        tokens = _tokens_from_items(items)
        if not tokens:
            return PluginOutput(items={"code_blocks": []}, metrics={}, diagnostics=[])
        image_rgb = items.get("image_rgb")
        text_lines_raw = items.get("text_lines")
        text_lines = cast(list[dict[str, Any]], list(text_lines_raw)) if isinstance(text_lines_raw, list) else []
        code_blocks = extract_code_blocks(
            tokens=tokens,
            text_lines=text_lines,
            state_id="pending",
            min_keywords=int(self._sst_cfg["code_min_keywords"]),
            image_rgb=image_rgb,
            detect_caret=bool(self._sst_cfg.get("code_detect_caret", False)),
            detect_selection=bool(self._sst_cfg.get("code_detect_selection", False)),
        )
        return PluginOutput(items={"code_blocks": code_blocks}, metrics={}, diagnostics=[])


class ExtractChartPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="extract.chart", version="0.1.0")
    requires = ("tokens",)
    provides = ("charts",)
    stage_names = ("extract.chart",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        tokens = _tokens_from_items(inp.items)
        charts = extract_charts(
            tokens=tokens,
            state_id="pending",
            min_ticks=int(self._sst_cfg["chart_min_ticks"]),
        )
        return PluginOutput(items={"charts": charts}, metrics={}, diagnostics=[])


class UiParsePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="ui.parse", version="0.1.0")
    requires = ("tokens",)
    provides = ("element_graph",)
    stage_names = ("ui.parse",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        tokens = _tokens_from_items(items)
        diagnostics: list[dict[str, Any]] = []
        frame_bbox = items.get("frame_bbox")
        if not frame_bbox:
            diagnostics.append({"kind": "sst.ui_missing_bbox", "plugin": self.meta.id})
            empty = {"state_id": "pending", "elements": tuple(), "edges": tuple()}
            return PluginOutput(items={"element_graph": empty, "element_graph_raw": empty}, metrics={}, diagnostics=diagnostics)
        raw_sst = _raw_sst_config(ctx.config)
        ui_cfg = raw_sst.get("ui_parse", {}) if isinstance(raw_sst, dict) else {}
        if not isinstance(ui_cfg, dict):
            ui_cfg = {}
        mode = str(ui_cfg.get("mode", "detector"))
        enabled = bool(ui_cfg.get("enabled", True))
        max_providers = int(ui_cfg.get("max_providers", 1))
        fallback_detector = bool(ui_cfg.get("fallback_detector", True))

        element_graph: dict[str, Any] | None = None
        if enabled and mode == "vlm_json":
            element_graph = _parse_element_graph_from_vlm(
                ctx.stores.get("vlm"),
                items.get("frame_bytes"),
                tokens,
                frame_bbox,
                max_providers=max_providers,
                diagnostics=diagnostics,
            )
        if element_graph is None and enabled and (mode == "detector" or fallback_detector):
            text_blocks_raw = items.get("text_blocks")
            tables_raw = items.get("tables")
            spreadsheets_raw = items.get("spreadsheets")
            code_blocks_raw = items.get("code_blocks")
            charts_raw = items.get("charts")
            text_blocks = cast(list[dict[str, Any]], list(text_blocks_raw)) if isinstance(text_blocks_raw, list) else []
            tables = cast(list[dict[str, Any]], list(tables_raw)) if isinstance(tables_raw, list) else []
            spreadsheets = cast(list[dict[str, Any]], list(spreadsheets_raw)) if isinstance(spreadsheets_raw, list) else []
            code_blocks = cast(list[dict[str, Any]], list(code_blocks_raw)) if isinstance(code_blocks_raw, list) else []
            charts = cast(list[dict[str, Any]], list(charts_raw)) if isinstance(charts_raw, list) else []
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
        if element_graph is None:
            diagnostics.append({"kind": "sst.ui_empty", "plugin": self.meta.id})
            element_graph = {"state_id": "pending", "elements": tuple(), "edges": tuple()}
        elements = element_graph.get("elements") if isinstance(element_graph, dict) else []
        metrics = {"ui.elements": float(len(elements or ())) }
        return PluginOutput(
            items={"element_graph": element_graph, "element_graph_raw": element_graph},
            metrics=metrics,
            diagnostics=diagnostics,
        )


class TrackCursorPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="track.cursor", version="0.1.0")
    provides = ("cursor",)
    stage_names = ("track.cursor",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        cursor = items.get("cursor") if isinstance(items.get("cursor"), dict) else None
        frame_width = int(items.get("frame_width") or 0)
        frame_height = int(items.get("frame_height") or 0)
        if cursor is None:
            record_raw = items.get("record")
            record = cast(dict[str, Any], record_raw) if isinstance(record_raw, dict) else {}
            cursor = track_cursor(record, frame_width, frame_height)
        if cursor is None:
            detect_cfg = _raw_sst_config(ctx.config).get("cursor_detect", {})
            if isinstance(detect_cfg, dict) and bool(detect_cfg.get("enabled", False)):
                cursor = _detect_cursor(items.get("image_rgb"), frame_width, frame_height, detect_cfg)
            else:
                cursor = {"bbox": (0, 0, 0, 0), "type": "unknown", "confidence": 0.0}
        return PluginOutput(items={"cursor": cursor}, metrics={}, diagnostics=[])


class BuildStatePlugin(SSTStagePluginBase):
    meta = PluginMeta(id="build.state", version="0.1.0")
    requires = ("tokens",)
    provides = ("state",)
    stage_names = ("build.state",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        tokens = _tokens_from_items(items)
        element_graph_raw = items.get("element_graph")
        element_graph = cast(dict[str, Any], element_graph_raw) if isinstance(element_graph_raw, dict) else {"state_id": "pending", "elements": tuple(), "edges": tuple()}
        text_lines_raw = items.get("text_lines")
        text_blocks_raw = items.get("text_blocks")
        tables_raw = items.get("tables")
        spreadsheets_raw = items.get("spreadsheets")
        code_blocks_raw = items.get("code_blocks")
        charts_raw = items.get("charts")
        text_lines = cast(list[dict[str, Any]], list(text_lines_raw)) if isinstance(text_lines_raw, list) else []
        text_blocks = cast(list[dict[str, Any]], list(text_blocks_raw)) if isinstance(text_blocks_raw, list) else []
        tables = cast(list[dict[str, Any]], list(tables_raw)) if isinstance(tables_raw, list) else []
        spreadsheets = cast(list[dict[str, Any]], list(spreadsheets_raw)) if isinstance(spreadsheets_raw, list) else []
        code_blocks = cast(list[dict[str, Any]], list(code_blocks_raw)) if isinstance(code_blocks_raw, list) else []
        charts = cast(list[dict[str, Any]], list(charts_raw)) if isinstance(charts_raw, list) else []
        tokens_raw_raw = items.get("tokens_raw")
        tokens_raw = cast(list[dict[str, Any]], tokens_raw_raw) if isinstance(tokens_raw_raw, list) else None
        state = build_state(
            run_id=str(items.get("run_id") or "run"),
            frame_id=str(items.get("record_id") or "frame"),
            ts_ms=int(items.get("ts_ms") or 0),
            phash=str(items.get("phash") or ""),
            image_sha256=str(items.get("image_sha256") or ""),
            frame_index=int(items.get("frame_index") or 0),
            width=int(items.get("frame_width") or 0),
            height=int(items.get("frame_height") or 0),
            tokens=tokens,
            tokens_raw=tokens_raw,
            element_graph=element_graph,
            text_lines=text_lines,
            text_blocks=text_blocks,
            tables=tables,
            spreadsheets=spreadsheets,
            code_blocks=code_blocks,
            charts=charts,
            cursor=items.get("cursor") if isinstance(items.get("cursor"), dict) else None,
            window_title=items.get("window_title"),
        )
        return PluginOutput(items={"state": state}, metrics={}, diagnostics=[])


class MatchIdsPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="match.ids", version="0.1.0")
    requires = ("state",)
    provides = ("state",)
    stage_names = ("match.ids",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        prev_state = items.get("prev_state") if isinstance(items.get("prev_state"), dict) else items.get("state_prev")
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        if state is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.match_missing_state", "plugin": self.meta.id}])
        tracked = match_ids(prev_state if isinstance(prev_state, dict) else None, state)
        return PluginOutput(items={"state": tracked}, metrics={}, diagnostics=[])


class TemporalSegmentPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="temporal.segment", version="0.1.0")
    requires = ("phash",)
    provides = ("boundary", "boundary_reason", "phash_distance", "diff_score_bp", "boundary_override")
    stage_names = ("temporal.segment",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        phash = str(items.get("phash") or "")
        if not phash:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.segment_missing_phash", "plugin": self.meta.id}])
        image_rgb = items.get("image_rgb")
        if image_rgb is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.segment_missing_image", "plugin": self.meta.id}])
        prev_phash = items.get("prev_phash")
        prev_downscaled = items.get("prev_downscaled") if isinstance(items.get("prev_downscaled"), tuple) else None
        cfg = _raw_sst_config(ctx.config).get("temporal_segment", {})
        if not isinstance(cfg, dict):
            cfg = {}
        mode = str(cfg.get("mode", "shadow"))
        decision, downscaled = decide_boundary(
            phash=phash,
            prev_phash=str(prev_phash or "") if prev_phash else None,
            image_rgb=image_rgb,
            downscale_px=int(self._sst_cfg["segment_downscale_px"]),
            prev_downscaled=prev_downscaled,
            d_stable=int(self._sst_cfg["d_stable"]),
            d_boundary=int(self._sst_cfg["d_boundary"]),
            diff_threshold_bp=int(self._sst_cfg["diff_threshold_bp"]),
        )
        out = {
            "boundary": bool(decision.boundary),
            "boundary_reason": str(decision.reason),
            "phash_distance": int(decision.phash_distance),
            "diff_score_bp": int(decision.diff_score_bp),
            "boundary_override": mode == "replace",
            "downscaled": downscaled,
        }
        return PluginOutput(items=out, metrics={}, diagnostics=[])


class BuildDeltaPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="build.delta", version="0.1.0")
    requires = ("state",)
    provides = ("delta_event",)
    stage_names = ("build.delta",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        prev_state = items.get("prev_state") if isinstance(items.get("prev_state"), dict) else items.get("state_prev")
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        if state is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.delta_missing_state", "plugin": self.meta.id}])
        delta_event = build_delta(
            prev_state=prev_state if isinstance(prev_state, dict) else None,
            state=state,
            bbox_shift_px=int(self._sst_cfg["delta_bbox_shift_px"]),
            table_match_iou_bp=int(self._sst_cfg["delta_table_match_iou_bp"]),
        )
        changes = len(delta_event.get("changes", ())) if isinstance(delta_event, dict) else 0
        metrics = {"delta.changes": float(changes)}
        return PluginOutput(items={"delta_event": delta_event}, metrics=metrics, diagnostics=[])


class InferActionPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="infer.action", version="0.1.0")
    provides = ("action_event",)
    stage_names = ("infer.action",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        delta_event = items.get("delta_event") if isinstance(items.get("delta_event"), dict) else None
        prev_state = items.get("prev_state") if isinstance(items.get("prev_state"), dict) else None
        if prev_state is None:
            prev_state = items.get("state_prev") if isinstance(items.get("state_prev"), dict) else None
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        cursor_prev = items.get("cursor_prev") if isinstance(items.get("cursor_prev"), dict) else None
        cursor_curr = items.get("cursor") if isinstance(items.get("cursor"), dict) else None
        action_event = None
        if state is not None:
            action_event = infer_action(
                delta_event=delta_event,
                cursor_prev=cursor_prev,
                cursor_curr=cursor_curr,
                prev_state=prev_state,
                state=state,
            )
        conf_bp = int(action_event.get("confidence_bp", 0)) if isinstance(action_event, dict) else 0
        metrics = {"action.confidence": float(conf_bp) / 10000.0}
        return PluginOutput(items={"action_event": action_event}, metrics=metrics, diagnostics=[])


class ComplianceRedactPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="compliance.redact", version="0.1.0")
    provides = ("state", "delta_event", "action_event")
    stage_names = ("compliance.redact",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        delta_event = items.get("delta_event") if isinstance(items.get("delta_event"), dict) else None
        action_event = items.get("action_event") if isinstance(items.get("action_event"), dict) else None
        if state is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.redact_missing_state", "plugin": self.meta.id}])
        state_redacted, delta_event, action_event, compliance_metrics = redact_artifacts(
            state=state,
            delta_event=delta_event,
            action_event=action_event,
            enabled=bool(self._sst_cfg["redact_enabled"]),
            denylist_app_hints=list(self._sst_cfg["redact_denylist"]),
        )
        metrics = {"redaction.count": float(compliance_metrics.get("redactions", 0))}
        if state_redacted is None:
            diagnostics = [{"kind": "sst.redact_dropped", "plugin": self.meta.id}]
            return PluginOutput(items={}, metrics=metrics, diagnostics=diagnostics)
        return PluginOutput(
            items={"state": state_redacted, "delta_event": delta_event, "action_event": action_event},
            metrics=metrics,
            diagnostics=[],
        )


class PersistPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="persist", version="0.1.0")
    requires = ("state",)
    provides = ("persisted",)
    stage_names = ("persist.bundle",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        persist_cfg = _raw_sst_config(ctx.config).get("persist", {})
        if not isinstance(persist_cfg, dict):
            persist_cfg = {}
        mode = str(persist_cfg.get("mode", "shadow"))
        if mode != "replace":
            return PluginOutput(items={"persisted": {"handled": False}}, metrics={}, diagnostics=[])
        persistence = items.get("persistence")
        if persistence is None:
            persistence = _build_persistence(ctx, self._sst_cfg)
        if persistence is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.persist_missing_store", "plugin": self.meta.id}])
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        if state is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[{"kind": "sst.persist_missing_state", "plugin": self.meta.id}])
        extra_docs = items.get("extra_docs") if isinstance(items.get("extra_docs"), list) else []
        frame_bbox = items.get("frame_bbox")
        frame_bbox_tuple = frame_bbox if isinstance(frame_bbox, tuple) else (0, 0, 0, 0)
        stats = persistence.persist_state_bundle(
            run_id=str(items.get("run_id") or "run"),
            record_id=str(items.get("record_id") or "frame"),
            state=state,
            image_sha256=str(items.get("image_sha256") or ""),
            frame_bbox=cast(tuple[int, int, int, int], frame_bbox_tuple),
            prev_record_id=str(items.get("prev_record_id") or "") or None,
            delta_event=items.get("delta_event") if isinstance(items.get("delta_event"), dict) else None,
            action_event=items.get("action_event") if isinstance(items.get("action_event"), dict) else None,
            extra_docs=extra_docs,
        )
        return PluginOutput(
            items={
                "persisted": {
                    "handled": True,
                    "derived_records": int(stats.derived_records),
                    "indexed_docs": int(stats.indexed_docs),
                    "derived_ids": tuple(stats.derived_ids),
                    "indexed_ids": tuple(stats.indexed_ids),
                }
            },
            metrics={},
            diagnostics=[],
        )


class IndexPlugin(SSTStagePluginBase):
    meta = PluginMeta(id="index", version="0.1.0")
    requires = ("state",)
    provides = ("extra_docs",)
    stage_names = ("index.text",)

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput:
        items = inp.items
        state = items.get("state") if isinstance(items.get("state"), dict) else None
        if state is None:
            return PluginOutput(items={}, metrics={}, diagnostics=[])
        extra_docs: list[dict[str, Any]] = []
        run_id = str(items.get("run_id") or "run")
        record_id = str(items.get("record_id") or "frame")
        state_id = str(state.get("state_id") or "state")
        frame_bbox = items.get("frame_bbox") if isinstance(items.get("frame_bbox"), tuple) else (0, 0, 0, 0)

        element_graph = state.get("element_graph") if isinstance(state.get("element_graph"), dict) else {}
        elements = element_graph.get("elements", ()) if isinstance(element_graph, dict) else ()
        for el in elements:
            label = str(el.get("label") or "").strip()
            if not label:
                continue
            doc_id = _doc_id(run_id, record_id, state_id, label, "ui.label")
            extra_docs.append(
                {
                    "doc_id": doc_id,
                    "text": label,
                    "doc_kind": "ui.label",
                    "meta": {"element_id": el.get("element_id")},
                    "bboxes": [el.get("bbox")],
                }
            )
        for chart in state.get("charts", ()):
            summary = str(chart.get("summary") or "").strip()
            if not summary:
                continue
            doc_id = _doc_id(run_id, record_id, state_id, summary, "chart.summary")
            extra_docs.append(
                {
                    "doc_id": doc_id,
                    "text": summary,
                    "doc_kind": "chart.summary",
                    "meta": {"chart_id": chart.get("chart_id")},
                    "bboxes": [chart.get("bbox")],
                }
            )
        for table in state.get("tables", ()):
            for cell in table.get("cells", ()):
                text = str(cell.get("text") or "").strip()
                if not text:
                    continue
                doc_id = _doc_id(run_id, record_id, state_id, text, "table.cell")
                extra_docs.append(
                    {
                        "doc_id": doc_id,
                        "text": text,
                        "doc_kind": "table.cell",
                        "meta": {"table_id": table.get("table_id"), "r": cell.get("r"), "c": cell.get("c")},
                        "bboxes": [cell.get("bbox")],
                    }
                )
        delta_event = items.get("delta_event") if isinstance(items.get("delta_event"), dict) else None
        if isinstance(delta_event, dict):
            summary = str(delta_event.get("summary") or "").strip()
            if summary:
                doc_id = _doc_id(run_id, record_id, state_id, summary, "delta.summary")
                extra_docs.append(
                    {
                        "doc_id": doc_id,
                        "text": summary,
                        "doc_kind": "delta.summary",
                        "meta": {"delta_id": delta_event.get("delta_id")},
                        "bboxes": [frame_bbox],
                    }
                )
        return PluginOutput(items={"extra_docs": extra_docs}, metrics={}, diagnostics=[])


def _raw_sst_config(config: dict[str, Any]) -> dict[str, Any]:
    processing = config.get("processing", {}) if isinstance(config, dict) else {}
    sst = processing.get("sst", {}) if isinstance(processing, dict) else {}
    return sst if isinstance(sst, dict) else {}


def _quantize_metrics(metrics: dict[str, Any], *, decimals: int = 4) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in metrics.items():
        try:
            out[str(key)] = round(float(value), decimals)
        except Exception:
            continue
    return out


def _sorted_tokens(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = _stable_tokens(tokens)
    tokens.sort(key=lambda t: (t.get("bbox", (0, 0, 0, 0))[1], t.get("bbox", (0, 0, 0, 0))[0], t.get("token_id")))
    return tokens


def _tokens_from_items(items: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = items.get("tokens") if isinstance(items.get("tokens"), list) else None
    if tokens is None and isinstance(items.get("text_tokens"), list):
        tokens = items.get("text_tokens")
    return list(tokens or [])


def _sorted_patches(patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _area(patch: dict[str, Any]) -> int:
        bbox = patch.get("bbox") or (0, 0, 0, 0)
        try:
            return int(max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1]))
        except Exception:
            return 0

    return sorted(
        patches,
        key=lambda p: (
            _safe_bbox(p)["y1"],
            _safe_bbox(p)["x1"],
            -_area(p),
            str(p.get("patch_id", "")),
        ),
    )


def _safe_bbox(patch: dict[str, Any]) -> dict[str, int]:
    bbox = patch.get("bbox") or (0, 0, 0, 0)
    try:
        return {"x1": int(bbox[0]), "y1": int(bbox[1]), "x2": int(bbox[2]), "y2": int(bbox[3])}
    except Exception:
        return {"x1": 0, "y1": 0, "x2": 0, "y2": 0}


def _patch_ids_unique(patches: list[dict[str, Any]]) -> bool:
    seen = set()
    for patch in patches:
        pid = str(patch.get("patch_id") or "")
        if pid in seen and pid:
            return False
        seen.add(pid)
    return True


def _patches_cover_frame(patches: list[dict[str, Any]], image_rgb: Any) -> bool:
    if not hasattr(image_rgb, "size"):
        return True
    width, height = image_rgb.size
    min_x1 = min((p.get("bbox", (0, 0, 0, 0))[0] for p in patches), default=0)
    min_y1 = min((p.get("bbox", (0, 0, 0, 0))[1] for p in patches), default=0)
    max_x2 = max((p.get("bbox", (0, 0, 0, 0))[2] for p in patches), default=0)
    max_y2 = max((p.get("bbox", (0, 0, 0, 0))[3] for p in patches), default=0)
    return min_x1 <= 0 and min_y1 <= 0 and max_x2 >= width and max_y2 >= height


def _parse_element_graph_from_vlm(
    capability: Any | None,
    frame_bytes: Any,
    tokens: list[dict[str, Any]],
    frame_bbox: tuple[int, int, int, int] | None,
    *,
    max_providers: int,
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if capability is None or not frame_bytes or frame_bbox is None:
        return None
    providers = _providers(capability)
    if max_providers > 0:
        providers = providers[:max_providers]
    for provider_id, provider in providers:
        try:
            response = provider.extract(frame_bytes)
            raw_layout = response.get("layout") if isinstance(response, dict) else None
            text = str(response.get("text", "") or "")
        except Exception as exc:
            diagnostics.append({"kind": "sst.ui_vlm_error", "error": str(exc), "provider_id": provider_id})
            continue
        source = raw_layout if raw_layout is not None else text
        element_graph = _parse_element_graph(source, tokens, frame_bbox, provider_id=str(provider_id))
        if element_graph:
            return element_graph
    diagnostics.append({"kind": "sst.ui_vlm_empty"})
    return None


def _providers(capability: Any) -> list[tuple[str, Any]]:
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = list(target.items())
        except Exception:
            items = []
        if items:
            return [(str(pid), provider) for pid, provider in items]
    return [("vision.extractor", capability)]


def _parse_element_graph(
    text: str | dict[str, Any],
    tokens: list[dict[str, Any]],
    frame_bbox: tuple[int, int, int, int],
    *,
    provider_id: str,
) -> dict[str, Any] | None:
    if isinstance(text, dict):
        data = text
    else:
        try:
            data = json.loads(text)
        except Exception:
            return None
    if not isinstance(data, dict):
        return None
    raw_elements = data.get("elements")
    if not isinstance(raw_elements, list):
        return None
    if not _validate_element_schema(raw_elements):
        return None
    state_id = "vlm"
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_element(el: dict[str, Any], parent_id: str | None, depth: int, order: int) -> None:
        el_type = str(el.get("type", "unknown"))
        bbox_raw = el.get("bbox")
        bbox = _coerce_bbox(bbox_raw, frame_bbox)
        if bbox is None:
            return
        label = el.get("text")
        state_raw = el.get("state")
        state = cast(dict[str, Any], state_raw) if isinstance(state_raw, dict) else {}
        interactable = bool(el.get("interactable", _default_interactable(el_type)))
        token_ids = _tokens_for_bbox(tokens, bbox)
        element_id = encode_record_id_component(f"{el_type}-{provider_id}-{depth}-{order}-{bbox}")
        elements.append(
            {
                "element_id": element_id,
                "type": el_type,
                "bbox": bbox,
                "text_refs": tuple(token_ids),
                "label": label,
                "interactable": interactable,
                "state": {
                    "enabled": bool(state.get("enabled", True)),
                    "selected": bool(state.get("selected", False)),
                    "focused": bool(state.get("focused", False)),
                    "expanded": bool(state.get("expanded", False)),
                },
                "parent_id": parent_id,
                "children_ids": tuple(),
                "z": int(depth),
                "app_hint": None,
            }
        )
        if parent_id:
            edges.append({"src": parent_id, "dst": element_id, "kind": "contains"})
        children = el.get("children")
        if isinstance(children, list):
            for idx, child in enumerate(children):
                if isinstance(child, dict):
                    add_element(child, element_id, depth + 1, idx)

    root_id = encode_record_id_component(f"root-{provider_id}")
    elements.append(
        {
            "element_id": root_id,
            "type": "window",
            "bbox": frame_bbox,
            "text_refs": tuple(_tokens_for_bbox(tokens, frame_bbox)),
            "label": None,
            "interactable": False,
            "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
            "parent_id": None,
            "children_ids": tuple(),
            "z": 0,
            "app_hint": None,
        }
    )
    for idx, item in enumerate(raw_elements):
        if isinstance(item, dict):
            add_element(item, root_id, 1, idx)
    _link_children(elements)
    elements.sort(key=lambda e: (e["z"], e["bbox"][1], e["bbox"][0], e["element_id"]))
    return {"state_id": state_id, "elements": tuple(elements), "edges": tuple(edges)}


def _validate_element_schema(elements: list[Any]) -> bool:
    def _valid_element(el: Any) -> bool:
        if not isinstance(el, dict):
            return False
        if not isinstance(el.get("type"), str):
            return False
        bbox = el.get("bbox")
        if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            return False
        try:
            _ = [float(v) for v in bbox]
        except Exception:
            return False
        children = el.get("children")
        if children is None:
            return True
        if not isinstance(children, list):
            return False
        return all(_valid_element(child) for child in children)

    return all(_valid_element(el) for el in elements)


def _tokens_for_bbox(tokens: list[dict[str, Any]], bbox: tuple[int, int, int, int]) -> list[str]:
    out = []
    for token in tokens:
        tb = token.get("bbox")
        if not tb or len(tb) != 4:
            continue
        mx = (tb[0] + tb[2]) // 2
        my = (tb[1] + tb[3]) // 2
        if bbox[0] <= mx < bbox[2] and bbox[1] <= my < bbox[3]:
            out.append(token.get("token_id"))
    return [t for t in out if t]


def _link_children(elements: list[dict[str, Any]]) -> None:
    by_parent: dict[str, list[str]] = {}
    for el in elements:
        pid = el.get("parent_id")
        if not pid:
            continue
        by_parent.setdefault(pid, []).append(el["element_id"])
    for el in elements:
        children = sorted(by_parent.get(el["element_id"], []))
        el["children_ids"] = tuple(children)


def _default_interactable(el_type: str) -> bool:
    return el_type in {"button", "textbox", "checkbox", "radio", "dropdown", "tab", "menu", "icon"}


def _coerce_bbox(bbox: Any, frame_bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    except Exception:
        return None
    width = int(frame_bbox[2])
    height = int(frame_bbox[3])
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height or x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _detect_cursor(image_rgb: Any, frame_width: int, frame_height: int, cfg: dict[str, Any]) -> dict[str, Any]:
    if Image is None or image_rgb is None or not hasattr(image_rgb, "size"):
        return {"bbox": (0, 0, 0, 0), "type": "unknown", "confidence": 0.0}
    threshold = _scale_value(cfg.get("threshold", 0.65), 0.65)
    stride = int(cfg.get("stride_px", 4))
    scales = cfg.get("scales")
    if not isinstance(scales, (list, tuple)):
        scales = (0.75, 1.0, 1.25)
    scales = [_scale_value(scale, 1.0) for scale in scales]
    downscale = _scale_value(cfg.get("downscale", 0.5), 0.5)
    downscale = max(0.1, min(1.0, downscale))
    base = image_rgb
    if downscale != 1.0:
        new_size = (max(1, int(frame_width * downscale)), max(1, int(frame_height * downscale)))
        base = image_rgb.resize(new_size)
    gray = ImageOps.grayscale(base)
    pix = gray.load()
    best_score = 0.0
    best_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    best_type = "unknown"

    for tmpl in _CURSOR_TEMPLATES:
        for scale in scales:
            if scale <= 0:
                continue
            tw = max(1, int(tmpl.width * scale))
            th = max(1, int(tmpl.height * scale))
            if tw <= 2 or th <= 2:
                continue
            tmpl_img = _template_to_image(tmpl, tw, th)
            tmpl_mask = tmpl_img.load()
            for y in range(0, gray.size[1] - th + 1, stride):
                for x in range(0, gray.size[0] - tw + 1, stride):
                    score = _match_template(pix, tmpl_mask, x, y, tw, th)
                    if score > best_score:
                        best_score = score
                        best_bbox = (
                            int(x / downscale),
                            int(y / downscale),
                            int((x + tw) / downscale),
                            int((y + th) / downscale),
                        )
                        best_type = tmpl.name
    if best_score < threshold:
        return {"bbox": (0, 0, 0, 0), "type": "unknown", "confidence": float(best_score)}
    bbox = clamp_bbox(best_bbox, width=frame_width, height=frame_height)
    return {"bbox": bbox, "type": best_type, "confidence": float(best_score)}


def _template_to_image(tmpl: _CursorTemplate, width: int, height: int):
    img = Image.new("L", (tmpl.width, tmpl.height), 0)
    pixels = img.load()
    for y, row in enumerate(tmpl.mask):
        for x, ch in enumerate(row):
            if ch == "1":
                pixels[x, y] = 255
    if width != tmpl.width or height != tmpl.height:
        img = img.resize((width, height))
    return img


def _match_template(pix, tmpl_mask, x0: int, y0: int, tw: int, th: int) -> float:
    hits = 0
    total = 0
    for y in range(th):
        for x in range(tw):
            if tmpl_mask[x, y] < 128:
                continue
            total += 1
            if pix[x0 + x, y0 + y] < 128:
                hits += 1
    if total == 0:
        return 0.0
    return hits / float(total)


def _doc_id(run_id: str, record_id: str, state_id: str, text: str, kind: str) -> str:
    seed = {"record_id": record_id, "state_id": state_id, "text": text, "kind": kind}
    digest = hash_canonical(seed)[:16]
    component = encode_record_id_component(f"{kind}-{digest}")
    return f"{run_id}/derived.sst.text/extra/{component}"


def _scale_value(value: Any, default: float) -> float:
    try:
        val = float(value)
    except Exception:
        val = float(default)
    if val > 1.5:
        return val / 10000.0
    return val


def _build_persistence(ctx: RunContext, sst_cfg: dict[str, Any]) -> SSTPersistence | None:
    metadata = ctx.stores.get("metadata") if isinstance(ctx.stores, dict) else None
    if metadata is None:
        return None
    event_builder = ctx.stores.get("event_builder") if isinstance(ctx.stores, dict) else None
    try:
        extractor_id = str(ctx.config.get("runtime", {}).get("extractor_id") or "sst")
    except Exception:
        extractor_id = "sst"
    extractor_version = str(ctx.config.get("runtime", {}).get("extractor_version") or "0.1.0")
    config_hash_val = config_hash(sst_cfg)

    def _noop_index(_doc_id: str, _text: str) -> None:
        return None

    return SSTPersistence(
        metadata=metadata,
        event_builder=event_builder,
        index_text=_noop_index,
        extractor_id=extractor_id,
        extractor_version=extractor_version,
        config_hash=config_hash_val,
        schema_version=int(sst_cfg.get("schema_version", 1)),
    )
