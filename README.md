# For You — Data Layer

Postgres + pgvector foundation for the personalized "For You" ranking engine
(see [`plan.md`](./plan.md) for the full project). This slice provides the
containerized database, the full schema, migrations, and an async SQLAlchemy 2.0
access layer that the ranking service and simulation will build on.

## Stack

- **Postgres 16 + pgvector** (`pgvector/pgvector:pg16`), `citext` for handles.
- **SQLAlchemy 2.0** async models (`asyncpg`) + **Alembic** migrations (`psycopg` sync).
- **384-dim embeddings** (local `all-MiniLM-L6-v2` — zero per-embedding API cost).
- **uv** for packaging, everything runs in **Docker Compose**.

## Quickstart

```bash
cp .env.example .env

# 1. Start Postgres (extensions enabled on first boot).
docker compose up -d db

# 2. Apply the schema.
docker compose run --rm app alembic upgrade head

# 3. Smoke-test embeddings + the covering index.
docker compose run --rm app python scripts/verify_smoke.py

# 4. Run the test suite.
docker compose run --rm app pytest
```

## Ranking-inspector demo (plan.md §9)

A live web app that serves the feed straight from the ranking engine, re-ranks on every
preference change, and explains each result. It's a *ranking inspector*, not an X clone:
the pipeline's stages, per-post scores, and the tunable preference layer are the point.

```bash
# Build the corpus the demo runs on.
docker compose run --rm app python scripts/seed_world.py --wipe
docker compose run --rm app python scripts/generate_embeddings.py
docker compose run --rm app python scripts/generate_topic_centroids.py
docker compose run --rm app python scripts/train_scorer.py

docker compose up api        # FastAPI ranking service -> http://localhost:8000
docker compose up web        # Vite demo frontend      -> http://localhost:5173
```

Open http://localhost:5173. Drag the recency / source-mix / reach / exploration sliders (or
weight a topic) and watch the feed re-rank live; click any post for the "Why this post?"
panel (source provenance, per-action model probabilities, feature values, preference
multiplier, MMR penalty) and read the live pipeline-stage trace. If host port 8000 is
taken, set `API_PORT` in `.env` — the frontend follows it automatically. The backend is
`src/foryou/web/` (FastAPI over `rank_feed`); the frontend + its design system are in `web/`.

## Live-trigger path (plan.md §8)

The **Operator** tab is the only place the world can be written to. Post something and a
small number of personas reply for real — then the feed re-ranks against a world that
actually changed.

Cost is bounded by construction, never by convention:

- **A fixed cap per action** (`LIVE_MAX_REACTIONS_PER_ACTION`, default 3).
- **Global daily counters** in `budget_ledger`, read *before* any model is called. Once
  spent, the trigger short-circuits to "no new reaction" — the post still publishes, but
  zero tokens are spent and zero API calls are made.
- **Guardrails in code, not the prompt**: which personas react and on what topic is decided
  in Python, and every generated reply is truncated and passed through the rule-based safety
  gate before it can be inserted. A rejected reply is still *charged* — the model ran.

```bash
# Same path from the CLI, no browser needed (--fake forces the offline LLM).
docker compose run --rm app python scripts/live_trigger.py \
    --handle reader_0 --content "shipping the ranking inspector today" --fake
```

With `OPENAI_API_KEY` set it calls `gpt-4o-mini`; unset, it falls back to a deterministic
offline `FakeLLM`, so the whole component runs at zero cost. New posts and replies are
embedded **inline**, so they are rankable candidates immediately — no follow-up
`make embeddings`.

Live content is timestamped on the **corpus clock** (`max(posts.created_at)` plus a beat),
not wall-clock. A wall-clock post would drag the ranking clock past the seeded world, age the
whole corpus out of the recency window, and empty the trending window.

## Schema

| Table | Purpose |
|-------|---------|
| `users` | Personas and real users (archetype + structured `persona_config`). |
| `posts` | Posts with reply / quote / conversation links and topic tags. |
| `follows` | Directed follow edges. |
| `engagements` | Append-only interaction event log — the scorer's training data. |
| `user_relationships` | Block / mute signals used as pipeline filters. |
| `post_embeddings` | Per-post content vectors (`Vector(384)`). |
| `user_embeddings` | Per-user engagement-history centroid. |
| `topic_centroids` | Per-topic centroid for the topic sliders. |
| `post_velocity` | Rolling engagement-velocity aggregates, refreshed in batch by the world simulation (`make simulate`). |
| `feed_impressions` | Explainability log written by the ranking service — backs "Why this post?". |
| `budget_ledger` | Daily token / reaction counters enforcing the live-trigger cap (`make live`). |

Embeddings and velocity live in **dedicated tables** rather than columns on
`posts`/`users`, so the vector index and high-churn velocity writes stay isolated
from the hot recency-scan tables.

## Indexing rationale

- **`posts (author_id, created_at)` INCLUDE `(id)`** — the flagship covering index
  for the in-network source ("recent posts by followee":
  `WHERE author_id IN (...) ORDER BY created_at DESC`). A composite ASC btree
  serves the `DESC` order via a backward index scan, and the `INCLUDE(id)` keeps
  the candidate-id fetch index-only. *Why Postgres here:* X's real system uses an
  in-memory store (Thunder) for this hot read; at this project's scale a covering
  index keeps a single source of truth with acceptable latency and no extra
  infrastructure.
- **`post_embeddings (embedding)` HNSW `vector_cosine_ops`** — approximate nearest
  neighbour for the out-of-network similarity source (cosine `<=>`). HNSW over
  IVFFlat: better recall/latency and no training step; higher build cost is
  negligible at this scale.
- **`posts.topics` GIN** — topic-slider filtering over the topic-tag array.
- **`posts (created_at)`** — global recency / out-of-network fallback.
- **`posts (conversation_id | in_reply_to_id | quoted_post_id)`** — thread traversal.
- **`follows (followee_id)`** — "who follows me" (the PK covers the follower side).
- **`engagements (post_id, created_at)` / `(user_id, created_at)`** — velocity
  aggregation and per-user history for embeddings.

## Layout

```
src/foryou/
  config.py            # pydantic-settings + EMBEDDING_DIM
  db/
    base.py            # DeclarativeBase + naming convention
    session.py         # async engine + async_sessionmaker
    enums.py mixins.py
    models/            # one file per table
migrations/            # Alembic env + versions
db/init/               # extension bootstrap SQL
scripts/verify_smoke.py
tests/
```
