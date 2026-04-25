"""Habr long-form article draft generator."""

import logging

from anthropic import AsyncAnthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from integrations.content.models import HabrDraft

logger = logging.getLogger(__name__)

_ARTICLE_SYSTEM = (
    "Ты — опытный технический автор и маркетолог. "
    "Пишешь глубокие статьи для Habr: технически точные, практичные, с примерами кода. "
    "Статьи всегда на русском языке."
)

_ARTICLE_PROMPT = """\
Напиши статью для Habr по следующему брифу.

Продукт: {product_name}
Описание: {product_description}
Бриф / главный тезис: {brief}

Структура статьи (обязательная):
1. **Введение** — контекст, почему это важно (200–300 слов)
2. **Проблема** — боль разработчика / бизнеса без этого продукта (400–600 слов)
3. **Решение** — как продукт решает проблему, архитектура, ключевые фичи (600–900 слов)
4. **Примеры кода** — минимум 2 практических примера с комментариями (400–600 слов)
5. **Результаты / кейс** — цифры, метрики, что изменилось (300–400 слов)
6. **Вывод + CTA** — что читатель должен сделать дальше (150–200 слов)

Общий объём: 2000–4000 слов.
Используй заголовки Markdown (## и ###).
Верни ТОЛЬКО текст статьи без мета-комментариев.
"""


class HabrGenerator:
    """Generates long-form Habr articles and persists them to DB."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate_habr_draft(
        self,
        product_id: int,
        product_name: str,
        product_description: str,
        brief: str,
    ) -> HabrDraft:
        """Generate a long-form Habr article for the given product and brief."""
        prompt = _ARTICLE_PROMPT.format(
            product_name=product_name,
            product_description=product_description or "не указано",
            brief=brief,
        )
        logger.info("Generating Habr draft for product %d: %s", product_id, brief[:60])

        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=_ARTICLE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        body = response.content[0].text.strip()
        title = _extract_title(body, product_name, brief)
        word_count = len(body.split())

        logger.info(
            "Generated Habr draft for product %d — %d words, title: %s",
            product_id,
            word_count,
            title,
        )
        return HabrDraft(
            product_id=product_id,
            product_name=product_name,
            title=title,
            brief=brief,
            body=body,
            word_count=word_count,
            status="draft",
        )

    async def save_draft(self, session: AsyncSession, draft: HabrDraft) -> int:
        """Persist a HabrDraft to DB and return its id."""
        stmt = text("""INSERT INTO habr_drafts
               (product_id, product_name, title, brief, body, word_count, status)
               VALUES (:product_id, :product_name, :title, :brief, :body, :word_count, :status)
               RETURNING id""")
        result = await session.execute(
            stmt,
            {
                "product_id": draft.product_id,
                "product_name": draft.product_name,
                "title": draft.title,
                "brief": draft.brief,
                "body": draft.body,
                "word_count": draft.word_count,
                "status": draft.status,
            },
        )
        row = result.first()
        await session.commit()
        return row[0]  # type: ignore[index]

    async def get_draft_by_id(self, session: AsyncSession, draft_id: int) -> HabrDraft | None:
        """Fetch a draft by primary key."""
        stmt = text("""SELECT id, product_id, product_name, title, brief, body,
                      word_count, status, created_at
               FROM habr_drafts WHERE id = :draft_id""")
        result = await session.execute(stmt, {"draft_id": draft_id})
        row = result.first()
        if not row:
            return None
        return HabrDraft(
            id=row[0],
            product_id=row[1],
            product_name=row[2],
            title=row[3],
            brief=row[4],
            body=row[5],
            word_count=row[6],
            status=row[7],
            created_at=row[8],
        )

    async def mark_ready(self, session: AsyncSession, draft_id: int) -> None:
        """Advance draft status to 'ready' (reviewed, ready for export)."""
        stmt = text("UPDATE habr_drafts SET status = 'ready' WHERE id = :draft_id")
        await session.execute(stmt, {"draft_id": draft_id})
        await session.commit()

    async def export_draft(self, session: AsyncSession, draft_id: int) -> str | None:
        """Return draft body as Markdown string and mark as exported."""
        draft = await self.get_draft_by_id(session, draft_id)
        if not draft:
            return None
        stmt = text("UPDATE habr_drafts SET status = 'exported' WHERE id = :draft_id")
        await session.execute(stmt, {"draft_id": draft_id})
        await session.commit()
        return draft.body


def _extract_title(body: str, product_name: str, brief: str) -> str:
    """Extract the first H1/H2 heading from the article body, or synthesise a title."""
    for line in body.splitlines():
        stripped = line.lstrip("#").strip()
        if line.startswith("#") and stripped:
            return stripped[:200]
    # Fallback: derive from brief
    title = brief.strip().rstrip(".")
    return f"{product_name}: {title}"[:200]
