#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${1:-}"
PORT="${2:-8000}"
BASE_TIMEOUT="${3:-20}"
IDLE_TIMEOUT="${4:-30}"
HARD_TIMEOUT="${5:-300}"

echo "whoami: $(whoami)"
echo "uname: $(uname -a)"
echo "python: $(python3 -V 2>&1)"
echo "nvidia-smi: $(nvidia-smi -L 2>&1 || true)"
echo "model_path: ${MODEL_PATH}"
if [ -z "${MODEL_PATH}" ]; then
  echo "ERROR: model path missing"
  exit 2
fi

if [ ! -e "${MODEL_PATH}" ]; then
  echo "ERROR: model path not found"
  exit 2
fi

echo "model_path_contents:"
ls -lah "${MODEL_PATH}" | head -n 20

if [ ! -f "${MODEL_PATH}/config.json" ]; then
  echo "WARN: config.json missing under model path"
fi

py="/usr/bin/python3"
if [ -x "/home/justi/.venvs/vllm/bin/python" ]; then
  py="/home/justi/.venvs/vllm/bin/python"
elif [ -x "$HOME/.venvs/vllm/bin/python" ]; then
  py="$HOME/.venvs/vllm/bin/python"
fi

echo "python_bin: ${py}"
echo "starting_vllm_foreground..."
LOG_PATH="/tmp/vllm_probe_runtime.log"
: > "${LOG_PATH}"
"${py}" -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port "${PORT}" \
  --model "${MODEL_PATH}" \
  --dtype auto \
  --gpu-memory-utilization 0.9 \
  --max-model-len 2048 \
  > "${LOG_PATH}" 2>&1 &
pid=$!
start_ts="$(date +%s)"
last_activity="${start_ts}"
last_size=0

while true; do
  if curl -fsS "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    echo "vllm_ready:1"
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
    cat "${LOG_PATH}"
    echo "vllm_exit_code:0"
    exit 0
  fi
  if ! kill -0 "${pid}" >/dev/null 2>&1; then
    wait "${pid}" || true
    code=$?
    cat "${LOG_PATH}"
    echo "vllm_exit_code:${code}"
    exit "${code}"
  fi
  size="$(stat -c %s "${LOG_PATH}" 2>/dev/null || echo 0)"
  if [ "${size}" -ne "${last_size}" ]; then
    last_size="${size}"
    last_activity="$(date +%s)"
  fi
  now="$(date +%s)"
  if [ $((now-start_ts)) -ge "${HARD_TIMEOUT}" ]; then
    echo "probe_timeout:hard"
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
    cat "${LOG_PATH}"
    echo "vllm_exit_code:124"
    exit 124
  fi
  if [ $((now-start_ts)) -ge "${BASE_TIMEOUT}" ] && [ $((now-last_activity)) -ge "${IDLE_TIMEOUT}" ]; then
    echo "probe_timeout:idle"
    kill "${pid}" >/dev/null 2>&1 || true
    wait "${pid}" >/dev/null 2>&1 || true
    cat "${LOG_PATH}"
    echo "vllm_exit_code:124"
    exit 124
  fi
  sleep 1
done
