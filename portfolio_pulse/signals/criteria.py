"""Extension point: custom screener-driven alert rules — not designed yet.

This is deliberately empty. The intent is to wire this up against the
US-Market-Move-Screener project's own signals (composite rotation_score, RRG
quadrant, trend filter, etc.) once the actual alert criteria are decided —
e.g. "alert when a held stock's rotation_score crosses below 40" or "alert on
an RRG quadrant flip." Until then, `scan()` returning `[]` means no alerts fire.

Whatever criteria land here should build `store.db.Alert` objects and persist
them the same way any alert is recorded (`store.record_alert` +
`notify.telegram.send_alert`) — see jobs/fast_poll.py for where this is called
and how a returned Alert would be delivered.
"""

from __future__ import annotations

from portfolio_pulse.store.db import Alert


def scan(store) -> list[Alert]:
    """Evaluate custom alert criteria against tracked positions/watchlist.
    Returns [] until criteria are defined."""
    return []
