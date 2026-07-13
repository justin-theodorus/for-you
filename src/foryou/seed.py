"""Deterministic, no-LLM synthetic world generator.

Populates users, posts (with topics), the follow graph, and the engagement event
log so the ranking pipeline has a corpus to run against. Content is templated (not
LLM-generated) and everything is a pure function of ``config.seed`` — the same seed
yields an identical world (including row ids), so corpora are snapshot-able for
ranking experiments.

LLM-authored persona *content* now lives in ``foryou.personas`` (plan.md §6), which
reuses this module's determinism spine (``det_uuid``, ``BASE_TIME``) and the shared
``build_engagements`` heuristic so the two content paths can't drift. Reply/quote
*posts* and thread reconstruction are still deferred (plan.md §7).
"""

from __future__ import annotations

import datetime
import random
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from foryou.db.enums import Archetype, EngagementKind, PostKind
from foryou.db.models import Engagement, Follow, Post, User

# Fixed anchor so timestamps — and thus the whole corpus — are reproducible
# regardless of when the seed runs.
BASE_TIME = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
POST_WINDOW_SECONDS = int(datetime.timedelta(days=14).total_seconds())

ARCHETYPE_TOPICS: dict[Archetype, list[str]] = {
    Archetype.FOUNDER: ["startups", "tech"],
    Archetype.JOURNALIST: ["news", "politics"],
    Archetype.MEME: ["memes", "culture"],
    Archetype.TRADER: ["finance", "crypto"],
    Archetype.POLITICIAN: ["politics", "policy"],
    Archetype.ENGINEER: ["tech", "programming"],
    Archetype.ARTIST: ["art", "culture"],
    Archetype.OTHER: ["life", "food"],
}

_TOPIC_CONTENT: dict[str, list[str]] = {
    "startups": [
        "Shipping the MVP beats polishing a roadmap nobody has validated.",
        "Fundraising is a means, not a milestone — default alive first.",
        "Your first ten customers should feel hand-built, not scaled.",
        "Hiring slowly is a feature when runway is the real constraint.",
    ],
    "tech": [
        "The best abstraction is the one you never had to write.",
        "Latency is a product feature users feel before they can name it.",
        "Every cache is a bug waiting for its invalidation story.",
        "Local-first tools are quietly winning the developer experience race.",
    ],
    "news": [
        "Slow-news discipline beats being first and wrong every single time.",
        "The correction deserves the same front page as the mistake.",
        "Primary sources over hot takes — link the document, not the thread.",
        "Follow the incentives and the confusing story usually resolves.",
    ],
    "politics": [
        "Turnout, not persuasion, decides most of the races people obsess over.",
        "Policy is what survives contact with a budget committee.",
        "Coalitions are boring to build and decisive to have.",
        "Local elections quietly shape more of daily life than national ones.",
    ],
    "memes": [
        "Nobody: absolutely nobody: me at 2am refactoring a working script.",
        "The format is old but the pain is eternal and relatable.",
        "It's funny because it's a bug report in disguise.",
        "Posting this into the void and the void is posting back.",
    ],
    "culture": [
        "The remix is the original now; provenance is a vibe, not a rule.",
        "Subcultures scale until the algorithm flattens them into a trend.",
        "Taste is just pattern recognition you can't fully explain.",
        "Every canon is a fandom that won the argument early.",
    ],
    "finance": [
        "Risk you can't explain in a sentence is risk you don't understand.",
        "Compounding is boring right up until it isn't.",
        "The market can stay irrational longer than your thesis can stay funded.",
        "Diversification is the only free lunch, and people still skip it.",
    ],
    "crypto": [
        "Decentralization is a spectrum, not a marketing checkbox.",
        "Most tokens are a governance problem cosplaying as an asset.",
        "Self-custody is freedom and a loaded footgun in the same breath.",
        "The infrastructure outlives the hype cycle that funded it.",
    ],
    "policy": [
        "Good policy is legible: you can predict what it will do to you.",
        "Implementation is where ninety percent of the outcome actually lives.",
        "Sunset clauses age better than permanent emergency powers.",
        "Measure the second-order effects or they will measure you.",
    ],
    "programming": [
        "Naming is cache invalidation for humans.",
        "A test you don't trust is worse than no test at all.",
        "Delete code like it owes you money; the diff is the feature.",
        "Readability is a performance optimization for the next maintainer.",
    ],
    "art": [
        "Constraints are the medium; the blank canvas is the enemy.",
        "Finish ugly, then let the edit find the piece.",
        "Reference is not theft; unexamined imitation is.",
        "The work teaches you what it wants to be if you keep showing up.",
    ],
    "life": [
        "Small systems beat big resolutions every ordinary Tuesday.",
        "Rest is part of the work, not a reward for finishing it.",
        "The calendar is honest in a way the to-do list never is.",
        "Attention is the whole budget; spend it on purpose.",
    ],
    "food": [
        "Salt earlier than you think and taste more than you expect.",
        "A sharp knife is the cheapest upgrade in the whole kitchen.",
        "The best recipe is the one you'll actually cook on a weeknight.",
        "Cold ferment turns patience into flavor you can't fake.",
    ],
}

