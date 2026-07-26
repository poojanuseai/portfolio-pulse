"""Central configuration: thresholds, US/ET market calendar, env plumbing.

Everything tunable lives here so the rest of the code reads cleanly. Secrets come
from environment variables (never hard-coded); see .env.example for the full list.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

# Load the project-root .env (if present) BEFORE any os.environ reads below, so
# locally-run jobs and the dashboard pick up credentials without manual exports.
# Real environment variables still win over .env values (override=False default).
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:  # pragma: no cover — python-dotenv is in requirements.txt
    pass

# --------------------------------------------------------------------------- #
# Time / market calendar (all trading logic is in US Eastern Time)
# --------------------------------------------------------------------------- #
ET = ZoneInfo("America/New_York")

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# NYSE/Nasdaq full-day holidays. Keep this current each year.
US_MARKET_HOLIDAYS_2026: set[date] = {
    date(2026, 1, 1),    # New Year's Day
    date(2026, 1, 19),   # Martin Luther King Jr. Day
    date(2026, 2, 16),   # Washington's Birthday
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}


def now_et() -> datetime:
    """Timezone-aware current time in US Eastern Time."""
    return datetime.now(ET)


def is_trading_day(d: date | None = None) -> bool:
    """True if `d` (default today, ET) is a weekday and not a US market holiday."""
    d = d or now_et().date()
    return d.weekday() < 5 and d not in US_MARKET_HOLIDAYS_2026


def is_market_hours(dt: datetime | None = None) -> bool:
    """True during the NYSE/Nasdaq cash session on a trading day."""
    dt = dt or now_et()
    if not is_trading_day(dt.date()):
        return False
    return MARKET_OPEN <= dt.timetz().replace(tzinfo=None) <= MARKET_CLOSE


# --------------------------------------------------------------------------- #
# HTTP defaults (Telegram API calls; yfinance manages its own requests)
# --------------------------------------------------------------------------- #
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
HTTP_TIMEOUT = 20  # seconds

# --------------------------------------------------------------------------- #
# Storage backend selection
#   PP_STORE_BACKEND = "sqlite" (default, local/offline) | "supabase" (prod)
# --------------------------------------------------------------------------- #
STORE_BACKEND = os.environ.get("PP_STORE_BACKEND", "sqlite").lower()
SQLITE_PATH = os.environ.get(
    "PP_SQLITE_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "pulse.db"),
)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# --------------------------------------------------------------------------- #
# Secrets (read lazily by the modules that need them; empty is tolerated so the
# offline pieces run without every credential present)
# --------------------------------------------------------------------------- #
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def utc_now() -> datetime:
    """Timezone-aware UTC now (used for stored timestamps)."""
    return datetime.now(timezone.utc)
