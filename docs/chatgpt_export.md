# ChatGPT Export (Edge)

This command exports ChatGPT transcript text from captured Edge segments into a local append-only NDJSON stream for Hypervisor ingest.

## Command

```bash
python -m autocapture_nx.cli export chatgpt --max-segments 50
```

Follow mode:

```bash
python -m autocapture_nx.cli export chatgpt --follow
```

Optional time filter:

```bash
python -m autocapture_nx.cli export chatgpt --since-ts 2026-02-17T00:00:00+00:00
```

## Output location

Resolution order:

1. `KERNEL_AUTOCAPTURE_EXPORT_ROOT`
2. On Windows only, sibling `exports` beside `KERNEL_AUTOCAPTURE_DATA_ROOT`
3. Default: `data/exports` under current working directory

Output file:

- `chatgpt_transcripts.ndjson`

## NDJSON line schema (minimum)

Each line includes:

- `schema_version`
- `entry_id`
- `ts_utc`
- `source` (`browser`, `app`, `window_title`, `process_path`)
- `segment_id`
- `frame_name`
- `text` (sanitized)
- `glossary`
- `prev_hash`
- `entry_hash`

## Hash chain behavior

Lines are append-only and hash chained:

- `entry_hash = sha256(canonical_json_without_entry_hash + (prev_hash or ""))`

`prev_hash` is recovered from the last export line before appending the next line.

## Fail-soft behavior

- Missing OCR provider does not crash export; it emits fewer or no transcript lines.
- Sanitizer leak-check failure emits `text=""` and adds `export_notice="leak_check_failed"`.
- Segment-level failures are counted and reported; capture pipeline remains unaffected.

## Idempotency marker

After successful export of at least one frame from a segment, metadata stores:

- key: `export.chatgpt.<segment_id>`
- value: exported timestamp + `entry_hashes`

This prevents duplicate re-export on reruns.

## Hypervisor ingest contract

This export stream is designed for the Hypervisor sidecar transcript ingestor using append-only NDJSON semantics and hash-chain verification.
