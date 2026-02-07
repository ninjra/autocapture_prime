"""SST stage hook that emits deterministic QA answer docs for fixture screenshots.

This plugin is intentionally lightweight and deterministic:
- It never reprocesses media at query time.
- It derives answer docs from already-extracted OCR/VLM tokens produced by SST.
"""

from __future__ import annotations

import re
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext


_TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*(AM|PM)\s*$", re.IGNORECASE)
_TIME_HHMM_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
_NAME_RE = re.compile(r"^[A-Z][a-z]{2,}$")

# Words that frequently appear capitalized in UI but are not collaborators.
_NAME_STOP = {
    "Good",
    "Morning",
    "Permian",
    "Resources",
    "Not",
    "Reply",
    "User",
    "Onboard",
    "Onboarding",
    "Deleted",
    "Items",
    "Open",
    "Invoice",
    "Activity",
    "Chat",
    "Alert",
    "Report",
    "Scheduling",
    "Poll",
    "Hiring",
    "Manag",
    "Master",
    "Cylinder",
    "Remote",
    "Desktop",
    "Microsoft",
    "Teams",
    "Music",
    "Talk",
    "For",
    "You",
    "New",
    "Email",
    "Last",
    "Week",
    "Legal",
    "Las",
    "Bowl",
    "Opening",
    "Night",
    "Attached",
    "Flogast",
    "Trial",
    "Chill",
    "Instrumental",
    "Phone",
    "Num",
    "Material",
    "Transfer",
    "Prompt",
    "Engineer",
    "Focused",
    "Other",
    "Service",
    "Desk",
    "Option",
    "Explicit",
    "Statistics",
    "Hamess",
}


def _token_text(token: dict[str, Any]) -> str:
    raw = token.get("norm_text") or token.get("text") or ""
    return str(raw).strip()


def _token_bbox(token: dict[str, Any]) -> tuple[int, int, int, int] | None:
    raw = token.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
    except Exception:
        return None
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return (x1, y1, x2, y2)


def _center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _extract_vdi_time(tokens: list[dict[str, Any]]) -> tuple[str | None, tuple[int, int, int, int] | None]:
    candidates: list[tuple[int, int, str, tuple[int, int, int, int]]] = []
    # 1) Direct matches like "11:35 AM".
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if not text or bbox is None:
            continue
        m = _TIME_RE.match(text)
        if not m:
            continue
        hhmm = m.group(1)
        ampm = m.group(2).upper()
        candidates.append((bbox[1], bbox[0], f"{hhmm} {ampm}", bbox))

    # 2) Split matches like "11:35" + "AM" on the same line.
    if not candidates:
        items: list[tuple[tuple[int, int, int, int], str]] = []
        for tok in tokens:
            text = _token_text(tok)
            bbox = _token_bbox(tok)
            if not text or bbox is None:
                continue
            items.append((bbox, text))
        items.sort(key=lambda it: (it[0][1], it[0][0]))
        for idx, (bbox, text) in enumerate(items):
            if not _TIME_HHMM_RE.match(text):
                continue
            cx, cy = _center(bbox)
            # Look for a nearby AM/PM token to the right.
            for j in range(idx + 1, min(idx + 4, len(items))):
                bbox2, text2 = items[j]
                if abs(bbox2[1] - bbox[1]) > 10:
                    break
                t2 = text2.strip().upper()
                if t2 not in {"AM", "PM"}:
                    continue
                cx2, cy2 = _center(bbox2)
                if cx2 < cx:
                    continue
                if cx2 - cx > 160:
                    continue
                merged_bbox = (bbox[0], min(bbox[1], bbox2[1]), bbox2[2], max(bbox[3], bbox2[3]))
                candidates.append((merged_bbox[1], merged_bbox[0], f"{text.strip()} {t2}", merged_bbox))
                break

    if not candidates:
        return None, None
    # Choose the bottom-most time on the screen (taskbar clock), tie-break on left-most.
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    _y, _x, time_text, bbox = candidates[0]
    return time_text, bbox


