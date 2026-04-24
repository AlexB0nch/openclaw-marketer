# Strategist Skill: Weekly Content Planning

## Purpose
Generate weekly content plans based on product metrics, events, and budget constraints for human approval and downstream automation.

## Input Parameters
- **week_start_date** (optional): Start date for plan generation (defaults to next Monday)
- **products** (optional): List of product IDs to include (defaults: all active products)
- **budget_limit_rub** (optional): Override budget limit (defaults: monthly remaining budget)

## Output
- **ContentPlan JSON** with:
  - Topics and channels for each product
  - Budget allocation across products
  - Confidence score (0-100%)
  - Approval status: `pending_approval` (awaiting human review)
  - Markdown summary for Telegram

## Integration Points

### Triggering
- **Automatic:** Every Sunday at 19:00 MSK via APScheduler
- **Manual:** `/plan` Telegram command triggers on-demand generation

### Approval Workflow
- Plan is sent to Telegram admin chat with inline buttons
- Human clicks ✅ or ❌ to approve/reject
- Approved plans automatically cascade to Content Agent (Sprint 2)

### Feedback Loop
- `/report` command shows current plan status
- `/status` command shows metrics and pending approvals
- Rejected plans logged with reason for future reference

## Usage Examples

### Automatic Weekly Generation
```
Sundays 19:00 MSK
↓
Strategist generates plan
↓
Sends to Telegram with approval buttons
↓
Admin approves or rejects
```

### Manual On-Demand Generation
```
Admin sends: /plan
↓
Bot generates plan immediately
↓
Sends to chat with approval buttons
↓
Admin clicks to approve
```

### Check Status
```
Admin sends: /status
↓
Bot shows current plan status + last week metrics
```

### Weekly Report
```
Admin sends: /report
↓
Bot shows metrics, plan status, recommendations
```

## Data Dependencies
- **products** table: active products
- **campaigns** table: recent campaign status
- **metrics** table: impressions, clicks, spend (last 4 weeks)
- **events_calendar** table: upcoming events to plan around

## Constraints
- Minimum 70% confidence to suggest topics
- Cannot generate plan without metrics from past 2 weeks
- Weekly budget <= monthly budget limit (100,000 RUB)
- All plans require human approval before publication

## Error Handling
- Missing metrics: error message + request to wait
- Zero active products: warning message + suggest reviewing products
- Budget exceeded: suggest reducing allocation or extending timeline

## Success Criteria
- Plan generated with >=70% confidence
- All products covered with topic suggestions
- Budget properly allocated
- Sent to Telegram with clear call-to-action buttons
