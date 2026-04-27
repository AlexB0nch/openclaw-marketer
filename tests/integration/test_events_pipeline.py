"""Integration tests for Events Agent pipeline."""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test_dummy")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_dummy")
os.environ.setdefault("TELEGRAM_ADMIN_CHAT_ID", "0")
os.environ.setdefault("TELEGRAM_CHANNEL_ID", "@test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("N8N_WEBHOOK_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test")
os.environ.setdefault("EVENTS_ENABLED", "true")

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.events.digest import DigestBuilder
from integrations.events.filter import RelevanceFilter, save_relevance
from integrations.events.scraper import ConferenceEvent, ConferenceScraper, save_events
from integrations.events.tracker import DeadlineTracker

# ── helpers ────────────────────────────────────────────────────────────────


def _make_event(
    name: str = "Test Conf",
    url: str = "https://test.ru",
    start_date: date | None = None,
    cfp_deadline: date | None = None,
    status: str = "new",
) -> ConferenceEvent:
    return ConferenceEvent(
        name=name,
        url=url,
        start_date=start_date,
        cfp_deadline=cfp_deadline,
        status=status,
    )


# ── test_scrape_all_returns_list ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scrape_all_returns_list():
    """scrape_all returns a list even when all scrapers are mocked."""
    scraper = ConferenceScraper()
    with (
        patch.object(scraper, "_scrape_aiconf", return_value=[]),
        patch.object(scraper, "_scrape_productsense", return_value=[]),
        patch.object(scraper, "_scrape_ritfest", return_value=[]),
        patch.object(scraper, "_scrape_habr", return_value=[]),
        patch.object(scraper, "_scrape_ppc_world", return_value=[]),
        patch.object(scraper, "_scrape_tadviser", return_value=[]),
    ):
        result = await scraper.scrape_all()
    assert isinstance(result, list)
    await scraper.close()


@pytest.mark.asyncio
async def test_scraper_graceful_degradation_on_site_failure():
    """One failing scraper does not block others."""
    import aiohttp

    scraper = ConferenceScraper()
    good_event = _make_event("Good Conf")
    with (
        patch.object(
            scraper, "_scrape_aiconf", side_effect=aiohttp.ClientError("connection refused")
        ),
        patch.object(scraper, "_scrape_productsense", return_value=[good_event]),
        patch.object(scraper, "_scrape_ritfest", return_value=[]),
        patch.object(scraper, "_scrape_habr", return_value=[]),
        patch.object(scraper, "_scrape_ppc_world", return_value=[]),
        patch.object(scraper, "_scrape_tadviser", return_value=[]),
    ):
        result = await scraper.scrape_all()
    assert isinstance(result, list)
    # graceful: at least 1 good event returned
    assert any(e.name == "Good Conf" for e in result)
    await scraper.close()


# ── test_filter_relevant_scores_and_saves ──────────────────────────────────


@pytest.mark.asyncio
async def test_filter_relevant_scores_and_saves(db_session):
    """filter_relevant scores events and save_relevance updates DB status."""
    future_date = date.today() + timedelta(days=60)
    event = _make_event("AI Summit", start_date=future_date)
    await save_events(db_session, [event])

    f = RelevanceFilter(threshold=50)
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="75")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    with patch("integrations.events.filter.get_anthropic_client", return_value=mock_client):
        relevant = await f.filter_relevant([event], ["ai_assistant"])

    assert len(relevant) >= 1
    await save_relevance(db_session, relevant)

    from sqlalchemy import text

    row = await db_session.execute(
        text("SELECT status FROM events_calendar WHERE name = 'AI Summit'")
    )
    r = row.fetchone()
    assert r is not None
    assert r[0] == "relevant"


# ── test_deadline_tracker_finds_events_within_14_days ──────────────────────


@pytest.mark.asyncio
async def test_deadline_tracker_finds_events_within_14_days(db_session):
    """check_upcoming_deadlines returns events with CFP in [today+1..today+14]."""
    cfp_in_7 = date.today() + timedelta(days=7)
    event = _make_event("Deadline Conf", cfp_deadline=cfp_in_7, status="relevant")
    await save_events(db_session, [event])
    # Set status to relevant manually
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE events_calendar SET status='relevant' WHERE name='Deadline Conf'")
    )
    await db_session.commit()

    tracker = DeadlineTracker()
    result = await tracker.check_upcoming_deadlines(db_session)
    assert any(e.name == "Deadline Conf" for e in result)


# ── test_abstract_generation_called_for_deadline_events ───────────────────


@pytest.mark.asyncio
async def test_abstract_generation_called_for_deadline_events():
    """generate_abstract_draft calls Claude and returns non-empty string."""
    event = _make_event("Speaker Conf")
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Отличный черновик заявки на конференцию.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    tracker = DeadlineTracker()
    with patch("integrations.events.tracker.get_anthropic_client", return_value=mock_client):
        result = await tracker.generate_abstract_draft(event, "ai_assistant")

    assert isinstance(result, str)
    assert len(result) > 0


# ── test_monthly_digest_sent_to_telegram ──────────────────────────────────


@pytest.mark.asyncio
async def test_monthly_digest_sent_to_telegram(db_session, mock_telegram_bot):
    """send_monthly_digest calls bot.send_message at least once."""
    future_date = date.today() + timedelta(days=30)
    event = _make_event("Digest Conf", start_date=future_date, status="relevant")
    await save_events(db_session, [event])
    from sqlalchemy import text

    await db_session.execute(
        text("UPDATE events_calendar SET status='relevant' WHERE name='Digest Conf'")
    )
    await db_session.commit()

    builder = DigestBuilder()
    await builder.send_monthly_digest(db_session, mock_telegram_bot)
    assert mock_telegram_bot.send_message.called


# ── test_skip_callback_sets_status_skipped ────────────────────────────────


@pytest.mark.asyncio
async def test_skip_callback_sets_status_skipped(db_session):
    """handle_skip_callback updates event status to 'skipped'."""
    event = _make_event("Skip Conf", status="relevant")
    await save_events(db_session, [event])

    from sqlalchemy import text

    row = await db_session.execute(text("SELECT id FROM events_calendar WHERE name='Skip Conf'"))
    event_id = row.fetchone()[0]

    builder = DigestBuilder()
    await builder.handle_skip_callback(db_session, f"events_skip:{event_id}")

    row2 = await db_session.execute(
        text("SELECT status FROM events_calendar WHERE id=:id"), {"id": event_id}
    )
    assert row2.fetchone()[0] == "skipped"