_ALL_TOPICS: list[str] = sorted(_TOPIC_CONTENT)

# Engagement kind distribution (weights). click/dwell/report don't map to a post
# counter; like/reply/repost/quote do.
ENGAGEMENT_KINDS: list[EngagementKind] = [
    EngagementKind.LIKE,
    EngagementKind.CLICK,
    EngagementKind.DWELL,
    EngagementKind.REPOST,
    EngagementKind.REPLY,
    EngagementKind.QUOTE,
    EngagementKind.REPORT,
]
ENGAGEMENT_WEIGHTS: list[float] = [50.0, 20.0, 15.0, 6.0, 5.0, 3.0, 1.0]

COUNTER_ATTR: dict[EngagementKind, str] = {
    EngagementKind.LIKE: "like_count",
    EngagementKind.REPLY: "reply_count",
    EngagementKind.REPOST: "repost_count",
    EngagementKind.QUOTE: "quote_count",
}


@dataclass
class SeedConfig:
    """Knobs for the synthetic world. Defaults produce a small, fast corpus."""

    personas: int = 16
    readers: int = 12
    posts_per_persona: int = 8
    follows_per_user: int = 6
    engagements_per_user: int = 15
    seed: int = 42
    wipe: bool = False


@dataclass
class SeedSummary:
    """Row counts written by a seed run."""

    users: int
    posts: int
    follows: int
    engagements: int


@dataclass
class _Participant:
    user: User
    topics: list[str]


def det_uuid(rng: random.Random) -> uuid.UUID:
    """Deterministic UUIDv4 so the whole corpus (ids included) is reproducible."""
    return uuid.UUID(bytes=rng.randbytes(16), version=4)


def overlap(a: list[str], b: list[str]) -> int:
    return len(set(a) & set(b))


def weighted_sample[T](
    rng: random.Random, items: list[T], weights: list[float], k: int
) -> list[T]:
    """Pick up to ``k`` distinct items with probability proportional to weight."""
    pool = list(zip(items, weights, strict=True))
    chosen: list[T] = []
    for _ in range(min(k, len(pool))):
        total = sum(weight for _, weight in pool)
        target = rng.uniform(0, total)
        running = 0.0
        for index, (item, weight) in enumerate(pool):
            running += weight
            if running >= target:
                chosen.append(item)
                pool.pop(index)
                break
        else:  # floating-point slack: take the last remaining item
            item, _ = pool.pop()
            chosen.append(item)
    return chosen


def build_engagements(
    rng: random.Random,
    actors: Sequence[tuple[uuid.UUID, list[str]]],
    posts: list[Post],
    per_user: int,
    *,
    base_time: datetime.datetime,
) -> list[Engagement]:
    """Topic-overlap-weighted engagement events; bumps post counters in place.

    Shared by the seeder and the persona generator (plan.md §6) so the heuristic —
    weighting, kind distribution, and counter/log consistency — can't drift between
    them. Each ``actor`` is an ``(user_id, topics)`` pair; every actor engages up to
    ``per_user`` posts it did not author. Timestamps are clamped to ``base_time``.
    """
    engagements: list[Engagement] = []
    for actor_id, topics in actors:
        candidates = [p for p in posts if p.author_id != actor_id]
        weights = [1.0 + overlap(topics, post.topics) * 4.0 for post in candidates]
        for post in weighted_sample(rng, candidates, weights, per_user):
            kind = rng.choices(ENGAGEMENT_KINDS, ENGAGEMENT_WEIGHTS, k=1)[0]
            created_at = min(
                base_time,
                post.created_at + datetime.timedelta(minutes=rng.randint(1, 240)),
            )
            value = float(rng.randint(500, 60_000)) if kind is EngagementKind.DWELL else None
            engagements.append(
                Engagement(
                    id=det_uuid(rng),
                    user_id=actor_id,
                    post_id=post.id,
                    kind=kind,
                    value=value,
                    created_at=created_at,
                )
            )
            attr = COUNTER_ATTR.get(kind)
            if attr is not None:
                # Python-side default=0 only applies at INSERT, so the attribute
                # is still None on the pending object — coalesce before bumping.
                setattr(post, attr, (getattr(post, attr) or 0) + 1)
    return engagements


