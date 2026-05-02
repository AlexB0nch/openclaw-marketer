import logging
import os

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from telegram import Bot, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from app.config import Settings
from integrations.ads.approval import AdsApprovalManager
from integrations.ads.scheduler import AdsScheduler
from integrations.analytics.scheduler import AnalyticsScheduler
from integrations.content.router import router as content_router
from integrations.events.events_router import router as events_router
from integrations.events.events_scheduler import EventsScheduler
from integrations.scheduler import StrategistScheduler
from integrations.telegram.commands import (
    button_callback_approve,
    button_callback_reject,
    cmd_approve,
    cmd_dashboard,
    cmd_plan,
    cmd_reject,
    cmd_report,
    cmd_status,
    set_dashboard_engine,
)
from integrations.telegram.scout_router import router as scout_router
from integrations.yandex_direct.client import YandexDirectClient

logger = logging.getLogger(__name__)

settings = Settings()
app = FastAPI(title="AI Marketing Team", version="1.0.0")
app.include_router(content_router)
app.include_router(scout_router)
app.include_router(events_router)

scheduler: StrategistScheduler | None = None
analytics_scheduler: AnalyticsScheduler | None = None
ads_scheduler: AdsScheduler | None = None
events_scheduler: EventsScheduler | None = None
scout_scheduler = None
telegram_app: Application | None = None
_db_engine = None


# ── Ads Agent Telegram callback handlers ─────────────────────────────────────


async def _ads_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ads_approve:<campaign_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    campaign_id = int(query.data.split(":")[1])
    actor = query.from_user.username or str(query.from_user.id)

    try:
        yandex_client = YandexDirectClient(settings)
        approval_manager = AdsApprovalManager()
        async with AsyncSession(_db_engine) as session:
            await approval_manager.handle_approval_callback(
                session=session,
                yandex_client=yandex_client,
                campaign_id=campaign_id,
                actor=actor,
            )
        await query.edit_message_text(
            f"\u2705 Кампания #{campaign_id} запущена оператором {actor}."
        )
        logger.info("Ads campaign %d approved via Telegram by %s", campaign_id, actor)
    except Exception as exc:
        logger.error("Ads approve callback failed for campaign %d: %s", campaign_id, exc)
        await query.edit_message_text(f"\u274c Ошибка при запуске кампании #{campaign_id}: {exc}")


async def _ads_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ads_edit:<campaign_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    campaign_id = int(query.data.split(":")[1])
    await query.edit_message_text(
        f"\u270f\ufe0f Кампания #{campaign_id} отправлена на доработку. "
        "Отредактируйте конфиг и повторно запросите одобрение."
    )
    logger.info("Ads campaign %d sent back for editing", campaign_id)


async def _ads_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ads_reject:<campaign_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    campaign_id = int(query.data.split(":")[1])
    actor = query.from_user.username or str(query.from_user.id)

    try:
        approval_manager = AdsApprovalManager()
        async with AsyncSession(_db_engine) as session:
            await approval_manager.handle_rejection_callback(
                session=session,
                campaign_id=campaign_id,
                actor=actor,
            )
        await query.edit_message_text(
            f"\u274c Кампания #{campaign_id} отклонена оператором {actor}."
        )
        logger.info("Ads campaign %d rejected via Telegram by %s", campaign_id, actor)
    except Exception as exc:
        logger.error("Ads reject callback failed for campaign %d: %s", campaign_id, exc)
        await query.edit_message_text(
            f"\u274c Ошибка при отклонении кампании #{campaign_id}: {exc}"
        )


# ── Events Agent Telegram callback handlers ───────────────────────────────────


async def _events_draft_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle events_draft:<event_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    try:
        from integrations.events.digest import DigestBuilder

        builder = DigestBuilder()
        async with AsyncSession(_db_engine) as session:
            await builder.handle_draft_callback(session, query.get_bot(), query.data)
    except Exception as exc:
        logger.error("Events draft callback failed: %s", exc)
        await query.edit_message_text(f"\u274c Ошибка при генерации черновика: {exc}")


async def _events_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle events_skip:<event_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    try:
        from integrations.events.digest import DigestBuilder

        builder = DigestBuilder()
        async with AsyncSession(_db_engine) as session:
            await builder.handle_skip_callback(session, query.data)
        await query.edit_message_text("\u274c Событие пропущено.")
    except Exception as exc:
        logger.error("Events skip callback failed: %s", exc)
        await query.edit_message_text(f"\u274c Ошибка при пропуске события: {exc}")


async def _events_apply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle events_apply:<event_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    try:
        from integrations.events.digest import DigestBuilder

        builder = DigestBuilder()
        async with AsyncSession(_db_engine) as session:
            await builder.handle_apply_callback(
                session, query.get_bot(), query.data, settings.telegram_admin_chat_id
            )
    except Exception as exc:
        logger.error("Events apply callback failed: %s", exc)
        await query.edit_message_text(f"\u274c Ошибка: {exc}")


