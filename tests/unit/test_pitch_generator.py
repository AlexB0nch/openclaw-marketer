"""Unit tests for integrations/telegram/pitch.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from integrations.telegram.pitch import PitchDraft, PitchGenerator
from integrations.telegram.scorer import RelevanceScore
from integrations.telegram.scout import ChannelInfo


def _make_channel(**kwargs) -> ChannelInfo:
    defaults = {
        "username": "testchan",
        "title": "Test Channel",
        "subscriber_count": 10_000,
        "avg_views": 500.0,
        "er": 0.05,
        "description": "AI tools for teams",
        "contact_username": None,
        "contact_email": None,
        "topics": ["ai", "b2b"],
        "source": "telethon",
    }
    defaults.update(kwargs)
    return ChannelInfo(**defaults)


def _make_score(channel_username: str = "testchan", score: int = 75) -> RelevanceScore:
    return RelevanceScore(
        channel_username=channel_username,
        product="ai_assistant",
        score=score,
        breakdown={"size_score": 20, "er_score": 20, "topic_score": 20, "semantic_score": 15},
    )


def _make_generator(
    short_text: str = "Короткий питч",
    medium_text: str = "Средний питч",
    long_text: str = "Длинный питч",
) -> PitchGenerator:
    content_short = MagicMock(text=short_text)
    content_medium = MagicMock(text=medium_text)
    content_long = MagicMock(text=long_text)

    resp_short = MagicMock()
    resp_short.content = [content_short]
    resp_medium = MagicMock()
    resp_medium.content = [content_medium]
    resp_long = MagicMock()
    resp_long.content = [content_long]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(side_effect=[resp_short, resp_medium, resp_long])
    return PitchGenerator(anthropic_client=client)


# ── generate_pitch ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_pitch_returns_pydantic_model():
    gen = _make_generator()
    draft = await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    assert isinstance(draft, PitchDraft)
    assert draft.channel_username == "testchan"
    assert draft.product == "ai_assistant"


@pytest.mark.asyncio
async def test_generate_pitch_status_is_pending():
    gen = _make_generator()
    draft = await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    assert draft.status == "pending_approval"


@pytest.mark.asyncio
async def test_pitch_short_truncated_to_200():
    long_short = "А" * 300
    gen = _make_generator(short_text=long_short)
    draft = await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    assert len(draft.pitch_short) <= 200


@pytest.mark.asyncio
async def test_generate_pitch_calls_three_claude_requests():
    gen = _make_generator()
    await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    assert gen._client.messages.create.await_count == 3


@pytest.mark.asyncio
async def test_generate_pitch_uses_haiku_for_short():
    gen = _make_generator()
    await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    first_call = gen._client.messages.create.call_args_list[0]
    assert first_call.kwargs["model"] == "claude-haiku-4-5-20251001"


@pytest.mark.asyncio
async def test_generate_pitch_uses_sonnet_for_long():
    gen = _make_generator()
    await gen.generate_pitch(_make_channel(), "ai_assistant", _make_score())
    third_call = gen._client.messages.create.call_args_list[2]
    assert third_call.kwargs["model"] == "claude-sonnet-4-6"


# ── save_draft ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_draft_calls_db():
    gen = _make_generator()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    draft = PitchDraft(
        channel_username="testchan",
        product="ai_assistant",
        pitch_short="short",
        pitch_medium="medium",
        pitch_long="long",
    )
    await gen.save_draft(mock_session, draft)
    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_draft_sql_uses_on_conflict():
    gen = _make_generator()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    draft = PitchDraft(
        channel_username="chan",
        product="ai_news",
        pitch_short="s",
        pitch_medium="m",
        pitch_long="l",
    )
    await gen.save_draft(mock_session, draft)
    sql_str = str(mock_session.execute.call_args[0][0])
    assert "ON CONFLICT" in sql_str.upper()


# ── batch_generate ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_generate_returns_correct_count():
    # Each generate_pitch needs 3 Claude calls, so mock side_effect with enough responses
    def _make_resp(text: str) -> MagicMock:
        r = MagicMock()
        r.content = [MagicMock(text=text)]
        return r

    client = MagicMock()
    client.messages = MagicMock()
    # 2 channels × 3 calls each = 6 responses
    client.messages.create = AsyncMock(side_effect=[_make_resp(f"text{i}") for i in range(6)])
    gen = PitchGenerator(anthropic_client=client)

    channels = [_make_channel(username=f"ch{i}") for i in range(2)]
    scores = [_make_score(f"ch{i}") for i in range(2)]
    drafts = await gen.batch_generate(list(zip(channels, scores, strict=False)), "ai_assistant")

    assert len(drafts) == 2
    assert all(isinstance(d, PitchDraft) for d in drafts)


@pytest.mark.asyncio
async def test_batch_generate_respects_semaphore():
    """Verify semaphore allows at most 5 concurrent calls."""
    import asyncio

    concurrent_count = 0
    max_concurrent = 0

    async def _mock_generate(channel, product, score):
        nonlocal concurrent_count, max_concurrent
        concurrent_count += 1
        max_concurrent = max(max_concurrent, concurrent_count)
        await asyncio.sleep(0.01)
        concurrent_count -= 1
        return PitchDraft(
            channel_username=channel.username,
            product=product,
            pitch_short="s",
            pitch_medium="m",
            pitch_long="l",
        )

    gen = PitchGenerator.__new__(PitchGenerator)
    gen.generate_pitch = _mock_generate

    channels = [_make_channel(username=f"ch{i}") for i in range(10)]
    scores = [_make_score(f"ch{i}") for i in range(10)]
    await gen.batch_generate(list(zip(channels, scores, strict=False)), "ai_assistant")

    assert max_concurrent <= 5
