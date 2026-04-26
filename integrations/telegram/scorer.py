"""Relevance scorer for Telegram channels using keyword overlap and Claude AI."""

from __future__ import annotations

import asyncio
import json
import logging
import math

import anthropic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.telegram.scout import ChannelInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class RelevanceScore(BaseModel):
    channel_username: str
    product: str
    score: int  # 0-100, sum of all breakdown values
    breakdown: dict[str, int]  # keys: size_score, er_score, topic_score, semantic_score


# ---------------------------------------------------------------------------
# Keyword map by product
# ---------------------------------------------------------------------------

PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "ai_assistant": ["ai", "помощник", "переписка", "email", "b2b", "автоматизация"],
    "ai_trainer": ["спорт", "тренировки", "фитнес", "коуч", "зож", "здоровье"],
    "ai_news": ["новости", "дайджест", "агрегатор", "it", "технологии", "tech"],
}


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class RelevanceScorer:
    """Scores Telegram channels for relevance to a given product."""

    def __init__(self, anthropic_client: anthropic.AsyncAnthropic) -> None:
        self._client = anthropic_client

    # ------------------------------------------------------------------
    # Sub-scores
    # ------------------------------------------------------------------

    @staticmethod
    def _size_score(subscriber_count: int) -> int:
        """0-25 based on log10 scale of subscriber count."""
        if subscriber_count < 1000:
            return 0
        if subscriber_count >= 100_000:
            return 25
        return int(math.log10(subscriber_count / 1000) / math.log10(100) * 25)

    @staticmethod
    def _er_score(er: float) -> int:
        """0-25 based on engagement rate."""
        if er < 0.01:
            return 0
        if er >= 0.10:
            return 25
        return int((er - 0.01) / 0.09 * 25)

    @staticmethod
    def _topic_score(channel: ChannelInfo, product: str) -> int:
        """0-25 based on keyword overlap between product and channel text."""
        product_keywords = PRODUCT_KEYWORDS.get(product, product.lower().split())
        if not product_keywords:
            return 0
        channel_text = (channel.description + " " + " ".join(channel.topics)).lower()
        matches = sum(1 for kw in product_keywords if kw in channel_text)
        return min(25, int(matches / len(product_keywords) * 25 * 2))

    async def _semantic_score(self, channel: ChannelInfo, product: str) -> int:
        """0-25 from Claude Haiku based on semantic relevance."""
        prompt = (
            f"Rate 0-25 how relevant this Telegram channel is for promoting {product}:\n"
            f"Channel description: {channel.description}\n"
            f"Topics: {channel.topics}\n"
            f"Output only an integer from 0 to 25."
        )
        try:
            response = await self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            value = int(raw)
            return max(0, min(25, value))
        except Exception:
            logger.warning("semantic_score failed for @%s, defaulting to 0", channel.username)
            return 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def score_channel(self, channel: ChannelInfo, product: str) -> RelevanceScore:
        """Score a single channel for relevance to *product*."""
        size_score = self._size_score(channel.subscriber_count)
        er_score = self._er_score(channel.er)
        topic_score = self._topic_score(channel, product)
        semantic_score = await self._semantic_score(channel, product)

        breakdown: dict[str, int] = {
            "size_score": size_score,
            "er_score": er_score,
            "topic_score": topic_score,
            "semantic_score": semantic_score,
        }
        return RelevanceScore(
            channel_username=channel.username,
            product=product,
            score=sum(breakdown.values()),
            breakdown=breakdown,
        )

    async def batch_score(self, channels: list[ChannelInfo], product: str) -> list[RelevanceScore]:
        """Score all channels concurrently."""
        return list(await asyncio.gather(*[self.score_channel(ch, product) for ch in channels]))

    async def save_scores(self, session: AsyncSession, scores: list[RelevanceScore]) -> None:
        """Upsert scores into tg_channel_scores table."""
        sql = text("""
            INSERT INTO tg_channel_scores (channel_id, product, score, breakdown, scored_at)
            SELECT id, :product, :score, :breakdown, NOW()
            FROM tg_channels WHERE username = :username
            ON CONFLICT (channel_id, product) DO UPDATE SET
              score=EXCLUDED.score,
              breakdown=EXCLUDED.breakdown,
              scored_at=NOW()
            """)
        for score in scores:
            await session.execute(
                sql,
                {
                    "username": score.channel_username,
                    "product": score.product,
                    "score": score.score,
                    "breakdown": json.dumps(score.breakdown),
                },
            )
        await session.commit()
        logger.info("Saved %d scores to DB", len(scores))
