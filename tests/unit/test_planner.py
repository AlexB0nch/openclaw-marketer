"""Unit tests for Strategist planner logic."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from integrations.strategist.models import (
    ContentPlan,
    ProductPlan,
    TopicEntry,
    WeeklyMetrics,
)
from integrations.strategist.planner import (
    calculate_weekly_metrics,
    fetch_active_products,
    generate_topics_for_product,
    generate_weekly_plan,
)


class TestCalculateWeeklyMetrics:
    """Test weekly metrics calculation."""

    @pytest.mark.asyncio
    async def test_calculate_metrics_no_data(self, db_session):
        """Test metrics calculation with no data."""
        metrics = await calculate_weekly_metrics(db_session, date(2026, 4, 27), date(2026, 5, 3))

        assert metrics.total_impressions == 0
        assert metrics.total_clicks == 0
        assert metrics.avg_ctr == 0.0


class TestFetchActiveProducts:
    """Test active products fetching."""

    @pytest.mark.asyncio
    async def test_fetch_active_products_empty(self, db_session):
        """Test fetching when no products exist."""
        products = await fetch_active_products(db_session)
        assert isinstance(products, list)


class TestGenerateTopicsForProduct:
    """Test topic generation for products."""

    @pytest.mark.asyncio
    async def test_generate_topics_returns_list(self):
        """Test that topic generation returns valid list."""
        product = {"id": 1, "name": "Test Product", "description": "Test", "url": "http://test"}
        topics = await generate_topics_for_product(product)

        assert isinstance(topics, list)
        assert len(topics) > 0
        assert all(isinstance(t, TopicEntry) for t in topics)

    @pytest.mark.asyncio
    async def test_generated_topics_have_required_fields(self):
        """Test generated topics have all required fields."""
        product = {"id": 1, "name": "Test", "description": "", "url": ""}
        topics = await generate_topics_for_product(product)

        for topic in topics:
            assert hasattr(topic, "topic")
            assert hasattr(topic, "channel")
            assert hasattr(topic, "estimated_engagement")
            assert hasattr(topic, "notes")
            assert topic.channel in ["telegram", "blog", "habr", "youtube"]
            assert 0 <= topic.estimated_engagement <= 100


class TestGenerateWeeklyPlan:
    """Test weekly plan generation."""

    @pytest.mark.asyncio
    async def test_generate_plan_structure(self, db_session):
        """Test that generated plan has correct structure."""
        week_start = date(2026, 4, 27)
        plan = await generate_weekly_plan(db_session, week_start)

        assert isinstance(plan, ContentPlan)
        assert plan.week_start_date == week_start
        assert plan.week_end_date == date(2026, 5, 3)
        assert plan.status == "pending_approval"
        assert isinstance(plan.products, list)
        assert isinstance(plan.metrics_summary, WeeklyMetrics)

    @pytest.mark.asyncio
    async def test_plan_has_valid_types(self, db_session):
        """Test plan has proper type hints compliance."""
        plan = await generate_weekly_plan(db_session, date(2026, 4, 27))

        assert isinstance(plan.created_at, datetime)
        assert plan.approved_by_user is None
        assert plan.approval_reason is None
        assert plan.approved_at is None


class TestContentPlanModel:
    """Test ContentPlan Pydantic model."""

    def test_content_plan_validation(self):
        """Test ContentPlan model validates correctly."""
        metrics = WeeklyMetrics(
            week_start=date(2026, 4, 27),
            total_impressions=1000,
            total_clicks=50,
            avg_ctr=5.0,
            total_spend_rub=Decimal("1000.00"),
            roi=2.0,
        )

        product_plan = ProductPlan(
            product_id=1,
            product_name="Test",
            topics=[
                TopicEntry(
                    topic="Test topic",
                    channel="telegram",
                    estimated_engagement=80,
                    notes="Test",
                )
            ],
            budget_allocation_rub=Decimal("1000.00"),
            priority="high",
        )

        plan = ContentPlan(
            week_start_date=date(2026, 4, 27),
            week_end_date=date(2026, 5, 3),
            products=[product_plan],
            metrics_summary=metrics,
            created_at=datetime.now(),
        )

        assert plan.status == "pending_approval"
        assert len(plan.products) == 1
        assert plan.products[0].product_name == "Test"

    def test_content_plan_json_serialization(self):
        """Test ContentPlan can be serialized to JSON."""
        metrics = WeeklyMetrics(
            week_start=date(2026, 4, 27),
            total_impressions=100,
            total_clicks=5,
            avg_ctr=5.0,
            total_spend_rub=Decimal("500.00"),
            roi=1.0,
        )

        product_plan = ProductPlan(
            product_id=1,
            product_name="Product",
            topics=[
                TopicEntry(
                    topic="Topic",
                    channel="blog",
                    estimated_engagement=75,
                    notes="Note",
                )
            ],
            budget_allocation_rub=Decimal("500.00"),
            priority="medium",
        )

        plan = ContentPlan(
            week_start_date=date(2026, 4, 27),
            week_end_date=date(2026, 5, 3),
            products=[product_plan],
            metrics_summary=metrics,
            created_at=datetime.now(),
        )

        json_str = plan.model_dump_json()
        assert isinstance(json_str, str)
        assert "pending_approval" in json_str
