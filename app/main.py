import logging
import os

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from telegram import Bot, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

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

# Configure the root logger so INFO-level messages from `app.*` and
# `integrations.*` reach Docker stdout. Uvicorn's default LOGGING_CONFIG
# only attaches handlers to the `uvicorn`, `uvicorn.error`, and
# `uvicorn.access` loggers — the root logger stays bare, which means
# our `logger.info(...)` calls would otherwise fall through to
# `logging.lastResort` (WARNING-only) and disappear silently.
# `force=True` overrides any pre-existing handlers so this is robust
# regardless of import/startup ordering.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)
# Belt-and-braces: a logger Uvicorn always renders, used for the
# critical Scout startup lines so they cannot be silently dropped.
_startup_logger = logging.getLogger("uvicorn.error")

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

    scout_enabled = settings.telegram_enable_scout
    session_path = settings.telethon_session_path
    abs_session_path = os.path.abspath(session_path)
    # Telethon appends ".session" if missing — mirror that for the existence check
    session_file = (
        abs_session_path if abs_session_path.endswith(".session") else abs_session_path + ".session"
    )
    session_exists = os.path.exists(session_file)

    if not settings.telethon_api_id:
        logger.info(
            "Telethon startup: TELETHON_API_ID not set — Scout disabled. "
            "scout_enabled=%s session_path=%s exists=%s authorized=%s",
            scout_enabled,
            session_file,
            session_exists,
            None,
        )
    else:
        from telethon import TelegramClient

        from integrations.telegram.scout_scheduler import ScoutScheduler

        telethon_client = TelegramClient(
            session_path,
            settings.telethon_api_id,
            settings.telethon_api_hash,
        )
        await telethon_client.connect()
        authorized = await telethon_client.is_user_authorized()
        logger.info(
            "Telethon startup: scout_enabled=%s session_path=%s exists=%s authorized=%s",
            scout_enabled,
            session_file,
            session_exists,
            authorized,
        )

        if not authorized:
            logger.warning(
                "Telethon session not authorized — MentionMonitor disabled. "
                "Session file %s (exists=%s). "
                "Run scripts/telethon_login.py to authorize.",
                session_file,
                session_exists,
            )
        elif not scout_enabled:
            logger.info("TG Scout disabled by TELEGRAM_ENABLE_SCOUT=false")
        else:
            # Use uvicorn.error here so the lines surface in Docker logs
            # even if root-logger config is somehow overridden later.
            _startup_logger.info(
                "About to start TG Scout: scout_enabled=%s authorized=%s",
                scout_enabled,
                authorized,
            )
            scout_scheduler = ScoutScheduler(settings, _db_engine, bot, telethon_client)
            scout_scheduler.start()
            _startup_logger.info("TG Scout start() completed")
            # MentionMonitor is started indirectly: ScoutScheduler.start()
            # spawns asyncio.create_task(self.start_mention_monitor()),
            # which calls MentionMonitor(...).start_monitoring(bot).
            logger.info("TG Scout & MentionMonitor started")

    telegram_app = Application.builder().token(settings.telegram_bot_token).build()

    # Restrict /commands to the admin chat only — non-admin users won't match
    # any handler so their messages are silently ignored.
    try:
        admin_chat_id = int(settings.telegram_admin_chat_id)
        admin_filter = filters.Chat(chat_id=admin_chat_id)
    except (TypeError, ValueError):
        logger.warning(
            "TELEGRAM_ADMIN_CHAT_ID=%r is not a valid int — commands will be open to all chats",
            settings.telegram_admin_chat_id,
        )
        admin_filter = None

    telegram_app.add_handler(CommandHandler("status", cmd_status, filters=admin_filter))
    telegram_app.add_handler(CommandHandler("plan", cmd_plan, filters=admin_filter))
    telegram_app.add_handler(CommandHandler("approve", cmd_approve, filters=admin_filter))
    telegram_app.add_handler(CommandHandler("reject", cmd_reject, filters=admin_filter))
    telegram_app.add_handler(CommandHandler("report", cmd_report, filters=admin_filter))
    telegram_app.add_handler(CommandHandler("dashboard", cmd_dashboard, filters=admin_filter))

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

    # Full PTB v20+ async lifecycle: initialize() alone only wires the bot
    # object — it does NOT long-poll. Updates arrive only after start() +
    # updater.start_polling(). Without these calls /status, /plan, /report,
    # /dashboard never reach their handlers.
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    try:
        bot_user = await telegram_app.bot.get_me()
        bot_username = bot_user.username or "<unknown>"
    except Exception as exc:  # pragma: no cover — diagnostic only
        logger.warning("get_me() failed after polling started: %s", exc)
        bot_username = "<unknown>"
    _startup_logger.info("Telegram bot polling started, bot=@%s", bot_username)
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
        # Reverse of startup: stop the long-poll loop first, then the
        # application, then release resources.
        try:
            if telegram_app.updater and telegram_app.updater.running:
                await telegram_app.updater.stop()
            if telegram_app.running:
                await telegram_app.stop()
        except Exception as exc:  # pragma: no cover — diagnostic only
            logger.warning("Telegram bot stop failed: %s", exc)
        await telegram_app.shutdown()
        _startup_logger.info("Telegram bot polling stopped")

    logger.info("Application shutdown complete")


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