async def _events_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle events_reject:<event_id> inline button callback."""
    query = update.callback_query
    await query.answer()
    if query.data is None:
        return
    event_id = int(query.data.split(":")[1])
    await query.edit_message_text(f"\u274c Заявка для события #{event_id} отклонена.")
    logger.info("Events application rejected for event %d", event_id)


# ── Application lifecycle ─────────────────────────────────────────────────────


@app.on_event("startup")
async def startup() -> None:
    """Initialize scheduler and Telegram bot on startup."""
    global scheduler, analytics_scheduler, ads_scheduler, events_scheduler, scout_scheduler, telegram_app, _db_engine

    logger.info("Starting up AI Marketing Team application")

    _db_engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
    )
    set_dashboard_engine(_db_engine)

    bot = Bot(token=settings.telegram_bot_token)

    scheduler = StrategistScheduler(settings, _db_engine, bot)
    scheduler.start()

    analytics_scheduler = AnalyticsScheduler(settings, _db_engine, bot)
    analytics_scheduler.start()

    ads_scheduler = AdsScheduler(settings, _db_engine, bot)
    ads_scheduler.start()

    if settings.events_enabled:
        events_scheduler = EventsScheduler(settings, _db_engine, bot)
        events_scheduler.start()
        logger.info("Events Agent enabled and started")

    if settings.telethon_api_id:
        from telethon import TelegramClient

        from integrations.telegram.scout_scheduler import ScoutScheduler

        session_path = settings.telethon_session_path
        abs_session_path = os.path.abspath(session_path)
        # Telethon appends ".session" if missing — mirror that for the existence check
        session_file = abs_session_path
        if not session_file.endswith(".session"):
            session_file = session_file + ".session"
        session_exists = os.path.exists(session_file)
        logger.info(
            "Telethon session file: path=%s abs=%s exists=%s",
            session_path,
            abs_session_path,
            session_exists,
        )

        telethon_client = TelegramClient(
            session_path,
            settings.telethon_api_id,
            settings.telethon_api_hash,
        )
        await telethon_client.connect()
        telethon_ready = await telethon_client.is_user_authorized()
        logger.debug(
            "Telethon session check: path=%s authorized=%s", session_path, telethon_ready
        )

        if not telethon_ready:
            logger.warning(
                "Telethon session not authorized — MentionMonitor disabled. "
                "Session file %s (exists=%s). "
                "Run scripts/telethon_login.py to authorize.",
                session_file,
                session_exists,
            )
        elif not settings.telegram_enable_scout:
            logger.info("TG Scout Agent disabled via TELEGRAM_ENABLE_SCOUT=false")
        else:
            scout_scheduler = ScoutScheduler(settings, _db_engine, bot, telethon_client)
            scout_scheduler.start()
            logger.info("TG Scout Agent enabled and started")

    telegram_app = Application.builder().token(settings.telegram_bot_token).build()

    telegram_app.add_handler(CommandHandler("status", cmd_status))
    telegram_app.add_handler(CommandHandler("plan", cmd_plan))
    telegram_app.add_handler(CommandHandler("approve", cmd_approve))
    telegram_app.add_handler(CommandHandler("reject", cmd_reject))
    telegram_app.add_handler(CommandHandler("report", cmd_report))
    telegram_app.add_handler(CommandHandler("dashboard", cmd_dashboard))

    telegram_app.add_handler(
        CallbackQueryHandler(button_callback_approve, pattern=r"^approve_\d+$")
    )
    telegram_app.add_handler(CallbackQueryHandler(button_callback_reject, pattern=r"^reject_\d+$"))

    telegram_app.add_handler(
        CallbackQueryHandler(_ads_approve_callback, pattern=r"^ads_approve:\d+$")
    )
    telegram_app.add_handler(CallbackQueryHandler(_ads_edit_callback, pattern=r"^ads_edit:\d+$"))
    telegram_app.add_handler(
        CallbackQueryHandler(_ads_reject_callback, pattern=r"^ads_reject:\d+$")
    )

    telegram_app.add_handler(
        CallbackQueryHandler(_events_draft_callback, pattern=r"^events_draft:\d+$")
    )
    telegram_app.add_handler(
        CallbackQueryHandler(_events_skip_callback, pattern=r"^events_skip:\d+$")
    )
    telegram_app.add_handler(
        CallbackQueryHandler(_events_apply_callback, pattern=r"^events_apply:\d+$")
    )
    telegram_app.add_handler(
        CallbackQueryHandler(_events_reject_callback, pattern=r"^events_reject:\d+$")
    )

    await telegram_app.initialize()
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Clean up resources on shutdown."""
    global scheduler, analytics_scheduler, ads_scheduler, events_scheduler, scout_scheduler, telegram_app

    logger.info("Shutting down AI Marketing Team application")

    if scheduler:
        scheduler.shutdown()

    if analytics_scheduler:
        analytics_scheduler.shutdown()

    if ads_scheduler:
        ads_scheduler.shutdown()

    if events_scheduler:
        events_scheduler.shutdown()

    if scout_scheduler:
        scout_scheduler.shutdown()

    if telegram_app:
        await telegram_app.shutdown()

    logger.info("Application shutdown complete")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
