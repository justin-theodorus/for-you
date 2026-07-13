"""Unit tests for archetype profiles and prompt assembly — no DB."""

from __future__ import annotations

import pytest

from foryou.db.enums import Archetype
from foryou.db.models import User
from foryou.personas.profiles import PROFILES, build_prompt, resolve_profile


@pytest.mark.parametrize("archetype", list(Archetype))
def test_every_archetype_resolves_to_its_own_profile(archetype: Archetype) -> None:
    user = User(handle="p", display_name="P", is_persona=True, archetype=archetype)

    profile = resolve_profile(user)

    assert profile.archetype is archetype
    assert profile.topics  # non-empty topic list
    assert profile.voice and profile.style


def test_missing_archetype_falls_back_to_other() -> None:
    user = User(handle="r", display_name="R", is_persona=False, archetype=None)

    assert resolve_profile(user).archetype is Archetype.OTHER


def test_all_eight_archetypes_have_a_profile() -> None:
    assert set(PROFILES) == set(Archetype)


def test_build_prompt_includes_voice_topic_and_length_bound() -> None:
    profile = PROFILES[Archetype.FOUNDER]

    system, user = build_prompt(profile, "startups")

    assert profile.style in system
    assert str(profile.max_post_chars) in system
    assert "startups" in user
