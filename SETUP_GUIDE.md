# Setup Guide — Portfolio Pulse

You can run everything locally with just Python (SQLite). Cloud + Telegram
require a few free accounts. Do them in this order; each step unlocks more of
the system and is independently testable.

## 0. Local install (5 min)
```bash
cd portfolio-pulse
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
streamlit run portfolio_pulse/dashboard/app.py   # opens the dashboard
```
The dashboard runs on SQLite with no credentials. Log a position under
**Watchlist** (symbol, quantity, average cost), then
`python -m portfolio_pulse.jobs.fast_poll` to refresh its live price.

## 1. Telegram (10 min) — log positions and get alerts on your phone
1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the
   **bot token**.
2. Message **@userinfobot** to get your numeric **chat id**.
3. Put both in `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
4. Test: `python -c "from portfolio_pulse.notify.telegram import send_message; send_message('Pulse test ✅')"`
5. Commands work once the poller runs (or after `fast_poll` once locally):
   `/add AAPL 10 185.50`, `/watch MSFT`, `/positions`, `/list`, `/sell AAPL`,
   `/remove AAPL`, `/help`.

## 2. Supabase (15 min) — shared cloud store for 24/7 operation
1. Create a free project at **supabase.com**.
2. In the SQL editor, paste and run **`migrations/supabase_schema.sql`**.
3. Copy the **Project URL** and the **service_role key** (Settings → API).
4. Set in `.env`: `PP_STORE_BACKEND=supabase`, `SUPABASE_URL`, `SUPABASE_KEY`.
5. Test: `python -m portfolio_pulse.jobs.fast_poll` should write to Supabase
   (log a position first with `/add`, or via the dashboard's Watchlist tab).

## 3. GitHub Actions (15 min) — the always-on poller
1. Push this repo to GitHub. **Use a public repo** for unlimited Actions minutes
   (all secrets live in GitHub Secrets, never in code).
2. Settings → Secrets and variables → Actions → add exactly 4 secrets:
   `SUPABASE_URL`, `SUPABASE_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. The workflows in `.github/workflows/` run on schedule. Trigger `setup-check`
   manually first via **Actions → setup-check → Run workflow** to confirm
   everything's wired up — it messages your Telegram bot on success and starts
   the always-on poller for you.
4. Watch a run's logs; check Supabase's `alerts` table and your Telegram.

## 4. Streamlit Community Cloud (10 min) — hosted dashboard
1. At **share.streamlit.io**, deploy `portfolio_pulse/dashboard/app.py` from your repo.
2. In the app's **Secrets**, add the same 4 keys as step 3 (TOML form:
   `SUPABASE_URL = "..."`), plus `PP_STORE_BACKEND = "supabase"` and, if you
   want the dashboard password-protected, `DASHBOARD_PASSWORD = "..."`.

## Verifying it end-to-end
- **Logging a position**: `/add AAPL 10 185.50` in Telegram → `/positions`
  should show it immediately (P&L computed off the last-refreshed price).
- **Price refresh**: run `python -m portfolio_pulse.jobs.fast_poll` (or wait
  for the next cron tick) → the dashboard's Portfolio tab's "Last $" column
  and "Prices last refreshed" caption should update.
- **Dashboard**: positions, P&L, and (once defined) the alert feed all reflect
  the same Supabase store the Telegram bot writes to.
- **Alerts**: none fire yet — `signals/criteria.py` is an empty extension
  point until custom alert rules are designed and wired in.
