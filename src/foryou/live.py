"""Bounded live-trigger path: a real user acts, a few personas react (plan.md §8).

The only path in the system where an LLM call happens on the request path — so the only one
that needs a *hard* stop. Cost is bounded three times over:

1. ``settings.live_enabled`` — a master switch. Off means the post still publishes and no
   reaction is ever generated.
2. A fixed per-action cap (``live_max_reactions_per_action``).
3. Global daily token/reaction counters in ``budget_ledger``, read **before** any model is
   called and re-checked before every reaction. Once a cap is hit the trigger short-circuits
   to "no new reaction" and reports which cap bound. That is the plan.md §8 contract.

Two clocks, deliberately different:

- **World content** is timestamped on the *corpus* clock — ``resolve_now()`` (the world's
  newest post) plus a beat — never wall-clock. The ranking clock is ``max(posts.created_at)``
  and the seeded world is anchored at ``BASE_TIME``, so a wall-clock post would yank
  ``ctx.now`` weeks forward: the corpus would fall outside the in-network lookback, recency
  would collapse to ~0 for every existing post, and the trending window would empty. Laying
  live content just past the world's head advances the clock by minutes instead — the same
  forward-timeline trick :mod:`foryou.simulate` uses (plan.md §7), and it needs zero
  pipeline changes.
- **The budget ledger** keys on the real UTC date (see :mod:`foryou.budget`): it caps real
  money, so it must reset on real calendar days.

Determinism follows the house pattern: the run RNG is namespaced
``random.Random(f"foryou-live:{post_id}")`` (Python hashes str via SHA-512, process-stable),
so a given post always draws the same reactors, and its ``det_uuid`` stream can never collide
with the seeder's ``Random(int)`` ids, ``foryou-personas:``, or ``foryou-simulate:``. Only the
reply *text* is model-nondeterministic — the same split the seeder and persona paths use.

Guardrails stay in code, never the prompt (plan.md §6): who reacts, how many, and on what
topic are decided here; every generated reply is truncated and run through the rule-based
:func:`~foryou.personas.safety.is_safe` gate before it can be inserted.

Flushes but never commits — the caller (the router or the CLI) owns the transaction.
"""

from __future__ import annotations

import asyncio
import datetime
import random
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.budget import DailyBudget, load_budget, record_spend
from foryou.candidates.context import resolve_now
from foryou.candidates.hydrator import cosine_similarity
from foryou.config import settings
from foryou.db.enums import EngagementKind, PostKind
from foryou.db.models import Engagement, Post, PostEmbedding, TopicCentroid, User
from foryou.embeddings.encoder import Encoder
from foryou.embeddings.generator import upsert_embeddings
from foryou.personas.content import generate_reply_text
from foryou.personas.engagement import EngagementActor, build_engagements_for_posts
from foryou.personas.llm import LLMClient
from foryou.personas.profiles import resolve_profile
from foryou.seed import det_uuid, overlap, weighted_sample

# How far past the world's head a live post lands: far enough to order strictly after it,
# near enough that the corpus stays "recent" relative to the new clock.
LIVE_POST_GAP = datetime.timedelta(minutes=1)
# Persona reactions scatter within this many minutes after the post they react to.
REACTION_SPREAD_MINUTES = 30
# How many topic centroids a post is tagged with when the caller doesn't name one.
INFERRED_TOPICS = 2
# Used only to pick a reply prompt's subject when a post has no topic at all (no centroids).
FALLBACK_TOPIC = "life"

# Why no — or fewer — reactions were generated. Surfaced to the CLI and the Operator tab.
CAP_DISABLED = "disabled"
CAP_NOT_REQUESTED = "not_requested"
CAP_DAILY_TOKENS = "daily_token_cap"
CAP_DAILY_REACTIONS = "daily_reaction_cap"


@dataclass(frozen=True, slots=True)
class LiveTriggerConfig:
    """Knobs for one trigger. Caps default to the cost-bound settings."""

    max_reactions: int = field(
        default_factory=lambda: settings.live_max_reactions_per_action
    )
    max_tokens_per_reaction: int = field(
        default_factory=lambda: settings.live_max_tokens_per_reaction
    )
    temperature: float = field(default_factory=lambda: settings.live_temperature)
    max_regenerations: int = field(
        default_factory=lambda: settings.live_max_regenerations
    )
    engagements_per_reactor: int = 1


@dataclass(frozen=True, slots=True)
class Reaction:
    """One persona reaction — a generated reply post, for the audit panel."""

    persona_id: uuid.UUID
    persona_handle: str
    post_id: uuid.UUID
    content: str


@dataclass(frozen=True, slots=True)
class LiveTriggerSummary:
    """Cost-visible outcome of one trigger (mirrors ``GenerationSummary``)."""

    reactions: list[Reaction]
    rejected: list[str]  # safety-gate categories, one per dropped reply
    engagements: int  # free heuristic likes/reposts — no tokens, so never budget-capped
    tokens_used: int
    estimated_usd: float
    capped: bool
    cap_reason: str | None
    budget: DailyBudget


