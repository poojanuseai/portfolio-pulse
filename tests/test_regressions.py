"""Regression suite for the US, no-broker, manual-position build. Runs in CI
on every push (tests.yml). Network-free: the one yfinance-touching path
(_resolve_stock's ticker lookup) is monkeypatched in TestTelegramCommands so
results don't depend on connectivity or live market data; the format-guard
tests below exercise the real function on inputs that never reach yfinance.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PP_SQLITE_PATH", "/tmp/pp_test_regress.db")

import pytest

from portfolio_pulse.notify import telegram
from portfolio_pulse.store.db import SQLiteStore


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(str(tmp_path / "t.db"))


def _msg(text, chat_id=1):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


class TestPositions:
    def test_upsert_then_read(self, store):
        store.upsert_position("AAPL", 10, 185.50)
        rows = store.get_holdings()
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"
        assert rows[0]["qty"] == 10
        assert rows[0]["avg_price"] == 185.50
        assert rows[0]["last_price"] == 185.50  # initialized to avg_price
        kinds = {w.symbol: w.kind for w in store.list_watch()}
        assert kinds["AAPL"] == "holding"

    def test_upsert_replaces_not_averages(self, store):
        # Manual re-entry restates the position outright — it is not a
        # weighted-average merge like the old broker sync was.
        store.upsert_position("AAPL", 10, 100)
        store.update_last_price("AAPL", 150)
        store.upsert_position("AAPL", 15, 120)
        row = store.get_holdings()[0]
        assert row["qty"] == 15 and row["avg_price"] == 120
        assert row["last_price"] == 150  # untouched by the re-add

    def test_close_position_demotes_to_watch(self, store):
        store.upsert_position("AAPL", 10, 100)
        assert store.close_position("AAPL") is True
        assert store.get_holdings() == []
        kinds = {w.symbol: w.kind for w in store.list_watch()}
        assert kinds["AAPL"] == "watch"  # still tracked, just no position

    def test_close_position_with_no_position_returns_false(self, store):
        store.add_watch("MSFT", kind="watch")
        assert store.close_position("MSFT") is False
        kinds = {w.symbol: w.kind for w in store.list_watch()}
        assert kinds["MSFT"] == "watch"  # unaffected

    def test_remove_watch_fully_untracks(self, store):
        store.upsert_position("AAPL", 10, 100)
        assert store.remove_watch("AAPL") is True
        assert store.get_holdings() == []
        assert store.list_watch() == []

    def test_update_last_price_only_touches_price(self, store):
        store.upsert_position("AAPL", 10, 100)
        store.update_last_price("AAPL", 123.45)
        row = store.get_holdings()[0]
        assert row["last_price"] == 123.45
        assert row["qty"] == 10 and row["avg_price"] == 100


class TestTelegramCommands:
    @pytest.fixture(autouse=True)
    def _stub_resolve(self, monkeypatch):
        # No network: any ticker-shaped, non-empty query resolves as verified
        # with no company name, so reply-text assertions stay simple.
        monkeypatch.setattr(
            telegram, "_resolve_stock",
            lambda q: (q.strip().upper(), "", True) if q.strip() else (None, "", False))

    def test_add_logs_position(self, store):
        reply = telegram.handle_update(_msg("/add AAPL 10 185.50"), store)
        assert "Logged 10" in reply
        assert store.get_holdings()[0]["symbol"] == "AAPL"

    def test_add_rejects_wrong_arg_count(self, store):
        reply = telegram.handle_update(_msg("/add AAPL 10"), store)
        assert "Usage" in reply
        assert store.get_holdings() == []

    def test_add_rejects_non_numeric_qty(self, store):
        reply = telegram.handle_update(_msg("/add AAPL ten 185.50"), store)
        assert "numbers" in reply

    def test_add_rejects_non_positive_values(self, store):
        reply = telegram.handle_update(_msg("/add AAPL 0 185.50"), store)
        assert "positive" in reply

    def test_watch_tracks_without_position(self, store):
        reply = telegram.handle_update(_msg("/watch MSFT"), store)
        assert "Watching" in reply
        assert store.get_holdings() == []
        assert store.list_watch("watch")[0].symbol == "MSFT"

    def test_sell_closes_position(self, store):
        store.upsert_position("AAPL", 10, 100)
        reply = telegram.handle_update(_msg("/sell AAPL"), store)
        assert "Closed AAPL" in reply
        assert store.get_holdings() == []

    def test_sell_with_no_position(self, store):
        reply = telegram.handle_update(_msg("/sell AAPL"), store)
        assert "no open position" in reply

    def test_remove_fully_untracks(self, store):
        store.upsert_position("AAPL", 10, 100)
        reply = telegram.handle_update(_msg("/remove AAPL"), store)
        assert "Removed AAPL" in reply
        assert store.list_watch() == []

    def test_positions_shows_pnl(self, store):
        store.upsert_position("AAPL", 10, 100)
        store.update_last_price("AAPL", 150)
        reply = telegram.handle_update(_msg("/positions"), store)
        assert "AAPL" in reply
        assert "+50.0%" in reply
        assert "Total" in reply

    def test_positions_empty(self, store):
        reply = telegram.handle_update(_msg("/positions"), store)
        assert "No open positions" in reply

    def test_list_shows_both_kinds(self, store):
        store.upsert_position("AAPL", 10, 100)
        store.add_watch("MSFT", kind="watch")
        reply = telegram.handle_update(_msg("/list"), store)
        assert "AAPL" in reply and "MSFT" in reply

    def test_unknown_chat_id_ignored(self, store, monkeypatch):
        monkeypatch.setattr(telegram.config, "TELEGRAM_CHAT_ID", "999")
        assert telegram.handle_update(_msg("/help", chat_id=1), store) is None

    def test_help_and_unknown_text(self, store):
        assert "commands" in telegram.handle_update(_msg("/help"), store).lower()
        assert telegram.handle_update(_msg("hello there"), store) is None


class TestParseCommand:
    def test_splits_command_and_arg(self):
        assert telegram.parse_command("/add AAPL 10 185.50") == ("add", "AAPL 10 185.50")

    def test_strips_bot_mention(self):
        assert telegram.parse_command("/add@MyBot AAPL 10 185.50") == ("add", "AAPL 10 185.50")

    def test_non_command_returns_empty(self):
        assert telegram.parse_command("just chatting") == ("", "")


class TestResolveStockFormatGuard:
    """The real _resolve_stock, on inputs that fail its shape check before any
    yfinance call is attempted — genuinely network-free."""

    def test_rejects_empty(self):
        assert telegram._resolve_stock("") == (None, "", False)

    def test_rejects_multi_word_query(self):
        assert telegram._resolve_stock("tata motors") == (None, "", False)

    def test_rejects_absurdly_long_query(self):
        assert telegram._resolve_stock("A" * 11) == (None, "", False)
