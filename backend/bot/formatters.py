"""
Telegram message formatting (HTML parse mode).

Pure functions building the user-facing message strings. Centralized here so the
alert engine and the bot handlers render identically. All dynamic text is HTML-
escaped to prevent broken markup / injection into the message.
"""

from __future__ import annotations

import html
from datetime import datetime

from backend.config import settings
from backend.core.domain import WhaleTransaction
from backend.database.models import AlertHistory, AlertRule


def _esc(value: object) -> str:
    return html.escape(str(value), quote=False)


def _usd(value: float) -> str:
    return f"${value:,.2f}" if value < 1000 else f"${value:,.0f}"


# --------------------------------------------------------------------------- #
# Whale alert                                                                  #
# --------------------------------------------------------------------------- #
def format_whale_alert(whale: WhaleTransaction, insight: str) -> str:
    """Rich HTML message for a fired whale alert."""
    e = whale.event
    tx_url = settings.explorer_tx_url(e.tx_hash)
    lines = [
        "<b>Whale Alert</b>",
        "",
        f"<b>Token:</b> {_esc(e.token_symbol)}",
        f"<b>Action:</b> {_esc(e.direction.value.title())}",
        f"<b>Value:</b> {_usd(whale.value_usd)}",
        f"<b>Amount:</b> {_esc(f'{e.amount:,.4f}')} {_esc(e.token_symbol)}",
        "",
        f"<b>From:</b> <code>{_esc(whale.short_from)}</code>",
        f"<b>To:</b> <code>{_esc(whale.short_to)}</code>",
        "",
        f"<b>AI Insight:</b>\n{_esc(insight)}",
        "",
        f'<a href="{_esc(tx_url)}">View transaction</a>',
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Command responses                                                            #
# --------------------------------------------------------------------------- #
WELCOME = (
    "<b>Welcome to Mantle Alpha Agent</b>\n\n"
    "I monitor the Mantle blockchain and notify you when whales move.\n\n"
    "<b>Try natural language:</b>\n"
    "- <i>Track mETH whale trades above $10,000</i>\n"
    "- <i>Notify me when MNT buys exceed $50,000</i>\n"
    "- <i>Stop tracking mETH</i>\n"
    "- <i>Show today's whale activity</i>\n\n"
    "<b>Or slash commands:</b>\n"
    "/track &lt;token&gt; &lt;amount&gt; - start tracking\n"
    "/untrack &lt;token&gt; - stop tracking\n"
    "/myalerts - list your rules\n"
    "/history - recent alerts\n"
    "/status - your stats and bot health\n"
    "/settings - notification preferences\n"
    "/help - full guide"
)

HELP = (
    "<b>Mantle Alpha Agent - Help</b>\n\n"
    "<b>Commands</b>\n"
    "/start - welcome and onboarding\n"
    "/track &lt;token&gt; &lt;amount&gt; - e.g. <code>/track mETH 10000</code>\n"
    "/untrack &lt;token&gt; - e.g. <code>/untrack mETH</code>\n"
    "/myalerts - list active rules\n"
    "/history - your recent alerts\n"
    "/status - stats and health\n"
    "/settings - toggle notifications\n"
    "/stop - pause all notifications\n\n"
    "<b>Natural language</b>\n"
    "Just talk to me:\n"
    "- <i>Track MNT buys above $50,000</i>\n"
    "- <i>Notify me when smart money accumulates mETH</i>\n"
    "- <i>Stop tracking MNT</i>\n"
    "- <i>Show today's whale activity</i>\n\n"
    "Whale threshold = token amount x live USD price."
)


def format_rule_created(rule: AlertRule) -> str:
    event = "" if rule.event_type.value == "any" else f" {rule.event_type.value}"
    return (
        f"Now tracking <b>{_esc(rule.token_symbol)}</b>{_esc(event)} whale "
        f"transactions above <b>{_usd(rule.threshold_usd)}</b>."
    )


def format_rule_removed(token: str, count: int) -> str:
    if count == 0:
        return f"You weren't tracking <b>{_esc(token)}</b>."
    return f"Stopped tracking <b>{_esc(token)}</b> ({count} rule(s) removed)."


def format_my_alerts(rules: list[AlertRule]) -> str:
    if not rules:
        return "You have no active alerts. Try: <i>Track mETH whales above $10,000</i>"
    lines = ["<b>Your active alerts:</b>", ""]
    for i, r in enumerate(rules, 1):
        suffix = "" if r.event_type.value == "any" else f" ({r.event_type.value})"
        lines.append(
            f"{i}. <b>{_esc(r.token_symbol)}</b>{_esc(suffix)} &gt; {_usd(r.threshold_usd)}"
        )
    return "\n".join(lines)


def format_history(alerts: list[AlertHistory], title: str = "Recent alerts") -> str:
    if not alerts:
        return "No alerts yet. I'll notify you the moment a whale moves."
    lines = [f"<b>{_esc(title)}:</b>", ""]
    for a in alerts:
        ts = _fmt_ts(a.created_at)
        lines.append(
            f"- {_esc(a.token_symbol)} {_usd(a.value_usd)} "
            f"<i>{_esc(a.direction or a.event_type.value)}</i> at {_esc(ts)}"
        )
    return "\n".join(lines)


def format_status(
    active_rules: int, total_alerts: int, last_alert: datetime | None, rpc_ok: bool
) -> str:
    last = _fmt_ts(last_alert) if last_alert else "-"
    health = "Operational" if rpc_ok else "Degraded (RPC unreachable)"
    return (
        "<b>Status</b>\n\n"
        f"<b>Active rules:</b> {active_rules}\n"
        f"<b>Total alerts:</b> {total_alerts}\n"
        f"<b>Last alert:</b> {_esc(last)}\n"
        f"<b>Bot health:</b> {health}"
    )


def format_settings(notifications_enabled: bool) -> str:
    state = "ON" if notifications_enabled else "OFF"
    return (
        "<b>Settings</b>\n\n"
        f"Notifications: <b>{state}</b>\n\n"
        "Use /settings on or /settings off to change, or /stop to pause everything."
    )


def _fmt_ts(ts: datetime | None) -> str:
    if ts is None:
        return "-"
    return ts.strftime("%Y-%m-%d %H:%M UTC")
