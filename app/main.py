import logging

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from telegram import Bot
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import Settings
from integrations.scheduler import StrategistScheduler
from integrations.telegram.commands import (
    button_callback_approve,
    button_callback_reject,
    cmd_approve,
    cmd_plan,
    cmd_reject,
    cmd_report,
    cmd_status,
)

logger = logging.getLogger(__name__)

settings = Settings()
app = FastAPI(title="AI Marketing Team", version="0.1.0")

scheduler: StrategistScheduler | None = None
telegram_app: Application | None = None


@app.on_event("startup")
async def startup() -> None:
    """Initialize scheduler and Telegram bot on startup."""
    global scheduler, telegram_app

    logger.info("Starting up AI Marketing Team application")

    # Initialize database engine
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )

    # Initialize Telegram bot
    bot = Bot(token=settings.telegram_bot_token)

    # Initialize scheduler
    scheduler = StrategistScheduler(settings, engine, bot)
    scheduler.start()

    # Initialize Telegram command handlers
    telegram_app = Application.builder().token(settings.telegram_bot_token).build()

    # Add command handlers
    telegram_app.add_handler(CommandHandler("status", cmd_status))
    telegram_app.add_handler(CommandHandler("plan", cmd_plan))
    telegram_app.add_handler(CommandHandler("approve", cmd_approve))
    telegram_app.add_handler(CommandHandler("reject", cmd_reject))
    telegram_app.add_handler(CommandHandler("report", cmd_report))

    # Add button callbacks
    telegram_app.add_handler(
        CallbackQueryHandler(button_callback_approve, pattern=r"^approve_\d+$")
    )
    telegram_app.add_handler(
        CallbackQueryHandler(button_callback_reject, pattern=r"^reject_\d+$")
    )

    # Start polling in background
    await telegram_app.initialize()
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Clean up resources on shutdown."""
    global scheduler, telegram_app

    logger.info("Shutting down AI Marketing Team application")

    if scheduler:
        scheduler.shutdown()

    if telegram_app:
        await telegram_app.shutdown()

    logger.info("Application shutdown complete")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
