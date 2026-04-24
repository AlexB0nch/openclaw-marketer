# AI Marketing Team — Claude Code Rules

## Project Overview
AI Marketing Team — система автономных агентов для маркетинга на базе OpenClaw.
Telegram-бот как главный интерфейс управления.
Стек: Python 3.11, OpenClaw self-hosted, n8n, PostgreSQL, Telegram Bot API.

## Branch Strategy
- Direct push to main is PROHIBITED. Always use PRs.
- Branch flow: `sprint-N/feature-name` → `develop` → `main`
- All PRs require CI to pass before merge.

## Code Standards
- Python 3.11, black formatter, ruff linter
- Type hints everywhere — no untyped functions
- Async-first: asyncio + aiohttp for all external API calls
- Environment variables via python-dotenv, NEVER hardcode secrets

## Testing
- pytest, minimum 70% coverage for integrations
- Mock ALL external API calls in tests

## Deploy
- Docker Compose for all services
- Health check endpoint: GET /health → 200
- Rollback: auto-revert on deploy failure
- Notify Telegram on deploy success/failure

## Agent Architecture
- Each agent has: `agents/<name>/SOUL.md` + `skills/` directory
- n8n workflows exported to `n8n-workflows/*.json`
- DB migrations in `db/migrations/` via Alembic

## Secret Management
- All API keys in GitHub Secrets + local `.env` (gitignored)
- `.env.example` always up to date

## Directory Structure
ai-marketing-team/
├── CLAUDE.md
├── agents/
│   ├── strategist/SOUL.md + skills/
│   ├── content/SOUL.md + skills/
│   ├── ads/SOUL.md + skills/
│   ├── tg-scout/SOUL.md + skills/
│   └── analytics/SOUL.md + skills/
├── integrations/
│   ├── telegram/
│   ├── yandex_direct/
│   ├── google_ads/
│   └── telegram_scout/
├── db/migrations/
├── n8n-workflows/
├── tests/
├── .github/workflows/
│   ├── ci.yml
│   └── deploy.yml
├── docker-compose.yml
└── .env.example