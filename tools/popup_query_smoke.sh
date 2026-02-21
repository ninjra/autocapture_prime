#!/usr/bin/env bash
set -euo pipefail

Q="${1:-what am i working on right now}"
BASE="${AUTOCAPTURE_WEB_BASE_URL:-http://127.0.0.1:8787}"

TOKEN_JSON="$(curl -sS --max-time 3 "$BASE/api/auth/token")"
TOKEN="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("token",""))' "$TOKEN_JSON")"
if [[ -z "$TOKEN" ]]; then
  echo "{\"ok\":false,\"error\":\"missing_token\",\"base\":\"$BASE\"}"
  exit 1
fi

curl -sS --max-time 20 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"$Q\",\"max_citations\":6}" \
  "$BASE/api/query/popup"
