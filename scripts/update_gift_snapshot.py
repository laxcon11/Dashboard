#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


IST = ZoneInfo("Asia/Kolkata")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update local GIFT NIFTY snapshot from manual feed input (e.g., Groww screen)."
    )
    p.add_argument("--price", type=float, required=True, help="GIFT NIFTY price")
    p.add_argument("--change-pct", type=float, default=None, help="Optional change percentage (e.g., -0.42)")
    p.add_argument("--delay-min", type=float, default=None, help="Optional feed delay in minutes")
    p.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help="Optional ISO timestamp; defaults to current IST time",
    )
    p.add_argument(
        "--out",
        type=str,
        default="notes/gift_nifty_snapshot.json",
        help="Output JSON path",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.timestamp:
        ts = args.timestamp
    else:
        ts = datetime.now(IST).isoformat(timespec="seconds")

    payload = {
        "price": float(args.price),
        "timestamp": ts,
        "delay_minutes": None if args.delay_min is None else float(args.delay_min),
        "change_pct": None if args.change_pct is None else float(args.change_pct),
        "source": "groww_manual",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"[ok] snapshot updated: {out}")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

