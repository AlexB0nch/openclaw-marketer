"""AdsScheduler: APScheduler jobs for the Ads Agent."""

import contextlib
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.config import Settings
from integrations.ads.budget_monitor import BudgetMonitor
from integrations.error_handler import GlobalErrorHandler
from integrations.yandex_direct.ab_test import ABTestManager
from integrations.yandex_direct.client import YandexDirectClient

logger = logging.getLogger(__name__)


class AdsScheduler:
    """Scheduler for Ads Agent recurring tasks."""

    def __init__(self, settings: Settings, engine: object, bot: Bot) -> None:
        self.scheduler = AsyncIOScheduler()
        self.settings = settings
        self.engine = engine
        self.bot = bot

    def start(self) -> None:
        """Register and start all Ads Agent scheduler jobs."""
        # A/B test evaluation — daily 07:00 MSK
        self.scheduler.add_job(
            self._ab_test_check_task,
            trigger=CronTrigger(hour=7, minute=0, timezone="Europe/Moscow"),
            id="ads_ab_test_check",
            name="Ads A/B Test Check",
        )
        # Budget check — every hour
        self.scheduler.add_job(
            self._budget_check_task,
            trigger=CronTrigger(minute=0, timezone="Europe/Moscow"),
            id="ads_budget_check",
            name="Ads Budget Check",
        )
        # Weekly report — every Monday 08:00 MSK
        self.scheduler.add_job(
            self._weekly_report_task,
            trigger=CronTrigger(day_of_week=0, hour=8, minute=0, timezone="Europe/Moscow"),
            id="ads_weekly_report",
            name="Ads Weekly Report",
        )
        self.scheduler.start()
        logger.info("Ads scheduler started")

    async def _ab_test_check_task(self) -> None:
        """Evaluate A/B tests running 7+ days and pause losing variants."""
        try:
            from sqlalchemy import text

            manager = ABTestManager()
            yandex_client = YandexDirectClient(self.settings)

            async with AsyncSession(self.engine) as session:
                rows = await session.execute(
                    text(
                        "SELECT id FROM ad_campaigns "
                        "WHERE status = 'running' AND platform = 'yandex'"
                    )
                )
                campaign_ids = [r[0] for r in rows.fetchall()]

            for campaign_id in campaign_ids:
                try:
                    async with AsyncSession(self.engine) as session:
                        winner = await manager.evaluate_ab_test(session, campaign_id)
                        if winner is not None:
                            await manager.pause_losing_variants(session, campaign_id, yandex_client)
                            logger.info(
                                "A/B test for campaign %d resolved, winner=%d",
                                campaign_id,
                                winner,
                            )
                except Exception as exc:
                    logger.error("A/B test check failed for campaign %d: %s", campaign_id, exc)

        except Exception as exc:
            logger.error("A/B test check task failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("ads", "ab_test_check", exc, {})

    async def _budget_check_task(self) -> None:
        """Check daily spend limits and auto-pause if monthly limit hit."""
        try:
            yandex_client = YandexDirectClient(self.settings)
            monitor = BudgetMonitor(self.settings)

            async with AsyncSession(self.engine) as session:
                daily_spend = await monitor.check_daily_spend(session, yandex_client)
                paused = await monitor.auto_pause_on_limit(session, yandex_client)

            if daily_spend > self.settings.daily_spend_alert_threshold_rub:
                try:
                    await self.bot.send_message(
                        chat_id=self.settings.telegram_admin_chat_id,
                        text=(
                            "\u26a0\ufe0f *Предупреждение о бюджете*\n"
                            f"Дневные расходы: {daily_spend:,.0f} \u20bd\n"
                            f"Порог: {self.settings.daily_spend_alert_threshold_rub:,.0f} \u20bd"
                        ),
                        parse_mode="Markdown",
                    )
                except TelegramError as exc:
                    logger.error("Failed to send budget alert: %s", exc)

            if paused:
                try:
                    await self.bot.send_message(
                        chat_id=self.settings.telegram_admin_chat_id,
                        text=(
                            "\U0001f6d1 *Авто-пауза кампаний*\n"
                            "Достигнут месячный лимит. Все кампании приостановлены."
                        ),
                        parse_mode="Markdown",
                    )
                except TelegramError as exc:
                    logger.error("Failed to send pause notification: %s", exc)

        except Exception as exc:
            logger.error("Budget check task failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("ads", "budget_check", exc, {})

    async def _weekly_report_task(self) -> None:
        """Send weekly ad spend summary to Telegram admin."""
        try:
            from datetime import date, timedelta

            from sqlalchemy import text

            week_ago = (date.today() - timedelta(days=7)).isoformat()
            today = date.today().isoformat()

            async with AsyncSession(self.engine) as session:
                row = await session.execute(
                    text(
                        "SELECT COALESCE(SUM(spend_rub), 0.0), "
                        "COALESCE(SUM(clicks), 0), COALESCE(SUM(impressions), 0) "
                        "FROM ad_daily_spend WHERE date >= :start AND date <= :end"
                    ),
                    {"start": week_ago, "end": today},
                )
                spend, clicks, impressions = row.fetchone()

            ctr = (clicks / impressions * 100) if impressions > 0 else 0.0
            report = (
                "\U0001f4ca *Еженедельный отчёт по рекламе*\n\n"
                f"*Период:* {week_ago} \u2014 {today}\n"
                f"*Расход:* {float(spend):,.0f} \u20bd\n"
                f"*Клики:* {int(clicks):,}\n"
                f"*Показы:* {int(impressions):,}\n"
                f"*CTR:* {ctr:.2f}%"
            )

            await self.bot.send_message(
                chat_id=self.settings.telegram_admin_chat_id,
                text=report,
                parse_mode="Markdown",
            )
            logger.info("Weekly ads report sent")

        except Exception as exc:
            logger.error("Weekly ads report task failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("ads", "weekly_report", exc, {})

    def shutdown(self) -> None:
        """Stop scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Ads scheduler stopped")
