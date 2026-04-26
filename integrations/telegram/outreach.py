"""Outreach manager: weekly digest and callback handling for TG Scout."""

from __future__ import annotations

import logging

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from integrations.telegram.pitch import PitchDraft
from integrations.telegram.scout import ChannelInfo

logger = logging.getLogger(__name__)


class ChannelWithPitch(BaseModel):
    channel: ChannelInfo
    pitch: PitchDraft
    score: int


class OutreachManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def build_weekly_digest(
        self, session: AsyncSession, top_n: int = 10
    ) -> list[ChannelWithPitch]:
        """Fetch top-N channels by score with their latest pending pitch drafts."""
        sql = text(
            """
            SELECT
                c.username, c.title, c.subscriber_count, c.avg_views, c.er,
                c.description, c.contact_username, c.contact_email,
                c.topics, c.source,
                cs.score, cs.product,
                pd.pitch_short, pd.pitch_medium, pd.pitch_long, pd.status
            FROM tg_channels c
            JOIN tg_channel_scores cs ON cs.channel_id = c.id
            JOIN tg_pitch_drafts pd
                ON pd.channel_id = c.id AND pd.product = cs.product
            WHERE pd.status = 'pending_approval'
            ORDER BY cs.score DESC
            LIMIT :top_n
            """
        )
        result = await session.execute(sql, {"top_n": top_n})
        rows = result.mappings().all()

        items: list[ChannelWithPitch] = []
        import json

        for row in rows:
            topics = row["topics"]
            if isinstance(topics, str):
                topics = json.loads(topics)
            channel = ChannelInfo(
                username=row["username"],
                title=row["title"],
                subscriber_count=row["subscriber_count"],
                avg_views=float(row["avg_views"]),
                er=float(row["er"]),
                description=row["description"] or "",
                contact_username=row["contact_username"],
                contact_email=row["contact_email"],
                topics=topics or [],
                source=row["source"] or "telethon",
            )
            pitch = PitchDraft(
                channel_username=row["username"],
                product=row["product"],
                pitch_short=row["pitch_short"] or "",
                pitch_medium=row["pitch_medium"] or "",
                pitch_long=row["pitch_long"] or "",
                status=row["status"],
            )
            items.append(ChannelWithPitch(channel=channel, pitch=pitch, score=row["score"]))
        return items

    async def send_weekly_digest(self, session: AsyncSession, bot) -> None:
        """Send formatted digest cards to admin chat."""
        items = await self.build_weekly_digest(session)
        if not items:
            await bot.send_message(
                chat_id=self._settings.telegram_admin_chat_id,
                text="📭 Нет новых каналов для ревью на этой неделе.",
            )
            return

        header = f"📊 *Еженедельный дайджест TG Scout* — топ-{len(items)} каналов\n\n"
        await bot.send_message(
            chat_id=self._settings.telegram_admin_chat_id,
            text=header,
            parse_mode="Markdown",
        )

        for item in items:
            ch = item.channel
            topics_str = ", ".join(ch.topics[:3]) if ch.topics else "—"
            preview = item.pitch.pitch_short[:100]
            text = (
                f"📢 @{ch.username}\n"
                f"👥 {ch.subscriber_count:,} подписчиков | "
                f"ER: {ch.er * 100:.1f}% | Score: {item.score}/100\n"
                f"Тема: {topics_str}\n"
                f"📝 Питч: {preview}…"
            )
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Отправить питч",
                            callback_data=f"scout_send:{ch.username}",
                        ),
                        InlineKeyboardButton(
                            "👀 Показать полный",
                            callback_data=f"scout_show:{ch.username}",
                        ),
                        InlineKeyboardButton(
                            "❌ Пропустить",
                            callback_data=f"scout_skip:{ch.username}",
                        ),
                    ]
                ]
            )
            await bot.send_message(
                chat_id=self._settings.telegram_admin_chat_id,
                text=text,
                reply_markup=keyboard,
            )
        logger.info("Weekly digest sent: %d channels", len(items))

    async def handle_send_callback(
        self,
        session: AsyncSession,
        telethon_client,
        callback_data: str,
    ) -> None:
        """Send pitch_short via Telethon DM. Idempotent — won't send twice."""
        channel_username = callback_data.split(":", 1)[1]

        # Check idempotency
        check = await session.execute(
            text(
                """
                SELECT id FROM tg_channel_outreach
                WHERE channel_id = (SELECT id FROM tg_channels WHERE username = :username)
                AND action = 'sent'
                LIMIT 1
                """
            ),
            {"username": channel_username},
        )
        if check.fetchone():
            logger.info("Pitch already sent to @%s, skipping", channel_username)
            return

        # Load pitch
        row = await session.execute(
            text(
                """
                SELECT pd.pitch_short, c.contact_username
                FROM tg_pitch_drafts pd
                JOIN tg_channels c ON c.id = pd.channel_id
                WHERE c.username = :username AND pd.status = 'pending_approval'
                ORDER BY pd.created_at DESC LIMIT 1
                """
            ),
            {"username": channel_username},
        )
        data = row.mappings().fetchone()
        if not data:
            logger.warning("No pending pitch found for @%s", channel_username)
            return

        contact = data["contact_username"] or channel_username
        try:
            await telethon_client.send_message(contact, data["pitch_short"])
            result = "ok"
        except Exception as exc:
            result = str(exc)
            logger.error("Failed to send DM to @%s: %s", contact, exc)

        await session.execute(
            text(
                """
                INSERT INTO tg_channel_outreach (channel_id, product, action, actor, result, timestamp)
                SELECT c.id, pd.product, 'sent', 'bot', :result, NOW()
                FROM tg_channels c
                JOIN tg_pitch_drafts pd ON pd.channel_id = c.id
                WHERE c.username = :username
                ORDER BY pd.created_at DESC LIMIT 1
                """
            ),
            {"username": channel_username, "result": result},
        )
        await session.commit()
        logger.info("Outreach logged for @%s: %s", channel_username, result)

    async def handle_show_callback(
        self, session: AsyncSession, bot, callback_data: str
    ) -> None:
        """Reply with pitch_medium text."""
        channel_username = callback_data.split(":", 1)[1]
        row = await session.execute(
            text(
                """
                SELECT pd.pitch_medium
                FROM tg_pitch_drafts pd
                JOIN tg_channels c ON c.id = pd.channel_id
                WHERE c.username = :username
                ORDER BY pd.created_at DESC LIMIT 1
                """
            ),
            {"username": channel_username},
        )
        data = row.mappings().fetchone()
        if not data:
            return

        await bot.send_message(
            chat_id=self._settings.telegram_admin_chat_id,
            text=f"📋 Полный питч для @{channel_username}:\n\n{data['pitch_medium']}",
        )

        await session.execute(
            text(
                """
                INSERT INTO tg_channel_outreach (channel_id, action, actor, result, timestamp)
                SELECT id, 'shown', 'bot', 'ok', NOW()
                FROM tg_channels WHERE username = :username
                """
            ),
            {"username": channel_username},
        )
        await session.commit()

    async def handle_skip_callback(
        self, session: AsyncSession, callback_data: str
    ) -> None:
        """Mark channel as skipped_this_week."""
        channel_username = callback_data.split(":", 1)[1]

        await session.execute(
            text(
                "UPDATE tg_channels SET status = 'skipped_this_week' WHERE username = :username"
            ),
            {"username": channel_username},
        )
        await session.execute(
            text(
                """
                INSERT INTO tg_channel_outreach (channel_id, action, actor, result, timestamp)
                SELECT id, 'skipped', 'bot', 'ok', NOW()
                FROM tg_channels WHERE username = :username
                """
            ),
            {"username": channel_username},
        )
        await session.commit()
        logger.info("Channel @%s marked as skipped_this_week", channel_username)
