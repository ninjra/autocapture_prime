#!/usr/bin/env python3
"""Inspect advanced/observation extracted records from a single-run metadata DB."""

from __future__ import annotations

import argparse
import json
import sqlite3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        required=True,
        help="Path to metadata.db for a single-image run.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Rows per section.")
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    try:
        schema_rows = con.execute("PRAGMA table_info(metadata)").fetchall()
        column_names = [str(row["name"]) for row in schema_rows]
        print("metadata_columns")
        print("- " + ", ".join(column_names))

        rows = con.execute("SELECT record_type, COUNT(*) FROM metadata GROUP BY 1 ORDER BY 2 DESC").fetchall()
        print("record_type_counts")
        for record_type, count in rows:
            print(f"- {record_type}: {count}")

        sst_rows = con.execute(
            """
            SELECT payload
            FROM metadata
            WHERE record_type = 'derived.sst.text'
            ORDER BY ts_utc DESC
            LIMIT 5
            """
        ).fetchall()
        if sst_rows:
            print("\nderived_sst_text")
            for row in sst_rows:
                payload_text = str(row["payload"] or "")
                try:
                    parsed = json.loads(payload_text)
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict):
                    print(
                        "- extractor={extractor} state_id={state_id} backend={backend} provider={provider} text_snippet={snippet}".format(
                            extractor=str(parsed.get("extractor") or ""),
                            state_id=str(parsed.get("state_id") or ""),
                            backend=str(parsed.get("backend") or ""),
                            provider=str(parsed.get("provider_id") or ""),
                            snippet=str(parsed.get("text") or "")[:140].replace("\n", " "),
                        )
                    )

        text_col = ""
        for candidate in ("text", "record_json", "payload", "payload_json", "record"):
            if candidate in column_names:
                text_col = candidate
                break
        if not text_col:
            print("\nno_payload_column_detected")
            return 0

        recs = con.execute(
            f"""
            SELECT id, record_type, {text_col} AS payload_text
            FROM metadata
            WHERE record_type = 'derived.sst.text.extra'
            ORDER BY ts_utc DESC
            LIMIT ?
            """,
            (max(args.limit * 4, 64),),
        ).fetchall()
        adv: list[tuple[str, str, str]] = []
        obs: list[tuple[str, str, str]] = []
        for row in recs:
            rid = str(row["id"])
            payload_text = str(row["payload_text"] or "")
            doc_kind = ""
            text = payload_text
            source_provider_id = ""
            source_backend = ""
            source_modality = ""
            vlm_grounded = ""
            try:
                parsed = json.loads(payload_text)
                if isinstance(parsed, dict):
                    doc_kind = str(parsed.get("doc_kind") or "")
                    text = str(parsed.get("text") or payload_text)
                    meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
                    source_provider_id = str(meta.get("source_provider_id") or "")
                    source_backend = str(meta.get("source_backend") or "")
                    source_modality = str(meta.get("source_modality") or "")
                    if "vlm_grounded" in meta:
                        vlm_grounded = str(bool(meta.get("vlm_grounded")))
            except Exception:
                pass
            if doc_kind.startswith("adv."):
                adv.append((rid, doc_kind, text, source_provider_id, source_backend, source_modality, vlm_grounded))
            if doc_kind.startswith("obs."):
                obs.append((rid, doc_kind, text, source_provider_id, source_backend, source_modality, vlm_grounded))

        print("\nadv_docs")
        for rid, kind, text, src_provider, src_backend, src_modality, src_grounded in adv[: args.limit]:
            snippet = str(text or "").replace("\n", " ")[:400]
            print(f"- {rid} {kind} [provider={src_provider} backend={src_backend} modality={src_modality} vlm_grounded={src_grounded}]")
            print(f"  {snippet}")

        print("\nobs_docs")
        for rid, kind, text, src_provider, src_backend, src_modality, src_grounded in obs[: args.limit]:
            snippet = str(text or "").replace("\n", " ")[:300]
            print(f"- {rid} {kind} [provider={src_provider} backend={src_backend} modality={src_modality} vlm_grounded={src_grounded}]")
            print(f"  {snippet}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
