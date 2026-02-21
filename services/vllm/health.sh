#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
curl -sS --max-time 3 "${BASE_URL%/}/v1/models"
