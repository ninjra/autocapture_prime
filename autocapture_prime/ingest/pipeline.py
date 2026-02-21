from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from PIL import Image

from autocapture_prime.config import PrimeConfig
from autocapture_prime.eval.metrics import record_ingest_metric
from autocapture_prime.layout.omniparser_engine import OmniParserEngine
from autocapture_prime.layout.uied_engine import UIEDEngine
from autocapture_prime.link.temporal_linker import TemporalLinker
from autocapture_prime.ocr.paddle_engine import PaddleOcrEngine
from autocapture_prime.ocr.tesseract_engine import TesseractOcrEngine
from autocapture_prime.store.index import build_lexical_index
from autocapture_prime.store.tables import write_rows

from .frame_decoder import FrameDecoder
from .normalize import qpc_to_relative_seconds
from .session_loader import SessionLoader
from .session_scanner import SessionCandidate


@dataclass(frozen=True)
class _SpanWithSource:
    span: Any
    source_pass: str
    source_strategy: str


def _norm_rect(rect: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int] | None:
    x0, y0, x1, y1 = rect
    x0 = max(0, min(width, int(x0)))
    y0 = max(0, min(height, int(y0)))
    x1 = max(0, min(width, int(x1)))
    y1 = max(0, min(height, int(y1)))
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)


def _dedupe_rois(rois: list[tuple[int, int, int, int]], width: int, height: int) -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for roi in rois:
        norm = _norm_rect(roi, width, height)
        if norm is None or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return sorted(out, key=lambda item: (item[1], item[0], item[3] - item[1], item[2] - item[0]))


def _dirty_rect_rois(frame_meta: dict[str, Any], width: int, height: int) -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    for item in frame_meta.get("dirty_rects", []) if isinstance(frame_meta.get("dirty_rects", []), list) else []:
        if not isinstance(item, dict):
            continue
        x = int(item.get("x", 0) or 0)
        y = int(item.get("y", 0) or 0)
        w = int(item.get("w", 0) or 0)
        h = int(item.get("h", 0) or 0)
        out.append((x, y, x + w, y + h))
    return _dedupe_rois(out, width, height)


def _heuristic_tab_rois(width: int, height: int) -> list[tuple[int, int, int, int]]:
    top_h = max(40, int(height * 0.12))
    left_w = max(320, int(width * 0.25))
    return _dedupe_rois(
        [
            (0, 0, width, top_h),
            (0, 0, left_w, int(height * 0.2)),
            (max(0, width - left_w), 0, width, int(height * 0.2)),
        ],
        width,
        height,
    )


def _click_rois(click: tuple[int, int], width: int, height: int) -> list[tuple[int, int, int, int]]:
    cx, cy = int(click[0]), int(click[1])
    half_w = max(160, int(width * 0.06))
    half_h = max(90, int(height * 0.08))
    return _dedupe_rois([(cx - half_w, cy - half_h, cx + half_w, cy + half_h)], width, height)


def _roi_plan(
    frame_meta: dict[str, Any],
    *,
    strategy: str,
    width: int,
    height: int,
    click_anchor: tuple[int, int] | None,
) -> list[tuple[int, int, int, int]]:
    mode = str(strategy or "none").strip().lower()
    if mode in {"", "none"}:
        return []
    rois: list[tuple[int, int, int, int]] = []
    if mode == "dirty_rects":
        rois.extend(_dirty_rect_rois(frame_meta, width, height))
    elif mode == "heuristic_tabs":
        rois.extend(_heuristic_tab_rois(width, height))
    elif mode == "click_anchored":
        if click_anchor is not None:
            rois.extend(_click_rois(click_anchor, width, height))
    else:
        # Composite deterministic mode: dirty -> click -> tabs.
        rois.extend(_dirty_rect_rois(frame_meta, width, height))
        if click_anchor is not None:
            rois.extend(_click_rois(click_anchor, width, height))
        rois.extend(_heuristic_tab_rois(width, height))
    return _dedupe_rois(rois, width, height)


def _event_mouse_xy(event: dict[str, Any]) -> tuple[int, int] | None:
    if not isinstance(event, dict):
        return None
    mouse = event.get("mouse")
    if not isinstance(mouse, dict):
        return None
    x = int(mouse.get("x", 0) or 0)
    y = int(mouse.get("y", 0) or 0)
    return (x, y)


def _event_kind(event: dict[str, Any]) -> str:
    raw = event.get("type")
    if isinstance(raw, str):
        return raw.strip().upper()
    if isinstance(raw, int):
        return {1: "MOUSE", 2: "CONTROL", 3: "GENERIC_HID"}.get(raw, "UNKNOWN")
    return "UNKNOWN"


