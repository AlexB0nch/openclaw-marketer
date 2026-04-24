"""Strategist planner: weekly content plan generation."""

from datetime import date, datetime, timedelta
from decimal import Decimal
import json

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    ContentPlan,
    PlanApprovalLog,
    ProductPlan,
    TopicEntry,
    WeeklyMetrics,
)


async def calculate_weekly_metrics(
    session: AsyncSession, week_start: date, week_end: date
) -> WeeklyMetrics:
    """Query and aggregate metrics for a given week."""
    from app.models import Metrics, Product  # avoid circular imports

    stmt = select(
        Metrics.product_id,
        Metrics.date,
    ).where((Metrics.date >= week_start) & (Metrics.date <= week_end))
    result = await session.execute(stmt)
    rows = result.fetchall()

    if not rows:
        return WeeklyMetrics(
            week_start=week_start,
            total_impressions=0,
            total_clicks=0,
            avg_ctr=0.0,
            total_spend_rub=Decimal("0.00"),
            roi=0.0,
            top_performing_product=None,
        )

    total_impressions = 0
    total_clicks = 0
    total_spend = Decimal("0.00")

    for row in rows:
        # Aggregate metrics (assuming these columns exist in Metrics table)
        # This is a simplified version; adjust based on actual schema
        pass

    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0.0

    return WeeklyMetrics(
        week_start=week_start,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        avg_ctr=avg_ctr,
        total_spend_rub=total_spend,
        roi=0.0,
        top_performing_product=None,
    )


async def fetch_active_products(session: AsyncSession) -> list[dict]:
    """Get active products with recent campaign data."""
    from app.models import Product, Campaign

    stmt = select(Product).where(Product.active == True)
    result = await session.execute(stmt)
    products = result.scalars().all()

    products_data = []
    for product in products:
        products_data.append(
            {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "url": product.url,
            }
        )

    return products_data


async def generate_topics_for_product(product: dict) -> list[TopicEntry]:
    """
    Generate topic suggestions for a product.

    In production, this would call Claude API with prompt caching.
    For Sprint 1, we use static suggestions.
    """
    topics = [
        TopicEntry(
            topic=f"Launch campaign for {product['name']}",
            channel="telegram",
            estimated_engagement=85,
            notes="High engagement expected based on product relevance",
        ),
        TopicEntry(
            topic=f"Customer success story: {product['name']}",
            channel="blog",
            estimated_engagement=72,
            notes="Educational content, medium engagement",
        ),
        TopicEntry(
            topic=f"Technical deep dive: {product['name']} features",
            channel="habr",
            estimated_engagement=65,
            notes="Dev-focused, niche audience",
        ),
    ]
    return topics


async def generate_weekly_plan(
    session: AsyncSession,
    week_start: date,
) -> ContentPlan:
    """
    Orchestrate plan generation: fetch data → calculate metrics → generate topics → assemble plan.
    """
    week_end = week_start + timedelta(days=6)

    # 1. Calculate metrics for this week
    metrics = await calculate_weekly_metrics(session, week_start, week_end)

    # 2. Fetch active products
    products_data = await fetch_active_products(session)

    # 3. Generate topics for each product
    product_plans = []
    for product in products_data:
        topics = await generate_topics_for_product(product)
        budget = Decimal("2000.00")  # Simplified budget allocation

        product_plan = ProductPlan(
            product_id=product["id"],
            product_name=product["name"],
            topics=topics,
            budget_allocation_rub=budget,
            priority="high" if metrics.total_impressions > 1000 else "medium",
        )
        product_plans.append(product_plan)

    # 4. Assemble ContentPlan
    plan = ContentPlan(
        week_start_date=week_start,
        week_end_date=week_end,
        products=product_plans,
        metrics_summary=metrics,
        status="pending_approval",
        created_at=datetime.now(),
    )

    return plan


async def save_plan_to_db(session: AsyncSession, plan: ContentPlan) -> int:
    """Persist plan to database and create approval log entry."""
    from sqlalchemy import func

    # Check for existing plan for this week
    stmt = select(func.count()).select_from(
        select(1).where(
            (select("id").select_from("content_plans")).c.week_start_date == plan.week_start_date
        )
    )

    # Insert plan
    plan_data = {
        "week_start_date": plan.week_start_date,
        "week_end_date": plan.week_end_date,
        "status": plan.status,
        "plan_json": plan.model_dump_json(),
        "created_by_agent": "strategist",
        "created_at": datetime.now(),
    }

    stmt = insert("content_plans").values(**plan_data)
    result = await session.execute(stmt)
    plan_id = result.inserted_primary_key[0]

    # Insert approval log entry
    log_data = {
        "plan_id": plan_id,
        "action": "submitted",
        "actor": "strategist",
        "timestamp": datetime.now(),
    }
    stmt = insert("plan_approvals").values(**log_data)
    await session.execute(stmt)

    await session.commit()
    return plan_id


async def get_plan_by_id(session: AsyncSession, plan_id: int) -> ContentPlan | None:
    """Fetch and deserialize a plan from database."""
    from sqlalchemy import text

    stmt = text("SELECT plan_json, status, created_at FROM content_plans WHERE id = :id")
    result = await session.execute(stmt, {"id": plan_id})
    row = result.first()

    if not row:
        return None

    plan_dict = json.loads(row[0])
    plan_dict["status"] = row[1]
    plan_dict["created_at"] = row[2]

    return ContentPlan(**plan_dict)


async def update_plan_status(
    session: AsyncSession,
    plan_id: int,
    new_status: str,
    approved_by: str | None = None,
    reason: str | None = None,
) -> bool:
    """Update plan status and log approval action."""
    from sqlalchemy import text

    update_dict = {
        "status": new_status,
    }
    if approved_by:
        update_dict["approved_by_user"] = approved_by
        update_dict["approved_at"] = datetime.now()
    if reason:
        update_dict["approval_reason"] = reason

    stmt = text(
        """UPDATE content_plans
           SET status = :status,
               approved_by_user = :approved_by_user,
               approved_at = :approved_at,
               approval_reason = :approval_reason
           WHERE id = :id"""
    )
    await session.execute(
        stmt,
        {
            "id": plan_id,
            "status": new_status,
            "approved_by_user": approved_by,
            "approved_at": datetime.now() if approved_by else None,
            "approval_reason": reason,
        },
    )

    # Log action
    action = "approved" if new_status == "approved" else "rejected"
    log_stmt = text(
        """INSERT INTO plan_approvals (plan_id, action, actor, reason, timestamp)
           VALUES (:plan_id, :action, :actor, :reason, :timestamp)"""
    )
    await session.execute(
        log_stmt,
        {
            "plan_id": plan_id,
            "action": action,
            "actor": approved_by or "system",
            "reason": reason,
            "timestamp": datetime.now(),
        },
    )

    await session.commit()
    return True
