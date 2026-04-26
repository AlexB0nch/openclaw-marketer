"""APScheduler setup for TG Scout weekly pipeline and mention monitor."""

from __future__ import annotations

import asyncio
import logging
import os

import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.config import Settings
from integrations.telegram.monitor import MentionMonitor
from integrations.telegram.outreach import OutreachManager
from integrations.telegram.pitch import PitchGenerator
from integrations.telegram.scorer import RelevanceScorer
from integrations.telegram.scout import TelegramScout
from integrations.telegram.tgstat_client import TGStatClient

logger = logging.getLogger(__name__)

_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "ai_assistant": ["AI помощник", "переписка", "email автоматизация", "B2B инструменты"],
    "ai_trainer": ["спорт", "тренировки", "фитнес", "спортивный коуч", "ЗОЖ"],
    "ai_news": ["новости", "дайджест", "агрегатор", "IT новости", "технологии"],
}


class ScoutScheduler:
    def __init__(self, settings: Settings, engine, bot: Bot, telethon_client) -> None:
        self.scheduler = AsyncIOScheduler()
        self._settings = settings
        self._engine = engine
        self._bot = bot
        self._telethon_client = telethon_client
        self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def start(self) -> None:
        """Register weekly scout job and start mention monitor."""
        self.scheduler.add_job(
            self.run_weekly_scout,
            trigger=CronTrigger(
                day_of_week=0, hour=9, minute=0, timezone="Europe/Moscow"
            ),
            id="scout_weekly_search",
            name="TG Scout Weekly Search",
        )
        self.scheduler.start()

        asyncio.create_task(self.start_mention_monitor())
        logger.info("ScoutScheduler started")

    async def run_weekly_scout(self) -> None:
        """Full pipeline: search → enrich → score → generate pitches → send digest."""
        logger.info("Starting weekly scout pipeline")
        scout = TelegramScout(
            api_id=self._settings.telethon_api_id,
            api_hash=self._settings.telethon_api_hash,
            session_path=self._settings.telethon_session_path,
        )
        tgstat = TGStatClient(self._settings.tgstat_api_key)
        scorer = RelevanceScorer(self._anthropic)
        pitcher = PitchGenerator(self._anthropic)
        outreach = OutreachManager(self._settings)

        async with AsyncSession(self._engine) as session:
            for product, keywords in _PRODUCT_KEYWORDS.items():
                try:
                    channels = await scout.search_channels(keywords)
                    channels = await tgstat.enrich_channels(channels)
                    await scout.save_channels(session, channels)

                    scores = await scorer.batch_score(channels, product)
                    await scorer.save_scores(session, scores)

                    pairs = list(zip(channels, scores))
                    drafts = await pitcher.batch_generate(pairs, product)
                    for draft in drafts:
                        await pitcher.save_draft(session, draft)

                    logger.info(
                        "Scout pipeline done for product=%s: %d channels", product, len(channels)
                    )
                except Exception as exc:
                    logger.error("Scout pipeline failed for product=%s: %s", product, exc)

            try:
                await outreach.send_weekly_digest(session, self._bot)
            except Exception as exc:
                logger.error("send_weekly_digest failed: %s", exc)

    async def start_mention_monitor(self) -> None:
        """Start MentionMonitor as a background coroutine."""
        keywords_raw = os.getenv("MONITOR_KEYWORDS", "")
        keywords = [kw.strip() for kw in keywords_raw.split(",") if kw.strip()]

        monitor = MentionMonitor(
            telethon_client=self._telethon_client,
            keywords=keywords,
            admin_chat_id=int(self._settings.telegram_admin_chat_id),
        )
        try:
            await monitor.start_monitoring(self._bot)
        except Exception as exc:
            logger.error("MentionMonitor crashed: %s", exc)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("ScoutScheduler stopped")
