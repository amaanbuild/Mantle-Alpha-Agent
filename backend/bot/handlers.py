"""
Telegram command & natural-language handlers.

Both slash commands and free text funnel into the SAME :class:`AlertService`
and intent engine, so behavior is identical regardless of entry style. Each
handler:
  - upserts the user,
  - rate-limits per Telegram id,
  - performs the action inside a single DB transaction,
  - replies with an HTML-formatted message.
"""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from backend.ai.intent import IntentEngine, get_intent_engine
from backend.alerts.service import AlertService, AlertServiceError
from backend.blockchain.client import get_mantle_client
from backend.bot import formatters
from backend.core.logging import get_logger
from backend.core.security import RateLimiter, parse_amount, validate_token_symbol
from backend.core.types import EventType, IntentType
from backend.database.models import User
from backend.database.session import session_scope

logger = get_logger(__name__)


class BotHandlers:
    """Container for all Telegram update handlers."""

    def __init__(
        self,
        intent_engine: IntentEngine | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.intent = intent_engine or get_intent_engine()
        self.rate_limiter = rate_limiter or RateLimiter()

    # ------------------------------------------------------------------ #
    # Helpers                                                             #
    # ------------------------------------------------------------------ #
    async def _reply(self, update: Update, text: str) -> None:
        if update.message is None:
            return
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )

    async def _upsert_user(self, update: Update, service: AlertService) -> User:
        tg = update.effective_user
        chat = update.effective_chat
        return await service.users.get_or_create(
            telegram_id=tg.id,
            chat_id=chat.id if chat else tg.id,
            username=tg.username,
            first_name=tg.first_name,
            language_code=tg.language_code,
        )

    async def _rate_limited(self, update: Update) -> bool:
        uid = str(update.effective_user.id) if update.effective_user else "anon"
        allowed = await self.rate_limiter.allow(f"bot:{uid}")
        if not allowed:
            await self._reply(update, "Slow down a moment, you're sending requests too fast.")
        return not allowed

    @staticmethod
    def _strip_command(text: str | None) -> str:
        """Remove a leading /command (and optional @botname) from a message."""
        if not text:
            return ""
        parts = text.split(maxsplit=1)
        if parts and parts[0].startswith("/"):
            return parts[1] if len(parts) > 1 else ""
        return text

    async def _handle_nl_text(self, update: Update, text: str) -> None:
        """Run free text through the intent engine and dispatch the result.

        Shared by the natural-language handler and by slash commands that fall
        back here when their arguments are not in the structured form.
        """
        intent = await self.intent.extract(text)
        logger.info(
            "bot.intent",
            intent=intent.intent.value,
            token=intent.token,
            threshold=intent.threshold_usd,
            confidence=intent.confidence,
        )
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            reply = await self._dispatch_intent(service, user, intent, update)
        if reply:
            await self._reply(update, reply)

    # ------------------------------------------------------------------ #
    # Slash commands                                                      #
    # ------------------------------------------------------------------ #
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with session_scope() as session:
            await self._upsert_user(update, AlertService(session))
        await self._reply(update, formatters.WELCOME)

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply(update, formatters.HELP)

    async def track(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/track <token> <amount> (falls back to natural language for loose input)."""
        if await self._rate_limited(update):
            return
        args = context.args or []

        # Structured form: /track <token> <amount> where amount actually parses.
        if len(args) >= 2:
            token, amount_raw = args[0], args[1]
            try:
                threshold = parse_amount(amount_raw)
            except ValueError:
                threshold = None
            if threshold is not None:
                async with session_scope() as session:
                    service = AlertService(session)
                    user = await self._upsert_user(update, service)
                    try:
                        rule = await service.create_rule(
                            user,
                            token,
                            threshold,
                            EventType.ANY,
                            raw_request=update.message.text,
                        )
                    except (AlertServiceError, ValueError) as exc:
                        await self._reply(update, f"{exc}")
                        return
                    await self._reply(update, formatters.format_rule_created(rule))
                return

        # Loose input (e.g. "/track Track mETH whales above $10k"): let the AI parse it.
        rest = self._strip_command(update.message.text)
        if not rest.strip():
            await self._reply(
                update,
                "Usage: <code>/track &lt;token&gt; &lt;amount&gt;</code>\n"
                "Example: <code>/track mETH 10000</code>\n"
                "Or just tell me: <i>Track mETH whales above $10,000</i>",
            )
            return
        await self._handle_nl_text(update, f"track {rest}")

    async def untrack(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """/untrack <token> (falls back to natural language for loose input)."""
        if await self._rate_limited(update):
            return
        args = context.args or []

        # Structured form: first argument is a valid token symbol.
        if args:
            try:
                token = validate_token_symbol(args[0])
            except ValueError:
                token = None
            if token is not None:
                async with session_scope() as session:
                    service = AlertService(session)
                    user = await self._upsert_user(update, service)
                    count = await service.remove_token(user, token)
                    await self._reply(update, formatters.format_rule_removed(token, count))
                return

        # Loose input: route through the AI ("stop tracking ...").
        rest = self._strip_command(update.message.text)
        if not rest.strip():
            await self._reply(update, "Usage: <code>/untrack &lt;token&gt;</code>")
            return
        await self._handle_nl_text(update, f"stop tracking {rest}")

    async def myalerts(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            rules = await service.list_rules(user)
        await self._reply(update, formatters.format_my_alerts(rules))

    async def history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            alerts = await service.recent_history(user, limit=15)
        await self._reply(update, formatters.format_history(alerts))

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            summary = await service.status(user)
        rpc_ok = await get_mantle_client().is_connected()
        await self._reply(
            update,
            formatters.format_status(
                summary.active_rules, summary.total_alerts, summary.last_alert_at, rpc_ok
            ),
        )

    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        args = context.args or []
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            if args and args[0].lower() in {"on", "off"}:
                await service.set_notifications(user, args[0].lower() == "on")
            enabled = user.notifications_enabled
        await self._reply(update, formatters.format_settings(enabled))

    async def stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        async with session_scope() as session:
            service = AlertService(session)
            user = await self._upsert_user(update, service)
            await service.set_notifications(user, False)
        await self._reply(
            update,
            "Notifications paused. Your rules are kept, use /settings on to resume.",
        )

    # ------------------------------------------------------------------ #
    # Natural language                                                    #
    # ------------------------------------------------------------------ #
    async def natural_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not update.message.text:
            return
        if await self._rate_limited(update):
            return
        await self._handle_nl_text(update, update.message.text)

    async def _dispatch_intent(
        self, service: AlertService, user: User, intent, update: Update
    ) -> str | None:
        kind = intent.intent

        if kind in (IntentType.CREATE_ALERT, IntentType.MODIFY_ALERT):
            try:
                rule = await service.apply_create_intent(user, intent)
            except (AlertServiceError, ValueError) as exc:
                return f"{exc}"
            note = f"\n\n{intent.note}" if intent.note else ""
            return formatters.format_rule_created(rule) + note

        if kind == IntentType.DELETE_ALERT:
            try:
                count = await service.remove_token(user, intent.token)
            except ValueError as exc:
                return f"{exc}"
            return formatters.format_rule_removed(intent.token, count)

        if kind == IntentType.LIST_ALERTS:
            rules = await service.list_rules(user)
            return formatters.format_my_alerts(rules)

        if kind == IntentType.SHOW_HISTORY:
            today = "today" in intent.raw_text.lower()
            alerts = await service.recent_history(user, limit=15, today_only=today)
            title = "Today's whale activity" if today else "Recent alerts"
            return formatters.format_history(alerts, title)

        if kind == IntentType.SHOW_STATUS:
            summary = await service.status(user)
            rpc_ok = await get_mantle_client().is_connected()
            return formatters.format_status(
                summary.active_rules, summary.total_alerts, summary.last_alert_at, rpc_ok
            )

        if kind == IntentType.HELP:
            return formatters.HELP

        # Unknown -> gentle clarification.
        return intent.note or (
            "I didn't quite get that. Try: "
            "<i>Track mETH whale trades above $10,000</i> or /help."
        )
