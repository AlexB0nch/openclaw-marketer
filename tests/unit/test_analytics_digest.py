"""Unit tests for integrations/analytics/digest.py."""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.analytics.digest import AnomalyDetector, MorningDigest, WeeklyReport
from integrations.analytics.engine import AnalyticsEngine

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def digest_db(db_session):
    """Seed minimal data for digest/anomaly tests."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES " "(1, 'Alpha', 1), (2, 'Beta', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) VALUES "
            "(1, 1, 'Alpha TG', 'telegram', 'active'), "
            "(2, 2, 'Beta YD', 'yandex_direct', 'active')"
        )
    )
    # Yesterday's metrics for morning digest
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (1, :d, 8000, 200, 1200.0, 15), "
            "       (2, :d, 5000, 100, 800.0, 8)"
        ),
        {"d": str(yesterday)},
    )
    # 7-day historical metrics for CTR baseline (avg CTR = 200/8000 = 0.025)
    for i in range(1, 8):
        d = str(today - timedelta(days=i + 1))
        await db_session.execute(
            text(
                "INSERT INTO metrics "
                "(campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (1, :d, 8000, 200, 1200.0, 15)"
            ),
            {"d": d},
        )
    # Today's metrics for anomaly detection — normal CTR (200/8000 = 2.5%)
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (1, :d, 8000, 200, 1200.0, 15)"
        ),
        {"d": str(today)},
    )

    # A published post for top_post in digest
    await db_session.execute(
        text(
            "INSERT INTO scheduled_posts "
            "(id, product_id, product_name, platform, topic, body, "
            " scheduled_at, status, published_at, telegram_message_id) "
            "VALUES (1, 1, 'Alpha', 'telegram', 'Best Topic', 'Body', "
            " :d, 'published', :d, 42)"
        ),
        {"d": str(yesterday) + " 09:00"},
    )
    await db_session.execute(
        text(
            "INSERT INTO post_metrics (post_id, product_id, date, views, forwards, reactions) "
            "VALUES (1, 1, :d, 4200, 30, 90)"
        ),
        {"d": str(yesterday)},
    )
    await db_session.commit()
    return db_session


# ── MorningDigest ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_morning_digest_contains_date(digest_db, test_settings):
    """Digest contains yesterday's date string."""
    engine = AnalyticsEngine(digest_db)
    digest = MorningDigest()
    text_out = await digest.generate(digest_db, engine, test_settings)

    yesterday = (date.today() - timedelta(days=1)).strftime("%d.%m.%Y")
    assert yesterday in text_out


@pytest.mark.asyncio
async def test_morning_digest_contains_product_names(digest_db, test_settings):
    """Digest contains product names from yesterday's metrics."""
    engine = AnalyticsEngine(digest_db)
    digest = MorningDigest()
    text_out = await digest.generate(digest_db, engine, test_settings)

    assert "Alpha" in text_out
    assert "Beta" in text_out


@pytest.mark.asyncio
async def test_morning_digest_contains_emoji_header(digest_db, test_settings):
    """Digest starts with the expected emoji."""
    engine = AnalyticsEngine(digest_db)
    digest = MorningDigest()
    text_out = await digest.generate(digest_db, engine, test_settings)

    assert "📊" in text_out


@pytest.mark.asyncio
async def test_morning_digest_contains_top_post(digest_db, test_settings):
    """Digest includes top post section."""
    engine = AnalyticsEngine(digest_db)
    digest = MorningDigest()
    text_out = await digest.generate(digest_db, engine, test_settings)

    assert "Best Topic" in text_out
    assert "4" in text_out  # 4,200 views


@pytest.mark.asyncio
async def test_morning_digest_no_data(db_session, test_settings):
    """Digest handles gracefully when no metrics exist."""
    engine = AnalyticsEngine(db_session)
    digest = MorningDigest()
    text_out = await digest.generate(db_session, engine, test_settings)

    assert "Нет данных" in text_out


