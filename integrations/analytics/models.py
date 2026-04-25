"""Pydantic models for analytics data."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

MetricSource = Literal["telegram", "yandex_direct", "google_analytics"]


class MetricsRecord(BaseModel):
    """Unified metrics record across all data sources."""

    source: MetricSource
    product_id: int
    campaign_id: int | None = None
    date: date
    impressions: int = 0
    clicks: int = 0
    spend_rub: float = 0.0
    conversions: int = 0
    ctr: float = 0.0
    # Telegram post-level fields (optional)
    post_id: int | None = None
    views: int | None = None
    forwards: int | None = None
    reactions: int | None = None
