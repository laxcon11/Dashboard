from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import requests

from data_fetch import fetch_india_vix


CACHE_FILE = Path("notes/india_flows_cache.json")
MONTHLY_FILE = Path("notes/fii_dii_monthly_history.json")
EOD_DIR = Path("data/snapshots")
FII_ENDPOINTS = {
    "react": "https://www.nseindia.com/api/fiidiiTradeReact",
    "nse": "https://www.nseindia.com/api/fiidiiTradeNse",
}


def _latest_business_day() -> pd.Timestamp:
    t = pd.Timestamp.now().normalize()
    if t.weekday() < 5:
        return t
    return t - pd.offsets.BDay(1)


def _freshness_state(as_of: Optional[pd.Timestamp]) -> str:
    if as_of is None or pd.isna(as_of):
        return "STALE"
    bd = _latest_business_day()
    if as_of.normalize() == bd:
        return "PROVISIONAL"
    if as_of.normalize() == (bd - pd.offsets.BDay(1)).normalize():
        return "FINAL"
    return "STALE"


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        s = str(v).replace(",", "").strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _build_nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.nseindia.com/reports/fii-dii",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    for warm in ("https://www.nseindia.com/", "https://www.nseindia.com/reports/fii-dii"):
        try:
            s.get(warm, timeout=8)
        except Exception:
            pass
    return s


def _parse_date(row: dict) -> Optional[pd.Timestamp]:
    for key in ["date", "tradeDate", "timestamp", "asOfDate", "day"]:
        if key in row:
            try:
                return pd.to_datetime(row[key]).normalize()
            except Exception:
                continue
    return None


def _normalize_cat(row: dict) -> str:
    c = str(
        row.get("category")
        or row.get("clientType")
        or row.get("Client Type")
        or row.get("investorType")
        or ""
    ).upper()
    if "FII" in c or "FPI" in c:
        return "FII"
    if "DII" in c:
        return "DII"
    return ""


