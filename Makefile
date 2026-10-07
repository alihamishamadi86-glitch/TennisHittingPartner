.DEFAULT_GOAL := help
API := api
VENV := $(API)/.venv
PY := $(VENV)/bin/python

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up: ## Start the local stack (db, pubsub emulator, mailpit, api, worker)
	docker compose up -d --build

down: ## Stop the local stack
	docker compose down

logs: ## Tail api + worker logs
	docker compose logs -f api worker

$(VENV):
	python3.13 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e "$(API)[dev]"

install: $(VENV) ## Install backend deps into api/.venv and web deps
	cd web && npm install

lint: $(VENV) ## Lint + typecheck backend and frontend
	cd $(API) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app
	cd web && npm run lint && npm run typecheck

fmt: $(VENV) ## Auto-format backend
	cd $(API) && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

test: $(VENV) ## Run backend tests (requires `make up` for the db)
	cd $(API) && .venv/bin/pytest -q

migrate: ## Apply migrations to the local dev db
	docker compose run --rm migrate

migration: $(VENV) ## Create a migration: make migration m="add users"
	cd $(API) && DATABASE_URL=postgresql+asyncpg://thp:thp@localhost:55432/thp .venv/bin/alembic revision --autogenerate -m "$(m)"

topics: ## (Re)create Pub/Sub emulator topics after adding event types
	docker compose up -d --force-recreate pubsub-init

smoke: ## End-to-end check: API -> outbox -> Pub/Sub emulator -> worker
	./scripts/smoke_ping.sh http://localhost:8000

api-client: ## Regenerate the typed TS client from the running API's OpenAPI schema
	cd web && npm run gen:api

web: ## Run the Next.js dev server
	cd web && npm run dev

.PHONY: help up down logs install lint fmt test migrate migration topics smoke api-client web
