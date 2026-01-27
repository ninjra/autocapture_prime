#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEV_DIR="$ROOT/.dev"
LOG_DIR="$DEV_DIR/logs"
PID_DIR="$DEV_DIR/pids"
STATE_DIR="$DEV_DIR/state"
CACHE_DIR="$DEV_DIR/cache"

COMMON_ENV="$ROOT/ops/dev/common.env"
PORTS_ENV="$ROOT/ops/dev/ports.env"

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

say() {
  printf "%s\n" "$*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf "WARN %s\n" "$*"
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf "PASS %s\n" "$*"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf "FAIL %s\n" "$*" >&2
}

die() {
  fail "$*"
  exit 1
}

have_cmd() {
  command -v "$1" >/dev/null 2>&1
}

ensure_dev_dirs() {
  mkdir -p "$LOG_DIR" "$PID_DIR" "$STATE_DIR" "$CACHE_DIR"
}

load_env() {
  local f
  for f in "$COMMON_ENV" "$PORTS_ENV"; do
    if [ -f "$f" ]; then
      # shellcheck disable=SC1090
      set -a
      . "$f"
      set +a
    fi
  done
}

is_wsl() {
  if [ -r /proc/version ]; then
    grep -qi microsoft /proc/version
  else
    return 1
  fi
}

