"""Unit tests for integrations/telegram/scorer.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.telegram.scorer import RelevanceScore, RelevanceScorer
from integrations.telegram.scout import ChannelInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_channel(
    username: str = "test_channel",
    title: str = "Test Channel",
    subscriber_count: int = 10_000,
    er: float = 0.05,
    description: str = "",
    topics: list[str] | None = None,
) -> ChannelInfo:
    return ChannelInfo(
        username=username,
        title=title,
        subscriber_count=subscriber_count,
        avg_views=500.0,
        er=er,
        description=description,
        contact_username=None,
        contact_email=None,
        topics=topics or [],
        source="telethon",
    )


def _make_mock_client(semantic_response: str = "15") -> MagicMock:
    """Return a mock AsyncAnthropic client that returns *semantic_response* text."""
    content = MagicMock()
    content.text = semantic_response

    response = MagicMock()
    response.content = [content]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# size_score tests
# ---------------------------------------------------------------------------


def test_size_score_below_1k() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    assert scorer._size_score(500) == 0


def test_size_score_above_100k() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    assert scorer._size_score(200_000) == 25


def test_size_score_middle() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    result = scorer._size_score(10_000)
    assert 0 < result < 25


# ---------------------------------------------------------------------------
# er_score tests
# ---------------------------------------------------------------------------


def test_er_score_below_1pct() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    assert scorer._er_score(0.005) == 0


def test_er_score_above_10pct() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    assert scorer._er_score(0.15) == 25


# ---------------------------------------------------------------------------
# topic_score tests
# ---------------------------------------------------------------------------


def test_topic_score_no_match() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    channel = _make_channel(description="cooking recipes", topics=["cooking"])
    result = scorer._topic_score(channel, "ai_assistant")
    assert result == 0


def test_topic_score_full_match() -> None:
    scorer = RelevanceScorer(_make_mock_client())
    # All keywords for ai_assistant: ai, помощник, переписка, email, b2b, автоматизация
    description = "ai помощник переписка email b2b автоматизация"
    channel = _make_channel(description=description, topics=[])
    result = scorer._topic_score(channel, "ai_assistant")
    assert result == 25


# ---------------------------------------------------------------------------
# semantic_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_score_calls_claude() -> None:
    client = _make_mock_client("20")
    scorer = RelevanceScorer(client)
    channel = _make_channel()

    result = await scorer._semantic_score(channel, "ai_assistant")

    client.messages.create.assert_called_once()
    call_kwargs = client.messages.create.call_args
    assert call_kwargs.kwargs["model"] == "claude-haiku-4-5-20251001"
    assert result == 20


@pytest.mark.asyncio
async def test_semantic_score_returns_0_on_exception() -> None:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=Exception("API error"))
    scorer = RelevanceScorer(client)
    channel = _make_channel()

    result = await scorer._semantic_score(channel, "ai_assistant")

    assert result == 0


# ---------------------------------------------------------------------------
# batch_score tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_score_runs_all_channels() -> None:
    client = _make_mock_client("10")
    scorer = RelevanceScorer(client)
    channels = [
        _make_channel(username="ch1", subscriber_count=5_000, er=0.05),
        _make_channel(username="ch2", subscriber_count=50_000, er=0.08),
        _make_channel(username="ch3", subscriber_count=150_000, er=0.12),
    ]

    scores = await scorer.batch_score(channels, "ai_assistant")

    assert len(scores) == 3
    assert all(isinstance(s, RelevanceScore) for s in scores)
    usernames = {s.channel_username for s in scores}
    assert usernames == {"ch1", "ch2", "ch3"}


# ---------------------------------------------------------------------------
# save_scores tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_scores_calls_db() -> None:
    client = _make_mock_client()
    scorer = RelevanceScorer(client)

    session = MagicMock()
    session.execute = AsyncMock()

    scores = [
        RelevanceScore(
            channel_username="ch1",
            product="ai_assistant",
            score=60,
            breakdown={
                "size_score": 15,
                "er_score": 15,
                "topic_score": 20,
                "semantic_score": 10,
            },
        )
    ]

    await scorer.save_scores(session, scores)

    session.execute.assert_called_once()
    call_args = session.execute.call_args
    # Second positional arg is the params dict
    params = call_args.args[1]
    assert params["username"] == "ch1"
    assert params["product"] == "ai_assistant"
    assert params["score"] == 60
