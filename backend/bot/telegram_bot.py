"""
Telegram bot application wiring.

Builds the python-telegram-bot ``Application``, registers handlers, and exposes:
- :func:`build_application` : configured Application instance.
- :class:`TelegramNotifier`  : the ``async (chat_id, html) -> bool`` callback the
                               alert engine uses to deliver whale alerts.
- :func:`run_bot`            : entrypoint that runs polling (or webhook).

The same ``Bot`` instance powers both inbound handling and outbound alerts.
"""

from __future__ import annotations

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from backend.alerts.engine import get_alert_engine
from backend.bot.handlers import BotHandlers
from backend.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class TelegramNotifier:
    """Outbound delivery wrapper used by the alert engine."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, html: str) -> bool:
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=html,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except TelegramError as exc:
            logger.warning("notifier.send_failed", chat_id=chat_id, error=str(exc))
            return False


def build_application() -> Application:
    """Construct and configure the Telegram Application with all handlers."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    handlers = BotHandlers()

    app.add_handler(CommandHandler("start", handlers.start))
    app.add_handler(CommandHandler("help", handlers.help_cmd))
    app.add_handler(CommandHandler("track", handlers.track))
    app.add_handler(CommandHandler("untrack", handlers.untrack))
    app.add_handler(CommandHandler("myalerts", handlers.myalerts))
    app.add_handler(CommandHandler("history", handlers.history))
    app.add_handler(CommandHandler("status", handlers.status))
    app.add_handler(CommandHandler("settings", handlers.settings))
    app.add_handler(CommandHandler("stop", handlers.stop))

    # Any non-command text -> natural-language pipeline.
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.natural_language))

    app.add_error_handler(_on_error)

    # Wire the alert engine's delivery callback to this bot.
    notifier = TelegramNotifier(app.bot)
    get_alert_engine().set_notifier(notifier.send)

    logger.info("bot.application_built", mode=settings.TELEGRAM_MODE)
    return app


async def _on_error(update: object, context) -> None:  # pragma: no cover - PTB callback
    logger.error("bot.unhandled_error", error=str(context.error))


def run_bot() -> None:
    """Run the bot (polling for dev, webhook for production)."""
    app = build_application()
    if settings.TELEGRAM_MODE == "webhook" and settings.TELEGRAM_WEBHOOK_URL:
        logger.info("bot.starting_webhook", url=settings.TELEGRAM_WEBHOOK_URL)
        app.run_webhook(
            listen="0.0.0.0",
            port=settings.API_PORT,
            url_path=settings.TELEGRAM_BOT_TOKEN,
            webhook_url=f"{settings.TELEGRAM_WEBHOOK_URL.rstrip('/')}/{settings.TELEGRAM_BOT_TOKEN}",
            secret_token=settings.TELEGRAM_WEBHOOK_SECRET or None,
        )
    else:
        logger.info("bot.starting_polling")
        app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    run_bot()
