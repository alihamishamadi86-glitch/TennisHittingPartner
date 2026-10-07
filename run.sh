#!/usr/bin/env bash
# Run the whole app locally: backend stack in Docker, Next.js dev server in the foreground.
#   ./run.sh         start everything (Ctrl-C stops the web server; the stack keeps running)
#   ./run.sh down    stop the Docker stack
#   ./run.sh logs    tail api + worker logs
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-up}" in
  down) exec docker compose down ;;
  logs) exec docker compose logs -f api worker ;;
  up) ;;
  *) echo "usage: $0 [up|down|logs]" >&2; exit 2 ;;
esac

command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
command -v npm >/dev/null || { echo "Node 20+ (npm) is required" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker isn't running — start Docker Desktop first" >&2; exit 1; }

echo "▶ Starting db, Pub/Sub emulator, mailpit, api, worker…"
docker compose up -d --build

echo "▶ Waiting for the API…"
for _ in $(seq 1 60); do
  curl -sf http://localhost:8000/readyz >/dev/null && break
  sleep 2
done
curl -sf http://localhost:8000/readyz >/dev/null || {
  echo "API didn't become ready; recent logs:" >&2
  docker compose logs --tail 50 api >&2
  exit 1
}

echo "▶ Checking the event pipeline (API → Pub/Sub → worker)…"
./scripts/smoke_ping.sh http://localhost:8000

[[ -d web/node_modules ]] || (cd web && npm install)
[[ -f web/.env.local ]] || cp web/.env.example web/.env.local

cat <<'EOF'

  Web       http://localhost:3000
  API docs  http://localhost:8000/docs
  Email     http://localhost:8025   (verification / reset emails land here)

  Make an account admin:  docker compose exec api python -m scripts.create_admin you@example.com
  Stop the backend:       ./run.sh down

EOF

cd web && exec npm run dev
