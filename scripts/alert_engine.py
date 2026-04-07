"""
Phase 5 Alerting:
- regime flip alert from EOD snapshots
- top setup trigger alert from movers
- invalidation breach alert for open trades
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_fetch import batch_download, extract_price_data


SNAPSHOT_DIR = Path("data/snapshots")
JOURNAL_FILE = Path("notes/trading_journal.csv")
ALERT_FILE = Path("logs/alerts.log")
STATE_FILE = Path("logs/alert_engine_state.json")
ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_snapshots() -> list[Path]:
    files = sorted(SNAPSHOT_DIR.glob("eod_*.json"))
    return files[-2:]


def append_alert(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}\n"
    with ALERT_FILE.open("a") as f:
        f.write(line)
    print(msg)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def compact_alert_log(keep_days: int = 7) -> None:
    """Deduplicate and prune alerts older than *keep_days*."""
    if not ALERT_FILE.exists():
        return
    try:
        lines = ALERT_FILE.read_text().splitlines()
    except Exception:
        return

    cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    deduped: dict[tuple[str, str], str] = {}
    order: list[tuple[str, str]] = []
    for line in lines:
        if "] " not in line:
            continue
        left, msg = line.split("] ", 1)
        ts = left.lstrip("[")
        day = ts[:10] if len(ts) >= 10 else "unknown"
        if day < cutoff:
            continue  # drop entries older than keep_days
        key = (day, msg.strip())
        if key not in deduped:
            order.append(key)
        deduped[key] = line
    rewritten = [deduped[k] for k in order]
    ALERT_FILE.write_text("\n".join(rewritten) + ("\n" if rewritten else ""))


def main() -> int:
    compact_alert_log()
    snaps = load_snapshots()
    if len(snaps) < 1:
        print("No EOD snapshots found.")
        return 0

    state = load_state()
    cur_snap = snaps[-1].name
    snapshot_already_logged = state.get("last_snapshot_logged") == cur_snap

    if len(snaps) >= 2 and not snapshot_already_logged:
        prev = json.loads(snaps[-2].read_text())
        cur = json.loads(snaps[-1].read_text())
        if prev.get("regime") != cur.get("regime"):
            append_alert(f"Regime flip: {prev.get('regime')} -> {cur.get('regime')}")

        movers = cur.get("top_movers", [])
        if movers:
            top = movers[0]
            append_alert(f"Top setup trigger candidate: {top['symbol']} ({top['change_pct']:+.2f}%)")
            for mover in movers[1:3]:
                append_alert(f"Also flagged: {mover['symbol']} ({mover['change_pct']:+.2f}%)")
        state["last_snapshot_logged"] = cur_snap

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
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
