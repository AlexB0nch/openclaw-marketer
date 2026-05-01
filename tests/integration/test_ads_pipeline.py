"""Integration tests for the Ads Agent pipeline."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.ads.approval import AdsApprovalManager
from integrations.ads.budget_monitor import BudgetMonitor
from integrations.yandex_direct.ab_test import ABTestManager
from integrations.yandex_direct.campaigns import (
    AdVariant,
    BidStrategy,
    CampaignConfig,
    create_draft,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ads_db(db_session):
    """Seed ad_campaigns, ad_variants, ad_daily_spend for tests."""
    config = {
        "name": "AI Ассистент — поиск",
        "product_id": 1,
        "budget_rub": 15000.0,
        "keywords": ["ai ассистент", "автоматизация"],
        "ads": [
            {
                "title1": "AI Ассистент",
                "title2": "Для бизнеса",
                "text": "Попробуйте бесплатно",
                "display_url": "example.com/ai",
                "final_url": "https://example.com/ai",
            },
            {
                "title1": "Умный помощник",
                "title2": "Сэкономьте время",
                "text": "14 дней бесплатно",
                "display_url": "example.com/ai",
                "final_url": "https://example.com/ai",
            },
        ],
        "strategy": "HIGHEST_CLICK_RATE",
        "start_date": "2026-04-28",
        "end_date": "2026-05-28",
    }

    # Draft campaign (id=1)
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns "
            "(id, product_id, platform, status, config_json, budget_rub, spent_rub) "
            "VALUES (1, 1, 'yandex', 'draft', :cfg, 15000.0, 0.0)"
        ),
        {"cfg": json.dumps(config)},
    )

    # pending_approval campaign (id=2)
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns "
            "(id, product_id, platform, status, config_json, budget_rub, spent_rub) "
            "VALUES (2, 1, 'yandex', 'pending_approval', :cfg, 15000.0, 0.0)"
        ),
        {"cfg": json.dumps(config)},
    )

    # running campaign with two variants (id=3)
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns "
            "(id, product_id, platform, status, config_json, budget_rub, spent_rub,"
            " campaign_id_external) "
            "VALUES (3, 1, 'yandex', 'running', :cfg, 15000.0, 2000.0, '99001')"
        ),
        {"cfg": json.dumps(config)},
    )
    # Variant A: higher CTR
    await db_session.execute(
        text(
            "INSERT INTO ad_variants "
            "(id, campaign_id, title1, title2, text, display_url, final_url,"
            " clicks, impressions, ctr, status) "
            "VALUES (1, 3, 'AI Ассистент', 'Для бизнеса', 'Попробуйте',"
            " 'example.com', 'https://example.com', 200, 2000, 0.1, 'active')"
        )
    )
    # Variant B: lower CTR
    await db_session.execute(
        text(
            "INSERT INTO ad_variants "
            "(id, campaign_id, title1, title2, text, display_url, final_url,"
            " clicks, impressions, ctr, status) "
            "VALUES (2, 3, 'Умный помощник', 'Сэкономьте', '14 дней',"
            " 'example.com', 'https://example.com', 50, 2000, 0.025, 'active')"
        )
    )

    # Daily spend rows for budget monitor tests
    today = date.today().isoformat()
    await db_session.execute(
        text(
            "INSERT INTO ad_daily_spend (campaign_id, date, spend_rub, clicks, impressions, ctr) "
            "VALUES (3, :d, 6000.0, 100, 1000, 0.1)"
        ),
        {"d": today},
    )

    await db_session.commit()
    return db_session


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_campaign_draft_created(db_session):
    """create_draft saves campaign to DB with status='draft'."""
    config = CampaignConfig(
        name="Test Campaign",
        product_id=1,
        budget_rub=10_000.0,
        keywords=["тест", "кампания"],
        ads=[
            AdVariant(
                title1="Заголовок 1",
                title2="Заголовок 2",
                text="Текст объявления",
                display_url="example.com",
                final_url="https://example.com",
            ),
            AdVariant(
                title1="Вариант 2",
                title2="Подзаголовок",
                text="Другой текст",
                display_url="example.com",
                final_url="https://example.com",
            ),
        ],
        strategy=BidStrategy.HIGHEST_CLICK_RATE,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
    )

    campaign_id = await create_draft(db_session, config)

    assert campaign_id is not None
    assert campaign_id > 0

    row = await db_session.execute(
        text("SELECT status, budget_rub, platform FROM ad_campaigns WHERE id = :id"),
        {"id": campaign_id},
    )
    record = row.fetchone()
    assert record is not None
    assert record[0] == "draft"
    assert record[1] == pytest.approx(10_000.0)
    assert record[2] == "yandex"


@pytest.mark.asyncio
async def test_approval_request_sent_to_telegram(ads_db):
    """send_campaign_approval calls bot.send_message and sets status to pending_approval."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    manager = AdsApprovalManager()
    await manager.send_campaign_approval(
        session=ads_db,
        bot=mock_bot,
        chat_id="12345",
        campaign_id=1,
    )

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "12345"
    assert "1" in call_kwargs["text"]  # campaign id in message

    row = await ads_db.execute(text("SELECT status FROM ad_campaigns WHERE id = 1"))
    assert row.fetchone()[0] == "pending_approval"


