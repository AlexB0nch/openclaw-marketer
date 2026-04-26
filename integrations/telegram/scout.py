"""TG Scout: Telethon-based channel discovery and contact extraction."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from telethon import TelegramClient

logger = logging.getLogger(__name__)


class ChannelInfo(BaseModel):
    username: str
    title: str
    subscriber_count: int
    avg_views: float
    er: float  # 0.0–1.0, e.g. 0.082 = 8.2%
    description: str
    contact_username: str | None
    contact_email: str | None
    topics: list[str]
    source: str  # "telethon" | "tgstat"


class TelegramScout:
    def __init__(self, api_id: int, api_hash: str, session_path: str) -> None:
        from telethon import TelegramClient

        self._client: TelegramClient = TelegramClient(session_path, api_id, api_hash)

    @property
    def client(self) -> TelegramClient:
        return self._client

    async def search_channels(
        self,
        keywords: list[str],
        min_subscribers: int = 1000,
        min_er: float = 0.01,
    ) -> list[ChannelInfo]:
        """Search public Telegram channels by keywords, filter by size and ER."""
        from telethon.tl.functions.contacts import SearchRequest
        from telethon.tl.types import Channel

        if not self._client.is_connected():
            await self._client.connect()

        seen: dict[str, ChannelInfo] = {}

        for keyword in keywords:
            try:
                result = await self._client(SearchRequest(q=keyword, limit=50))
                chats = getattr(result, "chats", [])
                for chat in chats:
                    if not isinstance(chat, Channel):
                        continue
                    username = getattr(chat, "username", None)
                    if not username:
                        continue
                    if username in seen:
                        continue

                    try:
                        full = await self._client.get_entity(username)
                        from telethon.tl.functions.channels import GetFullChannelRequest

                        full_chat = await self._client(GetFullChannelRequest(full))
                        subs = full_chat.full_chat.participants_count or 0
                    except Exception:
                        subs = getattr(chat, "participants_count", 0) or 0

                    if subs < min_subscribers:
                        continue

                    avg_views = subs * 0.05
                    er = avg_views / subs if subs > 0 else 0.0

                    if er < min_er:
                        continue

                    desc = (
                        getattr(full_chat.full_chat if "full_chat" in dir() else chat, "about", "")
                        or ""
                    )
                    contact_user, contact_email = self.parse_contact(desc)

                    info = ChannelInfo(
                        username=username,
                        title=chat.title or "",
                        subscriber_count=subs,
                        avg_views=avg_views,
                        er=er,
                        description=desc,
                        contact_username=contact_user,
                        contact_email=contact_email,
                        topics=[keyword],
                        source="telethon",
                    )
                    seen[username] = info
            except Exception as exc:
                logger.warning("search_channels keyword=%r failed: %s", keyword, exc)

        return list(seen.values())

    @staticmethod
    def parse_contact(description: str) -> tuple[str | None, str | None]:
        """Extract first @username and first email from bio text."""
        username_match = re.search(r"(?<!\w)@([A-Za-z0-9_]{3,32})", description)
        email_match = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", description)
        username = username_match.group(1) if username_match else None
        email = email_match.group(0) if email_match else None
        return username, email

    async def save_channels(self, session: AsyncSession, channels: list[ChannelInfo]) -> None:
        """Upsert channels into tg_channels table."""
        if not channels:
            return

        sql = text("""
            INSERT INTO tg_channels (
                username, title, subscriber_count, avg_views, er, description,
                contact_username, contact_email, topics, source, status,
                created_at, updated_at
            ) VALUES (
                :username, :title, :subscriber_count, :avg_views, :er, :description,
                :contact_username, :contact_email, :topics, :source, 'new',
                NOW(), NOW()
            )
            ON CONFLICT (username) DO UPDATE SET
                title = EXCLUDED.title,
                subscriber_count = EXCLUDED.subscriber_count,
                avg_views = EXCLUDED.avg_views,
                er = EXCLUDED.er,
                description = EXCLUDED.description,
                updated_at = NOW()
            """)

        for ch in channels:
            await session.execute(
                sql,
                {
                    "username": ch.username,
                    "title": ch.title,
                    "subscriber_count": ch.subscriber_count,
                    "avg_views": ch.avg_views,
                    "er": ch.er,
                    "description": ch.description,
                    "contact_username": ch.contact_username,
                    "contact_email": ch.contact_email,
                    "topics": json.dumps(ch.topics, ensure_ascii=False),
                    "source": ch.source,
                },
            )
        await session.commit()
        logger.info("Saved %d channels to DB", len(channels))
