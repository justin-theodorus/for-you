"""Model re-exports so ``Base.metadata`` is fully populated on import.

Importing this package (or ``foryou.db.models``) registers every table with the
shared metadata, which Alembic's ``env.py`` relies on for autogenerate.
"""

from __future__ import annotations

from foryou.db.models.budget import BudgetLedger
from foryou.db.models.embedding import PostEmbedding, TopicCentroid, UserEmbedding
from foryou.db.models.engagement import Engagement
from foryou.db.models.follow import Follow
from foryou.db.models.impression import FeedImpression
from foryou.db.models.post import Post
from foryou.db.models.relationship import UserRelationship
from foryou.db.models.user import User
from foryou.db.models.velocity import PostVelocity

__all__ = [
    "BudgetLedger",
    "Engagement",
    "FeedImpression",
    "Follow",
    "Post",
    "PostEmbedding",
    "PostVelocity",
    "TopicCentroid",
    "User",
    "UserEmbedding",
    "UserRelationship",
]
