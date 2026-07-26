# Portfolio Pulse

A 24/7 personal tracker for a **manually-logged US equities portfolio**. No
broker connection — you log your own positions (ticker, quantity, average
cost) via Telegram or the dashboard. It refreshes live prices, shows P&L on a
**Streamlit dashboard**, and pushes alerts to **Telegram** whenever custom
screener-driven criteria (not built yet — see below) fire.

> **Not investment advice.** This is a personal software tool for tracking
> positions you choose and computing plain P&L/price facts about them. It
> makes no recommendations and never executes trades.

## What's here vs. what's next

This build deliberately does **not** include a broker connection, filings/news
monitoring, or a moving-average-crossover signal — those were specific to the
original NSE/Zerodha version this was forked from. What's here now:

- **Manual position logging** — `/add SYMBOL QTY PRICE` in Telegram, or the
  dashboard's Watchlist tab. No broker OAuth, no API keys beyond Telegram/Supabase.
- **Live price refresh** — every ~10 minutes during US market hours, via yfinance.
- **A dashboard** (Portfolio P&L, Stock History, Alert Feed, Watchlist) reading
  the same database the Telegram bot writes to.
- **An empty, obvious extension point** (`portfolio_pulse/signals/criteria.py`)
  for whatever custom alert rules get defined later — e.g. wired to a separate
  screener's composite score, RRG quadrant, or trend-filter signal. Until that's
  designed, the Alert Feed stays empty; nothing false-positives in the meantime.

## Run your own copy — free

Everything runs on free tiers; the total infrastructure cost is $0/month. Your
portfolio data stays entirely in YOUR Supabase project — nothing is shared
with anyone, including the tool's author.

1. **Fork this repo** (public fork keeps GitHub Actions free & unlimited), then
   in your fork open the **Actions** tab and click **"Enable workflows"**.
2. Follow **[SETUP_GUIDE.md](SETUP_GUIDE.md)** top to bottom: Telegram bot →
   Supabase database → GitHub secrets → (optional) Streamlit Cloud dashboard.
   Wherever an instruction shows a repo URL/path, substitute your own username.
   Exactly **4 secrets** are needed: `SUPABASE_URL`, `SUPABASE_KEY`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. In Telegram, send `/add AAPL 10 185.50` (ticker, quantity, average cost) for
   each position, or `/watch MSFT` to track a stock with no position.

Licensed under the [MIT License](LICENSE) — free to use, modify, and share.

## Architecture
```
GitHub Actions (cron, ~10 min during US market hours)     Streamlit Cloud
 └ heartbeat → fast_poll: refresh prices, drain Telegram,  └ dashboard/app.py
   run signals/criteria.scan() (empty until defined)          (reads + logs
                        │                                       positions)
                        ▼
                 Supabase (Postgres)  ◄─────────────────────────────┘
                        ▲
                   yfinance (US ticker daily/latest close)
```
- **Positions**: logged by hand via Telegram (`/add /sell /watch /remove`) or
  the dashboard's Watchlist tab — no broker API, no OAuth.
- **Prices**: yfinance, refreshed on every poll for whatever's in your
  positions/watchlist.
- **Alerts**: none yet — `signals/criteria.py` is an intentionally empty hook;
  the Alert Feed and Stock History tabs will populate once criteria are wired in.
- **Store**: SQLite locally, Supabase in production (shared by the GitHub
  Actions poller and the Streamlit Cloud dashboard, which run on different hosts).

## Module map
| Path | Responsibility |
|---|---|
| `config.py` | Thresholds, US/ET market calendar, env plumbing |
| `store/db.py` · `store/supabase_store.py` | Repository API (SQLite / Supabase) |
| `notify/telegram.py` | Push + `/add /sell /watch /remove /positions /list` |
| `signals/criteria.py` | Empty extension point for future custom alert rules |
| `jobs/fast_poll.py` · `jobs/heartbeat.py` | Price refresh + command drain, run every tick |
| `jobs/setup_check.py` | The "did I do it right?" verification job |
| `jobs/migrate_to_supabase.py` | One-time local-SQLite → Supabase copy |
| `dashboard/app.py` | Streamlit dashboard |

## Quick start (local, offline-friendly)
```bash
cd portfolio-pulse
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # fill in what you have; SQLite needs nothing

# run the dashboard (SQLite backend by default)
streamlit run portfolio_pulse/dashboard/app.py

# run a poll once (price refresh + drain any pending Telegram commands)
python -m portfolio_pulse.jobs.fast_poll
```
Price refresh and the dashboard run without any credentials at all (SQLite,
no Telegram). Telegram commands activate once `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` are set. See [SETUP_GUIDE.md](SETUP_GUIDE.md) for the full path.

## Hosting & cost
- **Poller**: GitHub Actions cron (free). Use a **public** repo for unlimited
  Actions minutes (secrets live in GitHub Secrets, never in code); a private
  repo can exceed the 2,000 free min/month at `*/10` — widen to `*/15` or go
  public. Cron can lag a few minutes and won't fire second-precise — fine for
  a position tracker, not intraday ticks (out of scope).
- **Store**: Supabase free tier. **Dashboard**: Streamlit Community Cloud (free).
- **APIs**: yfinance and the Telegram Bot API are both free.

## Known limits
- No broker sync — every position is entered by hand, and stays exactly as
  entered until you `/add` it again or `/sell`/`/remove` it.
- No alert criteria are defined yet (`signals/criteria.py` returns `[]`) — the
  Telegram bot and dashboard are fully functional for tracking, but nothing
  pushes a proactive alert until that's built.
- yfinance data can occasionally misprint or lag; there's no second-source
  cross-check (the original NSE/Kite version had one, specific to that broker).
