# AI Marketing Team

Система автономных маркетинговых агентов на базе OpenClaw.  
Telegram-бот — главный интерфейс управления.

**Стек:** Python 3.11 · FastAPI · PostgreSQL · python-telegram-bot · APScheduler · n8n · Docker Compose

---

## Быстрый старт

### Требования

- Docker Desktop (or Docker Engine + Compose)
- Python 3.11+
- Telegram Bot Token (получить у @BotFather)
- Anthropic API Key

### 1. Настройка окружения

```bash
cp .env.example .env
# Заполните значения в .env:
#   TELEGRAM_BOT_TOKEN=...
#   TELEGRAM_ADMIN_CHAT_ID=...
#   ANTHROPIC_API_KEY=...
#   POSTGRES_USER=aimarketing
#   POSTGRES_PASSWORD=<придумайте пароль>
```

### 2. Запуск инфраструктуры

```bash
docker-compose up -d postgres n8n
```

### 3. Применение миграций

```bash
# Sprint 0 — базовая схема
docker exec -i $(docker-compose ps -q postgres) \
  psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < db/migrations/001_initial.sql

# Sprint 1 — таблицы для Стратега
docker exec -i $(docker-compose ps -q postgres) \
  psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < db/migrations/002_sprint1_strategist.sql
```

Или через Makefile:

```bash
make migrate
```

### 4. Запуск приложения

```bash
docker-compose up app
# Health check: curl http://localhost:8000/health
```

---

## Sprint 1 — Стратег (Strategist Agent)

### Что делает Стратег

Каждое воскресенье в 19:00 МСК агент:
1. Анализирует активные продукты и метрики за прошлую неделю
2. Генерирует контент-план с темами и распределением бюджета
3. Отправляет план в Telegram-чат администратора с кнопками одобрения
4. В 19:05 МСК отправляет еженедельный дайджест с метриками

### Telegram-команды

| Команда | Описание |
|---------|----------|
| `/status` | Статус текущего плана + метрики прошлой недели |
| `/plan` | Немедленная генерация нового плана (не ждать воскресенья) |
| `/report` | Еженедельный дайджест: метрики, статус плана, рекомендации |
| `/approve <id>` | Одобрить план `#id` → передаётся в Content-агент |
| `/reject <id> [причина]` | Отклонить план с указанием причины |

Одобрение также доступно через **inline-кнопки** в сообщении с планом:  
`✅ Одобрить` · `❌ Отклонить`

### Тестирование команд вручную

1. Убедитесь, что `TELEGRAM_BOT_TOKEN` и `TELEGRAM_ADMIN_CHAT_ID` заполнены в `.env`
2. Запустите приложение:
   ```bash
   docker-compose up app
   ```
3. Откройте Telegram и отправьте боту:
   ```
   /plan
   ```
   — бот ответит планом с кнопками одобрения.

4. Нажмите **✅ Одобрить** или отправьте:
   ```
   /approve 1
   ```

5. Проверьте статус:
   ```
   /status
   ```

6. Получить дайджест:
   ```
   /report
   ```

### Схема базы данных (Sprint 1)

Добавлены две таблицы в [`db/migrations/002_sprint1_strategist.sql`](db/migrations/002_sprint1_strategist.sql):

**`content_plans`** — хранит сгенерированные планы:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL | Первичный ключ |
| `week_start_date` | DATE UNIQUE | Понедельник целевой недели |
| `week_end_date` | DATE | Воскресенье целевой недели |
| `status` | TEXT | `pending_approval` · `approved` · `rejected` · `archived` |
| `plan_json` | JSONB | Полный план (продукты, темы, бюджеты) |
| `created_by_agent` | TEXT | Всегда `"strategist"` |
| `approved_by_user` | TEXT | Username, одобривший план |
| `approval_reason` | TEXT | Причина одобрения/отклонения |

**`plan_approvals`** — журнал событий одобрения:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL | Первичный ключ |
| `plan_id` | BIGINT FK | → `content_plans.id` |
| `action` | TEXT | `submitted` · `approved` · `rejected` · `edited` |
| `actor` | TEXT | `"strategist"` или username пользователя |
| `reason` | TEXT | Необязательная причина |
| `timestamp` | TIMESTAMPTZ | Время события |

