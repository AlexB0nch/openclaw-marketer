"""Editorial calendar: scheduling and CRUD for ScheduledPost."""

import zoneinfo
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.content.models import Platform, ScheduledPost
from integrations.strategist.models import ContentPlan

_MSK = zoneinfo.ZoneInfo("Europe/Moscow")
_PUBLISH_HOURS = [9, 12, 18]

# Map Strategist channel names → Content Agent platforms
_CHANNEL_TO_PLATFORM: dict[str, Platform] = {
    "telegram": "telegram",
    "blog": "vc.ru",
    "habr": "habr",
    "linkedin": "linkedin",
    # youtube is not yet supported; skipped in generate_week_schedule
}


def _week_slots(week_start: date) -> list[datetime]:
    """Return all 21 publication slots (7 days × 3 times) in MSK timezone."""
    slots: list[datetime] = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        for hour in _PUBLISH_HOURS:
            slots.append(datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=_MSK))
    return slots


class CalendarManager:
    """Manages the editorial calendar for the Content Agent."""

    def generate_week_schedule(self, content_plan: ContentPlan) -> list[ScheduledPost]:
        """
        Turn an approved ContentPlan into ScheduledPost slot objects.

        Topics are assigned to 09:00, 12:00, 18:00 MSK slots in week order.
        Unsupported channels (youtube) are skipped.
        Body is empty at this stage — ContentGenerator fills it later.
        """
        slots = _week_slots(content_plan.week_start_date)
        posts: list[ScheduledPost] = []
        slot_index = 0

        for product in content_plan.products:
            for entry in product.topics:
                platform = _CHANNEL_TO_PLATFORM.get(entry.channel)
                if platform is None:
                    continue  # skip unsupported channels (e.g. youtube)
                if slot_index >= len(slots):
                    break  # no more slots this week
                posts.append(
                    ScheduledPost(
                        content_plan_id=None,  # filled after DB save of the plan
                        product_id=product.product_id,
                        product_name=product.product_name,
                        platform=platform,
                        topic=entry.topic,
                        body="",
                        scheduled_at=slots[slot_index],
                        status="pending",
                    )
                )
                slot_index += 1

        return posts

    async def save_scheduled_post(
        self,
        session: AsyncSession,
        post: ScheduledPost,
        content_plan_id: int | None = None,
    ) -> int:
        """Persist a ScheduledPost and return its DB id."""
        stmt = text("""INSERT INTO scheduled_posts
               (content_plan_id, product_id, product_name, platform, topic,
                body, scheduled_at, status)
               VALUES (:plan_id, :product_id, :product_name, :platform, :topic,
                       :body, :scheduled_at, :status)
               RETURNING id""")
        result = await session.execute(
            stmt,
            {
                "plan_id": content_plan_id if content_plan_id is not None else post.content_plan_id,
                "product_id": post.product_id,
                "product_name": post.product_name,
                "platform": post.platform,
                "topic": post.topic,
                "body": post.body,
                "scheduled_at": post.scheduled_at,
                "status": post.status,
            },
        )
        row = result.first()
        await session.commit()
        return row[0]  # type: ignore[index]

    async def get_pending_posts(
        self,
        session: AsyncSession,
        for_date: date,
    ) -> list[ScheduledPost]:
        """Return all pending/generated posts scheduled on for_date (MSK day boundaries)."""
        # Use a day-range comparison so the query works with both
        # SQLite (naive datetime text) and PostgreSQL (TIMESTAMPTZ).
        day_start = datetime(for_date.year, for_date.month, for_date.day, 0, 0, 0, tzinfo=_MSK)
        day_end = day_start + timedelta(days=1)

        stmt = text("""SELECT id, content_plan_id, product_id, product_name, platform, topic,
                      body, scheduled_at, status, published_at, telegram_message_id, created_at
               FROM scheduled_posts
               WHERE scheduled_at >= :day_start
                 AND scheduled_at  < :day_end
                 AND status IN ('pending', 'generated')
               ORDER BY scheduled_at""")
        result = await session.execute(stmt, {"day_start": day_start, "day_end": day_end})
        return [_row_to_post(row) for row in result.fetchall()]

    async def get_post_by_id(self, session: AsyncSession, post_id: int) -> ScheduledPost | None:
        """Fetch a single ScheduledPost by primary key."""
        stmt = text("""SELECT id, content_plan_id, product_id, product_name, platform, topic,
                      body, scheduled_at, status, published_at, telegram_message_id, created_at
               FROM scheduled_posts WHERE id = :post_id""")
        result = await session.execute(stmt, {"post_id": post_id})
        row = result.first()
        return _row_to_post(row) if row else None

    async def update_post_body(
        self,
        session: AsyncSession,
        post_id: int,
        body: str,
    ) -> None:
        """Store generated body text and advance status to 'generated'."""
        stmt = text("""UPDATE scheduled_posts
               SET body = :body, status = 'generated'
               WHERE id = :post_id""")
        await session.execute(stmt, {"body": body, "post_id": post_id})
        await session.commit()

    async def mark_published(
        self,
        session: AsyncSession,
        post_id: int,
        published_at: datetime,
        telegram_message_id: int | None = None,
    ) -> None:
        """Mark post as published and record delivery metadata."""
        stmt = text("""UPDATE scheduled_posts
               SET status = 'published',
                   published_at = :published_at,
                   telegram_message_id = :message_id
               WHERE id = :post_id""")
        await session.execute(
            stmt,
            {"post_id": post_id, "published_at": published_at, "message_id": telegram_message_id},
        )
        await session.commit()

    async def mark_failed(self, session: AsyncSession, post_id: int) -> None:
        """Mark post as failed (after exhausting retries)."""
        stmt = text("UPDATE scheduled_posts SET status = 'failed' WHERE id = :post_id")
        await session.execute(stmt, {"post_id": post_id})
        await session.commit()


def _row_to_post(row: tuple) -> ScheduledPost:  # type: ignore[type-arg]
    return ScheduledPost(
        id=row[0],
        content_plan_id=row[1],
        product_id=row[2],
        product_name=row[3],
        platform=row[4],
        topic=row[5],
        body=row[6],
        scheduled_at=row[7],
        status=row[8],
        published_at=row[9],
        telegram_message_id=row[10],
        created_at=row[11],
    )
