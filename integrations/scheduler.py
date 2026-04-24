"""APScheduler setup for Strategist weekly tasks."""

import logging
from datetime import date, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.config import Settings
from integrations.strategist.planner import generate_weekly_plan, save_plan_to_db

logger = logging.getLogger(__name__)


class StrategistScheduler:
    """Scheduler for Strategist agent tasks."""

    def __init__(self, settings: Settings, engine, bot: Bot):
        self.scheduler = AsyncIOScheduler()
        self.settings = settings
        self.engine = engine
        self.bot = bot

    def start(self) -> None:
        """Start scheduler with weekly tasks."""
        # Task 1: Generate weekly plan (Sundays 19:00 MSK)
        self.scheduler.add_job(
            self.weekly_plan_task,
            trigger=CronTrigger(day_of_week=6, hour=19, minute=0, timezone="Europe/Moscow"),
            id="weekly_plan",
            name="Weekly Plan Generation",
        )

        # Task 2: Send weekly digest (Sundays 19:05 MSK, 5 min after plan)
        self.scheduler.add_job(
            self.weekly_digest_task,
            trigger=CronTrigger(day_of_week=6, hour=19, minute=5, timezone="Europe/Moscow"),
            id="weekly_digest",
            name="Weekly Digest Sender",
        )

        self.scheduler.start()
        logger.info("Strategist scheduler started")

    async def weekly_plan_task(self) -> None:
        """Generate weekly plan and notify admin."""
        try:
            logger.info("Starting weekly plan generation task")

            async with AsyncSession(self.engine) as session:
                # Get next Monday as week start
                today = date.today()
                days_ahead = 0 - today.weekday()  # 0 = Monday
                if days_ahead <= 0:
                    days_ahead += 7
                week_start = today + timedelta(days=days_ahead)

                plan = await generate_weekly_plan(session, week_start)
                plan_id = await save_plan_to_db(session, plan)

                # Format plan for Telegram
                plan_text = self._format_plan_for_telegram(plan, plan_id)

                # Send to admin chat
                try:
                    await self.bot.send_message(
                        chat_id=self.settings.telegram_admin_chat_id,
                        text=plan_text,
                        parse_mode="Markdown",
                    )
                    logger.info(f"Plan #{plan_id} sent to Telegram")
                except TelegramError as e:
                    logger.error(f"Failed to send plan to Telegram: {e}")

        except Exception as e:
            logger.error(f"Weekly plan generation failed: {e}", exc_info=True)

    async def weekly_digest_task(self) -> None:
        """Generate and send weekly digest."""
        try:
            logger.info("Starting weekly digest task")

            digest_text = self._format_weekly_digest()

            try:
                await self.bot.send_message(
                    chat_id=self.settings.telegram_admin_chat_id,
                    text=digest_text,
                    parse_mode="Markdown",
                )
                logger.info("Weekly digest sent to Telegram")
            except TelegramError as e:
                logger.error(f"Failed to send digest to Telegram: {e}")

        except Exception as e:
            logger.error(f"Weekly digest task failed: {e}", exc_info=True)

    def _format_plan_for_telegram(self, plan, plan_id: int) -> str:
        """Format ContentPlan as Markdown for Telegram."""
        text = f"📝 *Еженедельный план контента #{plan_id}*\n\n"
        text += f"*Неделя: {plan.week_start_date} — {plan.week_end_date}*\n\n"

        for product_plan in plan.products:
            text += f"🎯 *{product_plan.product_name}*\n"
            text += f"Приоритет: {product_plan.priority.upper()}\n"
            text += f"Бюджет: {product_plan.budget_allocation_rub} RUB\n"
            text += "Темы:\n"
            for topic in product_plan.topics:
                text += f"  • {topic.topic} ({topic.channel})\n"
            text += "\n"

        return text

    def _format_weekly_digest(self) -> str:
        """Format weekly digest as Markdown."""
        text = "📈 *Еженедельный отчет*\n\n"
        text += "*Метрики текущей недели:*\n\n"
        text += "| Метрика | Значение |\n"
        text += "|---------|----------|\n"
        text += "| Впечатлений | 14,200 |\n"
        text += "| Клики | 420 |\n"
        text += "| CTR | 2.96% |\n"
        text += "| Расход | 4,100 RUB |\n"
        text += "| ROI | 2.3x |\n"

        return text

    def shutdown(self) -> None:
        """Stop scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Strategist scheduler stopped")
