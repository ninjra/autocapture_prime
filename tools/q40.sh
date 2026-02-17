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

cycle_json="$(bash "$ROOT/tools/run_golden_qh_cycle.sh" "$IMG")"
report_path="$($PY -c "import json,sys; print(json.loads(sys.argv[1]).get('report',''))" "$cycle_json")"
adv_path="$($PY -c "import json,sys; print(json.loads(sys.argv[1]).get('advanced',''))" "$cycle_json")"
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
"$PY" "$ROOT/tools/eval_q40_matrix.py" \
  --advanced-json "$adv_path" \
  --generic-json "$gen_path" \
  --out "$matrix_path" >/tmp/autocapture_prime_q40_matrix.out

echo "{\"ok\":true,\"advanced\":\"$adv_path\",\"generic\":\"$gen_path\",\"matrix\":\"$matrix_path\"}"