### Расписание задач (APScheduler)

| ID задачи | Расписание | Действие |
|-----------|-----------|----------|
| `weekly_plan` | Вс 19:00 МСК | Генерация плана → отправка в Telegram |
| `weekly_digest` | Вс 19:05 МСК | Дайджест метрик → отправка в Telegram |

### n8n Workflow

Файл: [`n8n-workflows/strategist-weekly-digest.json`](n8n-workflows/strategist-weekly-digest.json)

Импортируйте в n8n (`Settings → Import from file`). Workflow дублирует APScheduler-задачу через webhook и отправляет статус-уведомления в Telegram.

---

## Sprint 2 — Контент-агент (Content Agent)

### Что делает Контент-агент

Получает одобренный план от Стратега и:
1. **Строит редакционный календарь** — разбивает темы на слоты 09:00 / 12:00 / 18:00 МСК по дням недели
2. **Генерирует контент** — вызывает Claude API для каждой темы и платформы
3. **Публикует посты** — отправляет готовые тексты в Telegram-канал с retry-логикой
4. **Создаёт статьи для Habr** — long-form 2000–4000 слов по заданному брифу

### Применение миграции Sprint 2

```bash
docker exec -i $(docker-compose ps -q postgres) \
  psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < db/migrations/003_sprint2_content.sql
```

### Новая переменная окружения

```dotenv
TELEGRAM_CHANNEL_ID=@mychannel   # канал для публикации контента
```

### Локальная генерация контента

```python
import asyncio
from app.config import settings
from integrations.content.generator import ContentGenerator

async def main():
    gen = ContentGenerator(settings)
    post = await gen.generate_post(
        product_id=1,
        product_name="My Product",
        product_description="Short description",
        platform="telegram",
        topic="Как мы ускорили деплой на 40%",
    )
    print(post.body)

asyncio.run(main())
```

Поддерживаемые платформы: `telegram` · `habr` · `vc.ru` · `linkedin`

### Запуск публикации через HTTP API

Эндпоинты доступны после `docker-compose up app`:

```bash
# 1. Посмотреть посты на сегодня
curl "http://localhost:8000/api/v1/content/pending?target_date=2026-04-27"

# 2. Сгенерировать текст для поста #42
curl -X POST "http://localhost:8000/api/v1/content/42/generate" \
  -H "Content-Type: application/json" \
  -d '{"product_description": "Short product desc"}'

# 3. Опубликовать пост #42 в Telegram-канал
curl -X POST "http://localhost:8000/api/v1/content/42/publish"
```

### Использование Habr-черновиков

```bash
# Создать статью
curl -X POST "http://localhost:8000/api/v1/content/habr-draft" \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": 1,
    "product_name": "My Product",
    "product_description": "AI-powered platform",
    "brief": "Как мы сократили time-to-market с 3 месяцев до 2 недель"
  }'

# Экспортировать черновик #5 как Markdown
curl "http://localhost:8000/api/v1/content/habr-draft/5/export"
```

Или из Python:

```python
from integrations.content.habr_draft import HabrGenerator

gen = HabrGenerator(settings)
draft = await gen.generate_habr_draft(
    product_id=1,
    product_name="My Product",
    product_description="...",
    brief="Главный тезис статьи",
)
draft_id = await gen.save_draft(session, draft)
markdown = await gen.export_draft(session, draft_id)
```

### n8n Content Pipeline

Файл: [`n8n-workflows/content-pipeline.json`](n8n-workflows/content-pipeline.json)

Импортируйте в n8n. Workflow срабатывает 3 раза в день и последовательно:

| Шаг | n8n Node | HTTP Endpoint |
|-----|----------|---------------|
| 1 | Check calendar | `GET /api/v1/content/pending` |
| 2 | Generate content | `POST /api/v1/content/{id}/generate` |
| 3 | Publish to Telegram | `POST /api/v1/content/{id}/publish` |
| 4 | Save metrics | `POST /api/v1/content/{id}/metrics` |
| 5 (error) | Alert admin | Telegram Bot API direct |

