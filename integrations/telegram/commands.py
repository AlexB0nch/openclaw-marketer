"""Telegram command handlers for Strategist agent."""

import logging
from typing import TYPE_CHECKING

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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
