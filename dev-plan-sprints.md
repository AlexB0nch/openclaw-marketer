# AI Marketing Team — План разработки (спринты для Claude Code)

## Контекст проекта

**Стек:** Python, OpenClaw (self-hosted), n8n, PostgreSQL, Telegram Bot API, Yandex Direct API, GitHub Actions  
**Репо:** `ai-marketing-team` на GitHub  
**Деплой:** VPS (Vultr/Hetzner) через GitHub Actions → Docker Compose  
**Разработка:** Claude Code (локально + agent teams для параллельных задач)

---

## Принципы работы с Claude Code

- Каждый спринт — отдельная ветка `sprint-N/feature-name`
- В корне репо лежит `CLAUDE.md` — правила CI/CD, структура проекта, соглашения по коду
- Для параллельной разработки используй **Agent Teams**: lead → teammates по модулям
- Каждый агент имеет свой `SOUL.md` + папку `skills/` — Claude Code пишет их первым делом
- После каждого спринта: PR → CI (pytest + lint) → merge → auto-deploy

---

## CLAUDE.md (создать в Sprint 0)

```markdown
# AI Marketing Team — Claude Code Rules

## Branch Strategy
- Direct push to main is prohibited. Always use PRs.
- Branch flow: sprint-N/feature → develop → main
- All PRs require CI to pass

## Code Standards
- Python 3.11+, black formatter, ruff linter
- Type hints everywhere
- Async-first: asyncio + aiohttp for all external API calls
- Environment variables via python-dotenv, never hardcode secrets

## Testing
- pytest, minimum 70% coverage for integrations/
- Mock all external API calls in tests

## Deploy
- Docker Compose for all services
- Health check endpoint: GET /health → 200
- Rollback: auto-revert on deploy failure
- Notify Telegram on deploy success/failure

## Secret Management
- All API keys in GitHub Secrets + .env (gitignored)
- .env.example always up to date

## Agent Architecture
- Each agent: agents/{name}/SOUL.md + skills/ directory
- n8n workflows exported to n8n-workflows/*.json
- DB migrations in db/migrations/ (Alembic)
```

---

## Sprint 0 — Фундамент (3–4 дня)

**Цель:** Рабочая инфраструктура, репо, базовый OpenClaw + n8n на VPS.

### Задачи для Claude Code

```
Task 1: Project scaffold
- Создай структуру репозитория ai-marketing-team согласно схеме
- Сгенерируй CLAUDE.md с правилами CI/CD
- Создай docker-compose.yml: n8n + PostgreSQL + adminer
- Создай .env.example со всеми нужными переменными
- Добавь .gitignore, Makefile (make up, make down, make test, make deploy)

Task 2: GitHub Actions CI pipeline
- .github/workflows/ci.yml: lint (ruff), format check (black), pytest
- .github/workflows/deploy.yml: SSH на VPS, docker-compose pull & up
- Настрой secrets: VPS_HOST, VPS_USER, VPS_KEY, TELEGRAM_BOT_TOKEN

Task 3: Base database schema
- db/migrations/001_initial.sql: таблицы products, campaigns, content_items,
  tg_channels, metrics, events_calendar
- Alembic setup для будущих миграций
- Скрипт seed с тремя продуктами

Task 4: OpenClaw base config
- agents/base/SOUL.md: базовый шаблон для всех агентов
- openclaw.json: подключение Claude API, Telegram Bot, memory settings
- Makefile target: make openclaw-install
```

**Результат спринта:** `docker-compose up` поднимает n8n + DB, CI зелёный, OpenClaw отвечает в Telegram.

---

## Sprint 1 — Стратег (4–5 дней)

**Цель:** Главный координирующий агент работает в OpenClaw, принимает команды через Telegram.

### Задачи для Claude Code

