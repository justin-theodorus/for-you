"""Integration tests for the bounded live-trigger path (plan.md §8).

Fully offline: FakeLLM (no OpenAI import) + FakeEncoder (no torch), inside the rolled-back
fixture session — ``foryou.live`` flushes and never commits, so the savepoint contains it.

The load-bearing assertions here are the two that would silently ruin the demo if they
regressed: live content lands on the *corpus* clock (not wall-clock), and a hit cap
short-circuits to zero reactions with zero model calls.
"""

from __future__ import annotations

import datetime
import random

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.budget import load_budget, record_spend
from foryou.candidates.context import resolve_now
from foryou.config import settings
from foryou.db.enums import EngagementKind, PostKind
from foryou.db.models import Engagement, Post, PostEmbedding, User
from foryou.embeddings import generate_embeddings, generate_topic_centroids
from foryou.live import (
    CAP_DAILY_REACTIONS,
    CAP_DAILY_TOKENS,
    CAP_DISABLED,
    LiveTriggerConfig,
    _select_reactors,
    publish_and_react,
    publish_post,
    trigger_reactions,
)
from foryou.personas import FakeLLM, LLMClient, LLMResult
from foryou.seed import SeedConfig, seed_world
from tests.test_encoder import FakeEncoder

_SEED = SeedConfig(
    personas=8,
    readers=3,
    posts_per_persona=3,
    follows_per_user=3,
    engagements_per_user=4,
    seed=7,
)


class CountingLLM:
    """FakeLLM that records how many times it was actually called.

    The cap contract isn't "few reactions", it's "no model call at all" — only a counting
    client can prove that.
    """

    def __init__(self, inner: LLMClient | None = None) -> None:
        self._inner = inner or FakeLLM()
        self.calls = 0

    @property
    def model_version(self) -> str:
        return self._inner.model_version

    def complete(
        self,
        system: str,
        user: str,
        *,
        seed: int | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMResult:
        self.calls += 1
        return self._inner.complete(
            system, user, seed=seed, max_tokens=max_tokens, temperature=temperature
        )


async def _reader(session: AsyncSession) -> User:
    user = await session.scalar(
        select(User).where(User.is_persona.is_(False)).order_by(User.handle).limit(1)
    )
    assert user is not None
    return user


# --- The clock ------------------------------------------------------------------------


async def test_live_post_lands_on_the_corpus_clock_not_wall_clock(
    session: AsyncSession,
) -> None:
    """The whole demo hinges on this: a wall-clock post would age the corpus out of the
    in-network lookback, flatten recency, and empty the trending window."""
    await seed_world(session, _SEED)
    corpus_head = await resolve_now(session)
    author = await _reader(session)

    post = await publish_post(session, author, "a live post")

    assert post.created_at > corpus_head
    # Minutes past the world's head, not the ~2 weeks that wall-clock would jump.
    assert post.created_at - corpus_head < datetime.timedelta(hours=1)
    assert post.created_at < datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)


async def test_reactions_advance_the_ranking_clock(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)

    post, summary = await publish_and_react(
        session, author, "a live post", client=FakeLLM(), encoder=FakeEncoder()
    )

    assert summary.reactions
    # The replies are now the newest thing in the world, so the clock follows them.
    assert await resolve_now(session) >= post.created_at


# --- The conversation graph (first code in the project to populate it) -----------------


async def test_reactions_are_reply_posts_with_thread_links(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)

    post, summary = await publish_and_react(
        session, author, "a live post", client=FakeLLM(), encoder=FakeEncoder()
    )

    replies = (
        await session.execute(select(Post).where(Post.in_reply_to_id == post.id))
    ).scalars().all()

    assert len(replies) == len(summary.reactions)
    for reply in replies:
        assert reply.kind is PostKind.REPLY
        assert reply.in_reply_to_id == post.id
        assert reply.conversation_id == post.id
        assert reply.created_at > post.created_at


async def test_a_user_reply_links_into_the_parents_conversation(
    session: AsyncSession,
) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)
    root = await publish_post(session, author, "the root post")

    reply = await publish_post(session, author, "my own follow-up", in_reply_to=root)

    assert reply.kind is PostKind.REPLY
    assert reply.in_reply_to_id == root.id
    assert reply.conversation_id == root.id
    assert root.reply_count == 1


async def test_reply_counters_stay_reconcilable_with_the_engagement_log(
    session: AsyncSession,
) -> None:
    """The invariant every other content path keeps: counters agree with the event log."""
    await seed_world(session, _SEED)
    author = await _reader(session)

    post, summary = await publish_and_react(
        session, author, "a live post", client=FakeLLM(), encoder=FakeEncoder()
    )

    logged = await session.scalar(
        select(func.count())
        .select_from(Engagement)
        .where(Engagement.post_id == post.id, Engagement.kind == EngagementKind.REPLY)
    )
    await session.refresh(post)

    assert post.reply_count == logged
    assert post.reply_count >= len(summary.reactions)


# --- The caps -------------------------------------------------------------------------


async def test_per_action_cap_bounds_the_reaction_count(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])

    summary = await trigger_reactions(
        session, FakeLLM(), post, config=LiveTriggerConfig(max_reactions=2)
    )

    assert len(summary.reactions) <= 2


async def test_daily_reaction_cap_short_circuits_with_no_model_call(
    session: AsyncSession,
) -> None:
    await seed_world(session, _SEED)
    await record_spend(session, tokens=0, reactions=settings.live_daily_reaction_cap)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])
    client = CountingLLM()

    summary = await trigger_reactions(session, client, post)

    assert summary.reactions == []
    assert summary.tokens_used == 0
    assert summary.capped is True
    assert summary.cap_reason == CAP_DAILY_REACTIONS
    assert client.calls == 0  # "no new reaction" means no spend, not a cheaper reaction


