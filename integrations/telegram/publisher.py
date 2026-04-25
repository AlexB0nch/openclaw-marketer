"""Telegram message publisher — Sprint 1 notifications + Sprint 2 content publishing."""

import asyncio
import logging
from datetime import UTC, datetime

from telegram import Bot
from telegram.error import TelegramError

from integrations.content.models import ScheduledPost

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sprint 1 — admin notification helpers
# ---------------------------------------------------------------------------


async def send_formatted_message(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str = "Markdown",
    retry_count: int = 3,
) -> bool:
    """Send a formatted message with simple retry logic (Sprint 1)."""
    for attempt in range(retry_count):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except Exception as e:
            logger.error("Attempt %d/%d failed: %s", attempt + 1, retry_count, e)
    return False


async def send_digest_message(bot: Bot, chat_id: int, digest_text: str) -> bool:
    """Send weekly digest message."""
    return await send_formatted_message(bot, chat_id, digest_text)


async def notify_plan_generated(bot: Bot, chat_id: int, plan_summary: str) -> bool:
    """Notify admin about generated plan."""
    text = f"📝 *Новый план контента сгенерирован*\n\n{plan_summary}"
    return await send_formatted_message(bot, chat_id, text)


async def notify_plan_approved(bot: Bot, chat_id: int, plan_id: int) -> bool:
    """Notify about plan approval."""
    text = f"✅ План #{plan_id} одобрен. Направляем Content агенту."
    return await send_formatted_message(bot, chat_id, text)


async def notify_plan_rejected(bot: Bot, chat_id: int, plan_id: int, reason: str) -> bool:
    """Notify about plan rejection."""
    text = f"❌ План #{plan_id} отклонен.\n_Причина:_ {reason}"
    return await send_formatted_message(bot, chat_id, text)


# ---------------------------------------------------------------------------
# Sprint 2 — content publishing
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds; doubled each retry


async def publish_post(
    bot: Bot,
    channel_id: str,
    post: ScheduledPost,
) -> tuple[bool, int | None]:
    """
    Publish a ScheduledPost to a Telegram channel.

    Retries up to _MAX_RETRIES times with exponential backoff on network /
    server-side errors (TelegramError).  4xx client errors are not retried.

    Returns:
        (success, telegram_message_id)  — message_id is None on failure.
    """
    delay = _BACKOFF_BASE
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            message = await bot.send_message(
                chat_id=channel_id,
                text=post.body,
                parse_mode="Markdown",
            )
            logger.info(
                "Published post %s (product=%d) to %s — msg_id=%d",
                post.id,
                post.product_id,
                channel_id,
                message.message_id,
            )
            return True, message.message_id
        except TelegramError as exc:
            # 4xx errors (bad token, chat not found, etc.) — do not retry
            if hasattr(exc, "message") and any(
                code in str(exc) for code in ("400", "401", "403", "404")
            ):
                logger.error("Non-retryable Telegram error for post %s: %s", post.id, exc)
                return False, None
            logger.warning(
                "Telegram error on attempt %d/%d for post %s: %s",
                attempt,
                _MAX_RETRIES,
                post.id,
                exc,
            )
        except Exception as exc:
            logger.warning(
                "Unexpected error on attempt %d/%d for post %s: %s",
                attempt,
                _MAX_RETRIES,
                post.id,
                exc,
            )

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(delay)
            delay *= 2

    logger.error("Failed to publish post %s after %d attempts", post.id, _MAX_RETRIES)
    return False, None


async def notify_publish_error(bot: Bot, admin_chat_id: int, post: ScheduledPost) -> None:
    """Alert admin when a post fails to publish after all retries."""
    text = (
        f"⚠️ *Ошибка публикации*\n"
        f"Пост #{post.id} для продукта `{post.product_name}`\n"
        f"Платформа: {post.platform}\n"
        f"Тема: {post.topic}\n"
        f"Запланирован: {post.scheduled_at.strftime('%Y-%m-%d %H:%M')} MSK\n\n"
        "Проверьте токен бота и доступ к каналу."
    )
    await send_formatted_message(bot, admin_chat_id, text)


def utc_now() -> datetime:
    """Return current UTC time (injectable for tests)."""
    return datetime.now(tz=UTC)
