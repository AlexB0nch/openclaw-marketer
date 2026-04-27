"""Monthly digest builder and sender for Events Agent."""

import logging
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings
from integrations.events.scraper import ConferenceEvent
from integrations.events.tracker import DeadlineTracker

logger = logging.getLogger(__name__)

_RUSSIAN_MONTH_NAMES: dict[int, str] = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def _format_event_block(event: ConferenceEvent) -> str:
    start_date_str = (
        event.start_date.strftime("%d.%m.%Y") if event.start_date else "дата уточняется"
    )
    cfp_deadline_str = (
        event.cfp_deadline.strftime("%d.%m.%Y") if event.cfp_deadline else "не указан"
    )
    city_or_online = event.city if event.city else "Онлайн"
    audience_size_str = f"{event.audience_size} чел." if event.audience_size else "? чел."
    return (
        f"📢 *{event.name}*\n"
        f"🗓 {start_date_str} | ⏰ CFP: {cfp_deadline_str}\n"
        f"📍 {city_or_online} | 👥 {audience_size_str}\n"
        f"🔗 {event.url}\n"
    )


def _load_event_from_row(row: tuple) -> ConferenceEvent:
    import json

    topics_raw = row[9] if len(row) > 9 else None
    try:
        topics = json.loads(topics_raw) if topics_raw else []
    except Exception:
        topics = []
    return ConferenceEvent(
        name=row[1],
        url=row[2],
        start_date=date.fromisoformat(row[3]) if row[3] else None,
        cfp_deadline=date.fromisoformat(row[4]) if row[4] else None,
        city=row[5],
        is_online=bool(row[6]),
        audience_size=row[7],
        description=row[8] or "",
        topics=topics,
        source=row[10] if len(row) > 10 else "",
        status=row[11] if len(row) > 11 else "new",
    )


class DigestBuilder:
    async def build_monthly_digest(self, session: AsyncSession) -> str:
        today = date.today()
        month_name = _RUSSIAN_MONTH_NAMES[today.month]
        year = today.year
        deadline_cutoff = today + timedelta(days=30)

        deadline_result = await session.execute(
            text(
                "SELECT id, name, url, start_date, cfp_deadline, city, is_online, "
                "audience_size, description, topics, source, status "
                "FROM events_calendar "
                "WHERE status = 'relevant' AND cfp_deadline <= :cutoff "
                "ORDER BY cfp_deadline ASC"
            ),
            {"cutoff": deadline_cutoff.isoformat()},
        )
        deadline_events = deadline_result.fetchall()

        upcoming_result = await session.execute(
            text(
                "SELECT id, name, url, start_date, cfp_deadline, city, is_online, "
                "audience_size, description, topics, source, status "
                "FROM events_calendar "
                "WHERE status = 'relevant' "
                "ORDER BY CASE WHEN start_date IS NULL THEN 1 ELSE 0 END, start_date ASC"
            )
        )
        upcoming_events = upcoming_result.fetchall()

        total = len(upcoming_events)

        lines: list[str] = [f"📅 *Конференции — {month_name} {year}*\n"]

        lines.append("🔥 *Дедлайн в этом месяце*\n")
        if deadline_events:
            for row in deadline_events:
                event = _load_event_from_row(row)
                lines.append(_format_event_block(event))
        else:
            lines.append("_Нет дедлайнов в ближайшие 30 дней_\n")

        lines.append("\n📆 *Предстоящие события*\n")
        if upcoming_events:
            for row in upcoming_events:
                event = _load_event_from_row(row)
                lines.append(_format_event_block(event))
        else:
            lines.append("_Нет предстоящих релевантных событий_\n")

        lines.append(f"\n📊 Всего релевантных: {total}")
        lines.append("ℹ️ Подача заявки — только с вашего апрува")

        return "\n".join(lines)

    async def send_monthly_digest(self, session: AsyncSession, bot) -> None:
        settings = Settings()
        chat_id = settings.telegram_admin_chat_id

        digest_text = await self.build_monthly_digest(session)
        await bot.send_message(chat_id=chat_id, text=digest_text, parse_mode="Markdown")

        result = await session.execute(
            text(
                "SELECT id, name, url, cfp_deadline FROM events_calendar "
                "WHERE status = 'relevant' AND cfp_deadline IS NOT NULL"
            )
        )
        rows = result.fetchall()

        for row in rows:
            event_id, name, url, _ = row[0], row[1], row[2], row[3]
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📝 Черновик заявки",
                            callback_data=f"events_draft:{event_id}",
                        ),
                        InlineKeyboardButton(
                            "❌ Пропустить",
                            callback_data=f"events_skip:{event_id}",
                        ),
                    ]
                ]
            )
            await bot.send_message(
                chat_id=chat_id,
                text=f"*{name}*\n🔗 {url}",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )

    async def handle_draft_callback(self, session: AsyncSession, bot, callback_data: str) -> None:
        event_id = int(callback_data.split(":")[1])
        settings = Settings()
        chat_id = settings.telegram_admin_chat_id

        result = await session.execute(
            text(
                "SELECT id, name, url, start_date, cfp_deadline, city, is_online, "
                "audience_size, description, topics, source, status "
                "FROM events_calendar WHERE id = :id"
            ),
            {"id": event_id},
        )
        row = result.fetchone()
        if not row:
            await bot.send_message(chat_id=chat_id, text="Событие не найдено.")
            return

        event = _load_event_from_row(row)
        tracker = DeadlineTracker()
        abstract = await tracker.generate_abstract_draft(event, "ai_assistant")

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Подать заявку (заглушка)",
                        callback_data=f"events_apply:{event_id}",
                    ),
                    InlineKeyboardButton(
                        "✏️ Редактировать",
                        callback_data=f"events_edit:{event_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ Отклонить",
                        callback_data=f"events_reject:{event_id}",
                    ),
                ]
            ]
        )
        await bot.send_message(
            chat_id=chat_id,
            text=abstract or "Не удалось сгенерировать черновик.",
            reply_markup=keyboard,
        )

    async def handle_skip_callback(self, session: AsyncSession, callback_data: str) -> None:
        event_id = int(callback_data.split(":")[1])
        await session.execute(
            text("UPDATE events_calendar SET status='skipped' WHERE id=:id"),
            {"id": event_id},
        )
        await session.commit()

    async def handle_apply_callback(
        self,
        session: AsyncSession,
        bot,
        callback_data: str,
        chat_id: str,
    ) -> None:
        event_id = int(callback_data.split(":")[1])

        result = await session.execute(
            text("SELECT id, name, url FROM events_calendar WHERE id = :id"),
            {"id": event_id},
        )
        row = result.fetchone()
        if not row:
            await bot.send_message(chat_id=chat_id, text="Событие не найдено.")
            return

        _, _name, url = row[0], row[1], row[2]

        await session.execute(
            text(
                "INSERT INTO events_applications (event_id, product, action) "
                "VALUES (:event_id, :product, :action)"
            ),
            {"event_id": event_id, "product": "ai_assistant", "action": "registered"},
        )
        await session.commit()

        await bot.send_message(
            chat_id=chat_id,
            text=(f"✅ Заявка зарегистрирована в системе.\n" f"Отправьте вручную по ссылке: {url}"),
        )
