"""Pytest configuration and shared fixtures."""

import asyncio
import os

# Set dummy env vars before app imports (mirrors CI environment)
os.environ.setdefault("ANTHROPIC_API_KEY", "test_dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("N8N_WEBHOOK_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test_dummy")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from telegram import Bot  # noqa: E402

from app.config import Settings  # noqa: E402


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
        await conn.execute(text("CREATE TABLE content_plans (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("CREATE TABLE plan_approvals (id INTEGER PRIMARY KEY)"))
        await conn.execute(
            text(
                "CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                "description TEXT, url TEXT, active INTEGER NOT NULL DEFAULT 1, "
                "created_at TIMESTAMP, updated_at TIMESTAMP)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE campaigns (id INTEGER PRIMARY KEY, product_id INTEGER, "
                "name TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft')"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE metrics (id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL, "
                "date TEXT NOT NULL, impressions INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0, "
                "spend_rub REAL DEFAULT 0)"
            )
        )

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
    """Create test settings with dummy values (mirrors CI env)."""
    return Settings(
        anthropic_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_admin_chat_id="12345",
        postgres_user="test",
        postgres_password="test",
        n8n_webhook_url="http://localhost:5678",
        n8n_api_key="test_dummy",
    )


@pytest.fixture
def mock_anthropic_client():
    """Create mock Anthropic client."""
    return MagicMock()
