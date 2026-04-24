"""Pydantic models for Strategist agent."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TopicEntry(BaseModel):
    """Single content topic suggestion."""

    topic: str
    channel: Literal["telegram", "blog", "habr", "youtube"]
    estimated_engagement: int = Field(..., ge=0, le=100)
    notes: str


class ProductPlan(BaseModel):
    """Weekly plan for a single product."""

    product_id: int
    product_name: str
    topics: list[TopicEntry]
    budget_allocation_rub: Decimal = Field(..., decimal_places=2, ge=0)
    priority: Literal["high", "medium", "low"]


class WeeklyMetrics(BaseModel):
    """Aggregated metrics for a week."""

    week_start: date
    total_impressions: int = Field(..., ge=0)
    total_clicks: int = Field(..., ge=0)
    avg_ctr: float = Field(..., ge=0, le=100)
    total_spend_rub: Decimal = Field(..., decimal_places=2, ge=0)
    roi: float
    top_performing_product: str | None = None


class ContentPlan(BaseModel):
    """Weekly content plan with approval metadata."""

    week_start_date: date
    week_end_date: date
    products: list[ProductPlan]
    metrics_summary: WeeklyMetrics
    status: Literal["pending_approval", "approved", "rejected", "archived"] = "pending_approval"
    created_at: datetime
    approved_by_user: str | None = None
    approval_reason: str | None = None
    approved_at: datetime | None = None

    model_config = ConfigDict(json_schema_extra={"example": {"week_start_date": "2026-04-27"}})


class PlanApprovalLog(BaseModel):
    """Audit log entry for plan approval actions."""

    plan_id: int
    action: Literal["submitted", "approved", "rejected", "edited"]
    actor: str
    reason: str | None = None
    timestamp: datetime
