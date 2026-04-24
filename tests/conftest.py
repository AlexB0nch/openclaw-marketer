"""Pytest configuration and shared fixtures."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from telegram import Bot

from app.config import Settings


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_db_engine():
    """Create in-memory SQLite database for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        # Create minimal schema for testing
        await conn.execute("CREATE TABLE content_plans (id INTEGER PRIMARY KEY)")
        await conn.execute("CREATE TABLE plan_approvals (id INTEGER PRIMARY KEY)")

    return engine


@pytest_asyncio.fixture
async def db_session(test_db_engine):
    """Create database session for tests."""
    async_session = sessionmaker(test_db_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session


@pytest.fixture
def mock_telegram_bot():
    """Create mock Telegram bot."""
    bot = AsyncMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_document = AsyncMock()
    return bot


@pytest.fixture
def test_settings():
    """Create test settings."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        telegram_bot_token="test_token",
        telegram_admin_chat_id="12345",
        anthropic_api_key="test_key",
    )


@pytest.fixture
def mock_anthropic_client():
    """Create mock Anthropic client."""
    client = MagicMock()
    return client
