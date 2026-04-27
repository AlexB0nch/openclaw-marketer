"""Unit tests for integrations/events/digest.py."""

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

import pytest
from sqlalchemy import text

from integrations.events.digest import DigestBuilder


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
            "CREATE TABLE IF NOT EXISTS events_applications ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  event_id INTEGER NOT NULL,"
            "  product TEXT NOT NULL,"
            "  action TEXT NOT NULL"
            ")"
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_build_monthly_digest_contains_header(db_session) -> None:
    await _ensure_tables(db_session)

    today = date.today()
    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, start_date, status) "
            "VALUES (:name, :url, :start_date, 'relevant')"
        ),
        {
            "name": "Relevant Conf",
            "url": "https://example.com",
            "start_date": (today + timedelta(days=30)).isoformat(),
        },
    )
    await db_session.commit()

    builder = DigestBuilder()
    result = await builder.build_monthly_digest(db_session)

    assert isinstance(result, str)
    assert "📅" in result


@pytest.mark.asyncio
async def test_build_monthly_digest_empty(db_session) -> None:
    await _ensure_tables(db_session)

    builder = DigestBuilder()
    result = await builder.build_monthly_digest(db_session)

    assert isinstance(result, str)
    assert "📅" in result


@pytest.mark.asyncio
async def test_handle_skip_callback_sets_status(db_session) -> None:
    await _ensure_tables(db_session)

    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, status) "
            "VALUES ('Skip Conf', 'https://example.com', 'relevant')"
        )
    )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT id FROM events_calendar WHERE name = 'Skip Conf'")
    )
    event_id = result.scalar()

    builder = DigestBuilder()
    await builder.handle_skip_callback(db_session, f"events_skip:{event_id}")

    status_result = await db_session.execute(
        text("SELECT status FROM events_calendar WHERE id = :id"),
        {"id": event_id},
    )
    status = status_result.scalar()
    assert status == "skipped"


@pytest.mark.asyncio
async def test_send_monthly_digest_calls_bot(db_session, mock_telegram_bot) -> None:
    await _ensure_tables(db_session)

    today = date.today()
    await db_session.execute(
        text(
            "INSERT INTO events_calendar (name, url, start_date, cfp_deadline, status) "
            "VALUES (:name, :url, :start_date, :cfp_deadline, 'relevant')"
        ),
        {
            "name": "Send Test Conf",
            "url": "https://example.com",
            "start_date": (today + timedelta(days=60)).isoformat(),
            "cfp_deadline": (today + timedelta(days=20)).isoformat(),
        },
    )
    await db_session.commit()

    builder = DigestBuilder()
    await builder.send_monthly_digest(db_session, mock_telegram_bot)

    assert mock_telegram_bot.send_message.called
