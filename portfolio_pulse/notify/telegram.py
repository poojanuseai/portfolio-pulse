"""Telegram push + command handling.

Two responsibilities:
  * Push: send formatted alerts. Uses the plain Bot HTTP API via requests so it
    works from a stateless GitHub Actions run (no long-lived process needed).
  * Commands: /add /sell /watch /remove /positions /list, drained with
    getUpdates each poll (offset persisted in the store's meta table). Only
    messages from the configured chat_id are honoured — everyone else is ignored.

Message formatting is separated from I/O (format_alert, parse_command,
handle_update are pure) so the logic is unit-tested without network or a token.
"""

from __future__ import annotations

import html
from typing import Optional

import requests

from portfolio_pulse import config
from portfolio_pulse.store.db import Alert

_API = "https://api.telegram.org/bot{token}/{method}"
_OFFSET_KEY = "telegram_update_offset"

_QC_BADGE = {
    "CONFIRMED": "✅ verified",
    "PARTIAL": "⚠️ partial",
    "INSUFFICIENT": "⚠️ headline only",
    "SUSPECT": "⚠️ unverified",
    "SINGLE-SOURCE": "ℹ️ single source",
}


# --------------------------------------------------------------------------- #
# Formatting (pure)
# --------------------------------------------------------------------------- #
def format_alert(alert: Alert) -> str:
    """Render an alert as Telegram HTML. Always includes a source link when present."""
    tag = html.escape(alert.source_type or "Alert")
    sym = html.escape(alert.symbol)
    title = html.escape(alert.title)
    lines = [f"<b>{sym}</b> — {tag}", title]
    if alert.summary and alert.summary != alert.title:
        lines.append("")
        lines.append(html.escape(alert.summary))
    if alert.impact:
        lines.append(f"<i>{html.escape(alert.impact)}</i>")
    badge = _QC_BADGE.get(alert.qc_status, alert.qc_status)
    if badge:
        lines.append(f"<code>{html.escape(badge)}</code>")
    if alert.source_url:
        lines.append(f'<a href="{html.escape(alert.source_url)}">Source</a>')
    return "\n".join(lines)


