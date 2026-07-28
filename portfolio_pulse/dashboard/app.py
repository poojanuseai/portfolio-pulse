"""Portfolio Pulse dashboard (Streamlit) — state companion to the Telegram alerts.

Built around three questions the alert stream can't answer at a glance:
  1. Portfolio     — P&L per manually-logged position and for the whole book.
  2. Stock History — everything that happened to one stock over a chosen window.
  3. Alert Feed     — every alert, most recent first (empty until custom alert
                      criteria are defined — see signals/criteria.py).
Watchlist is where positions/watch items are added, closed, or removed — the
same actions available via /add /watch /sell /remove in Telegram.

Runs locally against SQLite, or on Streamlit Community Cloud against Supabase.
On Cloud, st.secrets are mirrored into env BEFORE importing the app package
(config reads env at import time).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import streamlit as st

# Streamlit Cloud launches this file from its own subfolder, so the repo root
# (which holds the portfolio_pulse package) isn't importable without this.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# --- bridge Streamlit Cloud secrets -> environment (must precede pp imports) ---
for _key in ("PP_STORE_BACKEND", "SUPABASE_URL", "SUPABASE_KEY",
             "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_PASSWORD"):
    try:
        if _key in st.secrets:
            # Always re-sync (and strip stray whitespace from pastes) so edits
            # to the app's Secrets take effect without a full process restart.
            os.environ[_key] = str(st.secrets[_key]).strip()
    except Exception:
        pass  # no secrets.toml locally — env vars are used instead

from portfolio_pulse.store import get_store  # noqa: E402

st.set_page_config(page_title="Portfolio Pulse", page_icon="📡", layout="wide")

# Dark-surface status colors (status is never color-alone here: every badge and
# QC label pairs the color with its text/icon).
_QC_COLOR = {
    "CONFIRMED": "#34C08B", "SINGLE-SOURCE": "#E2B93B",
    "PARTIAL": "#E2B93B", "INSUFFICIENT": "#E2B93B", "SUSPECT": "#F87171",
}

_CSS = """
<style>
/* ---- hide Streamlit chrome for an app-like feel ---- */
#MainMenu, footer, header[data-testid="stHeader"] {visibility: hidden; height: 0;}
.block-container {padding-top: 2.2rem; max-width: 1200px;}

