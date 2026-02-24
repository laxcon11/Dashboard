from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd


HOLIDAY_FILE = Path("notes/nse_holidays.json")


def _load_holidays() -> set[pd.Timestamp]:
    if not HOLIDAY_FILE.exists():
        return set()
    try:
        payload = json.loads(HOLIDAY_FILE.read_text())
    except Exception:
        return set()
    rows = payload.get("holidays", []) if isinstance(payload, dict) else []
    out: set[pd.Timestamp] = set()
    for item in rows:
        d = pd.to_datetime(item, errors="coerce")
        if pd.isna(d):
            continue
        out.add(d.normalize())
    return out


def is_nse_trading_day(d: pd.Timestamp) -> bool:
    day = pd.Timestamp(d).normalize()
    if day.weekday() >= 5:
        return False
    holidays = _load_holidays()
    return day not in holidays


def latest_nse_business_day(ref: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    day = pd.Timestamp.today().normalize() if ref is None else pd.Timestamp(ref).normalize()
    while not is_nse_trading_day(day):
        day = day - pd.Timedelta(days=1)
    return day


def nse_business_days_between(start: pd.Timestamp, end: pd.Timestamp) -> int:
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    if s > e:
        return 0
    days = pd.date_range(s, e, freq="D")
    return int(sum(1 for d in days if is_nse_trading_day(pd.Timestamp(d))))


def nse_business_day_age(last_date: Optional[pd.Timestamp], ref_date: Optional[pd.Timestamp] = None) -> Optional[int]:
    if last_date is None or pd.isna(last_date):
        return None
    last = pd.Timestamp(last_date).normalize()
    ref = latest_nse_business_day(ref_date)
    if last > ref:
        return 0
    return max(0, nse_business_days_between(last, ref) - 1)
