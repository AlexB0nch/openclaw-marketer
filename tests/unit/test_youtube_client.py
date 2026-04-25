"""Unit tests for GoogleAdsYouTubeClient."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.google_ads.youtube_client import (
    GoogleAdsYouTubeClient,
    VideoCampaignConfig,
    VideoCreativeBrief,
)


@pytest.fixture
def yt_client(test_settings):
    return GoogleAdsYouTubeClient(test_settings)


def _make_mock_google_ads_client() -> MagicMock:
    """Mock GoogleAdsClient and its services."""
    mock_client = MagicMock()

    # Budget service
    budget_result = MagicMock()
    budget_result.resource_name = "customers/123/campaignBudgets/1"
    budget_response = MagicMock()
    budget_response.results = [budget_result]
    mock_budget_service = MagicMock()
    mock_budget_service.mutate_campaign_budgets.return_value = budget_response

    # Campaign service
    campaign_result = MagicMock()
    campaign_result.resource_name = "customers/123/campaigns/456"
    campaign_response = MagicMock()
    campaign_response.results = [campaign_result]
    mock_campaign_service = MagicMock()
    mock_campaign_service.mutate_campaigns.return_value = campaign_response

    # GoogleAds service for metrics
    mock_row = MagicMock()
    mock_row.metrics.impressions = 5000
    mock_row.metrics.clicks = 150
    mock_row.metrics.cost_micros = 2_000_000_000  # 2000 RUB
    mock_row.metrics.video_views = 3000
    mock_batch = MagicMock()
    mock_batch.results = [mock_row]
    mock_ga_service = MagicMock()
    mock_ga_service.search_stream.return_value = [mock_batch]

    def get_service(name: str) -> MagicMock:
        if name == "CampaignBudgetService":
            return mock_budget_service
        if name == "CampaignService":
            return mock_campaign_service
        if name == "GoogleAdsService":
            return mock_ga_service
        return MagicMock()

    mock_client.get_service.side_effect = get_service
    mock_client.get_type.return_value = MagicMock()
    mock_client.enums = MagicMock()
    return mock_client


@pytest.mark.asyncio
async def test_create_video_campaign_returns_resource_name(
    yt_client: GoogleAdsYouTubeClient,
) -> None:
    mock_google_client = _make_mock_google_ads_client()
    with patch.object(yt_client, "_get_client", return_value=mock_google_client):
        config = VideoCampaignConfig(
            name="Test YouTube Campaign",
            product_id=1,
            budget_rub=10000.0,
            target_audiences=["молодежь 18-35", "предприниматели"],
            video_url="https://www.youtube.com/watch?v=test123",
            bid_strategy="TARGET_CPA",
        )
        resource_name = await yt_client.create_video_campaign(config)

    assert resource_name  # resource name returned


@pytest.mark.asyncio
async def test_get_video_metrics_returns_dict(yt_client: GoogleAdsYouTubeClient) -> None:
    mock_google_client = _make_mock_google_ads_client()
    with patch.object(yt_client, "_get_client", return_value=mock_google_client):
        metrics = await yt_client.get_video_metrics(
            "customers/123/campaigns/456",
            date(2026, 4, 1),
            date(2026, 4, 7),
        )

    assert "impressions" in metrics
    assert "clicks" in metrics
    assert "cost_rub" in metrics
    assert "video_views" in metrics
    assert metrics["impressions"] == 5000
    assert metrics["cost_rub"] == pytest.approx(2000.0)


@pytest.mark.asyncio
async def test_pause_campaign_calls_service(yt_client: GoogleAdsYouTubeClient) -> None:
    mock_google_client = _make_mock_google_ads_client()
    with patch.object(yt_client, "_get_client", return_value=mock_google_client):
        await yt_client.pause_campaign("customers/123/campaigns/456")
    # Should not raise


@pytest.mark.asyncio
async def test_update_bid_calls_service(yt_client: GoogleAdsYouTubeClient) -> None:
    mock_google_client = _make_mock_google_ads_client()
    with patch.object(yt_client, "_get_client", return_value=mock_google_client):
        await yt_client.update_bid("customers/123/campaigns/456", new_bid=150.0)
    # Should not raise


@pytest.mark.asyncio
async def test_generate_video_brief_returns_brief(yt_client: GoogleAdsYouTubeClient) -> None:
    brief_data = {
        "hook_text": "Устали от ручной работы?",
        "main_message": "AI ассистент сэкономит 3 часа в день",
        "cta_text": "Попробуйте бесплатно сегодня",
        "target_audience_desc": "Предприниматели и менеджеры 25-45 лет",
        "recommended_duration_sec": 30,
        "key_visuals": [
            "Перегруженный офис",
            "AI интерфейс",
            "Расслабленный предприниматель",
        ],
    }
    content = MagicMock()
    content.text = json.dumps(brief_data)
    response = MagicMock()
    response.content = [content]

    with patch("integrations.google_ads.youtube_client.anthropic.Anthropic") as mock_cls:
        mock_anthropic = MagicMock()
        mock_anthropic.messages.create.return_value = response
        mock_cls.return_value = mock_anthropic

        brief = await yt_client.generate_video_brief(
            "AI Ассистент",
            "Умный помощник для автоматизации бизнеса",
        )

    assert isinstance(brief, VideoCreativeBrief)
    assert brief.recommended_duration_sec == 30
    assert len(brief.key_visuals) == 3


@pytest.mark.asyncio
async def test_create_video_campaign_api_error(yt_client: GoogleAdsYouTubeClient) -> None:
    def _raise() -> MagicMock:
        raise RuntimeError("API error")

    with patch.object(yt_client, "_get_client", side_effect=_raise), pytest.raises(RuntimeError):
        await yt_client.create_video_campaign(
            VideoCampaignConfig(
                name="Test",
                product_id=1,
                budget_rub=5000.0,
                target_audiences=["all"],
                video_url="https://youtube.com/watch?v=abc",
            )
        )


@pytest.mark.asyncio
async def test_video_campaign_config_validation() -> None:
    config = VideoCampaignConfig(
        name="My Campaign",
        product_id=2,
        budget_rub=20000.0,
        target_audiences=["18-35", "технари"],
        video_url="https://www.youtube.com/watch?v=xyz",
    )
    assert config.budget_rub == 20000.0
    assert len(config.target_audiences) == 2
