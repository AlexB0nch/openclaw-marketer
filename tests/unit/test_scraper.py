"""Unit tests for integrations/events/scraper.py."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test_dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "@test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("N8N_WEBHOOK_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test")

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from sqlalchemy import text

from integrations.events.scraper import ConferenceEvent, ConferenceScraper, parse_date, save_events


def test_parse_date_formats() -> None:
    assert parse_date("15 мая 2026") == date(2026, 5, 15)
    assert parse_date("15.05.2026") == date(2026, 5, 15)
    assert parse_date("май 2026") == date(2026, 5, 1)
    assert parse_date("invalid") is None


@pytest.mark.asyncio
async def test_scrape_all_returns_list() -> None:
    html_stub = b"<html><body><h1>Test Conference</h1><p>2026</p></body></html>"

    mock_response = AsyncMock()
    mock_response.text = AsyncMock(return_value=html_stub.decode())
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.closed = False
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.close = AsyncMock()

    scraper = ConferenceScraper()
    with patch("aiohttp.ClientSession", return_value=mock_session):
        scraper._session = mock_session
        result = await scraper.scrape_all()

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_scraper_graceful_degradation() -> None:
    scraper = ConferenceScraper()

    async def raise_error() -> list[ConferenceEvent]:
        raise aiohttp.ClientError("connection failed")

    with patch.object(scraper, "_scrape_aiconf", side_effect=aiohttp.ClientError("fail")):
        html_stub = "<html><body><h1>Test</h1></body></html>"
        mock_response = AsyncMock()
        mock_response.text = AsyncMock(return_value=html_stub)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.close = AsyncMock()

        scraper._session = mock_session

        result = await scraper.scrape_all()
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_save_events_upsert(db_session) -> None:
    await db_session.execute(
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
    await db_session.commit()

    event = ConferenceEvent(
        name="Test Conf",
        url="https://example.com",
        start_date=date(2026, 6, 1),
        source="test",
    )

    await save_events(db_session, [event])
    await save_events(db_session, [event])

    result = await db_session.execute(
        text("SELECT COUNT(*) FROM events_calendar WHERE name = 'Test Conf'")
    )
    count = result.scalar()
    assert count == 1
