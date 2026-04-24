# AI Marketing Team — Полная архитектура и стратегия

## Обзор системы

Система строится как команда из шести специализированных AI-агентов, каждый из которых закрывает конкретную маркетинговую функцию. Агенты развёртываются на OpenClaw (self-hosted VPS) и оркестрируются через n8n. Ввод задач — через Telegram. Хранение кода — GitHub. Сборка и деплой — через Claude Code + GitHub Actions.

***

## Шесть агентов команды

### 1. Стратег (Chief Marketing Agent)

Верхнеуровневый координатор. Хранит в памяти позиционирование всех трёх продуктов, текущие цели по каждому, историю кампаний и результаты. Принимает высокоуровневые команды от тебя через Telegram и транслирует их в задачи для подчинённых агентов.[^1]

**Что делает автономно:**
- Еженедельно генерирует план кампаний на следующую неделю
- Перераспределяет бюджет между каналами на основе данных аналитика
- Формулирует messaging framework для каждого продукта
- Собирает weekly digest и отправляет тебе в Telegram

**SOUL.md:** Содержит описания трёх продуктов, их ЦА, tone of voice, конкурентный контекст, ограничения бюджета.

### 2. Контент-агент (Content Agent)

Пишет контент под каждый продукт и каждую площадку. Работает по редакционному календарю, который генерирует Стратег.[^2]

**Зоны ответственности:**
- Посты в Telegram-каналы (отдельный стиль для каждого из трёх продуктов)
- Черновики статей для Хабра и vc.ru
- Адаптации под LinkedIn (ИИ-помощник по переписке — B2B аудитория)
- Скрипты для YouTube Shorts / видео-ads

n8n уже содержит готовые workflow «Auto-generate social media posts from URLs» и «Create social media content from Telegram with AI» — Content Agent использует их как базу.[^3][^4]

### 3. Рекламный агент (Ads Agent)

Управляет платной рекламой. Интегрируется с Яндекс Директ через официальный Python API (`tapi-yandex-direct`) и YouTube Ads через Google Ads API.[^5][^6]

**Яндекс Директ — что автоматизируется:**
- Создание и обновление кампаний через `client.campaigns().post()`
- Управление ключевыми словами и ставками
- Получение отчётов по эффективности (Clicks, Cost, CTR) через `client.reports()`
- A/B тест объявлений: агент создаёт 2-3 варианта, через неделю анализирует и оставляет лучший

**YouTube Ads:**
- Планирование video-кампаний
- Подготовка brief для видео-creatives
- Трекинг метрик (view rate, CTR, конверсии)

**Апрув обязателен:** агент готовит кампанию полностью, но запускает только после твоего подтверждения в Telegram.

### 4. Telegram-скаут (TG Scout Agent)

Ищет релевантные Telegram-каналы, анализирует их аудиторию и готовит предложения для коллабораций.[^7]

**Workflow поиска:**
1. Парсинг каналов через Telethon + TGStat API по ключевым словам (AI, спорт, предпринимательство, разработка)
2. Фильтрация по критериям: ER > 5%, аудитория > 1K, тематическое совпадение
3. Сбор контактов (username, email в bio, ссылки)
4. Генерация персонализированного pitch-текста для каждого канала
5. Отправка тебе в Telegram: таблица каналов + черновики питчей

**Мониторинг упоминаний:**
- Отслеживает упоминания продуктов и ключевых слов в Telegram
- Сигнализирует, когда стоит вступить в обсуждение

**Запрос на отправку** питча всегда требует твоего апрува.[^8]

### 5. Аналитик (Analytics Agent)

Трекает метрики по всем каналам и продуктам, выявляет паттерны и аномалии.[^2]

**Источники данных:**
- Яндекс Директ API — метрики рекламы
- Telegram Bot API — статистика каналов (просмотры, репосты, реакции)
- Google Analytics — трафик на лендинги
- Собственная БД (PostgreSQL) — лиды, конверсии

**Что генерирует:**
- Утренний дайджест в Telegram: что изменилось за ночь
- Еженедельный отчёт: какой контент сработал, какой нет, ROI по каналам
- Алерты: аномальный рост/падение метрик, исчерпание рекламного бюджета

### 6. Конференц-разведчик (Events Agent)

Раз в месяц проводит мониторинг релевантных конференций и ивентов.[^9]

**Алгоритм:**
1. Web search по конференциям в нишах (AiConf, ProductSense, RIF, SportTech, WebSummit)
2. Парсинг дедлайнов подачи докладов
3. Оценка релевантности: размер аудитории, формат, стоимость участия
4. Генерация таблицы: название, дата, дедлайн заявки, формат, ссылка
5. Доставка тебе в Telegram

