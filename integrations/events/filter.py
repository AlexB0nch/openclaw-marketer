"""Relevance filter for conference events using Claude API."""

import logging
from datetime import date

import anthropic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from integrations.events.scraper import ConferenceEvent

logger = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=Settings().anthropic_api_key)
    return _client


class RelevantEvent(BaseModel):
    event: ConferenceEvent
    relevance_score: int
    matched_products: list[str]
    relevance_reason: str


class RelevanceFilter:
    def __init__(self, threshold: int = 50) -> None:
        self.threshold = threshold

    async def filter_relevant(
        self, events: list[ConferenceEvent], products: list[str]
    ) -> list[RelevantEvent]:
        today = date.today()

        filtered = [e for e in events if e.start_date is None or e.start_date >= today]

        seen: set[tuple[str, date | None]] = set()
        deduped: list[ConferenceEvent] = []
        for event in filtered:
            key = (event.name, event.start_date)
            if key not in seen:
                seen.add(key)
                deduped.append(event)

        results: list[RelevantEvent] = []
        for event in deduped:
            scores: list[tuple[str, int]] = []
            for product in products:
                score = await self._score_event(event, product)
                scores.append((product, score))

            max_score = max((s for _, s in scores), default=0)
            if max_score >= self.threshold:
                matched = [p for p, s in scores if s >= self.threshold]
                results.append(
                    RelevantEvent(
                        event=event,
                        relevance_score=max_score,
                        matched_products=matched,
                        relevance_reason=f"Score: {max_score}",
                    )
                )

        results.sort(key=lambda r: r.relevance_score, reverse=True)
        return results

    async def _score_event(self, event: ConferenceEvent, product: str) -> int:
        try:
            client = get_anthropic_client()
            message = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                system="Ты помощник по маркетингу. Оцени релевантность конференции для продукта.",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Конференция: {event.name}\n"
                            f"Описание: {event.description}\n"
                            f"Темы: {', '.join(event.topics)}\n"
                            f"Продукт: {product}\n\n"
                            "Насколько эта конференция подходит для выступления с докладом о продукте?\n"
                            "Ответь ТОЛЬКО числом от 0 до 100, без объяснений."
                        ),
                    }
                ],
            )
            return int(message.content[0].text.strip())
        except Exception as e:
            logger.warning("_score_event failed for %s/%s: %s", event.name, product, e)
            return 0

    async def save_relevance(self, session: AsyncSession, results: list[RelevantEvent]) -> None:
        for result in results:
            if result.relevance_score >= self.threshold:
                await session.execute(
                    text(
                        "UPDATE events_calendar SET status='relevant' "
                        "WHERE name=:name AND "
                        "(start_date=:sd OR (start_date IS NULL AND :sd IS NULL))"
                    ),
                    {
                        "name": result.event.name,
                        "sd": (
                            result.event.start_date.isoformat() if result.event.start_date else None
                        ),
                    },
                )
        await session.commit()


async def save_relevance(session: AsyncSession, results: list[RelevantEvent]) -> None:
    """Module-level convenience wrapper around RelevanceFilter.save_relevance."""
    await RelevanceFilter().save_relevance(session, results)
