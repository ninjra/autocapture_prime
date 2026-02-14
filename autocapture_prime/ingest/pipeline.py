from __future__ import annotations

import json
from pathlib import Path
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


def ingest_one_session(session: SessionCandidate, config: PrimeConfig) -> dict[str, Any]:
    loader = SessionLoader(session.session_dir)
    loaded = loader.load()
    decoder = FrameDecoder()
    if config.ocr_engine.lower() == "tesseract":
        ocr_engine = TesseractOcrEngine()
    else:
        ocr_engine = PaddleOcrEngine(config.ocr_cache_dir, config={"engine": config.ocr_engine})
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

    for image_path, frame_meta in loader.iter_frames(loaded):
        frame_index = int(frame_meta.get("frame_index", 0) or 0)
        decoded = decoder.decode_png(image_path, frame_index=frame_index)
        with Image.open(image_path) as image:
            spans = ocr_engine.run(image)
            elements = layout_engine.run(image, spans)

        frame_rows.append(
            {
                "session_id": session.session_id,
                "frame_index": frame_index,
                "image_path": str(decoded.image_path),
                "width": decoded.width,
                "height": decoded.height,
                "mode": decoded.mode,
                "qpc_ticks": int(frame_meta.get("qpc_ticks", 0) or 0),
                "t_rel_s": qpc_to_relative_seconds(int(frame_meta.get("qpc_ticks", 0) or 0), start_qpc, qpc_freq),
            }
        )
        for span in spans:
            ocr_rows.append(
                {
                    "session_id": session.session_id,
                    "frame_index": frame_index,
                    "text": span.text,
                    "confidence": span.confidence,
                    "bbox": list(span.bbox),
                    "reading_order": span.reading_order,
                    "language": span.language,
                }
            )
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
                }
            )
        link_frames.append((frame_index, elements))

    linker = TemporalLinker(iou_threshold=0.3)
    tracks, id_switches = linker.link(link_frames)
    track_rows = [
        {
            "session_id": session.session_id,
            "track_id": row.track_id,
            "frame_index": row.frame_index,
            "element_id": row.element_id,
            "type": row.type,
            "text": row.text,
            "bbox": list(row.bbox),
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
