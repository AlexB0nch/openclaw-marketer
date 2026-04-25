"""
Integration test: approved ContentPlan → ScheduledPost → published Telegram message.

All external APIs (Claude, Telegram) are mocked. The DB is the shared SQLite
in-memory fixture from conftest.py.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from integrations.content.calendar import CalendarManager
from integrations.content.generator import ContentGenerator
from integrations.content.habr_draft import HabrGenerator
from integrations.strategist.models import ContentPlan, ProductPlan, TopicEntry, WeeklyMetrics
from integrations.telegram.publisher import publish_post

_WEEK_START = date(2026, 4, 27)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_plan() -> ContentPlan:
    metrics = WeeklyMetrics(
        week_start=_WEEK_START,
        total_impressions=2000,
        total_clicks=100,
        avg_ctr=5.0,
        total_spend_rub=Decimal("4000.00"),
        roi=2.0,
        top_performing_product="Widget",
    )
    product = ProductPlan(
        product_id=1,
        product_name="Widget",
        topics=[
            TopicEntry(
                topic="Как Widget ускоряет разработку",
                channel="telegram",
                estimated_engagement=85,
                notes="Main feature post",
            ),
            TopicEntry(
                topic="Widget под капотом",
                channel="habr",
                estimated_engagement=70,
                notes="Technical deep-dive",
            ),
            TopicEntry(
                topic="Widget для бизнеса",
                channel="blog",
                estimated_engagement=65,
                notes="Business case",
            ),
        ],
        budget_allocation_rub=Decimal("2000.00"),
        priority="high",
    )
    return ContentPlan(
        week_start_date=_WEEK_START,
        week_end_date=_WEEK_START + timedelta(days=6),
        products=[product],
        metrics_summary=metrics,
        status="approved",
        created_at=datetime(2026, 4, 26, 19, 0, 0),
    )


def _mock_claude_response(body_text: str) -> MagicMock:
    block = MagicMock()
    block.text = body_text
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# Test: ContentPlan → ScheduledPost slots (no API calls)
# ---------------------------------------------------------------------------


class TestPlanToScheduledPosts:
    def test_generates_correct_number_of_posts(self, approved_plan):
        cal = CalendarManager()
        posts = cal.generate_week_schedule(approved_plan)
        # 3 topics: telegram→telegram, habr→habr, blog→vc.ru
        assert len(posts) == 3

    def test_platforms_mapped_correctly(self, approved_plan):
        posts = CalendarManager().generate_week_schedule(approved_plan)
        platforms = {p.platform for p in posts}
        assert "telegram" in platforms
        assert "habr" in platforms
        assert "vc.ru" in platforms

    def test_all_posts_belong_to_correct_product(self, approved_plan):
        posts = CalendarManager().generate_week_schedule(approved_plan)
        assert all(p.product_id == 1 for p in posts)
        assert all(p.product_name == "Widget" for p in posts)

    def test_slots_are_within_plan_week(self, approved_plan):
        posts = CalendarManager().generate_week_schedule(approved_plan)
        week_end = _WEEK_START + timedelta(days=6)
        for p in posts:
            assert _WEEK_START <= p.scheduled_at.date() <= week_end

    def test_posts_are_time_ordered(self, approved_plan):
        posts = CalendarManager().generate_week_schedule(approved_plan)
        times = [p.scheduled_at for p in posts]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# Test: generate_post fills body (Claude API mocked)
# ---------------------------------------------------------------------------


class TestGeneratePost:
    @pytest.mark.asyncio
    async def test_generate_fills_body(self, test_settings):
        with patch("integrations.content.generator.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_claude_response("Сгенерированный текст поста")
            )
            mock_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            post = await gen.generate_post(
                product_id=1,
                product_name="Widget",
                product_description="Speed up dev",
                platform="telegram",
                topic="Как Widget ускоряет разработку",
            )

        assert post.body == "Сгенерированный текст поста"
        assert post.platform == "telegram"

    @pytest.mark.asyncio
    async def test_generate_respects_rate_limiter(self, test_settings):
        """Rate limiter is called on each generate_post invocation."""
        with patch("integrations.content.generator.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(return_value=_mock_claude_response("text"))
            mock_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            acquire_calls = 0
            original_acquire = gen._limiter.acquire

            async def counting_acquire(*args, **kwargs):
                nonlocal acquire_calls
                acquire_calls += 1
                return await original_acquire(*args, **kwargs)

            gen._limiter.acquire = counting_acquire  # type: ignore[method-assign]
            await gen.generate_post(1, "P", "", "telegram", "T")
            await gen.generate_post(1, "P", "", "habr", "T")

        assert acquire_calls == 2


# ---------------------------------------------------------------------------
# Test: full pipeline — plan → schedule → save → generate → publish
# ---------------------------------------------------------------------------


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_plan_to_published_post(self, approved_plan, db_session, test_settings):
        """
        Full pipeline smoke-test:
        1. generate_week_schedule → ScheduledPost list
        2. save_scheduled_post → persisted to DB
        3. generate_post (mocked Claude) → body
        4. update_post_body → status=generated
        5. publish_post (mocked Telegram) → success + message_id
        6. mark_published → status=published
        """
        # Insert product so FK constraint is satisfied
        await db_session.execute(
            text("INSERT INTO products (id, name, active) VALUES (1, 'Widget', 1)")
        )
        await db_session.commit()

        # 1. Schedule
        cal = CalendarManager()
        posts = cal.generate_week_schedule(approved_plan)
        tg_post = next(p for p in posts if p.platform == "telegram")

        # 2. Save
        post_id = await cal.save_scheduled_post(db_session, tg_post, content_plan_id=None)
        assert post_id > 0

        # 3. Generate (mock Claude)
        with patch("integrations.content.generator.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_claude_response("Готовый Telegram пост 🚀")
            )
            mock_cls.return_value = mock_client

            gen = ContentGenerator(test_settings, rate=100.0, capacity=10.0)
            generated = await gen.generate_post(
                product_id=tg_post.product_id,
                product_name=tg_post.product_name,
                product_description="",
                platform=tg_post.platform,
                topic=tg_post.topic,
            )

        # 4. Update body in DB
        await cal.update_post_body(db_session, post_id, generated.body)
        saved = await cal.get_post_by_id(db_session, post_id)
        assert saved is not None
        assert saved.status == "generated"
        assert saved.body == "Готовый Telegram пост 🚀"

        # 5. Publish (mock Telegram bot)
        mock_bot = AsyncMock()
        sent_msg = MagicMock()
        sent_msg.message_id = 1234
        mock_bot.send_message = AsyncMock(return_value=sent_msg)

        success, message_id = await publish_post(mock_bot, "@widget_channel", saved)
        assert success is True
        assert message_id == 1234

        # 6. Mark published
        pub_at = datetime(2026, 4, 27, 9, 0, 0)
        await cal.mark_published(db_session, post_id, pub_at, telegram_message_id=message_id)

        final = await cal.get_post_by_id(db_session, post_id)
        assert final is not None
        assert final.status == "published"
        assert final.telegram_message_id == 1234

    @pytest.mark.asyncio
    async def test_failed_publish_sets_failed_status(
        self, approved_plan, db_session, test_settings
    ):
        """If publish fails after retries, post.status → failed."""
        from telegram.error import TelegramError

        await db_session.execute(
            text("INSERT OR IGNORE INTO products (id, name, active) VALUES (1, 'Widget', 1)")
        )
        await db_session.commit()

        cal = CalendarManager()
        posts = cal.generate_week_schedule(approved_plan)
        tg_post = next(p for p in posts if p.platform == "telegram")
        post_id = await cal.save_scheduled_post(db_session, tg_post)

        await cal.update_post_body(db_session, post_id, "Body text")
        saved = await cal.get_post_by_id(db_session, post_id)

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(side_effect=TelegramError("503 Service Unavailable"))

        with patch("integrations.telegram.publisher.asyncio.sleep", new=AsyncMock()):
            success, message_id = await publish_post(mock_bot, "@channel", saved)

        assert success is False
        await cal.mark_failed(db_session, post_id)

        fetched = await cal.get_post_by_id(db_session, post_id)
        assert fetched is not None
        assert fetched.status == "failed"


# ---------------------------------------------------------------------------
# Test: HabrGenerator (Claude API mocked)
# ---------------------------------------------------------------------------


class TestHabrDraftPipeline:
    @pytest.mark.asyncio
    async def test_generate_and_save_habr_draft(self, db_session, test_settings):
        """generate_habr_draft + save_draft + get_draft_by_id round-trip."""
        await db_session.execute(
            text("INSERT OR IGNORE INTO products (id, name, active) VALUES (1, 'Widget', 1)")
        )
        await db_session.commit()

        article_body = (
            "## Введение\n\nТекст введения.\n\n"
            "## Проблема\n\nОписание проблемы.\n\n"
            "## Решение\n\nОписание решения с кодом:\n\n```python\nprint('hello')\n```\n\n"
            "## Вывод\n\nЗаключение и CTA."
        )

        with patch("integrations.content.habr_draft.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_claude_response(article_body)
            )
            mock_cls.return_value = mock_client

            gen = HabrGenerator(test_settings)
            draft = await gen.generate_habr_draft(
                product_id=1,
                product_name="Widget",
                product_description="Speed up dev",
                brief="Как Widget помогает командам выпускать продукт быстрее",
            )

        assert draft.body == article_body
        assert draft.word_count > 0
        assert draft.status == "draft"
        assert "Введение" in draft.title or "Widget" in draft.title

        draft_id = await gen.save_draft(db_session, draft)
        assert isinstance(draft_id, int)

        fetched = await gen.get_draft_by_id(db_session, draft_id)
        assert fetched is not None
        assert fetched.body == article_body
        assert fetched.product_id == 1

    @pytest.mark.asyncio
    async def test_export_marks_as_exported(self, db_session, test_settings):
        """export_draft returns body and sets status to exported."""
        await db_session.execute(
            text("INSERT OR IGNORE INTO products (id, name, active) VALUES (1, 'Widget', 1)")
        )
        await db_session.commit()

        with patch("integrations.content.habr_draft.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_client.messages.create = AsyncMock(
                return_value=_mock_claude_response("## Title\n\nArticle body.")
            )
            mock_cls.return_value = mock_client

            gen = HabrGenerator(test_settings)
            draft = await gen.generate_habr_draft(1, "Widget", "", "Brief")
            draft_id = await gen.save_draft(db_session, draft)
            exported = await gen.export_draft(db_session, draft_id)

        assert exported == "## Title\n\nArticle body."

        fetched = await gen.get_draft_by_id(db_session, draft_id)
        assert fetched is not None
        assert fetched.status == "exported"
