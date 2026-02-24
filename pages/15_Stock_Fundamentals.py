import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import importlib.util

import watchlist_manager as wm
from NSE_Config import PRESET_WATCHLISTS
from config import EODHD_API_KEY, FINNHUB_API_KEY
from data_fetch import (
    batch_download,
    fetch_eodhd_market_news,
    fetch_equity_fundamentals_batch,
    fetch_equity_stock_news,
    fetch_finnhub_market_news,
    is_eodhd_eod_only,
    probe_market_data_providers,
)
from utils import get_ui_detail_mode, setup_page


setup_page("Stock EOD Profile")
_ = get_ui_detail_mode("Summary")

st.title("🏛️ Stock EOD Profile")
st.caption("EOD-first stock profile. Fundamentals/news require non-EOD-only provider access.")

eodhd_eod_only = is_eodhd_eod_only(EODHD_API_KEY) if EODHD_API_KEY else False
if eodhd_eod_only:
    st.warning("EODHD key is EOD-only. Fundamentals/news endpoints are blocked on this plan; using fallback providers where available.")

if not EODHD_API_KEY and not FINNHUB_API_KEY:
    st.error("No provider key found. Add EODHD_API_KEY and/or FINNHUB_API_KEY in .env.")
    st.stop()

if FINNHUB_API_KEY and importlib.util.find_spec("finnhub") is None and not EODHD_API_KEY:
    st.error("`finnhub-python` package is not installed in the active environment.")
    st.code("pip install finnhub-python", language="bash")
    st.stop()

diag = probe_market_data_providers(
    finnhub_api_key=FINNHUB_API_KEY,
    eodhd_api_key=EODHD_API_KEY,
    india_symbol_ns="INFY.NS",
    us_symbol="AAPL",
)
finnhub_ok = bool((diag.get("finnhub", {}) or {}).get("ok"))

