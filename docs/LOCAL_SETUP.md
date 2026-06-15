# Local Setup Guide

This guide runs the Mantle Alpha Agent on your machine without Docker (or with
Docker only for Postgres and Redis).

## 1. Prerequisites

- Python 3.12 or newer
- PostgreSQL 14 or newer (or use SQLite for a zero-infra start)
- Redis 6 or newer (optional locally; the app degrades to in-memory caches and limits)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- (Optional) An OpenAI API key. The bot works without one via the rule-based
  intent fallback.

## 2. Clone and create a virtualenv

```bash
cd "Mantle Alpha Agent"
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

## 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

- `TELEGRAM_BOT_TOKEN` is required for the bot to run.
- `OPENAI_API_KEY` is optional (improves natural-language understanding).
- `DATABASE_URL` points at your Postgres, or for the simplest start use:
  ```
  DATABASE_URL=sqlite+aiosqlite:///./dev.db
  ```
- `MANTLE_RPC_URL` defaults to the public Mantle RPC; a private RPC is
  recommended for reliable monitoring.

## 4. Start infrastructure (skip if using SQLite and no Redis)

```bash
docker compose up -d db redis
```

## 5. Run migrations

```bash
alembic upgrade head
```

(With SQLite you can skip this; non-production startup auto-creates tables.)

## 6. Run the processes

Open three terminals (all with the venv activated):

```bash
# Terminal 1: REST API plus docs at http://localhost:8000/docs
uvicorn backend.main:app --reload

# Terminal 2: Telegram bot (inbound commands and natural language)
python -m backend.bot.telegram_bot

# Terminal 3: blockchain monitor (emits whale alerts)
python -m backend.worker
```

Optional, Celery for periodic maintenance:

```bash
celery -A backend.tasks.celery_app:celery_app worker -l info
celery -A backend.tasks.celery_app:celery_app beat   -l info
```

## 7. Try it

In Telegram:

```
/start
/track mETH 10000
Track MNT buys above $50,000
/myalerts
/status
```

## 8. Run the tests

```bash
pytest                 # full suite, in-memory SQLite, no external services
pytest --cov=backend
```

## Troubleshooting

- Bot does not respond: check `TELEGRAM_BOT_TOKEN` and ensure only one polling
  instance runs.
- No alerts: confirm the `worker` process is running and `MANTLE_RPC_URL` is
  reachable (`GET /health` shows `rpc: true`).
- Prices missing: public CoinGecko and DeFiLlama may rate-limit; the static
  fallback keeps valuations working (`PRICE_STATIC_FALLBACK_ENABLED=true`).
- Database errors: run `alembic upgrade head` and verify `DATABASE_URL`.
