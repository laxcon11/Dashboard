"""
15_Stock_Fundamentals.py
Stock EOD Profile — rebuilt on yfinance (free, no API key required).
Falls back to EODHD/Finnhub if keys are present and plan allows.

Data sources (all free):
  Primary:   yfinance  — fundamentals, price history, stock news, analyst data
  Secondary: EODHD     — if key present and NOT eod-only plan
  Tertiary:  Finnhub   — if key present (US/global market news only)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

import watchlist_manager as wm
from NSE_Config import PRESET_WATCHLISTS
from utils import get_ui_detail_mode, setup_page, get_ui_device_mode, responsive_cols as _responsive_cols

# Optional paid providers — page works fully without them
try:
    from config import EODHD_API_KEY, FINNHUB_API_KEY
    from data_fetch import (
        fetch_eodhd_market_news,
        fetch_finnhub_market_news,
        is_eodhd_eod_only,
        probe_market_data_providers,
    )
    _PAID_PROVIDERS = True
except ImportError:
    EODHD_API_KEY = None
    FINNHUB_API_KEY = None
    _PAID_PROVIDERS = False

# ─── Page Setup ─────────────────────────────────────────────────────────────

setup_page("Stock EOD Profile")
view_mode  = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile  = device_mode == "Mobile"

st.title("🏛️ Stock EOD Profile")
st.caption("Free fundamentals and news powered by Yahoo Finance (yfinance). No API key required.")

# ─── Provider Status ─────────────────────────────────────────────────────────

eodhd_eod_only = False
finnhub_ok     = False

if _PAID_PROVIDERS and (EODHD_API_KEY or FINNHUB_API_KEY):
    eodhd_eod_only = is_eodhd_eod_only(EODHD_API_KEY) if EODHD_API_KEY else False
    with st.expander("Provider Diagnostics", expanded=False):
        diag = probe_market_data_providers(
            finnhub_api_key=FINNHUB_API_KEY,
            eodhd_api_key=EODHD_API_KEY,
            india_symbol_ns="INFY.NS",
            us_symbol="AAPL",
        )
        finnhub_ok = bool((diag.get("finnhub", {}) or {}).get("ok"))
        rows = []
        for name in ["eodhd", "finnhub"]:
            d = diag.get(name, {})
            rows.append({
                "provider":    name.upper(),
                "configured":  bool(d.get("configured")),
                "ok":          bool(d.get("ok")),
                "eod_only":    bool(d.get("eod_only")) if name == "eodhd" else False,
                "message":     d.get("message"),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if eodhd_eod_only:
            st.info("EODHD free plan detected — fundamentals/news from that provider are unavailable. yfinance is used instead.")

# ─── Watchlist Selector ──────────────────────────────────────────────────────

watchlists = wm.load_watchlists()
wl_names   = sorted(list(watchlists.keys()))
default_wl = next((w for w in ["Top 20 by Market Cap"] if w in watchlists), wl_names[0] if wl_names else "")

if not default_wl:
    st.warning("No watchlists found.")
    st.stop()

wl_name = st.selectbox("Watchlist", wl_names, index=wl_names.index(default_wl))
wl_symbols = watchlists.get(wl_name, [])
default_symbols = PRESET_WATCHLISTS.get("Top 20 by Market Cap", wl_symbols)[:10]
selected_symbols = st.multiselect(
    "Select Stocks",
    options=wl_symbols,
    default=[s for s in default_symbols if s in wl_symbols][:10],
)

if not selected_symbols:
    st.info("Select at least one stock.")
    st.stop()

# ─── yfinance Fetch Layer ─────────────────────────────────────────────────────

# Field definitions — (yfinance key, display label, format spec, good threshold fn, bad threshold fn)
FUNDAMENTALS_FIELDS: list[tuple[str, str, str, Any, Any]] = [
    ("trailingPE",       "P/E (TTM)",            "{:.1f}",  lambda v: v < 25,   lambda v: v > 45),
    ("priceToBook",      "P/B",                  "{:.2f}",  lambda v: v < 4,    lambda v: v > 8),
    ("trailingEps",      "EPS (TTM)",             "{:.2f}",  lambda v: v > 0,    lambda v: v < 0),
    ("revenueGrowth",    "Revenue Growth",        "{:+.1%}", lambda v: v > 0,    lambda v: v < 0),
    ("earningsGrowth",   "Earnings Growth",       "{:+.1%}", lambda v: v > 0,    lambda v: v < 0),
    ("grossMargins",     "Gross Margin",          "{:.1%}",  lambda v: v > 0.20, lambda v: v < 0.10),
    ("operatingMargins", "Operating Margin",      "{:.1%}",  lambda v: v > 0.15, lambda v: v < 0.05),
    ("returnOnEquity",   "ROE",                   "{:.1%}",  lambda v: v > 0.15, lambda v: v < 0.05),
    ("debtToEquity",     "Debt/Equity",           "{:.2f}",  lambda v: v < 1,    lambda v: v > 2),
    ("currentRatio",     "Current Ratio",         "{:.2f}",  lambda v: v > 1.5,  lambda v: v < 1.0),
    ("dividendYield",    "Dividend Yield",        "{:.2%}",  lambda v: v > 0.01, lambda v: v < 0.005),
    ("beta",             "Beta",                  "{:.2f}",  lambda v: 0.6 <= v <= 1.4, lambda v: v > 2.0),
]

DISPLAY_LABELS = [f[1] for f in FUNDAMENTALS_FIELDS]
FIELD_KEYS     = [f[0] for f in FUNDAMENTALS_FIELDS]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yf_batch(symbols: tuple[str, ...]) -> dict[str, dict]:
    """Fetch yfinance .info for all symbols. Cached 15 minutes.
    
    Also computes derived fields that yfinance doesn't provide for NSE stocks:
    - returnOnEquity: computed from netIncomeToCommon / (bookValue × sharesOutstanding)
    - currentRatio:   fetched from quarterly balance sheet if available
    """
    result = {}
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.info or {}

            # Compute ROE if yfinance didn't provide it
            if info.get("returnOnEquity") is None:
                net_income = info.get("netIncomeToCommon")
                book_val   = info.get("bookValue")
                shares     = info.get("sharesOutstanding")
                if net_income and book_val and shares and book_val > 0 and shares > 0:
                    total_equity = book_val * shares
                    info["returnOnEquity"] = net_income / total_equity

            # Compute Current Ratio from balance sheet if yfinance didn't provide it
            if info.get("currentRatio") is None:
                try:
                    # Try quarterly first, then annual (NSE stocks often only have annual)
                    for bs in [t.quarterly_balance_sheet, t.balance_sheet]:
                        if bs is not None and not bs.empty:
                            latest = bs.iloc[:, 0]  # most recent period
                            ca = latest.get("Current Assets") or latest.get("CurrentAssets")
                            cl = latest.get("Current Liabilities") or latest.get("CurrentLiabilities")
                            if ca and cl and float(cl) > 0:
                                info["currentRatio"] = float(ca) / float(cl)
                                break
                except Exception:
                    pass  # balance sheet fetch can fail; leave as None

            result[sym] = info
            time.sleep(0.15)   # gentle rate limiting
        except Exception:
            result[sym] = {}
    return result


@st.cache_data(ttl=900, show_spinner=False)
def fetch_yf_history(symbol: str, period: str = "6mo") -> pd.DataFrame:
    """Fetch OHLCV history for one symbol. Cached 15 minutes."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period=period, auto_adjust=True)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_yf_news(symbol: str) -> list[dict]:
    """Fetch Yahoo Finance news for one symbol. Cached 30 minutes."""
    try:
        t = yf.Ticker(symbol)
        return t.news or []
    except Exception:
        return []