def parse_command(text: str) -> tuple[str, str]:
    """Split '/add AAPL 10 185.50' -> ('add', 'AAPL 10 185.50'). Strips a bot
    @mention suffix."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return "", ""
    parts = text[1:].split(maxsplit=1)
    cmd = parts[0].split("@", 1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return cmd, arg


_HELP = (
    "Portfolio Pulse commands:\n"
    "/add SYMBOL QTY PRICE — log/update a position (e.g. /add AAPL 10 185.50)\n"
    "/sell SYMBOL — close a position, keep the stock on your watchlist\n"
    "/watch SYMBOL — track a stock with no position (screener candidates)\n"
    "/remove SYMBOL — stop tracking a stock entirely (position + watchlist)\n"
    "/positions — your open positions with live P&L\n"
    "/list — positions + watchlist, symbols only"
)


def _resolve_stock(query: str) -> tuple[Optional[str], str, bool]:
    """Resolve a bare US ticker (e.g. 'AAPL', 'BRK-B') to (SYMBOL, name, verified)
    via yfinance. There's no broker/company-name search here — type the exact
    ticker. `verified=False` means the symbol couldn't be confirmed to exist
    (network hiccup, or a genuine typo/delisted ticker) — callers should warn
    but still accept it so a transient lookup failure doesn't block logging a
    position. Returns (None, '', False) only when the input isn't ticker-shaped
    at all (empty, contains spaces, or absurdly long)."""
    up = query.strip().upper()
    if not up or " " in up or not (1 <= len(up) <= 10):
        return None, "", False
    try:
        import yfinance as yf

        info = yf.Ticker(up).info or {}
        name = (info.get("longName") or info.get("shortName") or "").strip()
        if name:
            return up, name, True
    except Exception:
        pass
    return up, "", False


def _positions_reply(store) -> str:
    rows = store.get_holdings()
    if not rows:
        return "No open positions yet. Log one with /add SYMBOL QTY PRICE"
    lines = []
    total_invested = total_value = 0.0
    for r in sorted(rows, key=lambda x: x["symbol"]):
        qty, avg, last = r["qty"], r["avg_price"], r["last_price"]
        invested, value = qty * avg, qty * last
        pnl_pct = (last - avg) / avg * 100 if avg else 0.0
        total_invested += invested
        total_value += value
        lines.append(f"{r['symbol']}: {qty:g} @ ${avg:,.2f} → ${last:,.2f} "
                     f"({pnl_pct:+.1f}%)")
    total_pnl = total_value - total_invested
    total_pct = (total_pnl / total_invested * 100) if total_invested else 0.0
    lines.append(f"\nTotal: ${total_value:,.2f} ({total_pnl:+,.2f}, {total_pct:+.1f}%)")
    return "\n".join(lines)


def handle_update(update: dict, store) -> Optional[str]:
    """Process one getUpdates entry; return reply text (or None to stay silent).

    Ignores anything not from the configured chat_id (basic access control).
    """
    msg = update.get("message") or update.get("edited_message") or {}
    chat = str((msg.get("chat") or {}).get("id", ""))
    if config.TELEGRAM_CHAT_ID and chat != str(config.TELEGRAM_CHAT_ID):
        return None
    cmd, arg = parse_command(msg.get("text", ""))
    if not cmd:
        return None

    if cmd in ("start", "help"):
        return _HELP

    if cmd == "add":
        parts = arg.split()
        if len(parts) != 3:
            return "Usage: /add SYMBOL QTY PRICE (e.g. /add AAPL 10 185.50)"
        sym_raw, qty_raw, price_raw = parts
        try:
            qty, price = float(qty_raw), float(price_raw)
        except ValueError:
            return "Qty and price must be numbers. Usage: /add SYMBOL QTY PRICE"
        if qty <= 0 or price <= 0:
            return "Qty and price must be positive."
        sym, name, verified = _resolve_stock(sym_raw)
        if not sym:
            return f"'{sym_raw}' doesn't look like a ticker. Usage: /add AAPL 10 185.50"
        store.upsert_position(sym, qty, price, name)
        label = f"{sym} ({name})" if name else sym
        reply = f"✅ Logged {qty:g} sh of {label} @ ${price:,.2f}."
        if not verified:
            reply += ("\n⚠️ Couldn't verify this ticker exists right now — "
                      "double-check it; /remove it if it was a typo.")
        return reply

    if cmd == "watch":
        if not arg:
            return "Usage: /watch SYMBOL"
        sym, name, verified = _resolve_stock(arg.split()[0])
        if not sym:
            return f"'{arg}' doesn't look like a ticker."
        store.add_watch(sym, name, kind="watch")
        label = f"{sym} ({name})" if name else sym
        reply = f"👁 Watching {label} (no position)."
        if not verified:
            reply += "\n⚠️ Couldn't verify this ticker exists right now."
        return reply

    if cmd == "sell":
        if not arg:
            return "Usage: /sell SYMBOL"
        sym = arg.split()[0].upper()
        ok = store.close_position(sym)
        return (f"Closed {sym} — kept on your watchlist for alerts/history."
                if ok else f"{sym} had no open position.")

    if cmd == "remove":
        if not arg:
            return "Usage: /remove SYMBOL"
        sym = arg.split()[0].upper()
        ok = store.remove_watch(sym)
        return f"Removed {sym} entirely." if ok else f"{sym} was not tracked."

    if cmd == "positions":
        return _positions_reply(store)

    if cmd == "list":
        hold = [w.symbol for w in store.list_watch("holding")]
        watch = [w.symbol for w in store.list_watch("watch")]
        return (f"Positions ({len(hold)}): {', '.join(hold) or '—'}\n"
                f"Watchlist ({len(watch)}): {', '.join(watch) or '—'}")

    return _HELP


# --------------------------------------------------------------------------- #
# I/O
# --------------------------------------------------------------------------- #
def send_message(text: str, chat_id: Optional[str] = None,
                 token: Optional[str] = None, disable_preview: bool = True) -> bool:
    """Send an HTML message. Returns True on success."""
    token = token or config.TELEGRAM_BOT_TOKEN
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(
            _API.format(token=token, method="sendMessage"),
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": disable_preview},
            timeout=config.HTTP_TIMEOUT,
        )
        return resp.ok
    except requests.RequestException:
        return False


def send_alert(alert: Alert) -> bool:
    return send_message(format_alert(alert))


def drain_commands(store, token: Optional[str] = None) -> int:
    """Fetch and process pending commands via getUpdates. Returns count handled.

    The offset is persisted so each update is processed once across cron runs.
    """
    token = token or config.TELEGRAM_BOT_TOKEN
    if not token:
        return 0
    offset = store.get_meta(_OFFSET_KEY)
    params = {"timeout": 0}
    if offset:
        params["offset"] = int(offset) + 1
    try:
        resp = requests.get(
            _API.format(token=token, method="getUpdates"),
            params=params, timeout=config.HTTP_TIMEOUT,
        )
        updates = resp.json().get("result", []) if resp.ok else []
    except (requests.RequestException, ValueError):
        return 0

    handled = 0
    last_id = None
    for upd in updates:
        last_id = upd.get("update_id", last_id)
        reply = handle_update(upd, store)
        if reply:
            send_message(reply, token=token)
            handled += 1
    if last_id is not None:
        store.set_meta(_OFFSET_KEY, str(last_id))
    return handled
