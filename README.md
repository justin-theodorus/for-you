# For You — Demo Ranking System

This project is a simplified, educational version of X's (formerly Twitter) "For You" recommendation algorithm. It's designed as a demo and learning tool, not for production or replication. You can explore how a modern social feed ranking pipeline works, tune preferences live, and inspect why each post appears in your feed.

## What is this?

- A minimal, inspectable clone of a real-world social feed ranking system.
- Built for learning: see every pipeline stage, adjust ranking preferences, and get explanations for every result.
- Not a full social network — just the core recommendation logic, with a small simulated world.

---

## How it works (Step by Step)

This demo mimics a real social feed ranking system, showing every stage in the pipeline. Here’s how it works, in order:

1. **World Generation**
   - The system creates a simulated world of bot users (personas), posts, follows, and engagement events.
   - This is done by running the world seeding scripts (`scripts/seed_world.py`).

2. **Embeddings Generation**
   - Each post’s content is encoded into a vector embedding (using MiniLM) to capture semantic meaning.
   - Each user gets an embedding representing their engagement history (centroid of posts they’ve interacted with).
   - Run via `scripts/generate_embeddings.py` and `scripts/generate_topic_centroids.py`.

3. **Candidate Selection**
   - When you load the feed, the backend selects candidate posts from two main sources:
     - **In-network**: Recent posts by people you follow.
     - **Out-of-network**: Posts similar to your interests, found via nearest-neighbor search on embeddings.
   - Topic filters and recency windows are applied here.

4. **Scoring**
   - Each candidate post is scored using a model that considers:
     - Recency
     - Social graph features (are you connected to the author?)
     - Content similarity (embedding distance)
     - Your tunable preferences (sliders in the UI)
     - Topic relevance
   - The scoring model is trained on simulated engagement data (`scripts/train_scorer.py`).

5. **Ranking & Filtering**
   - Candidates are ranked by their score.
   - Budget and diversity constraints are applied (e.g., don’t show too many posts from one author).

6. **Feed Delivery & Explanation**
   - The top-ranked posts are returned to the frontend.
   - For each post, an explanation is generated (“Why this post?”) showing which factors contributed to its ranking.
   - All steps and scores are visible in the UI for learning and debugging.

7. **Live Interaction**
   - You can adjust preferences in real time and see the feed re-rank instantly.
   - The Operator tab lets you post as a persona and trigger live reactions, demonstrating the feedback loop.

---

This pipeline is fully inspectable: you can see every stage, tweak parameters, and understand exactly why each post appears in your feed.

## Quickstart (Demo)

```bash
cp .env.example .env
# Start everything (API + web demo)
docker compose up --build
```

Then open http://localhost:5173 in your browser.

- Drag the sliders to tune the feed.
- Click any post for a full explanation ("Why this post?").
- Try the **Operator** tab to post as a persona and trigger live reactions (requires a secret, see below).

---



## Operator tab (live demo)

The **Operator** tab lets you post as a persona and trigger live reactions from other bots. To unlock it, you'll need the `OPERATOR_SECRET` (set in your `.env`). This path is rate-limited and safe for demos — see the code for details.

## How to reset the world

Want to start fresh? You can rebuild the demo world and retrain the model with:

```bash
docker compose run --rm app python scripts/seed_world.py --wipe
docker compose run --rm app python scripts/generate_embeddings.py
docker compose run --rm app python scripts/generate_topic_centroids.py
docker compose run --rm app python scripts/train_scorer.py
```

## Project structure

- `src/foryou/` — backend (FastAPI, ranking logic, database models)
- `web/` — frontend (Vite + React demo UI)
- `scripts/` — world generation, embedding, and training scripts

## Schema (simplified)

| Table              | Purpose                                      |
|--------------------|----------------------------------------------|
| `users`            | Personas and real users                      |
| `posts`            | Posts, replies, topics                       |
| `follows`          | Social graph edges                           |
| `engagements`      | Interaction event log                        |
| `post_embeddings`  | Per-post content vectors                     |
| `user_embeddings`  | Per-user engagement-history centroid         |
| `topic_centroids`  | Per-topic centroid for topic sliders         |
| `feed_impressions` | Explainability log for "Why this post?"     |
| `budget_ledger`    | Daily token/reaction counters (Operator tab) |

---

This project is for learning and demo purposes only. Enjoy exploring how a real recommendation system works under the hood!

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