```
Task 1: Strategist SOUL.md
- agents/strategist/SOUL.md с полным system prompt:
  * Описания трёх продуктов (ИИ-помощник, тренер, агрегатор)
  * Матрица ЦА по каждому продукту
  * Tone of voice для каждого
  * Инструкции по координации подчинённых агентов
  * Список доступных команд через Telegram

Task 2: Weekly planning engine
- integrations/strategist/planner.py
- Функция generate_weekly_plan(products, metrics_last_week) → ContentPlan
- ContentPlan: Pydantic model с полями по каждому агенту
- Сохранение плана в PostgreSQL
- Тесты с моком метрик

Task 3: Telegram command handler
- integrations/telegram/commands.py
- Команды: /status, /plan, /report, /approve <id>, /reject <id>
- Inline keyboard для апрувов
- Сохранение очереди апрувов в DB

Task 4: Weekly digest sender
- Cron task (APScheduler): каждое воскресенье в 19:00 MSK
- Формат дайджеста: markdown таблица по продуктам, метрики недели, план на след. неделю
- n8n workflow: strategist-weekly-digest.json

Task 5: OpenClaw skill for Strategist
- agents/strategist/skills/SKILL.md
- Инструкции агенту как использовать planner и command handler
```

**Промпт для Claude Code Agent Teams:**
```
Create an agent team to build Sprint 1.
Spawn 2 teammates:
- backend-dev: implement planner.py and database models, write tests
- telegram-dev: implement command handler with inline keyboards
Require plan approval before implementation. Backend-dev finishes first,
telegram-dev can then integrate with planner output.
```

**Результат спринта:** Пишешь `/plan` в Telegram → агент генерирует план на неделю и присылает тебе.

---

## Sprint 2 — Контент-агент (5–6 дней)

**Цель:** Автоматическая генерация и публикация контента в Telegram-каналы.

### Задачи для Claude Code

```
Task 1: Content generation engine
- integrations/content/generator.py
- ContentGenerator класс: generate_post(product, platform, topic) → Post
- Поддержка платформ: telegram, habr, vc_ru, linkedin
- Tone of voice per product (загружается из SOUL.md продукта)
- Async вызовы к Claude API через anthropic SDK
- Rate limiting (token bucket)

Task 2: Editorial calendar
- integrations/content/calendar.py
- CalendarManager: generate_week(products, plan) → List[ScheduledPost]
- CRUD для ScheduledPost в PostgreSQL
- Учёт оптимального времени публикации (TG: 9:00, 12:00, 18:00 MSK)

Task 3: Telegram publisher
- integrations/telegram/publisher.py
- Async publish: текст + опциональное изображение
- Retry logic (3 попытки с backoff)
- Логирование в DB: post_id, views, timestamp

Task 4: n8n workflow — content pipeline
- n8n-workflows/content-pipeline.json
- Trigger: cron каждые 3 часа
- Nodes: check_calendar → generate_if_needed → publish → save_metrics
- Error notification → Telegram

Task 5: Habr draft creator
- integrations/content/habr_draft.py
- Генерация long-form статьи (2000–4000 слов) по brief
- Структура: intro, problem, solution (продукт), code examples если нужно, CTA
- Сохранение черновика в DB, отправка тебе ссылки для ревью

Task 6: Content Agent SOUL.md
- agents/content/SOUL.md
- Инструкции по стилю каждого продукта
- Примеры хороших постов (few-shot примеры прямо в SOUL.md)
```

**Промпт для Claude Code:**
```
Implement Sprint 2 content agent.
Use agent team with 3 teammates:
- content-engine: ContentGenerator + CalendarManager with full tests
- publisher: Telegram publisher + retry logic + DB logging
- n8n-specialist: create content-pipeline.json workflow, document nodes
All teammates work in parallel. Lead synthesizes and ensures interfaces match.
```

**Результат спринта:** Контент-агент сам публикует посты по расписанию в три продуктовых канала.

---

## Sprint 3 — Аналитик (4–5 дней)

**Цель:** Сбор метрик, утренний дайджест, аналитические отчёты.

### Задачи для Claude Code

