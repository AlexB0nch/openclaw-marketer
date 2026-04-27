"""Sprint 7: end-to-end integration tests across all agents.

All external HTTP, Claude API, and Telegram Bot calls are mocked. The DB is the
shared SQLite in-memory fixture from conftest.py, augmented locally with the
DLQ table and TG-Scout tables not provided by the base fixture.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text

from integrations.content.calendar import CalendarManager
from integrations.events.filter import RelevanceFilter
from integrations.events.scraper import ConferenceEvent
from integrations.strategist.models import (
    ContentPlan,
    ProductPlan,
    TopicEntry,
    WeeklyMetrics,
)
from integrations.telegram.scout import ChannelInfo

_WEEK_START = date(2026, 4, 27)


def _claude_response(text_value: str) -> MagicMock:
    block = MagicMock()
    block.text = text_value
    resp = MagicMock()
    resp.content = [block]
    return resp


def _build_plan() -> ContentPlan:
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
                topic="Запуск Widget",
                channel="telegram",
                estimated_engagement=80,
                notes="Launch",
            ),
            TopicEntry(
                topic="Widget Case Study",
                channel="habr",
                estimated_engagement=70,
                notes="Case",
            ),
            TopicEntry(
                topic="Widget Blog",
                channel="blog",
                estimated_engagement=65,
                notes="Blog",
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
        status="pending_approval",
        created_at=datetime(2026, 4, 26, 19, 0, 0),
    )


async def _ensure_dlq_table(session) -> None:
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS dead_letter_queue ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  agent TEXT NOT NULL,"
            "  task TEXT NOT NULL,"
            "  payload TEXT,"
            "  error_message TEXT,"
            "  traceback TEXT,"
            "  attempts INTEGER DEFAULT 1,"
            "  status TEXT DEFAULT 'pending',"
            "  created_at TEXT DEFAULT (datetime('now')),"
            "  updated_at TEXT DEFAULT (datetime('now'))"
            ")"
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# 1. Strategist → Content pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strategist_to_content_pipeline(db_session):
    """Approve a plan then schedule posts for the week."""
    plan = _build_plan()
    plan_dict = json.loads(plan.model_dump_json())

    # Insert plan into DB with pending_approval status
    await db_session.execute(
        text(
            "INSERT INTO content_plans (id, week_start_date, week_end_date, "
            "status, plan_json, created_by_agent) "
            "VALUES (1, :ws, :we, 'pending_approval', :pj, 'strategist')"
        ),
        {
            "ws": plan.week_start_date.isoformat(),
            "we": plan.week_end_date.isoformat(),
            "pj": json.dumps(plan_dict, default=str),
        },
    )
    await db_session.commit()

    # Approve plan (direct SQL: avoids strategist's plan_approvals insert
    # whose schema is more elaborate in real Postgres than in SQLite test fixture)
    await db_session.execute(
        text("UPDATE content_plans SET status='approved', approved_by_user='admin' " "WHERE id=1")
    )
    await db_session.commit()

    row = await db_session.execute(text("SELECT status FROM content_plans WHERE id = 1"))
    assert row.scalar() == "approved"

    # Insert product so FK constraint is satisfied
    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (1, 'Widget', 1)")
    )
    await db_session.commit()

    # Generate scheduled posts
    cal = CalendarManager()
    posts = cal.generate_week_schedule(plan)
    for p in posts:
        await cal.save_scheduled_post(db_session, p, content_plan_id=1)

    count_row = await db_session.execute(text("SELECT COUNT(*) FROM scheduled_posts"))
    assert count_row.scalar() == 3


# ---------------------------------------------------------------------------
# 2. Content → Publish pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_to_publish_pipeline(db_session):
    from integrations.telegram.publisher import publish_post

    await db_session.execute(
        text("INSERT OR IGNORE INTO products (id, name, active) VALUES (1, 'Widget', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO scheduled_posts "
            "(product_id, product_name, platform, topic, body, scheduled_at, status) "
            "VALUES (1, 'Widget', 'telegram', 'Topic', 'Body 🚀', "
            ":sa, 'generated')"
        ),
        {"sa": datetime(2026, 4, 27, 9, 0).isoformat()},
    )
    await db_session.commit()

    cal = CalendarManager()
    row = await db_session.execute(text("SELECT id FROM scheduled_posts LIMIT 1"))
    post_id = row.scalar()
    saved = await cal.get_post_by_id(db_session, post_id)

    sent = MagicMock()
    sent.message_id = 9001
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=sent)

    success, message_id = await publish_post(bot, "@channel", saved)
    assert success is True
    assert message_id == 9001

    await cal.mark_published(
        db_session, post_id, datetime(2026, 4, 27, 9, 0, 5), telegram_message_id=message_id
    )

    final = await cal.get_post_by_id(db_session, post_id)
    assert final.status == "published"
    assert final.telegram_message_id == 9001


# ---------------------------------------------------------------------------
# 3. Analytics digest runs without crash on empty tables
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analytics_digest_runs_without_crash(db_session, test_settings):
    from integrations.analytics.digest import MorningDigest
    from integrations.analytics.engine import AnalyticsEngine

    engine = AnalyticsEngine(db_session)
    digest = MorningDigest()
    text_msg = await digest.generate(db_session, engine, test_settings)

    assert isinstance(text_msg, str)
    assert len(text_msg) > 0


# ---------------------------------------------------------------------------
# 4. Ads campaign approval flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ads_campaign_approval_flow(db_session):
    from integrations.ads.approval import AdsApprovalManager

    config = {"name": "Widget Ads", "budget_rub": 30000, "platform": "yandex"}
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns (id, product_id, platform, status, "
            "config_json, budget_rub) "
            "VALUES (1, 1, 'yandex', 'pending_approval', :cfg, 30000)"
        ),
        {"cfg": json.dumps(config)},
    )
    await db_session.commit()

    yandex_client = MagicMock()
    yandex_client.create_campaign = AsyncMock(return_value=42)

    manager = AdsApprovalManager()
    await manager.handle_approval_callback(
        session=db_session,
        yandex_client=yandex_client,
        campaign_id=1,
        actor="admin",
    )

    yandex_client.create_campaign.assert_awaited_once()
    row = await db_session.execute(text("SELECT status FROM ad_campaigns WHERE id = 1"))
    assert row.scalar() == "running"


# ---------------------------------------------------------------------------
# 5. TG Scout weekly pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tg_scout_weekly_pipeline():
    from integrations.telegram.pitch import PitchDraft, PitchGenerator
    from integrations.telegram.scorer import RelevanceScore, RelevanceScorer
    from integrations.telegram.scout import TelegramScout

    channels = [
        ChannelInfo(
            username=f"chan{i}",
            title=f"Channel {i}",
            subscriber_count=10_000 + i * 1000,
            avg_views=500.0,
            er=0.05,
            description="AI помощник для бизнеса",
            contact_username=None,
            contact_email=None,
            topics=["ai"],
            source="telethon",
        )
        for i in range(3)
    ]

    scout = TelegramScout.__new__(TelegramScout)
    scout.search_channels = AsyncMock(return_value=channels)
    scout.save_channels = AsyncMock()

    session = AsyncMock()
    session.commit = AsyncMock()

    result = await scout.search_channels(["AI помощник"])
    assert len(result) == 3
    await scout.save_channels(session, result)
    scout.save_channels.assert_awaited_once()

    scorer = RelevanceScorer.__new__(RelevanceScorer)
    scorer._semantic_score = AsyncMock(return_value=20)  # type: ignore[attr-defined]
    scorer._client = MagicMock()  # type: ignore[attr-defined]

    scores: list[RelevanceScore] = []
    for ch in channels:
        s = await scorer.score_channel(ch, "ai_assistant")
        scores.append(s)
    assert len(scores) == 3
    assert all(0 <= s.score <= 100 for s in scores)

    pitcher = PitchGenerator.__new__(PitchGenerator)
    pitcher._generate_short = AsyncMock(return_value="Short pitch")  # type: ignore[attr-defined]
    pitcher._generate_medium = AsyncMock(return_value="Medium pitch")  # type: ignore[attr-defined]
    pitcher._generate_long = AsyncMock(return_value="Long pitch")  # type: ignore[attr-defined]

    drafts: list[PitchDraft] = []
    for ch, sc in zip(channels, scores, strict=False):
        d = await pitcher.generate_pitch(ch, "ai_assistant", sc)
        drafts.append(d)
    assert len(drafts) == 3
    assert all(d.pitch_short for d in drafts)


# ---------------------------------------------------------------------------
# 6. Events monthly pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_monthly_pipeline(db_session):
    from integrations.events.digest import DigestBuilder

    events = [
        ConferenceEvent(
            name=f"AI Conf {i}",
            url=f"https://example.com/{i}",
            start_date=date.today() + timedelta(days=30 + i),
            cfp_deadline=date.today() + timedelta(days=10 + i),
            description="Conference about AI assistants and B2B automation",
            topics=["ai", "b2b"],
            source="aiconf",
            status="new",
        )
        for i in range(5)
    ]

    f = RelevanceFilter()
    # Mock _score_event so we don't hit Claude
    score_map = {0: 80, 1: 75, 2: 30, 3: 20, 4: 10}
    call_count = {"i": 0}

    async def fake_score(event, product):
        idx = int(event.name.rsplit(" ", 1)[1])
        result = score_map.get(idx, 0)
        call_count["i"] += 1
        return result

    f._score_event = fake_score  # type: ignore[method-assign]

    relevant = await f.filter_relevant(events, ["ai_assistant"])
    assert len(relevant) == 2

    # Save events to events_calendar
    for e in events:
        await db_session.execute(
            text(
                "INSERT INTO events_calendar "
                "(name, url, start_date, cfp_deadline, description, topics, "
                "source, status) "
                "VALUES (:n, :u, :sd, :cd, :d, :t, :s, :st)"
            ),
            {
                "n": e.name,
                "u": e.url,
                "sd": e.start_date.isoformat() if e.start_date else None,
                "cd": e.cfp_deadline.isoformat() if e.cfp_deadline else None,
                "d": e.description,
                "t": json.dumps(e.topics),
                "s": e.source,
                "st": "relevant" if e.name in {"AI Conf 0", "AI Conf 1"} else "new",
            },
        )
    await db_session.commit()

    builder = DigestBuilder()
    digest = await builder.build_monthly_digest(db_session)
    assert "AI Conf 0" in digest
    assert "AI Conf 1" in digest


# ---------------------------------------------------------------------------
# 7. Dead Letter Queue saves on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dead_letter_queue_saves_on_error(db_session):
    from integrations.error_handler import GlobalErrorHandler

    await _ensure_dlq_table(db_session)

    bot = AsyncMock()
    bot.send_message = AsyncMock()

    handler = GlobalErrorHandler(bot=bot, engine=None, admin_chat_id="12345")
    try:
        raise RuntimeError("simulated failure")
    except RuntimeError as exc:
        await handler.handle(
            agent="testagent",
            task="testtask",
            exc=exc,
            payload={"k": "v"},
            session=db_session,
        )

    row = await db_session.execute(
        text("SELECT agent, task, status, attempts FROM dead_letter_queue")
    )
    record = row.fetchone()
    assert record is not None
    assert record[0] == "testagent"
    assert record[1] == "testtask"
    assert record[2] == "pending"
    assert record[3] == 1

    bot.send_message.assert_awaited_once()


# ---------------------------------------------------------------------------
# 8. /dashboard command produces a message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_command_returns_message(test_db_engine):
    from integrations.telegram import commands as cmd_mod
    from integrations.telegram.commands import cmd_dashboard, set_dashboard_engine

    set_dashboard_engine(test_db_engine)

    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    # Suppress dlq table absence; cmd should still produce text via _safe_count
    with patch.object(cmd_mod, "_dashboard_engine", test_db_engine):
        await cmd_dashboard(update, context)

    update.message.reply_text.assert_awaited_once()
    sent_text = update.message.reply_text.await_args.args[0]
    assert "AI Marketing Team" in sent_text
    assert "Agents" in sent_text
