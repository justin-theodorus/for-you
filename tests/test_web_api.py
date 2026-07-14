"""Integration tests for the FastAPI ranking service (plan.md §9).

Drives the ASGI app with httpx + ASGITransport, overriding ``get_session`` with the
rolled-back fixture session so every endpoint runs inside the same isolated transaction
(the feed endpoint's ``commit()`` releases a savepoint, exactly like the CLI paths).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.config import settings
from foryou.db.models import Post, User
from foryou.db.session import get_session
from foryou.embeddings import generate_embeddings, generate_topic_centroids
from foryou.personas import FakeLLM
from foryou.seed import SeedConfig, seed_world
from foryou.web.app import create_app
from foryou.web.deps import get_encoder, get_llm_client
from tests.test_encoder import FakeEncoder

_SEED = SeedConfig(
    personas=8,
    readers=3,
    posts_per_persona=5,
    follows_per_user=4,
    engagements_per_user=8,
    seed=7,
)


async def _seed_world(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    await generate_embeddings(session, FakeEncoder(), batch_size=100)
    await generate_topic_centroids(session)


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """An ASGI client whose endpoints run in the test's rolled-back session.

    The encoder and LLM client are overridden too, so the live-trigger endpoint (plan.md §8)
    runs fully offline: no torch, no OpenAI import, no spend.
    """
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _override
    app.dependency_overrides[get_encoder] = lambda: FakeEncoder()
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def seeded(session: AsyncSession) -> None:
    await _seed_world(session)


async def _reader_handle(session: AsyncSession) -> str:
    reader = await session.scalar(
        select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
    )
    assert reader is not None
    return reader.handle


async def _persona_handle(session: AsyncSession) -> str:
    persona = await session.scalar(
        select(User).where(User.is_persona.is_(True)).order_by(User.handle).limit(1)
    )
    assert persona is not None
    return persona.handle


def _post_ids(payload: dict[str, Any]) -> list[str]:
    return [item["post_id"] for item in payload["items"]]


async def test_feed_returns_ranked_explainable_items(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)

    response = await client.post("/api/feed", json={"handle": handle})

    assert response.status_code == 200
    payload = response.json()
    items = payload["items"]
    assert items, "seeded world should produce a non-empty feed"
    # Ranks are dense and ordered 0..n-1.
    assert [item["rank"] for item in items] == list(range(len(items)))
    # Every item carries the explainability payload the impression log persists.
    first = items[0]
    assert first["why"]["sources"], "each post must record its source provenance"
    assert set(first["why"]["action_scores"]) == {"like", "reply", "repost", "quote", "dwell"}
    assert first["why"]["features"] is not None
    assert first["final_score"] is not None
    assert first["author"]["handle"]
    # Response-level context.
    assert payload["viewer"]["handle"].lower() == handle.lower()
    assert set(payload["weight_vector"]) == {"like", "reply", "repost", "quote", "dwell"}
    assert payload["model_version"] is not None


async def test_neutral_preferences_reproduce_untuned_order(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)

    untuned = (await client.post("/api/feed", json={"handle": handle})).json()
    neutral = (
        await client.post(
            "/api/feed",
            json={
                "handle": handle,
                "preferences": {
                    "recency": 0.5,
                    "friends_global": 0.5,
                    "niche_viral": 0.5,
                },
            },
        )
    ).json()

    assert _post_ids(untuned) == _post_ids(neutral)
    assert all(item["why"]["preference_multiplier"] == 1.0 for item in untuned["items"])


async def test_niche_viral_slider_changes_the_multiplier(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)

    viral = (
        await client.post(
            "/api/feed",
            json={"handle": handle, "preferences": {"niche_viral": 1.0}},
        )
    ).json()

    # Boosting velocity must lift the preference multiplier above the neutral 1.0 for at
    # least one high-velocity post — proof the §4 slider reaches the score.
    multipliers = [item["why"]["preference_multiplier"] for item in viral["items"]]
    assert any(m is not None and m > 1.0 for m in multipliers)


async def test_trace_reports_stage_counts(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)

    payload = (await client.post("/api/feed", json={"handle": handle})).json()

    trace = payload["trace"]
    assert trace["candidates_total"] >= trace["merged"] >= trace["selected"]
    assert trace["selected"] == len(payload["items"])
    source_names = {stage["name"] for stage in trace["per_source"]}
    assert source_names <= {"in_network", "out_of_network", "trending"}
    assert trace["filters"], "the default pipeline runs self + block/mute filters"
    assert trace["source_mix"]


async def test_topics_endpoint_returns_seeded_topics(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    topics = (await client.get("/api/topics")).json()

    assert topics, "centroids were generated, so topics must be non-empty"
    canonical = {
        "art", "crypto", "culture", "finance", "food", "life", "memes",
        "news", "policy", "politics", "programming", "startups", "tech",
    }
    assert set(topics) <= canonical


async def test_pipeline_endpoint_describes_stages(client: httpx.AsyncClient) -> None:
    stages = (await client.get("/api/pipeline")).json()

    keys = {stage["key"] for stage in stages}
    assert {"sources", "hydrate", "filter", "score", "select", "log"} <= keys
    assert all(stage["title"] and stage["description"] for stage in stages)


async def test_users_endpoint_lists_selectable_viewers(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)

    users = (await client.get("/api/users")).json()

    handles = {user["handle"].lower() for user in users}
    assert handle.lower() in handles
    assert all(isinstance(user["is_persona"], bool) for user in users)


async def test_profile_endpoint_returns_author_peek(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _persona_handle(session)

    profile = (await client.get(f"/api/profile/{handle}")).json()

    assert profile["user"]["handle"].lower() == handle.lower()
    assert profile["post_count"] > 0
    assert profile["recent_posts"], "a persona should have recent posts"
    assert isinstance(profile["follower_count"], int)


async def test_impressions_roundtrip_through_the_db(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    handle = await _reader_handle(session)
    feed = (await client.post("/api/feed", json={"handle": handle})).json()

    rows = (await client.get(f"/api/impressions/{feed['request_id']}")).json()

    assert len(rows) == len(feed["items"])
    assert [row["rank"] for row in rows] == list(range(len(rows)))
    assert all(row["action_scores"] and row["sources"] for row in rows)


async def test_trends_endpoint_shape(
    session: AsyncSession, client: httpx.AsyncClient, seeded: None
) -> None:
    response = await client.get("/api/trends")

    assert response.status_code == 200
    trends = response.json()
    assert isinstance(trends, list)
    for item in trends:
        assert item["velocity"] >= 0
        assert item["author"]["handle"]


async def test_unknown_viewer_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/feed", json={"handle": "no_such_handle_xyz"})

    assert response.status_code == 404


async def test_out_of_range_preference_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/feed", json={"handle": "whoever", "preferences": {"recency": 1.5}}
    )

    assert response.status_code == 422


# --- Live-trigger path (plan.md §8) ----------------------------------------------------


async def test_create_post_publishes_and_triggers_bounded_reactions(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    handle = await _reader_handle(session)

    response = await client.post(
        "/api/posts", json={"handle": handle, "content": "a live post from the composer"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["author"]["handle"] == handle
    assert body["post"]["content"] == "a live post from the composer"
    assert 0 < len(body["reactions"]) <= settings.live_max_reactions_per_action
    for reaction in body["reactions"]:
        assert reaction["persona_handle"]
        assert reaction["content"]
    assert body["tokens_used"] > 0
    assert body["model_version"] == "fake-llm"
    assert body["budget"]["reactions_used"] == len(body["reactions"])


async def test_persona_replies_become_rankable_candidates(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    """Inline embedding is what makes live content reachable by the pipeline at all.

    The contract is candidacy, not placement: a fresh reply from an account you don't follow,
    on a topic you don't track, with no engagement yet, legitimately ranks mid-pack. Asserting
    a top-N slot here would be asserting an emergent scoring outcome, not a guarantee.
    """
    handle = await _reader_handle(session)
    created = await client.post(
        "/api/posts", json={"handle": handle, "content": "a live post from the composer"}
    )
    body = created.json()
    reaction_ids = {r["post_id"] for r in body["reactions"]}
    assert reaction_ids

    feed = await client.post("/api/feed", json={"handle": handle, "limit": 200})
    ranked = set(_post_ids(feed.json()))

    # Every reply is a candidate. The author's own post is self-filtered, so it is not.
    assert reaction_ids <= ranked
    assert body["post"]["post_id"] not in ranked


async def test_a_live_replys_features_are_fully_populated(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    """A reply with no embedding would silently score embedding_similarity = 0."""
    handle = await _reader_handle(session)
    created = await client.post(
        "/api/posts", json={"handle": handle, "content": "a live post from the composer"}
    )
    reaction_ids = {r["post_id"] for r in created.json()["reactions"]}

    feed = await client.post("/api/feed", json={"handle": handle, "limit": 200})
    replies = [
        item for item in feed.json()["items"] if item["post_id"] in reaction_ids
    ]

    assert replies
    for reply in replies:
        features = reply["why"]["features"]
        assert features["recency"] > 0.9  # freshest content in the world
        assert features["embedding_similarity"] != 0.0  # embedded inline, so it's real


async def test_create_post_can_skip_reactions(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    handle = await _reader_handle(session)

    response = await client.post(
        "/api/posts",
        json={"handle": handle, "content": "quiet post", "trigger_reactions": False},
    )

    body = response.json()
    assert body["reactions"] == []
    assert body["tokens_used"] == 0
    assert body["capped"] is False


async def test_create_reply_links_into_the_conversation(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    handle = await _reader_handle(session)
    root = await client.post(
        "/api/posts",
        json={"handle": handle, "content": "the root post", "trigger_reactions": False},
    )
    root_id = root.json()["post"]["post_id"]

    response = await client.post(
        "/api/posts",
        json={
            "handle": handle,
            "content": "my own follow-up",
            "in_reply_to_id": root_id,
            "trigger_reactions": False,
        },
    )

    assert response.status_code == 201
    post = await session.get(Post, uuid.UUID(response.json()["post"]["post_id"]))
    assert post is not None
    assert str(post.in_reply_to_id) == root_id
    assert str(post.conversation_id) == root_id


async def test_budget_endpoint_reports_todays_caps(
    client: httpx.AsyncClient, seeded: None
) -> None:
    response = await client.get("/api/budget")

    assert response.status_code == 200
    body = response.json()
    assert body["tokens_cap"] == settings.live_daily_token_cap
    assert body["reactions_cap"] == settings.live_daily_reaction_cap
    assert body["tokens_remaining"] == body["tokens_cap"] - body["tokens_used"]
    assert body["exhausted"] is False


async def test_budget_endpoint_reflects_a_live_post(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    handle = await _reader_handle(session)
    created = await client.post(
        "/api/posts", json={"handle": handle, "content": "a live post from the composer"}
    )

    budget = (await client.get("/api/budget")).json()

    assert budget["reactions_used"] == len(created.json()["reactions"])
    assert budget["tokens_used"] == created.json()["tokens_used"]


async def test_create_post_for_unknown_author_returns_404(
    client: httpx.AsyncClient, seeded: None
) -> None:
    response = await client.post(
        "/api/posts", json={"handle": "no_such_handle_xyz", "content": "hello there"}
    )

    assert response.status_code == 404


async def test_reply_to_a_missing_post_returns_404(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None
) -> None:
    handle = await _reader_handle(session)

    response = await client.post(
        "/api/posts",
        json={
            "handle": handle,
            "content": "replying into the void",
            "in_reply_to_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize("content", ["", "   ", "x" * 281])
async def test_invalid_content_is_rejected(
    client: httpx.AsyncClient, session: AsyncSession, seeded: None, content: str
) -> None:
    """Humans get the same 280-char bound the personas do (profiles.MAX_POST_CHARS)."""
    handle = await _reader_handle(session)

    response = await client.post(
        "/api/posts", json={"handle": handle, "content": content}
    )

    assert response.status_code == 422
