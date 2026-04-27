"""Conference scraper for Russian tech events."""

import asyncio
import json
import logging
import re
from datetime import date, datetime

import aiohttp
from bs4 import BeautifulSoup
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_RUSSIAN_MONTHS: dict[str, int] = {
    "январь": 1,
    "января": 1,
    "февраль": 2,
    "февраля": 2,
    "март": 3,
    "марта": 3,
    "апрель": 4,
    "апреля": 4,
    "май": 5,
    "мая": 5,
    "июнь": 6,
    "июня": 6,
    "июль": 7,
    "июля": 7,
    "август": 8,
    "августа": 8,
    "сентябрь": 9,
    "сентября": 9,
    "октябрь": 10,
    "октября": 10,
    "ноябрь": 11,
    "ноября": 11,
    "декабрь": 12,
    "декабря": 12,
}


class ConferenceEvent(BaseModel):
    name: str
    url: str
    start_date: date | None = None
    cfp_deadline: date | None = None
    city: str | None = None
    is_online: bool = False
    audience_size: int | None = None
    description: str = ""
    topics: list[str] = []
    source: str = ""
    status: str = "new"


def parse_date(text: str) -> date | None:
    text = text.strip()
    try:
        # "15 мая 2026"
        match = re.match(r"(\d{1,2})\s+([а-яА-Я]+)\s+(\d{4})", text, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_word = match.group(2).lower()
            year = int(match.group(3))
            month = _RUSSIAN_MONTHS.get(month_word)
            if month:
                return date(year, month, day)

        # "15.05.2026"
        match = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if match:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))

        # "май 2026"
        match = re.match(r"([а-яА-Я]+)\s+(\d{4})", text, re.IGNORECASE)
        if match:
            month_word = match.group(1).lower()
            year = int(match.group(2))
            month = _RUSSIAN_MONTHS.get(month_word)
            if month:
                return date(year, month, 1)
    except Exception:
        pass
    return None


