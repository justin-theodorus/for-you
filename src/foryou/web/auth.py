"""The Operator write gate — a shared secret on the one endpoint that spends money.

Reader and Analyst are fully open: they only rank an existing corpus. ``POST /api/posts``
(plan.md §8) is the sole write, and the only path that calls an LLM per request, so it is
the only one worth gating on a public deployment.

**Be honest about what this is.** The secret is typed into a browser and sent as a header;
anyone we hand it to can read it back out. It is a speed bump that keeps a stranger from
idly burning the key. The real cost bound is ``budget_ledger``'s daily token/reaction caps
(``foryou.budget``), which hold whether or not the caller knows the password.

Unset ``OPERATOR_SECRET`` -> open, which keeps local dev and the existing test suite
unchanged; a deployment sets it.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Header, HTTPException

from foryou.config import settings

OPERATOR_HEADER = "X-Operator-Secret"

# Annotated form, like SessionDep/EncoderDep: keeps the Header() call out of an argument
# default (ruff B008).
OperatorSecretDep = Annotated[str | None, Header(alias=OPERATOR_HEADER)]


async def require_operator(x_operator_secret: OperatorSecretDep = None) -> None:
    """Reject a write unless the caller presents the configured operator secret.

    ``settings`` is read inside the body, not captured at import, so a test's
    ``monkeypatch.setattr`` against the module-level singleton takes effect.
    """
    expected = settings.operator_secret
    if not expected:
        return
    if x_operator_secret is None or not secrets.compare_digest(x_operator_secret, expected):
        raise HTTPException(status_code=401, detail="operator secret required")
