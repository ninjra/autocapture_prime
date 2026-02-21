#!/usr/bin/env bash
set -euo pipefail

HOST="127.0.0.1"
PORT="${1:-8000}"
ROOT_URL="http://${HOST}:${PORT}"
API_URL="${ROOT_URL}/v1"
EXPECTED_MODEL="${AUTOCAPTURE_VLM_MODEL:-internvl3_5_8b}"
ORCH_CMD="${AUTOCAPTURE_VLM_ORCHESTRATOR_CMD:-bash /mnt/d/projects/hypervisor/tools/wsl/start_internvl35_8b_with_watch.sh}"

echo "probe_base_url=${API_URL}"
models_json="$(curl -fsS --max-time 4 "${API_URL}/models")" || {
  echo "ok=false error=models_unreachable"
  echo "orchestrator_cmd=${ORCH_CMD}"
  exit 1
}

selected_model="$(python3 - <<'PY' "${models_json}" "${EXPECTED_MODEL}"
import json, re, sys
payload = json.loads(sys.argv[1])
expected = str(sys.argv[2] or "").strip()
aliases = {
    re.sub(r"[^a-z0-9]+", "", expected.lower()),
    re.sub(r"[^a-z0-9]+", "", "internvl3_5_8b"),
    re.sub(r"[^a-z0-9]+", "", "internvl3.5-8b"),
    re.sub(r"[^a-z0-9]+", "", "internvl35_8b"),
}
models = []
for item in (payload.get("data") or []):
    if isinstance(item, dict):
        mid = str(item.get("id") or "").strip()
        if mid:
            models.append(mid)
for mid in models:
    norm = re.sub(r"[^a-z0-9]+", "", mid.lower())
    for a in aliases:
        if a and (norm == a or a in norm or norm in a):
            print(mid)
            raise SystemExit(0)
print("")
PY
)"
if [[ -z "${selected_model}" ]]; then
  echo "ok=false error=models_missing_expected"
  echo "expected_model=${EXPECTED_MODEL}"
  echo "orchestrator_cmd=${ORCH_CMD}"
  echo "${models_json}"
  exit 1
fi

completion_json="$(curl -fsS --max-time "${AUTOCAPTURE_VLM_PREFLIGHT_COMPLETION_TIMEOUT_S:-12}" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${selected_model}\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_completion_tokens\":8,\"max_tokens\":8,\"temperature\":0}" \
  "${API_URL}/chat/completions")" || {
  echo "ok=false error=completion_unreachable"
  echo "orchestrator_cmd=${ORCH_CMD}"
  exit 1
}

echo "ok=true"
echo "selected_model=${selected_model}"
echo "${models_json}"
echo "${completion_json}"
