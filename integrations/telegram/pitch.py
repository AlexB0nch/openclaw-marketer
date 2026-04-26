"""Pitch generator for Telegram channel outreach using Claude AI."""

from __future__ import annotations

import asyncio
import logging

import anthropic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.telegram.scout import ChannelInfo
from integrations.telegram.scorer import RelevanceScore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PitchDraft(BaseModel):
    channel_username: str
    product: str
    pitch_short: str  # DM text, ≤200 chars
    pitch_medium: str  # email, 100-300 words
    pitch_long: str  # full proposal, 300-600 words
    status: str = "pending_approval"  # pending_approval|approved|rejected|sent


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class PitchGenerator:
    """Generates outreach pitches for Telegram channels."""

    def __init__(self, anthropic_client: anthropic.AsyncAnthropic) -> None:
        self._client = anthropic_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _generate_short(
        self, channel: ChannelInfo, product: str, relevance_score: RelevanceScore
    ) -> str:
        prompt = (
            f"Напиши короткий питч (ДМ, максимум 200 символов) для Telegram канала "
            f"@{channel.username} ({channel.title}) для продвижения продукта {product}.\n"
            f"Описание канала: {channel.description[:300]}\n"
            f"Темы: {', '.join(channel.topics)}\n"
            f"Оценка релевантности: {relevance_score.score}/100\n"
            f"Пиши на русском, неформально, персонализировано. "
            f"Только текст питча, без лишних объяснений."
        )
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()[:200]

    async def _generate_medium(self, channel: ChannelInfo, product: str) -> str:
        prompt = (
            f"Напиши питч для email (100-300 слов) для Telegram канала "
            f"@{channel.username} ({channel.title}) для продвижения продукта {product}.\n"
            f"Описание канала: {channel.description[:500]}\n"
            f"Темы: {', '.join(channel.topics)}\n"
            f"Включи: приветствие, почему продукт подходит именно этой аудитории, "
            f"предложение коллаборации, CTA.\n"
            f"Пиши на русском, профессионально, но живо."
        )
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    async def _generate_long(self, channel: ChannelInfo, product: str) -> str:
        prompt = (
            f"Напиши полное коммерческое предложение (300-600 слов) для Telegram канала "
            f"@{channel.username} для продвижения продукта {product}.\n"
            f"Описание канала: {channel.description}\n"
            f"Темы: {', '.join(channel.topics)}\n"
            f"Подписчиков: {channel.subscriber_count:,}\n"
            f"ER: {channel.er * 100:.1f}%\n"
            f"Включи: описание продукта, целевая аудитория, форматы сотрудничества, "
            f"ожидаемые результаты, условия.\n"
            f"Структурируй с заголовками. Пиши на русском."
        )
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_pitch(
        self,
        channel: ChannelInfo,
        product: str,
        relevance_score: RelevanceScore,
    ) -> PitchDraft:
        """Generate short, medium, and long pitches concurrently."""
        pitch_short, pitch_medium, pitch_long = await asyncio.gather(
            self._generate_short(channel, product, relevance_score),
            self._generate_medium(channel, product),
            self._generate_long(channel, product),
        )
        return PitchDraft(
            channel_username=channel.username,
            product=product,
            pitch_short=pitch_short,
            pitch_medium=pitch_medium,
            pitch_long=pitch_long,
            status="pending_approval",
        )

    async def save_draft(self, session: AsyncSession, draft: PitchDraft) -> None:
        """Insert pitch draft into tg_pitch_drafts table."""
        sql = text(
            """
            INSERT INTO tg_pitch_drafts
              (channel_id, product, pitch_short, pitch_medium, pitch_long, status, created_at)
            SELECT id, :product, :pitch_short, :pitch_medium, :pitch_long,
                   'pending_approval', NOW()
            FROM tg_channels WHERE username = :username
            ON CONFLICT DO NOTHING
            """
        )
        await session.execute(
            sql,
            {
                "username": draft.channel_username,
                "product": draft.product,
                "pitch_short": draft.pitch_short,
                "pitch_medium": draft.pitch_medium,
                "pitch_long": draft.pitch_long,
            },
        )
        await session.commit()

    async def batch_generate(
        self,
        channels_with_scores: list[tuple[ChannelInfo, RelevanceScore]],
        product: str,
    ) -> list[PitchDraft]:
        """Generate pitches for multiple channels, at most 5 concurrently."""
        semaphore = asyncio.Semaphore(5)

        async def _guarded(channel: ChannelInfo, score: RelevanceScore) -> PitchDraft:
            async with semaphore:
                return await self.generate_pitch(channel, product, score)

        return list(
            await asyncio.gather(
                *[_guarded(channel, score) for channel, score in channels_with_scores]
            )
        )
