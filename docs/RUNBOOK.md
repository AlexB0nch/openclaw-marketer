# Operations Runbook

Эксплуатационное руководство AI Marketing Team. Все команды предполагают
запуск из корня проекта на проде (`docker compose` или systemd-сервис).

---

## Содержание

1. [Перезапуск отдельного агента](#перезапуск-отдельного-агента)
2. [Повторный запуск задачи из DLQ](#повторный-запуск-задачи-из-dlq)
3. [Добавление нового продукта](#добавление-нового-продукта)
4. [Ротация API-ключей](#ротация-api-ключей)
5. [Восстановление из бэкапа S3](#восстановление-из-бэкапа-s3)
6. [Частые ошибки и их устранение](#частые-ошибки-и-их-устранение)

---

## Перезапуск отдельного агента

Все шедулеры живут в одном процессе FastAPI (`app/main.py`). Полноценный
«перезапуск одного агента без рестарта приложения» делается через REST API.

### Через API (recommended)

```bash
# Strategist — пересобрать план немедленно
curl -X POST https://marketing.example.com/api/v1/strategist/plan/generate \
  -H "X-Api-Key: $ADMIN_API_KEY"

# Content — обработать pending слоты
curl -X POST https://marketing.example.com/api/v1/content/run-pending \
  -H "X-Api-Key: $ADMIN_API_KEY"

# Analytics — снять снимок
curl -X POST https://marketing.example.com/api/v1/analytics/engine/snapshot \
  -H "X-Api-Key: $ADMIN_API_KEY"

# Events — внеплановый scrape
curl -X POST https://marketing.example.com/api/v1/events/scrape \
  -H "X-Api-Key: $ADMIN_API_KEY"
```

### Полный рестарт контейнера (если API недоступен)

```bash
docker compose restart api
docker compose logs -f api | tail -200
```

Health-check: `curl https://marketing.example.com/health` должен вернуть
`{"status":"ok"}`.

---

## Повторный запуск задачи из DLQ

`dead_letter_queue` хранит проваленные задачи всех агентов. Каждая запись
содержит `agent`, `task`, `payload` (JSONB), `error_message`, `traceback`,
`attempts`, `status` (`pending` / `retrying` / `resolved` / `abandoned`).

### Просмотр очереди

```bash
docker compose exec db psql -U marketing -d marketing -c \
  "SELECT id, agent, task, status, attempts, created_at, left(error_message, 80)
   FROM dead_letter_queue WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20;"
```

### Ручной retry конкретной задачи

```sql
-- 1. Снять статус, чтобы воркер подобрал её повторно
UPDATE dead_letter_queue
   SET status = 'pending', updated_at = now()
 WHERE id = 42;
```

```bash
# 2. Дёрнуть retry-loop вручную
curl -X POST https://marketing.example.com/api/v1/admin/dlq/retry \
  -H "X-Api-Key: $ADMIN_API_KEY"
```

### Закрыть задачу как «не воспроизводится»

```sql
UPDATE dead_letter_queue
   SET status = 'abandoned', updated_at = now()
 WHERE id = 42;
```

> Если `attempts >= 3`, авто-retry больше не запустится — нужен ручной анализ.

---

## Добавление нового продукта

Продукты появляются в нескольких местах. Чтобы новый продукт `ai_xyz`
поддерживался всеми агентами:

1. **Strategist** — добавить в `agents/strategist/config.yaml` и (если
   используется) в БД-таблицу `products`.
2. **Content** — обновить `integrations/content/templates/` (шаблоны
   текстов под продукт).
3. **TG Scout** — добавить ключевые слова в
   `integrations/telegram/scout_scheduler.py::_PRODUCT_KEYWORDS`.
4. **Events** — добавить в `integrations/events/events_scheduler.py::PRODUCTS`.
5. **Ads** — создать новую кампанию-шаблон в `ad_campaigns` (через UI
   Yandex Direct или SQL seed) и пометить нужный `product`.
6. **Analytics** — никаких изменений: метрики берутся через `posts.product`.

После всех правок:

```bash
docker compose restart api
pytest tests/integration -k product
```

---

## Ротация API-ключей

Все секреты — в `.env` на проде и в GitHub Secrets для CI. Никогда не
коммитьте ключи в репозиторий.

### Anthropic

1. Создать новый ключ в [console.anthropic.com](https://console.anthropic.com).
2. `ANTHROPIC_API_KEY=<new>` в `.env`.
3. `docker compose restart api`.
4. Удалить старый ключ в консоли Anthropic.

### Telegram Bot

1. `/revoke` в [@BotFather](https://t.me/BotFather) → получить новый токен.
2. `TELEGRAM_BOT_TOKEN=<new>` в `.env`.
3. `docker compose restart api`.
4. Проверить `/status` в админ-чате.

### Yandex Direct OAuth

1. Открыть [oauth.yandex.ru](https://oauth.yandex.ru/), отозвать старый
   токен у приложения.
2. Получить новый OAuth-token.
3. `YANDEX_DIRECT_OAUTH_TOKEN=<new>` в `.env`.
4. `docker compose restart api`.
5. Smoke-тест: `curl -X POST .../api/v1/ads/yandex/health` → 200.

### TGStat

1. В личном кабинете TGStat сгенерировать новый ключ.
2. `TGSTAT_API_KEY=<new>` в `.env`.
3. `docker compose restart api`.
4. Старый ключ удалить через 24 ч (на случай отката).

### AWS S3 (бэкапы)

1. В IAM создать новый Access Key для backup-юзера.
2. `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` в `.env`.
3. `docker compose restart api`.
4. Старый ключ — `aws iam delete-access-key` после успешного ночного бэкапа.

---

## Восстановление из бэкапа S3

Бэкапы кладутся cron'ом `daily_backup` (Strategist scheduler) каждый день в
03:00 MSK в `s3://$AWS_S3_BACKUP_BUCKET/backups/YYYY-MM-DD/<timestamp>.sql.gz`.

### Найти подходящий бэкап

```bash
aws s3 ls s3://$AWS_S3_BACKUP_BUCKET/backups/ --recursive | tail -20
```

### Скачать и развернуть

```bash
# 1. Скачать
aws s3 cp s3://$AWS_S3_BACKUP_BUCKET/backups/2026-04-26/20260426T030005.sql.gz /tmp/

# 2. Распаковать
gunzip /tmp/20260426T030005.sql.gz

# 3. Остановить приложение, чтобы не было записей в момент restore
docker compose stop api

# 4. Восстановить (DESTRUCTIVE! предварительно сделать pg_dump текущей БД)
docker compose exec -T db psql -U marketing -d marketing < /tmp/20260426T030005.sql

# 5. Запустить
docker compose start api
curl https://marketing.example.com/health
```

> Перед restore **обязательно** сделать дамп текущего состояния:
> `docker compose exec db pg_dump -U marketing marketing > /tmp/pre-restore.sql`.

---

## Частые ошибки и их устранение

### `ImportError` на старте

```
ImportError: cannot import name 'X' from 'integrations.Y'
```

**Причины:**
- Зависимость не установлена → `pip install -r requirements.txt`.
- Циклический импорт: проверить, что `Bot`/`engine` создаются в
  `app/main.py`, а не на module-level.
- Несовпадение версий → `pip freeze | grep <pkg>`, сверить с
  `requirements.txt`.

### Telethon session expired

```
telethon.errors.AuthKeyUnregisteredError
```

**Действия:**
1. Остановить контейнер: `docker compose stop api`.
2. Удалить старый session-файл: `rm $TELETHON_SESSION_PATH`.
3. Локально на машине, где можно ввести код из SMS, запустить
   `python scripts/telethon_login.py` (создаст новый session).
4. Скопировать session в прод.
5. `docker compose start api`.

### asyncpg pool exhausted

```
asyncpg.exceptions.TooManyConnectionsError: too many clients already
```

**Действия:**
1. Проверить, нет ли «висящих» сессий: `SELECT count(*) FROM pg_stat_activity;`.
2. Убедиться, что код использует `async with AsyncSession(engine) as session:`,
   а не глобальную сессию.
3. При необходимости временно поднять `db_pool_size` / `db_max_overflow` в
   `app/config.py` и `docker compose restart api`.
4. Постоянное решение — найти место с утечкой сессии (forgot `await session.close()`).

### n8n webhook unreachable

```
HTTP 502 / connection refused при вызове n8n endpoint
```

**Действия:**
1. `docker compose ps n8n` — контейнер запущен?
2. `docker compose logs n8n --tail 100` — есть ошибки?
3. Health: `curl http://n8n:5678/healthz`.
4. Если не отвечает — `docker compose restart n8n`.
5. Workflow «Uptime Monitor» (`n8n-workflows/uptime-monitor.json`) ловит
   эти инциденты и шлёт алерт в Telegram автоматически.

### DLQ растёт без пауз

Если в `dead_letter_queue` каждый час десятки новых записей от одного агента
— проблема массовая (упал внешний API, сменился токен, изменился контракт).
Проверить:

```sql
SELECT agent, task, count(*) FROM dead_letter_queue
WHERE created_at > now() - interval '1 hour'
GROUP BY agent, task ORDER BY count(*) DESC;
```

Найти общий `error_message`:

```sql
SELECT left(error_message, 120), count(*) FROM dead_letter_queue
WHERE status = 'pending' GROUP BY 1 ORDER BY 2 DESC LIMIT 5;
```

---

## Контакты

- Алерты: Telegram-чат `$TELEGRAM_ADMIN_CHAT_ID`
- Метрики: `/dashboard` команда в Telegram
- Логи: `docker compose logs api -f`