def _build_click_anchor_map(frames_meta: list[dict[str, Any]], input_events: list[dict[str, Any]]) -> dict[int, tuple[int, int]]:
    points: list[tuple[int, int, int, int]] = []
    # (qpc_ticks, event_index, x, y)
    for event in input_events:
        if _event_kind(event) != "MOUSE":
            continue
        mouse = event.get("mouse")
        if not isinstance(mouse, dict):
            continue
        buttons = int(mouse.get("buttons", 0) or 0)
        if buttons <= 0:
            continue
        xy = _event_mouse_xy(event)
        if xy is None:
            continue
        points.append(
            (
                int(event.get("qpc_ticks", 0) or 0),
                int(event.get("event_index", 0) or 0),
                int(xy[0]),
                int(xy[1]),
            )
        )
    if not points:
        return {}
    points.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    frame_ticks = sorted(int(f.get("qpc_ticks", 0) or 0) for f in frames_meta if isinstance(f, dict))
    if len(frame_ticks) >= 2:
        gaps = [max(1, frame_ticks[i + 1] - frame_ticks[i]) for i in range(len(frame_ticks) - 1)]
        window = max(1, min(gaps))
    else:
        window = 1000
    anchors: dict[int, tuple[int, int]] = {}
    for frame in frames_meta:
        if not isinstance(frame, dict):
            continue
        frame_index = int(frame.get("frame_index", 0) or 0)
        qpc_ticks = int(frame.get("qpc_ticks", 0) or 0)
        best: tuple[int, int, int, int] | None = None
        best_delta = 10**18
        best_idx = 10**18
        for item in points:
            delta = abs(item[0] - qpc_ticks)
            if delta > window:
                continue
            if delta < best_delta or (delta == best_delta and item[1] < best_idx):
                best = item
                best_delta = delta
                best_idx = item[1]
        if best is not None:
            anchors[frame_index] = (best[2], best[3])
    return anchors


def _rescale_spans(spans: list[Any], scale: float) -> list[Any]:
    if scale >= 0.999:
        return list(spans)
    if scale <= 0.0:
        return list(spans)
    out: list[Any] = []
    inv = 1.0 / scale
    for span in spans:
        x0, y0, x1, y1 = span.bbox
        out.append(
            type(span)(
                text=span.text,
                confidence=span.confidence,
                bbox=(int(round(x0 * inv)), int(round(y0 * inv)), int(round(x1 * inv)), int(round(y1 * inv))),
                reading_order=span.reading_order,
                language=span.language,
            )
        )
    return out


def _merge_spans(rows: list[_SpanWithSource]) -> list[_SpanWithSource]:
    best: dict[tuple[str, tuple[int, int, int, int]], _SpanWithSource] = {}
    for item in rows:
        x0, y0, x1, y1 = (int(item.span.bbox[0]), int(item.span.bbox[1]), int(item.span.bbox[2]), int(item.span.bbox[3]))
        key = (str(item.span.text or "").strip(), (x0, y0, x1, y1))
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        if float(item.span.confidence) > float(current.span.confidence):
            best[key] = item
            continue
        if float(item.span.confidence) == float(current.span.confidence):
            # Prefer full-frame source for deterministic tie-breaks.
            if current.source_pass != "full_frame" and item.source_pass == "full_frame":
                best[key] = item
    return sorted(best.values(), key=lambda item: (item.span.reading_order, item.span.bbox[1], item.span.bbox[0], item.span.text))


