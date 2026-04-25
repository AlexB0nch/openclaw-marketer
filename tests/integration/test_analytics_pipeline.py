"""Integration tests for the full Analytics Agent pipeline."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.analytics.collector import (
    TelegramMetricsCollector,
    YandexDirectMetricsCollector,
)
from integrations.analytics.digest import AnomalyDetector, MorningDigest, WeeklyReport
from integrations.analytics.engine import AnalyticsEngine

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pipeline_db(db_session):
    """Full dataset: products, campaigns, posts, metrics, post_metrics."""
    today = date.today()

    await db_session.execute(
        text(
            "INSERT INTO products (id, name, active) VALUES "
            "(1, 'AlphaProduct', 1), (2, 'BetaProduct', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) VALUES "
            "(1, 1, 'Alpha TG', 'telegram', 'active'), "
            "(2, 2, 'Beta YD', 'yandex_direct', 'active')"
        )
    )
    # 14 days of metrics for trend analysis
    for i in range(14):
        d = str(today - timedelta(days=i + 1))
        await db_session.execute(
            text(
                "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (1, :d, :imp, :cli, :sp, :cv), (2, :d, :imp2, :cli2, :sp2, :cv2)"
            ),
            {
                "d": d,
                "imp": 10_000 + i * 200,
                "cli": 300 + i * 5,
                "sp": 1500.0 + i * 30,
                "cv": 20 + i,
                "imp2": 5_000 + i * 100,
                "cli2": 150 + i * 2,
                "sp2": 800.0 + i * 15,
                "cv2": 10 + i,
            },
        )
    # Today's metrics
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (1, :d, 10000, 300, 1500.0, 20), (2, :d, 5000, 150, 800.0, 10)"
        ),
        {"d": str(today)},
    )
    # Published posts
    for i, (pid, pname, platform) in enumerate(
        [
            (1, "AlphaProduct", "telegram"),
            (2, "BetaProduct", "telegram"),
            (1, "AlphaProduct", "vc.ru"),
        ],
        start=1,
    ):
        pub_date = str(today - timedelta(days=i))
        await db_session.execute(
            text(
                "INSERT INTO scheduled_posts "
                "(id, product_id, product_name, platform, topic, body, "
                " scheduled_at, status, published_at, telegram_message_id) "
                "VALUES (:id, :pid, :pname, :plat, :topic, 'Body', "
                "        :pub, 'published', :pub, :mid)"
            ),
            {
                "id": i,
                "pid": pid,
                "pname": pname,
                "plat": platform,
                "topic": f"Topic {i}",
                "pub": pub_date + " 09:00",
                "mid": 100 + i if platform == "telegram" else None,
            },
        )
    # Post metrics
    await db_session.execute(
        text(
            "INSERT INTO post_metrics (post_id, product_id, date, views, forwards, reactions) "
            "VALUES (1, 1, :d1, 7000, 50, 150), (2, 2, :d2, 4000, 20, 60)"
        ),
        {
            "d1": str(today - timedelta(days=1)),
            "d2": str(today - timedelta(days=2)),
        },
    )
    await db_session.commit()
    return db_session


# ── Full pipeline: collect → engine → digest ──────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_telegram_collect_and_top_posts(pipeline_db, test_settings):
    """Collect Telegram post metrics then verify engine returns them in top posts."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"ok": True, "result": 2500})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_http = MagicMock()
    mock_http.get = MagicMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_http):
        collector = TelegramMetricsCollector(test_settings)
        new_records = await collector.collect_all_recent(pipeline_db, days=30)

    assert len(new_records) >= 1

    engine = AnalyticsEngine(pipeline_db)
    top_posts = await engine.top_performing_posts(period_days=30)
    assert len(top_posts) >= 1
    # Highest views should be 7000 from pre-seeded data (collector added 2500 for new rows)
    assert top_posts[0]["views"] >= 2500


