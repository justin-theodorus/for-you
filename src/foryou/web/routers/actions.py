"""Write endpoints — the bounded live-trigger path (plan.md §8).

The only place a real user mutates the world. Publishing a post embeds it inline and may
trigger a few budget-capped persona reactions; ``foryou.live`` owns all of that logic, so
this router just resolves the actor, calls it, and commits.

Like the feed endpoint, the actor is asserted in the request body (``handle`` / ``user_id``)
— there is no per-user identity here, and the chosen actor is not authenticated. What *is*
gated is the write itself: ``require_operator`` (``foryou.web.auth``) checks a single shared
secret, because this endpoint spends real tokens on a public deployment. Unset the secret
and the gate is open, which is the local default. The gate lives purely at this boundary —
``foryou.live`` is unchanged, and its budget_ledger caps still bound an unlocked caller.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from foryou.db.models import Post
from foryou.live import publish_and_react
from foryou.web import serialize
from foryou.web.auth import require_operator
from foryou.web.deps import EncoderDep, LLMClientDep, SessionDep, resolve_viewer
from foryou.web.schemas import LivePostResponse, PostCreate

router = APIRouter(tags=["actions"])


@router.post(
    "/posts",
    response_model=LivePostResponse,
    status_code=201,
    dependencies=[Depends(require_operator)],
)
async def create_post(
    body: PostCreate,
    session: SessionDep,
    client: LLMClientDep,
    encoder: EncoderDep,
) -> LivePostResponse:
    """Publish a post (or reply) and optionally trigger bounded persona reactions."""
    author = await resolve_viewer(session, body.handle, body.user_id)

    parent: Post | None = None
    if body.in_reply_to_id is not None:
        parent = await session.get(Post, body.in_reply_to_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="post to reply to not found")

    post, summary = await publish_and_react(
        session,
        author,
        body.content,
        client=client,
        encoder=encoder,
        topics=body.topics,
        in_reply_to=parent,
        react=body.trigger_reactions,
    )
    # The service only flushes; the router owns the commit (as the feed endpoint does).
    await session.commit()

    return serialize.live_post_response(
        post, author, summary, model_version=client.model_version
    )
