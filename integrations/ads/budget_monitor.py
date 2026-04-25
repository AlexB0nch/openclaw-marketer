"""Budget monitoring and auto-pause for ad campaigns."""

import logging
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from integrations.yandex_direct.client import YandexDirectClient

logger = logging.getLogger(__name__)


class BudgetMonitor:
    """Monitors ad spend and pauses campaigns when limits are hit."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def check_daily_spend(
        self, session: AsyncSession, yandex_client: YandexDirectClient
    ) -> float:
        """Return today's total spend in RUB across all campaigns."""
        today = date.today().isoformat()
        row = await session.execute(
            text("SELECT COALESCE(SUM(spend_rub), 0.0) FROM ad_daily_spend WHERE date = :d"),
            {"d": today},
        )
        return float(row.scalar() or 0.0)

    async def check_monthly_spend(
        self, session: AsyncSession, yandex_client: YandexDirectClient
    ) -> float:
        """Return current month's total spend in RUB."""
        month_start = date.today().replace(day=1).isoformat()
        today = date.today().isoformat()
        row = await session.execute(
            text(
                "SELECT COALESCE(SUM(spend_rub), 0.0) FROM ad_daily_spend "
                "WHERE date >= :start AND date <= :end"
            ),
            {"start": month_start, "end": today},
        )
        return float(row.scalar() or 0.0)

    async def auto_pause_on_limit(
        self, session: AsyncSession, yandex_client: YandexDirectClient
    ) -> bool:
        """Pause all running campaigns if monthly limit is reached. Returns True if paused."""
        monthly_spend = await self.check_monthly_spend(session, yandex_client)

        if monthly_spend < self._settings.monthly_ads_budget_limit_rub:
            return False

        # Fetch all running Yandex campaigns
        rows = await session.execute(
            text(
                "SELECT id, campaign_id_external FROM ad_campaigns "
                "WHERE status = 'running' AND platform = 'yandex' "
                "AND campaign_id_external IS NOT NULL"
            )
        )
        campaigns = rows.fetchall()

        for campaign_id, external_id in campaigns:
            try:
                await yandex_client.pause_campaign(int(external_id))
                await session.execute(
                    text("UPDATE ad_campaigns SET status = 'paused' WHERE id = :id"),
                    {"id": campaign_id},
                )
                logger.warning(
                    "Auto-paused campaign %d (external=%s): monthly limit %.0f RUB reached",
                    campaign_id,
                    external_id,
                    self._settings.monthly_ads_budget_limit_rub,
                )
            except Exception as exc:
                logger.error("Failed to auto-pause campaign %d: %s", campaign_id, exc)

        await session.commit()
        return len(campaigns) > 0
