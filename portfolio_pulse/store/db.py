"""Shared state store behind a small repository API.

Two backends satisfy the same `Store` interface:
  * SQLiteStore  — default; zero-setup, offline, used for local dev + verification.
  * SupabaseStore — hosted Postgres for production, where the GitHub Actions
                   poller and the Streamlit Cloud dashboard run on different
                   hosts and must share one DB.

Design choices:
  * Positions are logged BY HAND (no broker) — `upsert_position` replaces a
    symbol's qty/avg_price outright (you tell it your current position; it
    doesn't try to weighted-average partial fills for you).
  * `close_position` demotes a symbol from "holding" to "watch" rather than
    forgetting it — selling out of a position doesn't mean you stop caring
    about the stock's alerts.
  * Timestamps are stored as ISO-8601 UTC strings for portability across backends.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol

from portfolio_pulse import config


# --------------------------------------------------------------------------- #
# Row types (lightweight, backend-agnostic)
# --------------------------------------------------------------------------- #
@dataclass
class WatchItem:
    symbol: str
    name: str
    kind: str  # "holding" | "watch"
    added_at: str


@dataclass
class Forecast:
    id: Optional[int]
    symbol: str
    execution_date: str  # the day the forecast batch was run (kronos-check's "Execution Date")
    target_date: str     # the day being predicted for
    last_close: float
    predicted_close: float
    return_pct: float
    confidence: float
    created_at: str


@dataclass
class Alert:
    id: Optional[int]
    symbol: str
    alert_type: str  # e.g. "signal" — the specific taxonomy is defined by
                      # whatever fills in signals/criteria.py
    title: str
    summary: str
    impact: str
    source_url: str
    source_type: str
    qc_status: str
    created_at: str
    delivered: bool


def _iso(dt: datetime | None = None) -> str:
    return (dt or config.utc_now()).isoformat()


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class Store(Protocol):
    # watchlist / positions
    def add_watch(self, symbol: str, name: str = "", kind: str = "watch") -> bool: ...
    def remove_watch(self, symbol: str) -> bool: ...
    def list_watch(self, kind: Optional[str] = None) -> list[WatchItem]: ...
    def all_symbols(self) -> list[str]: ...
    def upsert_position(self, symbol: str, qty: float, avg_price: float,
                        name: str = "") -> None: ...
    def close_position(self, symbol: str) -> bool: ...
    def update_last_price(self, symbol: str, last_price: float) -> None: ...
    def get_holdings(self) -> list[dict[str, Any]]: ...

    # alerts
    def record_alert(self, alert: Alert) -> int: ...
    def mark_delivered(self, alert_id: int) -> None: ...
    def list_alerts(self, limit: int = 50, symbol: Optional[str] = None) -> list[Alert]: ...

    # forecasts (kronos-check TP estimates, imported by jobs/import_forecasts.py)
    def record_forecast(self, symbol: str, execution_date: str, target_date: str,
                        last_close: float, predicted_close: float,
                        return_pct: float, confidence: float) -> None: ...
    def list_forecasts(self, limit: int = 200) -> list[Forecast]: ...

    # generic key-value (e.g. Telegram update offset)
    def get_meta(self, key: str) -> Optional[str]: ...
    def set_meta(self, key: str, value: str) -> None: ...


# --------------------------------------------------------------------------- #
# SQLite backend
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'watch',
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS holdings_snapshot (
    symbol      TEXT PRIMARY KEY,
    qty         REAL NOT NULL DEFAULT 0,
    avg_price   REAL NOT NULL DEFAULT 0,
    last_price  REAL NOT NULL DEFAULT 0,
    synced_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    alert_type  TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    impact      TEXT NOT NULL DEFAULT '',
    source_url  TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '',
    qc_status   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    delivered   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS forecasts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL,
    execution_date   TEXT NOT NULL,
    target_date      TEXT NOT NULL,
    last_close       REAL NOT NULL,
    predicted_close  REAL NOT NULL,
    return_pct       REAL NOT NULL,
    confidence       REAL NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE(symbol, execution_date)
);
CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);
CREATE INDEX IF NOT EXISTS idx_forecasts_execdate ON forecasts(execution_date);
"""