def _build_participants(config: SeedConfig, rng: random.Random) -> list[_Participant]:
    archetypes = list(Archetype)
    participants: list[_Participant] = []
    for i in range(config.personas):
        archetype = archetypes[i % len(archetypes)]
        topics = ARCHETYPE_TOPICS[archetype]
        user = User(
            id=det_uuid(rng),
            handle=f"{archetype.value}_{i}",
            display_name=f"{archetype.value.title()} {i}",
            is_persona=True,
            archetype=archetype,
            persona_config={"topics": topics},
        )
        participants.append(_Participant(user, topics))
    for j in range(config.readers):
        topics = rng.sample(_ALL_TOPICS, k=rng.randint(2, 3))
        user = User(
            id=det_uuid(rng),
            handle=f"reader_{j}",
            display_name=f"Reader {j}",
            is_persona=False,
            # Persist reader interests so build_context can derive user_topics —
            # otherwise topic_match is 0 for every reader (the feed's audience).
            persona_config={"topics": topics},
        )
        participants.append(_Participant(user, topics))
    return participants


def _build_posts(
    config: SeedConfig, rng: random.Random, personas: list[_Participant]
) -> list[Post]:
    posts: list[Post] = []
    for participant in personas:
        for _ in range(config.posts_per_persona):
            topic = rng.choice(participant.topics)
            created_at = BASE_TIME - datetime.timedelta(
                seconds=rng.randint(0, POST_WINDOW_SECONDS)
            )
            posts.append(
                Post(
                    id=det_uuid(rng),
                    author_id=participant.user.id,
                    content=rng.choice(_TOPIC_CONTENT[topic]),
                    kind=PostKind.POST,
                    topics=[topic],
                    created_at=created_at,
                )
            )
    return posts


def _build_follows(
    config: SeedConfig, rng: random.Random, participants: list[_Participant]
) -> list[Follow]:
    follows: list[Follow] = []
    for participant in participants:
        others = [p for p in participants if p.user.id != participant.user.id]
        weights = [1.0 + overlap(participant.topics, p.topics) * 3.0 for p in others]
        for followee in weighted_sample(rng, others, weights, config.follows_per_user):
            follows.append(
                Follow(follower_id=participant.user.id, followee_id=followee.user.id)
            )
    return follows


def _build_engagements(
    config: SeedConfig,
    rng: random.Random,
    participants: list[_Participant],
    posts: list[Post],
) -> list[Engagement]:
    actors = [(p.user.id, p.topics) for p in participants]
    return build_engagements(
        rng, actors, posts, config.engagements_per_user, base_time=BASE_TIME
    )


async def seed_world(session: AsyncSession, config: SeedConfig | None = None) -> SeedSummary:
    """Generate and persist a reproducible synthetic world; return the row counts.

    The caller commits. With ``config.wipe`` the existing world is deleted first
    (``DELETE FROM users`` cascades to posts, follows, engagements, embeddings).
    """
    config = config or SeedConfig()
    rng = random.Random(config.seed)

    if config.wipe:
        await session.execute(delete(User))
        # Drop any prior identities so deterministic ids don't collide on re-seed.
        session.expunge_all()

    participants = _build_participants(config, rng)
    personas = [p for p in participants if p.user.is_persona]
    posts = _build_posts(config, rng, personas)
    follows = _build_follows(config, rng, participants)
    engagements = _build_engagements(config, rng, participants, posts)

    # Flush per dependency level: no ORM relationship() is defined, so the unit of
    # work won't order these mappers by FK on its own. Referenced rows must already
    # exist when the dependent inserts run.
    session.add_all([p.user for p in participants])
    await session.flush()
    session.add_all(posts)
    await session.flush()
    session.add_all(follows)
    session.add_all(engagements)
    await session.flush()

    return SeedSummary(
        users=len(participants),
        posts=len(posts),
        follows=len(follows),
        engagements=len(engagements),
    )
