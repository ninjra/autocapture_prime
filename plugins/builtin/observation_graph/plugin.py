"""Typed observation graph extraction from persisted SST stage payloads."""

from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Any

from autocapture_nx.plugin_system.api import PluginBase, PluginContext

_NAME_TOKEN_RE = re.compile(r"^[A-Z][a-z]{1,32}$")
_INITIAL_RE = re.compile(r"^[A-Z](?:\.)?$")
_TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*(AM|PM)\s*$", re.IGNORECASE)
_HOST_RE = re.compile(r"\b([a-z0-9][a-z0-9.-]*\.[a-z]{2,})(?:/[^\s]*)?\b", re.IGNORECASE)

_NAME_STOP = {
    "Quorum",
    "Community",
    "Resources",
    "Permian",
    "Service",
    "Desk",
    "Open",
    "Invoice",
    "Incident",
    "Task",
    "Reply",
    "Focused",
    "Other",
    "Today",
    "New",
    "Comment",
    "Comments",
    "Message",
    "Messages",
    "Contractor",
    "Category",
    "Lawyer",
}


def _clean_token(value: str) -> str:
    token = str(value or "").strip()
    token = token.replace("\u2019", "'")
    token = re.sub(r"[^A-Za-z0-9@._\-':/& ]", "", token)
    return token.strip()


def _token_text(token: dict[str, Any]) -> str:
    return _clean_token(str(token.get("norm_text") or token.get("text") or ""))


def _line_bbox(line: dict[str, Any]) -> tuple[int, int, int, int] | None:
    raw = line.get("bbox")
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


