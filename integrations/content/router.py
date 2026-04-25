"""FastAPI router for Content Agent HTTP endpoints (consumed by n8n workflow)."""

import logging
import zoneinfo
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from app.config import settings
from integrations.content.calendar import CalendarManager
from integrations.content.generator import ContentGenerator
from integrations.content.habr_draft import HabrGenerator
from integrations.content.models import HabrDraft, ScheduledPost
from integrations.telegram.publisher import notify_publish_error, publish_post

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/content", tags=["content"])

# ---------------------------------------------------------------------------
# DB session dependency (reuses settings, consistent with main.py)
# ---------------------------------------------------------------------------

_engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
_async_session = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with _async_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PendingPostsResponse(BaseModel):
    posts: list[ScheduledPost]
    count: int


class GenerateRequest(BaseModel):
    product_description: str = ""


class PublishResult(BaseModel):
    post_id: int
    success: bool
    telegram_message_id: int | None


class HabrDraftRequest(BaseModel):
    product_id: int
    product_name: str
    product_description: str = ""
    brief: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=PendingPostsResponse)
async def get_pending_posts(
    target_date: date | None = None,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PendingPostsResponse:
    """
    Return all pending/generated posts for a given date (MSK).

    Used by n8n node 1: check editorial calendar.
    Query param: ?target_date=YYYY-MM-DD  (defaults to today MSK)
    """
    if target_date is None:
        target_date = datetime.now(tz=zoneinfo.ZoneInfo("Europe/Moscow")).date()

    cal = CalendarManager()
    posts = await cal.get_pending_posts(session, target_date)
    return PendingPostsResponse(posts=posts, count=len(posts))


@router.post("/{post_id}/generate", response_model=ScheduledPost)
async def generate_content(
    post_id: int,
    body: GenerateRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ScheduledPost:
    """
    Generate content for a pending ScheduledPost and persist the body.

    Used by n8n node 2: generate content if needed.
    """
    cal = CalendarManager()
    post = await cal.get_post_by_id(session, post_id)
    if not post:
        raise HTTPException(status_code=404, detail=f"ScheduledPost {post_id} not found")
    if post.status not in ("pending",):
        raise HTTPException(
            status_code=409, detail=f"Post {post_id} already has status '{post.status}'"
        )

    gen = ContentGenerator(settings)
    generated = await gen.generate_post(
        product_id=post.product_id,
        product_name=post.product_name,
        product_description=body.product_description,
        platform=post.platform,
        topic=post.topic,
    )
    await cal.update_post_body(session, post_id, generated.body)
    return await cal.get_post_by_id(session, post_id)  # type: ignore[return-value]


@router.post("/{post_id}/publish", response_model=PublishResult)
async def publish_content(
    post_id: int,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> PublishResult:
    """
    Publish a generated ScheduledPost to its target platform.

    Currently supports Telegram channel only; other platforms return 202 stub.
    Used by n8n node 3: publish via Telegram publisher.
    """
    cal = CalendarManager()
    post = await cal.get_post_by_id(session, post_id)
    if not post:
        raise HTTPException(status_code=404, detail=f"ScheduledPost {post_id} not found")
    if post.status != "generated":
        raise HTTPException(
            status_code=409,
            detail=f"Post {post_id} must be in 'generated' status, got '{post.status}'",
        )

    if post.platform != "telegram":
        logger.info(
            "Post %d platform=%s: stub publish (not yet implemented)", post_id, post.platform
        )
        return PublishResult(post_id=post_id, success=True, telegram_message_id=None)

    bot = Bot(token=settings.telegram_bot_token)
    success, message_id = await publish_post(bot, settings.telegram_channel_id, post)

    published_at = datetime.now(tz=UTC)
    if success:
        await cal.mark_published(session, post_id, published_at, message_id)
    else:
        await cal.mark_failed(session, post_id)
        await notify_publish_error(bot, int(settings.telegram_admin_chat_id), post)

    return PublishResult(post_id=post_id, success=success, telegram_message_id=message_id)


@router.post("/{post_id}/metrics")
async def save_metrics(post_id: int) -> dict[str, str]:
    """
    Placeholder for saving post metrics (views, reactions).

    Used by n8n node 4: save metrics.
    Will be implemented in Sprint 3 (Analytics Agent).
    """
    logger.info("Metrics stub called for post %d", post_id)
    return {"status": "ok", "note": "metrics collection coming in Sprint 3"}


@router.post("/habr-draft", response_model=HabrDraft)
async def create_habr_draft(
    body: HabrDraftRequest,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> HabrDraft:
    """Generate and save a long-form Habr article draft."""
    gen = HabrGenerator(settings)
    draft = await gen.generate_habr_draft(
        product_id=body.product_id,
        product_name=body.product_name,
        product_description=body.product_description,
        brief=body.brief,
    )
    draft_id = await gen.save_draft(session, draft)
    return await gen.get_draft_by_id(session, draft_id)  # type: ignore[return-value]


@router.get("/habr-draft/{draft_id}/export")
async def export_habr_draft(
    draft_id: int,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    """Export a Habr draft as raw Markdown and mark it as exported."""
    gen = HabrGenerator(settings)
    markdown = await gen.export_draft(session, draft_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    return {"draft_id": str(draft_id), "markdown": markdown}
