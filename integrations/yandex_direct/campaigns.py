"""Campaign config models and factory for Yandex Direct."""

import json
import logging
from datetime import date, timedelta
from enum import StrEnum
from typing import Any

import anthropic
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings

logger = logging.getLogger(__name__)


class BidStrategy(StrEnum):
    HIGHEST_CLICK_RATE = "HIGHEST_CLICK_RATE"
    AVERAGE_CPC = "AVERAGE_CPC"


class AdVariant(BaseModel):
    title1: str  # max 35 chars
    title2: str  # max 35 chars
    text: str  # max 81 chars
    display_url: str
    final_url: str


class CampaignConfig(BaseModel):
    name: str
    product_id: int
    budget_rub: float
    keywords: list[str]
    ads: list[AdVariant]
    strategy: BidStrategy = BidStrategy.HIGHEST_CLICK_RATE
    start_date: date
    end_date: date


async def generate_campaign_config(
    product_name: str,
    goal: str,
    budget_rub: float,
    settings: Settings,
    product_id: int = 1,
    start_date: date | None = None,
    end_date: date | None = None,
) -> CampaignConfig:
    """Use Claude to generate keywords and 3 ad variants for a campaign."""
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = start_date + timedelta(days=30)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""Generate a Yandex Direct campaign config for:
Product: {product_name}
Goal: {goal}
Budget: {budget_rub} RUB/month

Return a JSON object with:
- "keywords": list of 10-15 Russian search keywords (no + prefix)
- "ads": list of exactly 3 ad variants, each with:
  - "title1": string max 35 chars
  - "title2": string max 35 chars
  - "text": string max 81 chars
  - "display_url": short display URL without https://
  - "final_url": full landing page URL (use https://example.com as placeholder)

Return only valid JSON, no markdown."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown code block if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]

    data: dict[str, Any] = json.loads(raw)

    ads = [AdVariant(**ad) for ad in data["ads"]]

    return CampaignConfig(
        name=f"{product_name} — {goal[:30]}",
        product_id=product_id,
        budget_rub=budget_rub,
        keywords=data["keywords"],
        ads=ads,
        strategy=BidStrategy.HIGHEST_CLICK_RATE,
        start_date=start_date,
        end_date=end_date,
    )


async def create_draft(session: AsyncSession, config: CampaignConfig) -> int:
    """Save CampaignConfig to ad_campaigns table with status='draft'; return row id."""
    result = await session.execute(
        text(
            "INSERT INTO ad_campaigns "
            "(product_id, platform, status, config_json, budget_rub, spent_rub) "
            "VALUES (:product_id, 'yandex', 'draft', :config_json, :budget_rub, 0.0)"
        ),
        {
            "product_id": config.product_id,
            "config_json": config.model_dump_json(),
            "budget_rub": config.budget_rub,
        },
    )
    await session.commit()
    return result.lastrowid
