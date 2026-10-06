# Tennis Hitting Partner

Platform that matches tennis players with vetted hitting partners.

| Path | What |
|---|---|
| [`api/`](api/) | FastAPI REST API + Pub/Sub worker (Python 3.13, SQLAlchemy 2, Alembic) |
| [`web/`](web/) | Next.js 16 (App Router, TypeScript, Tailwind) |
| [`infra/terraform/`](infra/terraform/) | Google Cloud infrastructure (Cloud Run, Cloud SQL, Pub/Sub, Scheduler, Tasks) |
| [`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md) | Architecture, requirements and milestones |

## Local development

Prerequisites: Docker, Python 3.13, Node 20.

```bash
make install     # api/.venv + web/node_modules
make up          # postgis, pubsub emulator, mailpit, api (:8000), worker (:8001)
make smoke       # API → outbox → Pub/Sub emulator → worker round trip
make web         # Next.js on :3000
```

| URL | Service |
|---|---|
| http://localhost:3000 | Web |
| http://localhost:8000/docs | API (OpenAPI UI) |
| http://localhost:8025 | Mailpit (captured email) |

Make yourself an admin locally (after registering in the UI):
`docker compose exec api python -m scripts.create_admin you@example.com`.

Other targets: `make test`, `make lint`, `make fmt`, `make migration m="..."`, `make api-client`
(regenerates `web/src/lib/api/schema.d.ts` from the running API). Run `make help` for the list.

## How events flow

1. A request handler changes state **and** calls `record_event(...)` in the same transaction
   (transactional outbox, `outbox_events` table).
2. The relay publishes pending rows to Pub/Sub — immediately after commit, plus a sweep every
   minute (Cloud Scheduler in GCP; an in-process loop in the local worker).
3. Pub/Sub pushes to the worker's `/pubsub/push`; handlers registered with `@handles(...)` run
   once per consumer (`processed_events` makes redeliveries no-ops).

Adding an event: add it to `api/app/events/catalog.py`, add the topic to `event_types` in
`infra/terraform`, write a handler in `api/app/events/handlers/`, and re-run `make up` locally
so the emulator bootstrap creates the topic.