def _no_reactions(
    budget: DailyBudget, reason: str, *, capped: bool = True
) -> LiveTriggerSummary:
    """The "no new reaction" outcome — returned *before* any model call is made."""
    return LiveTriggerSummary(
        reactions=[],
        rejected=[],
        engagements=0,
        tokens_used=0,
        estimated_usd=0.0,
        capped=capped,
        cap_reason=reason,
        budget=budget,
    )


async def next_world_time(session: AsyncSession) -> datetime.datetime:
    """The corpus clock, one beat forward — where new live content lands.

    Emphatically not wall-clock; see the module docstring. ``resolve_now`` falls back to
    wall-clock only for an empty world, the one case where the two agree.
    """
    return await resolve_now(session) + LIVE_POST_GAP


async def _infer_topics(
    session: AsyncSession, embedding: tuple[float, ...] | None
) -> list[str]:
    """Tag a post with its nearest ``topic_centroids`` — so the composer stays one textbox.

    Returns ``[]`` when the post has no embedding or centroids are unpopulated (run
    ``make centroids``); reactor selection then degrades to unweighted sampling.
    """
    if embedding is None:
        return []
    centroids = (await session.execute(select(TopicCentroid))).scalars().all()
    if not centroids:
        return []
    ranked = sorted(
        centroids,
        key=lambda row: cosine_similarity(
            embedding, tuple(float(value) for value in row.embedding)
        ),
        reverse=True,
    )
    return [row.topic for row in ranked[:INFERRED_TOPICS]]


async def _embed(session: AsyncSession, encoder: Encoder, posts: list[Post]) -> None:
    """Embed new posts inside the caller's transaction — no commit (see §A3 in the plan).

    ``upsert_embeddings`` already runs the blocking encode off the event loop.
    """
    rows = [(post.id, post.content) for post in posts if post.content]
    await upsert_embeddings(session, encoder, rows)


async def publish_post(
    session: AsyncSession,
    author: User,
    content: str,
    *,
    topics: list[str] | None = None,
    in_reply_to: Post | None = None,
) -> Post:
    """Write a real user's post (or reply) onto the corpus clock. Flushes; no commit.

    Replies set ``kind`` / ``in_reply_to_id`` / ``conversation_id`` — the first code in the
    project to populate the conversation graph, whose columns and indexes have existed since
    the initial schema but were never written.
    """
    created_at = await next_world_time(session)
    post = Post(
        author_id=author.id,
        content=content,
        kind=PostKind.REPLY if in_reply_to is not None else PostKind.POST,
        in_reply_to_id=in_reply_to.id if in_reply_to is not None else None,
        # Thread root: the parent's conversation if it has one, else the parent itself.
        conversation_id=(
            (in_reply_to.conversation_id or in_reply_to.id)
            if in_reply_to is not None
            else None
        ),
        topics=list(topics or []),
        created_at=created_at,
    )
    session.add(post)
    if in_reply_to is not None:
        # The reply post AND its engagement row: the denormalized counter must stay
        # reconcilable with the event log, the invariant every other content path keeps.
        session.add(
            Engagement(
                user_id=author.id,
                post_id=in_reply_to.id,
                kind=EngagementKind.REPLY,
                created_at=created_at,
            )
        )
        in_reply_to.reply_count = (in_reply_to.reply_count or 0) + 1
    await session.flush()
    return post


async def _select_reactors(
    session: AsyncSession, rng: random.Random, post: Post, limit: int
) -> list[User]:
    """Pick which personas react — in code, never by the model (the plan.md §6 guardrail).

    Weighted by topic overlap with the post, reusing the seeder's own heuristic, so a tech
    post draws engineers and founders rather than a uniform sample.
    """
    if limit <= 0:
        return []
    personas = (
        await session.execute(
            select(User)
            .where(User.is_persona.is_(True), User.id != post.author_id)
            .order_by(User.id)
        )
    ).scalars().all()
    if not personas:
        return []
    topics = list(post.topics)
    weights = [
        1.0 + overlap(topics, list(persona.persona_config.get("topics", []))) * 4.0
        for persona in personas
    ]
    return weighted_sample(rng, list(personas), weights, limit)


