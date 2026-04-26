"""Deadline tracker and abstract generator for conference events."""

import logging
from datetime import date, timedelta

import anthropic
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


class DeadlineTracker:
    async def check_upcoming_deadlines(self, session: AsyncSession) -> list[ConferenceEvent]:
        today = date.today()
        start = today + timedelta(days=1)
        end = today + timedelta(days=14)

        result = await session.execute(
            text(
                "SELECT name, url, start_date, cfp_deadline, city, is_online, "
                "audience_size, description, topics, source, status "
                "FROM events_calendar "
                "WHERE cfp_deadline >= :start AND cfp_deadline <= :end AND status = 'relevant'"
            ),
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        rows = result.fetchall()

        events: list[ConferenceEvent] = []
        for row in rows:
            import json

            topics_raw = row[8]
            try:
                topics = json.loads(topics_raw) if topics_raw else []
            except Exception:
                topics = []

            events.append(
                ConferenceEvent(
                    name=row[0],
                    url=row[1],
                    start_date=date.fromisoformat(row[2]) if row[2] else None,
                    cfp_deadline=date.fromisoformat(row[3]) if row[3] else None,
                    city=row[4],
                    is_online=bool(row[5]),
                    audience_size=row[6],
                    description=row[7] or "",
                    topics=topics,
                    source=row[9] or "",
                    status=row[10] or "new",
                )
            )
        return events

    async def generate_abstract_draft(self, event: ConferenceEvent, product: str) -> str:
        try:
            client = get_anthropic_client()
            message = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system="Ты опытный спикер конференций. Пиши на русском языке, профессионально и убедительно.",
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f'Напиши черновик заявки спикера для конференции "{event.name}" '
                            f'на тему продукта "{product}".\n\n'
                            "Структура (200-400 слов):\n"
                            "1. Хук — захватывающее начало\n"
                            "2. Постановка проблемы\n"
                            f"3. Наше решение ({product})\n"
                            "4. Ключевые выводы для аудитории\n"
                            "5. [Данные спикера — заполнить вручную]\n\n"
                            f"Конференция: {event.name}\n"
                            f"Описание: {event.description}"
                        ),
                    }
                ],
            )
            return message.content[0].text
        except Exception as e:
            logger.warning("generate_abstract_draft failed for %s: %s", event.name, e)
            return ""

    async def save_abstract(
        self,
        session: AsyncSession,
        event_id: int,
        product: str,
        abstract_text: str,
    ) -> None:
        existing = await session.execute(
            text(
                "SELECT id FROM events_abstracts WHERE event_id = :event_id AND product = :product"
            ),
            {"event_id": event_id, "product": product},
        )
        row = existing.fetchone()
        if row:
            await session.execute(
                text("UPDATE events_abstracts SET abstract_text = :abstract_text WHERE id = :id"),
                {"abstract_text": abstract_text, "id": row[0]},
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO events_abstracts (event_id, product, abstract_text) "
                    "VALUES (:event_id, :product, :abstract_text)"
                ),
                {"event_id": event_id, "product": product, "abstract_text": abstract_text},
            )
        await session.commit()