# ── WeeklyReport ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_report_returns_text_and_optional_chart(digest_db, test_settings):
    """generate() returns (str, Path | None) tuple."""
    engine = AnalyticsEngine(digest_db)
    report = WeeklyReport()
    text_out, chart_path = await report.generate(digest_db, engine, test_settings)

    assert isinstance(text_out, str)
    assert chart_path is None or isinstance(chart_path, Path)
    assert "📈" in text_out


@pytest.mark.asyncio
async def test_weekly_report_chart_failure_does_not_block(digest_db, test_settings):
    """Chart generation error returns chart_path=None and text is still valid."""
    engine = AnalyticsEngine(digest_db)
    report = WeeklyReport()

    with patch("matplotlib.pyplot.subplots", side_effect=RuntimeError("display error")):
        text_out, chart_path = await report.generate(digest_db, engine, test_settings)

    assert isinstance(text_out, str)
    assert "📈" in text_out
    assert chart_path is None


@pytest.mark.asyncio
async def test_weekly_report_import_error_does_not_block(digest_db, test_settings):
    """ImportError for matplotlib returns chart_path=None and text is still valid."""
    engine = AnalyticsEngine(digest_db)
    report = WeeklyReport()

    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "matplotlib":
            raise ImportError("no module matplotlib")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        text_out, chart_path = await report.generate(digest_db, engine, test_settings)

    assert isinstance(text_out, str)
    assert chart_path is None


@pytest.mark.asyncio
async def test_weekly_report_send_text_only(digest_db, test_settings, mock_telegram_bot):
    """send() calls send_message when chart_path is None."""
    report = WeeklyReport()

    await report.send(mock_telegram_bot, "12345", "Report text", None)

    mock_telegram_bot.send_message.assert_called_once()
    mock_telegram_bot.send_photo.assert_not_called()


@pytest.mark.asyncio
async def test_weekly_report_send_with_chart(tmp_path, mock_telegram_bot):
    """send() calls send_photo when chart file exists."""
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"PNG")

    report = WeeklyReport()
    await report.send(mock_telegram_bot, "12345", "Report text", chart)

    mock_telegram_bot.send_photo.assert_called_once()
    mock_telegram_bot.send_message.assert_not_called()


# ── AnomalyDetector ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anomaly_no_alert_on_normal_ctr(digest_db, test_settings):
    """No CTR alert when today's CTR matches 7-day average."""
    engine = AnalyticsEngine(digest_db)
    detector = AnomalyDetector()
    alerts = await detector.check(digest_db, engine, test_settings)

    ctr_alerts = [a for a in alerts if "CTR" in a]
    assert len(ctr_alerts) == 0


@pytest.mark.asyncio
async def test_anomaly_ctr_drop_fires_alert(db_session, test_settings):
    """CTR alert fires when today's CTR drops > 30% vs 7-day average."""
    today = date.today()

    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (10, 'DropProduct', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (10, 10, 'Drop Camp', 'telegram', 'active')"
        )
    )
    # Historical: avg CTR = 200/8000 = 2.5%
    for i in range(1, 8):
        d = str(today - timedelta(days=i))
        await db_session.execute(
            text(
                "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (10, :d, 8000, 200, 500.0, 5)"
            ),
            {"d": d},
        )
    # Today: CTR = 20/8000 = 0.25% — drop of 90% (> 30% threshold)
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (10, :d, 8000, 20, 500.0, 1)"
        ),
        {"d": str(today)},
    )
    await db_session.commit()

    engine = AnalyticsEngine(db_session)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 999_999.0  # disable spend alert
    alerts = await detector.check(db_session, engine, test_settings)

    ctr_alerts = [a for a in alerts if "CTR" in a]
    assert len(ctr_alerts) == 1
    assert "DropProduct" in ctr_alerts[0]