python_cmd() {
  if [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
  elif have_cmd python3; then
    echo python3
  elif have_cmd python; then
    echo python
  else
    echo ""
  fi
}

python_version_ok() {
  local py="$1"
  "$py" - <<'PY'
import sys
ok = sys.version_info >= (3, 10)
raise SystemExit(0 if ok else 1)
PY
}

port_free() {
  local port="$1"
  local py="$2"
  "$py" - <<'PY' "$port"
import socket
import sys
port = int(sys.argv[1])
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", port))
    s.listen(1)
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

port_open() {
  local port="$1"
  local py="$2"
  "$py" - <<'PY' "$port"
import socket
import sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", port))
    sys.exit(0)
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

port_owner_pid() {
  local port="$1"
  local pid=""
  if have_cmd lsof; then
    pid=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)
  elif have_cmd ss; then
    pid=$(ss -ltnp "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -n 1 || true)
  fi
  if [ -n "$pid" ]; then
    printf "%s" "$pid"
  fi
}

pid_path() {
  printf "%s/%s.pid" "$PID_DIR" "$1"
}

log_path() {
  printf "%s/%s.log" "$LOG_DIR" "$1"
}

pid_alive() {
  local pid_file="$1"
  if [ ! -f "$pid_file" ]; then
    return 1
  fi
  local pid
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -z "$pid" ]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

stop_service() {
  local name="$1"
  local pid_file
  pid_file=$(pid_path "$name")
  if [ ! -f "$pid_file" ]; then
    say "$name: not running"
    return 0
  fi
  local pid
  pid=$(cat "$pid_file" 2>/dev/null || true)
  if [ -z "$pid" ]; then
    rm -f "$pid_file"
    say "$name: stale pid file removed"
    return 0
  fi
  if kill -0 "$pid" 2>/dev/null; then
    say "$name: stopping (pid $pid)"
    kill "$pid" 2>/dev/null || true
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
      sleep 0.2
      waited=$((waited + 1))
      if [ "$waited" -ge 25 ]; then
        say "$name: force stopping (pid $pid)"
        kill -9 "$pid" 2>/dev/null || true
        break
      fi
    done
  fi
  rm -f "$pid_file"
  say "$name: stopped"
}

start_service() {
  local name="$1"
  local cmd="$2"
  if [ -z "$cmd" ]; then
    die "$name: missing start command. Set DEV_${name^^}_CMD in ops/dev/common.env"
  fi
  ensure_dev_dirs
  local log_file
  log_file=$(log_path "$name")
  touch "$log_file"
  say "$name: starting"
  nohup bash -lc "$cmd" >>"$log_file" 2>&1 &
  local pid=$!
  printf "%s" "$pid" >"$(pid_path "$name")"
  printf "%s" "$cmd" >"$STATE_DIR/${name}.cmd"
  say "$name: started (pid $pid)"
}

check_ready() {
  local name="$1"
  local port_var="$2"
  local health_var="$3"
  local py="$4"
  local pid_file
  pid_file=$(pid_path "$name")
  if ! pid_alive "$pid_file"; then
    return 1
  fi
  local port="${!port_var:-}"
  local health_url="${!health_var:-}"
  if [ -n "$health_url" ]; then
    if [ -z "$py" ]; then
      return 1
    fi
    "$py" - <<'PY' "$health_url" || return 1
import sys
import urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=1) as resp:
        sys.exit(0 if resp.status < 400 else 1)
except Exception:
    sys.exit(1)
PY
    return 0
  fi
  if [ -n "$port" ] && [ -n "$py" ]; then
    port_open "$port" "$py"
    return $?
  fi
  return 0
}

wait_ready() {
  local name="$1"
  local port_var="$2"
  local health_var="$3"
  local py="$4"
  local timeout="${DEV_READY_TIMEOUT:-20}"
  local waited=0
  while [ "$waited" -lt "$timeout" ]; do
    if check_ready "$name" "$port_var" "$health_var" "$py"; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

service_up() {
  local name="$1"
  local cmd_var="$2"
  local port_var="$3"
  local health_var="$4"
  local py="$5"
  local pid_file
  pid_file=$(pid_path "$name")

  if pid_alive "$pid_file"; then
    if check_ready "$name" "$port_var" "$health_var" "$py"; then
      say "$name: already running"
      return 0
    fi
    say "$name: running but not ready, restarting"
    stop_service "$name"
  fi

  local cmd="${!cmd_var:-}"
  if [ -z "$cmd" ]; then
    die "$name: start command unknown. Set DEV_${name^^}_CMD in ops/dev/common.env"
  fi
  start_service "$name" "$cmd"
  if ! wait_ready "$name" "$port_var" "$health_var" "$py"; then
    die "$name: failed to become ready"
  fi
  say "$name: ready"
}

usage() {
  cat <<'USAGE'
Usage: ./dev.sh <verb> [args]

Verbs:
  doctor   Validate repo and toolchain
  up       Start backend service
  down     Stop backend service
  logs     Show logs (default: backend)
  test     Run test plan
  fmt      Run formatter (optional)
  reset    Stop services and clear .dev state
  ui       Launch UI (optional)
USAGE
}

cmd_doctor() {
  load_env
  ensure_dev_dirs

  if [ ! -f "$ROOT/DEV_HARNESS.md" ]; then
    fail "DEV_HARNESS.md missing"
  else
    pass "DEV_HARNESS.md present"
  fi
  if [ ! -f "$ROOT/dev.sh" ]; then
    fail "dev.sh missing"
  else
    pass "dev.sh present"
  fi
  if [ ! -f "$ROOT/dev.ps1" ]; then
    fail "dev.ps1 missing"
  else
    pass "dev.ps1 present"
  fi
  if [ ! -f "$ROOT/ops/dev/common.env.example" ]; then
    fail "ops/dev/common.env.example missing"
  else
    pass "ops/dev/common.env.example present"
  fi
  if [ ! -f "$ROOT/ops/dev/ports.env.example" ]; then
    fail "ops/dev/ports.env.example missing"
  else
    pass "ops/dev/ports.env.example present"
  fi

  local py
  py=$(python_cmd)
  if [ -z "$py" ]; then
    fail "python not found (required for this repo)"
  else
    if python_version_ok "$py"; then
      pass "python >= 3.10 (${py})"
    else
      fail "python < 3.10 (${py})"
    fi
  fi

  if is_wsl; then
    if printf "%s" "$ROOT" | grep -q "^/mnt/c"; then
      warn "repo under /mnt/c (WSL performance warning)"
    else
      pass "WSL path OK"
    fi
  fi

  if [ -n "${DEV_BACKEND_PORT:-}" ]; then
    if [ -z "$py" ]; then
      fail "DEV_BACKEND_PORT set but python missing for port check"
    else
      if port_free "$DEV_BACKEND_PORT" "$py"; then
        pass "backend port $DEV_BACKEND_PORT is free"
      else
        local owner
        owner=$(port_owner_pid "$DEV_BACKEND_PORT")
        local pid_file
        pid_file=$(pid_path backend)
        if [ -n "$owner" ] && [ -f "$pid_file" ]; then
          local expected
          expected=$(cat "$pid_file" 2>/dev/null || true)
          if [ "$owner" = "$expected" ]; then
            pass "backend port $DEV_BACKEND_PORT in use by expected pid $owner"
          else
            fail "backend port $DEV_BACKEND_PORT in use by pid $owner (expected $expected)"
          fi
        else
          fail "backend port $DEV_BACKEND_PORT is in use"
        fi
      fi
    fi
  fi

  if [ -n "${DEV_UI_PORT:-}" ]; then
    if [ -z "$py" ]; then
      fail "DEV_UI_PORT set but python missing for port check"
    else
      if port_free "$DEV_UI_PORT" "$py"; then
        pass "ui port $DEV_UI_PORT is free"
      else
        local owner
        owner=$(port_owner_pid "$DEV_UI_PORT")
        local pid_file
        pid_file=$(pid_path ui)
        if [ -n "$owner" ] && [ -f "$pid_file" ]; then
          local expected
          expected=$(cat "$pid_file" 2>/dev/null || true)
          if [ "$owner" = "$expected" ]; then
            pass "ui port $DEV_UI_PORT in use by expected pid $owner"
          else
            fail "ui port $DEV_UI_PORT in use by pid $owner (expected $expected)"
          fi
        else
          fail "ui port $DEV_UI_PORT is in use"
        fi
      fi
    fi
  fi

  if [ "$FAIL_COUNT" -gt 0 ]; then
    exit 2
  fi
  if [ "$WARN_COUNT" -gt 0 ]; then
    exit 1
  fi
  exit 0
}

cmd_up() {
  load_env
  ensure_dev_dirs
  local py
  py=$(python_cmd)
  service_up backend DEV_BACKEND_CMD DEV_BACKEND_PORT DEV_BACKEND_HEALTH_URL "$py"
}

cmd_down() {
  load_env
  ensure_dev_dirs
  stop_service backend
  stop_service ui
}

cmd_logs() {
  ensure_dev_dirs
  local service="${1:-backend}"
  local follow="${2:-}"
  local log_file
  log_file=$(log_path "$service")
  if [ ! -f "$log_file" ]; then
    die "$service: no log file at $log_file"
  fi
  if [ "$follow" = "-f" ] || [ "$follow" = "--follow" ]; then
    tail -n 200 -f "$log_file"
  else
    tail -n 200 "$log_file"
  fi
}

cmd_test() {
  load_env
  local py
  py=$(python_cmd)
  if [ -z "$py" ]; then
    die "python not found (required to run tests)"
  fi
  "$py" tools/run_all_tests.py
}

cmd_fmt() {
  load_env
  local cmd="${DEV_FMT_CMD:-}"
  if [ -z "$cmd" ]; then
    die "formatter not configured. Set DEV_FMT_CMD in ops/dev/common.env"
  fi
  bash -lc "$cmd"
}

ui_detected() {
  if [ -f "$ROOT/package.json" ]; then
    return 0
  fi
  local d
  for d in ui frontend client web apps; do
    if [ -d "$ROOT/$d" ]; then
      return 0
    fi
  done
  return 1
}

cmd_ui() {
  load_env
  ensure_dev_dirs
  if ! ui_detected; then
    say "No UI detected (no package.json or ui/frontend/client/web/apps directory)"
    exit 2
  fi
  local cmd="${DEV_UI_CMD:-}"
  if [ -z "$cmd" ]; then
    die "UI detected but launch command unclear. Set DEV_UI_CMD in ops/dev/common.env"
  fi
  local py
  py=$(python_cmd)
  service_up ui DEV_UI_CMD DEV_UI_PORT DEV_UI_HEALTH_URL "$py"
}

cmd_reset() {
  cmd_down
  rm -rf "$DEV_DIR"
  say "reset: cleared $DEV_DIR"
}

main() {
  local verb="${1:-}"
  shift || true
  case "$verb" in
    doctor) cmd_doctor "$@" ;;
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    logs) cmd_logs "$@" ;;
    test) cmd_test "$@" ;;
    fmt) cmd_fmt "$@" ;;
    reset) cmd_reset "$@" ;;
    ui) cmd_ui "$@" ;;
    ""|help|-h|--help) usage ;;
    *)
      say "Unknown verb: $verb"
      usage
      exit 2
      ;;
  esac
}

main "$@"