Переменные n8n: `APP_BASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`.

### Схема базы данных (Sprint 2)

[`db/migrations/003_sprint2_content.sql`](db/migrations/003_sprint2_content.sql) добавляет:

**`scheduled_posts`** — слоты редакционного календаря:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL | Первичный ключ |
| `content_plan_id` | BIGINT FK | → `content_plans.id` |
| `product_id` | BIGINT FK | → `products.id` |
| `platform` | TEXT | `telegram` · `habr` · `vc.ru` · `linkedin` |
| `topic` | TEXT | Тема из ContentPlan |
| `body` | TEXT | Готовый текст (пусто до генерации) |
| `scheduled_at` | TIMESTAMPTZ | Время публикации (МСК слот) |
| `status` | TEXT | `pending` → `generated` → `published` / `failed` |
| `telegram_message_id` | BIGINT | ID сообщения после публикации |

**`habr_drafts`** — черновики статей:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL | Первичный ключ |
| `product_id` | BIGINT FK | → `products.id` |
| `title` | TEXT | Заголовок статьи |
| `brief` | TEXT | Исходный бриф |
| `body` | TEXT | Текст статьи (Markdown) |
| `word_count` | INTEGER | Количество слов |
| `status` | TEXT | `draft` → `ready` → `exported` |

---

## Sprint 3 — Аналитика (Analytics Agent)

### Что делает Аналитик

Ежедневно и еженедельно агент:
1. **Собирает метрики** — Telegram Bot API (просмотры постов), Yandex Direct (клики, CTR, расходы), Google Analytics 4 (сессии, конверсии)
2. **Анализирует данные** — топ-посты, стоимость лида, эффективность каналов, тренды
3. **Отправляет дайджест** — 08:30 МСК ежедневно, с таблицей метрик по продуктам
4. **Еженедельный отчёт** — воскресенье 19:00 МСК, с WoW-сравнением и рекомендациями
5. **Детектирует аномалии** — каждый час: падение CTR >30% или превышение дневного бюджета

### Применение миграции Sprint 3

```bash
docker exec -i $(docker-compose ps -q postgres) \
  psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < db/migrations/004_sprint3_analytics.sql
```

Добавляет: `post_metrics`, `analytics_snapshots`, индексы на `metrics(date)`.

### Новые переменные окружения

```dotenv
# Yandex Direct
YANDEX_DIRECT_TOKEN=        # OAuth-токен Яндекс.Директа
YANDEX_DIRECT_LOGIN=        # Логин рекламного кабинета

# Google Analytics 4 / Google Ads
GOOGLE_ADS_DEVELOPER_TOKEN= # Developer token из Google Ads API Center
GOOGLE_ADS_CLIENT_ID=       # OAuth2 Client ID
GOOGLE_ADS_CLIENT_SECRET=   # OAuth2 Client Secret
GOOGLE_ADS_REFRESH_TOKEN=   # OAuth2 Refresh Token
GOOGLE_ADS_CUSTOMER_ID=     # GA4 Property ID (формат: 123456789)

# Пороги аномалий
DAILY_SPEND_ALERT_THRESHOLD_RUB=5000  # Алерт при превышении дневного расхода
```

Все поля опциональны — приложение стартует без них (коллекторы пропускают работу, если токен пуст).

### Ручной запуск дайджеста

APScheduler запускает дайджест автоматически в 08:30 МСК. Для ручного теста:

```python
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from telegram import Bot
from app.config import settings
from integrations.analytics.digest import MorningDigest
from integrations.analytics.engine import AnalyticsEngine

async def main():
    engine_db = create_async_engine(settings.database_url)
    bot = Bot(token=settings.telegram_bot_token)
    async with AsyncSession(engine_db) as session:
        engine = AnalyticsEngine(session)
        digest = MorningDigest()
        text = await digest.generate(session, engine, settings)
        await bot.send_message(
            chat_id=settings.telegram_admin_chat_id,
            text=text,
            parse_mode="Markdown",
        )

asyncio.run(main())
```