@pytest.mark.asyncio
async def test_anomaly_no_alert_when_avg_ctr_is_zero(db_session, test_settings):
    """No CTR alert when 7-day average is zero (constraint: avoid false alerts)."""
    today = date.today()

    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (20, 'ZeroAvg', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (20, 20, 'ZeroAvg Camp', 'telegram', 'active')"
        )
    )
    # Historical: 0 clicks (avg CTR = 0)
    for i in range(1, 8):
        d = str(today - timedelta(days=i))
        await db_session.execute(
            text(
                "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
                "VALUES (20, :d, 8000, 0, 0.0, 0)"
            ),
            {"d": d},
        )
    # Today: also 0 clicks
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (20, :d, 8000, 0, 0.0, 0)"
        ),
        {"d": str(today)},
    )
    await db_session.commit()

    engine = AnalyticsEngine(db_session)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 999_999.0
    alerts = await detector.check(db_session, engine, test_settings)

    ctr_alerts = [a for a in alerts if "CTR" in a]
    assert len(ctr_alerts) == 0


@pytest.mark.asyncio
async def test_anomaly_no_alert_when_no_historical_data(db_session, test_settings):
    """No CTR alert when no 7-day history (avg_ctr is None)."""
    today = date.today()

    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (30, 'NewProduct', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (30, 30, 'New Camp', 'telegram', 'active')"
        )
    )
    # Only today's data — no history
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (30, :d, 8000, 10, 100.0, 1)"
        ),
        {"d": str(today)},
    )
    await db_session.commit()

    engine = AnalyticsEngine(db_session)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 999_999.0
    alerts = await detector.check(db_session, engine, test_settings)

    ctr_alerts = [a for a in alerts if "CTR" in a]
    assert len(ctr_alerts) == 0


@pytest.mark.asyncio
async def test_anomaly_spend_alert_fires(db_session, test_settings):
    """Spend alert fires when daily spend exceeds threshold."""
    today = date.today()

    await db_session.execute(
        text("INSERT INTO products (id, name, active) VALUES (40, 'SpendProd', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO campaigns (id, product_id, name, platform, status) "
            "VALUES (40, 40, 'SpendCamp', 'telegram', 'active')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO metrics (campaign_id, date, impressions, clicks, spend_rub, conversions) "
            "VALUES (40, :d, 1000, 10, 9999.0, 1)"
        ),
        {"d": str(today)},
    )
    await db_session.commit()

    engine = AnalyticsEngine(db_session)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 5000.0
    alerts = await detector.check(db_session, engine, test_settings)

    spend_alerts = [a for a in alerts if "бюджет" in a]
    assert len(spend_alerts) == 1
    assert "9" in spend_alerts[0]  # 9,999 or 9999


@pytest.mark.asyncio
async def test_anomaly_no_spend_alert_below_threshold(digest_db, test_settings):
    """No spend alert when daily spend is below threshold."""
    engine = AnalyticsEngine(digest_db)
    detector = AnomalyDetector()
    test_settings.daily_spend_alert_threshold_rub = 999_999.0
    alerts = await detector.check(digest_db, engine, test_settings)

    spend_alerts = [a for a in alerts if "бюджет" in a]
    assert len(spend_alerts) == 0


@pytest.mark.asyncio
async def test_anomaly_alert_sends_message(db_session, test_settings, mock_telegram_bot):
    """alert() calls bot.send_message with anomalies."""
    detector = AnomalyDetector()
    await detector.alert(mock_telegram_bot, "12345", ["⚠️ Alert 1", "💸 Alert 2"])

    mock_telegram_bot.send_message.assert_called_once()
    call_kwargs = mock_telegram_bot.send_message.call_args
    assert "Alert 1" in call_kwargs.kwargs["text"] or "Alert 1" in str(call_kwargs)


@pytest.mark.asyncio
async def test_anomaly_alert_skips_empty_list(db_session, test_settings, mock_telegram_bot):
    """alert() does nothing when anomalies list is empty."""
    detector = AnomalyDetector()
    await detector.alert(mock_telegram_bot, "12345", [])
    mock_telegram_bot.send_message.assert_not_called()
