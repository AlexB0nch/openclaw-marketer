"""Unit tests for campaign config factory."""

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from integrations.yandex_direct.campaigns import (
    AdVariant,
    BidStrategy,
    CampaignConfig,
    create_draft,
    generate_campaign_config,
)


def _mock_claude_response(keywords: list[str], ads: list[dict]) -> MagicMock:
    payload = json.dumps({"keywords": keywords, "ads": ads})
    content = MagicMock()
    content.text = payload
    response = MagicMock()
    response.content = [content]
    return response


@pytest.mark.asyncio
async def test_generate_campaign_config_returns_config(test_settings):
    ads = [
        {
            "title1": "Купить AI ассистент",
            "title2": "Скидка 20%",
            "text": "Умный помощник для бизнеса. Попробуйте бесплатно!",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
        {
            "title1": "AI для бизнеса",
            "title2": "Начните сейчас",
            "text": "Автоматизируйте рутину с AI. Первый месяц бесплатно!",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
        {
            "title1": "Умный ассистент",
            "title2": "Для команды",
            "text": "Сэкономьте 3 часа в день с AI ассистентом.",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
    ]
    mock_response = _mock_claude_response(["купить ai ассистент", "ai для бизнеса"], ads)

    with patch("integrations.yandex_direct.campaigns.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client

        config = await generate_campaign_config(
            product_name="AI Ассистент",
            goal="лиды",
            budget_rub=10000.0,
            settings=test_settings,
        )

    assert isinstance(config, CampaignConfig)
    assert len(config.ads) == 3
    assert len(config.keywords) >= 2
    assert config.budget_rub == 10000.0


@pytest.mark.asyncio
async def test_generate_campaign_config_3_ad_variants(test_settings):
    ads = [
        {
            "title1": "Title 1A",
            "title2": "Sub 1A",
            "text": "Text 1A for ad variant.",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
        {
            "title1": "Title 2A",
            "title2": "Sub 2A",
            "text": "Text 2A for ad variant.",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
        {
            "title1": "Title 3A",
            "title2": "Sub 3A",
            "text": "Text 3A for ad variant.",
            "display_url": "example.com",
            "final_url": "https://example.com",
        },
    ]
    mock_response = _mock_claude_response(["kw1", "kw2"], ads)
    with patch("integrations.yandex_direct.campaigns.anthropic.Anthropic") as mock_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_cls.return_value = mock_client
        config = await generate_campaign_config("Product", "sales", 5000.0, test_settings)

    assert len(config.ads) == 3
    for ad in config.ads:
        assert isinstance(ad, AdVariant)


@pytest.mark.asyncio
async def test_create_draft_returns_id(db_session, test_settings):
    ads = [
        AdVariant(
            title1="T1",
            title2="T2",
            text="Text ad",
            display_url="ex.com",
            final_url="https://ex.com",
        ),
        AdVariant(
            title1="T3",
            title2="T4",
            text="Text ad2",
            display_url="ex.com",
            final_url="https://ex.com",
        ),
        AdVariant(
            title1="T5",
            title2="T6",
            text="Text ad3",
            display_url="ex.com",
            final_url="https://ex.com",
        ),
    ]
    config = CampaignConfig(
        name="Test Campaign",
        product_id=1,
        budget_rub=5000.0,
        keywords=["kw1", "kw2"],
        ads=ads,
        strategy=BidStrategy.HIGHEST_CLICK_RATE,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )
    campaign_id = await create_draft(db_session, config)
    assert isinstance(campaign_id, int)
    assert campaign_id > 0


@pytest.mark.asyncio
async def test_create_draft_status_is_draft(db_session, test_settings):
    from sqlalchemy import text as sqla_text

    ads = [
        AdVariant(
            title1="T1", title2="T2", text="Text", display_url="ex.com", final_url="https://ex.com"
        )
    ] * 3
    config = CampaignConfig(
        name="Draft Check",
        product_id=1,
        budget_rub=1000.0,
        keywords=["kw"],
        ads=ads,
        strategy=BidStrategy.AVERAGE_CPC,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )
    campaign_id = await create_draft(db_session, config)
    row = await db_session.execute(
        sqla_text("SELECT status FROM ad_campaigns WHERE id = :id"), {"id": campaign_id}
    )
    status = row.fetchone()[0]
    assert status == "draft"
