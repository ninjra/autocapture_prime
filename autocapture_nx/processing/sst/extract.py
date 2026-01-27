"""Deterministic SST extractors."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from io import StringIO
from typing import Any, Callable, Iterable

from autocapture_nx.kernel.ids import encode_record_id_component

from .utils import bp, bbox_iou, bbox_union, norm_text

BBox = tuple[int, int, int, int]


RE_COL = re.compile(r"^[A-Z]{1,3}$")
RE_ROW = re.compile(r"^[0-9]{1,5}$")
RE_CELL_REF = re.compile(r"^[A-Z]{1,3}[0-9]{1,5}$")
RE_NUMBER = re.compile(r"^[0-9]+(\.[0-9]+)?$")
RE_SQL = re.compile(r"\b(SELECT|FROM|WHERE|JOIN|GROUP|ORDER|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
RE_CODE_PUNCT = re.compile(r"[{}();=]")


@dataclass(frozen=True)
class ExtractDiagnostics:
    items: tuple[dict[str, Any], ...]


def providers_from_capability(capability: Any | None, default_provider: str) -> list[tuple[str, Any]]:
    if capability is None:
        return []
    target = capability
    if hasattr(target, "target"):
        target = getattr(target, "target")
    if hasattr(target, "items"):
        try:
            items = list(target.items())
        except Exception:
            items = []
        if items:
            return items
    return [(default_provider, capability)]


def run_ocr_tokens(
    *,
    patches: list[dict[str, Any]],
    ocr_capability: Any | None,
    frame_width: int,
    frame_height: int,
    min_conf_bp: int,
    nms_iou_bp: int,
    max_tokens: int,
    max_patches: int,
    allow_ocr: bool,
    should_abort: Callable[[], bool] | None,
    deadline_ts: float | None,
) -> tuple[list[dict[str, Any]], ExtractDiagnostics]:
    diagnostics: list[dict[str, Any]] = []
    if not allow_ocr or ocr_capability is None:
        diagnostics.append({"kind": "ocr.skipped", "detail": "ocr disabled or missing"})
        return [], ExtractDiagnostics(tuple(diagnostics))

    providers = providers_from_capability(ocr_capability, "ocr.engine")
    if not providers:
        diagnostics.append({"kind": "ocr.missing", "detail": "no providers"})
        return [], ExtractDiagnostics(tuple(diagnostics))

    selected_patches = patches[: max(1, max_patches)]
    tokens: list[dict[str, Any]] = []
    for provider_id, provider in providers:
        for patch in selected_patches:
            if should_abort and should_abort():
                diagnostics.append({"kind": "ocr.aborted", "detail": provider_id})
                return _postprocess_tokens(tokens, min_conf_bp, nms_iou_bp, max_tokens), ExtractDiagnostics(tuple(diagnostics))
            if deadline_ts is not None:
                import time

                if time.time() >= deadline_ts:
                    diagnostics.append({"kind": "ocr.deadline", "detail": provider_id})
                    return _postprocess_tokens(tokens, min_conf_bp, nms_iou_bp, max_tokens), ExtractDiagnostics(tuple(diagnostics))
            try:
                provider_tokens = _extract_tokens_from_provider(provider, provider_id, patch, frame_width, frame_height)
            except Exception as exc:
                diagnostics.append({"kind": "ocr.error", "provider_id": provider_id, "error": str(exc)})
                continue
            tokens.extend(provider_tokens)
    return _postprocess_tokens(tokens, min_conf_bp, nms_iou_bp, max_tokens), ExtractDiagnostics(tuple(diagnostics))


def _extract_tokens_from_provider(
    provider: Any,
    provider_id: str,
    patch: dict[str, Any],
    frame_width: int,
    frame_height: int,
) -> list[dict[str, Any]]:
    patch_id = str(patch.get("patch_id", "patch"))
    bbox = patch["bbox"]
    patch_bytes = patch.get("image_bytes", b"")
    raw_tokens: list[dict[str, Any]] = []
    if hasattr(provider, "extract_tokens"):
        data = provider.extract_tokens(patch_bytes)
        if isinstance(data, dict):
            items = data.get("tokens", [])
        else:
            items = data
        for idx, item in enumerate(items or []):
            text = str(item.get("text", ""))
            token_bbox = _patch_to_frame_bbox(item.get("bbox"), bbox, frame_width, frame_height)
            conf_bp = bp(float(item.get("confidence", 0.0)))
            raw_tokens.append(_token_dict(provider_id, patch_id, idx, text, token_bbox, conf_bp))
        if raw_tokens:
            return raw_tokens
    # Fallback: use text-only extraction and approximate token bboxes.
    extracted = provider.extract(patch_bytes)
    text = str(extracted.get("text", ""))
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        lines = [text] if text.strip() else []
    idx = 0
    for line_no, line in enumerate(lines):
        words = [w for w in re.split(r"\s+", line) if w]
        if not words:
            continue
        for word_no, word in enumerate(words):
            token_bbox = _approx_token_bbox(bbox, line_no, len(lines), word_no, len(words))
            raw_tokens.append(_token_dict(provider_id, patch_id, idx, word, token_bbox, 6500))
            idx += 1
    return raw_tokens


def _token_dict(provider_id: str, patch_id: str, idx: int, text: str, bbox: BBox, conf_bp: int) -> dict[str, Any]:
    norm = norm_text(text)
    token_id = encode_record_id_component(f"tok-{provider_id}-{patch_id}-{idx:05d}")
    flags = {
        "monospace_likely": _monospace_hint(text),
        "is_number": bool(RE_NUMBER.match(norm)),
    }
    return {
        "token_id": token_id,
        "text": text,
        "norm_text": norm,
        "bbox": bbox,
        "confidence_bp": int(conf_bp),
        "source": "ocr",
        "flags": flags,
        "provider_id": provider_id,
        "patch_id": patch_id,
    }


def _patch_to_frame_bbox(token_bbox: Any, patch_bbox: BBox, frame_width: int, frame_height: int) -> BBox:
    if not token_bbox or not isinstance(token_bbox, (list, tuple)) or len(token_bbox) != 4:
        return patch_bbox
    px1, py1, px2, py2 = (int(token_bbox[0]), int(token_bbox[1]), int(token_bbox[2]), int(token_bbox[3]))
    ox1, oy1, ox2, oy2 = patch_bbox
    x1 = max(0, min(frame_width, ox1 + px1))
    y1 = max(0, min(frame_height, oy1 + py1))
    x2 = max(0, min(frame_width, ox1 + px2))
    y2 = max(0, min(frame_height, oy1 + py2))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return (x1, y1, x2, y2)


def _approx_token_bbox(
    patch_bbox: BBox,
    line_no: int,
    line_count: int,
    word_no: int,
    word_count: int,
) -> BBox:
    x1, y1, x2, y2 = patch_bbox
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    line_h = max(1, height // max(1, line_count))
    word_w = max(1, width // max(1, word_count))
    ty1 = y1 + line_no * line_h
    ty2 = min(y2, ty1 + line_h)
    tx1 = x1 + word_no * word_w
    tx2 = min(x2, tx1 + word_w)
    return (int(tx1), int(ty1), int(tx2), int(ty2))


def _postprocess_tokens(tokens: list[dict[str, Any]], min_conf_bp: int, nms_iou_bp: int, max_tokens: int) -> list[dict[str, Any]]:
    if not tokens:
        return []
    # Filter by confidence and normalize ordering first.
    filtered = [t for t in tokens if int(t.get("confidence_bp", 0)) >= min_conf_bp and t.get("norm_text")]
    filtered.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], t["norm_text"], t["token_id"]))
    deduped = _nms_by_text(filtered, nms_iou_bp)
    deduped.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], t["bbox"][2], t["token_id"]))
    return deduped[:max(1, max_tokens)]


def _nms_by_text(tokens: list[dict[str, Any]], nms_iou_bp: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for token in tokens:
        grouped.setdefault(token["norm_text"], []).append(token)
    kept: list[dict[str, Any]] = []
    threshold = max(0.0, min(1.0, nms_iou_bp / 10000.0))
    for norm in sorted(grouped.keys()):
        group = grouped[norm]
        group.sort(key=lambda t: (-int(t["confidence_bp"]), t["bbox"][1], t["bbox"][0], t["token_id"]))
        local_kept: list[dict[str, Any]] = []
        for token in group:
            if any(bbox_iou(token["bbox"], prev["bbox"]) >= threshold for prev in local_kept):
                continue
            local_kept.append(token)
        kept.extend(local_kept)
    return kept


def extract_tables(
    *,
    tokens: list[dict[str, Any]],
    state_id: str,
    min_rows: int,
    min_cols: int,
    max_cells: int,
    row_gap_px: int,
    col_gap_px: int,
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    rows = _cluster_rows(tokens, row_gap_px=row_gap_px)
    if len(rows) < min_rows:
        return []
    col_centers = _cluster_cols(rows, col_gap_px=col_gap_px)
    if len(col_centers) < min_cols:
        return []
    col_edges = _edges_from_centers(col_centers)
    row_edges = _edges_from_centers([r["center_y"] for r in rows])
    rows_n = max(0, len(row_edges) - 1)
    cols_n = max(0, len(col_edges) - 1)
    if rows_n * cols_n <= 0 or rows_n * cols_n > max_cells:
        return []

    cells: list[dict[str, Any]] = []
    for r in range(rows_n):
        for c in range(cols_n):
            cell_bbox = (col_edges[c], row_edges[r], col_edges[c + 1], row_edges[r + 1])
            members = [t for t in tokens if _mid_in_bbox(t["bbox"], cell_bbox)]
            members.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], t["token_id"]))
            text = " ".join(t["text"] for t in members)
            norm = norm_text(text)
            conf = _mean_conf_bp(members)
            cells.append(
                {
                    "r": r,
                    "c": c,
                    "bbox": cell_bbox,
                    "text": text,
                    "norm_text": norm,
                    "confidence_bp": conf,
                }
            )
    table_bbox = bbox_union(c["bbox"] for c in cells)
    table_id = encode_record_id_component(f"table-{state_id}-{table_bbox}")
    csv_text = _cells_to_csv(cells, rows_n, cols_n)
    merges = _detect_merges(tokens, row_edges, col_edges)
    return [
        {
            "table_id": table_id,
            "state_id": state_id,
            "bbox": table_bbox,
            "rows": rows_n,
            "cols": cols_n,
            "row_y": tuple(row_edges),
            "col_x": tuple(col_edges),
            "merges": tuple(merges),
            "grid": {
                "rows": rows_n,
                "cols": cols_n,
                "row_y": tuple(row_edges),
                "col_x": tuple(col_edges),
                "merges": tuple(merges),
            },
            "cells": tuple(cells),
            "csv": csv_text,
            "kind": "table",
        }
    ]


def extract_spreadsheets(
    *,
    tokens: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    state_id: str,
    header_scan_rows: int,
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    if not tables:
        return []
    table = tables[0]
    rows = _cluster_rows(tokens, row_gap_px=12)
    header_rows = rows[: max(1, header_scan_rows)]
    col_headers = {t["norm_text"] for row in header_rows for t in row["tokens"] if RE_COL.match(t["norm_text"])}
    row_headers = {t["norm_text"] for row in rows for t in row["tokens"] if RE_ROW.match(t["norm_text"])}
    if not col_headers or not row_headers:
        return []
    top_row_cells = tuple(c for c in table["cells"] if c["r"] == 0)
    active_cell = _detect_active_cell(tokens, table)
    formula_bar = _detect_formula_bar(tokens, table)
    spreadsheet_id = encode_record_id_component(f"sheet-{state_id}-{table['table_id']}")
    return [
        {
            **table,
            "table_id": spreadsheet_id,
            "kind": "spreadsheet",
            "active_cell": active_cell,
            "formula_bar": formula_bar,
            "headers": {"columns": tuple(sorted(col_headers)), "rows": tuple(sorted(row_headers))},
            "top_row_cells": top_row_cells,
        }
    ]


def extract_code_blocks(
    *,
    tokens: list[dict[str, Any]],
    text_lines: list[dict[str, Any]],
    state_id: str,
    min_keywords: int,
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    code_lines = [line for line in text_lines if _line_code_score(line) > 0]
    if not code_lines:
        return []
    keyword_hits = sum(1 for line in code_lines if RE_SQL.search(line["text"]))
    if keyword_hits < min_keywords and len(code_lines) < 3:
        return []
    lines_sorted = sorted(code_lines, key=lambda line: (line["bbox"][1], line["bbox"][0], line["line_id"]))
    bbox = bbox_union(line["bbox"] for line in lines_sorted)
    code_id = encode_record_id_component(f"code-{state_id}-{bbox}")
    indent_unit = _indent_unit(tokens)
    token_map = {t["token_id"]: t for t in tokens}
    rendered_lines = []
    line_numbers: list[str | None] = []
    for line in lines_sorted:
        line_tokens = [token_map[tid] for tid in line.get("token_ids", []) if tid in token_map]
        line_tokens.sort(key=lambda t: (t["bbox"][0], t["bbox"][1], t["token_id"]))
        number = None
        if line_tokens and RE_ROW.match(line_tokens[0]["norm_text"]):
            if len(line_tokens) > 1:
                num_bbox = line_tokens[0]["bbox"]
                line_width = max(1, line["bbox"][2] - line["bbox"][0])
                if (num_bbox[2] - num_bbox[0]) <= max(6, line_width // 5):
                    number = line_tokens[0]["norm_text"]
                    line_tokens = line_tokens[1:]
        line_numbers.append(number)
        if not line_tokens:
            continue
        indent_spaces = max(0, (line_tokens[0]["bbox"][0] - bbox[0]) // max(1, indent_unit))
        text = " ".join(t["text"] for t in line_tokens if t.get("text"))
        rendered_lines.append((" " * indent_spaces) + norm_text(text))
    code_text = "\n".join(rendered_lines).strip()
    language = "sql" if RE_SQL.search(code_text) else "unknown"
    diagnostics: list[str] = []
    confidence = 8500 if language == "sql" else 6500
    if language == "sql" and not _sql_balance_ok(code_text):
        diagnostics.append("sql_unbalanced")
        confidence = 4500
    return [
        {
            "code_id": code_id,
            "state_id": state_id,
            "bbox": bbox,
            "language": language,
            "text": code_text,
            "lines": tuple(rendered_lines),
            "line_numbers": tuple(line_numbers),
            "caret": None,
            "selection": None,
            "confidence_bp": confidence,
            "diagnostics": tuple(diagnostics),
        }
    ]


def extract_charts(
    *,
    tokens: list[dict[str, Any]],
    state_id: str,
    min_ticks: int,
) -> list[dict[str, Any]]:
    if not tokens:
        return []
    numeric = [t for t in tokens if RE_NUMBER.match(t["norm_text"])]
    if len(numeric) < min_ticks:
        return []
    bbox = bbox_union(t["bbox"] for t in numeric)
    ticks_y = tuple(sorted({t["norm_text"] for t in numeric[: min_ticks * 2]}))
    chart_id = encode_record_id_component(f"chart-{state_id}-{bbox}")
    evidence = {"tick_count": len(ticks_y)}
    return [
        {
            "chart_id": chart_id,
            "state_id": state_id,
            "bbox": bbox,
            "chart_type": "unknown",
            "labels": tuple(),
            "ticks_x": tuple(),
            "ticks_y": ticks_y,
            "series": tuple(),
            "evidence": evidence,
            "confidence_bp": 6000,
        }
    ]


def parse_ui_elements(
    *,
    state_id: str,
    frame_bbox: BBox,
    tokens: list[dict[str, Any]],
    text_blocks: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    spreadsheets: list[dict[str, Any]],
    code_blocks: list[dict[str, Any]],
    charts: list[dict[str, Any]],
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    root_id = encode_record_id_component(f"root-{state_id}")
    root = _element(root_id, "window", frame_bbox, label=None, parent_id=None, z=0)
    elements.append(root)

    def add_child(el_type: str, bbox: BBox, label: str | None, token_ids: Iterable[str]) -> str:
        eid = encode_record_id_component(f"{el_type}-{state_id}-{bbox}")
        child = _element(eid, el_type, bbox, label=label, parent_id=root_id, z=1, text_refs=tuple(token_ids))
        elements.append(child)
        edges.append({"src": root_id, "dst": eid, "kind": "contains"})
        return eid

    for block in text_blocks:
        block_tokens = [t["token_id"] for t in tokens if t.get("block_id") == block["block_id"]]
        add_child("unknown", block["bbox"], block.get("text"), block_tokens)
    for table in tables:
        token_ids = [t["token_id"] for t in tokens if _mid_in_bbox(t["bbox"], table["bbox"])]
        add_child("table", table["bbox"], None, token_ids)
    for sheet in spreadsheets:
        token_ids = [t["token_id"] for t in tokens if _mid_in_bbox(t["bbox"], sheet["bbox"])]
        add_child("grid", sheet["bbox"], None, token_ids)
    for code in code_blocks:
        token_ids = [t["token_id"] for t in tokens if _mid_in_bbox(t["bbox"], code["bbox"])]
        add_child("code", code["bbox"], code.get("language"), token_ids)
    for chart in charts:
        token_ids = [t["token_id"] for t in tokens if _mid_in_bbox(t["bbox"], chart["bbox"])]
        add_child("chart", chart["bbox"], None, token_ids)

    # Attach orphan tokens to the root deterministically.
    root_refs = tuple(sorted({t["token_id"] for t in tokens if not t.get("block_id")}))
    root = {**root, "text_refs": root_refs}
    elements[0] = root

    elements.sort(key=lambda e: (e["z"], e["bbox"][1], e["bbox"][0], e["element_id"]))
    _link_children(elements)
    return {"state_id": state_id, "elements": tuple(elements), "edges": tuple(edges)}


def track_cursor(record: dict[str, Any], frame_width: int, frame_height: int) -> dict[str, Any] | None:
    cursor = record.get("cursor")
    if not isinstance(cursor, dict):
        return None
    try:
        x = int(cursor.get("x", 0))
        y = int(cursor.get("y", 0))
    except Exception:
        return None
    size = 16
    x1 = max(0, min(frame_width, x - size // 2))
    y1 = max(0, min(frame_height, y - size // 2))
    x2 = max(x1 + 1, min(frame_width, x1 + size))
    y2 = max(y1 + 1, min(frame_height, y1 + size))
    visible = bool(cursor.get("visible", True))
    return {
        "bbox": (x1, y1, x2, y2),
        "type": "arrow" if visible else "unknown",
        "confidence_bp": 9000 if visible else 2000,
    }


def _cluster_rows(tokens: list[dict[str, Any]], *, row_gap_px: int) -> list[dict[str, Any]]:
    ordered = sorted(tokens, key=lambda t: (t["bbox"][1], t["bbox"][0], t["token_id"]))
    rows: list[dict[str, Any]] = []
    for token in ordered:
        mid = (token["bbox"][1] + token["bbox"][3]) // 2
        if not rows:
            rows.append({"tokens": [token], "center_y": mid})
            continue
        prev = rows[-1]
        if abs(mid - prev["center_y"]) <= row_gap_px:
            prev["tokens"].append(token)
            prev["center_y"] = (prev["center_y"] + mid) // 2
        else:
            rows.append({"tokens": [token], "center_y": mid})
    for row in rows:
        row["tokens"].sort(key=lambda t: (t["bbox"][0], t["bbox"][1], t["token_id"]))
    return rows


def _cluster_cols(rows: list[dict[str, Any]], *, col_gap_px: int) -> list[int]:
    centers: list[int] = []
    for row in rows:
        for token in row["tokens"]:
            mid_x = (token["bbox"][0] + token["bbox"][2]) // 2
            placed = False
            for idx, center in enumerate(centers):
                if abs(mid_x - center) <= col_gap_px:
                    centers[idx] = (center + mid_x) // 2
                    placed = True
                    break
            if not placed:
                centers.append(mid_x)
    return sorted(set(int(c) for c in centers))


def _edges_from_centers(centers: list[int]) -> list[int]:
    if not centers:
        return [0, 1]
    centers = sorted(int(c) for c in centers)
    edges = [max(0, centers[0] - 1)]
    for a, b in zip(centers, centers[1:]):
        edges.append((a + b) // 2)
    edges.append(centers[-1] + 1)
    # Ensure strictly increasing edges.
    for idx in range(1, len(edges)):
        if edges[idx] <= edges[idx - 1]:
            edges[idx] = edges[idx - 1] + 1
    return edges


def _mid_in_bbox(bbox: BBox, cell: BBox) -> bool:
    mx = (bbox[0] + bbox[2]) // 2
    my = (bbox[1] + bbox[3]) // 2
    return cell[0] <= mx < cell[2] and cell[1] <= my < cell[3]


def _mean_conf_bp(tokens: list[dict[str, Any]]) -> int:
    if not tokens:
        return 0
    total = sum(int(t.get("confidence_bp", 0)) for t in tokens)
    return int(total // max(1, len(tokens)))


def _cells_to_csv(cells: list[dict[str, Any]], rows: int, cols: int) -> str:
    grid = [["" for _c in range(cols)] for _r in range(rows)]
    for cell in cells:
        r = int(cell["r"])
        c = int(cell["c"])
        if 0 <= r < rows and 0 <= c < cols:
            grid[r][c] = str(cell.get("text", ""))
    buf = StringIO()
    writer = csv.writer(buf)
    for row in grid:
        writer.writerow(row)
    return buf.getvalue().strip()


def _detect_merges(tokens: list[dict[str, Any]], row_edges: list[int], col_edges: list[int]) -> list[dict[str, int]]:
    if not tokens:
        return []
    merges: set[tuple[int, int, int, int]] = set()
    row_count = max(0, len(row_edges) - 1)
    col_count = max(0, len(col_edges) - 1)
    for token in tokens:
        text = str(token.get("norm_text") or token.get("text") or "")
        if not text:
            continue
        bbox = token.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        rows = _spanned_indices(bbox[1], bbox[3], row_edges)
        cols = _spanned_indices(bbox[0], bbox[2], col_edges)
        if len(rows) <= 1 and len(cols) <= 1:
            continue
        r1, r2 = min(rows), max(rows)
        c1, c2 = min(cols), max(cols)
        if 0 <= r1 <= r2 < row_count and 0 <= c1 <= c2 < col_count:
            merges.add((r1, c1, r2, c2))
    return [{"r1": r1, "c1": c1, "r2": r2, "c2": c2} for r1, c1, r2, c2 in sorted(merges)]


def _spanned_indices(start: int, end: int, edges: list[int]) -> list[int]:
    indices: list[int] = []
    for idx in range(max(0, len(edges) - 1)):
        a = edges[idx]
        b = edges[idx + 1]
        if end <= a or start >= b:
            continue
        indices.append(idx)
    return indices


def _detect_active_cell(tokens: list[dict[str, Any]], table: dict[str, Any]) -> dict[str, Any] | None:
    cells = table.get("cells") or []
    cell_map = {(int(c["r"]), int(c["c"])): c for c in cells if isinstance(c, dict)}
    rows = int(table.get("rows", 0) or 0)
    cols = int(table.get("cols", 0) or 0)
    if not rows or not cols:
        return None
    candidates = [t for t in tokens if RE_CELL_REF.match(str(t.get("norm_text", "")))]
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], t["token_id"]))
    for token in candidates:
        ref = str(token.get("norm_text", "")).upper()
        col_part = "".join(ch for ch in ref if ch.isalpha())
        row_part = "".join(ch for ch in ref if ch.isdigit())
        if not col_part or not row_part:
            continue
        col_idx = _col_to_index(col_part)
        try:
            row_idx = int(row_part) - 1
        except Exception:
            continue
        if col_idx < 0 or row_idx < 0 or col_idx >= cols or row_idx >= rows:
            continue
        cell = cell_map.get((row_idx, col_idx))
        if cell is None:
            continue
        return {"ref": ref, "r": row_idx, "c": col_idx, "bbox": cell.get("bbox")}
    return None


def _detect_formula_bar(tokens: list[dict[str, Any]], table: dict[str, Any]) -> dict[str, Any] | None:
    bbox = table.get("bbox")
    if not bbox:
        return None
    y1, y2 = bbox[1], bbox[3]
    height = max(1, y2 - y1)
    upper_limit = y1 + max(1, height // 4)
    anchor = None
    for token in tokens:
        text = str(token.get("norm_text") or token.get("text") or "").lower()
        if text in {"fx", "f(x)"} and token.get("bbox") and token["bbox"][1] <= upper_limit:
            anchor = token
            break
    if anchor is None:
        return None
    anchor_y = (anchor["bbox"][1] + anchor["bbox"][3]) // 2
    line_tokens = [t for t in tokens if abs(((t["bbox"][1] + t["bbox"][3]) // 2) - anchor_y) <= 8]
    if not line_tokens:
        return None
    line_tokens.sort(key=lambda t: (t["bbox"][0], t["token_id"]))
    text = " ".join(str(t.get("text", "")) for t in line_tokens).strip()
    bar_bbox = bbox_union(t["bbox"] for t in line_tokens)
    return {"bbox": bar_bbox, "text": norm_text(text)}


def _col_to_index(col: str) -> int:
    value = 0
    for ch in col.upper():
        if not ("A" <= ch <= "Z"):
            return -1
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return value - 1


def _sql_balance_ok(text: str) -> bool:
    paren = 0
    single = 0
    double = 0
    for ch in text:
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == "'":
            single ^= 1
        elif ch == "\"":
            double ^= 1
    return paren == 0 and single == 0 and double == 0


def _line_code_score(line: dict[str, Any]) -> int:
    text = str(line.get("text", ""))
    score = 0
    if RE_SQL.search(text):
        score += 2
    if RE_CODE_PUNCT.search(text):
        score += 1
    if any(ch in text for ch in ("\t", "    ")):
        score += 1
    return score


def _indent_unit(tokens: list[dict[str, Any]]) -> int:
    widths = []
    for token in tokens:
        text = str(token.get("text", ""))
        if not text:
            continue
        bbox = token.get("bbox")
        if not bbox:
            continue
        width = max(1, int(bbox[2]) - int(bbox[0]))
        widths.append(max(1, width // max(1, len(text))))
    if not widths:
        return 8
    widths.sort()
    return max(4, widths[len(widths) // 2])


def _monospace_hint(text: str) -> bool:
    if not text:
        return False
    lengths = {len(word) for word in re.split(r"\s+", text) if word}
    return len(lengths) <= 2 and any(ch in text for ch in ("_", "{", "}", ";"))


def _element(
    element_id: str,
    el_type: str,
    bbox: BBox,
    *,
    label: str | None,
    parent_id: str | None,
    z: int,
    text_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "element_id": element_id,
        "type": el_type,
        "bbox": bbox,
        "text_refs": text_refs,
        "label": label,
        "interactable": el_type in {"button", "textbox", "checkbox", "radio", "dropdown", "tab", "menu", "icon"},
        "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
        "parent_id": parent_id,
        "children_ids": tuple(),
        "z": int(z),
        "app_hint": None,
    }


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