with st.expander("Provider Diagnostics", expanded=False):
    rows = []
    for name in ["eodhd", "finnhub"]:
        d = diag.get(name, {})
        rows.append(
            {
                "provider": name.upper(),
                "configured": bool(d.get("configured")),
                "ok": bool(d.get("ok")),
                "status_code": d.get("status_code"),
                "eod_only": bool(d.get("eod_only")) if name == "eodhd" else False,
                "message": d.get("message"),
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

watchlists = wm.load_watchlists()
wl_names = sorted(list(watchlists.keys()))
default_wl = "Top 20 by Market Cap" if "Top 20 by Market Cap" in watchlists else (wl_names[0] if wl_names else "")

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

if eodhd_eod_only and not finnhub_ok:
    st.markdown("### EOD Snapshot Comparison")
    with st.spinner("Fetching EOD price history..."):
        history_map = batch_download(selected_symbols, period="6mo")

    def _pct(series: pd.Series, bars: int):
        try:
            s = pd.to_numeric(series, errors="coerce").dropna()
            if len(s) <= bars:
                return None
            return float((s.iloc[-1] / s.iloc[-(bars + 1)] - 1.0) * 100.0)
        except Exception:
            return None

    rows = []
    for sym in selected_symbols:
        df = history_map.get(sym)
        if df is None or df.empty or "Close" not in df.columns:
            rows.append({"Symbol": sym, "Last Close": None, "1D %": None, "1W %": None, "1M %": None, "3M %": None, "6M %": None, "20D Avg Vol": None})
            continue
        close = pd.to_numeric(df.get("Close"), errors="coerce")
        vol = pd.to_numeric(df.get("Volume"), errors="coerce") if "Volume" in df.columns else pd.Series(dtype="float64")
        rows.append(
            {
                "Symbol": sym,
                "Last Close": float(close.dropna().iloc[-1]) if not close.dropna().empty else None,
                "1D %": _pct(close, 1),
                "1W %": _pct(close, 5),
                "1M %": _pct(close, 21),
                "3M %": _pct(close, 63),
                "6M %": _pct(close, 126),
                "20D Avg Vol": float(vol.dropna().tail(20).mean()) if not vol.dropna().empty else None,
            }
        )
    eod_table = pd.DataFrame(rows)
    st.dataframe(
        eod_table.style.format(
            {
                "Last Close": "{:,.2f}",
                "1D %": "{:+.2f}%",
                "1W %": "{:+.2f}%",
                "1M %": "{:+.2f}%",
                "3M %": "{:+.2f}%",
                "6M %": "{:+.2f}%",
                "20D Avg Vol": "{:,.0f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    st.markdown("### Stock Deep Dive")
    deep_symbol = st.selectbox("Select Stock", selected_symbols, index=0)
    deep_df = history_map.get(deep_symbol)
    if deep_df is None or deep_df.empty:
        st.info("No EOD history found for selected symbol.")
        st.stop()
    d1, d2, d3, d4 = st.columns(4)
    c = pd.to_numeric(deep_df.get("Close"), errors="coerce").dropna()
    v = pd.to_numeric(deep_df.get("Volume"), errors="coerce").dropna() if "Volume" in deep_df.columns else pd.Series(dtype="float64")
    with d1:
        st.metric("Last Close", f"{float(c.iloc[-1]):,.2f}" if not c.empty else "N/A")
    with d2:
        one_day = _pct(c, 1)
        st.metric("1D Change", f"{one_day:+.2f}%" if one_day is not None else "N/A")
    with d3:
        st.metric("52W High", f"{float(c.tail(252).max()):,.2f}" if not c.empty else "N/A")
    with d4:
        st.metric("52W Low", f"{float(c.tail(252).min()):,.2f}" if not c.empty else "N/A")

    price_fig = go.Figure()
    price_fig.add_trace(go.Scatter(x=deep_df.index, y=deep_df["Close"], mode="lines", name="Close"))
    price_fig.update_layout(height=320, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="", yaxis_title="Price")
    st.plotly_chart(price_fig, width="stretch")

    if not v.empty:
        vol_fig = go.Figure()
        vol_fig.add_trace(go.Bar(x=deep_df.index, y=deep_df["Volume"], name="Volume"))
        vol_fig.update_layout(height=220, margin=dict(l=20, r=20, t=20, b=20), xaxis_title="", yaxis_title="Volume")
        st.plotly_chart(vol_fig, width="stretch")

    st.info("Provider note: EODHD free key supports EOD price data only. Use News Feed page for headlines.")
    st.stop()

with st.spinner("Fetching fundamentals..."):
    fundamentals_map = fetch_equity_fundamentals_batch(
        selected_symbols,
        finnhub_api_key=FINNHUB_API_KEY,
        eodhd_api_key=EODHD_API_KEY,
    )

DISPLAY_ROWS = [
    ("P/E", "peBasicExclExtraTTM"),
    ("P/B", "pbAnnual"),
    ("EPS (TTM)", "epsBasicExclExtraItemsTTM"),
    ("Revenue Growth YoY", "revenueGrowthTTMYoy"),
    ("Gross Margin", "grossMarginTTM"),
    ("Debt/Equity", "debtEquityAnnual"),
    ("Dividend Yield", "dividendYieldIndicatedAnnual"),
    ("Beta", "beta"),
]

table = pd.DataFrame(index=[x[0] for x in DISPLAY_ROWS], columns=selected_symbols)
for sym in selected_symbols:
    f = fundamentals_map.get(sym, {}) or {}
    for row_name, key in DISPLAY_ROWS:
        table.loc[row_name, sym] = f.get(key)


def _style_cell(metric: str, val):
    try:
        v = float(val)
    except Exception:
        return ""
    good = False
    bad = False
    if metric == "P/E":
        good, bad = v < 25, v > 45
    elif metric == "P/B":
        good, bad = v < 4, v > 8
    elif metric == "Debt/Equity":
        good, bad = v < 1, v > 2
    elif metric == "Revenue Growth YoY":
        good, bad = v > 0, v < 0
    elif metric == "Gross Margin":
        good, bad = v > 20, v < 10
    elif metric == "Dividend Yield":
        good, bad = v > 1.0, v < 0.5
    elif metric == "Beta":
        good, bad = 0.6 <= v <= 1.4, v > 2.0
    if good:
        return "background-color: #dcfce7;"
    if bad:
        return "background-color: #fee2e2;"
    return ""


def _style_df(df: pd.DataFrame):
    style_df = pd.DataFrame("", index=df.index, columns=df.columns)
    for idx in df.index:
        for col in df.columns:
            style_df.loc[idx, col] = _style_cell(idx, df.loc[idx, col])
    return style_df


st.markdown("### Fundamentals Comparison")
styled = table.style.format(precision=2).apply(lambda _: _style_df(table), axis=None)
st.dataframe(styled, width="stretch")

st.markdown("---")
st.markdown("### Stock Deep Dive")
deep_symbol = st.selectbox("Select Stock", selected_symbols, index=0)
deep_f = fundamentals_map.get(deep_symbol, {}) or {}

d1, d2, d3, d4 = st.columns(4)
with d1:
    st.metric("P/E", f"{float(deep_f.get('peBasicExclExtraTTM')):.2f}" if deep_f.get("peBasicExclExtraTTM") is not None else "N/A")
with d2:
    st.metric("EPS", f"{float(deep_f.get('epsBasicExclExtraItemsTTM')):.2f}" if deep_f.get("epsBasicExclExtraItemsTTM") is not None else "N/A")
with d3:
    st.metric("D/E", f"{float(deep_f.get('debtEquityAnnual')):.2f}" if deep_f.get("debtEquityAnnual") is not None else "N/A")
with d4:
    st.metric("Beta", f"{float(deep_f.get('beta')):.2f}" if deep_f.get("beta") is not None else "N/A")

high_52 = deep_f.get("52WeekHigh")
low_52 = deep_f.get("52WeekLow")
if high_52 is not None and low_52 is not None:
    try:
        low_52 = float(low_52)
        high_52 = float(high_52)
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=[high_52 - low_52],
                y=["52W Range"],
                orientation="h",
                base=[low_52],
                marker_color="#60a5fa",
                name="Range",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[low_52, high_52],
                y=["52W Range", "52W Range"],
                mode="markers+text",
                text=[f"Low {low_52:.2f}", f"High {high_52:.2f}"],
                textposition="top center",
                marker=dict(size=10, color=["#ef4444", "#10b981"]),
                showlegend=False,
            )
        )
        fig.update_layout(height=180, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig, width="stretch")
    except Exception:
        pass

with st.spinner("Loading stock news..."):
    stock_news = fetch_equity_stock_news(
        deep_symbol,
        finnhub_api_key=FINNHUB_API_KEY,
        eodhd_api_key=EODHD_API_KEY,
        days_back=7,
    )

st.markdown("#### Recent Stock News (7D)")
if stock_news.empty:
    st.info("No stock news found for selected symbol.")
else:
    for _, row in stock_news.head(12).iterrows():
        with st.container(border=True):
            headline = str(row.get("headline", "")).strip()
            url = str(row.get("url", "")).strip()
            source = str(row.get("source", "")).strip()
            dt = pd.to_datetime(row.get("datetime"), errors="coerce")
            dt_txt = "Unknown time" if pd.isna(dt) else dt.strftime("%Y-%m-%d %H:%M")
            if url:
                st.markdown(f"**[{headline}]({url})**")
            else:
                st.markdown(f"**{headline}**")
            st.caption(f"{source} · {dt_txt}")

tab1, tab2, tab3 = st.tabs(["India Market News (EODHD)", "US/Global Market News (Finnhub)", "Raw Fundamentals"])
with tab1:
    with st.spinner("Loading India market news..."):
        india_news = (
            fetch_eodhd_market_news(EODHD_API_KEY, days_back=7)
            if EODHD_API_KEY and not eodhd_eod_only
            else pd.DataFrame()
        )
    if india_news.empty:
        if eodhd_eod_only:
            st.info("India Market News unavailable: EODHD free plan is EOD-only (news endpoint blocked).")
        else:
            st.info("No India market news available from EODHD.")
    else:
        for _, row in india_news.head(20).iterrows():
            with st.container(border=True):
                headline = str(row.get("headline", "")).strip()
                url = str(row.get("url", "")).strip()
                source = str(row.get("source", "")).strip()
                dt = pd.to_datetime(row.get("datetime"), errors="coerce")
                dt_txt = "Unknown time" if pd.isna(dt) else dt.strftime("%Y-%m-%d %H:%M")
                st.markdown(f"**[{headline}]({url})**" if url else f"**{headline}**")
                st.caption(f"{source} · {dt_txt}")
with tab2:
    with st.spinner("Loading US/global market news..."):
        market_news = fetch_finnhub_market_news(FINNHUB_API_KEY, category="general") if FINNHUB_API_KEY else pd.DataFrame()
    if market_news.empty:
        st.info("No US/global market news available from Finnhub.")
    else:
        for _, row in market_news.head(20).iterrows():
            with st.container(border=True):
                headline = str(row.get("headline", "")).strip()
                url = str(row.get("url", "")).strip()
                source = str(row.get("source", "")).strip()
                dt = pd.to_datetime(row.get("datetime"), errors="coerce")
                dt_txt = "Unknown time" if pd.isna(dt) else dt.strftime("%Y-%m-%d %H:%M")
                st.markdown(f"**[{headline}]({url})**" if url else f"**{headline}**")
                st.caption(f"{source} · {dt_txt}")
with tab3:
    st.json(deep_f)