***

## Архитектурная схема

```
[Ты] → Telegram → OpenClaw (Стратег)
                        ↓
          ┌─────────────┼─────────────┐
          ↓             ↓             ↓
     n8n Workflow   n8n Workflow  n8n Workflow
    (Контент)       (Реклама)    (TG Scout)
          ↓             ↓             ↓
    Telegram API   Яндекс API    Telethon
    Habr/vc.ru     YouTube API   TGStat API
          ↓             ↓             ↓
                  PostgreSQL (метрики)
                        ↓
               Analytics Agent → Telegram (отчёты)
```

***

## OpenClaw: технические детали

OpenClaw — self-hosted агент с четырёхслойной архитектурой:[^10]
- **Gateway Layer** — мультиканальная оркестрация (Node.js + WebSocket)
- **Reasoning Layer** — модели Claude/GPT с ClawRouters для автоматической маршрутизации
- **Memory Layer** — persistent storage с vector search
- **Execution Layer** — Skills/Plugins, web search, code execution

Для каждого из шести агентов создаётся отдельный `SOUL.md` файл в `~/.openclaw/workspace/` с его ролью, инструкциями и доступными инструментами.[^11]

**ClawHub skills для проекта:**
- `agent-team-orchestration` — управление командой агентов[^12]
- `agent-analytics` — дашборд агентов в реальном времени
- `agent-autonomy-primitives` — long-running autonomous loops[^12]
- `agent-rate-limiter` — защита от 429 ошибок при работе с внешними API[^12]

**ClawRouters — экономия API-бюджета:** простые задачи (генерация постов) → дешёвые модели; стратегические решения → Claude Sonnet/Opus. Экономия 40–60% API costs.[^1]

***

## Стек технологий

| Компонент | Технология | Назначение |
|---|---|---|
| Агентный фреймворк | OpenClaw (self-hosted) | Оркестрация, память, Telegram |
| Автоматизация воронок | n8n | Workflows, интеграции |
| Рекламный API | tapi-yandex-direct | Яндекс Директ[^5] |
| Реклама YouTube | Google Ads API | Video campaigns |
| Telegram парсинг | Telethon + python-telegram-bot | TG Scout[^13] |
| Хранилище | PostgreSQL | Метрики, лиды, история |
| CI/CD | GitHub Actions | Деплой, тесты[^14] |
| Разработка | Claude Code | Написание кода агентов |
| Хостинг | VPS (Vultr/Hetzner) | Уже есть |

***

## Матрица: что агент делает сам vs. с апрувом

| Действие | Агент | Режим |
|---|---|---|
| Генерация контент-плана на неделю | Стратег | ✅ Авто |
| Написание и публикация постов в TG | Контент | ✅ Авто |
| Черновик статьи для Хабра | Контент | ✅ Авто |
| Публикация на Хабре / vc.ru | Контент | ⚠️ Апрув |
| Создание рекламной кампании в Директ | Ads | ✅ Авто (подготовка) |
| Запуск рекламы | Ads | ⚠️ Апрув + бюджет |
| Поиск TG-каналов и подготовка питча | TG Scout | ✅ Авто |
| Отправка питча каналу | TG Scout | ⚠️ Апрув |
| Мониторинг метрик и дайджест | Аналитик | ✅ Авто |
| Поиск конференций | Events | ✅ Авто |
| Подача заявки на конференцию | Events | ⚠️ Апрув |

***

## Структура GitHub-репозитория

```
ai-marketing-team/
├── CLAUDE.md                    # Rules for Claude Code CI/CD
├── docker-compose.yml           # n8n + PostgreSQL
├── agents/
│   ├── strategist/
│   │   ├── SOUL.md              # System prompt
│   │   └── skills/              # Agent-specific skills
│   ├── content/
│   ├── ads/
│   ├── tg-scout/
│   ├── analytics/
│   └── events/
├── n8n-workflows/
│   ├── content-pipeline.json
│   ├── ads-automation.json
│   ├── tg-scout-pipeline.json
│   └── analytics-report.json
├── integrations/
│   ├── yandex_direct/
│   │   ├── client.py            # tapi-yandex-direct wrapper
│   │   ├── campaigns.py
│   │   └── reports.py
│   ├── telegram/
│   │   ├── scout.py             # Telethon channel search
│   │   └── publisher.py
│   └── google_ads/
│       └── youtube_client.py
├── db/
│   └── migrations/
├── tests/
└── .github/
    └── workflows/
        ├── ci.yml               # Lint, tests
        └── deploy.yml           # Deploy to VPS
```

