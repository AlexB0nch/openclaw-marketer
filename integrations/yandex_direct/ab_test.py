"""A/B test manager for Yandex Direct ad variants."""

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from integrations.yandex_direct.client import YandexDirectClient

logger = logging.getLogger(__name__)


class ABTestManager:
    """Manages A/B tests for Yandex Direct campaigns."""

    async def start_ab_test(self, session: AsyncSession, campaign_id: int) -> list[int]:
        """Create ad variants from campaign config for A/B testing. Returns list of variant IDs."""
        row = await session.execute(
            text("SELECT config_json FROM ad_campaigns WHERE id = :id"),
            {"id": campaign_id},
        )
        record = row.fetchone()
        if not record:
            raise ValueError(f"Campaign {campaign_id} not found")

        config = json.loads(record[0])
        ads = config.get("ads", [])

        variant_ids: list[int] = []
        for ad in ads:
            res = await session.execute(
                text(
                    "INSERT INTO ad_variants "
                    "(campaign_id, title1, title2, text, display_url, final_url, "
                    " clicks, impressions, ctr, status) "
                    "VALUES (:campaign_id, :title1, :title2, :text, :display_url, :final_url, "
                    "        0, 0, 0.0, 'active')"
                ),
                {
                    "campaign_id": campaign_id,
                    "title1": ad["title1"],
                    "title2": ad["title2"],
                    "text": ad["text"],
                    "display_url": ad["display_url"],
                    "final_url": ad["final_url"],
                },
            )
            variant_ids.append(res.lastrowid)

        await session.commit()
        return variant_ids

    async def evaluate_ab_test(self, session: AsyncSession, campaign_id: int) -> int | None:
        """Compare CTR of variants after 7 days; return winner variant ID or None if no data."""
        rows = await session.execute(
            text(
                "SELECT id, clicks, impressions, ctr FROM ad_variants "
                "WHERE campaign_id = :cid AND status = 'active'"
            ),
            {"cid": campaign_id},
        )
        variants = rows.fetchall()
        if not variants:
            return None

        best: tuple[int, float] | None = None
        for row in variants:
            variant_id, clicks, impressions, ctr = row
            effective_ctr = float(ctr) if impressions > 0 else 0.0
            if best is None or effective_ctr > best[1]:
                best = (variant_id, effective_ctr)

        return best[0] if best else None

    async def pause_losing_variants(
        self,
        session: AsyncSession,
        campaign_id: int,
        client: YandexDirectClient,
    ) -> None:
        """Pause all non-winner variants. Must call evaluate_ab_test first to get winner."""
        winner_id = await self.evaluate_ab_test(session, campaign_id)
        if winner_id is None:
            return

        rows = await session.execute(
            text(
                "SELECT id FROM ad_variants "
                "WHERE campaign_id = :cid AND status = 'active' AND id != :winner"
            ),
            {"cid": campaign_id, "winner": winner_id},
        )
        losers = rows.fetchall()

        for (loser_id,) in losers:
            await session.execute(
                text("UPDATE ad_variants SET status = 'paused' WHERE id = :id"),
                {"id": loser_id},
            )

        await session.commit()
        logger.info(
            "Campaign %s: paused %d losing variants, winner=%d",
            campaign_id,
            len(losers),
            winner_id,
        )
