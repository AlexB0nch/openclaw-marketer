"""Unit tests for integrations/telegram/scout.py."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from integrations.telegram.scout import ChannelInfo, TelegramScout


def _make_channel(**kwargs) -> ChannelInfo:
    defaults = {
        "username": "testchan",
        "title": "Test Channel",
        "subscriber_count": 10_000,
        "avg_views": 500.0,
        "er": 0.05,
        "description": "Some bio",
        "contact_username": None,
        "contact_email": None,
        "topics": ["tech"],
        "source": "telethon",
    }
    defaults.update(kwargs)
    return ChannelInfo(**defaults)


# ── parse_contact ────────────────────────────────────────────────────────────


def test_parse_contact_extracts_username():
    user, email = TelegramScout.parse_contact("Contact @myuser for info")
    assert user == "myuser"
    assert email is None


def test_parse_contact_extracts_email():
    user, email = TelegramScout.parse_contact("email: hello@example.com")
    assert user is None
    assert email == "hello@example.com"


def test_parse_contact_extracts_both():
    user, email = TelegramScout.parse_contact("Write @support or support@corp.io")
    assert user == "support"
    assert email == "support@corp.io"


def test_parse_contact_empty():
    user, email = TelegramScout.parse_contact("")
    assert user is None
    assert email is None


def test_parse_contact_no_match():
    user, email = TelegramScout.parse_contact("Just some random text without contacts")
    assert user is None
    assert email is None


# ── search_channels ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_channels_filters_by_min_subscribers():
    scout = TelegramScout.__new__(TelegramScout)
    channels = await _mock_search_returns_channels(scout, min_subscribers=5000)
    for ch in channels:
        assert ch.subscriber_count >= 5000


async def _mock_search_returns_channels(scout, min_subscribers):
    """Helper: return pre-built ChannelInfo filtered by min_subscribers."""
    channels = [
        ChannelInfo(
            username="bigchannel",
            title="Big Channel",
            subscriber_count=10_000,
            avg_views=500.0,
            er=0.05,
            description="",
            contact_username=None,
            contact_email=None,
            topics=["test"],
            source="telethon",
        )
    ]
    return [ch for ch in channels if ch.subscriber_count >= min_subscribers]


# ── save_channels ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_channels_upsert():
    scout = TelegramScout.__new__(TelegramScout)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    channels = [_make_channel(username="chan1"), _make_channel(username="chan2")]
    await scout.save_channels(mock_session, channels)

    assert mock_session.execute.call_count == 2
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_channels_empty_list():
    scout = TelegramScout.__new__(TelegramScout)
    mock_session = AsyncMock()
    await scout.save_channels(mock_session, [])
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_save_channels_sql_contains_on_conflict():
    scout = TelegramScout.__new__(TelegramScout)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    await scout.save_channels(mock_session, [_make_channel()])

    call_args = mock_session.execute.call_args
    sql_text = str(call_args[0][0])
    assert "ON CONFLICT" in sql_text.upper()
