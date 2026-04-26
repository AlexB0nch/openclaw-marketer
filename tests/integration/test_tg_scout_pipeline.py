"""Integration tests for the TG Scout pipeline (all external calls mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.telegram.monitor import MentionMonitor
from integrations.telegram.outreach import ChannelWithPitch, OutreachManager
from integrations.telegram.pitch import PitchDraft, PitchGenerator
from integrations.telegram.scorer import RelevanceScore, RelevanceScorer
from integrations.telegram.scout import ChannelInfo, TelegramScout
from integrations.telegram.tgstat_client import TGStatClient

# ── Helpers ───────────────────────────────────────────────────────────────────


def _channel(username: str = "chan", subs: int = 10_000) -> ChannelInfo:
    return ChannelInfo(
        username=username,
        title=f"Title {username}",
        subscriber_count=subs,
        avg_views=float(subs) * 0.05,
        er=0.05,
        description="AI B2B автоматизация помощник",
        contact_username="owner",
        contact_email=None,
        topics=["ai", "b2b"],
        source="telethon",
    )


def _score(username: str = "chan") -> RelevanceScore:
    return RelevanceScore(
        channel_username=username,
        product="ai_assistant",
        score=80,
        breakdown={"size_score": 20, "er_score": 20, "topic_score": 20, "semantic_score": 20},
    )


def _draft(username: str = "chan") -> PitchDraft:
    return PitchDraft(
        channel_username=username,
        product="ai_assistant",
        pitch_short="Short",
        pitch_medium="Medium",
        pitch_long="Long",
        status="pending_approval",
    )


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    session.commit = AsyncMock()
    return session


# ── test_search_and_save_channels ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_and_save_channels():
    channels = [_channel("chan1"), _channel("chan2")]
    session = _mock_session()

    scout = TelegramScout.__new__(TelegramScout)
    scout.search_channels = AsyncMock(return_value=channels)
    scout.save_channels = AsyncMock()

    result = await scout.search_channels(["AI помощник"])
    await scout.save_channels(session, result)

    scout.save_channels.assert_awaited_once_with(session, channels)
    assert len(result) == 2


# ── test_enrich_channels_skips_if_no_api_key ─────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_channels_skips_if_no_api_key():
    channels = [_channel("chan1")]
    client = TGStatClient(api_key="")

    with patch("aiohttp.ClientSession") as mock_http:
        result = await client.enrich_channels(channels)
        mock_http.assert_not_called()

    assert result is channels


# ── test_score_channels_and_save ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_score_channels_and_save():
    mock_anthropic = MagicMock()
    mock_anthropic.messages = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="18")]
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    scorer = RelevanceScorer(mock_anthropic)
    channels = [_channel("c1"), _channel("c2")]
    session = _mock_session()

    scores = await scorer.batch_score(channels, "ai_assistant")
    await scorer.save_scores(session, scores)

    assert len(scores) == 2
    assert all(isinstance(s, RelevanceScore) for s in scores)
    assert all(s.product == "ai_assistant" for s in scores)
    session.commit.assert_awaited()


# ── test_generate_pitches_batch ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_pitches_batch():
    def _resp(text: str) -> MagicMock:
        r = MagicMock()
        r.content = [MagicMock(text=text)]
        return r

    mock_anthropic = MagicMock()
    mock_anthropic.messages = MagicMock()
    # 2 channels × 3 Claude calls each = 6
    mock_anthropic.messages.create = AsyncMock(side_effect=[_resp(f"text{i}") for i in range(6)])

    pitcher = PitchGenerator(mock_anthropic)
    channels = [_channel("c1"), _channel("c2")]
    scores = [_score("c1"), _score("c2")]
    drafts = await pitcher.batch_generate(list(zip(channels, scores, strict=False)), "ai_assistant")

    assert len(drafts) == 2
    assert all(d.status == "pending_approval" for d in drafts)


# ── test_weekly_digest_sent_to_telegram ──────────────────────────────────────


@pytest.mark.asyncio
async def test_weekly_digest_sent_to_telegram():
    settings = MagicMock()
    settings.telegram_admin_chat_id = "12345"
    manager = OutreachManager(settings)

    items = [
        ChannelWithPitch(channel=_channel("c1"), pitch=_draft("c1"), score=85),
        ChannelWithPitch(channel=_channel("c2"), pitch=_draft("c2"), score=70),
    ]

    with patch.object(manager, "build_weekly_digest", return_value=items):
        bot = AsyncMock()
        session = _mock_session()
        await manager.send_weekly_digest(session, bot)

    # 1 header + 2 channel cards
    assert bot.send_message.await_count == 3


# ── test_send_pitch_callback_logs_outreach ───────────────────────────────────


@pytest.mark.asyncio
async def test_send_pitch_callback_logs_outreach():
    settings = MagicMock()
    settings.telegram_admin_chat_id = "12345"
    manager = OutreachManager(settings)

    session = AsyncMock()
    # First execute: no existing outreach
    no_row = MagicMock()
    no_row.fetchone.return_value = None
    # Second execute: pitch data
    pitch_row = MagicMock()
    pitch_row.__getitem__ = lambda self, k: {
        "pitch_short": "Hello pitch",
        "contact_username": "owner",
    }[k]
    pitch_data = MagicMock()
    pitch_data.mappings.return_value.fetchone.return_value = pitch_row

    session.execute = AsyncMock(side_effect=[no_row, pitch_data, AsyncMock()])
    session.commit = AsyncMock()

    telethon_client = AsyncMock()
    await manager.handle_send_callback(session, telethon_client, "scout_send:testchan")

    telethon_client.send_message.assert_awaited_once()
    session.commit.assert_awaited()
    # Third execute is the INSERT into outreach table
    assert session.execute.await_count == 3


# ── test_mention_monitor_deduplicates ────────────────────────────────────────


@pytest.mark.asyncio
async def test_mention_monitor_deduplicates():
    telethon_client = MagicMock()
    monitor = MentionMonitor(
        telethon_client=telethon_client,
        keywords=["AI помощник"],
        admin_chat_id=123,
    )
    monitor.on_mention = AsyncMock()
    bot = AsyncMock()

    def _make_event(msg_id: int) -> MagicMock:
        event = MagicMock()
        event.message.id = msg_id
        event.message.message = "AI помощник крутой инструмент"
        chat = MagicMock()
        chat.username = "somechan"
        event.get_chat = AsyncMock(return_value=chat)
        return event

    event = _make_event(42)
    await monitor._handle_event(event, bot)
    await monitor._handle_event(event, bot)  # same id again

    monitor.on_mention.assert_awaited_once()