```
Task 1: Metrics collector
- integrations/analytics/collector.py
- TelegramMetricsCollector: views, forwards, reactions per post (Bot API)
- YandexDirectMetricsCollector: clicks, cost, CTR (tapi-yandex-direct)
- GoogleAnalyticsCollector: sessions, conversions (GA4 API)
- Unified MetricsRecord Pydantic model
- Все коллекторы async, сохраняют в PostgreSQL

Task 2: Analytics engine
- integrations/analytics/engine.py
- Функции: top_performing_posts(period), cost_per_lead(product), 
  channel_effectiveness(), trend_analysis(metric, days)
- Pandas для агрегаций, экспорт в dict для Telegram-сообщений

Task 3: Morning digest
- Cron: каждый день в 8:30 MSK
- Содержание: метрики за вчера по каждому продукту, топ-пост, алерты
- Форматирование: emoji + markdown таблицы в Telegram

Task 4: Weekly report
- Воскресенье 19:00 MSK
- PDF или изображение с графиками (matplotlib/plotly)
- Сравнение с прошлой неделей, ROI по каналам, рекомендации

Task 5: Anomaly detection
- Алерт если CTR упал > 30% или расход рекламного бюджета вырос > 50%
- Немедленный push в Telegram с описанием аномалии

Task 6: Analytics Agent SOUL.md + n8n workflow
- agents/analytics/SOUL.md
- n8n-workflows/analytics-report.json
```

**Результат спринта:** Каждое утро в 8:30 получаешь в Telegram дайджест по всем продуктам.

---

## Sprint 4 — Рекламный агент (6–7 дней)

**Цель:** Автоматизация Яндекс Директ и YouTube Ads с апрувом перед запуском.

### Задачи для Claude Code

```
Task 1: Yandex Direct client
- integrations/yandex_direct/client.py
- Обёртка над tapi-yandex-direct
- Методы: list_campaigns(), create_campaign(config), update_keywords(),
  pause_campaign(), get_report(date_range, fields)
- Полная async поддержка через asyncio.to_thread
- Тесты с mock API

Task 2: Campaign factory
- integrations/yandex_direct/campaigns.py
- CampaignConfig Pydantic model (название, бюджет, ключевые слова, объявления)
- generate_campaign_config(product, goal, budget) → CampaignConfig
  * product = "ai_assistant" | "ai_trainer" | "ai_news"
  * Автоматический подбор ключевых слов через Яндекс Wordstat API
- create_and_submit_for_approval(config) → Draft сохраняется в DB

Task 3: A/B test manager
- integrations/yandex_direct/ab_test.py
- Создаёт 2-3 варианта объявления с разными заголовками
- Через 7 дней: compare_variants() → winner
- Auto-pause losing variants, scale winner

Task 4: YouTube Ads client
- integrations/google_ads/youtube_client.py
- Google Ads API (google-ads-python library)
- Методы: create_video_campaign(), get_video_metrics(), update_bid()
- Brief generator: generate_video_brief(product) → VideoCreativeBrief
  * Выводит brief тебе в Telegram для создания видео

Task 5: Approval workflow
- integrations/ads/approval.py
- Когда кампания готова: send_approval_request(campaign_draft) → Telegram
- Inline кнопки: ✅ Запустить / ✏️ Редактировать / ❌ Отклонить
- Если апрув: автоматический запуск через API
- Лог всех апрувов в DB

Task 6: Budget monitor
- Алерт если суточный расход > threshold (задаётся в .env)
- Auto-pause кампании при исчерпании месячного бюджета
- Ежедневный расход → в утренний дайджест аналитика

Task 7: Ads Agent SOUL.md
- agents/ads/SOUL.md
- n8n-workflows/ads-automation.json
```

**Промпт для Claude Code Agent Teams:**
```
Implement Sprint 4 Ads Agent.
Agent team with 3 teammates:
- yandex-dev: Tasks 1-3 (Yandex Direct + A/B testing), full unit tests with mocks
- youtube-dev: Task 4 (YouTube Ads client + brief generator)
- workflow-dev: Tasks 5-6 (approval workflow + budget monitor)
All teammates work in parallel. Lead ensures approval workflow
integrates with both yandex-dev and youtube-dev output.
Require plan approval before any implementation that touches external APIs.
```

**Результат спринта:** Агент готовит кампанию в Директ, присылает тебе на апрув, после клика «Запустить» — всё происходит автоматически.

---

## Sprint 5 — TG Scout (5–6 дней)

**Цель:** Поиск Telegram-каналов, анализ аудитории, подготовка питчей.

### Задачи для Claude Code

