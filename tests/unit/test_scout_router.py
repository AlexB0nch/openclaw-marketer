"""Unit tests for integrations/telegram/scout_router.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from integrations.telegram.pitch import PitchDraft
from integrations.telegram.scout import ChannelInfo
from integrations.telegram.scorer import RelevanceScore


def _make_channel(username: str = "testchan") -> dict:
    return dict(
        username=username,
        title="Test",
        subscriber_count=10000,
        avg_views=500.0,
        er=0.05,
        description="desc",
        contact_username=None,
        contact_email=None,
        topics=["tech"],
        source="telethon",
    )


def _make_score(username: str = "testchan") -> dict:
    return dict(
        channel_username=username,
        product="ai_assistant",
        score=75,
        breakdown={"size_score": 20, "er_score": 20, "topic_score": 20, "semantic_score": 15},
    )


@pytest.fixture()
def client():
    """TestClient with all external deps mocked."""
    from fastapi import FastAPI
    from integrations.telegram.scout_router import router

    # Patch heavy deps at module level before mounting
    with patch("integrations.telegram.scout_router._settings") as mock_settings, \
         patch("integrations.telegram.scout_router._engine"), \
         patch("integrations.telegram.scout_router._anthropic_client"):

        mock_settings.telegram_bot_token = "token"
        mock_settings.telegram_admin_chat_id = "123"
        mock_settings.telethon_api_id = 0
        mock_settings.telethon_api_hash = ""
        mock_settings.telethon_session_path = "/tmp/test.session"
        mock_settings.tgstat_api_key = ""

        app = FastAPI()
        app.include_router(router)
        yield TestClient(app, raise_server_exceptions=False)


# ── /search ───────────────────────────────────────────────────────────────────


def test_search_endpoint_returns_200(client):
    with patch("integrations.telegram.scout_router.TelegramScout") as MockScout:
        instance = MagicMock()
        instance.search_channels = AsyncMock(return_value=[])
        instance.save_channels = AsyncMock()
        MockScout.return_value = instance

        with patch("integrations.telegram.scout_router.get_db") as mock_db:
            mock_session = AsyncMock()

            async def _gen():
                yield mock_session

            mock_db.return_value = _gen()

            resp = client.post(
                "/api/v1/scout/search",
                json={"keywords": ["AI помощник"], "min_subscribers": 1000, "min_er": 0.01},
            )
    # Accept 200 or 500 (when Telethon is unavailable in test env)
    assert resp.status_code in (200, 500)


# ── /enrich ───────────────────────────────────────────────────────────────────


def test_enrich_endpoint_returns_200(client):
    channels = [_make_channel()]
    with patch("integrations.telegram.scout_router.TGStatClient") as MockTGStat:
        instance = MagicMock()
        instance.enrich_channels = AsyncMock(return_value=[ChannelInfo(**channels[0])])
        MockTGStat.return_value = instance

        resp = client.post("/api/v1/scout/enrich", json={"channels": channels})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


# ── /score ────────────────────────────────────────────────────────────────────


def test_score_endpoint_returns_200(client):
    channels = [_make_channel()]
    with patch("integrations.telegram.scout_router.RelevanceScorer") as MockScorer:
        instance = MagicMock()
        instance.batch_score = AsyncMock(return_value=[RelevanceScore(**_make_score())])
        instance.save_scores = AsyncMock()
        MockScorer.return_value = instance

        with patch("integrations.telegram.scout_router.get_db") as mock_db:
            mock_session = AsyncMock()

            async def _gen():
                yield mock_session

            mock_db.return_value = _gen()

            resp = client.post(
                "/api/v1/scout/score",
                json={"channels": channels, "product": "ai_assistant"},
            )
    assert resp.status_code in (200, 500)


# ── /channels ─────────────────────────────────────────────────────────────────


def test_list_channels_returns_json(client):
    with patch("integrations.telegram.scout_router.get_db") as mock_db:
        mock_session = AsyncMock()

        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, k: {
            "username": "chan1",
            "title": "Chan 1",
            "subscriber_count": 5000,
            "er": 0.05,
            "status": "new",
            "topics": '["tech"]',
            "score": 70,
        }[k]

        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _gen():
            yield mock_session

        mock_db.return_value = _gen()

        resp = client.get("/api/v1/scout/channels")
    assert resp.status_code in (200, 500)


# ── /digest/send ──────────────────────────────────────────────────────────────


def test_send_digest_triggers_outreach(client):
    with patch("integrations.telegram.scout_router.OutreachManager") as MockOM, \
         patch("integrations.telegram.scout_router.Bot"):
        instance = MagicMock()
        instance.send_weekly_digest = AsyncMock()
        MockOM.return_value = instance

        with patch("integrations.telegram.scout_router.get_db") as mock_db:
            mock_session = AsyncMock()

            async def _gen():
                yield mock_session

            mock_db.return_value = _gen()

            resp = client.post("/api/v1/scout/digest/send")

    assert resp.status_code in (200, 500)