async def trigger_reactions(
    session: AsyncSession,
    client: LLMClient,
    post: Post,
    *,
    config: LiveTriggerConfig | None = None,
) -> LiveTriggerSummary:
    """Generate up to N budget-capped persona replies to ``post``. Flushes; no commit."""
    config = config or LiveTriggerConfig()
    rng = random.Random(f"foryou-live:{post.id}")

    # Locked read: a check-then-generate sequence would otherwise let two concurrent
    # triggers both pass the cap check and overrun it.
    budget = await load_budget(session, for_update=True)
    if not settings.live_enabled:
        return _no_reactions(budget, CAP_DISABLED)
    if budget.reactions_remaining <= 0:
        return _no_reactions(budget, CAP_DAILY_REACTIONS)
    if budget.tokens_remaining < config.max_tokens_per_reaction:
        return _no_reactions(budget, CAP_DAILY_TOKENS)

    # The per-action cap and the daily reaction cap, whichever binds first.
    allowed = min(config.max_reactions, budget.reactions_remaining)
    capped = allowed < config.max_reactions
    cap_reason = CAP_DAILY_REACTIONS if capped else None

    reactors = await _select_reactors(session, rng, post, allowed)
    topic = next(iter(post.topics), FALLBACK_TOPIC)

    replies: list[Post] = []
    reactions: list[Reaction] = []
    rejected: list[str] = []
    seen: set[str] = set()
    tokens_used = 0

    for index, persona in enumerate(reactors):
        # Pre-flight the worst case before spending (the batch generator's pattern): never
        # start a generation that could push today's spend past the cap.
        if tokens_used + config.max_tokens_per_reaction > budget.tokens_remaining:
            capped = True
            cap_reason = CAP_DAILY_TOKENS
            break

        # The OpenAI SDK call is synchronous — off the event loop, we're inside a request.
        text, spent = await asyncio.to_thread(
            generate_reply_text,
            client,
            resolve_profile(persona),
            topic,
            post.content,
            seed=index,
            max_tokens=config.max_tokens_per_reaction,
            temperature=config.temperature,
            max_regenerations=config.max_regenerations,
            seen=seen,
        )
        # Charged even when the gate rejects the output: a dropped generation still cost money.
        tokens_used += spent
        if text is None:
            rejected.append("safety_gate")
            continue

        created_at = post.created_at + datetime.timedelta(
            minutes=rng.randint(1, REACTION_SPREAD_MINUTES)
        )
        reply = Post(
            id=det_uuid(rng),
            author_id=persona.id,
            content=text,
            kind=PostKind.REPLY,
            in_reply_to_id=post.id,
            conversation_id=post.conversation_id or post.id,
            topics=[topic],
            created_at=created_at,
        )
        replies.append(reply)
        reactions.append(
            Reaction(
                persona_id=persona.id,
                persona_handle=persona.handle,
                post_id=reply.id,
                content=text,
            )
        )
        session.add(
            Engagement(
                id=det_uuid(rng),
                user_id=persona.id,
                post_id=post.id,
                kind=EngagementKind.REPLY,
                created_at=created_at,
            )
        )
        post.reply_count = (post.reply_count or 0) + 1

    session.add_all(replies)
    await session.flush()

    # Free tier: the reactors also like/repost the post itself. Zero tokens, so it is not
    # budget-capped — and it is what lets live content actually reach TrendingSource.
    engagements = build_engagements_for_posts(
        rng,
        [
            EngagementActor(persona.id, list(persona.persona_config.get("topics", [])))
            for persona in reactors
        ],
        [post],
        config.engagements_per_reactor,
        base_time=post.created_at + datetime.timedelta(minutes=REACTION_SPREAD_MINUTES),
    )
    session.add_all(engagements)
    await session.flush()

    await record_spend(session, tokens=tokens_used, reactions=len(reactions))

    return LiveTriggerSummary(
        reactions=reactions,
        rejected=rejected,
        engagements=len(engagements),
        tokens_used=tokens_used,
        estimated_usd=tokens_used / 1_000_000 * settings.persona_usd_per_1m_tokens,
        capped=capped,
        cap_reason=cap_reason,
        budget=await load_budget(session),
    )


async def publish_and_react(
    session: AsyncSession,
    author: User,
    content: str,
    *,
    client: LLMClient,
    encoder: Encoder,
    topics: list[str] | None = None,
    in_reply_to: Post | None = None,
    react: bool = True,
    config: LiveTriggerConfig | None = None,
) -> tuple[Post, LiveTriggerSummary]:
    """The whole §8 flow: publish -> embed -> infer topics -> react -> embed. No commit.

    Embedding inline — rather than deferring to ``make embeddings`` the way §6/§7 do — is
    what makes live content a first-class pipeline citizen straight away: it surfaces via
    ``OutOfNetworkSource``, gets a real ``embedding_similarity``, and is MMR-penalized.
    """
    post = await publish_post(
        session, author, content, topics=topics, in_reply_to=in_reply_to
    )
    await _embed(session, encoder, [post])

    if not post.topics:
        vector = await session.scalar(
            select(PostEmbedding.embedding).where(PostEmbedding.post_id == post.id)
        )
        inferred = await _infer_topics(
            session,
            tuple(float(value) for value in vector) if vector is not None else None,
        )
        if inferred:
            post.topics = inferred
            await session.flush()

    if not react:
        return post, _no_reactions(
            await load_budget(session), CAP_NOT_REQUESTED, capped=False
        )

    summary = await trigger_reactions(session, client, post, config=config)
    replies = (
        await session.execute(select(Post).where(Post.in_reply_to_id == post.id))
    ).scalars().all()
    await _embed(session, encoder, list(replies))
    return post, summary