```
Task 1: Telegram channel parser
- integrations/telegram/scout.py
- Telethon client (user session, не бот) для поиска каналов
- search_channels(keywords, min_subscribers, min_er) → List[ChannelInfo]
- ChannelInfo: username, title, subscriber_count, avg_views, er, topics, contact
- Парсинг описания канала для извлечения email/username для связи
- Сохранение в таблицу tg_channels с полем status (new/pitched/partner)

Task 2: TGStat API integration
- integrations/telegram/tgstat_client.py
- Получение дополнительных метрик: ER, рост аудитории, категория
- Дедупликация с результатами Telethon

Task 3: Relevance scorer
- integrations/telegram/scorer.py
- score_channel(channel, product) → RelevanceScore (0-100)
- Критерии: тематика, размер аудитории, ER, пересечение с ЦА продукта
- Claude API для семантического анализа описания канала

Task 4: Pitch generator
- integrations/telegram/pitch.py
- generate_pitch(channel, product) → PitchDraft
- Персонализация под тематику канала
- Три варианта: короткий (DM), средний (email), развёрнутый
- Сохранение черновика в DB со статусом pending_approval

Task 5: Approval & send workflow
- integrations/telegram/outreach.py
- Еженедельная подборка: топ-10 каналов по score → Telegram тебе
- Inline кнопки: ✅ Отправить питч / 👀 Показать питч / ❌ Пропустить
- После апрува: логирование, смена статуса канала

Task 6: Mention monitor
- integrations/telegram/monitor.py
- Telethon: подписка на ключевые слова в публичных каналах/группах
- Алерт когда упоминается продукт или релевантный вопрос
- "Ответить в обсуждении" — возможность быстрого ответа через Telegram бот

Task 7: TG Scout SOUL.md + n8n workflow
- agents/tg-scout/SOUL.md
- n8n-workflows/tg-scout-pipeline.json
```

**Важно:** Telethon работает от имени обычного аккаунта (не бота) — нужна активная сессия. Хранить session файл в защищённом месте на VPS, никогда в git.

**Результат спринта:** Каждую неделю получаешь в Telegram подборку из 10 каналов с готовыми питчами. Одна кнопка — и питч отправлен.

---

## Sprint 6 — Events Agent (3–4 дня)

**Цель:** Автоматический мониторинг конференций и возможностей для выступлений.

### Задачи для Claude Code

```
Task 1: Conference scraper
- integrations/events/scraper.py
- Async web scraper (aiohttp + BeautifulSoup)
- Источники: aiconf.ru, productsense.io, ritfest.ru, tadviser.ru, 
  it-conf.ru, habr.com/conferences, ppc.world/events
- Парсинг: название, дата, дедлайн CFP, город/онлайн, размер аудитории, ссылка
- Сохранение в таблицу events_calendar

Task 2: Relevance filter
- integrations/events/filter.py
- filter_relevant(events, products) → List[RelevantEvent]
- Claude API для оценки релевантности (тема, аудитория, продукт)
- Исключение уже прошедших и дубликатов

Task 3: CFP deadline tracker
- integrations/events/tracker.py
- Алерт за 14 и 3 дня до дедлайна подачи заявки
- Генерация abstract-черновика для выступления на основе продукта

Task 4: Monthly digest
- Cron: 1-е число каждого месяца, 10:00 MSK
- Форматированная таблица в Telegram: конф, дата, дедлайн, ссылка
- Выделение конференций с дедлайном в течение 30 дней

Task 5: Events Agent SOUL.md
```

**Результат спринта:** 1-го числа каждого месяца — список конференций с дедлайнами. За 3 дня до дедлайна — напоминание с черновиком заявки.

---

## Sprint 7 — Интеграция и полировка (4–5 дней)

**Цель:** Все агенты работают как единая система. End-to-end тесты. Мониторинг.

### Задачи для Claude Code