### Настройка порогов аномалий

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `DAILY_SPEND_ALERT_THRESHOLD_RUB` | `5000` | Алерт при дневном расходе > N₽ |

Порог CTR зафиксирован в коде: падение >30% vs 7-дневного скользящего среднего.  
Для изменения — отредактируйте `AnomalyDetector.check()` в [`digest.py`](integrations/analytics/digest.py).

### Расписание задач (Analytics APScheduler)

| ID задачи | Расписание | Действие |
|-----------|-----------|----------|
| `analytics_morning_digest` | Ежедн. 08:30 МСК | Дайджест вчерашних метрик |
| `analytics_weekly_report` | Вс 19:00 МСК | WoW-отчёт + PNG-график |
| `analytics_anomaly_check` | Каждый час | CTR + spend аномалии |

### n8n Workflow

Файл: [`n8n-workflows/analytics-report.json`](n8n-workflows/analytics-report.json)

Импортируйте в n8n. Workflow дублирует APScheduler через HTTP API:

| Шаг | n8n Node | HTTP Endpoint |
|-----|----------|---------------|
| 1 | collect_metrics | `POST /api/v1/analytics/collect` |
| 2 | run_engine | `POST /api/v1/analytics/engine/snapshot` |
| 3 | check_anomalies | `POST /api/v1/analytics/anomalies` |
| 4 | send_digest | `POST /api/v1/analytics/digest` |
| 5 (error) | on_error_alert | Telegram Bot API direct |

### Схема базы данных (Sprint 3)

[`db/migrations/004_sprint3_analytics.sql`](db/migrations/004_sprint3_analytics.sql) добавляет:

**`post_metrics`** — метрики Telegram-постов:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `post_id` | BIGINT FK | → `scheduled_posts.id` |
| `product_id` | BIGINT FK | → `products.id` |
| `date` | DATE | Дата сбора |
| `views` | BIGINT | Просмотры (прокси: подписчики канала) |
| `forwards` | BIGINT | Репосты |
| `reactions` | BIGINT | Реакции |

**`analytics_snapshots`** — ежедневные снимки метрик:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `snapshot_date` | DATE | Дата снимка |
| `product_id` | BIGINT FK | → `products.id` |
| `data` | JSONB | Агрегированные метрики продукта |

---

## Sprint 4 — Рекламный агент (Ads Agent)

### Что делает Рекламный агент

Создаёт, запускает и оптимизирует рекламные кампании в Яндекс.Директ:
1. **Создаёт черновики кампаний** — генерирует ключевые слова и варианты объявлений через Claude API
2. **Отправляет на одобрение** — Telegram-сообщение с кнопками ✅ Запустить / ✏️ Редактировать / ❌ Отклонить
3. **Запускает кампании** — только после явного одобрения человека через Yandex Direct API
4. **A/B-тестирование** — оценивает варианты через 7 дней, останавливает проигравшие
5. **Мониторинг бюджета** — каждый час, авто-пауза при достижении месячного лимита (100 000 ₽)
6. **Еженедельный отчёт** — каждый понедельник 08:00 МСК с метриками и CTR

### Применение миграции Sprint 4

```bash
docker exec -i $(docker-compose ps -q postgres) \
  psql -U $POSTGRES_USER -d $POSTGRES_DB \
  < db/migrations/005_sprint4_ads.sql
```

Добавляет: `ad_campaigns`, `ad_variants`, `ad_approvals`, `ad_daily_spend`.

### Продукты

| ID | Название | Описание |
|----|----------|----------|
| 1 | AI Ассистент | Персональный AI-помощник для бизнеса |
| 2 | AI Тренер | Платформа обучения с AI-наставником |
| 3 | AI Агрегатор новостей | Автоагрегация и суммаризация новостей |

### Workflow одобрения

```
Создание черновика (status=draft)
↓
POST /ads/approval/send → Telegram с кнопками
↓
Ожидание нажатия кнопки (status=pending_approval)
↓
✅ Одобрено → Yandex Direct API → status=running
❌ Отклонено → status=rejected, причина логируется
✏️ Редактировать → status остаётся draft
```