def ingest_one_session(session: SessionCandidate, config: PrimeConfig) -> dict[str, Any]:
    loader = SessionLoader(session.session_dir)
    loaded = loader.load()
    decoder = FrameDecoder()
    ocr_engine: Any
    if config.ocr_engine.lower() == "tesseract":
        ocr_engine = TesseractOcrEngine()
    else:
        ocr_engine = PaddleOcrEngine(config.ocr_cache_dir, config={"engine": config.ocr_engine})
    layout_engine: Any
    if config.layout_engine.lower() == "omniparser":
        layout_engine = OmniParserEngine(config.allow_agpl)
    else:
        layout_engine = UIEDEngine()

    frame_rows: list[dict[str, Any]] = []
    ocr_rows: list[dict[str, Any]] = []
    element_rows: list[dict[str, Any]] = []
    link_frames: list[tuple[int, list[Any]]] = []

    qpc_freq = int(loaded.manifest.get("qpc_frequency_hz", 1) or 1)
    start_qpc = int(loaded.manifest.get("start_qpc_ticks", 0) or 0)
    click_anchor_map = _build_click_anchor_map(loaded.frames_meta, loaded.input_events)

    for image_path, frame_meta in loader.iter_frames(loaded):
        frame_index = int(frame_meta.get("frame_index", 0) or 0)
        qpc_ticks = int(frame_meta.get("qpc_ticks", 0) or 0)
        decoded = decoder.decode_png(image_path, frame_index=frame_index)
        click_anchor = click_anchor_map.get(frame_index)
        with Image.open(image_path) as image:
            span_rows: list[_SpanWithSource] = []
            scale = float(config.ocr_full_frame_scale)
            if scale < 0.999:
                resampling = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
                scaled = image.resize(
                    (
                        max(1, int(round(image.width * scale))),
                        max(1, int(round(image.height * scale))),
                    ),
                    resample=resampling,
                )
                spans_scaled = _rescale_spans(ocr_engine.run(scaled), scale)
                span_rows.extend(
                    [
                        _SpanWithSource(span=s, source_pass="full_frame", source_strategy="full_frame_scaled")
                        for s in spans_scaled
                    ]
                )
            else:
                span_rows.extend(
                    [
                        _SpanWithSource(span=s, source_pass="full_frame", source_strategy="full_frame")
                        for s in ocr_engine.run(image)
                    ]
                )
            rois = _roi_plan(
                frame_meta,
                strategy=config.ocr_roi_strategy,
                width=image.width,
                height=image.height,
                click_anchor=click_anchor,
            )
            if rois:
                roi_spans = ocr_engine.run(image, rois=rois)
                span_rows.extend(
                    [
                        _SpanWithSource(span=s, source_pass="roi", source_strategy=config.ocr_roi_strategy)
                        for s in roi_spans
                    ]
                )
            merged_span_rows = _merge_spans(span_rows)
            spans = [item.span for item in merged_span_rows]
            elements = layout_engine.run(image, spans)

        frame_rows.append(
            {
                "session_id": session.session_id,
                "frame_index": frame_index,
                "image_path": str(decoded.image_path),
                "width": decoded.width,
                "height": decoded.height,
                "mode": decoded.mode,
                "qpc_ticks": qpc_ticks,
                "t_rel_s": qpc_to_relative_seconds(qpc_ticks, start_qpc, qpc_freq),
                "click_anchor": [int(click_anchor[0]), int(click_anchor[1])] if click_anchor is not None else [],
            }
        )
        for item in merged_span_rows:
            span = item.span
            ocr_rows.append(
                {
                    "session_id": session.session_id,
                    "frame_index": frame_index,
                    "text": span.text,
                    "confidence": span.confidence,
                    "bbox": list(span.bbox),
                    "reading_order": span.reading_order,
                    "language": span.language,
                    "extractor": f"ocr.{config.ocr_engine.lower()}",
                    "source_pass": item.source_pass,
                    "source_strategy": item.source_strategy,
                }
            )
        span_passes = sorted(set(item.source_pass for item in merged_span_rows))
        for element in elements:
            element_rows.append(
                {
                    "session_id": session.session_id,
                    "frame_index": frame_index,
                    "element_id": element.element_id,
                    "type": element.type,
                    "label": element.label,
                    "text": element.text,
                    "bbox": list(element.bbox),
                    "confidence": element.confidence,
                    "parent_id": element.parent_id,
                    "extractor": f"layout.{config.layout_engine.lower()}",
                    "source_passes": span_passes,
                }
            )
        link_frames.append((frame_index, elements))

    linker = TemporalLinker(iou_threshold=0.3)
    tracks, id_switches = linker.link(link_frames, click_points=click_anchor_map)
    track_rows = [
        {
            "session_id": session.session_id,
            "track_id": row.track_id,
            "frame_index": row.frame_index,
            "element_id": row.element_id,
            "type": row.type,
            "text": row.text,
            "bbox": list(row.bbox),
            "extractor": "link.temporal_linker",
            "anchor_used": bool(row.frame_index in click_anchor_map),
        }
        for row in tracks
    ]

    target_root = config.storage_root / session.session_id
    target_root.mkdir(parents=True, exist_ok=True)
    out_frames = write_rows(frame_rows, target_root, "frames")
    out_input = write_rows(loaded.input_events, target_root, "events_input")
    out_ocr = write_rows(ocr_rows, target_root, "ocr_spans")
    out_elements = write_rows(element_rows, target_root, "elements")
    out_tracks = write_rows(track_rows, target_root, "tracks")
    index_path = build_lexical_index(ocr_rows + element_rows, target_root / "lexical_index.json")

    summary = {
        "session_id": session.session_id,
        "rows": {
            "frames": len(frame_rows),
            "input_events": len(loaded.input_events),
            "ocr_spans": len(ocr_rows),
            "elements": len(element_rows),
            "tracks": len(track_rows),
        },
        "id_switches": id_switches,
        "click_anchor_frames": len(click_anchor_map),
        "outputs": {
            "frames": str(out_frames),
            "events_input": str(out_input),
            "ocr_spans": str(out_ocr),
            "elements": str(out_elements),
            "tracks": str(out_tracks),
            "lexical_index": str(index_path),
        },
    }
    (target_root / "ingest_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    record_ingest_metric(config.storage_root, summary)
    return summary
