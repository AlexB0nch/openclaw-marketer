# Agents Reference

Полная документация по агентам AI Marketing Team. Один раздел на агента.

## Strategist (Стратег)

- **Роль:** генерирует еженедельный контент-план, отправляет на одобрение,
  ведёт аудит планов.
- **Telegram-команды:** `/plan`, `/status`, `/approve <id>`, `/reject <id> [причина]`, `/report`
- **Cron jobs (Europe/Moscow):**
  - `weekly_plan` — Вс 19:00 — генерация плана
  - `weekly_digest` — Вс 19:05 — отправка дайджеста
  - `daily_backup` — 03:00 — pg_dump → S3 (Sprint 7)
- **Approval flow:** план в Telegram → кнопки `approve_<id>` / `reject_<id>` → статус
  обновляется в `content_plans`.

## Content (Контент-агент)

- **Роль:** разбивает план на слоты редкалендаря, генерирует тексты, публикует
  в Telegram, готовит черновики Habr.
- **API:**
  - `GET /api/v1/content/pending`
  - `POST /api/v1/content/{id}/generate`
  - `POST /api/v1/content/{id}/publish`
  - `POST /api/v1/content/habr-draft`
  - `GET  /api/v1/content/habr-draft/{id}/export`
- **Cron:** оркестрируется n8n (3 раза в день), без локального APScheduler.
- **Платформы:** `telegram`, `habr`, `vc.ru`, `linkedin`.

## Analytics (Аналитика)

- **Роль:** сбор метрик, ежедневный/еженедельный дайджест, поиск аномалий.
- **Cron jobs (Europe/Moscow):**
  - `analytics_morning_digest` — 08:30 ежедневно
  - `analytics_weekly_report` — Вс 19:00
  - `analytics_anomaly_check` — каждый час
- **API:** `/api/v1/analytics/{collect,engine/snapshot,anomalies,digest}`

## Ads (Реклама)

- **Роль:** ведение черновиков, человеко-апрув, запуск через Yandex Direct,
  A/B-тесты, автопауза.
- **Telegram callbacks:** `ads_approve:<id>`, `ads_edit:<id>`, `ads_reject:<id>`
- **Cron jobs (Europe/Moscow):**
  - `ads_ab_test_check` — 07:00 ежедневно
  - `ads_budget_check` — каждый час
  - `ads_weekly_report` — Пн 08:00
- **Approval flow:** Telegram → `AdsApprovalManager.handle_approval_callback()` →
  Yandex Direct API → `ad_campaigns.status='running'`.

## TG Scout

- **Роль:** еженедельный поиск релевантных Telegram-каналов, скоринг 0–100,
  генерация питчей, мониторинг упоминаний.
- **API:** `/api/v1/scout/{search,enrich,score,pitches/generate,digest/send}`,
  `/api/v1/scout/channels`
- **Cron jobs (Europe/Moscow):**
  - `scout_weekly_search` — Пн 09:00
  - `scout_mention_monitor` — фоновая корутина (всегда)

## Events (Conference Scout)

- **Роль:** ежемесячный сбор tech-конференций, фильтрация релевантности,
  CFP-дедлайны, черновики заявок спикеров.
- **Telegram callbacks:** `events_draft:<id>`, `events_skip:<id>`, `events_apply:<id>`, `events_reject:<id>`
- **Cron jobs (Europe/Moscow):**
  - `events_monthly_scrape` — 1-е число 10:00
  - `events_monthly_digest` — 1-е число 10:30
  - `events_deadline_check` — 09:00 ежедневно
- **API:** `/api/v1/events/{scrape,filter,calendar,digest/send,abstract/{id}}`

---

## Сводная таблица команд

| Команда | Агент | Описание |
|---|---|---|
| `/status` | Strategist | Статус текущего плана |
| `/plan` | Strategist | Сгенерировать план немедленно |
| `/approve <id>` | Strategist | Одобрить план |
| `/reject <id>` | Strategist | Отклонить план |
| `/report` | Strategist | Еженедельный дайджест |
| `/dashboard` | All | Объединённая панель (Sprint 7) |

## Сводная таблица inline callbacks

| Pattern | Агент |
|---|---|
| `approve_\d+` | Strategist |
| `reject_\d+` | Strategist |
| `ads_approve:\d+` | Ads |
| `ads_edit:\d+` | Ads |
| `ads_reject:\d+` | Ads |
| `events_draft:\d+` | Events |
| `events_skip:\d+` | Events |
| `events_apply:\d+` | Events |
| `events_reject:\d+` | Events |

## Сводная таблица cron jobs (timezone: Europe/Moscow)

| Job ID | Расписание | Агент |
|---|---|---|
| `weekly_plan` | Вс 19:00 | Strategist |
| `weekly_digest` | Вс 19:05 | Strategist |
| `daily_backup` | 03:00 ежедн. | Strategist (Sprint 7) |
| `analytics_morning_digest` | 08:30 ежедн. | Analytics |
| `analytics_weekly_report` | Вс 19:00 | Analytics |
| `analytics_anomaly_check` | каждый час | Analytics |
| `ads_ab_test_check` | 07:00 ежедн. | Ads |
| `ads_budget_check` | каждый час | Ads |
| `ads_weekly_report` | Пн 08:00 | Ads |
| `scout_weekly_search` | Пн 09:00 | TG Scout |
| `events_monthly_scrape` | 1-е 10:00 | Events |
| `events_monthly_digest` | 1-е 10:30 | Events |
| `events_deadline_check` | 09:00 ежедн. | Events |
