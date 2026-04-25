"""Unit tests for ABTestManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import text

from integrations.yandex_direct.ab_test import ABTestManager

_CAMPAIGN_CONFIG = (
    '{"ads": ['
    '{"title1": "T1", "title2": "S1", "text": "Text1", "display_url": "ex.com", "final_url": "https://ex.com"}, '
    '{"title1": "T2", "title2": "S2", "text": "Text2", "display_url": "ex.com", "final_url": "https://ex.com"}, '
    '{"title1": "T3", "title2": "S3", "text": "Text3", "display_url": "ex.com", "final_url": "https://ex.com"}'
    "]}"
)


@pytest_asyncio.fixture
async def ab_test_db(db_session):
    """Seed ad_campaigns and ad_variants for AB test."""
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns (id, product_id, platform, status, config_json, budget_rub, spent_rub) "
            "VALUES (1, 1, 'yandex', 'running', :config, 5000.0, 0.0)"
        ),
        {"config": _CAMPAIGN_CONFIG},
    )
    await db_session.commit()
    return db_session


@pytest.mark.asyncio
async def test_start_ab_test_creates_variants(ab_test_db):
    manager = ABTestManager()
    variant_ids = await manager.start_ab_test(ab_test_db, campaign_id=1)
    assert len(variant_ids) == 3


@pytest.mark.asyncio
async def test_evaluate_ab_test_returns_winner(ab_test_db):
    manager = ABTestManager()
    await manager.start_ab_test(ab_test_db, campaign_id=1)

    # Simulate metrics: variant with most clicks wins
    rows = await ab_test_db.execute(text("SELECT id FROM ad_variants WHERE campaign_id = 1"))
    ids = [r[0] for r in rows.fetchall()]

    # Give variant 0 the best CTR
    await ab_test_db.execute(
        text("UPDATE ad_variants SET clicks = 100, impressions = 1000, ctr = 10.0 WHERE id = :id"),
        {"id": ids[0]},
    )
    await ab_test_db.execute(
        text("UPDATE ad_variants SET clicks = 30, impressions = 1000, ctr = 3.0 WHERE id = :id"),
        {"id": ids[1]},
    )
    await ab_test_db.execute(
        text("UPDATE ad_variants SET clicks = 20, impressions = 1000, ctr = 2.0 WHERE id = :id"),
        {"id": ids[2]},
    )
    await ab_test_db.commit()

    winner = await manager.evaluate_ab_test(ab_test_db, campaign_id=1)
    assert winner == ids[0]


@pytest.mark.asyncio
async def test_evaluate_ab_test_no_data_returns_none(db_session):
    await db_session.execute(
        text(
            "INSERT INTO ad_campaigns (id, product_id, platform, status, config_json, budget_rub, spent_rub) "
            "VALUES (99, 1, 'yandex', 'running', '{}', 1000.0, 0.0)"
        )
    )
    await db_session.commit()
    manager = ABTestManager()
    result = await manager.evaluate_ab_test(db_session, campaign_id=99)
    assert result is None


@pytest.mark.asyncio
async def test_pause_losing_variants(ab_test_db):
    manager = ABTestManager()
    await manager.start_ab_test(ab_test_db, campaign_id=1)

    rows = await ab_test_db.execute(text("SELECT id FROM ad_variants WHERE campaign_id = 1"))
    ids = [r[0] for r in rows.fetchall()]

    await ab_test_db.execute(
        text("UPDATE ad_variants SET ctr = 10.0 WHERE id = :id"), {"id": ids[0]}
    )
    await ab_test_db.execute(
        text("UPDATE ad_variants SET ctr = 3.0 WHERE id = :id"), {"id": ids[1]}
    )
    await ab_test_db.execute(
        text("UPDATE ad_variants SET ctr = 2.0 WHERE id = :id"), {"id": ids[2]}
    )
    await ab_test_db.commit()

    mock_client = MagicMock()
    mock_client.pause_campaign = AsyncMock()
    await manager.pause_losing_variants(ab_test_db, campaign_id=1, client=mock_client)

    rows = await ab_test_db.execute(
        text("SELECT status FROM ad_variants WHERE campaign_id = 1 AND id != :winner"),
        {"winner": ids[0]},
    )
    statuses = [r[0] for r in rows.fetchall()]
    assert all(s == "paused" for s in statuses)
