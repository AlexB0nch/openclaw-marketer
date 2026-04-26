"""Unit tests for integrations/telegram/outreach.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.telegram.outreach import ChannelWithPitch, OutreachManager
from integrations.telegram.pitch import PitchDraft
from integrations.telegram.scout import ChannelInfo


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.telegram_admin_chat_id = "123456"
    return s


def _make_channel(username: str = "testchan") -> ChannelInfo:
    return ChannelInfo(
        username=username,
        title=f"Title {username}",
        subscriber_count=10_000,
        avg_views=500.0,
        er=0.05,
        description="desc",
        contact_username="contact",
        contact_email=None,
        topics=["tech"],
        source="telethon",
    )


def _make_pitch(username: str = "testchan") -> PitchDraft:
    return PitchDraft(
        channel_username=username,
        product="ai_assistant",
        pitch_short="Short pitch text here",
        pitch_medium="Medium pitch text " * 20,
        pitch_long="Long pitch text " * 60,
        status="pending_approval",
    )


def _make_cwp(username: str = "testchan", score: int = 80) -> ChannelWithPitch:
    return ChannelWithPitch(
        channel=_make_channel(username), pitch=_make_pitch(username), score=score
    )


def _build_mock_row(username: str, score: int = 80) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, key: {
        "username": username,
        "title": f"Title {username}",
        "subscriber_count": 10000,
        "avg_views": 500.0,
        "er": 0.05,
        "description": "desc",
        "contact_username": "contact",
        "contact_email": None,
        "topics": '["tech"]',
        "source": "telethon",
        "score": score,
        "product": "ai_assistant",
        "pitch_short": "Short pitch",
        "pitch_medium": "Medium pitch",
        "pitch_long": "Long pitch",
        "status": "pending_approval",
    }[key]
    return row


# ── build_weekly_digest ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_weekly_digest_returns_top_10():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()

    rows = [_build_mock_row(f"chan{i}", score=100 - i) for i in range(15)]
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = rows[:10]  # SQL already limits
    mock_session.execute = AsyncMock(return_value=mock_result)

    items = await manager.build_weekly_digest(mock_session, top_n=10)
    assert len(items) == 10


@pytest.mark.asyncio
async def test_build_weekly_digest_passes_top_n_to_sql():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    await manager.build_weekly_digest(mock_session, top_n=5)

    params = mock_session.execute.call_args[0][1]
    assert params["top_n"] == 5


# ── send_weekly_digest ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_weekly_digest_sends_empty_message_if_no_items():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()
    bot = AsyncMock()

    with patch.object(manager, "build_weekly_digest", return_value=[]):
        await manager.send_weekly_digest(mock_session, bot)

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args[1]["text"]
    assert "Нет" in text or "нет" in text


@pytest.mark.asyncio
async def test_send_weekly_digest_sends_card_per_channel():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()
    bot = AsyncMock()

    items = [_make_cwp(f"chan{i}") for i in range(3)]
    with patch.object(manager, "build_weekly_digest", return_value=items):
        await manager.send_weekly_digest(mock_session, bot)

    # Header + 3 cards = 4 calls
    assert bot.send_message.await_count == 4


# ── handle_send_callback (idempotency) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_send_pitch_idempotent():
    """If a 'sent' outreach row exists, DM is not sent again."""
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()

    existing_row = MagicMock()
    mock_check_result = MagicMock()
    mock_check_result.fetchone.return_value = existing_row
    mock_session.execute = AsyncMock(return_value=mock_check_result)

    telethon_client = AsyncMock()
    await manager.handle_send_callback(mock_session, telethon_client, "scout_send:testchan")

    telethon_client.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_send_callback_sends_dm_when_not_sent():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()

    # First execute: no existing outreach row
    no_row_result = MagicMock()
    no_row_result.fetchone.return_value = None
    # Second execute: pitch data
    pitch_row = MagicMock()
    pitch_row.__getitem__ = lambda self, k: {
        "pitch_short": "Short pitch",
        "contact_username": "owner",
    }[k]
    pitch_data = MagicMock()
    pitch_data.mappings.return_value.fetchone.return_value = pitch_row

    mock_session.execute = AsyncMock(side_effect=[no_row_result, pitch_data, AsyncMock()])
    mock_session.commit = AsyncMock()

    telethon_client = AsyncMock()
    await manager.handle_send_callback(mock_session, telethon_client, "scout_send:testchan")

    telethon_client.send_message.assert_awaited_once()


# ── handle_skip_callback ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_skip_callback_updates_status():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    await manager.handle_skip_callback(mock_session, "scout_skip:testchan")

    assert mock_session.execute.await_count == 2  # UPDATE + INSERT
    update_sql = str(mock_session.execute.call_args_list[0][0][0])
    assert "skipped_this_week" in update_sql
    mock_session.commit.assert_awaited_once()


# ── handle_show_callback ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_show_callback_sends_pitch_medium():
    manager = OutreachManager(_make_settings())
    mock_session = AsyncMock()

    pitch_row = MagicMock()
    pitch_row.__getitem__ = lambda self, k: {"pitch_medium": "This is the medium pitch text"}[k]
    result = MagicMock()
    result.mappings.return_value.fetchone.return_value = pitch_row
    mock_session.execute = AsyncMock(return_value=result)
    mock_session.commit = AsyncMock()

    bot = AsyncMock()
    await manager.handle_show_callback(mock_session, bot, "scout_show:testchan")

    bot.send_message.assert_awaited_once()
    text = bot.send_message.call_args[1]["text"]
    assert "medium pitch" in text
