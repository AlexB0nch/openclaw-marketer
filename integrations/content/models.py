"""Pydantic models for Content Agent."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["telegram", "habr", "vc.ru", "linkedin"]
PostStatus = Literal["pending", "generated", "published", "failed"]
HabrStatus = Literal["draft", "ready", "exported"]


class Post(BaseModel):
    """Generated post content — not yet persisted to DB."""

    platform: Platform
    topic: str
    body: str
    product_id: int
    product_name: str


class ScheduledPost(BaseModel):
    """Persisted scheduled post with delivery metadata (mirrors scheduled_posts table)."""

    id: int | None = None
    content_plan_id: int | None = None
    product_id: int
    product_name: str
    platform: Platform
    topic: str
    body: str = ""
    scheduled_at: datetime
    status: PostStatus = "pending"
    published_at: datetime | None = None
    telegram_message_id: int | None = None
    created_at: datetime | None = None


class HabrDraft(BaseModel):
    """Long-form Habr article draft (mirrors habr_drafts table)."""

    id: int | None = None
    product_id: int
    product_name: str
    title: str
    brief: str
    body: str
    word_count: int = Field(default=0, ge=0)
    status: HabrStatus = "draft"
    created_at: datetime | None = None