`CLAUDE.md` определяет правила CI/CD: ветки `feature/*` → `develop` → `main`, обязательное прохождение тестов перед merge, хранение всех API ключей в GitHub Secrets.[^14]

***

## Продукты и фокус агентов

| Продукт | Приоритетные каналы | Ads агент | Контент агент |
|---|---|---|---|
| ИИ-помощник по переписке | Яндекс Директ, LinkedIn, Хабр | Директ (ключи: AI помощник, email автоматизация) | Статьи-кейсы, B2B посты |
| ИИ-тренер для спортсменов | YouTube Ads, TG Sport-каналы | YouTube pre-roll | Видео-контент, тренировочные советы |
| ИИ-агрегатор новостей | Хабр, TG dev-каналы, Директ | Директ (ключи: агрегатор новостей, дайджест) | Технические статьи, демо-посты |

---

## References

1. [OpenClaw Self-Hosted AI Agent GitHub: The Definitive 2026 Guide ...](https://www.oneclaw.net/blog/openclaw-ai-agent-self-hosted-github) - Deploy the OpenClaw self-hosted AI agent from GitHub with Docker, Node.js, or OneClaw managed hostin...

2. [Advanced N8n Workflows: AI Agents & Marketing Guide 2026](https://koanthic.com/en/advanced-n8n-workflows-ai-agents-marketing-guide-2026/) - Advanced n8n workflows with AI agents transform marketing automation in 2026. Build intelligent work...

3. [Auto-generate social media posts from URLs with AI, Telegram ...](https://n8n.io/workflows/9059-auto-generate-social-media-posts-from-urls-with-ai-telegram-and-multi-platform-posting/) - 1. Telegram – create a bot, connect via n8n Telegram credentials. 2. OpenAI / Gemini – add API key i...

4. [Create social media content from Telegram with AI - N8N](https://n8n.io/workflows/3057-create-social-media-content-from-telegram-with-ai/) - This n8n workflow empowers you to effortlessly generate social media content and captivating image p...

5. [tapi-yandex-direct - PyPI](https://pypi.org/project/tapi-yandex-direct/) - Python client for API Yandex Direct

6. [GitHub - pavelmaksimov/tapi-yandex-direct: Python библиотека API Яндекс Директ](https://github.com/pavelmaksimov/tapi-yandex-direct) - Python библиотека API Яндекс Директ. Contribute to pavelmaksimov/tapi-yandex-direct development by c...

7. [Telegram Channel Bot - GitHub](https://github.com/rodolflying/telegram_channel_bot) - An python app to automate channel related tasks like : periodical messages/reminders, news scraping,...

8. [OpenClaw for Marketing: A Primer](https://marketingagent.blog/2026/02/12/openclaw-for-marketing-a-primer/) - OpenClaw is arriving at a moment when marketing teams are simultaneously overwhelmed and empowered. ...

9. [AiConf 2026: переход от теории к практике - Habr](https://habr.com/ru/companies/oleg-bunin/articles/1017262/) - В 2026 году AiConf делает шаг от разговоров об AI к его практическому применению: ключевым элементом...

10. [OpenClaw GitHub Official Repository 2026: The Future of ... - Skywork](https://skywork.ai/slide/en/openclaw-autonomous-ai-repository-2038571898183094272) - OpenClaw GitHub Official Repository 2026: The Future of Autonomous AI Exploring the core capabilitie...

11. [GitHub - openclaw/openclaw: Your own personal AI assistant. Any OS. Any Platform. The lobster way. 🦞](https://github.com/openclaw/openclaw) - Your own personal AI assistant. Any OS. Any Platform. The lobster way. 🦞 - openclaw/openclaw

12. [Git & Github](https://github.com/VoltAgent/awesome-openclaw-skills) - The awesome collection of OpenClaw skills. 5,400+ skills filtered and categorized from the official ...

13. [python-telegram-bot/python-telegram-bot: We have made ... - GitHub](https://github.com/python-telegram-bot/python-telegram-bot) - Telegram Channel Telegram Group. We have made you a wrapper you can't refuse. We have a vibrant comm...

14. [CI/CD Pipeline Design with Claude Code: GitHub Actions from Zero ...](https://dev.to/myougatheaxo/cicd-pipeline-design-with-claude-code-github-actions-from-zero-to-deploy-2b14) - Step 1: Define CI/CD Rules in CLAUDE.md · Step 2: Generate the CI Workflow · Step 3: Auto-Post Cover...

