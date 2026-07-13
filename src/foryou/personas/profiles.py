"""Archetype -> structured persona profile + prompt assembly.

Behavior bounds live here, in code — never in the ``persona_config`` blob or the
prompt text (plan.md §6: "guardrails outside the prompt"). A profile shapes *how* a
persona writes (voice, style) and caps *how long* a post may be; the generator, not
the model, decides *which* topic and *how many* posts.
"""

from __future__ import annotations

from dataclasses import dataclass

from foryou.db.enums import Archetype
from foryou.db.models import User
from foryou.seed import ARCHETYPE_TOPICS

MAX_POST_CHARS = 280


@dataclass(frozen=True)
class PersonaProfile:
    """Code-side, authoritative persona shape for one archetype."""

    archetype: Archetype
    topics: list[str]
    voice: str
    style: str
    max_post_chars: int = MAX_POST_CHARS


# Voice + style guidance per archetype. Topics are reused from the seeder so the two
# content paths tag posts with the same topic vocabulary.
_VOICE_STYLE: dict[Archetype, tuple[str, str]] = {
    Archetype.FOUNDER: (
        "a driven startup founder who has shipped and failed and shipped again",
        "punchy, contrarian, lessons-learned",
    ),
    Archetype.JOURNALIST: (
        "a careful reporter who values primary sources over hot takes",
        "measured, precise, skeptical",
    ),
    Archetype.MEME: (
        "an extremely online poster who speaks fluent internet",
        "playful, absurd, self-aware",
    ),
    Archetype.TRADER: (
        "a markets person who thinks in risk and probabilities",
        "terse, numerate, unsentimental",
    ),
    Archetype.POLITICIAN: (
        "a coalition-builder focused on what policy actually does to people",
        "earnest, plainspoken, pragmatic",
    ),
    Archetype.ENGINEER: (
        "a pragmatic engineer who has maintained systems in production",
        "dry, exact, allergic to hype",
    ),
    Archetype.ARTIST: (
        "a working artist who cares about craft and constraint",
        "vivid, reflective, image-forward",
    ),
    Archetype.OTHER: (
        "a thoughtful everyday person sharing what they notice",
        "warm, grounded, conversational",
    ),
}

PROFILES: dict[Archetype, PersonaProfile] = {
    archetype: PersonaProfile(
        archetype=archetype,
        topics=ARCHETYPE_TOPICS[archetype],
        voice=voice,
        style=style,
    )
    for archetype, (voice, style) in _VOICE_STYLE.items()
}


def resolve_profile(user: User) -> PersonaProfile:
    """Return the profile for a persona; unknown/absent archetype -> OTHER."""
    if user.archetype is not None and user.archetype in PROFILES:
        return PROFILES[user.archetype]
    return PROFILES[Archetype.OTHER]


def build_prompt(profile: PersonaProfile, topic: str) -> tuple[str, str]:
    """Assemble the (system, user) prompt for one post on ``topic``.

    Soft constraints are stated in the prompt for quality, but every one of them is
    *also* enforced in code (length truncation, safety gate) so a non-compliant model
    can't widen the guardrails.
    """
    system = (
        f"You are {profile.voice}, posting on a social network. "
        f"Voice/style: {profile.style}. "
        f"Write ONE short, standalone post of at most {profile.max_post_chars} characters. "
        "No hashtags, no @mentions, no links. "
        "Never harass, threaten, demean, or incite violence against anyone. "
        "Output only the post text, nothing else."
    )
    user = f"Write a post about {topic}."
    return system, user
