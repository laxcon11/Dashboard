"""
Phase 5 Alerting:
- regime flip alert from EOD snapshots
- top setup trigger alert from movers
- invalidation breach alert for open trades
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_fetch import batch_download, extract_price_data


SNAPSHOT_DIR = Path("data/snapshots")
JOURNAL_FILE = Path("notes/trading_journal.csv")
ALERT_FILE = Path("logs/alerts.log")
ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_snapshots() -> list[Path]:
    files = sorted(SNAPSHOT_DIR.glob("eod_*.json"))
    return files[-2:]


def append_alert(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}\n"
    with ALERT_FILE.open("a") as f:
        f.write(line)
    print(msg)


def main() -> int:
    snaps = load_snapshots()
    if len(snaps) < 1:
        print("No EOD snapshots found.")
        return 0

    if len(snaps) >= 2:
        prev = json.loads(snaps[-2].read_text())
        cur = json.loads(snaps[-1].read_text())
        if prev.get("regime") != cur.get("regime"):
            append_alert(f"Regime flip: {prev.get('regime')} -> {cur.get('regime')}")

        movers = cur.get("top_movers", [])
        if movers:
            top = movers[0]
            append_alert(f"Top setup trigger candidate: {top['symbol']} ({top['change_pct']:+.2f}%)")

    # Invalidation breach checks
    if JOURNAL_FILE.exists():
        try:
            df = pd.read_csv(JOURNAL_FILE)
        except Exception:
            df = pd.DataFrame()
        if not df.empty and "Status" in df.columns:
            open_df = df[df["Status"] == "OPEN"].copy()
            if not open_df.empty:
                symbols = open_df["Symbol"].dropna().unique().tolist()
                mkt = batch_download(symbols, period="1d")
                for _, row in open_df.iterrows():
                    sym = row["Symbol"]
                    invalidation = float(row.get("Invalidation", 0) or 0)
                    if invalidation <= 0:
                        continue
                    ltp = extract_price_data(mkt.get(sym))[0]
                    if ltp is None:
                        continue
                    side = str(row.get("Side", "LONG")).upper()
                    breached = (side == "LONG" and ltp <= invalidation) or (side == "SHORT" and ltp >= invalidation)
                    if breached:
                        append_alert(f"Invalidation breach: {sym} LTP {ltp:.2f} vs invalidation {invalidation:.2f} ({side})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
