# Deploy live on Railway (recommended for hackathon)

Railway runs always-on processes (no spin-down), gives free trial credit that
comfortably covers a hackathon judging window, and adds managed PostgreSQL plus
Redis in two clicks. This deploys the bot and monitor so judges can DM
@MantleAlphaBot anytime. (The REST API is optional, since the bot works via
polling without any public URL.)

> Prerequisite: your code is pushed to GitHub.

---

## 1. Create the project

1. Go to https://railway.app and sign in with GitHub.
2. New Project, then Deploy from GitHub repo, and pick your `Mantle-Alpha-Agent` repo.
   Railway auto-detects Python via `requirements.txt` and builds it.

## 2. Add the databases

In the project canvas:

1. New, then Database, then Add PostgreSQL.
2. New, then Database, then Add Redis.

Railway exposes them as `${{Postgres.DATABASE_URL}}` and `${{Redis.REDIS_URL}}`
variable references. The config auto-converts the `postgres://` URL to the async
driver, so no editing is needed.

## 3. Configure the first service as the BOT

Open the service Railway created from your repo, then Settings:

- Start Command:
  ```
  alembic upgrade head && python -m backend.bot.telegram_bot
  ```
  (The `alembic upgrade head` prefix creates the schema on first boot.)

Then open Variables and add:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `TELEGRAM_BOT_TOKEN` | your BotFather token |
| `OPENAI_API_KEY` | optional, omit to use the rule-based parser |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `REDIS_URL` | `${{Redis.REDIS_URL}}` |
| `MANTLE_RPC_URL` | `https://rpc.mantle.xyz` |

Click Deploy. Watch the logs for `bot.starting_polling` and `getUpdates 200`.

## 4. Add the MONITOR as a second service

1. New, then GitHub Repo, then select the same repo again (creates a 2nd service).
2. Settings, then Start Command:
   ```
   python -m backend.worker
   ```
3. Variables: add the same set as the bot (`ENVIRONMENT`, `TELEGRAM_BOT_TOKEN`,
   `DATABASE_URL`, `REDIS_URL`, `MANTLE_RPC_URL`, optional `OPENAI_API_KEY`).
   Tip: use Railway's "Add Reference" to share the DB and Redis variables.

Deploy. Watch for `monitor.starting` and the Mantle RPC connection.

## 5. (Optional) Expose the REST API

1. New, then GitHub Repo, same repo (3rd service).
2. Start Command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
3. Same variables. Settings, then Networking, then Generate Domain.
4. Visit `https://<your-domain>/docs` for live OpenAPI docs to show judges.

## 6. Verify it is live

- DM @MantleAlphaBot: `/start`, then `/track mETH 100`.
- Within minutes the monitor should deliver a whale alert.
- Bot logs show `getUpdates 200`; monitor logs show `monitor.range_done`.

---

## Cost and tips

- Railway's trial credit is plenty for a hackathon. Two small services plus
  Postgres plus Redis stay well under it.
- Bot polling needs no public port. Only the optional API service needs a domain.
- Rotate your bot token (@BotFather, then `/revoke`) if it was ever shared publicly.
- To redeploy, just `git push`. Railway rebuilds automatically.

## Render alternative

A declarative `render.yaml` blueprint is included at the repo root for
[Render](https://render.com). Use New, then Blueprint, then connect repo. Note
Render's free tier spins down web services and bills background workers, so
Railway is the better fit for an always-on bot during judging.
