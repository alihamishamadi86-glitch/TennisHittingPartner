#!/usr/bin/env bash
# Verifies the event pipeline end to end: POST a ping, then poll until the worker marks it received.
# Usage: scripts/smoke_ping.sh <api-base-url> [bearer-token]
set -euo pipefail

BASE_URL="${1:?api base url required}"
AUTH=()
[[ -n "${2:-}" ]] && AUTH=(-H "Authorization: Bearer $2")

ping_id=$(curl -sf -X POST ${AUTH[@]+"${AUTH[@]}"} "$BASE_URL/system/ping" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
echo "ping $ping_id created"

for _ in $(seq 1 30); do
  received=$(curl -sf ${AUTH[@]+"${AUTH[@]}"} "$BASE_URL/system/ping/$ping_id" | python3 -c 'import json,sys; print(json.load(sys.stdin)["received_at"] or "")')
  if [[ -n "$received" ]]; then
    echo "✅ worker received ping at $received"
    exit 0
  fi
  sleep 1
done

echo "❌ ping not received by worker within 30s" >&2
exit 1
