"""Unit tests for integrations/telegram/monitor.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from integrations.telegram.monitor import MentionMonitor


def _make_monitor(keywords=None, admin_chat_id=123456) -> MentionMonitor:
    client = MagicMock()
    return MentionMonitor(
        telethon_client=client,
        keywords=keywords or ["AI помощник", "фитнес"],
        admin_chat_id=admin_chat_id,
    )


def _make_event(msg_id: int, text: str, channel_username: str = "testchan") -> MagicMock:
    event = MagicMock()
    event.message.id = msg_id
    event.message.message = text

    chat = MagicMock()
    chat.username = channel_username
    event.get_chat = AsyncMock(return_value=chat)
    return event


# ── Deduplication ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deduplicates_same_message_id():
    monitor = _make_monitor()
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    event = _make_event(msg_id=42, text="AI помощник очень помогает")
    await monitor._handle_event(event, bot)
    await monitor._handle_event(event, bot)  # same message_id

    monitor.on_mention.assert_awaited_once()


@pytest.mark.asyncio
async def test_different_message_ids_both_trigger():
    monitor = _make_monitor()
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    await monitor._handle_event(_make_event(1, "AI помощник"), bot)
    await monitor._handle_event(_make_event(2, "AI помощник"), bot)

    assert monitor.on_mention.await_count == 2


# ── Keyword matching ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_alert_if_keyword_not_found():
    monitor = _make_monitor()
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    await monitor._handle_event(_make_event(10, "Обычный текст без ключевых слов"), bot)
    monitor.on_mention.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyword_matching_case_insensitive():
    monitor = _make_monitor(keywords=["AI помощник"])
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    await monitor._handle_event(_make_event(11, "ai помощник очень крутой"), bot)
    monitor.on_mention.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_matching_keyword_used():
    monitor = _make_monitor(keywords=["фитнес", "AI помощник"])
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    await monitor._handle_event(_make_event(12, "фитнес и AI помощник"), bot)

    call_kwargs = monitor.on_mention.call_args
    keyword_arg = call_kwargs[0][1]  # positional arg index 1
    assert keyword_arg == "фитнес"


# ── on_mention format ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_mention_sends_correct_format():
    monitor = _make_monitor(admin_chat_id=999)
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    event = _make_event(msg_id=55, text="Использую AI помощник каждый день")
    await monitor.on_mention(
        event, "AI помощник", "Использую AI помощник каждый день", "mychan", bot
    )

    bot.send_message.assert_awaited_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 999
    assert "AI помощник" in call_kwargs["text"]
    assert "@mychan" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_on_mention_message_truncated_at_200():
    monitor = _make_monitor(admin_chat_id=999)
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    long_text = "AI помощник " + "x" * 300
    event = _make_event(msg_id=56, text=long_text)
    await monitor.on_mention(event, "AI помощник", long_text, "chan", bot)

    call_kwargs = bot.send_message.call_args[1]
    # The displayed text should contain the truncated version
    assert len(call_kwargs["text"]) < len(long_text) + 200  # rough check


@pytest.mark.asyncio
async def test_on_mention_keyboard_has_three_buttons():
    from telegram import InlineKeyboardMarkup

    monitor = _make_monitor(admin_chat_id=1)
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    event = _make_event(msg_id=57, text="фитнес тренировки")
    await monitor.on_mention(event, "фитнес", "фитнес тренировки", "sportchan", bot)

    call_kwargs = bot.send_message.call_args[1]
    keyboard: InlineKeyboardMarkup = call_kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert len(buttons) == 3


# ── Handles missing chat username ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_event_uses_chat_id_if_no_username():
    monitor = _make_monitor()
    bot = AsyncMock()
    monitor.on_mention = AsyncMock()

    event = _make_event(msg_id=99, text="AI помощник")
    chat = MagicMock()
    chat.username = None
    chat.id = 777
    event.get_chat = AsyncMock(return_value=chat)

    await monitor._handle_event(event, bot)
    monitor.on_mention.assert_awaited_once()
    _, _, _, channel_username, _ = monitor.on_mention.call_args[0]
    assert channel_username == "777"
