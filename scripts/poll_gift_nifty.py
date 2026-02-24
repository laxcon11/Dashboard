#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import GIFT_NIFTY_LOCAL_SNAPSHOT
from gift_nifty import get_gift_nifty_snapshot


IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def is_active_window(dt: datetime, start_hour: int, cutoff_hour: int) -> bool:
    # Weekday-only polling. Active across midnight:
    # start_hour..23:59 and 00:00..cutoff_hour-1.
    if dt.weekday() >= 5:
        return False
    h = dt.hour
    return (h >= int(start_hour)) or (h < int(cutoff_hour))


def write_snapshot(snapshot: dict, out_path: Path) -> None:
    payload = {
        "price": snapshot.get("price"),
        "timestamp": now_ist().isoformat(timespec="seconds"),
        "delay_minutes": snapshot.get("delay_min"),
        "change_pct": snapshot.get("change_pct"),
        "source": snapshot.get("source", "unknown"),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Poll and persist GIFT NIFTY snapshot during configured active windows."
    )
    p.add_argument("--interval-sec", type=int, default=180, help="Polling interval in seconds (default: 180)")
    p.add_argument("--start-hour", type=int, default=17, help="IST start hour after India close (default: 17)")
    p.add_argument("--cutoff-hour", type=int, default=10, help="IST morning cutoff hour (default: 10)")
    p.add_argument("--once", action="store_true", help="Run single poll cycle and exit")
    p.add_argument("--out", type=str, default=GIFT_NIFTY_LOCAL_SNAPSHOT, help="Output snapshot JSON path")
    return p.parse_args()


def poll_once(out_path: Path, start_hour: int, cutoff_hour: int) -> int:
    dt = now_ist()
    if not is_active_window(dt, start_hour=start_hour, cutoff_hour=cutoff_hour):
        print(f"[skip] outside active window at {dt.strftime('%Y-%m-%d %H:%M:%S IST')}")
        return 0

    snap = get_gift_nifty_snapshot(prev_nifty_close=None)
    if not snap.get("available", False):
        print("[warn] GIFT snapshot unavailable")
        return 1
    write_snapshot(snap, out_path)
    badge = "N/A" if snap.get("premium_pct_vs_prev_close") is None else f"{float(snap['premium_pct_vs_prev_close']):+.2f}%"
    print(
        f"[ok] {dt.strftime('%Y-%m-%d %H:%M:%S IST')} | "
        f"GIFT NIFTY {badge} ({snap.get('implied_label', 'Unknown')}) | src={snap.get('source', 'unknown')}"
    )
    return 0


def main() -> int:
    args = parse_args()
    out_path = Path(args.out)

    if args.once:
        return poll_once(out_path, args.start_hour, args.cutoff_hour)

    print(
        f"[start] polling every {args.interval_sec}s | window: >= {args.start_hour:02d}:00 or < {args.cutoff_hour:02d}:00 IST"
    )
    while True:
        try:
            poll_once(out_path, args.start_hour, args.cutoff_hour)
        except KeyboardInterrupt:
            print("\n[stop] interrupted")
            return 0
        except Exception as exc:
            print(f"[error] {type(exc).__name__}: {exc}")
        time.sleep(max(15, int(args.interval_sec)))


if __name__ == "__main__":
    raise SystemExit(main())