def _rows_from_payload(payload: Any) -> Dict[str, Dict[str, float]]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    by_day: Dict[str, Dict[str, float]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        d = _parse_date(row)
        if d is None:
            continue
        key = str(d.date())
        by_day.setdefault(key, {"fii_net": 0.0, "dii_net": 0.0})

        cat = _normalize_cat(row)
        net = (
            _safe_float(row.get("netValue"))
            or _safe_float(row.get("net"))
            or _safe_float(row.get("netAmount"))
        )
        if net is None:
            buy = _safe_float(row.get("buyValue") or row.get("buy") or row.get("buyAmt"))
            sell = _safe_float(row.get("sellValue") or row.get("sell") or row.get("sellAmt"))
            if buy is not None and sell is not None:
                net = buy - sell
        if net is None:
            continue
        if cat == "FII":
            by_day[key]["fii_net"] = float(net)
        elif cat == "DII":
            by_day[key]["dii_net"] = float(net)
        else:
            # Try wide-row fallback keys.
            fii_net = _safe_float(row.get("fiiNet"))
            dii_net = _safe_float(row.get("diiNet"))
            if fii_net is not None:
                by_day[key]["fii_net"] = float(fii_net)
            if dii_net is not None:
                by_day[key]["dii_net"] = float(dii_net)
    return by_day


def _merge_rows(existing_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    by_day: Dict[str, Dict[str, Any]] = {}
    for r in existing_rows:
        d = str(r.get("date", "")).strip()
        if d:
            by_day[d] = dict(r)
    for r in new_rows:
        d = str(r.get("date", "")).strip()
        if d:
            by_day[d] = dict(r)
    return [by_day[k] for k in sorted(by_day.keys())]


def _normalize_csv_cols(df: pd.DataFrame) -> pd.DataFrame:
    def _norm(c: str) -> str:
        s = re.sub(r"[\r\n\t]+", " ", str(c))
        s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
        return s

    out = df.copy()
    out.columns = [_norm(c) for c in out.columns]
    return out


def _extract_rows_from_csv_df(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    w = _normalize_csv_cols(df)
    cat_col = next((c for c in w.columns if "category" in c), None)
    date_col = next((c for c in w.columns if c == "date" or c.endswith("_date")), None)
    net_col = next((c for c in w.columns if "net_value" in c or c == "netvalue" or c == "net"), None)
    if not cat_col or not date_col or not net_col:
        return []

    by_day: Dict[str, Dict[str, float]] = {}
    for _, row in w.iterrows():
        d = pd.to_datetime(row.get(date_col), errors="coerce")
        if pd.isna(d):
            continue
        key = str(d.normalize().date())
        by_day.setdefault(key, {"fii_net": 0.0, "dii_net": 0.0})
        cat = str(row.get(cat_col, "")).upper()
        net = _safe_float(row.get(net_col))
        if net is None:
            continue
        if "FII" in cat or "FPI" in cat:
            by_day[key]["fii_net"] = float(net)
        elif "DII" in cat:
            by_day[key]["dii_net"] = float(net)
    return [{"date": d, **vals} for d, vals in sorted(by_day.items())]


def _fetch_fii_dii_csv(endpoint: str, session: requests.Session) -> Optional[list[dict]]:
    try:
        r = session.get(endpoint, timeout=20)
        if r.status_code != 200 or not r.text.strip():
            return None
        from io import StringIO

        df = pd.read_csv(StringIO(r.text))
        rows = _extract_rows_from_csv_df(df)
        return rows or None
    except Exception:
        return None


def _load_downloaded_fii_dii_csv() -> Optional[dict]:
    # User-downloaded backup files from NSE report downloads.
    home = Path.home() / "Downloads"
    patterns = [
        "*fii*dii*.csv",
        "*fiidii*.csv",
        "*FII*DII*.csv",
        "*FII*FPI*DII*.csv",
    ]
    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend(home.glob(pat))
    if not candidates:
        return None
    candidates = sorted(set(candidates), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates[:5]:
        try:
            df = pd.read_csv(p)
            rows = _extract_rows_from_csv_df(df)
            if rows:
                return {"rows": rows, "source": f"NSE(downloaded_csv:{p.name})"}
        except Exception:
            continue
    return None


def _fetch_nse_fii_dii() -> Optional[dict]:
    s = _build_nse_session()
    endpoint_maps: Dict[str, Dict[str, Dict[str, float]]] = {}
    for endpoint_name, url in FII_ENDPOINTS.items():
        try:
            r = s.get(url, timeout=15)
            if r.status_code != 200:
                continue
            payload = r.json()
            parsed = _rows_from_payload(payload)
            if parsed:
                endpoint_maps[endpoint_name] = parsed
        except Exception:
            continue

    # Primary = across exchanges (react). Fallback = NSE-only.
    selected = endpoint_maps.get("react") or endpoint_maps.get("nse")

    # CSV backup from official NSE endpoints, if JSON shape changes.
    csv_rows = (
        _fetch_fii_dii_csv("https://www.nseindia.com/api/fiidiiTradeReact?csv=true", s)
        or _fetch_fii_dii_csv("https://www.nseindia.com/api/fiidiiTradeNse?csv=true", s)
    )
    if (not selected) and csv_rows:
        selected = {r["date"]: {"fii_net": r["fii_net"], "dii_net": r["dii_net"]} for r in csv_rows}

    if not selected:
        return None

    rows = [{"date": d, **vals} for d, vals in sorted(selected.items())]

    cache = _load_cache() or {}
    merged_rows = _merge_rows(cache.get("rows", []), rows)
    if "react" in endpoint_maps:
        source = "NSE(react_across_exchanges)"
    elif "nse" in endpoint_maps:
        source = "NSE(nse_only)"
    else:
        source = "NSE(csv_fallback)"
    return {
        "rows": merged_rows,
        "source": source,
        "latest_pull_rows": len(rows),
    }


def _load_cache() -> Optional[dict]:
    if not CACHE_FILE.exists():
        return None
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return None


def _reconcile_monthly_with_daily(monthly_rows: list[dict], daily_df: pd.DataFrame) -> list[dict]:
    if daily_df.empty:
        return monthly_rows

    # Ensure month_start is a date string "YYYY-MM-01"
    out = {str(r["month_start"]): r for r in monthly_rows}
    
    # Current month start
    now = pd.Timestamp.now().normalize()
    current_month_start = now.replace(day=1)
    
    # Group daily by month
    daily = daily_df.copy()
    daily["month_period"] = daily["date"].dt.to_period("M")
    
    monthly_groups = daily.groupby("month_period")
    for period, group in monthly_groups:
        m_start = period.to_timestamp()
        key = str(m_start.date())
        
        # Only add complete months (before current month) or if it's the current month but not already in 'out'
        # Actually, if it's in daily, it's more "live" than the xlsx import.
        # But we only want to ADD missing months to the 'Prior Months' list.
        if m_start < current_month_start:
            if key not in out:
                out[key] = {
                    "month_start": key,
                    "fii_net": float(group["fii_net"].sum()),
                    "dii_net": float(group["dii_net"].sum()),
                    "source": "derived_from_daily_cache"
                }
    
    return [out[k] for k in sorted(out.keys())]


def _load_monthly_history() -> list[dict]:
    if not MONTHLY_FILE.exists():
        return []
    try:
        obj = json.loads(MONTHLY_FILE.read_text())
    except Exception:
        return []
    rows = obj.get("rows", []) if isinstance(obj, dict) else []
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        d = str(r.get("month_start", "")).strip()
        if not d:
            continue
        out.append(
            {
                "month_start": d,
                "fii_net": _safe_float(r.get("fii_net")) or 0.0,
                "dii_net": _safe_float(r.get("dii_net")) or 0.0,
                "source": str(r.get("source", "imported")).strip() or "imported",
            }
        )
    return out


def _save_cache(payload: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(payload, indent=2))


def _latest_breadth_from_snapshot() -> dict:
    files = sorted(EOD_DIR.glob("eod_*.json"))
    if not files:
        return {}
    try:
        p = json.loads(files[-1].read_text())
        b = p.get("breadth", {}) if isinstance(p, dict) else {}
        adv = int(b.get("advances", 0) or 0)
        dec = int(b.get("declines", 0) or 0)
        ratio = float(b.get("ratio", 0.0) or 0.0)
        dt = pd.to_datetime(p.get("date"), errors="coerce")
        return {
            "advances": adv,
            "declines": dec,
            "ratio": ratio,
            "as_of": (None if pd.isna(dt) else dt.normalize()),
            "source": f"snapshot:{files[-1].name}",
        }
    except Exception:
        return {}


def get_india_macro_signals_v1() -> Dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    fetched = _fetch_nse_fii_dii()
    if fetched is None:
        fetched = _load_downloaded_fii_dii_csv()
    if fetched is None:
        fetched = _load_cache()
    else:
        fetched["fetched_at"] = now
        _save_cache(fetched)

    rows = fetched.get("rows", []) if isinstance(fetched, dict) else []
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["fii_net"] = pd.to_numeric(df["fii_net"], errors="coerce").fillna(0.0)
        df["dii_net"] = pd.to_numeric(df["dii_net"], errors="coerce").fillna(0.0)
        df = df.dropna(subset=["date"]).sort_values("date")
    latest = df.iloc[-1] if not df.empty else None
    as_of = None if latest is None else pd.to_datetime(latest["date"]).normalize()
    fii_latest = float(latest["fii_net"]) if latest is not None else None
    dii_latest = float(latest["dii_net"]) if latest is not None else None

    fii_20d = None
    dominance = None
    if not df.empty:
        fii_20d = float(df["fii_net"].tail(20).sum())
        denom = abs(float(df["fii_net"].iloc[-1])) + abs(float(df["dii_net"].iloc[-1]))
        dominance = (float(df["fii_net"].iloc[-1]) / denom) if denom > 0 else 0.0

    # GST Processing Logic
    gst_file = Path("data/gst_monthly.csv")
    gst_data = {"status": "UNAVAILABLE", "source": "pending"}
    gst_df_full = pd.DataFrame()

    if gst_file.exists():
        try:
            gst_df_full = pd.read_csv(gst_file)
            gst_df_full["gst_collection_lakh_cr"] = pd.to_numeric(gst_df_full["gst_collection_lakh_cr"])
            gst_df_full["mom_growth"] = gst_df_full["gst_collection_lakh_cr"].pct_change() * 100
            gst_df_full["yoy_growth"] = gst_df_full["gst_collection_lakh_cr"].pct_change(12) * 100
            gst_df_full["gst_3m_avg"] = gst_df_full["gst_collection_lakh_cr"].rolling(3).mean()

            latest_gst = gst_df_full.iloc[-1]
            gst_yoy = latest_gst["yoy_growth"]

            if pd.notna(gst_yoy):
                if gst_yoy > 10:
                    demand_signal = "Strong Demand"
                elif gst_yoy > 5:
                    demand_signal = "Stable Demand"
                else:
                    demand_signal = "Demand Weakening"
            else:
                demand_signal = "Insufficient History"

            is_ath = latest_gst["gst_collection_lakh_cr"] >= gst_df_full["gst_collection_lakh_cr"].max()

            gst_data = {
                "latest_collection": float(latest_gst["gst_collection_lakh_cr"]),
                "mom_growth": float(latest_gst["mom_growth"]),
                "gst_yoy": float(latest_gst["yoy_growth"]),
                "three_month_avg": float(latest_gst["gst_3m_avg"]),
                "demand_signal": demand_signal,
                "is_all_time_high": bool(is_ath),
                "status": "PROVISIONAL" if str(latest_gst["month"]) >= datetime.now().strftime("%Y-%m") else "FINAL",
                "source": "PIB/GSTN",
                "as_of": str(latest_gst["month"])
            }
        except Exception as e:
            gst_data["error"] = str(e)

    vix_price, vix_change = fetch_india_vix()
    breadth = _latest_breadth_from_snapshot()
    gst_context_file = Path("notes/gst_context.json")
    curve_file = Path("notes/india_curve_context.json")
    gst_context = None
    curve = None
    if gst_context_file.exists():
        try:
            gst_context = json.loads(gst_context_file.read_text())
        except Exception:
            gst_context = None
    if curve_file.exists():
        try:
            curve = json.loads(curve_file.read_text())
        except Exception:
            curve = None

    return {
        "flows": {
            "fii_net": fii_latest,
            "dii_net": dii_latest,
            "fii_20d": fii_20d,
            "fii_dii_dominance": dominance,
            "as_of": None if as_of is None else str(as_of.date()),
            "status": _freshness_state(as_of),
            "source": fetched.get("source", "cache") if isinstance(fetched, dict) else "unavailable",
            "rows": int(len(df)),
            "history_rows": (
                df[["date", "fii_net", "dii_net"]]
                .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
                .to_dict(orient="records")
                if not df.empty
                else []
            ),
            "monthly_history_rows": _reconcile_monthly_with_daily(_load_monthly_history(), df),
            "note": "PROVISIONAL if same latest business day; FINAL if T-1 business day; else STALE.",
        },
        "vix": {
            "value": vix_price,
            "change_pct": vix_change,
            "status": "PROVISIONAL" if vix_price is not None else "STALE",
            "source": "NSE",
        },
        "breadth": {
            "advances": breadth.get("advances"),
            "declines": breadth.get("declines"),
            "ratio": breadth.get("ratio"),
            "as_of": None if breadth.get("as_of") is None else str(breadth.get("as_of").date()),
            "status": _freshness_state(breadth.get("as_of")),
            "source": breadth.get("source", "snapshot"),
        },
        "curve": (
            {
                **curve,
                "value": (curve.get("ten_year_yield", 0) - curve.get("three_month_yield", 0)),
                "status": "FINAL",
            }
            if curve
            else {"status": "UNAVAILABLE", "source": "pending"}
        ),
        "gst": {
            **gst_data,
            "listed_contribution": gst_context.get("listed_revenue_contribution_pct") if gst_context else None,
            "portal_links": gst_context.get("sources") if gst_context else []
        },
        "gst_history": gst_df_full.to_dict(orient="records") if not gst_df_full.empty else [],
        "updated_at": now,
    }


def get_india_context_signals() -> Dict[str, Any]:
    """Alias for backward compatibility."""
    return get_india_macro_signals_v1()