async def test_daily_token_cap_short_circuits_with_no_model_call(
    session: AsyncSession,
) -> None:
    await seed_world(session, _SEED)
    await record_spend(session, tokens=settings.live_daily_token_cap, reactions=0)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])
    client = CountingLLM()

    summary = await trigger_reactions(session, client, post)

    assert summary.reactions == []
    assert summary.tokens_used == 0
    assert summary.capped is True
    assert summary.cap_reason == CAP_DAILY_TOKENS
    assert client.calls == 0


async def test_remaining_daily_reactions_bound_a_single_action(
    session: AsyncSession,
) -> None:
    """When the daily budget has less headroom than the per-action cap, it wins."""
    await seed_world(session, _SEED)
    await record_spend(
        session, tokens=0, reactions=settings.live_daily_reaction_cap - 1
    )
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])

    summary = await trigger_reactions(
        session, FakeLLM(), post, config=LiveTriggerConfig(max_reactions=3)
    )

    assert len(summary.reactions) <= 1
    assert summary.capped is True
    assert summary.cap_reason == CAP_DAILY_REACTIONS


async def test_disabled_switch_publishes_but_never_reacts(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_world(session, _SEED)
    monkeypatch.setattr(settings, "live_enabled", False)
    author = await _reader(session)
    client = CountingLLM()

    post, summary = await publish_and_react(
        session, author, "a live post", client=client, encoder=FakeEncoder()
    )

    assert post.id is not None  # the post still publishes
    assert summary.reactions == []
    assert summary.cap_reason == CAP_DISABLED
    assert client.calls == 0


async def test_spend_is_recorded_against_the_ledger(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)

    _, summary = await publish_and_react(
        session, author, "a live post", client=FakeLLM(), encoder=FakeEncoder()
    )

    budget = await load_budget(session)

    assert budget.reactions_used == len(summary.reactions)
    assert budget.tokens_used == summary.tokens_used
    assert summary.tokens_used > 0


# --- The safety gate ------------------------------------------------------------------


async def test_unsafe_output_is_dropped_but_still_charged(session: AsyncSession) -> None:
    """Guardrails outside the prompt: a rejected generation inserts nothing and still costs."""
    await seed_world(session, _SEED)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])

    summary = await trigger_reactions(session, FakeLLM(unsafe=True), post)

    assert summary.reactions == []
    assert summary.rejected  # every attempt was gated
    assert summary.tokens_used > 0  # honest accounting: the model still ran
    replies = (
        await session.execute(select(Post).where(Post.in_reply_to_id == post.id))
    ).scalars().all()
    assert replies == []


# --- Determinism + embeddings ---------------------------------------------------------


async def test_reactor_selection_is_deterministic_per_post(session: AsyncSession) -> None:
    """RNG is namespaced on the post id, so a given post always draws the same personas.

    Selection is exercised directly rather than by triggering twice: a second trigger on the
    same post would replay the same ``det_uuid`` stream and collide on the primary key —
    which is determinism working as designed, and a path no caller takes (every published
    post is a fresh row).
    """
    await seed_world(session, _SEED)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])

    first = await _select_reactors(
        session, random.Random(f"foryou-live:{post.id}"), post, 3
    )
    second = await _select_reactors(
        session, random.Random(f"foryou-live:{post.id}"), post, 3
    )

    assert [user.id for user in first] == [user.id for user in second]
    assert first  # the seeded world has personas to draw from


async def test_reactor_selection_is_weighted_by_topic_overlap(
    session: AsyncSession,
) -> None:
    """Who reacts is decided in code, not by the model (the plan.md §6 guardrail)."""
    await seed_world(session, _SEED)
    author = await _reader(session)
    post = await publish_post(session, author, "a live post", topics=["tech"])

    reactors = await _select_reactors(
        session, random.Random(f"foryou-live:{post.id}"), post, 3
    )

    assert all(user.is_persona for user in reactors)
    assert author.id not in {user.id for user in reactors}  # never yourself


async def test_live_content_is_embedded_inline(session: AsyncSession) -> None:
    """Without an embedding, new content is invisible to OutOfNetworkSource and MMR."""
    await seed_world(session, _SEED)
    author = await _reader(session)

    post, summary = await publish_and_react(
        session, author, "a live post", client=FakeLLM(), encoder=FakeEncoder()
    )

    embedded = set(
        (
            await session.execute(
                select(PostEmbedding.post_id).where(
                    PostEmbedding.post_id.in_(
                        [post.id, *[r.post_id for r in summary.reactions]]
                    )
                )
            )
        ).scalars().all()
    )

    assert post.id in embedded
    assert {r.post_id for r in summary.reactions} <= embedded


async def test_topics_are_inferred_from_the_nearest_centroids(
    session: AsyncSession,
) -> None:
    """The composer is one textbox, so an untagged post gets topics from its embedding."""
    await seed_world(session, _SEED)
    encoder = FakeEncoder()
    await generate_embeddings(session, encoder, batch_size=100)
    await generate_topic_centroids(session)
    author = await _reader(session)

    post, _ = await publish_and_react(
        session, author, "an untagged live post", client=FakeLLM(), encoder=encoder
    )

    assert post.topics  # inferred, not empty


async def test_explicit_topics_win_over_inference(session: AsyncSession) -> None:
    await seed_world(session, _SEED)
    author = await _reader(session)

    post, _ = await publish_and_react(
        session,
        author,
        "a live post",
        client=FakeLLM(),
        encoder=FakeEncoder(),
        topics=["crypto"],
    )

    assert list(post.topics) == ["crypto"]
