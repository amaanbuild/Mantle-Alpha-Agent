# Deploy free on Render (no credit card)

Render's free tier gives one always-available web service (750 hours/month, which
covers a single service running full time), with no credit card required. This
app ships an all-in-one entrypoint (`backend/run_all.py`) that runs the REST API,
the Telegram bot, and the Mantle monitor in a single process, using a
self-contained SQLite database. The whole system fits one free web service, with
nothing else to provision.

> One caveat: free web services sleep after about 15 minutes with no inbound
> traffic. We keep it awake with a free uptime pinger (step 4). With that in
> place it stays up 24/7 for judging.

---

## 1. Push to GitHub

Make sure your latest code (including `render.yaml` and `backend/run_all.py`) is
on GitHub. This repo already has them.

## 2. Create the Blueprint

1. Go to https://render.com and sign in with GitHub (no card needed).
2. Click New, then Blueprint.
3. Connect this repository. Render reads `render.yaml` and shows one web service
   (`mantle-alpha-agent`).
4. Click Apply (or Deploy Blueprint). Render builds the service.

## 3. Add your bot token

1. Open the `mantle-alpha-agent` service, then Environment.
2. Set `TELEGRAM_BOT_TOKEN` to your BotFather token (it was left blank on purpose).
3. (Optional) set `OPENAI_API_KEY`. Without it, the deterministic intent parser
   is used, so the bot still works.
4. Save. Render redeploys automatically.

Watch the logs for:

```
run_all.bot_started
run_all.monitor_started
```

Your service gets a public URL like `https://mantle-alpha-agent.onrender.com`.
Visit `/docs` there for live OpenAPI docs.

## 4. Keep it awake (free uptime pinger)

Free web services sleep when idle, which would pause the bot and monitor. Prevent
that with a free pinger:

1. Sign up at https://uptimerobot.com (free) or https://cron-job.org (free).
2. Create an HTTP(s) monitor pointing at:
   ```
   https://<your-service>.onrender.com/health
   ```
3. Set the interval to every 5 to 10 minutes.

That steady traffic keeps the instance warm 24/7, so whale alerts keep flowing.

## 5. Verify it is live

- DM your bot on Telegram: `/start`, then `/track mETH 100`.
- Within a few minutes the monitor should deliver a whale alert.
- The Render log shows `monitor.range_done` and `getUpdates 200`.

---

## Notes and tips

- Data lives in a SQLite file on the instance. The free disk is ephemeral, so
  data resets on each redeploy. That is fine for a live demo.
- Only one instance may poll Telegram at a time. Keep this as a single free
  service (do not scale it to multiple instances).
- Redeploy by pushing to GitHub. Render rebuilds automatically.
- Rotate your bot token (@BotFather, then `/revoke`) if it was ever shared
  publicly, then update `TELEGRAM_BOT_TOKEN` in the Render dashboard.

## Want persistence? Add managed Postgres

To keep data across redeploys, create a managed PostgreSQL database in Render and
set the service's `DATABASE_URL` to its connection string (the app auto-converts
the `postgres://` URL to the async driver). Free Render databases are time-limited
and only one is allowed per account, so SQLite is the simpler default here.

## Other free always-on options

- Koyeb, Fly.io, and Hugging Face Spaces can also run `backend.run_all` as a
  single container. Use the same start command:
  `uvicorn backend.run_all:app --host 0.0.0.0 --port $PORT`.
- A truly free always-on VM (Oracle Cloud Always Free) can run the full
  `docker compose up -d` stack if you prefer the multi-process setup.
