"""One-time migration: copy the local SQLite state into Supabase.

Run AFTER creating the Supabase project and running migrations/supabase_schema.sql,
with SUPABASE_URL + SUPABASE_KEY filled in .env:

    python -m portfolio_pulse.jobs.migrate_to_supabase

Copies: watchlist (positions + watch), the positions snapshot, alert history,
and the Telegram update offset. Idempotent — safe to re-run.
"""

from __future__ import annotations

from portfolio_pulse import config
from portfolio_pulse.store.db import Alert, SQLiteStore
from portfolio_pulse.store.supabase_store import SupabaseStore


def run() -> dict:
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        return {"error": "SUPABASE_URL / SUPABASE_KEY not set in .env"}
    src = SQLiteStore()
    dst = SupabaseStore()
    counts: dict[str, int] = {}

    for w in src.list_watch():
        dst.add_watch(w.symbol, w.name, w.kind)
    counts["watchlist"] = len(src.list_watch())

    holdings = src.get_holdings()
    for h in holdings:
        dst.upsert_position(h["symbol"], h["qty"], h["avg_price"])
        dst.update_last_price(h["symbol"], h["last_price"])
    counts["positions"] = len(holdings)

    conn = src._connect()
    try:
        alerts = conn.execute("SELECT * FROM alerts ORDER BY id").fetchall()
    finally:
        conn.close()
    for r in alerts:
        dst.record_alert(Alert(None, r["symbol"], r["alert_type"], r["title"],
                               r["summary"], r["impact"], r["source_url"],
                               r["source_type"], r["qc_status"], r["created_at"],
                               bool(r["delivered"])))
    counts["alerts"] = len(alerts)

    offset = src.get_meta("telegram_update_offset")
    if offset:
        dst.set_meta("telegram_update_offset", offset)

    return counts


if __name__ == "__main__":
    print(run())
