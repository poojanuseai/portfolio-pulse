"""Import a kronos-check TP-estimate CSV into the `forecasts` table.

kronos-check (a separate local project — https://github.com/... n/a, lives at
../kronos-check on this machine) runs the Kronos forecasting model against a
shortlist of tickers you pick by hand after scanning US-Market-Move-Screener,
and writes results to output/kronos_check_<date>.csv. This job is the bridge
that gets those results into Portfolio Pulse's shared store so the dashboard's
"TP Estimates" tab can show them.

Deliberately run locally, not as a GitHub Actions job: kronos-check needs
torch + the screener's local cache.db, neither of which belong on a free
cloud runner. Needs a local .env with PP_STORE_BACKEND=supabase,
SUPABASE_URL, SUPABASE_KEY (same ones the poller uses) so it writes to the
same database the dashboard reads.

Usage: python -m portfolio_pulse.jobs.import_forecasts path\\to\\kronos_check_2026-07-28.csv
"""

from __future__ import annotations

import argparse

import pandas as pd

from portfolio_pulse.notify import telegram
from portfolio_pulse.store import get_store

_COLUMNS = ["Execution Date", "Target Date", "Symbol", "Last Close",
            "Predicted Close (2W)", "Predicted Return %", "Confidence (0-1)"]


def run(csv_path: str) -> int:
    store = get_store()
    df = pd.read_csv(csv_path)
    missing = [c for c in _COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Not a kronos-check CSV — missing column(s): {missing}")

    for _, row in df.iterrows():
        store.record_forecast(
            symbol=str(row["Symbol"]).strip().upper(),
            execution_date=str(row["Execution Date"]),
            target_date=str(row["Target Date"]),
            last_close=float(row["Last Close"]),
            predicted_close=float(row["Predicted Close (2W)"]),
            return_pct=float(row["Predicted Return %"]),
            confidence=float(row["Confidence (0-1)"]),
        )

    count = len(df)
    if count:
        top = df.sort_values("Predicted Return %", ascending=False).iloc[0]
        telegram.send_message(
            f"📈 Imported {count} Kronos TP estimate(s).\n"
            f"Top: {top['Symbol']} {top['Predicted Return %']:+.2f}% "
            f"by {top['Target Date']} (confidence {top['Confidence (0-1)']:.2f})"
        )
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Import a kronos-check output CSV into Portfolio Pulse.")
    parser.add_argument("csv_path", help="Path to a kronos_check_*.csv file")
    args = parser.parse_args()
    n = run(args.csv_path)
    print(f"Imported {n} forecast(s).")
