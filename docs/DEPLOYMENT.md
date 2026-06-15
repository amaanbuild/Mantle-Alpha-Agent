# Production Deployment Guide

This guide covers deploying the Mantle Alpha Agent to a production environment.

## Topology

Run each concern as its own horizontally-scalable process/container:

| Service | Command | Notes |
|---|---|---|
| `api` | `uvicorn backend.main:app` | Stateless; scale to N replicas behind a load balancer |
| `bot` | `python -m backend.bot.telegram_bot` | **Single instance** for polling; use webhook mode to scale |
| `worker` | `python -m backend.worker` | **Single instance** (block cursor); the monitor |
| `celery` | `celery -A backend.tasks.celery_app:celery_app worker` | Scale freely |
| `beat` | `celery ... beat` | **Single instance** (scheduler) |
| `db` | PostgreSQL 16 | Managed service recommended |
| `redis` | Redis 7 | Managed service recommended |

> The **bot** and **worker** must each run as a single instance to avoid
> duplicate Telegram polling and duplicate block processing. The **api** and
> **celery** workers scale horizontally.

## 1. Environment

Set production values (via your platform's secret manager - never commit `.env`):

```
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://<user>:<pass>@<host>:5432/<db>
REDIS_URL=redis://<host>:6379/0
CELERY_BROKER_URL=redis://<host>:6379/1
CELERY_RESULT_BACKEND=redis://<host>:6379/2

MANTLE_RPC_URL=<private-mantle-rpc>     # strongly recommended over the public RPC
TELEGRAM_BOT_TOKEN=<token>
OPENAI_API_KEY=<key>

API_KEY=<random-strong-secret>          # protects POST/DELETE REST endpoints
```

In production the app does **not** auto-create tables - run migrations explicitly.

## 2. Database migrations

```bash
alembic upgrade head
```

In Docker Compose this is the one-shot `migrate` service that other services
wait on (`service_completed_successfully`).

## 3. Telegram webhook mode (recommended for scale)

Polling is fine for a single bot instance. For higher throughput / HA, switch to
webhooks:

```
TELEGRAM_MODE=webhook
TELEGRAM_WEBHOOK_URL=https://your-domain.example
TELEGRAM_WEBHOOK_SECRET=<random-secret>
```

Expose the bot service behind TLS (a reverse proxy / managed ingress). The bot
registers the webhook automatically on startup.

## 4. Build & run with Docker Compose

```bash
docker compose -f docker-compose.yml up -d --build
```

For a managed platform (ECS, Cloud Run, Fly.io, Kubernetes), build the single
image in `docker/Dockerfile` and deploy each service with its own command from
the table above. Suggested resources: api/bot/worker 0.25-0.5 vCPU & 256-512 MB
each to start.

## 5. Health checks & observability

- Liveness/readiness: `GET /health` (returns `database` and `rpc` booleans).
- Logs are **structured JSON** in production (`LOG_LEVEL`, parsed by any log
  aggregator).
- Wire your error tracker (e.g. Sentry) into `backend/core/logging.py` and the
  bot/worker error handlers.
- Metrics: alert volume and last-alert timestamps are queryable from
  `alert_history`; add a Prometheus exporter against the same tables if desired.

## 6. Scaling notes

- **API**: stateless - scale replicas; put behind a load balancer.
- **Worker**: single instance. To shard, partition by token/contract and run one
  monitor per shard with distinct cursors.
- **Pricing/RPC**: use paid CoinGecko (`COINGECKO_API_KEY`) and a private RPC to
  avoid public rate limits.
- **Redis**: shared cache, rate-limit store, Celery broker, and monitor cursor -
  use a managed, persistent instance.

## 7. Security checklist

- [ ] All secrets injected from a secret manager; `.env` not committed.
- [ ] `API_KEY` set for REST mutating endpoints.
- [ ] TLS terminated in front of api/bot.
- [ ] Database backups & PITR enabled.
- [ ] Reporter key for on-chain logging (if enabled) is dedicated & minimally funded.
- [ ] Rate limits tuned (`RATE_LIMIT_*`) for expected traffic.

## 8. On-chain logging (optional)

Deploy `contracts/AlertLogger.sol` to Mantle, authorize the reporter address,
and set `ENABLE_ONCHAIN_LOGGING=true` with the contract address and reporter key.
See [contracts/README.md](../contracts/README.md).

## 9. Zero-downtime upgrades

1. Apply DB migrations (backward-compatible) via the `migrate` step.
2. Roll the `api` and `celery` replicas.
3. Restart `worker` and `bot` (brief gap acceptable; cursor resumes from Redis).
