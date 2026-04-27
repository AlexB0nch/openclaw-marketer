"""EventsScheduler: APScheduler jobs for the Events Agent."""

import contextlib
import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.config import Settings
from integrations.error_handler import GlobalErrorHandler
from integrations.events.digest import DigestBuilder
from integrations.events.filter import RelevanceFilter, save_relevance
from integrations.events.scraper import ConferenceScraper, save_events
from integrations.events.tracker import DeadlineTracker

logger = logging.getLogger(__name__)

PRODUCTS = ["ai_assistant", "ai_trainer", "ai_news"]


class EventsScheduler:
    def __init__(self, settings: Settings, engine: object, bot: Bot) -> None:
        self.scheduler = AsyncIOScheduler()
        self.settings = settings
        self.engine = engine
        self.bot = bot

    def start(self) -> None:
        # Monthly scrape — 1st of month at 10:00 MSK
        self.scheduler.add_job(
            self._monthly_scrape_task,
            trigger=CronTrigger(day=1, hour=10, minute=0, timezone="Europe/Moscow"),
            id="events_monthly_scrape",
            name="Events Monthly Scrape",
        )
        # Monthly digest — 1st of month at 10:30 MSK
        self.scheduler.add_job(
            self._monthly_digest_task,
            trigger=CronTrigger(day=1, hour=10, minute=30, timezone="Europe/Moscow"),
            id="events_monthly_digest",
            name="Events Monthly Digest",
        )
        # Daily deadline check — every day at 09:00 MSK
        self.scheduler.add_job(
            self._deadline_check_task,
            trigger=CronTrigger(hour=9, minute=0, timezone="Europe/Moscow"),
            id="events_deadline_check",
            name="Events Deadline Check",
        )
        self.scheduler.start()
        logger.info("Events scheduler started")

    async def _monthly_scrape_task(self) -> None:
        try:
            scraper = ConferenceScraper()
            try:
                events = await scraper.scrape_all()
            finally:
                await scraper.close()
            f = RelevanceFilter()
            relevant = await f.filter_relevant(events, PRODUCTS)
            async with AsyncSession(self.engine) as session:
                await save_events(session, events)
                await save_relevance(session, relevant)
            logger.info(
                "Events monthly scrape complete: %d events, %d relevant",
                len(events),
                len(relevant),
            )
        except Exception as exc:
            logger.error("Events monthly scrape failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("events", "monthly_scrape", exc, {})

    async def _monthly_digest_task(self) -> None:
        try:
            builder = DigestBuilder()
            async with AsyncSession(self.engine) as session:
                await builder.send_monthly_digest(session, self.bot)
            logger.info("Events monthly digest sent")
        except Exception as exc:
            logger.error("Events monthly digest failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("events", "monthly_digest", exc, {})

    async def _deadline_check_task(self) -> None:
        try:
            tracker = DeadlineTracker()
            today = date.today()
            async with AsyncSession(self.engine) as session:
                upcoming = await tracker.check_upcoming_deadlines(session)
            for event in upcoming:
                if event.cfp_deadline is None:
                    continue
                days_left = (event.cfp_deadline - today).days
                if days_left <= 3:
                    msg = (
                        f"🚨 *Срочно! CFP дедлайн через {days_left} дн.*\n"
                        f"*{event.name}*\n"
                        f"⏰ Дедлайн: {event.cfp_deadline.strftime('%d.%m.%Y')}\n"
                        f"🔗 {event.url}"
                    )
                elif days_left <= 14:
                    msg = (
                        f"⏰ *CFP дедлайн через {days_left} дн.*\n"
                        f"*{event.name}*\n"
                        f"🔗 {event.url}"
                    )
                else:
                    continue
                try:
                    await self.bot.send_message(
                        chat_id=self.settings.telegram_admin_chat_id,
                        text=msg,
                        parse_mode="Markdown",
                    )
                except TelegramError as exc:
                    logger.error("Failed to send deadline reminder: %s", exc)
        except Exception as exc:
            logger.error("Events deadline check failed: %s", exc, exc_info=True)
            with contextlib.suppress(Exception):
                await GlobalErrorHandler(
                    self.bot, self.engine, self.settings.telegram_admin_chat_id
                ).handle("events", "deadline_check", exc, {})

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Events scheduler stopped")
