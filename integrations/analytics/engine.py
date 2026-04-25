"""Analytics engine: aggregation queries over collected metrics."""

import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_VALID_METRICS = {"impressions", "clicks", "spend_rub", "conversions"}


class AnalyticsEngine:
    """Run analytics queries on the metrics and post_metrics tables."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def top_performing_posts(self, period_days: int = 7) -> list[dict]:
        """Return top 10 published posts ordered by views in the last N days."""
        cutoff = date.today() - timedelta(days=period_days)
        result = await self._session.execute(
            text(
                "SELECT "
                "  sp.id, sp.topic, sp.platform, sp.product_name, "
                "  COALESCE(pm.views, 0) AS views, "
                "  COALESCE(pm.forwards, 0) AS forwards, "
                "  COALESCE(pm.reactions, 0) AS reactions, "
                "  sp.published_at "
                "FROM scheduled_posts sp "
                "LEFT JOIN post_metrics pm ON pm.post_id = sp.id "
                "WHERE sp.status = 'published' "
                "  AND sp.published_at >= :cutoff "
                "ORDER BY views DESC "
                "LIMIT 10"
            ),
            {"cutoff": str(cutoff)},
        )
        rows = result.fetchall()
        return [
            {
                "post_id": r[0],
                "topic": r[1],
                "platform": r[2],
                "product_name": r[3],
                "views": int(r[4]),
                "forwards": int(r[5]),
                "reactions": int(r[6]),
                "published_at": str(r[7]),
            }
            for r in rows
        ]

    async def cost_per_lead(self, product_id: int) -> dict:
        """Return total spend, conversions, and cost-per-lead for a product."""
        result = await self._session.execute(
            text(
                "SELECT "
                "  COALESCE(SUM(m.spend_rub), 0) AS total_spend, "
                "  COALESCE(SUM(m.conversions), 0) AS total_conversions "
                "FROM metrics m "
                "JOIN campaigns c ON c.id = m.campaign_id "
                "WHERE c.product_id = :product_id"
            ),
            {"product_id": product_id},
        )
        row = result.fetchone()
        total_spend = float(row[0]) if row else 0.0
        total_conversions = int(row[1]) if row else 0
        cpl = total_spend / total_conversions if total_conversions > 0 else 0.0
        return {
            "product_id": product_id,
            "total_spend_rub": round(total_spend, 2),
            "total_conversions": total_conversions,
            "cost_per_lead_rub": round(cpl, 2),
        }

    async def channel_effectiveness(self) -> dict:
        """Return per-platform aggregates: views, forwards, reactions, engagement."""
        result = await self._session.execute(
            text(
                "SELECT "
                "  sp.platform, "
                "  COUNT(*) AS post_count, "
                "  COALESCE(SUM(pm.views), 0) AS total_views, "
                "  COALESCE(SUM(pm.forwards), 0) AS total_forwards, "
                "  COALESCE(SUM(pm.reactions), 0) AS total_reactions "
                "FROM scheduled_posts sp "
                "LEFT JOIN post_metrics pm ON pm.post_id = sp.id "
                "WHERE sp.status = 'published' "
                "GROUP BY sp.platform"
            )
        )
        rows = result.fetchall()
        channels: dict = {}
        for r in rows:
            platform = r[0]
            post_count = int(r[1])
            views = int(r[2])
            forwards = int(r[3])
            reactions = int(r[4])
            engagement = round((reactions + forwards) / views * 100, 2) if views > 0 else 0.0
            avg_views = round(views / post_count, 1) if post_count > 0 else 0.0
            channels[platform] = {
                "post_count": post_count,
                "total_views": views,
                "total_forwards": forwards,
                "total_reactions": reactions,
                "avg_views_per_post": avg_views,
                "engagement_rate_pct": engagement,
            }
        return channels

    async def trend_analysis(self, metric: str, days: int = 30) -> dict:
        """Return daily time series with 7-day rolling average via pandas.

        Args:
            metric: one of impressions, clicks, spend_rub, conversions
            days: look-back window in days
        """
        if metric not in _VALID_METRICS:
            raise ValueError(f"Invalid metric '{metric}'. Valid: {_VALID_METRICS}")

        cutoff = date.today() - timedelta(days=days)
        # metric is validated against whitelist above — safe in f-string
        result = await self._session.execute(
            text(
                f"SELECT date, COALESCE(SUM({metric}), 0) AS value "  # noqa: S608
                "FROM metrics "
                "WHERE date >= :cutoff "
                "GROUP BY date "
                "ORDER BY date"
            ),
            {"cutoff": str(cutoff)},
        )
        rows = result.fetchall()

        if not rows:
            return {"dates": [], "values": [], "trend": []}

        df = pd.DataFrame(rows, columns=["date", "value"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        df["trend"] = df["value"].rolling(window=7, min_periods=1).mean()

        return {
            "dates": [str(d.date()) for d in df.index],
            "values": [float(v) for v in df["value"]],
            "trend": [round(float(v), 2) for v in df["trend"]],
        }