/* ---- typography ---- */
html, body, [class*="css"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased;
}
h1 {letter-spacing: -0.02em; font-weight: 750;}
h4 {letter-spacing: -0.01em; color: #C7CEDB;}

/* ---- metric tiles as cards ---- */
div[data-testid="stMetric"] {
  background: linear-gradient(180deg, #171F2E 0%, #131A27 100%);
  border: 1px solid #232D40;
  border-radius: 12px;
  padding: 14px 16px 10px 16px;
}
div[data-testid="stMetric"] label {color: #98A2B3 !important; font-size: 0.78rem;
  text-transform: uppercase; letter-spacing: 0.06em;}
div[data-testid="stMetricValue"] {
  font-variant-numeric: tabular-nums; font-weight: 650; font-size: 1.55rem;
}
div[data-testid="stMetricDelta"] {font-variant-numeric: tabular-nums;}

/* ---- tabs ---- */
button[data-baseweb="tab"] {
  font-weight: 600; letter-spacing: 0.01em; padding: 0.6rem 1.1rem;
}
div[data-baseweb="tab-highlight"] {background-color: #2DD4BF;}

/* ---- dataframes ---- */
div[data-testid="stDataFrame"] {
  border: 1px solid #232D40; border-radius: 12px; overflow: hidden;
}

/* ---- buttons & inputs ---- */
button[kind="secondaryFormSubmit"], .stButton button {
  border-radius: 10px; border: 1px solid #2A3548;
}
.stButton button:hover {border-color: #2DD4BF; color: #2DD4BF;}

/* ---- pulse dot in the title ---- */
.pulse-dot {
  display: inline-block; width: 10px; height: 10px; border-radius: 50%;
  background: #2DD4BF; margin-right: 10px; vertical-align: middle;
  box-shadow: 0 0 0 rgba(45, 212, 191, 0.6); animation: pulse 2.2s infinite;
}
@keyframes pulse {
  0% {box-shadow: 0 0 0 0 rgba(45, 212, 191, 0.45);}
  70% {box-shadow: 0 0 0 12px rgba(45, 212, 191, 0);}
  100% {box-shadow: 0 0 0 0 rgba(45, 212, 191, 0);}
}
"""
# Populated once alert criteria (signals/criteria.py) are defined and give
# their alerts real alert_type values — until then the feed is simply empty.
_TYPE_LABEL: dict[str, str] = {}


def _store():
    return get_store()


# --------------------------------------------------------------------------- #
# Data shaping
# --------------------------------------------------------------------------- #
def _holdings_rows(store) -> list[dict]:
    rows = []
    for r in store.get_holdings():
        qty, avg, last = r["qty"], r["avg_price"], r["last_price"]
        invested = qty * avg
        value = qty * last
        rows.append({
            "Symbol": r["symbol"], "Qty": qty, "Avg $": round(avg, 2),
            "Last $": round(last, 2), "Invested $": round(invested, 2),
            "Value $": round(value, 2), "P&L $": round(value - invested, 2),
            "P&L %": round((last - avg) / avg * 100, 2) if avg else None,
        })
    return rows


def _parse_created(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #
def _status_bar(store) -> None:
    holds = _holdings_rows(store)
    total_val = sum(r["Value $"] for r in holds)
    total_pnl = sum(r["P&L $"] for r in holds)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Portfolio value", f"${total_val:,.0f}")
    c2.metric("Total P&L", f"${total_pnl:,.0f}",
              delta=f"{(total_pnl / (total_val - total_pnl) * 100):.1f}%"
              if total_val != total_pnl else None)
    c3.metric("Open positions", len(holds))
    c4.metric("Watchlist", len(store.list_watch("watch")))


def _portfolio_tab(store) -> None:
    st.subheader("Holdings P&L")
    rows = _holdings_rows(store)
    if not rows:
        st.info("No positions logged yet — use /add SYMBOL QTY PRICE in "
                "Telegram, or the Watchlist tab.")
        return
    invested = sum(r["Invested $"] for r in rows)
    value = sum(r["Value $"] for r in rows)
    pnl = value - invested
    pct = (pnl / invested * 100) if invested else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Invested", f"${invested:,.2f}")
    c2.metric("Value", f"${value:,.2f}")
    c3.metric("P&L", f"${pnl:,.2f}", delta=f"{pct:.1f}%")
    st.dataframe(
        rows, use_container_width=True, hide_index=True,
        column_config={"P&L %": st.column_config.NumberColumn(format="%.2f%%")},
    )
    synced = store.get_holdings()
    if synced:
        latest = max(s["synced_at"] for s in synced)[:16].replace("T", " ")
        st.caption(f"Prices last refreshed: {latest} UTC — refreshed every "
                   "~10 minutes during US market hours.")


def _history_tab(store) -> None:
    st.subheader("Stock History")
    symbols = store.all_symbols()
    if not symbols:
        st.info("Nothing tracked yet.")
        return
    c1, c2 = st.columns([2, 1])
    sym = c1.selectbox("Stock", symbols)
    window = c2.selectbox("Window", ["7 days", "30 days", "90 days", "All"], index=1)
    alerts = store.list_alerts(limit=500, symbol=sym)
    if window != "All":
        days = int(window.split()[0])
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        alerts = [a for a in alerts if _parse_created(a.created_at) >= cutoff]
    if not alerts:
        st.info(f"No events for {sym} in the last {window.lower()} — "
                "that itself is worth knowing.")
        return
    st.caption(f"{len(alerts)} event(s)")
    for a in alerts:
        _alert_card(a)


def _alert_card(a) -> None:
    color = _QC_COLOR.get(a.qc_status, "#8B93A7")
    type_label = _TYPE_LABEL.get(a.alert_type, a.alert_type)
    when = a.created_at[:16].replace("T", " ")
    src = (f'&nbsp;·&nbsp;<a href="{a.source_url}" target="_blank" '
           f'style="color:#2DD4BF;text-decoration:none">source ↗</a>'
           if a.source_url else "")
    body = a.summary if a.summary and a.summary != a.title else ""
    impact = (f'<div style="color:#98A2B3;font-size:0.85em;margin-top:2px">'
              f'{a.impact}</div>' if a.impact else "")
    st.markdown(
        f"""<div style="background:#141B29;border:1px solid #232D40;
        border-left:3px solid {color};border-radius:10px;
        padding:12px 16px;margin-bottom:10px">
        <div style="font-size:0.78em;color:#8B93A7;letter-spacing:0.02em">
        {when} &nbsp;·&nbsp; <b style="color:#C7CEDB">{a.symbol}</b>
        &nbsp;·&nbsp; {a.source_type or type_label}
        &nbsp;·&nbsp; <span style="color:{color}">{a.qc_status}</span>{src}</div>
        <div style="font-weight:600;color:#E6EAF2;margin-top:4px">{a.title}</div>
        <div style="color:#C7CEDB">{body}</div>{impact}</div>""",
        unsafe_allow_html=True,
    )


def _feed_tab(store) -> None:
    st.subheader("Alert feed")
    limit = st.slider("Show latest", 10, 200, 50)
    alerts = store.list_alerts(limit=limit)
    if not alerts:
        st.info("No alerts yet — this fills in once alert criteria are "
                "defined (signals/criteria.py).")
        return
    for a in alerts:
        _alert_card(a)


def _watchlist_tab(store) -> None:
    st.subheader("Manage positions & watchlist")
    st.caption("Log a position (with quantity & average cost) or just watch a "
               "stock with no position. Same actions as /add /watch /sell "
               "/remove in Telegram.")

    st.markdown("#### Log a position")
    with st.form("add_position", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        sym = c1.text_input("Symbol", placeholder="e.g. AAPL",
                            label_visibility="collapsed")
        qty = c2.number_input("Qty", min_value=0.0, step=1.0,
                              label_visibility="collapsed", key="pos_qty")
        price = c3.number_input("Avg price ($)", min_value=0.0, step=0.01,
                                label_visibility="collapsed", key="pos_price")
        if (c4.form_submit_button("Add", use_container_width=True)
                and sym.strip() and qty > 0 and price > 0):
            store.upsert_position(sym.strip().upper(), qty, price)
            st.rerun()

    st.markdown("#### Watch a stock (no position)")
    with st.form("add_watch", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        wsym = c1.text_input("Symbol", placeholder="e.g. MSFT",
                             label_visibility="collapsed", key="watch_sym")
        if c2.form_submit_button("Watch", use_container_width=True) and wsym.strip():
            store.add_watch(wsym.strip().upper(), kind="watch")
            st.rerun()

    st.divider()
    holdings = store.list_watch("holding")
    if holdings:
        st.markdown(f"#### Positions — {len(holdings)}")
        for w in holdings:
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(f"**{w.symbol}** — {w.name or '(no name on file)'}")
            if c2.button("Sell/Close", key=f"sell_{w.symbol}", use_container_width=True):
                store.close_position(w.symbol)
                st.rerun()
            if c3.button("Remove", key=f"rm_h_{w.symbol}", use_container_width=True):
                store.remove_watch(w.symbol)
                st.rerun()

    watch = store.list_watch("watch")
    if watch:
        st.markdown(f"#### Watchlist — {len(watch)}")
        for w in watch:
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{w.symbol}** — {w.name or '(no name on file)'}")
            if c2.button("Remove", key=f"rm_w_{w.symbol}", use_container_width=True):
                store.remove_watch(w.symbol)
                st.rerun()

    if not holdings and not watch:
        st.caption("Nothing tracked yet.")


def _forecasts_tab(store) -> None:
    st.subheader("Kronos TP Estimates")
    st.caption("Imported from kronos-check (run locally against a shortlist you "
               "pick after scanning US-Market-Move-Screener). Not investment advice.")
    forecasts = store.list_forecasts(limit=500)
    if not forecasts:
        st.info("No forecasts imported yet — run kronos-check on your shortlist, "
                "then `python -m portfolio_pulse.jobs.import_forecasts <csv>`.")
        return
    dates = sorted({f.execution_date for f in forecasts}, reverse=True)
    exec_date = st.selectbox("Batch (execution date)", dates)
    batch = sorted((f for f in forecasts if f.execution_date == exec_date),
                   key=lambda f: f.return_pct, reverse=True)
    rows = [{
        "Symbol": f.symbol, "Last $": round(f.last_close, 2),
        "Predicted $": round(f.predicted_close, 2), "Return %": round(f.return_pct, 2),
        "Confidence": round(f.confidence, 3), "Target date": f.target_date,
    } for f in batch]
    st.dataframe(
        rows, use_container_width=True, hide_index=True,
        column_config={
            "Return %": st.column_config.NumberColumn(format="%.2f%%"),
            "Confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0),
        },
    )


def main() -> None:
    # Optional password gate: set DASHBOARD_PASSWORD in the app's secrets to
    # keep a cloud-hosted dashboard private. Unset = open (fine for local use).
    _pw = os.environ.get("DASHBOARD_PASSWORD", "")
    if _pw and not st.session_state.get("pp_authed"):
        st.markdown(_CSS, unsafe_allow_html=True)
        st.title("📡 Portfolio Pulse")
        entered = st.text_input("Password", type="password",
                                placeholder="Enter dashboard password")
        if entered.strip() == _pw.strip():
            if entered:
                st.session_state["pp_authed"] = True
                st.rerun()
        elif entered:
            st.error("Wrong password.")
        st.stop()

    try:
        store = _store()
        store.list_alerts(limit=1)  # connectivity probe — fail here, friendly
    except Exception as exc:
        st.markdown(_CSS, unsafe_allow_html=True)
        st.title("📡 Portfolio Pulse")
        st.error(
            "**Can't reach the database.** This almost always means the "
            "`SUPABASE_URL` or `SUPABASE_KEY` in this app's Secrets is wrong "
            "or points to a deleted project.\n\n"
            "**Fix:** Manage app (bottom right) → ⋮ → Settings → Secrets → "
            "paste your current Supabase Project URL and service_role key "
            "(Supabase dashboard → Project Settings) → Save."
        )
        st.caption(f"Technical detail: {type(exc).__name__}: {exc}")
        st.stop()

    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown(
        '<h1><span class="pulse-dot"></span>Portfolio Pulse</h1>',
        unsafe_allow_html=True,
    )
    st.caption("Your manually-logged US positions — P&L, history, and alerts. "
               "No broker connection. Alerts on Telegram; this is the state "
               "view. Not investment advice.")
    _status_bar(store)
    st.divider()

    portfolio, history, feed, watch, forecasts = st.tabs(
        ["💼 Portfolio", "🕘 Stock History", "📨 Alert Feed", "👁 Watchlist",
         "🎯 TP Estimates"]
    )
    with portfolio:
        _portfolio_tab(store)
    with history:
        _history_tab(store)
    with feed:
        _feed_tab(store)
    with watch:
        _watchlist_tab(store)
    with forecasts:
        _forecasts_tab(store)


main()
