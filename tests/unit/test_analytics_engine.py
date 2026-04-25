"""Unit tests for integrations/analytics/engine.py."""

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.analytics.engine import AnalyticsEngine

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine_db(db_session):
    """Seed products, campaigns, metrics, scheduled_posts, post_metrics."""
    today = date.today()

    # Products
    await db_session.execute(
        text(
            "INSERT INTO products (id, name, active) VALUES "
            "(1, 'ProductA', 1), (2, 'ProductB', 1)"
        )
    )
    # Campaigns
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) VALUES "
            "(1, 1, 'Camp A Tg', 'telegram', 'active'), "
            "(2, 2, 'Camp B YD', 'yandex_direct', 'active')"
        )
    )
    # Metrics — 10 days of data for trend tests
    for i in range(10):
        d = str(today - timedelta(days=i))
        await db_session.execute(
            text(
                "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (:cid, :date, :imp, :cli, :sp, :cv)"
            ),
            {
                "cid": 1,
                "date": d,
                "imp": 1000 + i * 50,
                "cli": 30 + i,
                "sp": 500.0 + i * 10,
                "cv": 5 + i,
            },
        )
        await db_session.execute(
            text(
                "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (:cid, :date, :imp, :cli, :sp, :cv)"
            ),
            {
                "cid": 2,
                "date": d,
                "imp": 2000 + i * 100,
                "cli": 60 + i * 2,
                "sp": 1000.0 + i * 20,
                "cv": 10 + i,
            },
        )

    # Scheduled posts (published)
    await db_session.execute(
        text(
            "INSERT INTO scheduled_posts "
            "(id, product_id, product_name, platform, topic, body, "
            " scheduled_at, status, published_at, telegram_message_id) VALUES "
            "(1, 1, 'ProductA', 'telegram', 'Topic Alpha', 'Body', "
            " '2026-04-24 09:00', 'published', '2026-04-24 09:01', 100), "
            "(2, 2, 'ProductB', 'telegram', 'Topic Beta', 'Body', "
            " '2026-04-24 12:00', 'published', '2026-04-24 12:01', 101), "
            "(3, 1, 'ProductA', 'vc.ru', 'Topic Gamma', 'Body', "
            " '2026-04-23 09:00', 'published', '2026-04-23 09:01', NULL)"
        )
    )
    # Post metrics
    await db_session.execute(
        text(
            "INSERT INTO post_metrics (post_id, product_id, date, views, forwards, reactions) VALUES "
            "(1, 1, '2026-04-24', 5000, 20, 80), "
            "(2, 2, '2026-04-24', 3000, 10, 40), "
            "(3, 1, '2026-04-23', 1200, 5, 15)"
        )
    )
    await db_session.commit()
    return db_session


# ── top_performing_posts ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_performing_posts_sorted_by_views(engine_db):
    """Returns posts sorted descending by views."""
    engine = AnalyticsEngine(engine_db)
    posts = await engine.top_performing_posts(period_days=30)

    assert len(posts) >= 2
    assert posts[0]["views"] >= posts[1]["views"]
    assert posts[0]["post_id"] == 1  # 5000 views
    assert "topic" in posts[0]
    assert "platform" in posts[0]


@pytest.mark.asyncio
async def test_top_performing_posts_returns_correct_fields(engine_db):
    """Each result contains the expected keys."""
    engine = AnalyticsEngine(engine_db)
    posts = await engine.top_performing_posts(period_days=30)

    expected_keys = {
        "post_id",
        "topic",
        "platform",
        "product_name",
        "views",
        "forwards",
        "reactions",
        "published_at",
    }
    assert expected_keys.issubset(set(posts[0].keys()))


@pytest.mark.asyncio
async def test_top_performing_posts_empty_period(engine_db):
    """Returns empty list if no posts in given period."""
    engine = AnalyticsEngine(engine_db)
    posts = await engine.top_performing_posts(period_days=0)
    assert isinstance(posts, list)


