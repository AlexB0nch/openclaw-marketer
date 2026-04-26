"""Unit tests for integrations/telegram/tgstat_client.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.telegram.scout import ChannelInfo
from integrations.telegram.tgstat_client import TGStatChannelData, TGStatClient


def _make_channel(**kwargs) -> ChannelInfo:
    defaults = dict(
        username="testchan",
        title="Test",
        subscriber_count=5000,
        avg_views=250.0,
        er=0.05,
        description="",
        contact_username=None,
        contact_email=None,
        topics=["tech"],
        source="telethon",
    )
    defaults.update(kwargs)
    return ChannelInfo(**defaults)


# ── enrich_channels skips if no api_key ──────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_channels_skips_if_no_api_key():
    client = TGStatClient(api_key="")
    channels = [_make_channel()]
    result = await client.enrich_channels(channels)
    assert result is channels  # same object, no copy


@pytest.mark.asyncio
async def test_enrich_channels_no_api_key_makes_no_http_calls():
    client = TGStatClient(api_key="")
    with patch("aiohttp.ClientSession") as mock_session:
        channels = [_make_channel()]
        await client.enrich_channels(channels)
        mock_session.assert_not_called()


# ── get_channel_info ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_channel_info_returns_none_if_no_api_key():
    client = TGStatClient(api_key="")
    result = await client.get_channel_info("testchan")
    assert result is None


@pytest.mark.asyncio
async def test_get_channel_info_success():
    fake_response = {
        "response": {
            "participants_count": 12000,
            "avg_post_reach": 960.0,
            "err24": 8.0,
            "category": "Technology",
            "members_grow_7d": 150,
        }
    }

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=fake_response)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with patch("asyncio.sleep", new=AsyncMock()):
            client = TGStatClient(api_key="testkey")
            result = await client.get_channel_info("testchan")

    assert result is not None
    assert result.subscriber_count == 12000
    assert result.avg_views_per_post == 960.0
    assert abs(result.er - 0.08) < 1e-9
    assert result.category == "Technology"
    assert result.growth_7d == 150


@pytest.mark.asyncio
async def test_get_channel_info_returns_none_on_500():
    mock_resp = AsyncMock()
    mock_resp.status = 500
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = MagicMock(return_value=mock_resp)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        with patch("asyncio.sleep", new=AsyncMock()):
            client = TGStatClient(api_key="testkey")
            result = await client.get_channel_info("testchan")

    assert result is None


@pytest.mark.asyncio
async def test_get_channel_info_returns_none_on_exception():
    with patch("aiohttp.ClientSession", side_effect=Exception("network error")):
        with patch("asyncio.sleep", new=AsyncMock()):
            client = TGStatClient(api_key="testkey")
            result = await client.get_channel_info("testchan")

    assert result is None


# ── enrich_channels merges data ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_channels_merges_data():
    channel = _make_channel(username="mychan", subscriber_count=1000, er=0.01)

    tgstat_data = TGStatChannelData(
        subscriber_count=20000,
        avg_views_per_post=1600.0,
        er=0.08,
        category="Business",
        growth_7d=300,
    )

    client = TGStatClient(api_key="key")
    with patch.object(client, "get_channel_info", return_value=tgstat_data):
        result = await client.enrich_channels([channel])

    assert len(result) == 1
    assert result[0].subscriber_count == 20000
    assert result[0].avg_views == 1600.0
    assert result[0].er == 0.08
    assert result[0].source == "tgstat"
    assert result[0].topics == ["Business"]


@pytest.mark.asyncio
async def test_enrich_channels_keeps_channel_if_tgstat_returns_none():
    channel = _make_channel(username="mychan", subscriber_count=5000)
    client = TGStatClient(api_key="key")
    with patch.object(client, "get_channel_info", return_value=None):
        result = await client.enrich_channels([channel])

    assert result[0].subscriber_count == 5000
    assert result[0].source == "telethon"