@pytest.mark.asyncio
async def test_approve_launches_campaign(ads_db):
    """handle_approval_callback changes status to running after creating campaign via API."""
    mock_client = MagicMock()
    mock_client.create_campaign = AsyncMock(return_value=12345)

    manager = AdsApprovalManager()
    await manager.handle_approval_callback(
        session=ads_db,
        yandex_client=mock_client,
        campaign_id=2,
        actor="admin",
    )

    mock_client.create_campaign.assert_called_once()

    row = await ads_db.execute(
        text("SELECT status, campaign_id_external FROM ad_campaigns WHERE id = 2")
    )
    record = row.fetchone()
    assert record[0] == "running"
    assert record[1] == "12345"

    # Approval log entry created
    row2 = await ads_db.execute(
        text(
            "SELECT action, actor FROM ad_approvals "
            "WHERE campaign_id = 2 AND action = 'approved'"
        )
    )
    approval = row2.fetchone()
    assert approval is not None
    assert approval[1] == "admin"


@pytest.mark.asyncio
async def test_approve_rejects_wrong_status(ads_db):
    """handle_approval_callback raises ValueError if campaign not in pending_approval state."""
    mock_client = MagicMock()
    mock_client.create_campaign = AsyncMock(return_value=99)

    manager = AdsApprovalManager()
    with pytest.raises(ValueError, match="pending_approval"):
        await manager.handle_approval_callback(
            session=ads_db,
            yandex_client=mock_client,
            campaign_id=1,  # status is 'draft', not 'pending_approval'
            actor="admin",
        )

    mock_client.create_campaign.assert_not_called()


@pytest.mark.asyncio
async def test_reject_sets_status(ads_db):
    """handle_rejection_callback sets status=rejected and logs rejection."""
    manager = AdsApprovalManager()
    await manager.handle_rejection_callback(
        session=ads_db,
        campaign_id=2,
        reason="Budget too high",
        actor="admin",
    )

    row = await ads_db.execute(text("SELECT status FROM ad_campaigns WHERE id = 2"))
    assert row.fetchone()[0] == "rejected"

    row2 = await ads_db.execute(
        text(
            "SELECT action, actor, reason FROM ad_approvals "
            "WHERE campaign_id = 2 AND action = 'rejected'"
        )
    )
    record = row2.fetchone()
    assert record is not None
    assert record[1] == "admin"
    assert record[2] == "Budget too high"


@pytest.mark.asyncio
async def test_budget_monitor_daily_spend(ads_db, test_settings):
    """check_daily_spend returns today's total spend from ad_daily_spend."""
    mock_client = MagicMock()
    monitor = BudgetMonitor(test_settings)

    daily = await monitor.check_daily_spend(ads_db, mock_client)
    assert daily == pytest.approx(6000.0)


@pytest.mark.asyncio
async def test_budget_monitor_pauses_on_limit(ads_db, test_settings):
    """auto_pause_on_limit pauses all running campaigns when monthly limit is hit."""
    # Insert enough spend in the current month to exceed the monthly limit.
    # Use the first of the current month so the row is always within
    # check_monthly_spend's [month_start, today] window.
    month_start = date.today().replace(day=1).isoformat()
    await ads_db.execute(
        text(
            "INSERT INTO ad_daily_spend "
            "(campaign_id, date, spend_rub, clicks, impressions, ctr) "
            "VALUES (3, :d, 95000.0, 1000, 10000, 0.1)"
        ),
        {"d": month_start},
    )
    await ads_db.commit()

    mock_client = MagicMock()
    mock_client.pause_campaign = AsyncMock()

    test_settings.monthly_ads_budget_limit_rub = 100_000.0
    monitor = BudgetMonitor(test_settings)
    paused = await monitor.auto_pause_on_limit(ads_db, mock_client)

    assert paused is True
    mock_client.pause_campaign.assert_called_once_with(99001)

    row = await ads_db.execute(text("SELECT status FROM ad_campaigns WHERE id = 3"))
    assert row.fetchone()[0] == "paused"


@pytest.mark.asyncio
async def test_budget_monitor_no_pause_below_limit(ads_db, test_settings):
    """auto_pause_on_limit returns False when monthly spend is below limit."""
    mock_client = MagicMock()
    mock_client.pause_campaign = AsyncMock()

    test_settings.monthly_ads_budget_limit_rub = 1_000_000.0  # very high limit
    monitor = BudgetMonitor(test_settings)
    paused = await monitor.auto_pause_on_limit(ads_db, mock_client)

    assert paused is False
    mock_client.pause_campaign.assert_not_called()


@pytest.mark.asyncio
async def test_ab_test_selects_winner(ads_db):
    """evaluate_ab_test picks the variant with the highest CTR."""
    manager = ABTestManager()
    winner_id = await manager.evaluate_ab_test(ads_db, campaign_id=3)

    # Variant 1 has CTR=0.1, Variant 2 has CTR=0.025 → winner is variant 1
    assert winner_id == 1


@pytest.mark.asyncio
async def test_ab_test_pause_losing_variants(ads_db):
    """pause_losing_variants sets losing variants to 'paused' and keeps winner 'active'."""
    mock_client = MagicMock()
    mock_client.pause_campaign = AsyncMock()

    manager = ABTestManager()
    await manager.pause_losing_variants(ads_db, campaign_id=3, client=mock_client)

    row_winner = await ads_db.execute(text("SELECT status FROM ad_variants WHERE id = 1"))
    row_loser = await ads_db.execute(text("SELECT status FROM ad_variants WHERE id = 2"))

    # Winner stays active, loser gets paused
    assert row_winner.fetchone()[0] == "active"
    assert row_loser.fetchone()[0] == "paused"


@pytest.mark.asyncio
async def test_ab_test_no_variants_returns_none(db_session):
    """evaluate_ab_test returns None when campaign has no active variants."""
    # Insert a campaign with no variants
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns "
            "(id, product_id, platform, status, config_json, budget_rub) "
            "VALUES (99, 1, 'yandex', 'running', '{}', 5000.0)"
        )
    )
    await db_session.commit()

    manager = ABTestManager()
    winner = await manager.evaluate_ab_test(db_session, campaign_id=99)
    assert winner is None
