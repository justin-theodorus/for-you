"""LLM persona agents: generate persona posts + heuristic engagements (plan.md §6)."""

from __future__ import annotations

from foryou.personas.content import generate_post_text
from foryou.personas.engagement import EngagementActor, build_engagements_for_posts
from foryou.personas.generator import (
    GenerationSummary,
    PersonaGenConfig,
    generate_personas,
)
from foryou.personas.llm import FakeLLM, LLMClient, LLMResult, OpenAIClient
from foryou.personas.profiles import PersonaProfile, build_prompt, resolve_profile
from foryou.personas.safety import SafetyVerdict, is_safe

__all__ = [
    "EngagementActor",
    "FakeLLM",
    "GenerationSummary",
    "LLMClient",
    "LLMResult",
    "OpenAIClient",
    "PersonaGenConfig",
    "PersonaProfile",
    "SafetyVerdict",
    "build_engagements_for_posts",
    "build_prompt",
    "generate_personas",
    "generate_post_text",
    "is_safe",
    "resolve_profile",
]
