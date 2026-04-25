"""Unit tests for Telegram publisher — Sprint 1 helpers + Sprint 2 publish_post."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

from integrations.content.models import ScheduledPost
from integrations.telegram.publisher import (
    notify_plan_approved,
    notify_plan_generated,
    notify_plan_rejected,
    notify_publish_error,
    publish_post,
    send_formatted_message,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_post(**kwargs) -> ScheduledPost:
    defaults = {
        "id": 1,
        "product_id": 1,
        "product_name": "TestProd",
        "platform": "telegram",
        "topic": "Test topic",
        "body": "Post body text",
        "scheduled_at": datetime(2026, 4, 27, 9, 0, 0, tzinfo=UTC),
        "status": "generated",
    }
    defaults.update(kwargs)
    return ScheduledPost(**defaults)


def _make_sent_message(message_id: int = 42) -> MagicMock:
    msg = MagicMock()
    msg.message_id = message_id
    return msg


# ---------------------------------------------------------------------------
# Sprint 1 helpers
# ---------------------------------------------------------------------------


class TestSendFormattedMessage:
    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock())
        result = await send_formatted_message(mock_telegram_bot, 123, "hello")
        assert result is True
        mock_telegram_bot.send_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_false_after_all_retries_fail(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(side_effect=Exception("network error"))
        result = await send_formatted_message(mock_telegram_bot, 123, "hello", retry_count=3)
        assert result is False
        assert mock_telegram_bot.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(side_effect=[Exception("fail"), MagicMock()])
        result = await send_formatted_message(mock_telegram_bot, 123, "hello", retry_count=3)
        assert result is True
        assert mock_telegram_bot.send_message.await_count == 2


class TestNotifyHelpers:
    @pytest.mark.asyncio
    async def test_notify_plan_generated(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock())
        result = await notify_plan_generated(mock_telegram_bot, 123, "summary text")
        assert result is True
        call_text = mock_telegram_bot.send_message.call_args.kwargs["text"]
        assert "summary text" in call_text

    @pytest.mark.asyncio
    async def test_notify_plan_approved(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock())
        result = await notify_plan_approved(mock_telegram_bot, 123, plan_id=7)
        assert result is True
        call_text = mock_telegram_bot.send_message.call_args.kwargs["text"]
        assert "7" in call_text

    @pytest.mark.asyncio
    async def test_notify_plan_rejected(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock())
        result = await notify_plan_rejected(mock_telegram_bot, 123, plan_id=3, reason="too short")
        assert result is True
        call_text = mock_telegram_bot.send_message.call_args.kwargs["text"]
        assert "too short" in call_text


# ---------------------------------------------------------------------------
# Sprint 2 — publish_post
# ---------------------------------------------------------------------------


class TestPublishPost:
    @pytest.mark.asyncio
    async def test_success_returns_true_and_message_id(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=_make_sent_message(message_id=77))
        post = _make_post()
        success, msg_id = await publish_post(mock_telegram_bot, "@channel", post)
        assert success is True
        assert msg_id == 77

    @pytest.mark.asyncio
    async def test_retries_three_times_on_telegram_error(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(side_effect=TelegramError("500 server error"))
        post = _make_post()
        with patch("integrations.telegram.publisher.asyncio.sleep", new=AsyncMock()):
            success, msg_id = await publish_post(mock_telegram_bot, "@channel", post)
        assert success is False
        assert msg_id is None
        assert mock_telegram_bot.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_succeeds_on_third_attempt(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(
            side_effect=[
                TelegramError("503"),
                TelegramError("503"),
                _make_sent_message(message_id=99),
            ]
        )
        post = _make_post()
        with patch("integrations.telegram.publisher.asyncio.sleep", new=AsyncMock()):
            success, msg_id = await publish_post(mock_telegram_bot, "@channel", post)
        assert success is True
        assert msg_id == 99
        assert mock_telegram_bot.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_on_4xx_error(self, mock_telegram_bot):
        """4xx errors (client errors) must not be retried."""
        mock_telegram_bot.send_message = AsyncMock(side_effect=TelegramError("400 Bad Request"))
        post = _make_post()
        with patch("integrations.telegram.publisher.asyncio.sleep", new=AsyncMock()):
            success, msg_id = await publish_post(mock_telegram_bot, "@channel", post)
        assert success is False
        assert mock_telegram_bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self, mock_telegram_bot):
        """Sleep durations should be 1 s then 2 s between the three attempts."""
        mock_telegram_bot.send_message = AsyncMock(side_effect=TelegramError("503"))
        sleep_calls: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        post = _make_post()
        with patch("integrations.telegram.publisher.asyncio.sleep", new=_fake_sleep):
            await publish_post(mock_telegram_bot, "@channel", post)

        # 3 attempts → 2 sleeps (after attempt 1 and 2)
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0

    @pytest.mark.asyncio
    async def test_sends_post_body_as_text(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=_make_sent_message())
        post = _make_post(body="Особый текст поста")
        await publish_post(mock_telegram_bot, "@channel", post)
        call_kwargs = mock_telegram_bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "Особый текст поста"

    @pytest.mark.asyncio
    async def test_sends_to_correct_channel(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=_make_sent_message())
        post = _make_post()
        await publish_post(mock_telegram_bot, "@my_channel", post)
        call_kwargs = mock_telegram_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == "@my_channel"


# ---------------------------------------------------------------------------
# notify_publish_error
# ---------------------------------------------------------------------------


class TestNotifyPublishError:
    @pytest.mark.asyncio
    async def test_sends_alert_to_admin(self, mock_telegram_bot):
        mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock())
        post = _make_post(id=5, product_name="MyProd")
        await notify_publish_error(mock_telegram_bot, 999, post)
        call_kwargs = mock_telegram_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 999
        assert "MyProd" in call_kwargs["text"]
        assert "5" in call_kwargs["text"]