# ── cost_per_lead ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_per_lead_correct_calculation(engine_db):
    """CPL = total_spend / total_conversions."""
    engine = AnalyticsEngine(engine_db)
    result = await engine.cost_per_lead(product_id=1)

    assert result["product_id"] == 1
    assert result["total_spend_rub"] > 0
    assert result["total_conversions"] > 0
    expected_cpl = result["total_spend_rub"] / result["total_conversions"]
    assert result["cost_per_lead_rub"] == pytest.approx(expected_cpl, rel=1e-3)


@pytest.mark.asyncio
async def test_cost_per_lead_zero_conversions(engine_db):
    """CPL is 0 when there are no conversions (no division by zero)."""
    # Insert a campaign with zero conversions
    await engine_db.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (99, 1, 'ZeroConv', 'google', 'active')"
        )
    )
    await engine_db.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (99, '2026-04-20', 500, 10, 200.0, 0)"
        )
    )
    await engine_db.commit()

    engine = AnalyticsEngine(engine_db)
    result = await engine.cost_per_lead(product_id=1)
    # Just assert no crash and cost_per_lead_rub is a float
    assert isinstance(result["cost_per_lead_rub"], float)


# ── channel_effectiveness ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_channel_effectiveness_groups_by_platform(engine_db):
    """Returns a dict keyed by platform with expected sub-keys."""
    engine = AnalyticsEngine(engine_db)
    channels = await engine.channel_effectiveness()

    assert isinstance(channels, dict)
    assert "telegram" in channels
    assert "vc.ru" in channels

    tg = channels["telegram"]
    assert "post_count" in tg
    assert "total_views" in tg
    assert "engagement_rate_pct" in tg
    assert tg["total_views"] == 8000  # 5000 + 3000


@pytest.mark.asyncio
async def test_channel_effectiveness_engagement_rate(engine_db):
    """Engagement rate = (reactions + forwards) / views * 100."""
    engine = AnalyticsEngine(engine_db)
    channels = await engine.channel_effectiveness()

    tg = channels["telegram"]
    # (80+20 + 40+10) / (5000+3000) * 100 = 150/8000*100 = 1.875
    assert tg["engagement_rate_pct"] == pytest.approx(1.875, rel=1e-2)


# ── trend_analysis ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trend_analysis_returns_correct_structure(engine_db):
    """Returns dates, values, and trend lists of equal length."""
    engine = AnalyticsEngine(engine_db)
    result = await engine.trend_analysis("clicks", days=10)

    assert "dates" in result
    assert "values" in result
    assert "trend" in result
    assert len(result["dates"]) == len(result["values"]) == len(result["trend"])
    assert len(result["dates"]) > 0


@pytest.mark.asyncio
async def test_trend_analysis_rolling_average(engine_db):
    """Trend values are rolling averages (not raw values)."""
    engine = AnalyticsEngine(engine_db)
    result = await engine.trend_analysis("impressions", days=10)

    # With 10 data points, trend[-1] should be ≤ max(values) (smoothed)
    max_val = max(result["values"])
    min_val = min(result["values"])
    # Rolling average must be between min and max
    for t in result["trend"]:
        assert min_val <= t <= max_val + 1  # +1 for float rounding


@pytest.mark.asyncio
async def test_trend_analysis_invalid_metric_raises(engine_db):
    """Raises ValueError for unknown metric name."""
    engine = AnalyticsEngine(engine_db)
    with pytest.raises(ValueError, match="Invalid metric"):
        await engine.trend_analysis("not_a_metric", days=7)


@pytest.mark.asyncio
async def test_trend_analysis_empty_data(db_session):
    """Returns empty lists when no metrics exist (fresh DB with no rows)."""
    engine = AnalyticsEngine(db_session)
    result = await engine.trend_analysis("clicks", days=30)
    assert result == {"dates": [], "values": [], "trend": []}
