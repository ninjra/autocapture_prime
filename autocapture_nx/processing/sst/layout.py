"""Layout assembly for text tokens."""

from __future__ import annotations

from statistics import median
from typing import Any

from .utils import bbox_union, norm_text


def assemble_layout(
    tokens: list[dict[str, Any]],
    *,
    line_y_threshold_px: int,
    block_gap_px: int,
    align_tolerance_px: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not tokens:
        return [], []
    ordered = sorted(tokens, key=lambda t: (t["bbox"][1], t["bbox"][0], t["token_id"]))
    heights = [max(1, t["bbox"][3] - t["bbox"][1]) for t in ordered]
    median_h = int(median(heights)) if heights else 12
    line_thresh = max(1, line_y_threshold_px, median_h // 2)

    lines: list[dict[str, Any]] = []
    for token in ordered:
        mid_y = (token["bbox"][1] + token["bbox"][3]) // 2
        placed = False
        for line in lines:
            if abs(mid_y - line["mid_y"]) <= line_thresh:
                line["tokens"].append(token)
                line["mid_y"] = (line["mid_y"] * line["count"] + mid_y) // (line["count"] + 1)
                line["count"] += 1
                placed = True
                break
        if not placed:
            lines.append({"tokens": [token], "mid_y": mid_y, "count": 1})

    line_out: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        toks = sorted(line["tokens"], key=lambda t: (t["bbox"][0], t["bbox"][2], t["token_id"]))
        bbox = bbox_union(t["bbox"] for t in toks)
        text = " ".join(t["text"] for t in toks if t.get("text"))
        line_id = f"line-{idx:04d}"
        for t in toks:
            t["line_id"] = line_id
        line_out.append(
            {
                "line_id": line_id,
                "token_ids": tuple(t["token_id"] for t in toks),
                "bbox": bbox,
                "text": norm_text(text),
                "x1": bbox[0],
                "y1": bbox[1],
                "y2": bbox[3],
            }
        )

    line_out.sort(key=lambda line: (line["y1"], line["x1"], line["line_id"]))

    blocks: list[dict[str, Any]] = []
    for line in line_out:
        if not blocks:
            blocks.append({"lines": [line], "x1": line["x1"], "y2": line["y2"]})
            continue
        prev = blocks[-1]
        gap = max(0, line["y1"] - prev["y2"])
        aligned = abs(line["x1"] - prev["x1"]) <= align_tolerance_px
        if gap <= block_gap_px and aligned:
            prev["lines"].append(line)
            prev["y2"] = max(prev["y2"], line["y2"])
            continue
        blocks.append({"lines": [line], "x1": line["x1"], "y2": line["y2"]})

    block_out: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        lines_in = block["lines"]
        bbox = bbox_union(line["bbox"] for line in lines_in)
        text = "\n".join(line["text"] for line in lines_in if line.get("text"))
        block_id = f"block-{idx:04d}"
        for line in lines_in:
            for token in tokens:
                if token.get("line_id") == line["line_id"]:
                    token["block_id"] = block_id
        block_out.append(
            {
                "block_id": block_id,
                "line_ids": tuple(line["line_id"] for line in lines_in),
                "bbox": bbox,
                "text": norm_text(text),
            }
        )

    block_out.sort(key=lambda b: (b["bbox"][1], b["bbox"][0], b["block_id"]))
    return line_out, block_out
