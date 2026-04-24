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

## Запуск тестов

```bash
# Установка зависимостей
pip install -r requirements.txt

# Все тесты
pytest tests/ -v --asyncio-mode=auto

# Только юнит-тесты
pytest tests/unit/ -v --asyncio-mode=auto

# С покрытием
pytest tests/ --cov=integrations/strategist --cov-report=term-missing
```

**Результат Sprint 1:** 25 тестов, 0 ошибок.

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
├── db/migrations/
│   ├── 001_initial.sql           # Sprint 0: базовые таблицы
│   └── 002_sprint1_strategist.sql # Sprint 1: content_plans, plan_approvals
├── integrations/
│   ├── scheduler.py              # APScheduler (воскресные задачи)
│   ├── strategist/
│   │   ├── models.py             # Pydantic-модели (ContentPlan и др.)
│   │   └── planner.py            # Логика генерации плана
│   └── telegram/
│       ├── commands.py           # Обработчики команд + inline-кнопки
│       └── publisher.py          # Отправка сообщений с retry
├── n8n-workflows/
│   └── strategist-weekly-digest.json
├── tests/
│   ├── conftest.py               # Фикстуры (DB, mock bot, settings)
│   ├── unit/
│   │   ├── test_planner.py
│   │   └── test_telegram_commands.py
│   └── integration/
│       └── test_weekly_digest.py
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
