"""Screen state construction."""

from __future__ import annotations

from typing import Any

from autocapture_nx.kernel.ids import encode_record_id_component

from .utils import bp, hash_canonical, norm_text


def build_state(
    *,
    run_id: str,
    frame_id: str,
    ts_ms: int,
    phash: str,
    image_sha256: str | None = None,
    frame_index: int | None = None,
    width: int,
    height: int,
    tokens: list[dict[str, Any]],
    tokens_raw: list[dict[str, Any]] | None = None,
    element_graph: dict[str, Any],
    text_lines: list[dict[str, Any]],
    text_blocks: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    spreadsheets: list[dict[str, Any]],
    code_blocks: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    cursor: dict[str, Any] | None,
    window_title: str | None,
) -> dict[str, Any]:
    tokens_key = [
        {
            "norm_text": t.get("norm_text", ""),
            "bbox": tuple(int(v) for v in t.get("bbox", (0, 0, 0, 0))),
            "confidence_bp": int(t.get("confidence_bp", 0)),
        }
        for t in tokens
    ]
    tokens_hash = hash_canonical(tokens_key)[:16] if tokens_key else "empty"
    state_id = encode_record_id_component(f"state-{run_id}-{phash}-{tokens_hash}")

    visible_apps = _visible_apps(tokens, window_title)
    focus_element_id = _focus_element(element_graph, cursor)
    state_conf = _state_confidence(tokens, tables, spreadsheets, code_blocks, charts)

    # Update state ids on nested artifacts now that we have a stable state id.
    source_state_id = str(element_graph.get("state_id") or "")
    source_backend = str(element_graph.get("source_backend") or "")
    source_provider_id = str(element_graph.get("source_provider_id") or "")
    element_graph = {**element_graph, "state_id": state_id}
    if source_state_id:
        element_graph["source_state_id"] = source_state_id
    if source_backend:
        element_graph["source_backend"] = source_backend
    if source_provider_id:
        element_graph["source_provider_id"] = source_provider_id
    tables = [_with_state_id(t, state_id) for t in tables]
    spreadsheets = [_with_state_id(t, state_id) for t in spreadsheets]
    code_blocks = [_with_state_id(c, state_id) for c in code_blocks]
    charts = [_with_state_id(c, state_id) for c in charts]

    payload = {
        "state_id": state_id,
        "frame_id": frame_id,
        "frame_index": int(frame_index or 0),
        "ts_ms": int(ts_ms),
        "phash": phash,
        "image_sha256": str(image_sha256 or ""),
        "width": int(width),
        "height": int(height),
        "tokens": tuple(tokens),
        "element_graph": element_graph,
        "text_lines": tuple(text_lines),
        "text_blocks": tuple(text_blocks),
        "tables": tuple(tables),
        "spreadsheets": tuple(spreadsheets),
        "code_blocks": tuple(code_blocks),
        "charts": tuple(charts),
        "cursor": cursor,
        "visible_apps": tuple(visible_apps),
        "focus_element_id": focus_element_id,
        "state_confidence_bp": int(state_conf),
        "diagnostics": tuple(),
    }
    if tokens_raw is not None:
        payload["tokens_raw"] = tuple(tokens_raw)
        payload["tokens_raw_count"] = int(len(tokens_raw))
    return payload


def _with_state_id(payload: dict[str, Any], state_id: str) -> dict[str, Any]:
    return {**payload, "state_id": state_id}


def _visible_apps(tokens: list[dict[str, Any]], window_title: str | None) -> list[str]:
    apps: list[str] = []
    if window_title:
        apps.append(norm_text(window_title))
    top_tokens = sorted(tokens, key=lambda t: (t["bbox"][1], t["bbox"][0], t["token_id"]))[:12]
    for token in top_tokens:
        text = norm_text(str(token.get("text", "")))
        if not text:
            continue
        if len(text) > 64:
            continue
        if text.isdigit():
            continue
        apps.append(text)
    uniq = []
    seen = set()
    for item in apps:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq[:8]


def _focus_element(element_graph: dict[str, Any], cursor: dict[str, Any] | None) -> str | None:
    if not cursor:
        return None
    cb = cursor.get("bbox")
    if not cb:
        return None
    cx = (cb[0] + cb[2]) // 2
    cy = (cb[1] + cb[3]) // 2
    candidates = []
    for el in element_graph.get("elements", ()):
        bbox = el.get("bbox")
        if not bbox:
            continue
        if bbox[0] <= cx < bbox[2] and bbox[1] <= cy < bbox[3]:
            if bool(el.get("interactable", False)):
                candidates.append(el)
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e.get("z", 0), e["bbox"][1], e["bbox"][0], e["element_id"]))
    return candidates[0]["element_id"]


def _state_confidence(
    tokens: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    spreadsheets: list[dict[str, Any]],
    code_blocks: list[dict[str, Any]],
    charts: list[dict[str, Any]],
) -> int:
    if not tokens:
        base = 4000
    else:
        avg = sum(int(t.get("confidence_bp", 0)) for t in tokens) // max(1, len(tokens))
        base = max(3000, min(9500, avg))
    boost = 0
    if tables:
        boost += 400
    if spreadsheets:
        boost += 300
    if code_blocks:
        boost += 300
    if charts:
        boost += 200
    return bp(min(1.0, (base + boost) / 10000.0))
