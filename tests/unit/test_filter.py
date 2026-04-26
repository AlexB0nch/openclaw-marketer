"""Unit tests for integrations/events/filter.py."""

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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.events.filter import RelevanceFilter
from integrations.events.scraper import ConferenceEvent


def _make_event(
    name: str = "Test Conf",
    start_date: date | None = None,
    description: str = "",
    topics: list[str] | None = None,
) -> ConferenceEvent:
    return ConferenceEvent(
        name=name,
        url="https://example.com",
        start_date=start_date,
        description=description,
        topics=topics or [],
    )


def test_filter_removes_past_events() -> None:
    today = date.today()
    past_event = _make_event("Past Conf", start_date=today - timedelta(days=1))
    future_event = _make_event("Future Conf", start_date=today + timedelta(days=10))
    no_date_event = _make_event("No Date Conf", start_date=None)

    rf = RelevanceFilter(threshold=0)

    with patch.object(rf, "_score_event", new=AsyncMock(return_value=100)):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            rf.filter_relevant([past_event, future_event, no_date_event], ["product"])
        )

    names = [r.event.name for r in results]
    assert "Past Conf" not in names
    assert "Future Conf" in names
    assert "No Date Conf" in names


def test_filter_removes_duplicates() -> None:
    today = date.today()
    start = today + timedelta(days=5)
    event1 = _make_event("Same Conf", start_date=start)
    event2 = _make_event("Same Conf", start_date=start)

    rf = RelevanceFilter(threshold=0)

    with patch.object(rf, "_score_event", new=AsyncMock(return_value=100)):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            rf.filter_relevant([event1, event2], ["product"])
        )

    assert len(results) == 1


@pytest.mark.asyncio
async def test_score_event_returns_int() -> None:
    import integrations.events.filter as filter_module

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="75")]

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(return_value=mock_message)

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    original_client = filter_module._client
    try:
        filter_module._client = mock_client
        rf = RelevanceFilter()
        event = _make_event("Test Conf")
        score = await rf._score_event(event, "some_product")
        assert score == 75
    finally:
        filter_module._client = original_client


@pytest.mark.asyncio
async def test_score_event_returns_zero_on_failure() -> None:
    import integrations.events.filter as filter_module

    mock_messages = MagicMock()
    mock_messages.create = AsyncMock(side_effect=Exception("API error"))

    mock_client = MagicMock()
    mock_client.messages = mock_messages

    original_client = filter_module._client
    try:
        filter_module._client = mock_client
        rf = RelevanceFilter()
        event = _make_event("Test Conf")
        score = await rf._score_event(event, "some_product")
        assert score == 0
    finally:
        filter_module._client = original_client


def test_filter_relevant_threshold() -> None:
    today = date.today()
    future_date = today + timedelta(days=10)
    event_low = _make_event("Low Score Conf", start_date=future_date)
    event_high = _make_event("High Score Conf", start_date=future_date)

    rf = RelevanceFilter(threshold=50)

    async def mock_score(event: ConferenceEvent, product: str) -> int:
        if event.name == "Low Score Conf":
            return 30
        return 60

    with patch.object(rf, "_score_event", side_effect=mock_score):
        import asyncio

        results = asyncio.get_event_loop().run_until_complete(
            rf.filter_relevant([event_low, event_high], ["product"])
        )

    names = [r.event.name for r in results]
    assert "Low Score Conf" not in names
    assert "High Score Conf" in names
