# Content Agent — Skills Reference

## Overview

Four components work together in a pipeline:

```
ContentPlan (approved)
      │
      ▼
CalendarManager.generate_week_schedule()   ← allocates time slots
      │  list[ScheduledPost] (body="", status=pending)
      ▼
ContentGenerator.generate_post()           ← fills body via Claude API
      │  Post.body
      ▼
CalendarManager.update_post_body()         ← persists body, status→generated
      │
      ▼
publisher.publish_post()                   ← sends to Telegram channel
      │  (success, message_id)
      ▼
CalendarManager.mark_published()           ← records published_at, msg_id
```

---

## Skill 1 — generate_week_schedule

**Module:** `integrations/content/calendar.py`
**Class:** `CalendarManager`

```python
from integrations.content.calendar import CalendarManager
from integrations.strategist.models import ContentPlan

cal = CalendarManager()
posts = cal.generate_week_schedule(content_plan)
# Returns list[ScheduledPost] with body="" and status="pending"
# Slots: Mon–Sun at 09:00, 12:00, 18:00 MSK
# Channel mapping: telegram→telegram, blog→vc.ru, habr→habr, linkedin→linkedin
# youtube topics are skipped (not yet supported)
```

**Persist to DB:**
```python
async with session:
    for post in posts:
        post_id = await cal.save_scheduled_post(session, post, content_plan_id=plan_db_id)
```

---

## Skill 2 — generate_post

**Module:** `integrations/content/generator.py`
**Class:** `ContentGenerator`

```python
from integrations.content.generator import ContentGenerator
from app.config import settings

gen = ContentGenerator(settings)

post = await gen.generate_post(
    product_id=1,
    product_name="OpenClaw",
    product_description="Self-hosted AI platform",
    platform="telegram",          # "telegram" | "habr" | "vc.ru" | "linkedin"
    topic="Как мы сократили time-to-deploy на 40%",
)
# post.body — ready text for the platform
# Rate limiting: 1 req / 2 s (token bucket, burst=2)
```

**Fill body for a scheduled post:**
```python
await cal.update_post_body(session, post_id=42, body=post.body)
# status automatically advances to "generated"
```

---

## Skill 3 — publish_post (Telegram)

**Module:** `integrations/telegram/publisher.py`

```python
from telegram import Bot
from integrations.telegram.publisher import publish_post, notify_publish_error
from app.config import settings

bot = Bot(token=settings.telegram_bot_token)
success, message_id = await publish_post(bot, settings.telegram_channel_id, scheduled_post)

if success:
    await cal.mark_published(session, post.id, published_at=datetime.now(UTC), telegram_message_id=message_id)
else:
    await cal.mark_failed(session, post.id)
    await notify_publish_error(bot, int(settings.telegram_admin_chat_id), scheduled_post)
```

**Retry policy:** 3 attempts, exponential backoff 1 s → 2 s → 4 s.
4xx Telegram errors (bad token, chat not found) are **not** retried.

---

## Skill 4 — generate_habr_draft

**Module:** `integrations/content/habr_draft.py`
**Class:** `HabrGenerator`

```python
from integrations.content.habr_draft import HabrGenerator

gen = HabrGenerator(settings)

draft = await gen.generate_habr_draft(
    product_id=1,
    product_name="OpenClaw",
    product_description="Self-hosted AI platform",
    brief="Как self-hosted LLM-платформа помогает командам не терять данные",
)
# draft.body  — Markdown article 2000–4000 words
# draft.title — extracted from first heading or synthesised
# draft.word_count — integer

draft_id = await gen.save_draft(session, draft)   # persists to habr_drafts table
markdown  = await gen.export_draft(session, draft_id)  # marks exported, returns body
```

**Article structure** (enforced in prompt):
1. Введение (200–300 сл.)
2. Проблема (400–600 сл.)
3. Решение (600–900 сл.)
4. Примеры кода (400–600 сл.)
5. Результаты / кейс (300–400 сл.)
6. Вывод + CTA (150–200 сл.)

---

## Skill 5 — n8n HTTP API

All four steps above are exposed as REST endpoints under `/api/v1/content/`
and are called by the n8n `content-pipeline` workflow.

| Method | Endpoint                            | n8n Node         | Description                      |
|--------|-------------------------------------|------------------|----------------------------------|
| GET    | `/api/v1/content/pending`           | Node 1 – Check   | Pending posts for today (MSK)    |
| POST   | `/api/v1/content/{id}/generate`     | Node 2 – Generate| Fill body via Claude API         |
| POST   | `/api/v1/content/{id}/publish`      | Node 3 – Publish | Send to Telegram channel         |
| POST   | `/api/v1/content/{id}/metrics`      | Node 4 – Metrics | Save metrics (Sprint 3 stub)     |
| POST   | `/api/v1/content/habr-draft`        | –                | Create Habr article on demand    |
| GET    | `/api/v1/content/habr-draft/{id}/export` | –           | Export draft as Markdown         |

---

## Environment Variables

```dotenv
ANTHROPIC_API_KEY=sk-ant-...          # Claude API
TELEGRAM_BOT_TOKEN=123:ABC...         # Bot token
TELEGRAM_ADMIN_CHAT_ID=123456789      # Admin alert destination
TELEGRAM_CHANNEL_ID=@mychannel        # Publication channel (Sprint 2)
```

---

## DB Tables (Sprint 2)

| Table             | Key columns                                              |
|-------------------|----------------------------------------------------------|
| `scheduled_posts` | id, content_plan_id, product_id, platform, topic, body, scheduled_at, status |
| `habr_drafts`     | id, product_id, title, brief, body, word_count, status   |

**scheduled_posts.status lifecycle:** `pending` → `generated` → `published` (or `failed`)
**habr_drafts.status lifecycle:** `draft` → `ready` → `exported`