class SQLiteStore:
    """File-backed store. Safe for the single-writer poller + read-only dashboard."""

    def __init__(self, path: str | None = None):
        self.path = path or config.SQLITE_PATH
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # -- watchlist / positions -------------------------------------------------
    def add_watch(self, symbol: str, name: str = "", kind: str = "watch") -> bool:
        symbol = symbol.strip().upper()
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO watchlist(symbol, name, kind, added_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       name = CASE WHEN excluded.name != '' THEN excluded.name
                                   ELSE watchlist.name END,
                       kind = excluded.kind""",
                (symbol, name, kind, _iso()),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def remove_watch(self, symbol: str) -> bool:
        """Fully untrack a symbol — removes it from the watchlist AND clears any
        open position on it. Use `close_position` instead if you just sold out
        but still want alerts/history for the stock."""
        symbol = symbol.strip().upper()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM holdings_snapshot WHERE symbol = ?", (symbol,))
            cur = conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

    def list_watch(self, kind: Optional[str] = None) -> list[WatchItem]:
        conn = self._connect()
        try:
            if kind:
                rows = conn.execute(
                    "SELECT * FROM watchlist WHERE kind = ? ORDER BY symbol", (kind,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM watchlist ORDER BY symbol").fetchall()
            return [WatchItem(r["symbol"], r["name"], r["kind"], r["added_at"]) for r in rows]
        finally:
            conn.close()

    def all_symbols(self) -> list[str]:
        return [w.symbol for w in self.list_watch()]

    def upsert_position(self, symbol: str, qty: float, avg_price: float,
                        name: str = "") -> None:
        """Log/replace a manually-entered position. Not a weighted-average merge
        — the caller states their current qty/avg_price outright (e.g. after
        topping up, average it yourself first). Ensures the symbol is tracked
        as kind='holding'. `last_price` is only initialized here (to avg_price)
        if the position is new; an existing row's last_price is left for the
        price-refresh job to keep current."""
        symbol = symbol.strip().upper()
        conn = self._connect()
        try:
            existing = conn.execute(
                "SELECT last_price FROM holdings_snapshot WHERE symbol = ?", (symbol,)
            ).fetchone()
            last_price = existing["last_price"] if existing else avg_price
            conn.execute(
                """INSERT INTO holdings_snapshot(symbol, qty, avg_price, last_price, synced_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       qty=excluded.qty, avg_price=excluded.avg_price,
                       synced_at=excluded.synced_at""",
                (symbol, qty, avg_price, last_price, _iso()),
            )
            conn.execute(
                """INSERT INTO watchlist(symbol, name, kind, added_at)
                   VALUES (?, ?, 'holding', ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       kind = 'holding',
                       name = CASE WHEN excluded.name != '' THEN excluded.name
                                   ELSE watchlist.name END""",
                (symbol, name, _iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def close_position(self, symbol: str) -> bool:
        """Clear an open position (e.g. you sold) but keep the symbol tracked
        as a plain watch item — history/alerts for it aren't lost."""
        symbol = symbol.strip().upper()
        conn = self._connect()
        try:
            cur = conn.execute("DELETE FROM holdings_snapshot WHERE symbol = ?", (symbol,))
            had_position = cur.rowcount > 0
            if had_position:
                conn.execute(
                    "UPDATE watchlist SET kind = 'watch' WHERE symbol = ?", (symbol,)
                )
            conn.commit()
            return had_position
        finally:
            conn.close()

    def update_last_price(self, symbol: str, last_price: float) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE holdings_snapshot SET last_price = ? WHERE symbol = ?",
                (last_price, symbol.strip().upper()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_holdings(self) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM holdings_snapshot ORDER BY symbol"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -- alerts ---------------------------------------------------------------
    def record_alert(self, alert: Alert) -> int:
        conn = self._connect()
        try:
            cur = conn.execute(
                """INSERT INTO alerts(symbol, alert_type, title, summary, impact,
                                      source_url, source_type, qc_status, created_at, delivered)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (alert.symbol, alert.alert_type, alert.title, alert.summary,
                 alert.impact, alert.source_url, alert.source_type, alert.qc_status,
                 alert.created_at or _iso(), int(alert.delivered)),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    def mark_delivered(self, alert_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE alerts SET delivered = 1 WHERE id = ?", (alert_id,))
            conn.commit()
        finally:
            conn.close()

    def list_alerts(self, limit: int = 50, symbol: Optional[str] = None) -> list[Alert]:
        conn = self._connect()
        try:
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM alerts WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                    (symbol.strip().upper(), limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return [
                Alert(r["id"], r["symbol"], r["alert_type"], r["title"], r["summary"],
                      r["impact"], r["source_url"], r["source_type"], r["qc_status"],
                      r["created_at"], bool(r["delivered"]))
                for r in rows
            ]
        finally:
            conn.close()

    # -- forecasts --------------------------------------------------------------
    def record_forecast(self, symbol: str, execution_date: str, target_date: str,
                        last_close: float, predicted_close: float,
                        return_pct: float, confidence: float) -> None:
        """Upsert on (symbol, execution_date) so re-importing the same day's
        kronos-check CSV doesn't create duplicate rows."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO forecasts(symbol, execution_date, target_date, last_close,
                                         predicted_close, return_pct, confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol, execution_date) DO UPDATE SET
                       target_date=excluded.target_date, last_close=excluded.last_close,
                       predicted_close=excluded.predicted_close, return_pct=excluded.return_pct,
                       confidence=excluded.confidence, created_at=excluded.created_at""",
                (symbol.strip().upper(), execution_date, target_date, last_close,
                 predicted_close, return_pct, confidence, _iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def list_forecasts(self, limit: int = 200) -> list[Forecast]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT * FROM forecasts ORDER BY execution_date DESC, return_pct DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [
                Forecast(r["id"], r["symbol"], r["execution_date"], r["target_date"],
                         r["last_close"], r["predicted_close"], r["return_pct"],
                         r["confidence"], r["created_at"])
                for r in rows
            ]
        finally:
            conn.close()

    # -- meta key-value -------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    def set_meta(self, key: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO meta(key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
_INSTANCE: Store | None = None


def get_store() -> Store:
    """Return the process-wide store for the configured backend."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    if config.STORE_BACKEND == "supabase":
        from portfolio_pulse.store.supabase_store import SupabaseStore
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise RuntimeError(
                "PP_STORE_BACKEND=supabase but SUPABASE_URL/SUPABASE_KEY are unset."
            )
        _INSTANCE = SupabaseStore()
        return _INSTANCE
    _INSTANCE = SQLiteStore()
    return _INSTANCE