### Новая переменная окружения (Sprint 4)

```dotenv
# Yandex Wordstat (опционально, для предложения ключевых слов)
YANDEX_WORDSTAT_TOKEN=
```

### Расписание задач (Ads APScheduler)

| ID задачи | Расписание | Действие |
|-----------|-----------|----------|
| `ads_ab_test_check` | Ежедн. 07:00 МСК | Оценка A/B-тестов, пауза проигравших |
| `ads_budget_check` | Каждый час | Проверка дневного/месячного лимита |
| `ads_weekly_report` | Пн 08:00 МСК | Отчёт по расходам и CTR |

### A/B-тестирование

- Минимум 2 варианта объявлений на кампанию
- Оценка через 7 дней при >= 100 показов на вариант
- Победитель: максимальный CTR
- Проигравшие варианты останавливаются автоматически

### n8n Workflow

Файл: [`n8n-workflows/ads-automation.json`](n8n-workflows/ads-automation.json)

| Шаг | n8n Node | Действие |
|-----|----------|----------|
| 1 | check_pending_drafts | Опрос черновиков каждые 15 минут |
| 2 | send_approval_request | `POST /ads/approval/send` |
| 3 | wait_for_approval | Ожидание нажатия кнопки в Telegram |
| 4 | launch_campaign | `POST /ads/launch` |
| 5 | notify_admin | Telegram-уведомление об успехе |
| error | error_notify_admin | Telegram-алерт при ошибке |

### Схема базы данных (Sprint 4)

[`db/migrations/005_sprint4_ads.sql`](db/migrations/005_sprint4_ads.sql) добавляет:

**`ad_campaigns`** — рекламные кампании:

| Колонка | Тип | Описание |
|---------|-----|----------|
| `platform` | TEXT | `yandex` или `youtube` |
| `status` | TEXT | `draft` → `pending_approval` → `running` / `paused` / `rejected` |
| `config_json` | JSONB | Полный конфиг (ключевые слова, объявления, стратегия) |
| `campaign_id_external` | TEXT | ID кампании в Яндекс.Директ |
| `budget_rub` | NUMERIC | Месячный бюджет |

**`ad_variants`** — варианты объявлений для A/B-тестов.  
**`ad_approvals`** — журнал одобрений/отклонений.  
**`ad_daily_spend`** — ежедневная статистика расходов.

---

## Запуск тестов

```bash
# Установка зависимостей
pip install -r requirements.txt

# Все тесты
pytest tests/ -v

# Только юнит-тесты
pytest tests/unit/ -v

# Только интеграционные тесты
pytest tests/integration/ -v

# С покрытием
pytest tests/ --cov=integrations --cov-report=term-missing
```

**Результат Sprint 1:** 25 тестов, 0 ошибок.  
**Результат Sprint 2:** добавлено 40+ тестов (generator, calendar, publisher, pipeline).  
**Результат Sprint 3:** добавлено 35+ тестов (collector, engine, digest, pipeline).  
**Результат Sprint 4:** добавлено 9 тестов (approval, budget_monitor, ab_test, pipeline).

---

## Линтинг и форматирование

```bash
ruff check .          # проверка стиля
black --check .       # проверка форматирования
black .               # применить форматирование
```

---

## Структура проекта

