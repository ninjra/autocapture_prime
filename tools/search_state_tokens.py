#!/usr/bin/env python3
"""Search token/line text inside latest derived.sst.state payload."""

from __future__ import annotations

import argparse
import json
import sqlite3


def _norm(text: str) -> str:
    return str(text or "").strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--needle", required=True)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    row = con.execute(
        """
        SELECT payload
        FROM metadata
        WHERE record_type = 'derived.sst.state'
        ORDER BY ts_utc DESC
        LIMIT 1
        """
    ).fetchone()
    con.close()
    if not row:
        print("no_state_payload")
        return 1
    payload = json.loads(str(row[0] or "{}"))
    state = payload.get("screen_state") if isinstance(payload.get("screen_state"), dict) else {}
    tokens = state.get("tokens_raw") if isinstance(state.get("tokens_raw"), list) else []
    lines = state.get("text_lines") if isinstance(state.get("text_lines"), list) else []
    needle = str(args.needle or "").casefold()

    print(f"needle={args.needle}")
    print("token_hits")
    hit_count = 0
    for item in tokens:
        if not isinstance(item, dict):
            continue
        txt = _norm(str(item.get("norm_text") or item.get("text") or ""))
        if needle and needle not in txt.casefold():
            continue
        bbox = item.get("bbox")
        print(f"- {txt} @ {bbox}")
        hit_count += 1
        if hit_count >= max(1, int(args.limit)):
            break
    if hit_count <= 0:
        print("- none")

    print("line_hits")
    hit_count = 0
    for item in lines:
        if not isinstance(item, dict):
            continue
        txt = _norm(str(item.get("text") or ""))
        if needle and needle not in txt.casefold():
            continue
        bbox = item.get("bbox")
        print(f"- {txt} @ {bbox}")
        hit_count += 1
        if hit_count >= max(1, int(args.limit)):
            break
    if hit_count <= 0:
        print("- none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
