"""FastAPI router for Events Agent HTTP endpoints."""

import json
import logging
from datetime import date as date_type
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from integrations.events.digest import DigestBuilder
from integrations.events.filter import RelevanceFilter, RelevantEvent, save_relevance
from integrations.events.scraper import ConferenceEvent, ConferenceScraper, save_events
from integrations.events.tracker import DeadlineTracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/events", tags=["events"])

_engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
_async_session = sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

PRODUCTS = ["ai_assistant", "ai_trainer", "ai_news"]


async def get_session() -> AsyncSession:  # type: ignore[misc]
    async with _async_session() as session:
        yield session


# Request/response models
class ScrapeResponse(BaseModel):
    count: int
    events: list[ConferenceEvent]


class FilterResponse(BaseModel):
    count: int
    relevant: list[RelevantEvent]


class CalendarResponse(BaseModel):
    count: int
    events: list[ConferenceEvent]


class AbstractResponse(BaseModel):
    event_id: int
    abstract: str


# Endpoints
@router.post("/scrape", response_model=ScrapeResponse)
async def trigger_scrape(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> ScrapeResponse:
    scraper = ConferenceScraper()
    try:
        events = await scraper.scrape_all()
    finally:
        await scraper.close()
    await save_events(session, events)
    return ScrapeResponse(count=len(events), events=events)


@router.post("/filter", response_model=FilterResponse)
async def trigger_filter(
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FilterResponse:
    f = RelevanceFilter()
    all_rows = await session.execute(
        text(
            "SELECT name, url, start_date, cfp_deadline, city, is_online, audience_size,"
            " description, topics, source, status FROM events_calendar"
        )
    )
    events = []
    for r in all_rows.fetchall():
        events.append(
            ConferenceEvent(
                name=r[0],
                url=r[1],
                start_date=date_type.fromisoformat(r[2]) if r[2] else None,
                cfp_deadline=date_type.fromisoformat(r[3]) if r[3] else None,
                city=r[4],
                is_online=bool(r[5]),
                audience_size=r[6],
                description=r[7] or "",
                topics=json.loads(r[8]) if r[8] else [],
                source=r[9] or "",
                status=r[10] or "new",
            )
        )
    relevant = await f.filter_relevant(events, PRODUCTS)
    await save_relevance(session, relevant)
    return FilterResponse(count=len(relevant), relevant=relevant)


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    status: str | None = None,
    days_ahead: int = 90,
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> CalendarResponse:
    cutoff = (date_type.today() + timedelta(days=days_ahead)).isoformat()
    if status:
        rows = await session.execute(
            text(
                "SELECT name, url, start_date, cfp_deadline, city, is_online, audience_size,"
                " description, topics, source, status FROM events_calendar"
                " WHERE status = :status AND (start_date IS NULL OR start_date <= :cutoff)"
                " ORDER BY start_date ASC"
            ),
            {"status": status, "cutoff": cutoff},
        )
    else:
        rows = await session.execute(
            text(
                "SELECT name, url, start_date, cfp_deadline, city, is_online, audience_size,"
                " description, topics, source, status FROM events_calendar"
                " WHERE start_date IS NULL OR start_date <= :cutoff"
                " ORDER BY start_date ASC"
            ),
            {"cutoff": cutoff},
        )
    events = []
    for r in rows.fetchall():
        events.append(
            ConferenceEvent(
                name=r[0],
                url=r[1],
                start_date=date_type.fromisoformat(r[2]) if r[2] else None,
                cfp_deadline=date_type.fromisoformat(r[3]) if r[3] else None,
                city=r[4],
                is_online=bool(r[5]),
                audience_size=r[6],
                description=r[7] or "",
                topics=json.loads(r[8]) if r[8] else [],
                source=r[9] or "",
                status=r[10] or "new",
            )
        )
    return CalendarResponse(count=len(events), events=events)


@router.post("/digest/send")
async def send_digest(  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> dict[str, str]:
    from telegram import Bot

    bot = Bot(token=settings.telegram_bot_token)
    builder = DigestBuilder()
    await builder.send_monthly_digest(session, bot)
    return {"status": "ok"}


@router.post("/abstract/{event_id}", response_model=AbstractResponse)
async def generate_abstract(
    event_id: int,
    product: str = "ai_assistant",
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> AbstractResponse:
    row = await session.execute(
        text(
            "SELECT name, url, start_date, cfp_deadline, city, is_online, audience_size,"
            " description, topics, source, status FROM events_calendar WHERE id = :id"
        ),
        {"id": event_id},
    )
    r = row.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    event = ConferenceEvent(
        name=r[0],
        url=r[1],
        start_date=date_type.fromisoformat(r[2]) if r[2] else None,
        cfp_deadline=date_type.fromisoformat(r[3]) if r[3] else None,
        city=r[4],
        is_online=bool(r[5]),
        audience_size=r[6],
        description=r[7] or "",
        topics=json.loads(r[8]) if r[8] else [],
        source=r[9] or "",
        status=r[10] or "new",
    )
    tracker = DeadlineTracker()
    abstract = await tracker.generate_abstract_draft(event, product)
    await tracker.save_abstract(session, event_id, product, abstract)
    return AbstractResponse(event_id=event_id, abstract=abstract)
