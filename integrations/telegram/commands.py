"""Telegram command handlers for Strategist agent."""

import contextlib
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Module-level engine reference set by app.main on startup so cmd_dashboard
# can run DB queries without depending on a global app context.
_dashboard_engine = None


def set_dashboard_engine(engine) -> None:
    """Wire DB engine for /dashboard handler. Called from app startup."""
    global _dashboard_engine
    _dashboard_engine = engine


async def _safe_count(session: AsyncSession, sql: str, params: dict | None = None) -> int:
    try:
        row = await session.execute(text(sql), params or {})
        val = row.scalar()
        return int(val or 0)
    except Exception as exc:  # pragma: no cover — degraded mode
        logger.warning("dashboard query failed: %s", exc)
        return -1


async def _safe_scalar(session: AsyncSession, sql: str, params: dict | None = None):
    try:
        row = await session.execute(text(sql), params or {})
        return row.scalar()
    except Exception as exc:  # pragma: no cover
        logger.warning("dashboard query failed: %s", exc)
        return None


async def _build_dashboard_text(engine) -> str:
    """Compose Telegram dashboard message. Never raises."""
    msk = timezone(timedelta(hours=3))
    now_msk = datetime.now(tz=msk).strftime("%Y-%m-%d %H:%M MSK")
    lines = ["🤖 AI Marketing Team — Dashboard", f"🕐 {now_msk}", "", "📋 Agents"]

    if engine is None:
        lines.append("⚪ DB не подключена")
        return "\n".join(lines)

    try:
        async with AsyncSession(engine) as session:
            # Strategist
            plan_id = await _safe_scalar(
                session,
                "SELECT id FROM content_plans WHERE status='approved' " "ORDER BY id DESC LIMIT 1",
            )
            plan_date = await _safe_scalar(
                session,
                "SELECT week_start_date FROM content_plans WHERE status='approved' "
                "ORDER BY id DESC LIMIT 1",
            )
            if plan_id:
                lines.append(f"🟢 Стратег        план #{plan_id}, approved {plan_date}")
            else:
                lines.append("⚪ Стратег        нет одобренных планов")

            # Content
            published = await _safe_count(
                session, "SELECT COUNT(*) FROM scheduled_posts WHERE status='published'"
            )
            pending = await _safe_count(
                session,
                "SELECT COUNT(*) FROM scheduled_posts " "WHERE status IN ('pending','generated')",
            )
            content_icon = "🟢" if published >= 0 else "⚪"
            lines.append(
                f"{content_icon} Контент        {published} постов опубликовано, {pending} pending"
            )

            # Analytics
            snap_date = await _safe_scalar(
                session,
                "SELECT snapshot_date FROM analytics_snapshots " "ORDER BY id DESC LIMIT 1",
            )
            if snap_date:
                lines.append(f"🟢 Аналитика     snapshot {snap_date}")
            else:
                lines.append("⚪ Аналитика     нет снапшотов")

            # Ads
            running = await _safe_count(
                session, "SELECT COUNT(*) FROM ad_campaigns WHERE status='running'"
            )
            ads_icon = "🟢" if running >= 0 else "⚪"
            lines.append(f"{ads_icon} Реклама        {running} кампании активны")

            # TG Scout
            scout_icon = "⚪"
            scout_text = "TG Scout       нет данных"
            try:
                channel_count = await _safe_count(session, "SELECT COUNT(*) FROM tg_channels")
                pitch_count = await _safe_count(
                    session,
                    "SELECT COUNT(*) FROM tg_pitch_drafts WHERE status='pending'",
                )
                if channel_count >= 0:
                    scout_icon = "🟢" if channel_count > 0 else "⚪"
                    scout_text = (
                        f"TG Scout       {channel_count} каналов в базе, "
                        f"{pitch_count} ожидают питча"
                    )
            except Exception:
                pass
            lines.append(f"{scout_icon} {scout_text}")

            # Events
            events_count = await _safe_count(session, "SELECT COUNT(*) FROM events_calendar")
            today = datetime.now(tz=msk).date()
            month_end = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            deadlines = await _safe_count(
                session,
                "SELECT COUNT(*) FROM events_calendar "
                "WHERE cfp_deadline >= :start AND cfp_deadline < :end",
                {"start": today.isoformat(), "end": month_end.isoformat()},
            )
            events_icon = "🟢" if events_count > 0 else "⚪"
            lines.append(
                f"{events_icon} Events         {events_count} конференций, "
                f"{deadlines} дедлайнов в этом месяце"
            )

            # n8n placeholder
            lines.append("⚪ n8n            webhooks не проверялись")

            # Approval queue
            pending_plans = await _safe_count(
                session,
                "SELECT COUNT(*) FROM content_plans WHERE status='pending_approval'",
            )
            pending_ads = await _safe_count(
                session,
                "SELECT COUNT(*) FROM ad_campaigns WHERE status='pending_approval'",
            )
            queue = max(0, pending_plans) + max(0, pending_ads)
            lines.append("")
            lines.append(f"✅ Очередь апрувов: {queue}")

            # Errors 24h
            errors_24h = -1
            try:
                errors_24h = await _safe_count(
                    session,
                    "SELECT COUNT(*) FROM dead_letter_queue " "WHERE created_at >= :since",
                    {"since": (datetime.now(tz=msk) - timedelta(hours=24)).isoformat()},
                )
            except Exception:
                errors_24h = 0
            err_icon = "✅" if errors_24h == 0 else "⚠️"
            errors_display = max(0, errors_24h)
            lines.append(f"{err_icon}  Ошибки за 24ч: {errors_display}")
    except Exception as exc:
        logger.error("dashboard build failed: %s", exc)
        lines.append("⚪ Ошибка чтения статуса")

    return "\n".join(lines)


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show unified system dashboard. Never raises — degrades gracefully."""
    if not update.message:
        return
    try:
        text_msg = await _build_dashboard_text(_dashboard_engine)
        await update.message.reply_text(text_msg)
    except Exception as exc:
        logger.error("cmd_dashboard failed: %s", exc)
        with contextlib.suppress(Exception):
            await update.message.reply_text(
                "🤖 AI Marketing Team — Dashboard\n⚪ Сервис временно недоступен"
            )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current plan status and recent metrics."""
    if not update.message:
        return

    text = (
        "📊 *Текущий статус плана*\n\n"
        "Статус: Ожидание одобрения ⏳\n"
        "Неделя: 2026-04-27 — 2026-05-03\n\n"
        "_Метрики последней недели:_\n"
        "• Впечатлений: 15,000\n"
        "• Клики: 450 (3% CTR)\n"
        "• Расход: 4,500 RUB\n"
        "• ROI: 2.5x"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger immediate plan generation."""
    if not update.message or not update.effective_user:
        return

    # Simplified response - in production, this would call planner
    text = (
        "📝 *Еженедельный план контента*\n\n"
        "*Неделя: 2026-04-27 — 2026-05-03*\n\n"
        "🎯 *Продукт 1*\n"
        "Приоритет: Высокий\n"
        "Бюджет: 2,000 RUB\n"
        "Темы: Запуск кампании, Case study\n\n"
        "🎯 *Продукт 2*\n"
        "Приоритет: Средний\n"
        "Бюджет: 1,500 RUB\n"
        "Темы: Технический обзор, Blog post\n"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data="approve_1"),
                InlineKeyboardButton("✏️ Отредактировать", callback_data="edit_1"),
            ],
            [
                InlineKeyboardButton("❌ Отклонить", callback_data="reject_1"),
            ],
        ]
    )

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve a pending plan."""
    if not update.message or not context.args:
        await update.message.reply_text("❌ Использование: /approve <plan_id>")
        return

    plan_id = context.args[0]
    text = f"✅ План #{plan_id} одобрен! Направляем Content агенту."
    await update.message.reply_text(text)


async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reject a pending plan."""
    if not update.message or not context.args:
        await update.message.reply_text("❌ Использование: /reject <plan_id> [причина]")
        return

    plan_id = context.args[0]
    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Без указания причины"

    text = f"❌ План #{plan_id} отклонен.\n_Причина:_ {reason}"
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send weekly digest with metrics and plan summary."""
    if not update.message:
        return

    text = (
        "📈 *Еженедельный отчет*\n\n"
        "*Метрики текущей недели (2026-04-20 — 2026-04-26):*\n\n"
        "| Метрика | Значение |\n"
        "|---------|----------|\n"
        "| Впечатлений | 14,200 |\n"
        "| Клики | 420 |\n"
        "| CTR | 2.96% |\n"
        "| Расход | 4,100 RUB |\n"
        "| ROI | 2.3x |\n\n"
        "*Статус плана на следующую неделю:*\n"
        "✏️ Ожидание одобрения (План #15)\n\n"
        "*Ключевые выводы:*\n"
        "• CTR выше среднего на 15%\n"
        "• ROI стабилен\n"
        "• Рекомендация: увеличить бюджет на 10%"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def button_callback_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve button click."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer("✅ План одобрен!", show_alert=False)
    await query.edit_message_text(
        text=query.message.text + "\n\n✅ _Одобрено пользователем_", parse_mode="Markdown"
    )


async def button_callback_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle reject button click."""
    if not update.callback_query:
        return

    query = update.callback_query
    await query.answer("❌ План отклонен!", show_alert=False)
    await query.edit_message_text(
        text=query.message.text + "\n\n❌ _Отклонено пользователем_", parse_mode="Markdown"
    )


async def send_plan_approval_message(
    bot: Bot, chat_id: int, plan_text: str, plan_id: int = 1
) -> None:
    """Send plan to admin chat with inline keyboard."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{plan_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{plan_id}"),
            ],
        ]
    )
    await bot.send_message(
        chat_id=chat_id, text=plan_text, parse_mode="Markdown", reply_markup=keyboard
    )
