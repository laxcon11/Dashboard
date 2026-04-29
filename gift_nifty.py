from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from config import (
    GIFT_NIFTY_API_KEY,
    GIFT_NIFTY_API_URL,
    GIFT_NIFTY_FLAT_THRESHOLD_PCT,
    GIFT_NIFTY_GROWW_FALLBACK,
    GIFT_NIFTY_GROWW_URL,
    GIFT_NIFTY_LOCAL_SNAPSHOT,
    GIFT_NIFTY_MONEYCONTROL_FALLBACK,
    GIFT_NIFTY_MONEYCONTROL_URL,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
)


IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)


def now_ist() -> datetime:
    return datetime.now(IST)


def is_gift_session_active(
    session_start_hour: int = GIFT_NIFTY_SESSION_START_IST_HOUR,
    cutoff_hour: int = GIFT_NIFTY_COLLAPSE_IST_HOUR,
) -> bool:
    """
    Active window: from post-cash close session start (default 16:00 IST)
    through next-day cutoff (default 10:00 IST).
    """
    n = now_ist()
    if n.weekday() >= 5:
        return False
    h = n.hour
    return (h >= int(session_start_hour)) or (h < int(cutoff_hour))


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def _parse_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    try:
        ts = pd.to_datetime(raw, errors="coerce", utc=True)
        if pd.isna(ts):
            ts = pd.to_datetime(raw, errors="coerce")
            if pd.isna(ts):
                return None
            dt = ts.to_pydatetime()
            if dt.tzinfo is None:
                return dt.replace(tzinfo=IST)
            return dt.astimezone(IST)
        return ts.to_pydatetime().astimezone(IST)
    except Exception:
        return None


def _classify_gap(premium_pct: Optional[float], flat_threshold_pct: float = GIFT_NIFTY_FLAT_THRESHOLD_PCT) -> str:
    if premium_pct is None:
        return "Unknown"
    if premium_pct >= flat_threshold_pct:
        return "Gap Up"
    if premium_pct <= -flat_threshold_pct:
        return "Gap Down"
    return "Flat"


def _from_local_snapshot() -> Optional[dict]:
    p = Path(GIFT_NIFTY_LOCAL_SNAPSHOT)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
        if isinstance(payload, dict):
            payload["_source"] = f"local:{p.name}"
            return payload
        return None
    except Exception as exc:
        logger.warning("Failed to read local GIFT snapshot %s: %s", p, exc)
        return None


def _from_api() -> Optional[dict]:
    if not GIFT_NIFTY_API_URL:
        return None
    headers = {"Accept": "application/json"}
    if GIFT_NIFTY_API_KEY:
        headers["Authorization"] = f"Bearer {GIFT_NIFTY_API_KEY}"
        headers["x-api-key"] = GIFT_NIFTY_API_KEY
    try:
        r = requests.get(GIFT_NIFTY_API_URL, timeout=12, headers=headers)
        if r.status_code != 200:
            return None
        payload = r.json()
        if isinstance(payload, dict):
            payload["_source"] = "api"
            return payload
        return None
    except Exception as exc:
        logger.debug("GIFT API fetch failed for %s: %s", GIFT_NIFTY_API_URL, exc)
        return None


