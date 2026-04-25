"""Async Google Ads YouTube campaign client."""

import asyncio
import json
import logging
from datetime import date
from typing import Any

import anthropic
from pydantic import BaseModel

from app.config import Settings

logger = logging.getLogger(__name__)


class VideoCampaignConfig(BaseModel):
    name: str
    product_id: int
    budget_rub: float
    target_audiences: list[str]
    video_url: str  # YouTube video URL
    bid_strategy: str = "TARGET_CPA"


class VideoCreativeBrief(BaseModel):
    hook_text: str  # First 5 seconds hook
    main_message: str  # Core value proposition
    cta_text: str  # Call-to-action text
    target_audience_desc: str  # Who this is for
    recommended_duration_sec: int  # Recommended video length
    key_visuals: list[str]  # List of visual scene descriptions


class GoogleAdsYouTubeClient:
    """Manages YouTube video campaigns via Google Ads API."""

    def __init__(self, settings: Settings) -> None:
        self._developer_token = settings.google_ads_developer_token
        self._client_id = settings.google_ads_client_id
        self._client_secret = settings.google_ads_client_secret
        self._refresh_token = settings.google_ads_refresh_token
        self._customer_id = settings.google_ads_customer_id
        self._anthropic_api_key = settings.anthropic_api_key

    def _get_client(self) -> Any:
        """Build Google Ads client (lazy, so tests can mock before import)."""
        from google.ads.googleads.client import GoogleAdsClient  # noqa: PLC0415

        credentials = {
            "developer_token": self._developer_token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
            "use_proto_plus": True,
        }
        return GoogleAdsClient.load_from_dict(credentials)

    async def create_video_campaign(self, config: VideoCampaignConfig) -> str:
        """Create a YouTube video campaign; return external campaign resource name."""

        def _call() -> str:
            client = self._get_client()
            campaign_service = client.get_service("CampaignService")
            campaign_budget_service = client.get_service("CampaignBudgetService")

            # Create budget
            budget_op = client.get_type("CampaignBudgetOperation")
            budget = budget_op.create
            budget.name = f"Budget for {config.name}"
            # Convert RUB to micros (1 RUB = 1,000,000 micros), daily from monthly
            budget.amount_micros = int(config.budget_rub * 1_000_000 / 30)
            budget.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

            budget_response = campaign_budget_service.mutate_campaign_budgets(
                customer_id=self._customer_id,
                operations=[budget_op],
            )
            budget_resource = budget_response.results[0].resource_name

            # Create campaign
            campaign_op = client.get_type("CampaignOperation")
            campaign = campaign_op.create
            campaign.name = config.name
            campaign.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.VIDEO
            campaign.campaign_budget = budget_resource
            campaign.status = client.enums.CampaignStatusEnum.PAUSED

            response = campaign_service.mutate_campaigns(
                customer_id=self._customer_id,
                operations=[campaign_op],
            )
            return response.results[0].resource_name

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise RuntimeError(f"create_video_campaign failed: {exc}") from exc

    async def get_video_metrics(
        self,
        campaign_id: str,
        date_from: date,
        date_to: date,
    ) -> dict[str, Any]:
        """Return aggregated metrics for a campaign over date range."""

        def _call() -> dict[str, Any]:
            client = self._get_client()
            ga_service = client.get_service("GoogleAdsService")
            query = f"""
                SELECT
                    campaign.id,
                    metrics.impressions,
                    metrics.clicks,
                    metrics.cost_micros,
                    metrics.video_views
                FROM campaign
                WHERE campaign.resource_name = '{campaign_id}'
                AND segments.date BETWEEN '{date_from.isoformat()}' AND '{date_to.isoformat()}'
            """
            response = ga_service.search_stream(customer_id=self._customer_id, query=query)
            total: dict[str, Any] = {
                "impressions": 0,
                "clicks": 0,
                "cost_rub": 0.0,
                "video_views": 0,
            }
            for batch in response:
                for row in batch.results:
                    total["impressions"] += row.metrics.impressions
                    total["clicks"] += row.metrics.clicks
                    total["cost_rub"] += row.metrics.cost_micros / 1_000_000
                    total["video_views"] += row.metrics.video_views
            return total

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise RuntimeError(f"get_video_metrics failed: {exc}") from exc

    async def update_bid(self, campaign_id: str, new_bid: float) -> None:
        """Update the target CPA bid (in RUB) for a campaign."""

        def _call() -> None:
            client = self._get_client()
            campaign_service = client.get_service("CampaignService")
            op = client.get_type("CampaignOperation")
            campaign = op.update
            campaign.resource_name = campaign_id
            campaign.target_cpa.target_cpa_micros = int(new_bid * 1_000_000)
            campaign_service.mutate_campaigns(customer_id=self._customer_id, operations=[op])

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:
            raise RuntimeError(f"update_bid failed: {exc}") from exc

    async def pause_campaign(self, campaign_id: str) -> None:
        """Pause a running campaign."""

        def _call() -> None:
            client = self._get_client()
            campaign_service = client.get_service("CampaignService")
            op = client.get_type("CampaignOperation")
            campaign = op.update
            campaign.resource_name = campaign_id
            campaign.status = client.enums.CampaignStatusEnum.PAUSED
            campaign_service.mutate_campaigns(customer_id=self._customer_id, operations=[op])

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:
            raise RuntimeError(f"pause_campaign failed: {exc}") from exc

    async def generate_video_brief(
        self, product_name: str, product_description: str
    ) -> VideoCreativeBrief:
        """Use Claude to generate a creative brief for a YouTube ad video."""
        client = anthropic.Anthropic(api_key=self._anthropic_api_key)
        prompt = f"""Generate a YouTube ad creative brief for:
Product: {product_name}
Description: {product_description}

Return a JSON object with:
- "hook_text": first 5 seconds hook (max 15 words)
- "main_message": core value proposition (max 30 words)
- "cta_text": call-to-action (max 10 words)
- "target_audience_desc": who this is for (max 25 words)
- "recommended_duration_sec": integer (15, 30, or 60)
- "key_visuals": list of 3-5 scene descriptions

Return only valid JSON, no markdown."""

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        return VideoCreativeBrief(**data)