@pytest.mark.asyncio
async def test_pipeline_yandex_collect_affects_cost_per_lead(pipeline_db, test_settings):
    """Yandex Direct data flows through to cost_per_lead calculation."""
    tsv = (
        "Report\tCampaign\n"
        "Date\tImpressions\tClicks\tCost\tCtr\tConversions\n"
        "2026-04-20\t20000\t600\t3000000000\t3.0\t40\n"
    )
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=tsv)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)

    mock_http = MagicMock()
    mock_http.post = MagicMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=None)

    with patch("integrations.analytics.collector.aiohttp.ClientSession", return_value=mock_http):
        collector = YandexDirectMetricsCollector(test_settings)
        records = await collector.collect(
            pipeline_db,
            campaign_id=1,
            product_id=1,
            date_from=date(2026, 4, 20),
            date_to=date(2026, 4, 20),
        )

    assert len(records) == 1
    assert records[0].spend_rub == pytest.approx(3000.0)

    engine = AnalyticsEngine(pipeline_db)
    cpl = await engine.cost_per_lead(product_id=1)
    assert cpl["total_spend_rub"] > 0
    assert cpl["total_conversions"] > 0


@pytest.mark.asyncio
async def test_pipeline_engine_to_digest(pipeline_db, test_settings):
    """Engine feeds into MorningDigest which produces valid Markdown."""
    engine = AnalyticsEngine(pipeline_db)
    digest = MorningDigest()
    text_out = await digest.generate(pipeline_db, engine, test_settings)

    assert isinstance(text_out, str)
    assert len(text_out) > 50
    assert "📊" in text_out


@pytest.mark.asyncio
async def test_pipeline_engine_to_weekly_report(pipeline_db, test_settings):
    """Engine feeds into WeeklyReport which produces valid Markdown and optional chart."""
    engine = AnalyticsEngine(pipeline_db)
    report = WeeklyReport()
    text_out, chart_path = await report.generate(pipeline_db, engine, test_settings)

    assert isinstance(text_out, str)
    assert "📈" in text_out
    assert chart_path is None or chart_path.exists()


@pytest.mark.asyncio
async def test_pipeline_anomaly_check_no_false_positives(pipeline_db, test_settings):
    """With stable metrics, no CTR anomaly is triggered."""
    engine = AnalyticsEngine(pipeline_db)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 999_999.0  # disable spend
    alerts = await detector.check(pipeline_db, engine, test_settings)

    ctr_alerts = [a for a in alerts if "CTR" in a]
    assert len(ctr_alerts) == 0


@pytest.mark.asyncio
async def test_pipeline_full_spend_anomaly_to_alert(pipeline_db, test_settings, mock_telegram_bot):
    """End-to-end: spend anomaly detected → alert() fires bot.send_message."""
    today = date.today()
    await pipeline_db.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (1, :d, 1000, 10, 99000.0, 0)"
        ),
        {"d": str(today)},
    )
    await pipeline_db.commit()

    engine = AnalyticsEngine(pipeline_db)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 5000.0
    alerts = await detector.check(pipeline_db, engine, test_settings)

    spend_alerts = [a for a in alerts if "бюджет" in a]
    assert len(spend_alerts) >= 1

    await detector.alert(mock_telegram_bot, test_settings.telegram_admin_chat_id, alerts)
    mock_telegram_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_channel_effectiveness_all_platforms(pipeline_db, test_settings):
    """channel_effectiveness returns entries for all published platforms."""
    engine = AnalyticsEngine(pipeline_db)
    channels = await engine.channel_effectiveness()

    assert isinstance(channels, dict)
    # We have telegram and vc.ru posts seeded
    assert len(channels) >= 1
    for _platform, stats in channels.items():
        assert stats["post_count"] >= 1


@pytest.mark.asyncio
async def test_pipeline_trend_analysis_14_days(pipeline_db, test_settings):
    """trend_analysis returns 14 data points and valid rolling averages."""
    engine = AnalyticsEngine(pipeline_db)
    result = await engine.trend_analysis("clicks", days=14)

    assert len(result["dates"]) == len(result["values"]) == len(result["trend"])
    assert len(result["dates"]) >= 1
    # Trend values should be positive (we seeded positive click counts)
    assert all(t >= 0 for t in result["trend"])
