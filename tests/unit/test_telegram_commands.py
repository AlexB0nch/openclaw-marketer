"""Unit tests for Telegram command handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User

from integrations.telegram.commands import (
    button_callback_approve,
    button_callback_reject,
    cmd_approve,
    cmd_plan,
    cmd_reject,
    cmd_report,
    cmd_status,
)


@pytest.fixture
def mock_update():
    """Create mock Telegram update."""
    user = User(id=123, is_bot=False, first_name="Admin")
    chat = Chat(id=12345, type="private")
    message = MagicMock(spec=Message)
    message.reply_text = AsyncMock()
    message.chat = chat
    message.from_user = user

    update = MagicMock(spec=Update)
    update.message = message
    update.effective_user = user
    return update


@pytest.fixture
def mock_context():
    """Create mock Telegram context."""
    context = MagicMock()
    context.args = []
    return context


class TestStatusCommand:
    """Test /status command handler."""

    @pytest.mark.asyncio
    async def test_cmd_status_sends_message(self, mock_update, mock_context):
        """Test status command sends a message."""
        await cmd_status(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "статус" in call_args[0][0].lower() or "Текущий" in call_args[0][0]


class TestPlanCommand:
    """Test /plan command handler."""

    @pytest.mark.asyncio
    async def test_cmd_plan_sends_plan(self, mock_update, mock_context):
        """Test plan command sends plan with keyboard."""
        await cmd_plan(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()


class TestApproveCommand:
    """Test /approve command handler."""

    @pytest.mark.asyncio
    async def test_cmd_approve_without_args(self, mock_update, mock_context):
        """Test approve command without plan ID."""
        mock_context.args = []
        await cmd_approve(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Использование" in call_args[0][0] or "usage" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_cmd_approve_with_plan_id(self, mock_update, mock_context):
        """Test approve command with valid plan ID."""
        mock_context.args = ["42"]
        await cmd_approve(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "42" in call_args[0][0]


class TestRejectCommand:
    """Test /reject command handler."""

    @pytest.mark.asyncio
    async def test_cmd_reject_without_args(self, mock_update, mock_context):
        """Test reject command without plan ID."""
        mock_context.args = []
        await cmd_reject(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_cmd_reject_with_plan_id_and_reason(self, mock_update, mock_context):
        """Test reject command with plan ID and reason."""
        mock_context.args = ["42", "budget", "too", "high"]
        await cmd_reject(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "42" in call_args[0][0]
        assert "budget" in call_args[0][0].lower()


class TestReportCommand:
    """Test /report command handler."""

    @pytest.mark.asyncio
    async def test_cmd_report_sends_digest(self, mock_update, mock_context):
        """Test report command sends weekly digest."""
        await cmd_report(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args
        assert "Отчет" in call_args[0][0] or "отчет" in call_args[0][0]


class TestButtonCallbacks:
    """Test inline button callback handlers."""

    @pytest.mark.asyncio
    async def test_button_approve_callback(self):
        """Test approve button callback."""
        callback_query = MagicMock()
        callback_query.answer = AsyncMock()
        callback_query.edit_message_text = AsyncMock()
        callback_query.message = MagicMock()
        callback_query.message.text = "Test plan"

        update = MagicMock(spec=Update)
        update.callback_query = callback_query

        context = MagicMock()

        await button_callback_approve(update, context)

        callback_query.answer.assert_called_once()
        callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_button_reject_callback(self):
        """Test reject button callback."""
        callback_query = MagicMock()
        callback_query.answer = AsyncMock()
        callback_query.edit_message_text = AsyncMock()
        callback_query.message = MagicMock()
        callback_query.message.text = "Test plan"

        update = MagicMock(spec=Update)
        update.callback_query = callback_query

        context = MagicMock()

        await button_callback_reject(update, context)

        callback_query.answer.assert_called_once()
        callback_query.edit_message_text.assert_called_once()
