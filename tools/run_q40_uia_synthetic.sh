#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
DEFAULT_IMG="$ROOT/docs/test sample/Screenshot 2026-02-02 113519.png"
IMG="$DEFAULT_IMG"
if [[ -n "${1:-}" && "${1:-}" != "--dry-run" ]]; then
  IMG="$1"
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_DIR="${AUTOCAPTURE_Q40_SYNTH_OUT_DIR:-$ROOT/artifacts/q40_uia_synthetic}"
SYNTH_MODE="${AUTOCAPTURE_Q40_SYNTH_UIA_MODE:-fallback}"
HASH_MODE="${AUTOCAPTURE_Q40_SYNTH_HASH_MODE:-match}"
DRY_RUN="${AUTOCAPTURE_Q40_SYNTH_DRY_RUN:-0}"
SINGLE_TIMEOUT_S="${AUTOCAPTURE_Q40_SYNTH_SINGLE_TIMEOUT_S:-420}"
if [[ "${1:-}" == "--dry-run" || "${2:-}" == "--dry-run" ]]; then
  DRY_RUN="1"
fi

case "${SYNTH_MODE}" in
  metadata|fallback) ;;
  *)
    echo "{\"ok\":false,\"error\":\"invalid_uia_mode\",\"mode\":\"${SYNTH_MODE}\"}"
    exit 2
    ;;
esac

run_cmd() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    return 0
  fi
  "$@"
}

extract_last_json() {
  "$PY" - <<'PY' "$1"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
if not path.exists():
    print("{}")
    raise SystemExit(0)
last = {}
for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
    line = str(raw or "").strip()
    if not (line.startswith("{") and line.endswith("}")):
        continue
    try:
        obj = json.loads(line)
    except Exception:
        continue
    if isinstance(obj, dict) and "ok" in obj:
        last = obj
print(json.dumps(last, sort_keys=True))
PY
}

mkdir -p "$OUT_DIR"
synth_root="$OUT_DIR/synth_${STAMP}"
mkdir -p "$synth_root"
synth_log="$synth_root/synthetic_pack.log"
pack_json="$synth_root/synthetic_uia_contract_pack.json"

run_cmd "$PY" "$ROOT/tools/synthetic_uia_contract_pack.py" \
  --out-dir "$synth_root" \
  --run-id "run_q40_uia_${STAMP}" \
  --hash-mode "$HASH_MODE" >"$synth_log"

if [[ "${DRY_RUN}" == "1" ]]; then
  cat <<JSON
{"ok":true,"dry_run":true,"strict":true,"expected_total":40,"uia_mode":"${SYNTH_MODE}","hash_mode":"${HASH_MODE}","out_dir":"${OUT_DIR}"}
JSON
  exit 0
fi

