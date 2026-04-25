"""Morning digest, weekly report, and anomaly detector for the Analytics Agent."""

import logging
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.config import Settings
from integrations.analytics.engine import AnalyticsEngine

logger = logging.getLogger(__name__)


async def _get_week_metrics(session: AsyncSession, week_start: date, week_end: date) -> dict:
    """Aggregate metrics totals for a date range [week_start, week_end)."""
    result = await session.execute(
        text(
            "SELECT "
            "  COALESCE(SUM(impressions), 0), "
            "  COALESCE(SUM(clicks), 0), "
            "  COALESCE(SUM(spend_rub), 0), "
            "  COALESCE(SUM(conversions), 0), "
            "  CAST(COALESCE(SUM(clicks), 0) AS REAL) "
            "    / NULLIF(COALESCE(SUM(impressions), 0), 0) * 100 "
            "FROM metrics "
            "WHERE date >= :start AND date < :end"
        ),
        {"start": str(week_start), "end": str(week_end)},
    )
    row = result.fetchone()
    if not row or row[0] is None:
        return {"impressions": 0.0, "clicks": 0.0, "spend": 0.0, "conversions": 0.0, "ctr": 0.0}
    return {
        "impressions": float(row[0]),
        "clicks": float(row[1]),
        "spend": float(row[2]),
        "conversions": float(row[3]),
        "ctr": round(float(row[4] or 0), 2),
    }


class MorningDigest:
    """Generate the daily 08:30 MSK analytics digest."""

    async def generate(
        self,
        session: AsyncSession,
        engine: AnalyticsEngine,
        settings: Settings,
    ) -> str:
        """Build a Markdown digest for yesterday's metrics."""
        yesterday = date.today() - timedelta(days=1)

        result = await session.execute(
            text(
                "SELECT "
                "  p.name, "
                "  COALESCE(SUM(m.impressions), 0), "
                "  COALESCE(SUM(m.clicks), 0), "
                "  COALESCE(SUM(m.spend_rub), 0), "
                "  COALESCE(SUM(m.conversions), 0) "
                "FROM metrics m "
                "JOIN campaigns c ON c.id = m.campaign_id "
                "JOIN products p ON p.id = c.product_id "
                "WHERE m.date = :yesterday "
                "GROUP BY p.name "
                "ORDER BY p.name"
            ),
            {"yesterday": str(yesterday)},
        )
        rows = result.fetchall()

        top_posts = await engine.top_performing_posts(period_days=1)
        top_post = top_posts[0] if top_posts else None

        lines = [f"📊 *Утренний дайджест — {yesterday.strftime('%d.%m.%Y')}*\n"]

        if rows:
            lines.append("| Продукт | Показы | Клики | CTR | Расход |")
            lines.append("|---------|--------|-------|-----|--------|")
            for r in rows:
                name = r[0]
                impressions = int(r[1])
                clicks = int(r[2])
                spend = float(r[3])
                ctr = round(clicks / impressions * 100, 2) if impressions > 0 else 0.0
                lines.append(f"| {name} | {impressions:,} | {clicks:,} | {ctr}% | {spend:,.0f}₽ |")
        else:
            lines.append("_Нет данных за вчера_")

        if top_post:
            lines.append(f"\n🏆 *Топ-пост:* {top_post['topic']}")
            lines.append(
                f"👁 {top_post['views']:,} просмотров · " f"↗️ {top_post['forwards']} репостов"
            )

        total_spend = sum(float(r[3]) for r in rows)
        budget = settings.monthly_ads_budget_limit_rub
        lines.append(f"\n💰 *Расход за день:* {total_spend:,.0f}₽ | Лимит: {budget:,.0f}₽/мес")

        return "\n".join(lines)


