"""APScheduler setup for Analytics Agent tasks."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.config import Settings
from integrations.analytics.digest import AnomalyDetector, MorningDigest, WeeklyReport
from integrations.analytics.engine import AnalyticsEngine

logger = logging.getLogger(__name__)


class AnalyticsScheduler:
    """Scheduler for Analytics Agent: digest, weekly report, anomaly checks."""

    def __init__(self, settings: Settings, engine, bot: Bot) -> None:
        self.scheduler = AsyncIOScheduler()
        self.settings = settings
        self.db_engine = engine
        self.bot = bot

    def start(self) -> None:
        """Register all analytics jobs and start the scheduler."""
        # Morning digest: every day 08:30 MSK
        self.scheduler.add_job(
            self.morning_digest_task,
            trigger=CronTrigger(hour=8, minute=30, timezone="Europe/Moscow"),
            id="analytics_morning_digest",
            name="Analytics Morning Digest",
        )
        # Weekly report: every Sunday 19:00 MSK
        self.scheduler.add_job(
            self.weekly_report_task,
            trigger=CronTrigger(day_of_week=6, hour=19, minute=0, timezone="Europe/Moscow"),
            id="analytics_weekly_report",
            name="Analytics Weekly Report",
        )
        # Anomaly check: every hour
        self.scheduler.add_job(
            self.anomaly_check_task,
            trigger=IntervalTrigger(hours=1),
            id="analytics_anomaly_check",
            name="Analytics Anomaly Check",
        )
        self.scheduler.start()
        logger.info("Analytics scheduler started")

    async def morning_digest_task(self) -> None:
        """Generate and send the morning metrics digest."""
        try:
            async with AsyncSession(self.db_engine) as session:
                engine = AnalyticsEngine(session)
                digest = MorningDigest()
                text = await digest.generate(session, engine, self.settings)
                try:
                    await self.bot.send_message(
                        chat_id=self.settings.telegram_admin_chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                    logger.info("Morning digest sent")
                except TelegramError as exc:
                    logger.error("Failed to send morning digest: %s", exc)
        except Exception as exc:
            logger.error("Morning digest task failed: %s", exc, exc_info=True)

    async def weekly_report_task(self) -> None:
        """Generate and send the weekly analytics report."""
        try:
            async with AsyncSession(self.db_engine) as session:
                engine = AnalyticsEngine(session)
                report = WeeklyReport()
                text, chart_path = await report.generate(session, engine, self.settings)
                try:
                    await report.send(
                        self.bot,
                        self.settings.telegram_admin_chat_id,
                        text,
                        chart_path,
                    )
                    logger.info("Weekly report sent")
                except TelegramError as exc:
                    logger.error("Failed to send weekly report: %s", exc)
        except Exception as exc:
            logger.error("Weekly report task failed: %s", exc, exc_info=True)

    async def anomaly_check_task(self) -> None:
        """Check for metric anomalies and fire alerts if found."""
        try:
            async with AsyncSession(self.db_engine) as session:
                engine = AnalyticsEngine(session)
                detector = AnomalyDetector()
                anomalies = await detector.check(session, engine, self.settings)
                if anomalies:
                    try:
                        await detector.alert(
                            self.bot,
                            self.settings.telegram_admin_chat_id,
                            anomalies,
                        )
                        logger.info("Anomaly alert sent: %d issues", len(anomalies))
                    except TelegramError as exc:
                        logger.error("Failed to send anomaly alert: %s", exc)
        except Exception as exc:
            logger.error("Anomaly check task failed: %s", exc, exc_info=True)

    def shutdown(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Analytics scheduler stopped")