if [[ ! -f "$pack_json" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_synthetic_pack\",\"path\":\"$pack_json\"}"
  exit 1
fi

validate_log="$synth_root/validate_pack.log"
set +e
"$PY" "$ROOT/tools/validate_synthetic_uia_contract.py" \
  --pack-json "$pack_json" \
  --require-hash-match >"$validate_log"
validate_rc=$?
set -e
if [[ $validate_rc -ne 0 ]]; then
  detail="$(extract_last_json "$validate_log")"
  echo "{\"ok\":false,\"error\":\"synthetic_pack_invalid\",\"detail\":$detail,\"pack\":\"$pack_json\"}"
  exit 1
fi

single_log="$synth_root/single_image.log"
set +e
if command -v timeout >/dev/null 2>&1; then
  timeout --signal=TERM --kill-after=10 "${SINGLE_TIMEOUT_S}" "$PY" "$ROOT/tools/process_single_screenshot.py" \
    --image "$IMG" \
    --output-dir "artifacts/single_image_runs" \
    --profile "config/profiles/golden_full.json" \
    --synthetic-hid "minimal" \
    --uia-synthetic "$SYNTH_MODE" \
    --uia-synthetic-pack-json "$pack_json" \
    --uia-synthetic-dataroot "$synth_root" \
    --force-idle >"$single_log" 2>&1
else
  "$PY" "$ROOT/tools/process_single_screenshot.py" \
    --image "$IMG" \
    --output-dir "artifacts/single_image_runs" \
    --profile "config/profiles/golden_full.json" \
    --synthetic-hid "minimal" \
    --uia-synthetic "$SYNTH_MODE" \
    --uia-synthetic-pack-json "$pack_json" \
    --uia-synthetic-dataroot "$synth_root" \
    --force-idle >"$single_log" 2>&1
fi
single_rc=$?
set -e
single_json="$(extract_last_json "$single_log")"
report_path="$("$PY" -c "import json,sys; print((json.loads(sys.argv[1]) if sys.argv[1].strip() else {}).get('report',''))" "$single_json")"
if [[ $single_rc -eq 124 || $single_rc -eq 137 || $single_rc -eq 143 ]]; then
  echo "{\"ok\":false,\"error\":\"single_image_timeout\",\"timeout_s\":${SINGLE_TIMEOUT_S},\"log\":\"$single_log\"}"
  exit 1
fi
if [[ $single_rc -ne 0 || -z "$report_path" || ! -f "$report_path" ]]; then
  echo "{\"ok\":false,\"error\":\"single_image_failed\",\"detail\":$single_json,\"log\":\"$single_log\"}"
  exit 1
fi

uia_gate="$("$PY" - <<'PY' "$report_path"
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    report = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(json.dumps({"ok": False, "error": f"report_parse_failed:{type(exc).__name__}"}))
    raise SystemExit(0)
uia_docs = report.get("uia_docs") if isinstance(report.get("uia_docs"), dict) else {}
count_by_kind = uia_docs.get("count_by_kind") if isinstance(uia_docs.get("count_by_kind"), dict) else {}
required = ["obs.uia.focus", "obs.uia.context", "obs.uia.operable"]
missing = [k for k in required if int(count_by_kind.get(k, 0) or 0) <= 0]
ok = len(missing) == 0
print(json.dumps({"ok": ok, "missing_kinds": missing, "uia_docs": uia_docs}, sort_keys=True))
PY
)"
uia_ok="$("$PY" -c "import json,sys; print('1' if bool(json.loads(sys.argv[1]).get('ok', False)) else '0')" "$uia_gate")"
if [[ "$uia_ok" != "1" ]]; then
  echo "{\"ok\":false,\"error\":\"uia_docs_missing\",\"detail\":$uia_gate,\"report\":\"$report_path\"}"
  exit 1
fi

adv_path="$ROOT/artifacts/advanced10/advanced20_strict_uia_synthetic_${STAMP}.json"
gen_path="$ROOT/artifacts/advanced10/generic20_uia_synthetic_${STAMP}.json"
matrix_path="$ROOT/artifacts/advanced10/q40_matrix_strict_uia_synthetic_${STAMP}.json"
adv_log="$synth_root/advanced20.log"
gen_log="$synth_root/generic20.log"
matrix_log="$synth_root/matrix.log"

set +e
"$PY" "$ROOT/tools/run_advanced10_queries.py" \
  --report "$report_path" \
  --cases "$ROOT/docs/query_eval_cases_advanced20.json" \
  --strict-all \
  --metadata-only \
  --output "$adv_path" >"$adv_log" 2>&1
adv_rc=$?
set -e
if [[ ! -f "$adv_path" ]]; then
  detail="$(extract_last_json "$adv_log")"
  echo "{\"ok\":false,\"error\":\"advanced20_failed\",\"detail\":$detail,\"log\":\"$adv_log\"}"
  exit 1
fi
if [[ $adv_rc -ne 0 ]]; then
  echo "{\"event\":\"run_q40_uia_synthetic.warning\",\"stage\":\"advanced20\",\"detail\":\"nonzero_exit_with_output\",\"log\":\"$adv_log\",\"output\":\"$adv_path\"}" >>"$adv_log"
fi

set +e
"$PY" "$ROOT/tools/run_advanced10_queries.py" \
  --report "$report_path" \
  --cases "$ROOT/docs/query_eval_cases_generic20.json" \
  --metadata-only \
  --output "$gen_path" >"$gen_log" 2>&1
gen_rc=$?
set -e
if [[ ! -f "$gen_path" ]]; then
  detail="$(extract_last_json "$gen_log")"
  echo "{\"ok\":false,\"error\":\"generic20_failed\",\"detail\":$detail,\"log\":\"$gen_log\"}"
  exit 1
fi
if [[ $gen_rc -ne 0 ]]; then
  echo "{\"event\":\"run_q40_uia_synthetic.warning\",\"stage\":\"generic20\",\"detail\":\"nonzero_exit_with_output\",\"log\":\"$gen_log\",\"output\":\"$gen_path\"}" >>"$gen_log"
fi

set +e
"$PY" "$ROOT/tools/eval_q40_matrix.py" \
  --advanced-json "$adv_path" \
  --generic-json "$gen_path" \
  --strict \
  --expected-total 40 \
  --out "$matrix_path" >"$matrix_log" 2>&1
matrix_rc=$?
set -e
if [[ $matrix_rc -ne 0 || ! -f "$matrix_path" ]]; then
  detail="$(extract_last_json "$matrix_log")"
  echo "{\"ok\":false,\"error\":\"strict_matrix_gate_failed\",\"detail\":$detail,\"log\":\"$matrix_log\",\"matrix\":\"$matrix_path\"}"
  exit 1
fi

cp "$adv_path" "$ROOT/artifacts/advanced10/advanced20_latest.json"
cp "$gen_path" "$ROOT/artifacts/advanced10/generic20_latest.json"
cp "$matrix_path" "$ROOT/artifacts/advanced10/q40_matrix_latest.json"

echo "{\"ok\":true,\"strict\":true,\"expected_total\":40,\"uia_mode\":\"$SYNTH_MODE\",\"report\":\"$report_path\",\"advanced\":\"$adv_path\",\"generic\":\"$gen_path\",\"matrix\":\"$matrix_path\",\"pack\":\"$pack_json\"}"
