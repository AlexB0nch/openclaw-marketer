"""Unit tests for CalendarManager."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from integrations.content.calendar import (
    _MSK,
    _PUBLISH_HOURS,
    CalendarManager,
    _week_slots,
)
from integrations.content.models import ScheduledPost
from integrations.strategist.models import ContentPlan, ProductPlan, TopicEntry, WeeklyMetrics

# ---------------------------------------------------------------------------
# Helpers — build a minimal ContentPlan
# ---------------------------------------------------------------------------

_WEEK_START = date(2026, 4, 27)  # Monday


def _make_metrics() -> WeeklyMetrics:
    return WeeklyMetrics(
        week_start=_WEEK_START,
        total_impressions=500,
        total_clicks=25,
        avg_ctr=5.0,
        total_spend_rub=Decimal("1000.00"),
        roi=1.5,
    )


def _make_topic(channel: str, topic: str = "Test topic") -> TopicEntry:
    return TopicEntry(
        topic=topic,
        channel=channel,  # type: ignore[arg-type]
        estimated_engagement=75,
        notes="test",
    )


def _make_plan(topics_per_product: list[list[tuple[str, str]]]) -> ContentPlan:
    products = []
    for i, topic_list in enumerate(topics_per_product, start=1):
        products.append(
            ProductPlan(
                product_id=i,
                product_name=f"Product {i}",
                topics=[_make_topic(ch, t) for ch, t in topic_list],
                budget_allocation_rub=Decimal("2000.00"),
                priority="medium",
            )
        )
    return ContentPlan(
        week_start_date=_WEEK_START,
        week_end_date=_WEEK_START + timedelta(days=6),
        products=products,
        metrics_summary=_make_metrics(),
        status="approved",
        created_at=datetime(2026, 4, 27, 19, 0, 0),
    )


# ---------------------------------------------------------------------------
# _week_slots helper
# ---------------------------------------------------------------------------


class TestWeekSlots:
    def test_returns_21_slots(self):
        slots = _week_slots(_WEEK_START)
        assert len(slots) == 21  # 7 days × 3 slots

    def test_slots_are_in_msk(self):
        slots = _week_slots(_WEEK_START)
        for slot in slots:
            assert slot.tzinfo is not None
            assert slot.tzinfo == _MSK or str(slot.tzinfo) == "Europe/Moscow"

    def test_slots_start_on_correct_date(self):
        slots = _week_slots(_WEEK_START)
        first = slots[0]
        assert first.date() == _WEEK_START
        assert first.hour == _PUBLISH_HOURS[0]

    def test_slots_end_on_sunday(self):
        slots = _week_slots(_WEEK_START)
        last = slots[-1]
        assert last.date() == _WEEK_START + timedelta(days=6)
        assert last.hour == _PUBLISH_HOURS[-1]

    def test_slot_hours_cycle_correctly(self):
        slots = _week_slots(_WEEK_START)
        day0_hours = [s.hour for s in slots[:3]]
        assert day0_hours == list(_PUBLISH_HOURS)

    def test_slots_are_sorted(self):
        slots = _week_slots(_WEEK_START)
        assert slots == sorted(slots)


# ---------------------------------------------------------------------------
# CalendarManager.generate_week_schedule
# ---------------------------------------------------------------------------


class TestGenerateWeekSchedule:
    def test_returns_list_of_scheduled_posts(self):
        plan = _make_plan([[("telegram", "Topic A"), ("habr", "Topic B")]])
        cal = CalendarManager()
        posts = cal.generate_week_schedule(plan)
        assert isinstance(posts, list)
        assert all(isinstance(p, ScheduledPost) for p in posts)

    def test_body_is_empty_initially(self):
        plan = _make_plan([[("telegram", "Topic A")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert all(p.body == "" for p in posts)

    def test_status_is_pending(self):
        plan = _make_plan([[("telegram", "Topic A")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert all(p.status == "pending" for p in posts)

    def test_product_id_assigned_correctly(self):
        plan = _make_plan([[("telegram", "Topic A")], [("habr", "Topic B")]])
        posts = CalendarManager().generate_week_schedule(plan)
        product_ids = {p.product_id for p in posts}
        assert 1 in product_ids
        assert 2 in product_ids

    def test_product_name_assigned(self):
        plan = _make_plan([[("telegram", "Topic A")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts[0].product_name == "Product 1"

    def test_channel_mapping_telegram(self):
        plan = _make_plan([[("telegram", "T")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts[0].platform == "telegram"

    def test_channel_mapping_blog_to_vcru(self):
        plan = _make_plan([[("blog", "T")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts[0].platform == "vc.ru"

    def test_channel_mapping_habr(self):
        plan = _make_plan([[("habr", "T")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts[0].platform == "habr"

    def test_youtube_channel_skipped(self):
        plan = _make_plan([[("youtube", "T"), ("telegram", "T2")]])
        posts = CalendarManager().generate_week_schedule(plan)
        # youtube is skipped → only telegram post remains
        assert len(posts) == 1
        assert posts[0].platform == "telegram"

    def test_scheduled_at_within_week(self):
        plan = _make_plan([[("telegram", "T1"), ("habr", "T2"), ("blog", "T3")]])
        posts = CalendarManager().generate_week_schedule(plan)
        week_end = _WEEK_START + timedelta(days=6)
        for p in posts:
            post_date = p.scheduled_at.date()
            assert _WEEK_START <= post_date <= week_end

    def test_no_more_than_21_posts(self):
        """Even with many topics we never exceed 21 slots per week."""
        topics = [("telegram", f"T{i}") for i in range(30)]
        plan = _make_plan([topics])
        posts = CalendarManager().generate_week_schedule(plan)
        assert len(posts) <= 21

    def test_empty_plan_returns_empty_list(self):
        plan = _make_plan([])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts == []

    def test_posts_are_ordered_by_slot(self):
        plan = _make_plan(
            [
                [("telegram", "T1"), ("habr", "T2"), ("blog", "T3")],
                [("telegram", "T4"), ("habr", "T5")],
            ]
        )
        posts = CalendarManager().generate_week_schedule(plan)
        times = [p.scheduled_at for p in posts]
        assert times == sorted(times)

    def test_topic_text_preserved(self):
        plan = _make_plan([[("telegram", "Особый топик для теста")]])
        posts = CalendarManager().generate_week_schedule(plan)
        assert posts[0].topic == "Особый топик для теста"


# ---------------------------------------------------------------------------
# CalendarManager CRUD (SQLite test DB)
# ---------------------------------------------------------------------------


class TestCalendarManagerDB:
    """Test DB operations using the SQLite fixture from conftest."""

    @pytest.mark.asyncio
    async def test_save_and_retrieve_by_id(self, db_session):
        """save_scheduled_post persists a post; get_post_by_id retrieves it."""
        from sqlalchemy import text

        await db_session.execute(
            text("INSERT INTO products (id, name, active) VALUES (10, 'TestProd', 1)")
        )
        await db_session.commit()

        cal = CalendarManager()
        post = ScheduledPost(
            product_id=10,
            product_name="TestProd",
            platform="telegram",
            topic="Unit test topic",
            body="",
            scheduled_at=datetime(2026, 4, 27, 9, 0, 0),
            status="pending",
        )
        post_id = await cal.save_scheduled_post(db_session, post)
        assert isinstance(post_id, int)
        assert post_id > 0

        fetched = await cal.get_post_by_id(db_session, post_id)
        assert fetched is not None
        assert fetched.topic == "Unit test topic"
        assert fetched.platform == "telegram"
        assert fetched.status == "pending"

    @pytest.mark.asyncio
    async def test_update_post_body_sets_generated(self, db_session):
        """update_post_body changes body and advances status to generated."""
        from sqlalchemy import text

        await db_session.execute(
            text("INSERT INTO products (id, name, active) VALUES (11, 'Prod11', 1)")
        )
        await db_session.commit()

        cal = CalendarManager()
        post = ScheduledPost(
            product_id=11,
            product_name="Prod11",
            platform="habr",
            topic="DB body update test",
            body="",
            scheduled_at=datetime(2026, 4, 27, 12, 0, 0),
        )
        post_id = await cal.save_scheduled_post(db_session, post)
        await cal.update_post_body(db_session, post_id, "Generated body text")

        updated = await cal.get_post_by_id(db_session, post_id)
        assert updated is not None
        assert updated.body == "Generated body text"
        assert updated.status == "generated"

    @pytest.mark.asyncio
    async def test_mark_failed_sets_status(self, db_session):
        """mark_failed sets status to failed."""
        from sqlalchemy import text

        await db_session.execute(
            text("INSERT INTO products (id, name, active) VALUES (12, 'Prod12', 1)")
        )
        await db_session.commit()

        cal = CalendarManager()
        post = ScheduledPost(
            product_id=12,
            product_name="Prod12",
            platform="telegram",
            topic="Fail test",
            body="text",
            scheduled_at=datetime(2026, 4, 27, 18, 0, 0),
            status="generated",
        )
        post_id = await cal.save_scheduled_post(db_session, post)
        await cal.mark_failed(db_session, post_id)

        fetched = await cal.get_post_by_id(db_session, post_id)
        assert fetched is not None
        assert fetched.status == "failed"

    @pytest.mark.asyncio
    async def test_mark_published_records_metadata(self, db_session):
        """mark_published stores published_at and telegram_message_id."""
        from sqlalchemy import text

        await db_session.execute(
            text("INSERT INTO products (id, name, active) VALUES (13, 'Prod13', 1)")
        )
        await db_session.commit()

        cal = CalendarManager()
        post = ScheduledPost(
            product_id=13,
            product_name="Prod13",
            platform="telegram",
            topic="Publish test",
            body="Body",
            scheduled_at=datetime(2026, 4, 27, 9, 0, 0),
            status="generated",
        )
        post_id = await cal.save_scheduled_post(db_session, post)
        pub_at = datetime(2026, 4, 27, 9, 1, 0)
        await cal.mark_published(db_session, post_id, pub_at, telegram_message_id=9999)

        fetched = await cal.get_post_by_id(db_session, post_id)
        assert fetched is not None
        assert fetched.status == "published"
        assert fetched.telegram_message_id == 9999

    @pytest.mark.asyncio
    async def test_get_nonexistent_post_returns_none(self, db_session):
        """get_post_by_id returns None for unknown id."""
        cal = CalendarManager()
        result = await cal.get_post_by_id(db_session, 999999)
        assert result is None