def _safe_float(info: dict, key: str) -> float | None:
    v = info.get(key)
    if v is None:
        return None
    try:
        f = float(v)
        return None if (f != f) else f   # NaN check
    except Exception:
        return None


def _fmt(val: float | None, fmt: str) -> str:
    if val is None:
        return "—"
    try:
        return fmt.format(val)
    except Exception:
        return str(val)


# ─── Fetch All Data ───────────────────────────────────────────────────────────

with st.spinner("Fetching fundamentals from Yahoo Finance..."):
    info_map = fetch_yf_batch(tuple(selected_symbols))

# ─── Fundamentals Comparison Table ───────────────────────────────────────────

st.markdown("### Fundamentals Comparison")

display_cols = selected_symbols if view_mode == "Detail" else selected_symbols[:min(6, len(selected_symbols))]

# BUG FIX: Use yf_key (index 0) for yfinance lookup, not display label (index 1)
table_data: dict[str, list] = {sym: [] for sym in display_cols}
for yf_key, label, fmt, _, _ in FUNDAMENTALS_FIELDS:
    for sym in display_cols:
        v = _safe_float(info_map.get(sym, {}), yf_key)
        table_data[sym].append(_fmt(v, fmt) if v is not None else "—")

table_df = pd.DataFrame(table_data, index=DISPLAY_LABELS)

