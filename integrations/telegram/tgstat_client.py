"""TGStat API client for channel enrichment."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from pydantic import BaseModel

from integrations.telegram.scout import ChannelInfo

logger = logging.getLogger(__name__)

_TGSTAT_BASE = "https://api.tgstat.ru/channels/get"


class TGStatChannelData(BaseModel):
    subscriber_count: int
    avg_views_per_post: float
    er: float
    category: str
    growth_7d: int


class TGStatClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_channel_info(self, username: str) -> TGStatChannelData | None:
        """Fetch channel stats from TGStat API. Returns None on empty key or error."""
        if not self._api_key:
            return None

        url = f"{_TGSTAT_BASE}?token={self._api_key}&channelId=@{username}"
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
            ):
                if resp.status != 200:
                    logger.warning("TGStat returned %d for @%s", resp.status, username)
                    return None
                data = await resp.json()
                item = data.get("response", {})
                return TGStatChannelData(
                    subscriber_count=item.get("participants_count", 0),
                    avg_views_per_post=float(item.get("avg_post_reach", 0)),
                    er=float(item.get("err24", 0)) / 100,
                    category=item.get("category", ""),
                    growth_7d=item.get("members_grow_7d", 0),
                )
        except Exception as exc:
            logger.warning("TGStat request failed for @%s: %s", username, exc)
            return None
        finally:
            await asyncio.sleep(1.0)

    async def enrich_channels(self, channels: list[ChannelInfo]) -> list[ChannelInfo]:
        """Enrich channel list with TGStat data. Silently skips if api_key is empty."""
        if not self._api_key:
            return channels

        enriched: list[ChannelInfo] = []
        for ch in channels:
            data = await self.get_channel_info(ch.username)
            if data:
                ch = ch.model_copy(
                    update={
                        "subscriber_count": data.subscriber_count,
                        "avg_views": data.avg_views_per_post,
                        "er": data.er,
                        "source": "tgstat",
                        "topics": [data.category] if data.category else ch.topics,
                    }
                )
            enriched.append(ch)
        return enriched
