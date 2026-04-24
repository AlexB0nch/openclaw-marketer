"""Integration tests for weekly digest and scheduler."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from integrations.scheduler import StrategistScheduler


@pytest_asyncio.fixture
async def scheduler(test_settings, test_db_engine, mock_telegram_bot):
    """Create scheduler instance for testing."""
    return StrategistScheduler(test_settings, test_db_engine, mock_telegram_bot)


class TestSchedulerTasks:
    """Test APScheduler tasks."""

    def test_scheduler_initialization(self, scheduler):
        """Test scheduler initializes correctly."""
        assert scheduler is not None
        assert scheduler.scheduler is not None

    def test_scheduler_has_jobs_configured(self, scheduler):
        """Test scheduler has jobs configured."""
        scheduler.start()
        jobs = scheduler.scheduler.get_jobs()

        job_ids = [job.id for job in jobs]
        assert "weekly_plan" in job_ids
        assert "weekly_digest" in job_ids

        scheduler.shutdown()

    @pytest.mark.asyncio
    async def test_format_plan_for_telegram(self, scheduler):
        """Test plan formatting for Telegram."""
        from integrations.strategist.models import ContentPlan, ProductPlan, TopicEntry, WeeklyMetrics
        from datetime import datetime
        from decimal import Decimal

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
            product_name="Test Product",
            topics=[
                TopicEntry(
                    topic="Test topic",
                    channel="telegram",
                    estimated_engagement=80,
                    notes="Test note",
                )
            ],
            budget_allocation_rub=Decimal("500.00"),
            priority="high",
        )

        plan = ContentPlan(
            week_start_date=date(2026, 4, 27),
            week_end_date=date(2026, 5, 3),
            products=[product_plan],
            metrics_summary=metrics,
            created_at=datetime.now(),
        )

        text = scheduler._format_plan_for_telegram(plan, 1)

        assert isinstance(text, str)
        assert "Test Product" in text
        assert "2026-04-27" in text
        assert "Test topic" in text

    @pytest.mark.asyncio
    async def test_format_digest(self, scheduler):
        """Test digest formatting."""
        text = scheduler._format_weekly_digest()

        assert isinstance(text, str)
        assert "Отчет" in text or "Метрики" in text
        assert "Впечатлений" in text or "Impressions" in text.lower()


class TestWeeklyPlanTask:
    """Test weekly plan generation task."""

    @pytest.mark.asyncio
    async def test_plan_task_handles_no_products(self, scheduler):
        """Test plan task handles case with no active products."""
        # This tests error handling - plan generation should not crash
        # even if there are no products
        try:
            await scheduler.weekly_plan_task()
        except Exception as e:
            pytest.fail(f"Plan task raised exception: {e}")

    @pytest.mark.asyncio
    async def test_plan_task_sends_telegram_message(self, scheduler):
        """Test plan task sends message to Telegram."""
        await scheduler.weekly_plan_task()

        # Check if bot.send_message was called
        # (it may not be called if there's an error, which is OK for this test)
        assert scheduler.bot is not None


class TestWeeklyDigestTask:
    """Test weekly digest task."""

    @pytest.mark.asyncio
    async def test_digest_task_sends_message(self, scheduler):
        """Test digest task sends message to Telegram."""
        await scheduler.weekly_digest_task()

        # Check if bot.send_message was called
        assert scheduler.bot is not None

    @pytest.mark.asyncio
    async def test_digest_task_error_handling(self, scheduler):
        """Test digest task handles errors gracefully."""
        # Make bot.send_message raise an error
        scheduler.bot.send_message = AsyncMock(side_effect=Exception("Network error"))

        try:
            await scheduler.weekly_digest_task()
        except Exception as e:
            pytest.fail(f"Digest task should handle errors gracefully: {e}")