# Cell colouring — use raw values for threshold checks, not formatted strings
def _cell_color(row_label: str, sym: str) -> str:
    """Return CSS style string based on raw value thresholds."""
    entry = next((f for f in FUNDAMENTALS_FIELDS if f[1] == row_label), None)
    if not entry:
        return ""
    yf_key, _, _, good_fn, bad_fn = entry
    v = _safe_float(info_map.get(sym, {}), yf_key)
    if v is None:
        return ""
    try:
        if good_fn(v):
            return "background-color:#dcfce7"
        if bad_fn(v):
            return "background-color:#fee2e2"
    except Exception:
        pass
    return ""

def _style_table(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame("", index=df.index, columns=df.columns)
    for idx in df.index:
        for col in df.columns:
            out.loc[idx, col] = _cell_color(idx, col)
    return out

styled = table_df.style.apply(lambda _: _style_table(table_df), axis=None)
st.dataframe(styled, use_container_width=True)

if view_mode == "Summary" and len(selected_symbols) > len(display_cols):
    st.caption(f"Showing {len(display_cols)} of {len(selected_symbols)} stocks in Summary mode.")

# ─── EOD Snapshot Table ───────────────────────────────────────────────────────

st.markdown("### EOD Snapshot")

def _pct(series: pd.Series, bars: int) -> float | None:
    try:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if len(s) <= bars:
            return None
        return float((s.iloc[-1] / s.iloc[-(bars + 1)] - 1.0) * 100.0)
    except Exception:
        return None

with st.spinner("Fetching price history..."):
    snap_rows = []
    for sym in selected_symbols:
        info = info_map.get(sym, {})
        df_h = fetch_yf_history(sym, "6mo")
        close = df_h["Close"] if not df_h.empty and "Close" in df_h.columns else pd.Series(dtype="float64")
        vol   = df_h["Volume"] if not df_h.empty and "Volume" in df_h.columns else pd.Series(dtype="float64")

        snap_rows.append({
            "Symbol":       sym,
            "Name":         info.get("shortName") or info.get("longName") or "—",
            "Sector":       info.get("sector", "—"),
            "Last Close":   _safe_float(info, "currentPrice") or (float(close.iloc[-1]) if not close.empty else None),
            "Market Cap":   _safe_float(info, "marketCap"),
            "1D %":         _pct(close, 1),
            "1W %":         _pct(close, 5),
            "1M %":         _pct(close, 21),
            "3M %":         _pct(close, 63),
            "20D Avg Vol":  float(vol.dropna().tail(20).mean()) if not vol.dropna().empty else None,
        })

snap_df = pd.DataFrame(snap_rows)

def _fmt_snap(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    def _color_pct(col):
        def _fn(v):
            try:
                if v is None or v != v: return ""
                return "color:#16a34a" if v > 0 else "color:#dc2626" if v < 0 else ""
            except Exception:
                return ""
        return col.map(_fn)

    s = df.style.format({
        "Last Close": lambda v: f"₹{v:,.2f}" if v is not None and v == v else "—",
        "Market Cap": lambda v: (
            f"₹{v/1e12:.2f}T" if v and v >= 1e12 else
            f"₹{v/1e9:.1f}B"  if v and v >= 1e9  else
            f"₹{v/1e7:.1f}Cr" if v is not None and v == v else "—"
        ),
        "1D %":  lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
        "1W %":  lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
        "1M %":  lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
        "3M %":  lambda v: f"{v:+.2f}%" if v is not None and v == v else "—",
        "20D Avg Vol": lambda v: f"{v:,.0f}" if v is not None and v == v else "—",
    }, na_rep="—")

    for col in ["1D %", "1W %", "1M %", "3M %"]:
        if col in df.columns:
            s = s.apply(_color_pct, subset=[col])
    return s

st.dataframe(_fmt_snap(snap_df), use_container_width=True, hide_index=True)

# ─── Stock Deep Dive ──────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### Stock Deep Dive")

deep_symbol = st.selectbox("Select Stock", selected_symbols, index=0, key="deep_dive_select")
deep_info   = info_map.get(deep_symbol, {})

# Company header
company_name = deep_info.get("longName") or deep_info.get("shortName") or deep_symbol
sector   = deep_info.get("sector", "")
industry = deep_info.get("industry", "")
header_parts = [p for p in [sector, industry] if p]
st.markdown(f"#### {company_name}")
if header_parts:
    st.caption(" · ".join(header_parts))

# Business summary (collapsible)
summary = deep_info.get("longBusinessSummary")
if summary:
    with st.expander("Business Summary", expanded=False):
        st.write(summary)

# Key metrics row
m1, m2, m3, m4, m5, m6 = _responsive_cols(6)
metrics_data = [
    (m1, "Current Price",    "currentPrice",      "₹{:,.2f}"),
    (m2, "P/E (TTM)",        "trailingPE",         "{:.1f}x"),
    (m3, "EPS (TTM)",        "trailingEps",        "₹{:.2f}"),
    (m4, "Debt / Equity",    "debtToEquity",       "{:.2f}"),
    (m5, "ROE",              "returnOnEquity",     "{:.1%}"),
    (m6, "Beta",             "beta",               "{:.2f}"),
]
for col, label, key, fmt in metrics_data:
    with col:
        v = _safe_float(deep_info, key)
        st.metric(label, fmt.format(v) if v is not None else "N/A")

# Second metrics row
m7, m8, m9, m10 = _responsive_cols(4)
with m7:
    v = _safe_float(deep_info, "grossMargins")
    st.metric("Gross Margin", f"{v:.1%}" if v is not None else "N/A")
with m8:
    v = _safe_float(deep_info, "revenueGrowth")
    st.metric("Revenue Growth", f"{v:+.1%}" if v is not None else "N/A")
with m9:
    v = _safe_float(deep_info, "dividendYield")
    st.metric("Div Yield", f"{v:.2%}" if v is not None else "N/A")
with m10:
    rec = deep_info.get("recommendationKey", "")
    target = _safe_float(deep_info, "targetMeanPrice")
    n_analysts = deep_info.get("numberOfAnalystOpinions")
    label = rec.replace("_", " ").title() if rec else "N/A"
    target_txt = f"₹{target:,.2f}" if target else ""
    st.metric(
        f"Analyst Consensus ({n_analysts or '?'} analysts)",
        label,
        delta=target_txt if target_txt else None,
    )

# 52-week range bar chart
hi = _safe_float(deep_info, "fiftyTwoWeekHigh")
lo = _safe_float(deep_info, "fiftyTwoWeekLow")
curr = _safe_float(deep_info, "currentPrice")
if hi and lo and hi > lo:
    fig_range = go.Figure()
    fig_range.add_trace(go.Bar(
        x=[hi - lo], y=["52W Range"], orientation="h", base=[lo],
        marker_color="#bfdbfe", name="Range",
        hovertemplate=f"Low ₹{lo:,.2f} → High ₹{hi:,.2f}<extra></extra>",
    ))
    if curr:
        fig_range.add_trace(go.Scatter(
            x=[curr], y=["52W Range"], mode="markers",
            marker=dict(size=14, color="#1d4ed8", symbol="diamond"),
            name=f"Current ₹{curr:,.2f}",
            hovertemplate=f"Current ₹{curr:,.2f}<extra></extra>",
        ))
    fig_range.add_trace(go.Scatter(
        x=[lo, hi], y=["52W Range", "52W Range"], mode="markers+text",
        text=[f"₹{lo:,.2f}", f"₹{hi:,.2f}"],
        textposition=["bottom center", "bottom center"],
        marker=dict(size=8, color=["#ef4444", "#10b981"]),
        showlegend=False,
    ))
    fig_range.update_layout(
        height=130, margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True, legend=dict(orientation="h", x=0, y=-0.6),
        xaxis_showgrid=False, yaxis_showgrid=False,
    )
    st.plotly_chart(fig_range, use_container_width=True)

# Price and volume history
with st.spinner("Loading price history..."):
    deep_df = fetch_yf_history(deep_symbol, "6mo")

if not deep_df.empty and "Close" in deep_df.columns:
    # Price chart with EMAs
    close_series = deep_df["Close"]
    price_fig = go.Figure()
    price_fig.add_trace(go.Scatter(
        x=deep_df.index, y=close_series,
        mode="lines", name="Close",
        line=dict(color="#2563eb", width=2),
    ))
    for ema_period, color in [(20, "#f59e0b"), (50, "#6366f1")]:
        ema = close_series.ewm(span=ema_period, adjust=False).mean()
        price_fig.add_trace(go.Scatter(
            x=deep_df.index, y=ema,
            mode="lines", name=f"EMA{ema_period}",
            line=dict(color=color, width=1, dash="dot"),
        ))
    price_fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        legend=dict(orientation="h", x=0, y=1.12),
        xaxis_title="", yaxis_title="Price (₹)",
    )
    st.plotly_chart(price_fig, use_container_width=True)

    # Volume chart
    if "Volume" in deep_df.columns:
        vol_series = deep_df["Volume"]
        avg_vol = vol_series.tail(20).mean()
        vol_colors = ["#16a34a" if v >= avg_vol else "#9ca3af" for v in vol_series]
        vol_fig = go.Figure()
        vol_fig.add_trace(go.Bar(
            x=deep_df.index, y=vol_series,
            name="Volume", marker_color=vol_colors,
        ))
        vol_fig.add_hline(
            y=avg_vol, line_dash="dot", line_color="#f59e0b",
            annotation_text=f"20D Avg: {avg_vol:,.0f}",
        )
        vol_fig.update_layout(
            height=200, margin=dict(l=10, r=10, t=10, b=10),
            xaxis_title="", yaxis_title="Volume",
            showlegend=False,
        )
        st.plotly_chart(vol_fig, use_container_width=True)
else:
    st.info("No price history available for this symbol.")

# ─── News & Market Context Tabs ───────────────────────────────────────────────

tabs_list = ["Stock News (Yahoo Finance)", "India Market News", "US/Global News", "Raw Data"]
tab_stock, tab_india, tab_global, tab_raw = st.tabs(tabs_list)

with tab_stock:
    with st.spinner("Loading stock news..."):
        yf_news = fetch_yf_news(deep_symbol)

    if not yf_news:
        st.info("No recent news found for this symbol on Yahoo Finance.")
    else:
        st.caption(f"{len(yf_news)} articles from Yahoo Finance")
        for item in yf_news[:15]:
            with st.container(border=True):
                title     = item.get("title", "").strip()
                link      = item.get("link", "") or item.get("url", "")
                publisher = item.get("publisher", "")
                ts        = item.get("providerPublishTime")
                dt_txt    = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                    if ts else "Unknown time"
                )
                thumbnail = item.get("thumbnail", {})
                thumb_url = ""
                if thumbnail and isinstance(thumbnail, dict):
                    resols = thumbnail.get("resolutions", [])
                    if resols:
                        thumb_url = resols[0].get("url", "")

                if thumb_url:
                    col_img, col_text = st.columns([1, 5])
                    with col_img:
                        st.image(thumb_url, width=80)
                    with col_text:
                        st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                        st.caption(f"{publisher} · {dt_txt}")
                else:
                    st.markdown(f"**[{title}]({link})**" if link else f"**{title}**")
                    st.caption(f"{publisher} · {dt_txt}")

