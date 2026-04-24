"""Telegram message publisher for async sending."""

import logging

from telegram import Bot

logger = logging.getLogger(__name__)


async def send_formatted_message(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str = "Markdown",
    retry_count: int = 3,
) -> bool:
    """
    Send formatted message with retry logic.

    Args:
        bot: Telegram bot instance
        chat_id: Target chat ID
        text: Message text
        parse_mode: HTML or Markdown
        retry_count: Number of retry attempts

    Returns:
        True if successful, False otherwise
    """
    for attempt in range(retry_count):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{retry_count} failed: {e}")
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
