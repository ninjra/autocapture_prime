#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
DATAROOT="${AUTOCAPTURE_DATAROOT:-/mnt/d/autocapture}"
DB_PATH="${AUTOCAPTURE_METADATA_DB:-$DATAROOT/metadata.db}"
OUT_DIR="${AUTOCAPTURE_STAGE1_RECOVERY_OUT_DIR:-$ROOT/artifacts/stage1_recovery}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$OUT_DIR/run_$STAMP"
mkdir -p "$RUN_DIR"

PREFLIGHT_JSON="$RUN_DIR/preflight.json"
BACKFILL_JSON="$RUN_DIR/backfill.json"
LINEAGE_JSON="$RUN_DIR/lineage.json"
COUNTS_JSON="$RUN_DIR/counts.json"
SUMMARY_JSON="$RUN_DIR/summary.json"

"$PY" "$ROOT/tools/preflight_live_stack.py" \
  --dataroot "$DATAROOT" \
  --db-stability-samples 4 \
  --db-stability-interval-ms 250 \
  --output "$PREFLIGHT_JSON"

"$PY" "$ROOT/tools/migrations/backfill_uia_obs_docs.py" \
  --db "$DB_PATH" \
  --dataroot "$DATAROOT" \
  --wait-stable-seconds 5 \
  --wait-timeout-seconds 120 \
  --poll-interval-ms 250 >"$BACKFILL_JSON"

"$PY" "$ROOT/tools/validate_stage1_lineage.py" \
  --db "$DB_PATH" \
  --strict \
  --samples 3 \
  --output "$LINEAGE_JSON" > /tmp/stage1_lineage_stdout.json

"$PY" - <<'PY' "$DB_PATH" "$COUNTS_JSON"
import json
import sqlite3
import sys

db_path = str(sys.argv[1])
out_path = str(sys.argv[2])
conn = sqlite3.connect(db_path)
cur = conn.cursor()
record_types = [
    "evidence.capture.frame",
    "evidence.uia.snapshot",
    "obs.uia.focus",
    "obs.uia.context",
    "obs.uia.operable",
    "derived.ingest.stage1.complete",
    "retention.eligible",
]
counts = {rt: int(cur.execute("SELECT COUNT(*) FROM metadata WHERE record_type = ?", (rt,)).fetchone()[0]) for rt in record_types}
payload = {"ok": True, "db": db_path, "counts": counts}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
print(json.dumps(payload, sort_keys=True))
conn.close()
PY

"$PY" - <<'PY' "$PREFLIGHT_JSON" "$BACKFILL_JSON" "$LINEAGE_JSON" "$COUNTS_JSON" "$SUMMARY_JSON"
import json
import pathlib
import sys

preflight_path = pathlib.Path(sys.argv[1])
backfill_path = pathlib.Path(sys.argv[2])
lineage_path = pathlib.Path(sys.argv[3])
counts_path = pathlib.Path(sys.argv[4])
summary_path = pathlib.Path(sys.argv[5])

preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
backfill = json.loads(backfill_path.read_text(encoding="utf-8"))
lineage = json.loads(lineage_path.read_text(encoding="utf-8"))
counts = json.loads(counts_path.read_text(encoding="utf-8"))

ok = bool(preflight.get("ready", False)) and bool(backfill.get("ok", False)) and bool(lineage.get("ok", False)) and bool(counts.get("ok", False))
summary = {
    "ok": ok,
    "artifacts": {
        "preflight": str(preflight_path),
        "backfill": str(backfill_path),
        "lineage": str(lineage_path),
        "counts": str(counts_path),
    },
    "failure_codes": list(preflight.get("failure_codes") or []),
    "backfill": backfill,
    "lineage_fail_reasons": list(lineage.get("fail_reasons") or []),
    "counts": counts.get("counts") if isinstance(counts.get("counts"), dict) else {},
}
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps(summary, sort_keys=True))
PY

echo "summary_path=$SUMMARY_JSON"
