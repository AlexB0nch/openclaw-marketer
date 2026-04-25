"""Unit tests for integrations/analytics/collector.py."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.analytics.collector import (
    GoogleAnalyticsCollector,
    TelegramMetricsCollector,
    YandexDirectMetricsCollector,
    _upsert_metrics,
)
from integrations.analytics.models import MetricsRecord

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_db(db_session):
    """Seed a product, campaign, and published scheduled_post."""
    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (1, 'TestProduct', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (1, 1, 'Test Campaign', 'telegram', 'active')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO scheduled_posts "
            "(id, product_id, product_name, platform, topic, body, "
            " scheduled_at, status, published_at, telegram_message_id) "
            "VALUES (1, 1, 'TestProduct', 'telegram', 'Topic', 'Body', "
            "        '2026-04-24 09:00', 'published', '2026-04-24 09:01', 999)"
        )
    )
    await db_session.commit()
    return db_session


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_aiohttp_mock(json_data=None, text_data=None, status=200):
    """Build a nested AsyncMock that mimics aiohttp.ClientSession context manager."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data or {})
    mock_resp.text = AsyncMock(return_value=text_data or "")
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    return mock_session


# ── TelegramMetricsCollector ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_collect_post_metrics(seeded_db, test_settings):
    """Collector saves views from getChatMemberCount into post_metrics."""
    mock_session = _make_aiohttp_mock(json_data={"ok": True, "result": 1500})

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_session):
        collector = TelegramMetricsCollector(test_settings)
        record = await collector.collect_post_metrics(
            seeded_db,
            post_id=1,
            telegram_message_id=999,
            product_id=1,
            date_collected=date(2026, 4, 24),
        )

    assert record is not None
    assert record.source == "telegram"
    assert record.views == 1500
    assert record.impressions == 1500
    assert record.post_id == 1

    # Verify persisted to post_metrics
    row = (
        await seeded_db.execute(text("SELECT views FROM post_metrics WHERE post_id = 1"))
    ).fetchone()
    assert row is not None
    assert row[0] == 1500


@pytest.mark.asyncio
async def test_telegram_collect_api_failure_returns_none(seeded_db, test_settings):
    """Collector returns None and does not crash on API error."""
    mock_session = _make_aiohttp_mock(json_data={"ok": False})

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_session):
        collector = TelegramMetricsCollector(test_settings)
        record = await collector.collect_post_metrics(
            seeded_db,
            post_id=1,
            telegram_message_id=999,
            product_id=1,
            date_collected=date(2026, 4, 24),
        )

    assert record is None


@pytest.mark.asyncio
async def test_telegram_collect_all_recent(seeded_db, test_settings):
    """collect_all_recent processes all recently published posts."""
    mock_session = _make_aiohttp_mock(json_data={"ok": True, "result": 800})

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_session):
        collector = TelegramMetricsCollector(test_settings)
        records = await collector.collect_all_recent(seeded_db, days=30)

    assert len(records) == 1
    assert records[0].views == 800


# ── YandexDirectMetricsCollector ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_yandex_direct_collect(seeded_db, test_settings):
    """Collector parses TSV response and upserts into metrics table."""
    tsv = (
        "reportName\tCampaign\n"
        "Date\tImpressions\tClicks\tCost\tCtr\tConversions\n"
        "2026-04-23\t10000\t250\t1500000000\t2.5\t12\n"
        "2026-04-24\t9500\t220\t1400000000\t2.32\t10\n"
    )
    mock_session = _make_aiohttp_mock(text_data=tsv)

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_session):
        collector = YandexDirectMetricsCollector(test_settings)
        records = await collector.collect(
            seeded_db,
            campaign_id=1,
            product_id=1,
            date_from=date(2026, 4, 23),
            date_to=date(2026, 4, 24),
        )

    assert len(records) == 2
    assert records[0].source == "yandex_direct"
    assert records[0].impressions == 10000
    assert records[0].clicks == 250
    # 1_500_000_000 microroubles = 1500 RUB
    assert records[0].spend_rub == pytest.approx(1500.0)
    assert records[0].conversions == 12

    # Verify upserted into metrics table
    row = (
        await seeded_db.execute(
            text("SELECT impressions FROM metrics WHERE campaign_id = 1 AND date = '2026-04-23'")
        )
    ).fetchone()
    assert row is not None
    assert row[0] == 10000


@pytest.mark.asyncio
async def test_yandex_direct_missing_token_skips(seeded_db, test_settings):
    """Returns empty list when token is not configured."""
    test_settings.yandex_direct_token = ""
    collector = YandexDirectMetricsCollector(test_settings)
    records = await collector.collect(
        seeded_db,
        campaign_id=1,
        product_id=1,
        date_from=date(2026, 4, 24),
        date_to=date(2026, 4, 24),
    )
    assert records == []


# ── GoogleAnalyticsCollector ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ga4_collect(seeded_db, test_settings):
    """Collector parses GA4 JSON response and upserts into metrics table."""
    token_json = {"access_token": "test_token"}
    ga4_json = {
        "rows": [
            {
                "dimensionValues": [{"value": "20260424"}],
                "metricValues": [{"value": "500"}, {"value": "30.5"}],
            }
        ]
    }

    call_count = 0

    class _MockResp:
        def __init__(self, data):
            self._data = data
            self.status = 200

        async def json(self):
            return self._data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class _MockSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def post(self, url, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call = token exchange, second = report
            return _MockResp(token_json if call_count == 1 else ga4_json)

    with patch(
        "integrations.analytics.collector.aiohttp.ClientSession", return_value=_MockSession()
    ):
        collector = GoogleAnalyticsCollector(test_settings)
        records = await collector.collect(
            seeded_db,
            campaign_id=1,
            product_id=1,
            date_from=date(2026, 4, 24),
            date_to=date(2026, 4, 24),
        )

    assert len(records) == 1
    assert records[0].source == "google_analytics"
    assert records[0].impressions == 500
    assert records[0].conversions == 30


@pytest.mark.asyncio
async def test_ga4_missing_customer_id_skips(seeded_db, test_settings):
    """Returns empty list when GOOGLE_ADS_CUSTOMER_ID is not set."""
    test_settings.google_ads_customer_id = ""
    collector = GoogleAnalyticsCollector(test_settings)
    records = await collector.collect(
        seeded_db,
        campaign_id=1,
        product_id=1,
        date_from=date(2026, 4, 24),
        date_to=date(2026, 4, 24),
    )
    assert records == []


# ── _upsert_metrics helper ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_metrics_idempotent(seeded_db):
    """Second upsert for same campaign+date replaces first row."""
    record = MetricsRecord(
        source="yandex_direct",
        product_id=1,
        campaign_id=1,
        date=date(2026, 4, 20),
        impressions=100,
        clicks=10,
        spend_rub=500.0,
        conversions=5,
    )
    await _upsert_metrics(seeded_db, record)

    record.impressions = 200
    await _upsert_metrics(seeded_db, record)

    rows = (
        await seeded_db.execute(
            text("SELECT impressions FROM metrics WHERE campaign_id = 1 AND date = '2026-04-20'")
        )
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 200
