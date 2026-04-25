# Ads Agent Skill: Campaign Creation and Management

## Purpose

Create, launch, and optimize paid advertising campaigns in Yandex Direct and YouTube Ads
with mandatory human approval gate and automated budget monitoring.

## Input Parameters

- **product_id** (required): Product to advertise (1 = AI Assistant, 2 = AI Trainer, 3 = News Aggregator)
- **platform** (required): `yandex` or `youtube`
- **budget_rub** (required): Total campaign budget in RUB (max 30,000 ₽ per campaign without extra approval)
- **keywords** (required for yandex): List of search keywords (5–50 items)
- **ads** (required): List of ad variants (minimum 2 for A/B testing)
- **start_date** / **end_date** (optional): Campaign period (defaults to 30 days from today)

## Output

- **Campaign draft** saved to `ad_campaigns` table with status `draft`
- **Telegram approval message** with inline buttons (Approve / Edit / Reject)
- **On approval**: campaign created in Yandex Direct API, status updated to `running`
- **A/B test variants** registered in `ad_variants` table

## Integration Points

### Triggering

- **Manual**: Admin requests via Telegram or REST API
- **Automatic**: After Strategist content plan is approved (topics → ad copy sync)
- **A/B evaluation**: Daily 07:00 MSK via APScheduler

### Approval Workflow

1. Draft created → `POST /ads/approval/send` → Telegram message with buttons
2. Admin clicks ✅ → `POST /ads/launch` → Yandex Direct API call → status `running`
3. Admin clicks ❌ → status `rejected`, reason logged
4. Admin clicks ✏️ → status stays `draft`, admin edits and resubmits

### Budget Monitoring

- Hourly check via APScheduler (`_budget_check_task`)
- Daily spend alert threshold: 5,000 ₽
- Monthly limit: 100,000 ₽ → auto-pause all campaigns on breach

## Usage Examples

### Create Campaign Draft

```python
from integrations.yandex_direct.campaigns import CampaignConfig, AdVariant, create_draft

config = CampaignConfig(
    name="AI Ассистент — поиск — май 2026",
    product_id=1,
    budget_rub=15_000,
    keywords=["ai ассистент", "автоматизация бизнеса"],
    ads=[
        AdVariant(
            title1="AI Ассистент для бизнеса",
            title2="Автоматизация за 5 минут",
            text="Бесплатный период 14 дней. Подключение за 1 день.",
            display_url="example.com/ai",
            final_url="https://example.com/ai-assistant",
        ),
        AdVariant(
            title1="Умный AI-помощник",
            title2="Сэкономьте 10 часов в неделю",
            text="Попробуйте бесплатно. Без кредитной карты.",
            display_url="example.com/ai",
            final_url="https://example.com/ai-assistant",
        ),
    ],
    strategy="HIGHEST_POSITION",
    start_date=date(2026, 5, 1),
    end_date=date(2026, 5, 31),
)
campaign_id = await create_draft(session, config)
```

### Send for Approval

```python
from integrations.ads.approval import AdsApprovalManager

manager = AdsApprovalManager()
await manager.send_campaign_approval(
    session=session,
    bot=bot,
    chat_id=settings.telegram_admin_chat_id,
    campaign_id=campaign_id,
)
```

### Check Budget

```python
from integrations.ads.budget_monitor import BudgetMonitor

monitor = BudgetMonitor(settings)
daily = await monitor.check_daily_spend(session, yandex_client)
monthly = await monitor.check_monthly_spend(session, yandex_client)
paused = await monitor.auto_pause_on_limit(session, yandex_client)
```

## Data Dependencies

- **ad_campaigns**: campaign records with status lifecycle
- **ad_variants**: A/B test variants with click/impression/CTR stats
- **ad_approvals**: audit log of all approval events
- **ad_daily_spend**: daily spend aggregated per campaign

## Constraints

- Minimum 2 ad variants per campaign (for A/B testing)
- A/B test evaluation after 7 days and at least 100 impressions per variant
- Monthly budget cap: 100,000 ₽ (configurable via `MONTHLY_ADS_BUDGET_LIMIT_RUB`)
- All campaigns require human approval before launch — no exceptions

## Error Handling

- Yandex Direct API error: log, retry up to 3 times, then alert admin via Telegram
- Budget exceeded: auto-pause all running campaigns, send Telegram notification
- Missing product data: refuse to create campaign, request data update first