def _from_moneycontrol_scrape() -> Optional[dict]:
    """
    Best-effort scrape fallback. Must be explicitly enabled and URL supplied.
    Output is marked unverified and should be treated as lower confidence.
    """
    if not GIFT_NIFTY_MONEYCONTROL_FALLBACK or not GIFT_NIFTY_MONEYCONTROL_URL:
        return None
    try:
        r = requests.get(
            GIFT_NIFTY_MONEYCONTROL_URL,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        if r.status_code != 200 or not r.text:
            return None
        html = r.text

        # Price-like tokens, prefer values in plausible index range.
        nums = re.findall(r"([0-9]{2},[0-9]{3}(?:\\.[0-9]+)?)", html)
        price = None
        for n in nums:
            v = _to_float(n)
            if v is not None and 15000 <= v <= 40000:
                price = v
                break
        if price is None:
            return None

        # Try to capture an explicit percentage change nearby.
        pct = None
        pct_match = re.search(r"([+-]?[0-9]+(?:\\.[0-9]+)?)\\s*%", html)
        if pct_match:
            pct = _to_float(pct_match.group(1))

        return {
            "price": price,
            "timestamp": datetime.now(IST).isoformat(timespec="seconds"),
            "delay_min": None,
            "change_pct": pct,
            "_source": "moneycontrol_scrape",
            "_unverified": True,
        }
    except Exception as exc:
        logger.debug("Moneycontrol GIFT scrape failed: %s", exc)
        return None


def _extract_price_from_text_window(txt: str) -> Optional[float]:
    nums = re.findall(r"([0-9]{2},[0-9]{3}(?:\\.[0-9]+)?)", txt)
    for n in nums:
        v = _to_float(n)
        if v is not None and 15000 <= v <= 40000:
            return v
    return None


def _extract_pct_from_text_window(txt: str) -> Optional[float]:
    # Try explicit signed percentage first.
    m = re.search(r"([+-]?[0-9]+(?:\\.[0-9]+)?)\\s*%", txt)
    if m:
        return _to_float(m.group(1))
    return None


def _from_groww_scrape() -> Optional[dict]:
    """
    Best-effort Groww scrape around sgx/gift context.
    """
    if not GIFT_NIFTY_GROWW_FALLBACK or not GIFT_NIFTY_GROWW_URL:
        return None
    try:
        r = requests.get(
            GIFT_NIFTY_GROWW_URL,
            timeout=12,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        if r.status_code != 200 or not r.text:
            return None

        html = r.text
        low = html.lower()

        # Prefer exact card extraction first (same block that shows current value on Groww page).
        # Example pattern:
        # headingLarge ... 25,570.50 ... gih22DayChangeText ... -151.50 ... (0.59%)
        card_pattern = re.compile(
            r"headingLarge\">(?:\s*<!--\s*-->)?\s*([0-9]{2},[0-9]{3}(?:\.[0-9]+)?)"
            r".{0,300}gih22DayChangeText"
            r".{0,240}?([+-]?[0-9]+(?:\.[0-9]+)?)"
            r".{0,120}?\(\s*(?:<!--\s*-->)?\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*(?:<!--\s*-->)?\s*\)",
            flags=re.IGNORECASE | re.DOTALL,
        )
        m = card_pattern.search(html)
        if m:
            price = _to_float(m.group(1))
            day_change = _to_float(m.group(2))
            pct_abs = _to_float(m.group(3))
            pct = pct_abs
            if pct is not None and day_change is not None and day_change < 0 and pct > 0:
                pct = -pct
            if price is not None:
                return {
                    "price": price,
                    "timestamp": datetime.now(IST).isoformat(timespec="seconds"),
                    "delay_min": None,
                    "change_pct": pct,
                    "_source": "groww_scrape",
                    "_unverified": True,
                }

        # Focus extraction around sgx/gift keyword neighborhoods.
        windows = []
        for kw in ["sgx-nifty", "sgx nifty", "gift nifty", "gift-nifty"]:
            pos = 0
            while True:
                i = low.find(kw, pos)
                if i < 0:
                    break
                lo = max(0, i - 1800)
                hi = min(len(html), i + 1800)
                windows.append(html[lo:hi])
                pos = i + len(kw)

        candidates = windows if windows else [html]
        for w in candidates:
            price = _extract_price_from_text_window(w)
            if price is None:
                continue
            pct = _extract_pct_from_text_window(w)
            return {
                "price": price,
                "timestamp": datetime.now(IST).isoformat(timespec="seconds"),
                "delay_min": None,
                "change_pct": pct,
                "_source": "groww_scrape",
                "_unverified": True,
            }
        return None
    except Exception as exc:
        logger.debug("Groww GIFT scrape failed: %s", exc)
        return None


def get_gift_nifty_snapshot(prev_nifty_close: Optional[float] = None) -> Dict[str, Any]:
    """
    Returns display-only snapshot. No scoring use.
    Expected payload keys (any one of aliases):
    - price: price / ltp / last / value
    - ts: timestamp / as_of / time / updated_at
    - delay_min: delay_minutes / delay_min (optional)
    - change_pct (optional)
    """
    # Prefer live sources first; keep local snapshot as fallback cache.
    raw = _from_api() or _from_groww_scrape() or _from_moneycontrol_scrape() or _from_local_snapshot() or {}
    price = _to_float(raw.get("price") or raw.get("ltp") or raw.get("last") or raw.get("value"))
    ts = _parse_ts(raw.get("timestamp") or raw.get("as_of") or raw.get("time") or raw.get("updated_at"))
    delay_min = _to_float(raw.get("delay_minutes") or raw.get("delay_min"))
    change_pct = _to_float(raw.get("change_pct"))

    if delay_min is None and ts is not None:
        delay_min = max(0.0, (now_ist() - ts).total_seconds() / 60.0)

    # Compute implied premium carefully; API payloads can sometimes provide non-price fields.
    premium_from_price = None
    if price is not None and prev_nifty_close and prev_nifty_close > 0:
        # Index level sanity guard: if feed "price" is too small, it is likely not index level.
        if price >= 1000:
            premium_from_price = ((price / float(prev_nifty_close)) - 1.0) * 100.0

    premium_pct = premium_from_price
    quality_note = ""

    # Fallback/cross-check with feed-provided change_pct when price-derived premium looks implausible.
    # This prevents false context like large double-digit gaps from malformed fields.
    if change_pct is not None:
        if premium_pct is None:
            premium_pct = float(change_pct)
            quality_note = "premium from feed change_pct (price comparison unavailable)"
        else:
            if abs(float(premium_pct)) > 8.0:
                premium_pct = float(change_pct)
                quality_note = "price-derived premium outlier; fallback to feed change_pct"
            elif abs(float(premium_pct) - float(change_pct)) > 3.0 and abs(float(change_pct)) <= 5.0:
                premium_pct = float(change_pct)
                quality_note = "price/change mismatch; using feed change_pct"

    label = _classify_gap(premium_pct)
    return {
        "available": price is not None,
        "price": price,
        "change_pct": change_pct,
        "premium_pct_vs_prev_close": premium_pct,
        "implied_label": label,
        "as_of_ist": None if ts is None else ts.strftime("%Y-%m-%d %H:%M:%S IST"),
        "delay_min": None if delay_min is None else float(delay_min),
        "delay_note": "real-time" if delay_min is not None and delay_min <= 1 else "delayed/unknown",
        "source": raw.get("_source", "unavailable"),
        "note": "Index-implied context only; stock-level gap can deviate.",
        "unverified": bool(raw.get("_unverified", False)),
        "quality_note": quality_note,
    }
