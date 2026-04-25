# Analytics Agent — Skills

## 1. Collect Telegram Post Metrics

```python
from integrations.analytics.collector import TelegramMetricsCollector

collector = TelegramMetricsCollector(settings)

# Single post
record = await collector.collect_post_metrics(
    session,
    post_id=42,
    telegram_message_id=999,
    product_id=1,
    date_collected=date.today(),
)
# record.views  → int (subscriber count proxy)
# record.source → "telegram"

# All posts published in last 3 days
records = await collector.collect_all_recent(session, days=3)
```

**Example output (MetricsRecord):**
```python
MetricsRecord(
    source="telegram",
    product_id=1,
    date=date(2026, 4, 25),
    post_id=42,
    views=14_300,
    forwards=87,
    reactions=210,
    impressions=14_300,
    clicks=0,
    spend_rub=0.0,
    conversions=0,
    ctr=0.0,
)
```

---

## 2. Collect Yandex Direct Metrics

```python
from integrations.analytics.collector import YandexDirectMetricsCollector

collector = YandexDirectMetricsCollector(settings)
records = await collector.collect(
    session,
    campaign_id=7,
    product_id=1,
    date_from=date(2026, 4, 18),
    date_to=date(2026, 4, 24),
)
```

**Example output:**
```python
MetricsRecord(
    source="yandex_direct",
    product_id=1,
    campaign_id=7,
    date=date(2026, 4, 24),
    impressions=18_500,
    clicks=420,
    spend_rub=3_150.0,
    ctr=2.27,
    conversions=28,
)
```

---

## 3. Run Analytics Engine Queries

```python
from integrations.analytics.engine import AnalyticsEngine

engine = AnalyticsEngine(session)

# Top posts by views (last 7 days)
posts = await engine.top_performing_posts(period_days=7)
# → [{"post_id": 42, "topic": "...", "views": 14300, "forwards": 87, ...}, ...]

# Cost per lead for product
cpl = await engine.cost_per_lead(product_id=1)
# → {"product_id": 1, "total_spend_rub": 9450.0, "total_conversions": 84, "cost_per_lead_rub": 112.5}

# Channel effectiveness
channels = await engine.channel_effectiveness()
# → {"telegram": {"post_count": 21, "total_views": 98000, "engagement_rate_pct": 1.87}, ...}

# Trend analysis (clicks, 30 days)
trend = await engine.trend_analysis("clicks", days=30)
# → {"dates": ["2026-03-26", ...], "values": [300, 320, ...], "trend": [295.0, 310.0, ...]}
```

---

## 4. Generate Morning Digest

```python
from integrations.analytics.digest import MorningDigest

digest = MorningDigest()
text = await digest.generate(session, engine, settings)
await bot.send_message(
    chat_id=settings.telegram_admin_chat_id,
    text=text,
    parse_mode="Markdown",
)
```

**Example output:**
```
📊 *Утренний дайджест — 25.04.2026*

| Продукт | Показы | Клики | CTR | Расход |
|---------|--------|-------|-----|--------|
| Alpha | 18,500 | 420 | 2.27% | 3,150₽ |
| Beta | 9,200 | 185 | 2.01% | 1,480₽ |

🏆 *Топ-пост:* Как мы увеличили конверсию на 40%
👁 14,300 просмотров · ↗️ 87 репостов

💰 *Расход за день:* 4,630₽ | Лимит: 100,000₽/мес
```

---

## 5. Generate Weekly Report

```python
from integrations.analytics.digest import WeeklyReport

report = WeeklyReport()
text, chart_path = await report.generate(session, engine, settings)
# chart_path: Path to PNG, or None if matplotlib failed
await report.send(bot, settings.telegram_admin_chat_id, text, chart_path)
```

**Example text output:**
```
📈 *Еженедельный отчёт* | 18.04 – 25.04.2026

| Метрика | Тек. неделя | Пред. неделя | Δ |
|---------|------------|-------------|---|
| Показы | 129,500.0 | 118,200.0 | +11,300.0 |
| Клики | 2,940.0 | 2,650.0 | +290.0 |
| CTR (%) | 2.3 | 2.2 | +0.1 |
| Расход (₽) | 32,410.0 | 29,800.0 | +2,610.0 |

💡 *Рекомендация:* Клики растут — увеличьте бюджет на топовые кампании.
```

---

## 6. Run Anomaly Detection

```python
from integrations.analytics.digest import AnomalyDetector

detector = AnomalyDetector()
anomalies = await detector.check(session, engine, settings)
if anomalies:
    await detector.alert(bot, settings.telegram_admin_chat_id, anomalies)
```

**Example alert output:**
```
🚨 *Обнаружены аномалии*

⚠️ *CTR упал на 62.4%* для *Alpha*
Сегодня: 0.86% | Средн. 7д: 2.29%
🔧 Рекомендация: проверьте объявления и таргетинг.

💸 *Превышен дневной бюджет!*
Расход: 7,840₽ | Порог: 5,000₽
🔧 Рекомендация: проверьте ставки и лимиты кампаний.
```

---

## Anomaly skip conditions

| Condition | Result |
|-----------|--------|
| 7-day avg CTR is `None` | Skip CTR check (no history) |
| 7-day avg CTR is `0` | Skip CTR check (no impressions) |
| Daily `spend_rub` is `None` | Skip spend check |
