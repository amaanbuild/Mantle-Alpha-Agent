# Process definitions for PaaS hosts (Render / Heroku and similar).
# Each line is a separately-scalable process; map them to services in your host.
#
#   bot     - Telegram bot (polling) - the always-on inbound handler
#   worker  - real-time Mantle block monitor -> alert engine -> Telegram
#   web     - REST API + OpenAPI docs (binds the platform-provided $PORT)
#   celery  - background/periodic task worker (optional)
#   beat    - periodic scheduler (optional)
#
# `release` runs once per deploy to apply DB migrations before processes boot.
release: alembic upgrade head
bot: python -m backend.bot.telegram_bot
worker: python -m backend.worker
web: uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
celery: celery -A backend.tasks.celery_app:celery_app worker -l info
beat: celery -A backend.tasks.celery_app:celery_app beat -l info