with tab_india:
    if _PAID_PROVIDERS and EODHD_API_KEY and not eodhd_eod_only:
        with st.spinner("Loading India market news from EODHD..."):
            india_news = fetch_eodhd_market_news(EODHD_API_KEY, days_back=7)
        if india_news.empty:
            st.info("No India market news available from EODHD.")
        else:
            for _, row in india_news.head(20).iterrows():
                with st.container(border=True):
                    headline = str(row.get("headline", "")).strip()
                    url      = str(row.get("url", "")).strip()
                    source   = str(row.get("source", "")).strip()
                    dt       = pd.to_datetime(row.get("datetime"), errors="coerce")
                    dt_txt   = "Unknown time" if pd.isna(dt) else dt.strftime("%Y-%m-%d %H:%M")
                    st.markdown(f"**[{headline}]({url})**" if url else f"**{headline}**")
                    st.caption(f"{source} · {dt_txt}")
    else:
        st.info(
            "India market news requires an EODHD API key with news access (paid plan). "
            "Stock-specific news above is available free via Yahoo Finance."
        )

with tab_global:
    if _PAID_PROVIDERS and FINNHUB_API_KEY:
        with st.spinner("Loading US/global market news from Finnhub..."):
            market_news = fetch_finnhub_market_news(FINNHUB_API_KEY, category="general")
        if market_news.empty:
            st.info("No US/global market news available from Finnhub.")
        else:
            for _, row in market_news.head(20).iterrows():
                with st.container(border=True):
                    headline = str(row.get("headline", "")).strip()
                    url      = str(row.get("url", "")).strip()
                    source   = str(row.get("source", "")).strip()
                    dt       = pd.to_datetime(row.get("datetime"), errors="coerce")
                    dt_txt   = "Unknown time" if pd.isna(dt) else dt.strftime("%Y-%m-%d %H:%M")
                    st.markdown(f"**[{headline}]({url})**" if url else f"**{headline}**")
                    st.caption(f"{source} · {dt_txt}")
    else:
        st.info("US/global market news requires a Finnhub API key.")

with tab_raw:
    st.caption(f"Raw yfinance .info payload for {deep_symbol}")
    # Filter to interesting fields, show all in expander
    key_fields = {k: deep_info.get(k) for k in [
        "longName", "sector", "industry", "country", "exchange",
        "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
        "trailingEps", "forwardEps", "bookValue",
        "revenueGrowth", "earningsGrowth", "grossMargins", "operatingMargins", "profitMargins",
        "returnOnEquity", "returnOnAssets", "debtToEquity", "currentRatio", "quickRatio",
        "beta", "dividendYield", "payoutRatio",
        "marketCap", "enterpriseValue", "totalRevenue", "totalDebt", "freeCashflow",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyDayAverage", "twoHundredDayAverage",
        "recommendationKey", "targetMeanPrice", "targetHighPrice", "targetLowPrice", "numberOfAnalystOpinions",
        "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk",
    ] if k in deep_info}
    st.json(key_fields)
    with st.expander("Full raw payload", expanded=False):
        st.json(deep_info)
