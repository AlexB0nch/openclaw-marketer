"""Unit tests for integrations/events/tracker.py."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test_dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "@test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("N8N_WEBHOOK_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test")

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from integrations.events.scraper import ConferenceEvent
from integrations.events.tracker import DeadlineTracker


async def _ensure_tables(session) -> None:
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS events_calendar ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name TEXT NOT NULL,"
            "  url TEXT NOT NULL,"
            "  start_date TEXT,"
            "  cfp_deadline TEXT,"
            "  city TEXT,"
            "  is_online INTEGER NOT NULL DEFAULT 0,"
            "  audience_size INTEGER,"
            "  description TEXT NOT NULL DEFAULT '',"
            "  topics TEXT NOT NULL DEFAULT '[]',"
            "  source TEXT NOT NULL DEFAULT '',"
            "  status TEXT NOT NULL DEFAULT 'new',"
            "  created_at TEXT,"
            "  updated_at TEXT"
            ")"
        )
    )
    await session.execute(
        text(
            "CREATE TABLE IF NOT EXISTS events_abstracts ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_id INTEGER NOT NULL,"
            "  product TEXT NOT NULL,"
            "  abstract_text TEXT NOT NULL DEFAULT ''"
            ")"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_check_upcoming_deadlines_finds_events(db_session) -> None:
    await _ensure_tables(db_session)

    today = date.today()
    cfp = today + timedelta(days=7)

    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, cfp_deadline, status) "
            "VALUES (:name, :url, :cfp, :status)"
        ),
        {
            "name": "Upcoming Conf",
            "url": "https://example.com",
            "cfp": cfp.isoformat(),
            "status": "relevant",
        },
    )
    await db_session.commit()

    tracker = DeadlineTracker()
    events = await tracker.check_upcoming_deadlines(db_session)

    assert any(e.name == "Upcoming Conf" for e in events)


@pytest.mark.asyncio
async def test_check_upcoming_deadlines_excludes_past(db_session) -> None:
    await _ensure_tables(db_session)

    today = date.today()
    cfp = today - timedelta(days=1)

    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, cfp_deadline, status) "
            "VALUES (:name, :url, :cfp, :status)"
        ),
        {
            "name": "Past Deadline Conf",
            "url": "https://example.com",
            "cfp": cfp.isoformat(),
            "status": "relevant",
        },
    )
    await db_session.commit()

    tracker = DeadlineTracker()
    events = await tracker.check_upcoming_deadlines(db_session)

    assert not any(e.name == "Past Deadline Conf" for e in events)


@pytest.mark.asyncio
async def test_generate_abstract_draft_calls_claude() -> None:
    import integrations.events.tracker as tracker_module

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Черновик заявки конференции...")]

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_message)

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    original_client = tracker_module._client
    try:
        tracker_module._client = mock_client
        tracker = DeadlineTracker()
        event = ConferenceEvent(name="Test Conf", url="https://example.com", description="Test")
        result = await tracker.generate_abstract_draft(event, "ai_assistant")
        assert isinstance(result, str)
        assert len(result) > 0
    finally:
        tracker_module._client = original_client


@pytest.mark.asyncio
async def test_generate_abstract_draft_returns_empty_on_failure() -> None:
    import integrations.events.tracker as tracker_module

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(side_effect=Exception("Claude API error"))

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    original_client = tracker_module._client
    try:
        tracker_module._client = mock_client
        tracker = DeadlineTracker()
        event = ConferenceEvent(name="Test Conf", url="https://example.com")
        result = await tracker.generate_abstract_draft(event, "ai_assistant")
        assert result == ""
    finally:
        tracker_module._client = original_client


@pytest.mark.asyncio
async def test_save_abstract_upsert(db_session) -> None:
    await _ensure_tables(db_session)

    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, status) "
            "VALUES ('Conf', 'https://example.com', 'relevant')"
        )
    )
    await db_session.commit()

    result = await db_session.execute(text("SELECT id FROM events_calendar WHERE name = 'Conf'"))
    event_id = result.scalar()

    tracker = DeadlineTracker()
    await tracker.save_abstract(db_session, event_id, "ai_assistant", "First draft")
    await tracker.save_abstract(db_session, event_id, "ai_assistant", "Updated draft")

    count_result = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM events_abstracts "
            "WHERE event_id = :event_id AND product = 'ai_assistant'"
        ),
        {"event_id": event_id},
    )
    count = count_result.scalar()
    assert count == 1

    text_result = await db_session.execute(
        text(
            "SELECT abstract_text FROM events_abstracts "
            "WHERE event_id = :event_id AND product = 'ai_assistant'"
        ),
        {"event_id": event_id},
    )
    abstract_text = text_result.scalar()
    assert abstract_text == "Updated draft"
