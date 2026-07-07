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
| `post_velocity` | Rolling engagement-velocity aggregates (trends). |
| `feed_impressions` | Explainability log (written by the ranking service later). |
| `budget_ledger` | Daily cap for the bounded live-trigger path. |

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