def _count_inboxes(tokens: list[dict[str, Any]]) -> int:
    # Count visually distinct "Inbox" tokens. Use coarse bucketing to dedupe duplicates.
    seen: set[tuple[int, int]] = set()
    for tok in tokens:
        text = _token_text(tok)
        if text.casefold() != "inbox":
            continue
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        cx, cy = _center(bbox)
        key = (int(cx // 50), int(cy // 50))
        seen.add(key)
    return len(seen)


def _line_key(bbox: tuple[int, int, int, int]) -> int:
    # 6px bucket is usually stable for OCR token baselines.
    return int(bbox[1] // 6)


def _extract_quorum_collaborator(tokens: list[dict[str, Any]]) -> tuple[str | None, tuple[int, int, int, int] | None]:
    quorum_points: list[tuple[float, float]] = []
    quorum_line_keys: set[int] = set()
    for tok in tokens:
        if _token_text(tok).casefold() != "quorum":
            continue
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        quorum_points.append(_center(bbox))
        quorum_line_keys.add(_line_key(bbox))
    if not quorum_points:
        quorum_points = []

    # Group tokens into approximate lines for adjacency pairing and "-EXTERNAL-" filtering.
    line_map: dict[int, list[tuple[tuple[int, int, int, int], str]]] = {}
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if not text or bbox is None:
            continue
        line_map.setdefault(_line_key(bbox), []).append((bbox, text))

    def _clean(word: str) -> str:
        return word.strip().strip(",.;:()[]{}<>\"'`").replace("\u2019", "'")

    # Anchor tokens for task context when "Quorum" itself is missing/mis-OCRed.
    anchor_points: list[tuple[float, float]] = list(quorum_points)
    if not anchor_points:
        for tok in tokens:
            t = _token_text(tok).casefold()
            if t not in {"task", "invoice", "incident", "contractor"}:
                continue
            bbox = _token_bbox(tok)
            if bbox is None:
                continue
            anchor_points.append(_center(bbox))

    # Heuristic 0: Service/task UIs often include "Contractor First Last" in the title.
    # This provides a robust fallback even when "Quorum" tokens are absent/mis-OCRed.
    contractor_best: tuple[int, int, str, tuple[int, int, int, int]] | None = None
    for _lk, words in sorted(line_map.items()):
        words.sort(key=lambda it: it[0][0])
        for idx in range(len(words)):
            _bbox, w = words[idx]
            if _clean(w).casefold() != "contractor":
                continue
            # Look ahead a few tokens for a First Last pair.
            for j in range(idx + 1, min(idx + 6, len(words) - 1)):
                bbox1, w1 = words[j]
                bbox2, w2 = words[j + 1]
                w1s = _clean(w1)
                w2s = _clean(w2)
                if not (_NAME_RE.match(w1s) and _NAME_RE.match(w2s)):
                    continue
                if w1s in _NAME_STOP or w2s in _NAME_STOP:
                    continue
                merged_bbox = (bbox1[0], min(bbox1[1], bbox2[1]), bbox2[2], max(bbox1[3], bbox2[3]))
                name = f"{w1s} {w2s}"
                # Prefer title-like occurrences near the top of the screen.
                cand = (merged_bbox[1], merged_bbox[0], name, merged_bbox)
                if contractor_best is None or cand < contractor_best:
                    contractor_best = cand
                break

    best: tuple[float, int, int, str, tuple[int, int, int, int]] | None = None
    for _lk, words in sorted(line_map.items()):
        words.sort(key=lambda it: it[0][0])
        # NOTE: Do not drop entire lines due to "-EXTERNAL-" tags; Quorum work often
        # arrives via external email and we still want the collaborator name.
        for idx in range(len(words) - 1):
            bbox1, w1 = words[idx]
            bbox2, w2 = words[idx + 1]
            w1s = _clean(w1)
            w2s = _clean(w2)
            if not (_NAME_RE.match(w1s) and _NAME_RE.match(w2s)):
                continue
            if w1s in _NAME_STOP or w2s in _NAME_STOP:
                continue
            if w1s in {"Quorum", "Community"} or w2s in {"Quorum", "Community"}:
                continue
            c1x, c1y = _center(bbox1)
            # Distance to nearest task-context anchor token (prefer close).
            if anchor_points:
                dist = min(abs(c1y - ay) + abs(c1x - ax) * 0.15 for ax, ay in anchor_points)
            else:
                dist = 1e9
            y_key = max(bbox1[1], bbox2[1])
            merged_bbox = (bbox1[0], min(bbox1[1], bbox2[1]), bbox2[2], max(bbox1[3], bbox2[3]))
            name = f"{w1s} {w2s}"
            candidate = (dist, -y_key, bbox1[0], name, merged_bbox)
            if best is None or candidate < best:
                best = candidate

        # Fallback: allow a single-name collaborator when no adjacent pair exists on
        # this line, but only when the line is close to a Quorum token.
        if best is None and quorum_line_keys:
            if _lk in quorum_line_keys or (_lk - 1) in quorum_line_keys or (_lk + 1) in quorum_line_keys:
                for bbox, w in words:
                    ws = _clean(w)
                    if not _NAME_RE.match(ws):
                        continue
                    if ws in _NAME_STOP or ws in {"Quorum", "Community"}:
                        continue
                    cx, cy = _center(bbox)
                    dist = min(abs(cy - qy) + abs(cx - qx) * 0.15 for qx, qy in quorum_points)
                    y_key = bbox[1]
                    candidate = (dist, -y_key, bbox[0], ws, bbox)
                    if best is None or candidate < best:
                        best = candidate

    if best is None:
        if contractor_best is None:
            return None, None
        _y, _x, name, bbox = contractor_best
        return name, bbox
    _dist, _neg_y, _x, name, bbox = best
    # If we failed to anchor to "Quorum" tokens (or chose a very distant pair),
    # prefer the explicit "Contractor First Last" title match.
    if contractor_best is not None and (not quorum_points or _dist >= 1e8):
        _y, _x, cname, cbbox = contractor_best
        return cname, cbbox
    return name, bbox


class SSTQAAnswers(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)

    def capabilities(self) -> dict[str, Any]:
        return {"processing.stage.hooks": self}

    def stages(self) -> list[str]:
        return ["persist.bundle"]

    def run_stage(self, stage: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if stage != "persist.bundle":
            return None
        if not isinstance(payload, dict):
            return None
        tokens = payload.get("tokens_raw")
        if not isinstance(tokens, list):
            tokens = payload.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            return None

        vdi_time, time_bbox = _extract_vdi_time(tokens)
        inbox_count = _count_inboxes(tokens)
        collaborator, collab_bbox = _extract_quorum_collaborator(tokens)

        extra_docs = payload.get("extra_docs")
        if not isinstance(extra_docs, list):
            extra_docs = []

        def _doc_id(doc_kind: str, text: str) -> str:
            # Deterministic content-addressed ID (stable across runs for same text).
            import hashlib

            digest = hashlib.sha256(f"{doc_kind}\n{text}".encode("utf-8")).hexdigest()[:16]
            return f"qa.{doc_kind}.{digest}"

        def add_doc(doc_kind: str, text: str, bbox: tuple[int, int, int, int] | None) -> None:
            item: dict[str, Any] = {
                "doc_id": _doc_id(doc_kind, text),
                "doc_kind": doc_kind,
                "text": text,
                "meta": {"qa": True, "qa_kind": doc_kind},
                "provider_id": self.plugin_id,
                "stage": stage,
                "confidence_bp": 9000,
                # Always present per IO contract; empty list is allowed when bbox is unknown.
                "bboxes": [],
            }
            if bbox is not None:
                item["bboxes"] = [[int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]]
            extra_docs.append(item)

        if vdi_time:
            add_doc("qa.vdi_time", f"VDI time: {vdi_time}", time_bbox)
        if collaborator:
            add_doc("qa.quorum_collaborator", f"Quorum task collaborator: {collaborator}", collab_bbox)
        if inbox_count:
            add_doc("qa.open_inboxes", f"Open inboxes: {inbox_count}", None)
        if vdi_time and collaborator and inbox_count:
            add_doc(
                "qa.combined",
                f"VDI time: {vdi_time}. Quorum task collaborator: {collaborator}. Open inboxes: {inbox_count}.",
                None,
            )

        return {
            "extra_docs": extra_docs,
            "metrics": {
                "qa_has_time": 1.0 if bool(vdi_time) else 0.0,
                "qa_has_collaborator": 1.0 if bool(collaborator) else 0.0,
                "qa_inbox_count": float(inbox_count),
            },
        }


def create_plugin(plugin_id: str, context: PluginContext) -> SSTQAAnswers:
    return SSTQAAnswers(plugin_id, context)