```
ai-marketing-team/
├── agents/
│   ├── base/SOUL.md              # Базовый шаблон агента
│   └── strategist/
│       ├── SOUL.md               # Системный промпт Стратега
│       └── skills/SKILL.md       # Описание навыков
├── app/
│   ├── config.py                 # Настройки (pydantic-settings)
│   ├── main.py                   # FastAPI + startup/shutdown
│   └── models.py                 # SQLAlchemy ORM модели
├── agents/
│   ├── base/SOUL.md
│   ├── strategist/SOUL.md + skills/SKILL.md
│   └── content/                  # Sprint 2
│       ├── SOUL.md               # Системный промпт Контент-агента
│       └── skills/SKILL.md       # Описание навыков + примеры вызовов
├── db/migrations/
│   ├── 001_initial.sql           # Sprint 0: базовые таблицы
│   ├── 002_sprint1_strategist.sql # Sprint 1: content_plans, plan_approvals
│   └── 003_sprint2_content.sql   # Sprint 2: scheduled_posts, habr_drafts
├── integrations/
│   ├── scheduler.py              # APScheduler (воскресные задачи)
│   ├── strategist/
│   │   ├── models.py             # Pydantic-модели (ContentPlan и др.)
│   │   └── planner.py            # Логика генерации плана
│   ├── content/                  # Sprint 2
│   │   ├── models.py             # Post, ScheduledPost, HabrDraft
│   │   ├── generator.py          # ContentGenerator + TokenBucket
│   │   ├── calendar.py           # CalendarManager (schedule + CRUD)
│   │   ├── habr_draft.py         # HabrGenerator (long-form articles)
│   │   └── router.py             # FastAPI router /api/v1/content/
│   └── telegram/
│       ├── commands.py           # Обработчики команд + inline-кнопки
│       └── publisher.py          # Sprint 1 helpers + Sprint 2 publish_post
├── n8n-workflows/
│   ├── strategist-weekly-digest.json
│   └── content-pipeline.json     # Sprint 2: 3x/day content pipeline
├── tests/
│   ├── conftest.py               # Фикстуры (DB со Sprint 2 таблицами, mocks)
│   ├── unit/
│   │   ├── test_planner.py
│   │   ├── test_telegram_commands.py
│   │   ├── test_content_generator.py  # Sprint 2
│   │   ├── test_content_calendar.py   # Sprint 2
│   │   └── test_telegram_publisher.py # Sprint 2
│   └── integration/
│       ├── test_weekly_digest.py
│       └── test_content_pipeline.py   # Sprint 2
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## CI/CD

- **CI** (`.github/workflows/ci.yml`): запускается на `push` в `sprint-*` и `develop`. Шаги: `ruff lint` → `black check` → `pytest`.
- **Deploy** (`.github/workflows/deploy.yml`): запускается на `push` в `main`. SSH → `docker-compose pull && up` → health check → Telegram-уведомление.

---

## Переменные окружения

Смотрите [`.env.example`](.env.example). Все секреты хранятся только в GitHub Secrets и локальном `.env` (не в репозитории).

---

## Sprint 6 — Events Agent (Conference Scout)

### Что делает
- Ежемесячно собирает русскоязычные tech-конференции с 6 источников (aiconf.ru, productsense.io, ritfest.ru, habr.com/ru/events/, ppc.world/events/, tadviser.ru)
- Оценивает релевантность конференций для каждого продукта через Claude Haiku (порог 50/100)
- Отслеживает CFP дедлайны: напоминания за 14 и 3 дня
- Генерирует черновики заявок спикеров через Claude Sonnet
- Отправляет ежемесячный дайджест администратору в Telegram с inline-кнопками
- Подача заявки — только с апрува администратора (стаб-заглушка)

### Новые переменные окружения
```env
EVENTS_ENABLED=true   # включить Events Agent
```

### Новые HTTP API эндпоинты
- `POST /api/v1/events/scrape` — запустить сбор конференций
- `POST /api/v1/events/filter` — оценить релевантность
- `GET  /api/v1/events/calendar` — список предстоящих событий
- `POST /api/v1/events/digest/send` — отправить дайджест
- `POST /api/v1/events/abstract/{event_id}` — сгенерировать черновик заявки

### Миграция БД
```bash
psql $DATABASE_URL -f db/migrations/007_sprint6_events.sql
```

### Расписание (APScheduler)
- 1-е число каждого месяца 10:00 МСК — сбор + фильтрация
- 1-е число каждого месяца 10:30 МСК — отправка дайджеста
- Ежедневно 09:00 МСК — проверка дедлайнов

### n8n workflow
Импортируй `n8n-workflows/events-pipeline.json` в n8n. Установи env var `APP_BASE_URL`.

### Новые таблицы БД
- `events_calendar` — конференции с полями name, url, start_date, cfp_deadline, status и т.д.
- `events_abstracts` — черновики заявок спикеров
- `events_applications` — зарегистрированные заявки (стаб)