class WeeklyReport:
    """Generate the Sunday 19:00 MSK weekly analytics report."""

    async def generate(
        self,
        session: AsyncSession,
        engine: AnalyticsEngine,
        settings: Settings,
    ) -> tuple[str, Path | None]:
        """Build a week-over-week Markdown report and optional chart PNG.

        Chart generation is wrapped in try/except: on any failure, chart_path=None
        and the text report is returned unchanged.
        """
        today = date.today()
        week_start = today - timedelta(days=7)
        prev_week_start = week_start - timedelta(days=7)

        curr = await _get_week_metrics(session, week_start, today)
        prev = await _get_week_metrics(session, prev_week_start, week_start)

        lines = [
            f"📈 *Еженедельный отчёт* | "
            f"{week_start.strftime('%d.%m')} – {today.strftime('%d.%m.%Y')}\n",
            "| Метрика | Тек. неделя | Пред. неделя | Δ |",
            "|---------|------------|-------------|---|",
        ]

        comparisons = [
            ("Показы", "impressions"),
            ("Клики", "clicks"),
            ("CTR (%)", "ctr"),
            ("Расход (₽)", "spend"),
            ("Конверсии", "conversions"),
        ]
        for label, key in comparisons:
            c_val = curr.get(key, 0.0)
            p_val = prev.get(key, 0.0)
            delta = c_val - p_val
            delta_str = f"+{delta:.1f}" if delta >= 0 else f"{delta:.1f}"
            lines.append(f"| {label} | {c_val:,.1f} | {p_val:,.1f} | {delta_str} |")

        # Recommendations from trend analysis
        try:
            trend = await engine.trend_analysis("clicks", days=14)
            if trend["trend"] and len(trend["trend"]) >= 2:
                last_t = trend["trend"][-1]
                pivot = trend["trend"][-7] if len(trend["trend"]) >= 7 else trend["trend"][0]
                if last_t > pivot * 1.1:
                    lines.append(
                        "\n💡 *Рекомендация:* Клики растут — "
                        "увеличьте бюджет на топовые кампании."
                    )
                elif last_t < pivot * 0.9:
                    lines.append(
                        "\n💡 *Рекомендация:* Клики падают — " "пересмотрите креативы и таргетинг."
                    )
                else:
                    lines.append(
                        "\n💡 *Рекомендация:* Стабильная динамика — "
                        "продолжайте текущую стратегию."
                    )
        except Exception as exc:
            logger.warning("Trend analysis for recommendations failed: %s", exc)

        report_text = "\n".join(lines)
        chart_path: Path | None = None

        # Chart generation — failure must never block the report
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            trend = await engine.trend_analysis("clicks", days=14)
            if trend["dates"] and trend["values"]:
                fig, ax = plt.subplots(figsize=(10, 4))
                ax.plot(
                    trend["dates"],
                    trend["values"],
                    label="Клики",
                    marker="o",
                    markersize=3,
                )
                ax.plot(
                    trend["dates"],
                    trend["trend"],
                    label="Тренд (7д)",
                    linestyle="--",
                    color="orange",
                )
                ax.set_title("Клики за 14 дней")
                ax.set_xlabel("Дата")
                ax.set_ylabel("Клики")
                ax.legend()
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()

                chart_path = Path("/tmp") / f"weekly_report_{today.isoformat()}.png"
                plt.savefig(chart_path, dpi=100, bbox_inches="tight")
                plt.close(fig)
        except Exception as exc:
            logger.warning("Chart generation failed, sending text-only report: %s", exc)
            chart_path = None

        return report_text, chart_path

    async def send(
        self,
        bot: Bot,
        chat_id: str,
        text: str,
        chart_path: Path | None,
    ) -> None:
        """Send report as photo (with chart) or plain text message."""
        if chart_path and chart_path.exists():
            try:
                with open(chart_path, "rb") as f:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=text[:1024],
                        parse_mode="Markdown",
                    )
                return
            except Exception as exc:
                logger.warning("send_photo failed, falling back to text: %s", exc)
        await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")


class AnomalyDetector:
    """Detect CTR drops and spend overruns; fire immediate Telegram alerts."""

    async def check(
        self,
        session: AsyncSession,
        engine: AnalyticsEngine,
        settings: Settings,
    ) -> list[str]:
        """Return list of alert strings (empty = no anomalies)."""
        alerts: list[str] = []
        today = date.today()

        # ── CTR anomaly ───────────────────────────────────────────────────────
        today_result = await session.execute(
            text(
                "SELECT c.product_id, p.name, "
                "  COALESCE(SUM(m.clicks), 0), "
                "  COALESCE(SUM(m.impressions), 0) "
                "FROM metrics m "
                "JOIN campaigns c ON c.id = m.campaign_id "
                "JOIN products p ON p.id = c.product_id "
                "WHERE m.date = :today "
                "GROUP BY c.product_id, p.name"
            ),
            {"today": str(today)},
        )
        today_rows = today_result.fetchall()

        for row in today_rows:
            product_id, product_name = row[0], row[1]
            today_clicks = int(row[2])
            today_impressions = int(row[3])
            today_ctr = today_clicks / today_impressions if today_impressions > 0 else None

            cutoff_7d = today - timedelta(days=7)
            avg_result = await session.execute(
                text(
                    "SELECT "
                    "  CAST(COALESCE(SUM(m.clicks), 0) AS REAL) "
                    "    / NULLIF(COALESCE(SUM(m.impressions), 0), 0) "
                    "FROM metrics m "
                    "JOIN campaigns c ON c.id = m.campaign_id "
                    "WHERE c.product_id = :pid "
                    "  AND m.date >= :cutoff "
                    "  AND m.date < :today"
                ),
                {"pid": product_id, "cutoff": str(cutoff_7d), "today": str(today)},
            )
            avg_row = avg_result.fetchone()
            avg_ctr = float(avg_row[0]) if avg_row and avg_row[0] is not None else None

            # Skip if no historical data (constraint: avoid false alerts)
            if avg_ctr is None or avg_ctr == 0:
                continue

            if today_ctr is not None and today_ctr < avg_ctr * 0.7:
                drop_pct = round((1 - today_ctr / avg_ctr) * 100, 1)
                alerts.append(
                    f"⚠️ *CTR упал на {drop_pct}%* для *{product_name}*\n"
                    f"Сегодня: {today_ctr:.2%} | Средн. 7д: {avg_ctr:.2%}\n"
                    f"🔧 Рекомендация: проверьте объявления и таргетинг."
                )

        # ── Spend anomaly ─────────────────────────────────────────────────────
        spend_result = await session.execute(
            text("SELECT COALESCE(SUM(spend_rub), 0) FROM metrics WHERE date = :today"),
            {"today": str(today)},
        )
        spend_row = spend_result.fetchone()
        daily_spend = float(spend_row[0]) if spend_row and spend_row[0] is not None else None

        # Skip if spend data is absent (constraint: avoid false alerts)
        if daily_spend is not None and daily_spend > settings.daily_spend_alert_threshold_rub:
            alerts.append(
                f"💸 *Превышен дневной бюджет!*\n"
                f"Расход: {daily_spend:,.0f}₽ | "
                f"Порог: {settings.daily_spend_alert_threshold_rub:,.0f}₽\n"
                f"🔧 Рекомендация: проверьте ставки и лимиты кампаний."
            )

        return alerts

    async def alert(self, bot: Bot, chat_id: str, anomalies: list[str]) -> None:
        """Send all anomaly alerts as a single Telegram message."""
        if not anomalies:
            return
        message = "🚨 *Обнаружены аномалии*\n\n" + "\n\n".join(anomalies)
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
