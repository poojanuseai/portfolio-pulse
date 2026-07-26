"""Fast poll (~every 10 min during US market hours): refresh position prices,
drain Telegram commands, and run whatever custom alert criteria have been
defined (see signals/criteria.py — empty by design until those are decided).

Idempotent by design: refreshing prices and draining commands are both safe
to repeat; criteria.scan() owns its own dedup if/when it needs one.
"""

from __future__ import annotations

from portfolio_pulse.notify import telegram
from portfolio_pulse.signals import criteria
from portfolio_pulse.store import get_store


def _refresh_prices(store) -> int:
    """Batch-refresh last_price for every open position via one yfinance call.
    Returns the number of symbols updated; best-effort (a failed fetch just
    leaves the previous last_price in place)."""
    symbols = [h["symbol"] for h in store.get_holdings()]
    if not symbols:
        return 0
    import yfinance as yf

    try:
        data = yf.download(symbols, period="1d", progress=False, group_by="ticker")
    except Exception:
        return 0

    updated = 0
    for sym in symbols:
        try:
            frame = data[sym] if len(symbols) > 1 else data
            close = float(frame["Close"].dropna().iloc[-1])
        except (KeyError, IndexError, ValueError):
            continue
        store.update_last_price(sym, close)
        updated += 1
    return updated


def run() -> dict:
    store = get_store()
    counts = {
        "prices_updated": _refresh_prices(store),
        "commands": telegram.drain_commands(store),
        "alerts": 0,
    }
    for alert in criteria.scan(store):
        alert.id = store.record_alert(alert)
        if telegram.send_alert(alert):
            store.mark_delivered(alert.id)
        counts["alerts"] += 1
    return counts


if __name__ == "__main__":
    print(run())
