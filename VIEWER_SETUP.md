# Set up Portfolio Pulse — no coding, no terminal, just clicks

Get free 24/7 position tracking on Telegram and a live dashboard for your US
stocks — no broker connection, you log positions by hand. Total cost:
**$0/month**. Time: **~20 minutes**, all in your browser and phone.

You'll create 3 free accounts (GitHub, Supabase, Telegram bot) — think of them
as: the engine, the memory, and the messenger. Your portfolio data stays
entirely in YOUR accounts. Nobody else — including the maker of this tool —
can see it.

> Not investment advice. This tool tracks positions you choose and computes
> plain P&L/price facts about them.

---

## Step 1 — Get your own copy of the engine (5 min)

1. Create a free account at **github.com** (just email + password)
2. Open this project's page → click **Fork** (top right) → **Create fork**.
   You now own a copy of the entire system.
3. In YOUR fork, click the **Actions** tab → press the green
   **"I understand my workflows, go ahead and enable them"** button.

## Step 2 — Create the memory (5 min)

1. Sign up free at **supabase.com** → **New project**
   (any name; any region; set any strong password and forget it)
2. Left sidebar → **SQL Editor** → open the file `migrations/supabase_schema.sql`
   from your fork (view it on GitHub, click "Copy raw file") → paste → **Run**.
   "Success. No rows returned" = perfect.
3. Collect two values (keep the tab open, you'll paste them in Step 4):
   - **Project Settings (gear) → General** → copy the **Project ID**.
     Your URL is: `https://<that-id>.supabase.co`
   - **Project Settings → API Keys** → reveal + copy the **service_role** key
     (the one marked *secret* — NOT the "anon" one)

## Step 3 — Create the messenger (5 min, on your phone)

1. In Telegram, search **@BotFather** → send `/newbot` → give it any name,
   then any username ending in `bot`. **Copy the token** it replies with.
2. Search **@userinfobot** → send it anything → **copy your numeric id**.
3. Open your new bot's chat and **press START** (important!).

## Step 4 — Give the engine its keys (5 min)

In your GitHub fork: **Settings → Secrets and variables → Actions →
New repository secret**. Add these four, one at a time (exact names):

| Name | Value |
|---|---|
| `SUPABASE_URL` | `https://<your-project-id>.supabase.co` |
| `SUPABASE_KEY` | the service_role key |
| `TELEGRAM_BOT_TOKEN` | from BotFather |
| `TELEGRAM_CHAT_ID` | from userinfobot |

## Step 5 — Press the "did I do it right?" button (2 min)

**Actions tab → setup-check → Run workflow → Run workflow.**
Wait ~1 minute. If everything's right, **your bot messages you
"🎉 Setup complete"**. If not, open the run — it says exactly which piece to
fix, in plain English. Fix it, run again.

## Step 6 — Log your positions (2 min, on your phone)

Send your bot, one at a time:
- `/add AAPL 10 185.50` — ticker, quantity, average cost — for each stock you own.
- `/watch MSFT` — to track a stock with no position (no qty/price needed).

**That's it.** The system now runs itself — every ~10 minutes during US market
hours. `/positions` shows your live P&L any time.

---

### Good to know
- **The engine polls every ~10 minutes** during US market hours — the
  setup-check starts a self-sustaining loop that keeps this cadence
  automatically. Nothing is ever lost, only batched.
- **Getting updates later:** when this project improves, your fork shows a
  "Sync fork" button on its main page — one click brings the new version in.
- Send `/help` to your bot for all commands (`/sell`, `/remove`, `/positions`,
  `/list`).
- No alerts fire yet — this build's alert criteria aren't defined (it's an
  intentionally empty extension point, `signals/criteria.py`). Tracking and
  P&L work fully; proactive alerts are a future addition.

---

## Optional — your dashboard (10 min, browser only)

A live view of your portfolio: P&L per position, per-stock event history, and
the alert feed. Runs free in the cloud; open it from any device.

1. Go to **share.streamlit.io** → **Continue with GitHub** (same account as
   your fork) → authorize
2. **Create app** → *Deploy a public app from GitHub* →
   - Repository: your fork (`<your-username>/portfolio-pulse`)
   - Branch: `main`
   - Main file path: `portfolio_pulse/dashboard/app.py`
3. Before deploying, open **Advanced settings → Secrets** and paste (with YOUR
   two values — same ones you gave GitHub in Step 4):
   ```toml
   PP_STORE_BACKEND = "supabase"
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_KEY = "your service_role key"
   ```
4. **Deploy** → after ~2 minutes you get a permanent link like
   `https://something.streamlit.app` — bookmark it on your phone.

The dashboard only *reads* your database, so it always shows exactly what the
Telegram bot knows. (Prefer running it on your own computer instead? See the
`Start Dashboard` launchers in the repo — requires Python and a local `.env`;
that's the tinkerer's path.)
