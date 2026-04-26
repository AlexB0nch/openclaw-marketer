"""Telegram mention monitor using Telethon."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

if TYPE_CHECKING:
    from telethon import TelegramClient

logger = logging.getLogger(__name__)


class MentionMonitor:
    def __init__(
        self,
        telethon_client: TelegramClient,
        keywords: list[str],
        admin_chat_id: int,
    ) -> None:
        self._client = telethon_client
        self._keywords = [kw.strip() for kw in keywords if kw.strip()]
        self._admin_chat_id = admin_chat_id
        self._seen_message_ids: set[int] = set()

    async def start_monitoring(self, bot) -> None:
        """Register event handler and run Telethon until disconnected."""
        from telethon import events

        @self._client.on(events.NewMessage(incoming=True))
        async def handler(event) -> None:
            await self._handle_event(event, bot)

        if not self._client.is_connected():
            await self._client.connect()

        logger.info("MentionMonitor started, watching %d keywords", len(self._keywords))
        await self._client.run_until_disconnected()

    async def _handle_event(self, event, bot) -> None:
        msg_id: int = event.message.id
        if msg_id in self._seen_message_ids:
            return

        text: str = event.message.message or ""
        text_lower = text.lower()

        matched_keyword: str | None = None
        for kw in self._keywords:
            if kw.lower() in text_lower:
                matched_keyword = kw
                break

        if matched_keyword is None:
            return

        self._seen_message_ids.add(msg_id)

        try:
            chat = await event.get_chat()
            channel_username = getattr(chat, "username", None) or str(chat.id)
        except Exception:
            channel_username = "unknown"

        await self.on_mention(event, matched_keyword, text, channel_username, bot)

    async def on_mention(
        self,
        event,
        keyword: str,
        message_text: str,
        channel_username: str,
        bot,
    ) -> None:
        """Send Telegram alert to admin with action buttons."""
        msg_id: int = event.message.id
        preview = message_text[:200] + ("…" if len(message_text) > 200 else "")

        alert = f'🔔 Упоминание: "{keyword}"\n' f"📢 Канал: @{channel_username}\n" f"💬 {preview}"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "👀 Посмотреть",
                        url=f"https://t.me/{channel_username}/{msg_id}",
                    ),
                    InlineKeyboardButton(
                        "💬 Ответить",
                        callback_data=f"mention_reply:{channel_username}:{msg_id}",
                    ),
                    InlineKeyboardButton(
                        "🔕 Игнорировать",
                        callback_data=f"mention_ignore:{msg_id}",
                    ),
                ]
            ]
        )

        try:
            await bot.send_message(
                chat_id=self._admin_chat_id,
                text=alert,
                reply_markup=keyboard,
            )
            logger.info("Mention alert sent: keyword=%r channel=@%s", keyword, channel_username)
        except Exception as exc:
            logger.error("Failed to send mention alert: %s", exc)
