"""Pytest configuration and shared fixtures."""

import asyncio
import os

# Set dummy env vars before app imports (mirrors CI environment)
os.environ.setdefault("ANTHROPIC_API_KEY", "test_dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "@test_channel")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("N8N_WEBHOOK_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test_dummy")
# Sprint 3 analytics (all optional — default empty string in Settings)
os.environ.setdefault("YANDEX_DIRECT_TOKEN", "test_yd_token")
os.environ.setdefault("YANDEX_DIRECT_LOGIN", "test_yd_login")
os.environ.setdefault("GOOGLE_ADS_CUSTOMER_ID", "123456789")
os.environ.setdefault("DAILY_SPEND_ALERT_THRESHOLD_RUB", "5000")
os.environ.setdefault("EVENTS_ENABLED", "true")

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
    """Create in-memory SQLite database for tests (Sprint 1 + Sprint 2 tables)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        # ── Sprint 0 / 1 tables ──────────────────────────────────────────
        await conn.execute(
            text(
                "CREATE TABLE products ("
                "  id INTEGER PRIMARY KEY,"
                "  name TEXT NOT NULL,"
                "  description TEXT,"
                "  url TEXT,"
                "  active INTEGER NOT NULL DEFAULT 1,"
                "  created_at TIMESTAMP,"
                "  updated_at TIMESTAMP"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE campaigns ("
                "  id INTEGER PRIMARY KEY,"
                "  product_id INTEGER,"
                "  name TEXT NOT NULL,"
                "  platform TEXT NOT NULL,"
                "  status TEXT NOT NULL DEFAULT 'draft'"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE metrics ("
                "  id INTEGER PRIMARY KEY,"
                "  campaign_id INTEGER NOT NULL,"
                "  date TEXT NOT NULL,"
                "  impressions INTEGER DEFAULT 0,"
                "  clicks INTEGER DEFAULT 0,"
                "  spend_rub REAL DEFAULT 0,"
                "  conversions INTEGER DEFAULT 0"
                ")"
            )
        )
        # content_plans: use TEXT instead of JSONB (portable; no JSONB in unit tests)
        await conn.execute(
            text(
                "CREATE TABLE content_plans ("
                "  id INTEGER PRIMARY KEY,"
                "  week_start_date TEXT,"
                "  week_end_date TEXT,"
                "  status TEXT NOT NULL DEFAULT 'pending_approval',"
                "  plan_json TEXT NOT NULL DEFAULT '{}',"
                "  created_by_agent TEXT NOT NULL DEFAULT 'strategist',"
                "  created_at TIMESTAMP,"
                "  approved_by_user TEXT,"
                "  approval_reason TEXT,"
                "  approved_at TIMESTAMP"
                ")"
            )
        )
        await conn.execute(text("CREATE TABLE plan_approvals (id INTEGER PRIMARY KEY)"))

        # ── Sprint 2 tables ──────────────────────────────────────────────
        # scheduled_posts: no CHECK constraints (SQLite ignores them anyway,
        # but omitting keeps DDL identical in spirit to Postgres without JSONB risk)
        await conn.execute(
            text(
                "CREATE TABLE scheduled_posts ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  content_plan_id INTEGER,"
                "  product_id INTEGER NOT NULL,"
                "  product_name TEXT NOT NULL DEFAULT '',"
                "  platform TEXT NOT NULL,"
                "  topic TEXT NOT NULL,"
                "  body TEXT NOT NULL DEFAULT '',"
                "  scheduled_at TEXT NOT NULL,"
                "  status TEXT NOT NULL DEFAULT 'pending',"
                "  published_at TEXT,"
                "  telegram_message_id INTEGER,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE habr_drafts ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  product_id INTEGER NOT NULL,"
                "  product_name TEXT NOT NULL DEFAULT '',"
                "  title TEXT NOT NULL,"
                "  brief TEXT NOT NULL,"
                "  body TEXT NOT NULL,"
                "  word_count INTEGER NOT NULL DEFAULT 0,"
                "  status TEXT NOT NULL DEFAULT 'draft',"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )

        # ── Sprint 3 tables ──────────────────────────────────────────────────
        await conn.execute(
            text(
                "CREATE TABLE post_metrics ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  post_id INTEGER,"
                "  product_id INTEGER,"
                "  date TEXT NOT NULL,"
                "  views INTEGER NOT NULL DEFAULT 0,"
                "  forwards INTEGER NOT NULL DEFAULT 0,"
                "  reactions INTEGER NOT NULL DEFAULT 0,"
                "  collected_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )
        # analytics_snapshots: TEXT instead of JSONB (SQLite-portable)
        await conn.execute(
            text(
                "CREATE TABLE analytics_snapshots ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  snapshot_date TEXT NOT NULL,"
                "  product_id INTEGER,"
                "  data TEXT NOT NULL,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )

        # ── Sprint 4 tables ──────────────────────────────────────────────────
        await conn.execute(
            text(
                "CREATE TABLE ad_campaigns ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  product_id INTEGER,"
                "  platform TEXT NOT NULL DEFAULT 'yandex',"
                "  status TEXT NOT NULL DEFAULT 'draft',"
                "  config_json TEXT NOT NULL DEFAULT '{}',"
                "  campaign_id_external TEXT,"
                "  budget_rub REAL NOT NULL DEFAULT 0.0,"
                "  spent_rub REAL NOT NULL DEFAULT 0.0,"
                "  created_at TEXT DEFAULT (datetime('now')),"
                "  launched_at TEXT,"
                "  completed_at TEXT"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE ad_variants ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  campaign_id INTEGER NOT NULL,"
                "  title1 TEXT NOT NULL,"
                "  title2 TEXT NOT NULL,"
                "  text TEXT NOT NULL,"
                "  display_url TEXT NOT NULL,"
                "  final_url TEXT NOT NULL,"
                "  clicks INTEGER NOT NULL DEFAULT 0,"
                "  impressions INTEGER NOT NULL DEFAULT 0,"
                "  ctr REAL NOT NULL DEFAULT 0.0,"
                "  status TEXT NOT NULL DEFAULT 'active'"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE ad_approvals ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  campaign_id INTEGER NOT NULL,"
                "  action TEXT NOT NULL,"
                "  actor TEXT NOT NULL,"
                "  reason TEXT,"
                "  timestamp TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE ad_daily_spend ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  campaign_id INTEGER NOT NULL,"
                "  date TEXT NOT NULL,"
                "  spend_rub REAL NOT NULL DEFAULT 0.0,"
                "  clicks INTEGER NOT NULL DEFAULT 0,"
                "  impressions INTEGER NOT NULL DEFAULT 0,"
                "  ctr REAL NOT NULL DEFAULT 0.0"
                ")"
            )
        )

        # ── Sprint 6 tables ──────────────────────────────────────────────────
        await conn.execute(
            text(
                "CREATE TABLE events_calendar ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  name TEXT NOT NULL,"
                "  url TEXT NOT NULL DEFAULT '',"
                "  start_date TEXT,"
                "  cfp_deadline TEXT,"
                "  city TEXT,"
                "  is_online INTEGER NOT NULL DEFAULT 0,"
                "  audience_size INTEGER,"
                "  description TEXT NOT NULL DEFAULT '',"
                "  topics TEXT NOT NULL DEFAULT '[]',"
                "  source TEXT NOT NULL DEFAULT '',"
                "  status TEXT NOT NULL DEFAULT 'new',"
                "  created_at TEXT DEFAULT (datetime('now')),"
                "  updated_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE events_abstracts ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  event_id INTEGER NOT NULL,"
                "  product TEXT NOT NULL,"
                "  abstract_text TEXT NOT NULL,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE events_applications ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  event_id INTEGER NOT NULL,"
                "  product TEXT NOT NULL,"
                "  action TEXT NOT NULL DEFAULT 'registered',"
                "  note TEXT,"
                "  created_at TEXT DEFAULT (datetime('now'))"
                ")"
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
    bot.send_photo = AsyncMock()
    return bot


@pytest.fixture
def test_settings():
    """Create test settings with dummy values (mirrors CI env)."""
    return Settings(
        anthropic_api_key="test_key",
        telegram_bot_token="test_token",
        telegram_admin_chat_id="12345",
        telegram_channel_id="@test_channel",
        postgres_user="test",
        postgres_password="test",
        n8n_webhook_url="http://localhost:5678",
        n8n_api_key="test_dummy",
    )


@pytest.fixture
def mock_anthropic_client():
    """Create mock Anthropic client."""
    return MagicMock()
