# For You — common workflows. All Python tooling runs inside the `app` container
# (deps live there, not on the host). `docker compose run --rm app` auto-starts the
# db service via depends_on, so most targets work without a separate `make up`.
#
# Run `make` or `make help` for the list.

COMPOSE := docker compose
APP := $(COMPOSE) run --rm app

# Extra args pass-through, e.g. `make test ARGS="-k embedding -v"`.
ARGS ?=

.DEFAULT_GOAL := help

.PHONY: help setup build up down reset migrate revision migrate-check \
	smoke embeddings test lint format typecheck check shell psql

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

## --- Setup & containers ---

setup: ## Create .env from .env.example (first-time only)
	@test -f .env && echo ".env already exists" || (cp .env.example .env && echo "created .env")

build: ## Build the app image (installs deps incl. CPU-only torch)
	$(COMPOSE) build app

up: ## Start Postgres in the background
	$(COMPOSE) up -d db

down: ## Stop all containers
	$(COMPOSE) down

reset: ## Stop containers AND wipe the Postgres volume (destroys data)
	$(COMPOSE) down -v

## --- Migrations ---

migrate: ## Apply migrations (alembic upgrade head)
	$(APP) alembic upgrade head

revision: ## Autogenerate a migration: make revision m="describe change"
	@test -n "$(m)" || { echo 'usage: make revision m="describe change"'; exit 1; }
	$(APP) alembic revision --autogenerate -m "$(m)"

migrate-check: ## Verify models match the DB (no drift)
	$(APP) alembic check

## --- Scripts ---

smoke: ## Run the end-to-end data-layer smoke test
	$(APP) python scripts/verify_smoke.py

embeddings: ## Generate post embeddings: make embeddings ARGS="--limit 20 --regenerate"
	$(APP) python scripts/generate_embeddings.py $(ARGS)

## --- Quality ---

test: ## Run the test suite: make test ARGS="-k name -v"
	$(APP) pytest $(ARGS)

lint: ## Lint with ruff
	$(APP) ruff check .

format: ## Auto-fix lint issues and format with ruff
	$(APP) bash -lc "ruff check --fix . && ruff format ."

typecheck: ## Type-check with mypy (strict)
	$(APP) mypy src scripts tests

check: ## Lint + type-check (the pre-commit gate)
	$(APP) bash -lc "ruff check . && mypy src scripts tests"

## --- Shells ---

shell: ## Open a bash shell in the app container
	$(APP) bash

psql: ## Open psql in the running db container
	$(COMPOSE) exec db psql -U foryou -d foryou