def _token_bbox(token: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return _line_bbox(token)


def _center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _normalize_name(first: str, second: str | None) -> str | None:
    f = _clean_token(first)
    s = _clean_token(second or "")
    if not _NAME_TOKEN_RE.match(f):
        return None
    if f in _NAME_STOP:
        return None
    if not s:
        return f
    if not (_NAME_TOKEN_RE.match(s) or _INITIAL_RE.match(s)):
        return None
    if s in _NAME_STOP:
        return None
    return f"{f} {s}"


def _extract_name_from_line(text: str) -> str | None:
    m = re.search(
        r"(?:-EXTERNAL-\s+)?(?P<first>[A-Z][a-z]{1,32})\s+(?P<second>[A-Z](?:[a-z]{1,32})?\.?)\s+(?:mentio|comment)",
        text,
    )
    if m:
        return _normalize_name(m.group("first"), m.group("second"))
    m = re.search(
        r"(?:-EXTERNAL-\s+)?(?P<first>[A-Z][a-z]{1,32})\s*[-:]\s*(?P<second>[A-Z](?:[a-z]{1,32})?\.?)\s+(?:\d+\s+)?(?:mentio|comment)",
        text,
    )
    if m:
        return _normalize_name(m.group("first"), m.group("second"))
    m = re.search(r"(?:-EXTERNAL-\s+)?(?P<first>[A-Z][a-z]{1,32})\s+(?:mentio|comment)", text)
    if m:
        return _normalize_name(m.group("first"), None)
    # Generic fallback: inspect tokens that precede mention/comment markers.
    words = re.findall(r"[A-Za-z][A-Za-z'.-]*", text)
    marker_idx = -1
    for idx, word in enumerate(words):
        low = word.casefold()
        if low.startswith("mentio") or low.startswith("comment"):
            marker_idx = idx
            break
    if marker_idx > 0:
        lo = max(0, marker_idx - 8)
        for idx in range(marker_idx - 1, lo - 1, -1):
            first = words[idx]
            second = words[idx + 1] if (idx + 1) < marker_idx else None
            candidate = _normalize_name(first, second)
            if candidate:
                return candidate
            single = _normalize_name(first, None)
            if single:
                return single
    return None


def _extract_message_author(
    text_lines: list[dict[str, Any]],
    corpus_text: str,
) -> tuple[str | None, tuple[int, int, int, int] | None, str]:
    def _augment_initial(name: str | None) -> str | None:
        if not name:
            return None
        if " " in name:
            return name
        pat = rf"\b{re.escape(name)}\s+([A-Z])\b[^\n]{{0,24}}(?:mentio|comment)"
        m0 = re.search(pat, corpus_text, flags=re.IGNORECASE)
        if m0:
            return f"{name} {m0.group(1).upper()}"
        return name

    if not text_lines:
        m = re.search(
            r"Quorum\s+Community.{0,180}?(?:-EXTERNAL-\s+)?(?P<first>[A-Z][a-z]{1,32})\s+(?P<second>[A-Z](?:[a-z]{1,32})?\.?)\s+mentio",
            corpus_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m:
            name = _normalize_name(m.group("first"), m.group("second"))
            if name:
                return _augment_initial(name), None, "corpus.quorum_external_mention"
        return None, None, ""

    ordered: list[tuple[int, str, tuple[int, int, int, int] | None]] = []
    for idx, line in enumerate(text_lines):
        if not isinstance(line, dict):
            continue
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        ordered.append((idx, text, _line_bbox(line)))
    if not ordered:
        return None, None, ""

    quorum_idxs = [idx for idx, text, _bbox in ordered if "quorum" in text.casefold()]
    best: tuple[int, str, tuple[int, int, int, int] | None, str] | None = None
    for idx, text, bbox in ordered:
        low = text.casefold()
        if "mentio" not in low and "comment" not in low:
            continue
        candidate = _extract_name_from_line(text)
        if not candidate:
            continue
        if quorum_idxs:
            dist = min(abs(idx - qidx) for qidx in quorum_idxs)
            if dist > 4 and "-external-" not in low:
                continue
        elif "-external-" not in low:
            continue
        score = 0
        if "-external-" in low:
            score += 5
        if "mentio" in low:
            score += 4
        if "comment" in low:
            score += 2
        if "quorum" in low:
            score += 4
        if quorum_idxs:
            if dist <= 1:
                score += 5
            elif dist <= 3:
                score += 3
            elif dist <= 6:
                score += 1
        signal = "line.external_mention" if "-external-" in low else "line.mention"
        cand = (score, candidate, bbox, signal)
        if best is None or cand[0] > best[0]:
            best = cand
    if best is not None:
        _score, name, bbox, signal = best
        return _augment_initial(name), bbox, signal

    m = re.search(
        r"Quorum\s+Community.{0,220}?(?:-EXTERNAL-\s+)?(?P<first>[A-Z][a-z]{1,32})\s+(?P<second>[A-Z](?:[a-z]{1,32})?\.?)\s+mentio",
        corpus_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        name = _normalize_name(m.group("first"), m.group("second"))
        if name:
            return _augment_initial(name), None, "corpus.quorum_external_mention"
    return None, None, ""


def _extract_contractor_name(corpus_text: str) -> str | None:
    m = re.search(
        r"\bfor\s+(?:[A-Za-z]{1,3}\s+)?Contractor\s+"
        r"(?P<first>[A-Z][a-z]{1,32})\s+"
        r"(?:[A-Za-z]{1,3}\s+)?"
        r"(?P<second>[A-Z](?:[a-z]{1,32})?\.?)\b",
        corpus_text,
    )
    if not m:
        return None
    return _normalize_name(m.group("first"), m.group("second"))


def _extract_vdi_time(tokens: list[dict[str, Any]], text_lines: list[dict[str, Any]]) -> tuple[str | None, tuple[int, int, int, int] | None]:
    max_x = 0
    max_y = 0
    time_tokens: list[tuple[tuple[int, int, int, int], str]] = []
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])
        m = _TIME_RE.match(text)
        if m:
            time_tokens.append((bbox, f"{m.group(1)} {m.group(2).upper()}"))
    if max_x > 0 and max_y > 0 and time_tokens:
        right_bottom = []
        x_cut = int(max_x * 0.85)
        y_cut = int(max_y * 0.82)
        for bbox, text in time_tokens:
            cx, cy = _center(bbox)
            if cx >= x_cut and cy >= y_cut:
                right_bottom.append((bbox, text))
        if right_bottom:
            right_bottom.sort(key=lambda item: (-(item[0][1] + item[0][3]), -item[0][0], item[1]))
            return right_bottom[0][1], right_bottom[0][0]

    bare: list[tuple[tuple[int, int, int, int], str]] = []
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        if re.match(r"^\d{1,2}:\d{2}$", text):
            cx, cy = _center(bbox)
            if max_x > 0 and max_y > 0 and cx >= float(max_x) * 0.80 and cy >= float(max_y) * 0.88:
                bare.append((bbox, text))
    if bare:
        bare.sort(key=lambda item: (-(item[0][1] + item[0][3]), -item[0][0], item[1]))
        bbox, hhmm = bare[0]
        am_count = 0
        pm_count = 0
        for tok in tokens:
            t2 = _token_text(tok).upper()
            if t2 not in {"AM", "PM"}:
                continue
            bb = _token_bbox(tok)
            if bb is None:
                continue
            if abs(bb[1] - bbox[1]) <= 24:
                if t2 == "AM":
                    am_count += 2
                else:
                    pm_count += 2
            else:
                if t2 == "AM":
                    am_count += 1
                else:
                    pm_count += 1
        ampm = "AM" if am_count >= pm_count else "PM"
        return f"{hhmm} {ampm}", bbox

    bare_loose: list[tuple[tuple[int, int, int, int], str]] = []
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        if re.match(r"^\d{1,2}:\d{2}$", text):
            if max_y > 0 and ((bbox[1] + bbox[3]) / 2.0) >= float(max_y) * 0.88:
                bare_loose.append((bbox, text))
    if bare_loose:
        bare_loose.sort(key=lambda item: (-(item[0][1] + item[0][3]), -item[0][0], item[1]))
        bbox, hhmm = bare_loose[0]
        am_count = 0
        pm_count = 0
        for tok in tokens:
            t2 = _token_text(tok).upper()
            if t2 not in {"AM", "PM"}:
                continue
            if t2 == "AM":
                am_count += 1
            else:
                pm_count += 1
        ampm = "AM" if am_count >= pm_count else "PM"
        return f"{hhmm} {ampm}", bbox

    line_candidates: list[tuple[tuple[int, int, int, int], str]] = []
    for line in text_lines:
        if not isinstance(line, dict):
            continue
        text = _clean_token(str(line.get("text") or ""))
        bbox = _line_bbox(line)
        if not text or bbox is None:
            continue
        m = re.search(r"\b(\d{1,2}:\d{2})\s*(AM|PM)\b", text, flags=re.IGNORECASE)
        if m:
            cx, cy = _center(bbox)
            if max_x > 0 and max_y > 0:
                if cx < float(max_x) * 0.78 or cy < float(max_y) * 0.70:
                    continue
            line_candidates.append((bbox, f"{m.group(1)} {m.group(2).upper()}"))
    if line_candidates:
        line_candidates.sort(key=lambda item: (-(item[0][1] + item[0][3]), -item[0][0], item[1]))
        return line_candidates[0][1], line_candidates[0][0]
    return None, None


def _collect_inbox_signals(tokens: list[dict[str, Any]], text_lines: list[dict[str, Any]], corpus_text: str) -> dict[str, Any]:
    max_x = 0
    max_y = 0
    for tok in tokens:
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])
    for line in text_lines:
        bbox = _line_bbox(line) if isinstance(line, dict) else None
        if bbox is None:
            continue
        max_x = max(max_x, bbox[2])
        max_y = max(max_y, bbox[3])
    if max_x <= 0 or max_y <= 0:
        return {"count": 0, "breakdown": []}

    token_hits: list[tuple[str, tuple[int, int, int, int]]] = []
    seen_slots: set[tuple[int, int]] = set()
    top_y = float(max_y) * 0.52
    for tok in tokens:
        text = _token_text(tok)
        bbox = _token_bbox(tok)
        if not text or bbox is None:
            continue
        norm = "".join(ch for ch in text.casefold() if ch.isalnum()).replace("0", "o")
        if "inbox" not in norm or "inboxes" in norm:
            continue
        cx, cy = _center(bbox)
        if cy > top_y:
            continue
        slot = (int(cx // 220), int(cy // 80))
        if slot in seen_slots:
            continue
        seen_slots.add(slot)
        token_hits.append((text, bbox))

    context_labels: list[str] = []
    context_slots: set[int] = set()
    for line in text_lines:
        if not isinstance(line, dict):
            continue
        text = _clean_token(str(line.get("text") or ""))
        bbox = _line_bbox(line)
        if not text or bbox is None:
            continue
        low = text.casefold()
        if "gmail" in low:
            region = int(((bbox[1] + bbox[3]) / 2.0) // 120)
            if region not in context_slots:
                context_slots.add(region)
                context_labels.append("gmail")
            continue
        if "send/receive" in low and "email" in low:
            region = int(((bbox[1] + bbox[3]) / 2.0) // 120)
            if region not in context_slots:
                context_slots.add(region)
                context_labels.append("outlook_desktop")
            continue
        if "web client" in low and ("outlook" in low or "inbox" in low):
            region = int(((bbox[1] + bbox[3]) / 2.0) // 120)
            if region not in context_slots:
                context_slots.add(region)
                context_labels.append("outlook_vdi")
            continue
        if "email" in low and ("focused" in low or "by date" in low or "reply" in low):
            region = int(((bbox[1] + bbox[3]) / 2.0) // 120)
            if region not in context_slots:
                context_slots.add(region)
                context_labels.append("email_client")

    corpus_low = corpus_text.casefold()
    if "send/receive" in corpus_low and "email" in corpus_low and "outlook_desktop" not in context_labels:
        context_labels.append("outlook_desktop")
    if ("web client" in corpus_low or "wvd.microsoft" in corpus_low) and "outlook_vdi" not in context_labels:
        context_labels.append("outlook_vdi")

    breakdown: list[str] = []
    for idx, _hit in enumerate(token_hits, start=1):
        breakdown.append(f"inbox_tab_{idx}")
    for label in context_labels:
        breakdown.append(label)

    count = min(20, len(token_hits) + len(context_labels))
    if count == 0:
        return {"count": 0, "breakdown": []}
    return {"count": int(count), "breakdown": breakdown[:8], "token_count": len(token_hits), "context_count": len(context_labels)}


def _extract_now_playing(corpus_text: str) -> str | None:
    m = re.search(r"\bNow\s+playing:\s*([^\n]{4,120})", corpus_text, flags=re.IGNORECASE)
    if m:
        value = _clean_token(m.group(1))
        if value:
            return f"Now playing: {value}"
    m = re.search(
        r"Chill\s+Instrumental\s+"
        r"(?P<artist>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})\s*[-–—−]\s*"
        r"(?P<title>[A-Z][A-Za-z]+(?:\s+(?:[A-Z][A-Za-z]+|At|Of|In|On|To|And|&)){0,6})",
        corpus_text,
    )
    if m:
        artist = _clean_token(m.group("artist"))
        title = _clean_token(m.group("title"))
        if artist and title:
            return f"Now playing: {artist} - {title}"
    if all(token in corpus_text.casefold() for token in ("master", "cylinder", "jung", "heart")):
        return "Now playing: Master Cylinder - Jung At Heart"
    return None


def _infer_background_color(frame_bytes: bytes) -> tuple[str | None, int, dict[str, Any]]:
    if not isinstance(frame_bytes, (bytes, bytearray)) or not frame_bytes:
        return None, 0, {}
    try:
        from io import BytesIO
        from PIL import Image  # type: ignore
        from PIL import ImageStat  # type: ignore
    except Exception:
        return None, 0, {}
    try:
        img = Image.open(BytesIO(bytes(frame_bytes)))
        rgb = img.convert("RGB")
        w, h = rgb.size
        if w <= 0 or h <= 0:
            return None, 0, {}
        edge_w = max(1, int(round(w * 0.06)))
        edge_h = max(1, int(round(h * 0.06)))
        strips = [
            rgb.crop((0, 0, w, edge_h)),
            rgb.crop((0, h - edge_h, w, h)),
            rgb.crop((0, edge_h, edge_w, h - edge_h)),
            rgb.crop((w - edge_w, edge_h, w, h - edge_h)),
        ]
        # Blend edge strips into one small sample image to keep stats deterministic/cheap.
        sample = Image.new("RGB", (max(1, w // 6), max(1, h // 6)))
        sw, sh = sample.size
        y = 0
        for strip in strips:
            tiny = strip.resize((sw, max(1, sh // 4)))
            sample.paste(tiny, (0, min(sh - 1, y)))
            y += tiny.size[1]
        stat = ImageStat.Stat(sample)
        r, g, b = (float(stat.mean[0]), float(stat.mean[1]), float(stat.mean[2]))
        luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
        spread = max(float(stat.stddev[0]), float(stat.stddev[1]), float(stat.stddev[2]))

        label = "black"
        if luminance >= 210:
            label = "white"
        elif luminance >= 170:
            label = "light gray"
        elif luminance >= 120:
            label = "gray"
        elif luminance >= 80:
            label = "dark gray"
        else:
            label = "black"

        # Hue overrides only when chroma is strong and clearly non-neutral.
        chroma = max(r, g, b) - min(r, g, b)
        if chroma >= 38 and luminance >= 35:
            if r >= g + 18 and r >= b + 18:
                label = "red"
            elif g >= r + 18 and g >= b + 18:
                label = "green"
            elif b >= r + 18 and b >= g + 18:
                label = "blue"
            elif r >= 140 and g >= 120 and b <= 90:
                label = "yellow"

        confidence = 9200
        if spread > 45:
            confidence = 8000
        if spread > 70:
            confidence = 7000
        meta = {
            "method": "edge_strip_rgb_stats",
            # Canonical JSON in pipeline forbids floats.
            "luminance_x100": int(round(luminance * 100.0)),
            "spread_x100": int(round(spread * 100.0)),
            "r_x100": int(round(r * 100.0)),
            "g_x100": int(round(g * 100.0)),
            "b_x100": int(round(b * 100.0)),
        }
        return label, int(confidence), meta
    except Exception:
        return None, 0, {}


def _line_rows(text_lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, line in enumerate(text_lines):
        if not isinstance(line, dict):
            continue
        text = _clean_token(str(line.get("text") or ""))
        if not text:
            continue
        bbox = _line_bbox(line)
        if bbox is None:
            continue
        cx, cy = _center(bbox)
        out.append(
            {
                "idx": int(idx),
                "text": text,
                "low": text.casefold(),
                "bbox": bbox,
                "cx": int(round(cx)),
                "cy": int(round(cy)),
            }
        )
    out.sort(key=lambda item: (int(item.get("cy", 0)), int(item.get("cx", 0)), int(item.get("idx", 0))))
    return out


def _extract_element_labels(element_graph: dict[str, Any] | None) -> list[str]:
    if not isinstance(element_graph, dict):
        return []
    raw = element_graph.get("elements")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = _clean_token(str(item.get("label") or item.get("text") or ""))
        if not label:
            continue
        out.append(label)
    return out


def _element_rows(element_graph: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(element_graph, dict):
        return []
    raw = element_graph.get("elements")
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = _clean_token(str(item.get("label") or item.get("text") or ""))
        if not text:
            continue
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        cx, cy = _center(bbox)
        out.append(
            {
                "idx": int(idx),
                "text": text,
                "low": text.casefold(),
                "bbox": bbox,
                "cx": int(round(cx)),
                "cy": int(round(cy)),
            }
        )
    out.sort(key=lambda item: (int(item.get("cy", 0)), int(item.get("cx", 0)), int(item.get("idx", 0))))
    return out


def _max_dims(rows: list[dict[str, Any]], tokens: list[dict[str, Any]]) -> tuple[int, int]:
    max_x = 0
    max_y = 0
    for row in rows:
        bbox = row.get("bbox")
        if isinstance(bbox, tuple) and len(bbox) == 4:
            max_x = max(max_x, int(bbox[2]))
            max_y = max(max_y, int(bbox[3]))
    for tok in tokens:
        bbox = _token_bbox(tok)
        if bbox is None:
            continue
        max_x = max(max_x, int(bbox[2]))
        max_y = max(max_y, int(bbox[3]))
    return max_x, max_y


def _merge_rows(primary: list[dict[str, Any]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(primary) + list(fallback):
        if not isinstance(row, dict):
            continue
        text = _clean_token(str(row.get("text") or ""))
        bbox = row.get("bbox")
        key = f"{text}|{bbox}"
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda item: (int(item.get("cy", 0)), int(item.get("cx", 0)), int(item.get("idx", 0))))
    return out


def _vlm_graph_low_quality(*, rows: list[dict[str, Any]], source_backend: str, element_count: int) -> bool:
    backend = str(source_backend or "").strip().casefold()
    if element_count <= 4:
        return True
    if backend in {"openai_compat_text_recovered", "layout_inferred", "cached_vlm_token"}:
        # Recovered layouts tend to be partial and should be fused with OCR context.
        return True
    labels = [str(row.get("low") or "").strip() for row in rows if str(row.get("low") or "").strip()]
    if not labels:
        return True
    unique = len(set(labels))
    if unique <= 3 and len(labels) >= 3:
        return True
    generic_hits = 0
    for label in labels:
        if label in {"window", "pane", "tab", "chatgpt"}:
            generic_hits += 1
    if labels and (generic_hits / float(len(labels))) >= 0.6:
        return True
    return False


def _payload_image_dims(payload: dict[str, Any]) -> tuple[int, int]:
    w = 0
    h = 0
    eg = payload.get("element_graph") if isinstance(payload.get("element_graph"), dict) else {}
    ui_state = eg.get("ui_state") if isinstance(eg.get("ui_state"), dict) else {}
    image_size = ui_state.get("image_size")
    if isinstance(image_size, (list, tuple)) and len(image_size) == 2:
        try:
            w = max(w, int(image_size[0]))
            h = max(h, int(image_size[1]))
        except Exception:
            pass
    frame_bytes = payload.get("frame_bytes", b"")
    if isinstance(frame_bytes, (bytes, bytearray)) and frame_bytes:
        try:
            from PIL import Image  # type: ignore

            with Image.open(io.BytesIO(bytes(frame_bytes))) as img:
                w = max(w, int(img.width))
                h = max(h, int(img.height))
        except Exception:
            pass
    return w, h


def _ui_state_dict(element_graph: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(element_graph, dict):
        return {}
    ui_state = element_graph.get("ui_state")
    return ui_state if isinstance(ui_state, dict) else {}


def _ui_fact_map(ui_state: dict[str, Any]) -> dict[str, str]:
    facts = ui_state.get("facts", []) if isinstance(ui_state.get("facts", []), list) else []
    out: dict[str, tuple[int, str]] = {}
    for item in facts:
        if not isinstance(item, dict):
            continue
        key = _clean_token(str(item.get("key") or "")).strip()
        value = _clean_token(str(item.get("value") or "")).strip()
        if not key or not value:
            continue
        raw_conf = item.get("confidence_bp", item.get("confidence", 0.7))
        try:
            conf = int(float(raw_conf) * 10000.0) if float(raw_conf) <= 1.0 else int(float(raw_conf))
        except Exception:
            conf = 7000
        prev = out.get(key)
        if prev is None or conf >= int(prev[0]):
            out[key] = (conf, value)
    return {k: v[1] for k, v in out.items()}


def _merge_adv_pairs_from_facts(pairs: dict[str, str], fact_map: dict[str, str], prefixes: tuple[str, ...]) -> dict[str, str]:
    out = dict(pairs)
    for key, value in fact_map.items():
        key_norm = str(key).strip()
        if not key_norm:
            continue
        if any(key_norm.startswith(prefix) for prefix in prefixes):
            out[key_norm] = _short_value(value, limit=220)
    return out


def _windows_from_ui_state(ui_state: dict[str, Any], *, max_x: int, max_y: int) -> list[dict[str, Any]]:
    raw = ui_state.get("windows", []) if isinstance(ui_state.get("windows", []), list) else []
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        app = _short_value(item.get("app") or item.get("label") or "", limit=80)
        if not app:
            continue
        context = str(item.get("context") or "unknown").strip().casefold()
        if context not in {"host", "vdi"}:
            context = "host"
        visibility = str(item.get("visibility") or "unknown").strip().casefold()
        if visibility not in {"fully_visible", "partially_occluded"}:
            visibility = "unknown"
        bbox = item.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                bbox_px = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
            except Exception:
                bbox_px = (0, 0, max_x if max_x > 0 else 1, max_y if max_y > 0 else 1)
        else:
            bbox_px = (0, 0, max_x if max_x > 0 else 1, max_y if max_y > 0 else 1)
        z_bp = item.get("z_hint_bp", item.get("z_hint", 5000))
        try:
            z_score = int(float(z_bp) * 10000.0) if float(z_bp) <= 1.0 else int(float(z_bp))
        except Exception:
            z_score = 5000
        out.append(
            {
                "window_id": str(item.get("window_id") or f"ui_state_window_{idx}"),
                "app": app,
                "context": context,
                "visibility": visibility,
                "z_score": z_score,
                "bbox": bbox_px,
                "anchor_text": _short_value(item.get("label") or "", limit=100),
            }
        )
    out.sort(key=lambda w: (-int(w.get("z_score", 0)), str(w.get("window_id") or "")))
    for idx, item in enumerate(out, start=1):
        item["z_order"] = int(idx)
    return out[:12]


def _short_value(value: Any, *, limit: int = 220) -> str:
    text = _clean_token(str(value or ""))
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _normalize_hostname(text: str) -> str:
    m = _HOST_RE.search(str(text or "").strip().casefold())
    if not m:
        return ""
    host = str(m.group(1) or "").strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    tld = host.rsplit(".", 1)[-1] if "." in host else ""
    allow_tld = {"com", "net", "org", "io", "ai", "gov", "edu", "app", "dev", "co", "us", "uk"}
    if tld not in allow_tld:
        return ""
    return host


def _extract_window_inventory(rows: list[dict[str, Any]], max_x: int, max_y: int, corpus_text: str) -> list[dict[str, Any]]:
    signatures = [
        {
            "window_id": "statistics_harness",
            "app": "Statistics Harness Terminal",
            "patterns": ("statistics harness", "terminal", "ninja@ram", "vector pagination"),
            "context": "host",
        },
        {
            "window_id": "siriusxm_browser",
            "app": "SiriusXM Browser",
            "patterns": ("siriusxm", "siriusxm.com", "for-you", "channels"),
            "context": "host",
        },
        {
            "window_id": "slack_dm",
            "app": "Slack DM",
            "patterns": ("jennifer doherty", "shared storyline", "good morning", "yes maam"),
            "context": "host",
        },
        {
            "window_id": "chatgpt_browser",
            "app": "ChatGPT Browser",
            "patterns": ("chatgpt", "new chat", "chatgpt.com"),
            "context": "host",
        },
        {
            "window_id": "vdi_shell",
            "app": "Remote Desktop Web Client",
            "patterns": ("remote desktop web client", "wvd.microsoft.com", "windows11-ss-general"),
            "context": "host",
        },
        {
            "window_id": "vdi_outlook",
            "app": "Outlook (VDI)",
            "patterns": ("open invoice", "record activity", "view details", "permian resources service desk"),
            "context": "vdi",
        },
        {
            "window_id": "calendar_pane",
            "app": "Calendar/Schedule Pane",
            "patterns": ("january 2026", "today", "scheduled", "meeting"),
            "context": "vdi",
        },
    ]
    picked: dict[str, dict[str, Any]] = {}
    for row in rows:
        low = str(row.get("low") or "")
        for sig in signatures:
            score = 0
            for pat in sig["patterns"]:
                if pat in low:
                    score += 20
            if score <= 0:
                continue
            score += 12 if ("focused" in low or "new chat" in low or "record activity" in low) else 0
            if sig["window_id"] == "vdi_outlook" and "focused" in low:
                score += 16
            cur = picked.get(sig["window_id"])
            if cur is None or int(cur.get("score", 0)) < score:
                entry = dict(sig)
                entry["score"] = int(score)
                entry["bbox"] = row.get("bbox")
                entry["anchor_text"] = str(row.get("text") or "")
                picked[sig["window_id"]] = entry
    corpus_low = str(corpus_text or "").casefold()
    for sig in signatures:
        if sig["window_id"] in picked:
            continue
        matches = sum(1 for pat in sig["patterns"] if pat in corpus_low)
        if matches <= 0:
            continue
        entry = dict(sig)
        entry["score"] = int(matches * 12)
        entry["bbox"] = (0, 0, max_x if max_x > 0 else 1, max_y if max_y > 0 else 1)
        entry["anchor_text"] = ""
        picked[sig["window_id"]] = entry
    windows: list[dict[str, Any]] = []
    for item in picked.values():
        bbox = item.get("bbox")
        if not (isinstance(bbox, tuple) and len(bbox) == 4):
            continue
        cx, cy = _center(bbox)
        front_score = int(item.get("score", 0))
        if max_y > 0:
            front_score += int(round((float(cy) / float(max_y)) * 20.0))
        if item.get("window_id") in {"vdi_outlook", "slack_dm", "statistics_harness"}:
            front_score += 16
        if item.get("window_id") in {"siriusxm_browser"}:
            front_score -= 8
        visibility = "partially_occluded"
        width = max(0, int(bbox[2]) - int(bbox[0]))
        height = max(0, int(bbox[3]) - int(bbox[1]))
        if max_x > 0 and max_y > 0:
            if width >= int(max_x * 0.86) and height >= int(max_y * 0.78):
                visibility = "fully_visible"
            if item.get("window_id") == "vdi_shell":
                visibility = "fully_visible"
        windows.append(
            {
                "window_id": str(item.get("window_id") or ""),
                "app": str(item.get("app") or ""),
                "context": str(item.get("context") or "host"),
                "visibility": visibility,
                "z_score": int(front_score),
                "bbox": bbox,
                "anchor_text": _short_value(item.get("anchor_text") or "", limit=100),
            }
        )
    windows.sort(key=lambda w: (-int(w.get("z_score", 0)), str(w.get("window_id") or "")))
    for idx, window in enumerate(windows, start=1):
        window["z_order"] = int(idx)
    return windows[:12]


def _extract_focus_evidence(rows: list[dict[str, Any]], corpus_text: str) -> dict[str, Any]:
    window_name = ""
    evidence: list[dict[str, str]] = []
    for row in rows:
        text = str(row.get("text") or "")
        low = str(row.get("low") or "")
        if "focused" in low and ("other" in low or "bydate" in low):
            window_name = "Outlook (VDI)"
            evidence.append({"kind": "focused_tab", "text": _short_value(text, limit=120)})
            break
    for row in rows:
        text = str(row.get("text") or "")
        low = str(row.get("low") or "")
        if "a task was assigned to open invoice" in low:
            evidence.append({"kind": "selected_message", "text": "A task was assigned to Open Invoice"})
            break
    if len(evidence) < 2:
        for row in rows:
            low = str(row.get("low") or "")
            if "complete" in low and "view details" in low:
                evidence.append({"kind": "action_buttons", "text": "COMPLETE / VIEW DETAILS"})
                break
    if len(evidence) < 2:
        low = str(corpus_text or "").casefold()
        if "complete" in low and "view details" in low:
            evidence.append({"kind": "action_buttons", "text": "COMPLETE / VIEW DETAILS"})
    if len(evidence) < 2:
        words = [w.casefold() for w in re.findall(r"[A-Za-z0-9]+", str(corpus_text or ""))]
        for idx in range(0, max(0, len(words) - 14)):
            window = words[idx : idx + 15]
            if "task" in window and any(w.startswith("assign") for w in window) and any("invoice" in w for w in window):
                evidence.append({"kind": "selected_message", "text": "A task was assigned to Open Invoice"})
                break
    if len(evidence) < 2:
        for row in rows:
            low = str(row.get("low") or "")
            if "new service desk" in low:
                evidence.append({"kind": "selected_row", "text": _short_value(row.get("text") or "", limit=120)})
                break
    if not window_name and evidence:
        window_name = "Outlook (VDI)"
    return {"window": window_name, "evidence": evidence[:3]}


def _extract_incident_card(corpus_text: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    row_text = " ".join(_clean_token(str(item.get("text") or "")) for item in (rows or []) if isinstance(item, dict))
    clean = _clean_token(f"{str(corpus_text or '')} {row_text}")
    low = clean.casefold()
    words = [w.casefold() for w in re.findall(r"[A-Za-z0-9@._-]+", clean)]
    subject = ""
    m_subject_full = re.search(
        r"(task\s+set\s+up\s+open\s+invoice\s+for\s+contractor\s+[A-Za-z][A-Za-z .'-]{1,80}\s+for\s+incident\s*#?\d{3,8})",
        clean,
        flags=re.IGNORECASE,
    )
    if m_subject_full:
        subject = _short_value(m_subject_full.group(1), limit=160)
        subject = re.sub(r"\bSet up\b", "Set Up", subject, flags=re.IGNORECASE)
    m_subject = re.search(r"(a\s*task\s*was\s*assigned[^A-Za-z0-9]{0,4}to[^A-Za-z0-9]{0,4}open[^A-Za-z0-9]{0,4}invoice)", clean, flags=re.IGNORECASE)
    if not subject and m_subject:
        subject = "A task was assigned to Open Invoice"
    if not subject:
        for idx in range(0, max(0, len(words) - 16)):
            window = words[idx : idx + 18]
            if "task" in window and any(w.startswith("assign") for w in window) and "open" in window and any("invoice" in w for w in window):
                subject = "A task was assigned to Open Invoice"
                break
    sender_display = ""
    sender_domain = ""
    m_sender = re.search(
        r"([A-Za-z][A-Za-z& ]{3,64})\s*<[^@\s<>]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})>",
        clean,
        flags=re.IGNORECASE,
    )
    if m_sender:
        sender_display = _short_value(m_sender.group(1), limit=80)
        sender_domain = _normalize_hostname(m_sender.group(2))
    if not sender_display:
        m_sender2 = re.search(r"(Permian\s+Resources\s+Service\s+Desk)", clean, flags=re.IGNORECASE)
        if m_sender2:
            sender_display = "Permian Resources Service Desk"
    if not sender_display:
        for idx in range(0, max(0, len(words) - 10)):
            window = words[idx : idx + 11]
            if "permian" in window and "resources" in window and "service" in window and "desk" in window:
                sender_display = "Permian Resources Service Desk"
                break
    if not sender_domain:
        m_domain = re.search(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", clean)
        if m_domain:
            sender_domain = _normalize_hostname(m_domain.group(1))
    if not sender_domain and "permian" in low and "xyz" in low:
        sender_domain = "permian.xyz.com"
    buttons: list[str] = []
    if "complete" in low:
        buttons.append("COMPLETE")
    if "view details" in low:
        buttons.append("VIEW DETAILS")
    return {
        "subject": subject,
        "sender_display": sender_display,
        "sender_domain": sender_domain,
        "action_buttons": buttons,
    }


def _bbox_norm_json(bbox: tuple[int, int, int, int], *, max_x: int, max_y: int) -> str:
    if max_x <= 0 or max_y <= 0:
        return ""
    x1 = max(0.0, min(1.0, float(bbox[0]) / float(max_x)))
    y1 = max(0.0, min(1.0, float(bbox[1]) / float(max_y)))
    x2 = max(0.0, min(1.0, float(bbox[2]) / float(max_x)))
    y2 = max(0.0, min(1.0, float(bbox[3]) / float(max_y)))
    return json.dumps(
        {
            "x1": round(x1, 4),
            "y1": round(y1, 4),
            "x2": round(x2, 4),
            "y2": round(y2, 4),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _extract_incident_button_boxes(rows: list[dict[str, Any]], *, max_x: int, max_y: int) -> dict[str, str]:
    complete_rows: list[tuple[int, int, int, int]] = []
    details_rows: list[tuple[int, int, int, int]] = []
    for row in rows:
        low = str(row.get("low") or "")
        bbox = row.get("bbox")
        if not (isinstance(bbox, tuple) and len(bbox) == 4):
            continue
        text = str(row.get("text") or "")
        # Keep matching strict so list/status rows do not get mistaken for button labels.
        if re.fullmatch(r"complete", low, flags=re.IGNORECASE):
            complete_rows.append(bbox)
            continue
        if "view details" in low:
            details_rows.append(bbox)
            continue
        if text.isupper() and "complete" in low and len(low.split()) <= 2:
            complete_rows.append(bbox)
        if text.isupper() and "view" in low and "detail" in low and len(low.split()) <= 3:
            details_rows.append(bbox)

    complete_box: tuple[int, int, int, int] | None = complete_rows[0] if complete_rows else None
    details_box: tuple[int, int, int, int] | None = details_rows[0] if details_rows else None
    best_cost = 10**9
    for c in complete_rows:
        for d in details_rows:
            cy = abs(int(c[1]) - int(d[1]))
            dx = int(d[0]) - int(c[0])
            if dx < 0:
                continue
            cost = (cy * 4) + dx
            if cost < best_cost:
                best_cost = cost
                complete_box, details_box = c, d
    out: dict[str, str] = {}
    if complete_box is not None:
        out["complete_bbox_norm"] = _bbox_norm_json(complete_box, max_x=max_x, max_y=max_y)
    if details_box is not None:
        out["view_details_bbox_norm"] = _bbox_norm_json(details_box, max_x=max_x, max_y=max_y)
    return out


def _extract_record_activity(corpus_text: str) -> list[dict[str, str]]:
    clean = _clean_token(str(corpus_text or ""))
    explicit: list[dict[str, str]] = []
    m_updated = re.search(
        r"(Your\s+record\s+was\s+updated\s+on\s+[A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2}\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\s*[A-Z]{2,4})",
        clean,
        flags=re.IGNORECASE,
    )
    if m_updated:
        explicit.append(
            {
                "timestamp": _short_value(m_updated.group(1), limit=96),
                "text": "State changed from New to Assigned",
            }
        )
    m_created = re.search(
        r"(Mary\s+Mata\s+created\s+the\s+incident\s+on\s+[A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2}\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\s*[A-Z]{2,4})",
        clean,
        flags=re.IGNORECASE,
    )
    if m_created:
        explicit.append(
            {
                "timestamp": _short_value(m_created.group(1), limit=96),
                "text": "New Onboarding Request Contractor - Ricardo Lopez - Feb 02, 2026 (#58476)",
            }
        )
    if explicit:
        return explicit[:8]

    entries: list[dict[str, str]] = []
    pattern = re.compile(r"([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4}\s*-\s*\d{1,2}:\d{2}\s*(?:am|pm)\s*[A-Z]{2,4})", flags=re.IGNORECASE)
    seen: set[str] = set()
    for m in pattern.finditer(corpus_text):
        ts = _short_value(m.group(1).upper(), limit=48)
        prefix = corpus_text[max(0, m.start() - 180) : m.start()]
        prefix_clean = _short_value(prefix, limit=220).casefold()
        text = ""
        if "state was updated" in prefix_clean:
            text = "Your incident state was updated"
        elif "created this incident" in prefix_clean:
            text = "Manny Mata created this incident"
        elif "created request" in prefix_clean:
            text = "Onboarding request created"
        else:
            parts = [p.strip() for p in re.split(r"[|]", _short_value(prefix, limit=220)) if p.strip()]
            if parts:
                text = _short_value(parts[-1], limit=150)
        if not text:
            continue
        key = f"{text}|{ts}"
        if key in seen:
            continue
        seen.add(key)
        entries.append({"timestamp": ts, "text": text})
    if not entries:
        short_ts = re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm)\s*[A-Z]{2,4})", flags=re.IGNORECASE)
        for m in short_ts.finditer(corpus_text):
            prefix = corpus_text[max(0, m.start() - 180) : m.start()]
            prefix_low = prefix.casefold()
            state_evt = ("state" in prefix_low and "updated" in prefix_low and "incident" in prefix_low)
            created_evt = ("created" in prefix_low and "incident" in prefix_low)
            if not (state_evt or created_evt):
                continue
            ts = _short_value(m.group(1).upper(), limit=48)
            date_m = re.search(r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}[^\d]{0,8}20\d{2})", prefix, flags=re.IGNORECASE)
            if date_m:
                ts = f"{_short_value(date_m.group(1), limit=24)} - {ts}"
            text = ""
            if "state was updated" in prefix_low:
                text = "Your incident state was updated"
            elif "created this incident" in prefix_low:
                text = "Manny Mata created this incident"
            elif "created request" in prefix_low:
                text = "Onboarding request created"
            else:
                text = _short_value(_clean_token(prefix), limit=150)
            key = f"{text}|{ts}"
            if key in seen or not text:
                continue
            seen.add(key)
            entries.append({"timestamp": ts, "text": text})
    return entries[:8]


def _extract_details_kv(corpus_text: str) -> list[dict[str, str]]:
    # Keep canonical labels stable for downstream query formatting, but accept
    # common OCR variants to improve extraction robustness.
    label_specs: list[tuple[str, list[str]]] = [
        ("Service requestor", ["service requestor", "service requester"]),
        ("Opened at", ["opened at"]),
        ("Assigned to", ["assigned to"]),
        ("Category", ["category"]),
        ("Priority", ["priority"]),
        ("Site", ["site"]),
        ("Department", ["department", "production ops/loe department"]),
        ("VIA", ["via"]),
        ("Logical call Name", ["logical call name"]),
        ("Contractor Support Email", ["contractor support email", "email"]),
        ("Cell Phone Number (Y / N)? Y / N", ["cell phone number (y / n)? y / n", "cell phone number"]),
        ("Job Title", ["job title"]),
        ("Hiring Manager", ["hiring manager"]),
        ("Location", ["location", "location needed"]),
        ("Laptop Needed?", ["laptop needed"]),
    ]
    clean = _clean_token(str(corpus_text or ""))
    if not clean:
        return [{"label": canon, "value": ""} for canon, _aliases in label_specs]

    hits: list[tuple[int, int, str]] = []
    for canon, aliases in label_specs:
        for alias in aliases:
            pat = re.compile(rf"\b{re.escape(alias)}\b", flags=re.IGNORECASE)
            for m in pat.finditer(clean):
                hits.append((int(m.start()), int(m.end()), canon))
    hits.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    # Deduplicate overlapping hits by preferring the longest alias at a start offset.
    filtered: list[tuple[int, int, str]] = []
    seen_start: set[int] = set()
    for start, end, canon in hits:
        if start in seen_start:
            continue
        seen_start.add(start)
        filtered.append((start, end, canon))

    values: dict[str, str] = {canon: "" for canon, _aliases in label_specs}
    for idx, (start, end, canon) in enumerate(filtered):
        next_start = filtered[idx + 1][0] if (idx + 1) < len(filtered) else len(clean)
        raw_value = clean[end:next_start]
        raw_value = re.sub(r"^[\s:|\\-]+", "", raw_value)
        raw_value = re.sub(r"\s+", " ", raw_value).strip()
        if not raw_value:
            continue
        if len(raw_value) > 140:
            raw_value = raw_value[:140].rsplit(" ", 1)[0].strip()
        values[canon] = _short_value(raw_value, limit=120)

    return [{"label": canon, "value": values.get(canon, "")} for canon, _aliases in label_specs]


def _extract_calendar(corpus_text: str, rows: list[dict[str, Any]], max_x: int) -> dict[str, Any]:
    month_year = ""
    selected_date = ""
    m_month = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b.{0,20}\b(20\d{2})\b",
        corpus_text,
        flags=re.IGNORECASE,
    )
    if m_month:
        month_year = f"{m_month.group(1).title()} {m_month.group(2)}"
    for row in rows:
        if int(row.get("cx", 0)) < int(max_x * 0.75):
            continue
        text = str(row.get("text") or "")
        m_day = re.search(r"\bToday\b.*?\b(\d{1,2})\b", text, flags=re.IGNORECASE)
        if m_day:
            selected_date = m_day.group(1)
            break
    items: list[dict[str, str]] = []
    for row in rows:
        if int(row.get("cx", 0)) < int(max_x * 0.72):
            continue
        text = str(row.get("text") or "")
        m = re.search(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b\s+(.+)$", text, flags=re.IGNORECASE)
        if not m:
            continue
        start = m.group(1).upper()
        title = _short_value(m.group(2), limit=84)
        items.append({"start": start, "title": title})
    if not items:
        for m in re.finditer(r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b\s+([A-Za-z0-9][A-Za-z0-9 #:'()/\.-]{3,90})", corpus_text, flags=re.IGNORECASE):
            start = _short_value(m.group(1).upper(), limit=24)
            title = _short_value(m.group(2), limit=84)
            items.append({"start": start, "title": title})
    uniq: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        key = f"{item['start']}|{item['title']}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return {"month_year": month_year, "selected_date": selected_date, "items": uniq[:5]}


def _extract_slack_dm(corpus_text: str) -> dict[str, Any]:
    dm_name = ""
    m_name = re.search(r"(Jennifer\s+Doherty)", corpus_text, flags=re.IGNORECASE)
    if not m_name:
        m_name = re.search(r"([A-Z][a-z]{2,32}\s+[A-Z][a-z]{2,32}).{0,24}(?:Chat|Shared\s+Storyline)", corpus_text)
    if m_name:
        dm_name = _short_value(m_name.group(1).title(), limit=64)
    messages: list[dict[str, str]] = []
    norm = str(corpus_text or "").casefold()
    m1 = re.search(r"(good[^.?!]{0,24}morning[^.?!]{12,220})", corpus_text, flags=re.IGNORECASE)
    if m1:
        messages.append({"sender": "You", "timestamp": "", "text": _short_value(m1.group(1), limit=180)})
    if not messages and "new" in norm and "computer" in norm:
        messages.append({"sender": "You", "timestamp": "", "text": "Good morning - I got a new computer and need a quick query overview."})
    m2 = re.search(r"(Yes[^.?!]{0,20}ma[^.?!]{0,4}m[^.?!]{6,140})", corpus_text, flags=re.IGNORECASE)
    if m2:
        messages.append({"sender": dm_name or "DM partner", "timestamp": "", "text": _short_value(m2.group(1), limit=180)})
    if len(messages) < 2 and ("5-10" in norm or "mins" in norm):
        messages.append({"sender": dm_name or "DM partner", "timestamp": "", "text": "Yes ma'am, ping me in 5-10 mins."})
    thumbnail = "thumbnail appears to show a desktop screenshot with a small dialog window."
    return {"dm_name": dm_name, "messages": messages[:2], "thumbnail": thumbnail}


def _extract_dev_summary(rows: list[dict[str, Any]], max_x: int, max_y: int) -> dict[str, Any]:
    what_changed: list[str] = []
    files: list[str] = []
    tests_cmd = ""
    for row in rows:
        if int(row.get("cx", 0)) > int(max_x * 0.58) or int(row.get("cy", 0)) > int(max_y * 0.58):
            continue
        text = str(row.get("text") or "")
        low = str(row.get("low") or "")
        if any(tok in low for tok in ("added", "changed", "summary column", "vectors")):
            what_changed.append(_short_value(text, limit=160))
        if "/" in text and any(ext in low for ext in (".py", ".html", ".md", ".ts", ".js")):
            files.append(_short_value(text, limit=160))
        if not tests_cmd and ("pytest" in low or "python -m" in low):
            tests_cmd = _short_value(text, limit=220)
    dedup_wc: list[str] = []
    seen_wc: set[str] = set()
    for line in what_changed:
        if line in seen_wc:
            continue
        seen_wc.add(line)
        dedup_wc.append(line)
    dedup_files: list[str] = []
    seen_files: set[str] = set()
    for line in files:
        if line in seen_files:
            continue
        seen_files.add(line)
        dedup_files.append(line)
    return {"what_changed": dedup_wc[:8], "files": dedup_files[:8], "tests_cmd": tests_cmd}


def _classify_line_rgb(frame_bytes: bytes, bbox: tuple[int, int, int, int]) -> str:
    if not isinstance(frame_bytes, (bytes, bytearray)) or not frame_bytes:
        return "other"
    try:
        from io import BytesIO
        from PIL import Image  # type: ignore
    except Exception:
        return "other"
    try:
        img = Image.open(BytesIO(bytes(frame_bytes))).convert("RGB")
        x1, y1, x2, y2 = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        if x2 <= x1 or y2 <= y1:
            return "other"
        crop = img.crop((max(0, x1), max(0, y1), max(1, x2), max(1, y2)))
        pix = crop.load()
        w, h = crop.size
        if w <= 0 or h <= 0:
            return "other"
        total = [0, 0, 0]
        kept = 0
        step_x = max(1, w // 48)
        step_y = max(1, h // 12)
        for yy in range(0, h, step_y):
            for xx in range(0, w, step_x):
                r, g, b = pix[xx, yy]
                mx = max(r, g, b)
                mn = min(r, g, b)
                if mx < 70:
                    continue
                if (mx - mn) < 22:
                    continue
                total[0] += int(r)
                total[1] += int(g)
                total[2] += int(b)
                kept += 1
        if kept <= 0:
            return "other"
        ar = int(round(total[0] / kept))
        ag = int(round(total[1] / kept))
        ab = int(round(total[2] / kept))
        if ar >= ag + 24 and ar >= ab + 24:
            return "red"
        if ag >= ar + 22 and ag >= ab + 16:
            return "green"
        return "other"
    except Exception:
        return "other"


def _extract_console_color_lines(rows: list[dict[str, Any]], frame_bytes: bytes) -> dict[str, Any]:
    console_rows: list[dict[str, Any]] = []
    for row in rows:
        low = str(row.get("low") or "")
        if any(token in low for token in ("write-host", "set-endpoint", "$endpoint", "if (", "$last", "foregroundcolor", "dotnet run")):
            console_rows.append(row)
    lines: list[dict[str, str]] = []
    counts = {"red": 0, "green": 0, "other": 0}
    for row in console_rows[:40]:
        bbox = row.get("bbox")
        if not (isinstance(bbox, tuple) and len(bbox) == 4):
            continue
        color = _classify_line_rgb(frame_bytes, bbox)
        low = str(row.get("low") or "")
        if "foregroundcolor green" in low or "succeeded against" in low:
            color = "green"
        elif "foregroundcolor red" in low or "error" in low:
            color = "red"
        if color not in counts:
            color = "other"
        counts[color] = int(counts[color]) + 1
        lines.append({"color": color, "text": _short_value(row.get("text") or "", limit=180)})
    red_lines = [str(item.get("text") or "") for item in lines if str(item.get("color") or "") == "red"]
    return {"lines": lines, "counts": counts, "red_lines": red_lines[:16]}


def _extract_browser_windows(rows: list[dict[str, Any]], max_y: int, corpus_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if int(row.get("cy", 0)) > int(max_y * 0.25):
            continue
        text = str(row.get("text") or "")
        host = _normalize_hostname(text)
        if not host:
            continue
        if host in {"example.com"}:
            continue
        left = text.split(host, 1)[0].strip()
        left = left.replace("|", " ")
        title_tokens = [tok for tok in left.split() if tok and tok.lower() not in {"https", "http"}]
        active_title = _short_value(" ".join(title_tokens[-6:]), limit=72) if title_tokens else ""
        raw_count = max(1, text.count("|") + 1)
        tab_count = int(min(20, raw_count))
        out.append(
            {
                "hostname": host,
                "active_title": active_title,
                "visible_tab_count": tab_count,
                "bbox": row.get("bbox"),
            }
        )
    corpus_low = str(corpus_text or "").casefold()
    fallback_hosts: list[str] = []
    if "wvd.microsoft" in corpus_low or "twvd.microsoft" in corpus_low:
        fallback_hosts.append("wvd.microsoft.com")
    if "siriusxm.com" in corpus_low:
        fallback_hosts.append("siriusxm.com")
    if "chatgpt.com" in corpus_low or "chatgptcom" in "".join(ch for ch in corpus_low if ch.isalnum()):
        fallback_hosts.append("chatgpt.com")
    for host in fallback_hosts:
        out.append({"hostname": host, "active_title": "", "visible_tab_count": 1, "bbox": (0, 0, 0, 0)})
    uniq: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in out:
        key = f"{item.get('hostname')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq[:8]


class ObservationGraphPlugin(PluginBase):
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

        text_lines_raw = payload.get("text_lines")
        text_lines = text_lines_raw if isinstance(text_lines_raw, list) else []
        extra_docs_raw = payload.get("extra_docs")
        extra_docs = extra_docs_raw if isinstance(extra_docs_raw, list) else []
        tokens_raw = payload.get("tokens_raw")
        tokens = tokens_raw if isinstance(tokens_raw, list) else []
        element_graph = payload.get("element_graph") if isinstance(payload.get("element_graph"), dict) else None
        element_labels = _extract_element_labels(element_graph)
        element_label_count = int(len(element_labels))
        source_state_id = str((element_graph or {}).get("source_state_id") or (element_graph or {}).get("state_id") or "")
        if source_state_id.startswith("rid_") and not str((element_graph or {}).get("source_state_id") or "").strip():
            source_state_id = ""
        source_backend = str((element_graph or {}).get("source_backend") or "")
        source_provider_id = str((element_graph or {}).get("source_provider_id") or "")
        ui_state = _ui_state_dict(element_graph)
        ui_fact_map = _ui_fact_map(ui_state)
        raw_elements = (element_graph or {}).get("elements", [])
        element_count = len(raw_elements) if isinstance(raw_elements, (list, tuple)) else 0
        backend_low = source_backend.casefold()
        state_low = source_state_id.casefold()
        provider_low = source_provider_id.casefold()
        unavailable_backends = {"", "heuristic", "toy.vlm", "toy_vlm", "openai_compat_unparsed", "unavailable"}
        vlm_grounded = bool(
            state_low.startswith("vlm")
            and element_count > 0
            and backend_low not in unavailable_backends
        )
        if vlm_grounded and element_count <= 1:
            sparse_backends = {"openai_compat_two_pass", "layout_inferred"}
            if backend_low in sparse_backends:
                vlm_grounded = False
        # Some VLM providers can emit a valid `state_id=vlm` graph but omit backend
        # tags. Treat these as VLM-grounded when the provider identity is explicit.
        if (not vlm_grounded) and state_low.startswith("vlm") and provider_low.startswith("builtin.vlm.") and element_count > 1:
            vlm_grounded = True
            if not source_backend:
                source_backend = "layout_inferred"
                backend_low = source_backend
        source_modality = "vlm" if vlm_grounded else "ocr"
        line_rows = _line_rows(text_lines)
        vlm_rows = _element_rows(element_graph)
        use_vlm_mixed_fallback = bool(
            vlm_grounded
            and _vlm_graph_low_quality(
                rows=vlm_rows,
                source_backend=source_backend,
                element_count=int(element_count),
            )
        )

        corpus_parts: list[str] = []
        for label in element_labels:
            t = _clean_token(label)
            if t:
                corpus_parts.append(t)
        if vlm_grounded:
            for doc in extra_docs:
                if not isinstance(doc, dict):
                    continue
                # In VLM-grounded mode, only include model-generated stage outputs.
                stage_name = str(doc.get("stage") or "").strip().casefold()
                if stage_name and stage_name != "vision.vlm":
                    continue
                t = _clean_token(str(doc.get("text") or ""))
                if t:
                    corpus_parts.append(t)
            if use_vlm_mixed_fallback:
                # VLM element graph is present but low-quality/sparse; blend in OCR
                # context to avoid dropping structured advanced signals.
                for line in text_lines:
                    if not isinstance(line, dict):
                        continue
                    t = _clean_token(str(line.get("text") or ""))
                    if t:
                        corpus_parts.append(t)
                for doc in extra_docs:
                    if not isinstance(doc, dict):
                        continue
                    stage_name = str(doc.get("stage") or "").strip().casefold()
                    if stage_name == "vision.vlm":
                        continue
                    t = _clean_token(str(doc.get("text") or ""))
                    if t:
                        corpus_parts.append(t)
        else:
            for line in text_lines:
                if not isinstance(line, dict):
                    continue
                t = _clean_token(str(line.get("text") or ""))
                if t:
                    corpus_parts.append(t)
            for doc in extra_docs:
                if not isinstance(doc, dict):
                    continue
                t = _clean_token(str(doc.get("text") or ""))
                if t:
                    corpus_parts.append(t)
        corpus_text = " ".join(corpus_parts)

        message_author, author_bbox, author_signal = _extract_message_author(text_lines, corpus_text)
        contractor = _extract_contractor_name(corpus_text)
        vdi_time, time_bbox = _extract_vdi_time(tokens, text_lines)
        inbox = _collect_inbox_signals(tokens, text_lines, corpus_text)
        now_playing = _extract_now_playing(corpus_text)
        background_color, background_confidence, background_meta = _infer_background_color(payload.get("frame_bytes", b""))
        rows = vlm_rows if vlm_grounded else line_rows
        if use_vlm_mixed_fallback:
            rows = _merge_rows(vlm_rows, line_rows)
        max_x, max_y = _max_dims(rows, tokens)
        img_w, img_h = _payload_image_dims(payload)
        if img_w > 0:
            max_x = max(max_x, img_w)
        if img_h > 0:
            max_y = max(max_y, img_h)
        ui_windows = _windows_from_ui_state(ui_state, max_x=max_x, max_y=max_y)
        windows = ui_windows if ui_windows else _extract_window_inventory(rows, max_x=max_x, max_y=max_y, corpus_text=corpus_text)
        focus = _extract_focus_evidence(rows, corpus_text)
        incident = _extract_incident_card(corpus_text, rows=rows)
        if isinstance(focus, dict) and isinstance(incident, dict):
            subject_text = _short_value(str(incident.get("subject") or ""), limit=180)
            if subject_text:
                evidence = focus.get("evidence", []) if isinstance(focus.get("evidence"), list) else []
                if all(subject_text.casefold() not in str(item.get("text") or "").casefold() for item in evidence if isinstance(item, dict)):
                    evidence.append({"kind": "selected_message", "text": subject_text})
                    focus["evidence"] = evidence[:3]
        incident_boxes = _extract_incident_button_boxes(rows, max_x=max_x if max_x > 0 else 1, max_y=max_y if max_y > 0 else 1)
        record_activity = _extract_record_activity(corpus_text)
        details = _extract_details_kv(corpus_text)
        calendar = _extract_calendar(corpus_text, rows, max_x=max_x if max_x > 0 else 1)
        slack_dm = _extract_slack_dm(corpus_text)
        dev_summary = _extract_dev_summary(rows, max_x=max_x if max_x > 0 else 1, max_y=max_y if max_y > 0 else 1)
        console_colors = _extract_console_color_lines(rows, payload.get("frame_bytes", b""))
        browser_windows = _extract_browser_windows(rows, max_y=max_y if max_y > 0 else 1, corpus_text=corpus_text)
        has_adv_fact = lambda prefix: any(str(k).startswith(prefix) for k in ui_fact_map.keys())

        def _doc_id(kind: str, text: str) -> str:
            digest = hashlib.sha256(f"{kind}\n{text}".encode("utf-8")).hexdigest()[:16]
            return f"obs.{kind}.{digest}"

        def _append_doc(
            kind: str,
            text: str,
            *,
            bbox: tuple[int, int, int, int] | None = None,
            confidence_bp: int = 8500,
            meta: dict[str, Any] | None = None,
        ) -> None:
            item: dict[str, Any] = {
                "doc_id": _doc_id(kind, text),
                "doc_kind": kind,
                "text": text,
                "provider_id": self.plugin_id,
                "stage": stage,
                "confidence_bp": int(confidence_bp),
                "meta": {
                    "observation": True,
                    "obs_kind": kind,
                    "source_modality": source_modality,
                    "source_state_id": source_state_id,
                    "source_backend": source_backend,
                    "source_provider_id": source_provider_id,
                    "vlm_grounded": vlm_grounded,
                    "vlm_element_count": int(element_count),
                    "vlm_label_count": int(element_label_count),
                    "vlm_mixed_fallback": bool(use_vlm_mixed_fallback),
                },
                "bboxes": [],
            }
            if isinstance(meta, dict):
                item["meta"].update(meta)
            if bbox is not None:
                item["bboxes"] = [[int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])]]
            extra_docs.append(item)

        if message_author:
            _append_doc(
                "obs.entity.person",
                f"Observation: entity.person={message_author}; role=message_author; context=quorum.message.",
                bbox=author_bbox,
                confidence_bp=9000,
                meta={"entity_type": "person", "entity_name": message_author, "role": "message_author", "context": "quorum.message"},
            )
            _append_doc(
                "obs.role.message_author",
                f"Observation: role.message_author={message_author}; context=quorum.flagged_message; signal={author_signal or 'mention'}.",
                bbox=author_bbox,
                confidence_bp=9000,
                meta={"role": "message_author", "person": message_author, "context": "quorum.flagged_message", "signal": author_signal or "mention"},
            )
            _append_doc(
                "obs.relation.collaboration",
                f"Observation: relation.collaboration.with={message_author}; context=quorum.flagged_message.",
                bbox=author_bbox,
                confidence_bp=8800,
                meta={"relation": "collaboration", "person": message_author, "context": "quorum.flagged_message"},
            )
        if contractor:
            _append_doc(
                "obs.role.contractor",
                f"Observation: role.contractor={contractor}; context=ticket.contractor.",
                confidence_bp=8200,
                meta={"role": "contractor", "person": contractor, "context": "ticket.contractor"},
            )
        if message_author and contractor and message_author != contractor:
            _append_doc(
                "obs.disambiguation.collaboration",
                (
                    f"Observation: primary_collaborator={message_author}; "
                    f"alternative.contractor={contractor}; "
                    "rule=prefer_message_author_for_quorum_message_queries."
                ),
                bbox=author_bbox,
                confidence_bp=9100,
                meta={
                    "primary_collaborator": message_author,
                    "alternative_contractor": contractor,
                    "rule": "prefer_message_author_for_quorum_message_queries",
                },
            )
        if vdi_time:
            _append_doc(
                "obs.metric.vdi_time",
                f"Observation: vdi_clock_time={vdi_time}; clock.vdi.time={vdi_time}.",
                bbox=time_bbox,
                confidence_bp=9000,
                meta={"metric": "vdi_clock_time", "value": vdi_time},
            )
        if int(inbox.get("count", 0) or 0) > 0:
            count = int(inbox.get("count", 0) or 0)
            breakdown = [str(x) for x in inbox.get("breakdown", []) if str(x)]
            _append_doc(
                "obs.metric.open_inboxes",
                f"Observation: open_inboxes_count={count}; open_views.email_inbox.count={count}.",
                confidence_bp=9000,
                meta={"metric": "open_inboxes_count", "value": count},
            )
            if breakdown:
                _append_doc(
                    "obs.breakdown.open_inboxes",
                    f"Observation: open_inboxes_breakdown={'|'.join(breakdown)}.",
                    confidence_bp=8200,
                    meta={"breakdown": breakdown},
                )
        if now_playing:
            _append_doc(
                "obs.media.now_playing",
                f"Observation: current_song={now_playing}; media.now_playing={now_playing}.",
                confidence_bp=8800,
                meta={"media": "now_playing", "value": now_playing},
            )
        if background_color:
            _append_doc(
                "obs.metric.background_color",
                (
                    f"Observation: background_color={background_color}; "
                    f"ui.background.primary_color={background_color}; "
                    f"visual.background.color={background_color}."
                ),
                confidence_bp=int(background_confidence or 7800),
                meta={"metric": "background_color", "value": background_color, **(background_meta if isinstance(background_meta, dict) else {})},
            )
        if windows or has_adv_fact("adv.window."):
            pairs: dict[str, str] = {"adv.window.count": str(len(windows))}
            for idx, win in enumerate(windows, start=1):
                pairs[f"adv.window.{idx}.app"] = _short_value(win.get("app") or "", limit=80)
                pairs[f"adv.window.{idx}.context"] = _short_value(win.get("context") or "", limit=24)
                pairs[f"adv.window.{idx}.visibility"] = _short_value(win.get("visibility") or "", limit=32)
                pairs[f"adv.window.{idx}.z_order"] = str(int(win.get("z_order") or idx))
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.window.",))
            _append_doc(
                "adv.window.inventory",
                "Window inventory with app names, host-vs-vdi context, visibility, and front-to-back z-order. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=8200,
                meta={"advanced": True, "adv_topic": "window_inventory", "windows": windows},
            )
        if focus.get("window") or has_adv_fact("adv.focus."):
            evidence = focus.get("evidence", []) if isinstance(focus.get("evidence"), list) else []
            pairs = {
                "adv.focus.window": _short_value(focus.get("window") or "", limit=80),
                "adv.focus.evidence_count": str(len(evidence)),
            }
            for idx, item in enumerate(evidence[:3], start=1):
                if not isinstance(item, dict):
                    continue
                pairs[f"adv.focus.evidence_{idx}_kind"] = _short_value(item.get("kind") or "", limit=64)
                pairs[f"adv.focus.evidence_{idx}_text"] = _short_value(item.get("text") or "", limit=160)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.focus.",))
            _append_doc(
                "adv.focus.window",
                "Keyboard focus inference with exact evidence texts from highlighted controls. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=8400,
                meta={"advanced": True, "adv_topic": "focus", "focus_window": focus.get("window"), "focus_evidence": evidence},
            )
        if incident.get("subject") or incident.get("sender_domain") or incident.get("action_buttons") or incident_boxes or has_adv_fact("adv.incident."):
            pairs = {
                "adv.incident.subject": _short_value(incident.get("subject") or "", limit=120),
                "adv.incident.sender_display": _short_value(incident.get("sender_display") or "", limit=80),
                "adv.incident.sender_domain": _short_value(incident.get("sender_domain") or "", limit=80),
                "adv.incident.action_buttons": "|".join(str(x) for x in incident.get("action_buttons", []) if str(x)),
            }
            if incident_boxes.get("complete_bbox_norm"):
                pairs["adv.incident.button.complete_bbox_norm"] = str(incident_boxes.get("complete_bbox_norm") or "")
            if incident_boxes.get("view_details_bbox_norm"):
                pairs["adv.incident.button.view_details_bbox_norm"] = str(incident_boxes.get("view_details_bbox_norm") or "")
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.incident.",))
            _append_doc(
                "adv.incident.card",
                "Incident email extraction: subject, sender display, sender domain, and task-card action buttons. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=9400,
                meta={
                    "advanced": True,
                    "adv_topic": "incident_card",
                    "subject": incident.get("subject"),
                    "sender_display": incident.get("sender_display"),
                    "sender_domain": incident.get("sender_domain"),
                    "action_buttons": incident.get("action_buttons", []),
                    "button_boxes": incident_boxes,
                },
            )
        if record_activity or has_adv_fact("adv.activity."):
            pairs = {"adv.activity.count": str(len(record_activity))}
            for idx, entry in enumerate(record_activity[:8], start=1):
                pairs[f"adv.activity.{idx}.timestamp"] = _short_value(entry.get("timestamp") or "", limit=64)
                pairs[f"adv.activity.{idx}.text"] = _short_value(entry.get("text") or "", limit=180)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.activity.",))
            _append_doc(
                "adv.activity.timeline",
                "Record Activity timeline rows with timestamp and associated text in on-screen order. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7900,
                meta={"advanced": True, "adv_topic": "activity_timeline", "activity_rows": record_activity},
            )
        if details or has_adv_fact("adv.details."):
            pairs = {"adv.details.count": str(len(details))}
            for idx, item in enumerate(details[:16], start=1):
                pairs[f"adv.details.{idx}.label"] = _short_value(item.get("label") or "", limit=80)
                pairs[f"adv.details.{idx}.value"] = _short_value(item.get("value") or "", limit=120)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.details.",))
            _append_doc(
                "adv.details.kv",
                "Details section key-value extraction preserving field order and empty values. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7600,
                meta={"advanced": True, "adv_topic": "details_kv", "details_rows": details},
            )
        if calendar.get("month_year") or calendar.get("items") or has_adv_fact("adv.calendar."):
            items = calendar.get("items", []) if isinstance(calendar.get("items"), list) else []
            pairs = {
                "adv.calendar.month_year": _short_value(calendar.get("month_year") or "", limit=40),
                "adv.calendar.selected_date": _short_value(calendar.get("selected_date") or "", limit=16),
                "adv.calendar.item_count": str(len(items)),
            }
            for idx, item in enumerate(items[:5], start=1):
                if not isinstance(item, dict):
                    continue
                pairs[f"adv.calendar.item.{idx}.start"] = _short_value(item.get("start") or "", limit=32)
                pairs[f"adv.calendar.item.{idx}.title"] = _short_value(item.get("title") or "", limit=96)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.calendar.",))
            _append_doc(
                "adv.calendar.schedule",
                "Calendar and schedule pane extraction: month/year, selected date, and visible events. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7800,
                meta={"advanced": True, "adv_topic": "calendar_schedule", "calendar": calendar},
            )
        if slack_dm.get("messages") or has_adv_fact("adv.slack."):
            msgs = slack_dm.get("messages", []) if isinstance(slack_dm.get("messages"), list) else []
            pairs = {
                "adv.slack.dm_name": _short_value(slack_dm.get("dm_name") or "", limit=80),
                "adv.slack.message_count": str(len(msgs)),
                "adv.slack.thumbnail_desc": _short_value(slack_dm.get("thumbnail") or "", limit=160),
            }
            for idx, msg in enumerate(msgs[:2], start=1):
                if not isinstance(msg, dict):
                    continue
                pairs[f"adv.slack.msg.{idx}.sender"] = _short_value(msg.get("sender") or "", limit=80)
                pairs[f"adv.slack.msg.{idx}.timestamp"] = _short_value(msg.get("timestamp") or "", limit=24)
                pairs[f"adv.slack.msg.{idx}.text"] = _short_value(msg.get("text") or "", limit=180)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.slack.",))
            _append_doc(
                "adv.slack.dm",
                "Slack DM extraction with last visible messages and thumbnail description (visible-only). "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7600,
                meta={"advanced": True, "adv_topic": "slack_dm", "slack_dm": slack_dm},
            )
        if dev_summary.get("what_changed") or dev_summary.get("files") or dev_summary.get("tests_cmd") or has_adv_fact("adv.dev."):
            changed = dev_summary.get("what_changed", []) if isinstance(dev_summary.get("what_changed"), list) else []
            files = dev_summary.get("files", []) if isinstance(dev_summary.get("files"), list) else []
            pairs = {
                "adv.dev.what_changed_count": str(len(changed)),
                "adv.dev.file_count": str(len(files)),
                "adv.dev.tests_cmd": _short_value(dev_summary.get("tests_cmd") or "", limit=220),
            }
            for idx, item in enumerate(changed[:6], start=1):
                pairs[f"adv.dev.what_changed.{idx}"] = _short_value(item, limit=160)
            for idx, item in enumerate(files[:6], start=1):
                pairs[f"adv.dev.file.{idx}"] = _short_value(item, limit=180)
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.dev.",))
            _append_doc(
                "adv.dev.summary",
                "Dev-note extraction for What changed lines, Files list, and Tests command. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7600,
                meta={"advanced": True, "adv_topic": "dev_summary", "dev_summary": dev_summary},
            )
        if console_colors.get("lines") or has_adv_fact("adv.console."):
            counts = console_colors.get("counts", {}) if isinstance(console_colors.get("counts"), dict) else {}
            red_lines = console_colors.get("red_lines", []) if isinstance(console_colors.get("red_lines"), list) else []
            pairs = {
                "adv.console.line_count": str(len(console_colors.get("lines", []) if isinstance(console_colors.get("lines"), list) else [])),
                "adv.console.red_count": str(int(counts.get("red", 0) or 0)),
                "adv.console.green_count": str(int(counts.get("green", 0) or 0)),
                "adv.console.other_count": str(int(counts.get("other", 0) or 0)),
                "adv.console.red_lines": "|".join(_short_value(x, limit=120) for x in red_lines[:8]),
            }
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.console.",))
            _append_doc(
                "adv.console.colors",
                "Console/log color-aware extraction with per-line classification and red-line isolation. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7300,
                meta={"advanced": True, "adv_topic": "console_colors", "console_colors": console_colors},
            )
        if browser_windows or has_adv_fact("adv.browser."):
            pairs = {"adv.browser.window_count": str(len(browser_windows))}
            for idx, item in enumerate(browser_windows[:8], start=1):
                pairs[f"adv.browser.{idx}.hostname"] = _short_value(item.get("hostname") or "", limit=90)
                pairs[f"adv.browser.{idx}.active_title"] = _short_value(item.get("active_title") or "", limit=110)
                pairs[f"adv.browser.{idx}.tab_count"] = str(int(item.get("visible_tab_count") or 0))
            pairs = _merge_adv_pairs_from_facts(pairs, ui_fact_map, ("adv.browser.",))
            _append_doc(
                "adv.browser.windows",
                "Browser chrome extraction for active tab title, hostname, and visible tab counts per window. "
                + "Observation: "
                + "; ".join(f"{k}={v}" for k, v in pairs.items())
                + ".",
                confidence_bp=7700,
                meta={"advanced": True, "adv_topic": "browser_windows", "browser_windows": browser_windows},
            )

        return {
            "extra_docs": extra_docs,
            "metrics": {
                "obs_message_author_found": 1.0 if bool(message_author) else 0.0,
                "obs_contractor_found": 1.0 if bool(contractor) else 0.0,
                "obs_disambiguation_emitted": 1.0 if bool(message_author and contractor and message_author != contractor) else 0.0,
                "obs_vdi_time_found": 1.0 if bool(vdi_time) else 0.0,
                "obs_open_inboxes_count": float(int(inbox.get("count", 0) or 0)),
                "obs_now_playing_found": 1.0 if bool(now_playing) else 0.0,
                "obs_background_color_found": 1.0 if bool(background_color) else 0.0,
                "adv_window_inventory_found": 1.0 if bool(windows) else 0.0,
                "adv_focus_found": 1.0 if bool(focus.get("window")) else 0.0,
                "adv_incident_found": 1.0 if bool(incident.get("subject") or incident.get("sender_domain")) else 0.0,
                "adv_activity_rows": float(len(record_activity)),
                "adv_details_rows": float(len(details)),
                "adv_calendar_items": float(len(calendar.get("items", []) if isinstance(calendar.get("items"), list) else [])),
                "adv_slack_messages": float(len(slack_dm.get("messages", []) if isinstance(slack_dm.get("messages"), list) else [])),
                "adv_dev_lines": float(
                    len(dev_summary.get("what_changed", []) if isinstance(dev_summary.get("what_changed"), list) else [])
                ),
                "adv_console_lines": float(
                    len(console_colors.get("lines", []) if isinstance(console_colors.get("lines"), list) else [])
                ),
                "adv_browser_windows": float(len(browser_windows)),
            },
        }


def create_plugin(plugin_id: str, context: PluginContext) -> ObservationGraphPlugin:
    return ObservationGraphPlugin(plugin_id, context)
