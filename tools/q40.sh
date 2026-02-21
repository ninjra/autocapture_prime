#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
IMG="${1:-$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

clamp_min() {
  local raw="$1"
  local fallback="$2"
  local floor="$3"
  local val="$raw"
  if [[ -z "$val" || ! "$val" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    val="$fallback"
  fi
  awk -v v="$val" -v f="$floor" 'BEGIN { if ((v+0) < (f+0)) { print f } else { print v } }'
}

export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S="$(clamp_min "${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S:-45}" "45" "30")"
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S="$(clamp_min "${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_MAX_S:-120}" "120" "60")"
export AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE="${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_SCALE:-1.5}"
export AUTOCAPTURE_VLM_PREFLIGHT_RETRIES="$(clamp_min "${AUTOCAPTURE_VLM_PREFLIGHT_RETRIES:-6}" "6" "3")"

adv_timeout_s="$(clamp_min "${AUTOCAPTURE_ADV_QUERY_TIMEOUT_S:-180}" "180" "60")"
gen_timeout_s="$(clamp_min "${AUTOCAPTURE_GENERIC20_QUERY_TIMEOUT_S:-120}" "120" "60")"
lock_retries="$(clamp_min "${AUTOCAPTURE_GENERIC20_LOCK_RETRIES:-2}" "2" "1")"
export AUTOCAPTURE_ADV_QUERY_TIMEOUT_S="$adv_timeout_s"
golden_strict="${AUTOCAPTURE_GOLDEN_STRICT:-1}"
case "${golden_strict,,}" in
  1|true|yes|on) golden_strict="1" ;;
  *) golden_strict="0" ;;
esac
if [[ "${golden_strict}" == "1" ]]; then
  export AUTOCAPTURE_SKIP_VLM_UNSTABLE=0
fi

cycle_out="$(bash "$ROOT/tools/run_golden_qh_cycle.sh" "$IMG" 2>&1)"
cycle_json="$($PY - <<'PY' "$cycle_out"
import json
import sys

txt = str(sys.argv[1] if len(sys.argv) > 1 else "")
last_obj = {}
for raw in txt.splitlines():
    line = raw.strip()
    if not line.startswith("{") or not line.endswith("}"):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if "ok" in obj:
        last_obj = obj
print(json.dumps(last_obj))
PY
)"
report_path="$($PY -c "import json,sys; print((json.loads(sys.argv[1]) if sys.argv[1].strip() else {}).get('report',''))" "$cycle_json")"
adv_path="$($PY -c "import json,sys; print((json.loads(sys.argv[1]) if sys.argv[1].strip() else {}).get('advanced',''))" "$cycle_json")"
if [[ -z "$report_path" || ! -f "$report_path" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_report\",\"cycle\":$cycle_json}"
  exit 1
fi
if [[ -z "$adv_path" || ! -f "$adv_path" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_advanced\",\"cycle\":$cycle_json}"
  exit 1
fi

gen_path="$ROOT/artifacts/advanced10/generic20_${STAMP}.json"
"$PY" "$ROOT/tools/run_advanced10_queries.py" \
  --report "$report_path" \
  --cases "$ROOT/docs/query_eval_cases_generic20.json" \
  --metadata-only \
  --query-timeout-s "$gen_timeout_s" \
  --lock-retries "$lock_retries" \
  --output "$gen_path" >/tmp/autocapture_prime_q40_generic.out

matrix_path="$ROOT/artifacts/advanced10/q40_matrix_${STAMP}.json"
matrix_log="/tmp/autocapture_prime_q40_matrix.out"
set +e
if [[ "${golden_strict}" == "1" ]]; then
  "$PY" "$ROOT/tools/eval_q40_matrix.py" \
    --advanced-json "$adv_path" \
    --generic-json "$gen_path" \
    --strict \
    --expected-total 40 \
    --out "$matrix_path" >"$matrix_log"
else
  "$PY" "$ROOT/tools/eval_q40_matrix.py" \
    --advanced-json "$adv_path" \
    --generic-json "$gen_path" \
    --out "$matrix_path" >"$matrix_log"
fi
matrix_rc=$?
set -e
if [[ $matrix_rc -ne 0 ]]; then
  matrix_detail="$($PY - <<'PY' "$matrix_log"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print(json.dumps({"raw_tail": ""}))
    raise SystemExit(0)
last = {}
tail = ""
for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = str(raw or "").strip()
    if not line:
        continue
    tail = line
    if line.startswith("{") and line.endswith("}"):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            last = obj
if last:
    print(json.dumps(last, sort_keys=True))
else:
    print(json.dumps({"raw_tail": tail}, sort_keys=True))
PY
)"
  echo "{\"ok\":false,\"error\":\"strict_matrix_gate_failed\",\"matrix\":\"$matrix_path\",\"strict\":${golden_strict},\"detail\":$matrix_detail}"
  exit 1
fi
cp "$matrix_path" "$ROOT/artifacts/advanced10/q40_matrix_latest.json"
cp "$adv_path" "$ROOT/artifacts/advanced10/advanced20_latest.json"
cp "$gen_path" "$ROOT/artifacts/advanced10/generic20_latest.json"

echo "{\"ok\":true,\"advanced\":\"$adv_path\",\"generic\":\"$gen_path\",\"matrix\":\"$matrix_path\"}"
