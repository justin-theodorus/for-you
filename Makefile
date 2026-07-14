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
	smoke seed personas simulate live embeddings centroids train feed api web test test-clean lint format typecheck check shell psql

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

seed: ## Seed a synthetic world: make seed ARGS="--wipe --seed 7"
	$(APP) python scripts/seed_world.py $(ARGS)

personas: ## Generate LLM persona posts (offline w/o OPENAI_API_KEY): make personas ARGS="--posts-per-persona 3"
	$(APP) python scripts/generate_personas.py $(ARGS)

simulate: ## Advance the world by N ticks (templated, additive): make simulate ARGS="--ticks 6"
	$(APP) python scripts/simulate.py $(ARGS)

live: ## Post as a user + trigger bounded persona reactions (§8): make live ARGS='--content "hi" --fake'
	$(APP) python scripts/live_trigger.py $(ARGS)

embeddings: ## Generate post embeddings: make embeddings ARGS="--limit 20 --regenerate"
	$(APP) python scripts/generate_embeddings.py $(ARGS)

centroids: ## Backfill topic centroids (run after embeddings) for the topic sliders
	$(APP) python scripts/generate_topic_centroids.py $(ARGS)

train: ## Train the scoring model: make train ARGS="--negative-ratio 3 --users all"
	$(APP) python scripts/train_scorer.py $(ARGS)

feed: ## Rank a user's feed: make feed ARGS="--handle reader_0 --limit 20"
	$(APP) python scripts/rank_feed.py $(ARGS)

## --- Web app (plan.md §9) ---

api: ## Serve the ranking API at http://localhost:8000 (needs seed+embeddings+centroids+train)
	$(COMPOSE) up api

web: ## Serve the demo frontend at http://localhost:5173 (start `make api` first)
	$(COMPOSE) up web

## --- Quality ---

test: ## Run the test suite: make test ARGS="-k name -v"
	$(APP) pytest $(ARGS)

test-clean: ## Wipe committed seed data first, then run the suite (tests assume a clean DB)
	$(COMPOSE) up -d db
	$(COMPOSE) exec db psql -U foryou -d foryou -c "TRUNCATE users CASCADE;"
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