class ConferenceScraper:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "Mozilla/5.0 (compatible; EventsBot/1.0)"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def scrape_all(self) -> list[ConferenceEvent]:
        results = await asyncio.gather(
            self._scrape_aiconf(),
            self._scrape_productsense(),
            self._scrape_ritfest(),
            self._scrape_habr(),
            self._scrape_ppc_world(),
            self._scrape_tadviser(),
            return_exceptions=True,
        )
        events: list[ConferenceEvent] = []
        for batch in results:
            if isinstance(batch, BaseException):
                logger.warning("Scraper failed: %s", batch)
                continue
            events.extend(batch)
        return events

    async def _fetch_html(self, url: str) -> str:
        session = await self._get_session()
        async with session.get(url) as response:
            return await response.text()

    async def _scrape_aiconf(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://aiconf.ru")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            title_tag = soup.find(["h1", "h2"])
            name = title_tag.get_text(strip=True) if title_tag else "AI Conference"
            date_str = ""
            for tag in soup.find_all(string=re.compile(r"\d{4}")):
                date_str = tag.strip()
                break
            cfp_text = None
            for tag in soup.find_all(string=re.compile(r"[Cc][Ff][Pp]|заявк", re.IGNORECASE)):
                cfp_text = tag.strip()
                break
            events.append(
                ConferenceEvent(
                    name=name,
                    url="https://aiconf.ru",
                    start_date=parse_date(date_str) if date_str else None,
                    cfp_deadline=parse_date(cfp_text) if cfp_text else None,
                    source="aiconf.ru",
                    topics=["AI", "машинное обучение"],
                )
            )
            return events
        except Exception as e:
            logger.warning("_scrape_aiconf failed: %s", e)
            return []

    async def _scrape_productsense(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://productsense.io")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            title_tag = soup.find(["h1", "h2"])
            name = title_tag.get_text(strip=True) if title_tag else "ProductSense"
            date_str = ""
            for tag in soup.find_all(string=re.compile(r"\d{4}")):
                date_str = tag.strip()
                break
            events.append(
                ConferenceEvent(
                    name=name,
                    url="https://productsense.io",
                    start_date=parse_date(date_str) if date_str else None,
                    source="productsense.io",
                    topics=["продакт-менеджмент", "продуктовая аналитика"],
                )
            )
            return events
        except Exception as e:
            logger.warning("_scrape_productsense failed: %s", e)
            return []

    async def _scrape_ritfest(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://ritfest.ru")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            title_tag = soup.find(["h1", "h2"])
            name = title_tag.get_text(strip=True) if title_tag else "РИТ Фест"
            date_str = ""
            for tag in soup.find_all(string=re.compile(r"\d{4}")):
                date_str = tag.strip()
                break
            events.append(
                ConferenceEvent(
                    name=name,
                    url="https://ritfest.ru",
                    start_date=parse_date(date_str) if date_str else None,
                    source="ritfest.ru",
                    topics=["IT", "технологии"],
                )
            )
            return events
        except Exception as e:
            logger.warning("_scrape_ritfest failed: %s", e)
            return []

    async def _scrape_habr(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://habr.com/ru/events/")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            cards = soup.find_all(
                ["article", "div"], class_=re.compile(r"event|card", re.IGNORECASE)
            )
            for card in cards[:5]:
                title_tag = card.find(["h2", "h3", "a"])
                if not title_tag:
                    continue
                name = title_tag.get_text(strip=True)
                link_tag = card.find("a", href=True)
                url = link_tag["href"] if link_tag else "https://habr.com/ru/events/"
                if url.startswith("/"):
                    url = "https://habr.com" + url
                date_str = ""
                for tag in card.find_all(string=re.compile(r"\d{4}|\d{1,2}\.\d{1,2}")):
                    date_str = tag.strip()
                    break
                events.append(
                    ConferenceEvent(
                        name=name,
                        url=url,
                        start_date=parse_date(date_str) if date_str else None,
                        source="habr.com",
                        topics=["IT"],
                    )
                )
            return events
        except Exception as e:
            logger.warning("_scrape_habr failed: %s", e)
            return []

    async def _scrape_ppc_world(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://ppc.world/events/")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            cards = soup.find_all(
                ["article", "div"], class_=re.compile(r"event|card|item", re.IGNORECASE)
            )
            for card in cards[:5]:
                title_tag = card.find(["h2", "h3", "a"])
                if not title_tag:
                    continue
                name = title_tag.get_text(strip=True)
                link_tag = card.find("a", href=True)
                url = link_tag["href"] if link_tag else "https://ppc.world/events/"
                if url.startswith("/"):
                    url = "https://ppc.world" + url
                date_str = ""
                for tag in card.find_all(string=re.compile(r"\d{4}|\d{1,2}\.\d{1,2}")):
                    date_str = tag.strip()
                    break
                events.append(
                    ConferenceEvent(
                        name=name,
                        url=url,
                        start_date=parse_date(date_str) if date_str else None,
                        source="ppc.world",
                        topics=["реклама", "контекстная реклама"],
                    )
                )
            return events
        except Exception as e:
            logger.warning("_scrape_ppc_world failed: %s", e)
            return []

    async def _scrape_tadviser(self) -> list[ConferenceEvent]:
        try:
            html = await self._fetch_html("https://www.tadviser.ru/index.php/Конференции")
            soup = BeautifulSoup(html, "html.parser")
            events: list[ConferenceEvent] = []
            rows = soup.find_all("tr")
            for row in rows[:10]:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                name = cells[0].get_text(strip=True)
                if not name:
                    continue
                link_tag = cells[0].find("a", href=True)
                url = link_tag["href"] if link_tag else "https://www.tadviser.ru"
                if url.startswith("/"):
                    url = "https://www.tadviser.ru" + url
                date_str = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                events.append(
                    ConferenceEvent(
                        name=name,
                        url=url,
                        start_date=parse_date(date_str) if date_str else None,
                        source="tadviser.ru",
                        topics=["IT", "бизнес"],
                    )
                )
            return events
        except Exception as e:
            logger.warning("_scrape_tadviser failed: %s", e)
            return []


async def save_events(session: AsyncSession, events: list[ConferenceEvent]) -> None:
    for event in events:
        existing = await session.execute(
            text(
                "SELECT id FROM events_calendar WHERE name = :name AND "
                "(start_date = :start_date OR (start_date IS NULL AND :start_date IS NULL))"
            ),
            {
                "name": event.name,
                "start_date": event.start_date.isoformat() if event.start_date else None,
            },
        )
        row = existing.fetchone()
        if row:
            await session.execute(
                text(
                    "UPDATE events_calendar SET url=:url, cfp_deadline=:cfp_deadline, "
                    "description=:description, topics=:topics, source=:source, "
                    "updated_at=:updated_at WHERE id=:id"
                ),
                {
                    "url": event.url,
                    "cfp_deadline": event.cfp_deadline.isoformat() if event.cfp_deadline else None,
                    "description": event.description,
                    "topics": json.dumps(event.topics, ensure_ascii=False),
                    "source": event.source,
                    "updated_at": datetime.utcnow().isoformat(),
                    "id": row[0],
                },
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO events_calendar (name, url, start_date, cfp_deadline, city, "
                    "is_online, audience_size, description, topics, source, status, created_at, updated_at) "
                    "VALUES (:name, :url, :start_date, :cfp_deadline, :city, :is_online, "
                    ":audience_size, :description, :topics, :source, :status, :created_at, :updated_at)"
                ),
                {
                    "name": event.name,
                    "url": event.url,
                    "start_date": event.start_date.isoformat() if event.start_date else None,
                    "cfp_deadline": event.cfp_deadline.isoformat() if event.cfp_deadline else None,
                    "city": event.city,
                    "is_online": 1 if event.is_online else 0,
                    "audience_size": event.audience_size,
                    "description": event.description,
                    "topics": json.dumps(event.topics, ensure_ascii=False),
                    "source": event.source,
                    "status": event.status,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                },
            )
    await session.commit()