```
Task 1: Integration tests
- tests/integration/ — полные e2e тесты основных воронок
- Тест воронки: plan → content_generate → publish → metrics_collect
- Тест воронки: campaign_create → approval_request → approve → launch
- Используй pytest + respx для мокирования HTTP

Task 2: Unified dashboard (Telegram)
- /dashboard команда: статус всех агентов, метрики за сегодня, очередь апрувов
- Форматированный вывод с emoji статусами (🟢 работает / 🔴 ошибка)

Task 3: Error handling & alerting
- Global exception handler для всех агентов
- Ошибка → Telegram алерт с traceback (только тебе)
- Retry logic для временных ошибок (429, 500, network)
- Dead letter queue в PostgreSQL для упавших задач

Task 4: Performance optimisation
- Профилирование узких мест (cProfile + py-spy)
- Connection pooling для PostgreSQL (asyncpg)
- Кэширование часто запрашиваемых данных (Redis или in-memory)

Task 5: Documentation
- README.md: quick start, архитектура, переменные окружения
- AGENTS.md: описание каждого агента, команды Telegram, flow апрувов
- Runbook: как перезапустить агента, как добавить новый продукт

Task 6: Production hardening
- Health check endpoints для всех сервисов
- Uptime monitoring (простой ping через n8n)
- Автоматический backup PostgreSQL на S3 каждую ночь
```

**Промпт для финального ревью через Claude Code:**
```
Create an agent team to do a final review of the ai-marketing-team project.
Spawn 3 reviewers:
- security-reviewer: check for hardcoded secrets, SQL injections, exposed tokens
- performance-reviewer: identify slow queries, missing indexes, sync calls in async context
- test-coverage-reviewer: find untested edge cases, missing integration tests
Each reviewer reports findings. Lead synthesizes and creates a prioritized fix list.
```

---

## Сводный таймлайн

| Спринт | Что строим | Длительность | Ключевой результат |
|---|---|---|---|
| 0 | Инфраструктура | 3–4 дня | docker-compose up работает |
| 1 | Стратег | 4–5 дней | `/plan` в Telegram → план на неделю |
| 2 | Контент-агент | 5–6 дней | Автопостинг в TG-каналы |
| 3 | Аналитик | 4–5 дней | Утренний дайджест в 8:30 |
| 4 | Рекламный агент | 6–7 дней | Директ + YouTube с апрувом |
| 5 | TG Scout | 5–6 дней | Еженедельные питчи каналам |
| 6 | Events Agent | 3–4 дня | Конференции и CFP дедлайны |
| 7 | Интеграция | 4–5 дней | Production-ready система |
| **Итого** | | **~5–7 недель** | Полная AI-команда маркетологов |

---

## Переменные окружения (.env.example)

```env
# Claude / OpenAI
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_ID=
TELEGRAM_PRODUCT1_CHANNEL_ID=   # ИИ-помощник по переписке
TELEGRAM_PRODUCT2_CHANNEL_ID=   # ИИ-тренер
TELEGRAM_PRODUCT3_CHANNEL_ID=   # ИИ-агрегатор новостей
TELETHON_API_ID=
TELETHON_API_HASH=

# Yandex Direct
YANDEX_DIRECT_TOKEN=
YANDEX_DIRECT_LOGIN=

# Google Ads / YouTube
GOOGLE_ADS_DEVELOPER_TOKEN=
GOOGLE_ADS_CLIENT_ID=
GOOGLE_ADS_CLIENT_SECRET=
GOOGLE_ADS_REFRESH_TOKEN=
GOOGLE_ADS_CUSTOMER_ID=

# TGStat
TGSTAT_API_KEY=

# Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=ai_marketing
POSTGRES_USER=
POSTGRES_PASSWORD=

# n8n
N8N_WEBHOOK_URL=
N8N_API_KEY=

# OpenClaw
OPENCLAW_PORT=3000

# Alerts
MONTHLY_ADS_BUDGET_LIMIT_RUB=
DAILY_SPEND_ALERT_THRESHOLD_RUB=
```

---

## Команды Telegram-бота (итоговый список)

| Команда | Агент | Описание |
|---|---|---|
| `/status` | Стратег | Статус всех агентов + метрики дня |
| `/plan` | Стратег | Сгенерировать план на текущую неделю |
| `/report` | Аналитик | Отчёт за последние 7 дней |
| `/dashboard` | Все | Сводный дашборд |
| `/pending` | Стратег | Список ожидающих апрувов |
| `/campaigns` | Ads | Список активных кампаний + метрики |
| `/channels` | TG Scout | Топ-10 найденных каналов этой недели |
| `/events` | Events | Ближайшие конференции |
| `/pause <product>` | Ads | Поставить на паузу рекламу продукта |
| `/publish <post_id>` | Контент | Немедленно опубликовать пост |
