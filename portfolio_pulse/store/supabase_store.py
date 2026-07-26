"""Supabase (hosted Postgres) backend — the production store.

Implements the exact same `Store` interface as SQLiteStore, over PostgREST via
supabase-py, so the GitHub Actions poller and the Streamlit Cloud dashboard
share one database. Run migrations/supabase_schema.sql once before first use.

Only credential-bearing hosts instantiate this; local development stays on SQLite.
"""

from __future__ import annotations

from typing import Any, Optional

from portfolio_pulse import config
from portfolio_pulse.store.db import Alert, WatchItem, _iso


class SupabaseStore:
    def __init__(self, url: Optional[str] = None, key: Optional[str] = None):
        from supabase import create_client
        self.client = create_client(url or config.SUPABASE_URL,
                                    key or config.SUPABASE_KEY)

    def _t(self, name: str):
        return self.client.table(name)

    # -- watchlist / positions -------------------------------------------------
    def add_watch(self, symbol: str, name: str = "", kind: str = "watch") -> bool:
        symbol = symbol.strip().upper()
        row = {"symbol": symbol, "kind": kind, "added_at": _iso()}
        if name:
            row["name"] = name
        self._t("watchlist").upsert(row, on_conflict="symbol").execute()
        return True

    def remove_watch(self, symbol: str) -> bool:
        """Fully untrack a symbol — clears any open position too. Use
        `close_position` instead if you just sold but want to keep the symbol."""
        symbol = symbol.strip().upper()
        self._t("holdings_snapshot").delete().eq("symbol", symbol).execute()
        res = self._t("watchlist").delete().eq("symbol", symbol).execute()
        return bool(res.data)

    def list_watch(self, kind: Optional[str] = None) -> list[WatchItem]:
        q = self._t("watchlist").select("*").order("symbol")
        if kind:
            q = q.eq("kind", kind)
        rows = q.execute().data or []
        return [WatchItem(r["symbol"], r.get("name", ""), r["kind"], r["added_at"])
                for r in rows]

    def all_symbols(self) -> list[str]:
        rows = self._t("watchlist").select("symbol").execute().data or []
        return [r["symbol"] for r in rows]

    def upsert_position(self, symbol: str, qty: float, avg_price: float,
                        name: str = "") -> None:
        symbol = symbol.strip().upper()
        existing = self._t("holdings_snapshot").select("last_price").eq(
            "symbol", symbol).limit(1).execute().data
        last_price = existing[0]["last_price"] if existing else avg_price
        self._t("holdings_snapshot").upsert({
            "symbol": symbol, "qty": float(qty), "avg_price": float(avg_price),
            "last_price": float(last_price), "synced_at": _iso(),
        }, on_conflict="symbol").execute()
        current_name = {w.symbol: w.name for w in self.list_watch()}.get(symbol, "")
        self._t("watchlist").upsert({
            "symbol": symbol, "name": name or current_name, "kind": "holding",
            "added_at": _iso(),
        }, on_conflict="symbol").execute()

    def close_position(self, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        res = self._t("holdings_snapshot").delete().eq("symbol", symbol).execute()
        had_position = bool(res.data)
        if had_position:
            self._t("watchlist").update({"kind": "watch"}).eq(
                "symbol", symbol).execute()
        return had_position

    def update_last_price(self, symbol: str, last_price: float) -> None:
        self._t("holdings_snapshot").update({"last_price": float(last_price)}).eq(
            "symbol", symbol.strip().upper()).execute()

    def get_holdings(self) -> list[dict[str, Any]]:
        return self._t("holdings_snapshot").select("*").order("symbol").execute().data or []

    # -- alerts ---------------------------------------------------------------
    def record_alert(self, alert: Alert) -> int:
        res = self._t("alerts").insert({
            "symbol": alert.symbol, "alert_type": alert.alert_type,
            "title": alert.title, "summary": alert.summary, "impact": alert.impact,
            "source_url": alert.source_url, "source_type": alert.source_type,
            "qc_status": alert.qc_status, "created_at": alert.created_at or _iso(),
            "delivered": alert.delivered,
        }).execute()
        return int(res.data[0]["id"])

    def mark_delivered(self, alert_id: int) -> None:
        self._t("alerts").update({"delivered": True}).eq("id", alert_id).execute()

    def list_alerts(self, limit: int = 50, symbol: Optional[str] = None) -> list[Alert]:
        q = self._t("alerts").select("*").order("id", desc=True).limit(limit)
        if symbol:
            q = q.eq("symbol", symbol.strip().upper())
        rows = q.execute().data or []
        return [
            Alert(r["id"], r["symbol"], r["alert_type"], r["title"], r["summary"],
                  r["impact"], r["source_url"], r["source_type"], r["qc_status"],
                  r["created_at"], bool(r["delivered"]))
            for r in rows
        ]

    # -- meta -----------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        res = self._t("meta").select("value").eq("key", key).limit(1).execute()
        return res.data[0]["value"] if res.data else None

    def set_meta(self, key: str, value: str) -> None:
        self._t("meta").upsert({"key": key, "value": value},
                              on_conflict="key").execute()
