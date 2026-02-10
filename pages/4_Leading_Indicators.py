import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from data_fetch import (
    batch_download,
    fetch_fred_series,
    prepare_timeseries_for_chart
)
from config import FRED_API_KEY  # ✅ FIXED: Import from config

st.set_page_config(layout="wide")
st.title("📊 Leading Indicators Dashboard")

st.divider()

st.caption(
    "Early signals of market direction based on liquidity, yields, "
    "currency strength and risk assets."
)
SIGNAL_EXPLANATIONS = {
    "Copper/Gold Positive":
        "Copper outperforming Gold → Growth expectations rising, risk appetite improving.",
    "Copper/Gold Defensive":
        "Gold outperforming Copper → Markets turning defensive, growth concerns rising.",

    "Credit Risk On":
        "High yield bonds outperforming → Investors comfortable taking risk.",
    "Credit Risk Off":
        "Investment grade outperforming → Credit stress rising, risk appetite falling.",

    "Yield Curve Positive":
        "Normal yield curve → Growth supportive environment.",
    "Yield Curve Inverted":
        "Inverted curve → Historically precedes recessions and equity volatility.",

    "Dollar Rising":
        "Stronger dollar tightens global liquidity and pressures risk assets.",
    "Dollar Stable":
        "Stable or weakening dollar supports equities and commodities.",

    "Equities Strong":
        "Markets trading above trend → Positive momentum environment.",
    "Equities Weak":
        "Markets below trend → Weak momentum or consolidation phase."
}

# ================= CONFIG =================

# FRED_API_KEY now imported from config.py

MARKET_SYMBOLS = {
    "^IXIC": "NASDAQ",
    "^NSEI": "NIFTY 50",
    "DX-Y.NYB": "Dollar Index",
    "USDINR=X": "USD/INR",
    "GC=F": "Gold",
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield"
}

FRED_SERIES = {
    "Fed Balance Sheet": "WALCL",
    "Reverse Repo": "RRPONTSYD",
    "Treasury General Account": "WTREGEN"
}

LEADING_SYMBOLS = {
    "HG=F": "Copper",
    "GC=F": "Gold",
    "HYG": "High Yield Bonds (HYG)",
    "LQD": "Investment Grade Bonds (LQD)",
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield",
    "^NSEI": "NIFTY 50",
    "DX-Y.NYB": "Dollar Index"
}

# ================= FETCH DATA =================

ALL_SYMBOLS = list(set(MARKET_SYMBOLS.keys()) | set(LEADING_SYMBOLS.keys()))

with st.spinner("Fetching market data..."):
    all_data = batch_download(ALL_SYMBOLS, period="6mo")

market_data = {k: all_data.get(k) for k in MARKET_SYMBOLS}
data = {k: all_data.get(k) for k in LEADING_SYMBOLS}


# ✅ FIXED: Check if critical symbols loaded
missing_symbols = []
for symbol in ["HYG", "LQD"]:
    if symbol not in data or data[symbol] is None or len(data.get(symbol, [])) == 0:
        missing_symbols.append(symbol)

if missing_symbols:
    st.error(f"⚠️ Critical symbols not loaded: {', '.join(missing_symbols)}")
    st.info("💡 **Troubleshooting**:\n"
            "1. Check if data_fetch.py validates plain tickers (HYG, LQD)\n"
            "2. Verify symbols are valid on Yahoo Finance\n"
            "3. Check internet connection")

liquidity_data = {}

if FRED_API_KEY:
    with st.spinner("Fetching liquidity data..."):
        for name, series in FRED_SERIES.items():
            liquidity_data[name] = fetch_fred_series(series, FRED_API_KEY, days=90)
else:
    st.warning("⚠️ FRED API key not found in config.py. Liquidity indicators disabled.")
    st.info("Liquidity indicators require a FRED API key.")

# ✅ FIXED: Better debug output
with st.expander("🔍 Data Loading Debug", expanded=False):
    st.write("**Symbol Loading Status:**")
    for symbol, name in LEADING_SYMBOLS.items():
        df = data.get(symbol)
        if df is not None and len(df) > 0:
            st.write(f"✅ {name:30s}: {len(df)} rows")
        else:
            st.write(f"❌ {name:30s}: No data")

    # Specific debug for credit spread
    st.markdown("---")
    st.write("**Credit Spread Debug:**")
    hyg = data.get("HYG")
    lqd = data.get("LQD")
    if hyg is not None and "Close" in hyg.columns:
        st.write(f"HYG: {len(hyg)} rows, latest close: ${hyg['Close'].iloc[-1]:.2f}")
    else:
        st.write("HYG: ❌ Not loaded or missing Close column")

    if lqd is not None and "Close" in lqd.columns:
        st.write(f"LQD: {len(lqd)} rows, latest close: ${lqd['Close'].iloc[-1]:.2f}")
    else:
        st.write("LQD: ❌ Not loaded Not loaded or missing Close column")


# ================= HELPER FUNCTIONS =================

def get_last_valid_close(df):
    if df is None or "Close" not in df.columns:
        return None
    series = df["Close"].dropna()
    return series.iloc[-1] if len(series) else None


def copper_gold_signal(data):
    copper = data.get("HG=F")
    gold = data.get("GC=F")

    if copper is None or gold is None:
        return None, None

    if "Close" not in copper.columns or "Close" not in gold.columns:
        return None, None

    df = pd.concat(
        [copper["Close"].rename("copper"),
         gold["Close"].rename("gold")],
        axis=1
    ).ffill().dropna()

    if len(df) < 15:
        return None, None

    ratio = df["copper"] / df["gold"]
    ma = ratio.rolling(10).mean()

    latest_ratio = ratio.iloc[-1]
    latest_ma = ma.iloc[-1]

    score = 1 if latest_ratio > latest_ma else -1
    return latest_ratio, score


def credit_spread_signal(data):
    hyg = data.get("HYG")
    lqd = data.get("LQD")

    if hyg is None or lqd is None:
        return None, None

    if "Close" not in hyg.columns or "Close" not in lqd.columns:
        return None, None

    # Align dates safely
    df = pd.concat(
        [hyg["Close"].rename("hyg"), lqd["Close"].rename("lqd")],
        axis=1
    )

    # Forward fill gaps and drop rows where both missing
    df = df.ffill().dropna()

    if len(df) < 15:
        return None, None

    ratio = df["hyg"] / df["lqd"]

    # Remove inf or bad values
    ratio = ratio.replace([float("inf"), -float("inf")], pd.NA).dropna()

    if len(ratio) < 10:
        return None, None

    ma = ratio.rolling(10).mean()

    latest_ratio = ratio.iloc[-1]
    latest_ma = ma.iloc[-1]

    score = 1 if latest_ratio > latest_ma else -1

    return latest_ratio, score

def dollar_trend_signal(market_data):
    dxy = market_data.get("DX-Y.NYB")

    if dxy is None or len(dxy) < 10:
        return None, None

    latest = dxy["Close"].iloc[-1]
    ma = dxy["Close"].rolling(10).mean().iloc[-1]

    score = -1 if latest > ma else 1  # Rising dollar = risk off
    return latest, score


def yield_trend_signal(market_data):
    y10 = market_data.get("^TNX")

    if y10 is None or len(y10) < 10:
        return None, None

    latest = y10["Close"].iloc[-1]
    ma = y10["Close"].rolling(10).mean().iloc[-1]

    score = -1 if latest > ma else 1  # Rising yields tighten conditions
    return latest, score

# ================= YIELD CURVE =================

st.subheader("Yield Curve Signal")

yield_10y = market_data.get("^TNX")
yield_3m = market_data.get("^IRX")

y10 = get_last_valid_close(yield_10y)
y3m = get_last_valid_close(yield_3m)

if y10 is None or y3m is None:
    st.warning("Yield data unavailable.")
else:
    curve = y10 - y3m
    if curve > 0:
        st.success(f"Yield Curve Normal (+{curve:.2f})")
        st.caption(SIGNAL_EXPLANATIONS["Yield Curve Positive"])
    else:
        st.error(f"Yield Curve Inverted ({curve:.2f})")
        st.caption(SIGNAL_EXPLANATIONS["Yield Curve Inverted"])

# ================= MACRO RISK SIGNALS =================

st.subheader("Macro Risk Signals")

ratio_cg, cg_score = copper_gold_signal(data)
ratio_credit, credit_score = credit_spread_signal(data)
dxy_value, dxy_score = dollar_trend_signal(market_data)
yield_value, yield_score = yield_trend_signal(market_data)

col1, col2 = st.columns(2)
col3, col4 = st.columns(2)

with col1:
    if ratio_cg is not None:
        label = "Copper/Gold Positive" if cg_score == 1 else "Copper/Gold Defensive"
        st.metric("Copper / Gold Ratio", f"{ratio_cg:.4f}")
        st.caption(SIGNAL_EXPLANATIONS[label])

with col2:
    if ratio_credit is not None:
        label = "Credit Risk On" if credit_score == 1 else "Credit Risk Off"
        st.metric("HYG / LQD Ratio", f"{ratio_credit:.3f}")
        st.caption(SIGNAL_EXPLANATIONS[label])

with col3:
    if dxy_value is not None:
        label = "Dollar Rising" if dxy_score == -1 else "Dollar Stable"
        st.metric("Dollar Index", f"{dxy_value:.2f}")
        st.caption(SIGNAL_EXPLANATIONS[label])

with col4:
    if yield_value is not None:
        trend = "Rising Yields (Tightening)" if yield_score == -1 else "Stable/Falling Yields"
        st.metric("US 10Y Yield", f"{yield_value:.2f}")
        st.caption("Rising yields tighten financial conditions and pressure equities.")


# ================= LIQUIDITY TREND =================

st.subheader("Liquidity Trend")

liquidity_shown = False

for name, df in liquidity_data.items():
    if df is not None and len(df) > 0 and {"date", "value"}.issubset(df.columns):
        liquidity_shown = True
        with st.expander(name):
            st.line_chart(df.set_index("date")["value"])

if not liquidity_shown:
    st.caption("No liquidity data available.")


# ================= MARKET LEADING INDICATORS =================

st.subheader("Market Leading Indicators")

for symbol, label in MARKET_SYMBOLS.items():
    df = market_data.get(symbol)
    if df is not None and len(df) > 0:
        df_chart = prepare_timeseries_for_chart(df)
        with st.expander(label):
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_chart.index,
                y=df_chart["Close"],
                mode="lines",
                name=label
            ))
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

st.subheader("Commodity & Credit Trends")

for symbol in ["HG=F", "GC=F", "HYG", "LQD"]:
    df = data.get(symbol)

    if df is not None and len(df) > 5 and "Close" in df.columns:
        df_chart = prepare_timeseries_for_chart(df)

        with st.expander(LEADING_SYMBOLS.get(symbol, symbol)):
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_chart.index,
                y=df_chart["Close"],
                mode="lines"
            ))
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)

st.subheader("Macro Ratio Trends")

# Copper / Gold Ratio Chart
copper = data.get("HG=F")
gold = data.get("GC=F")

if copper is not None and gold is not None:
    df_ratio = pd.concat(
        [copper["Close"].rename("copper"), gold["Close"].rename("gold")],
        axis=1
    ).ffill().dropna()

    df_ratio["ratio"] = df_ratio["copper"] / df_ratio["gold"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_ratio.index,
        y=df_ratio["ratio"],
        mode="lines",
        name="Copper/Gold"
    ))
    fig.update_layout(height=300, title="Copper / Gold Ratio Trend")
    st.plotly_chart(fig, use_container_width=True)

# HYG / LQD Ratio Chart
hyg = data.get("HYG")
lqd = data.get("LQD")

if hyg is not None and lqd is not None:
    df_ratio = pd.concat(
        [hyg["Close"].rename("hyg"), lqd["Close"].rename("lqd")],
        axis=1
    ).ffill().dropna()

    df_ratio["ratio"] = df_ratio["hyg"] / df_ratio["lqd"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_ratio.index,
        y=df_ratio["ratio"],
        mode="lines",
        name="HYG/LQD"
    ))
    fig.update_layout(height=300, title="HYG / LQD Credit Spread Trend")
    st.plotly_chart(fig, use_container_width=True)


# ================= LEADING SIGNAL SUMMARY =================

st.subheader("Leading Signal Summary")
st.info(
    "These signals help determine whether the market environment is "
    "Risk ON, Neutral, or Risk OFF. "
    "Credit, liquidity and macro indicators often lead equities."
)

signals = []

if y10 is not None and y3m is not None:
    signals.append("Yield Curve Positive" if (y10 - y3m) > 0 else "Yield Curve Inverted")

dxy = market_data.get("DX-Y.NYB")
if dxy is not None and len(dxy) > 5:
    signals.append("Dollar Rising" if dxy["Close"].iloc[-1] > dxy["Close"].iloc[-5] else "Dollar Stable")

nifty = market_data.get("^NSEI")
if nifty is not None and len(nifty) > 20:
    ma20 = nifty["Close"].rolling(20).mean().iloc[-1]
    signals.append("Equities Strong" if nifty["Close"].iloc[-1] > ma20 else "Equities Weak")

if cg_score is not None:
    signals.append("Copper/Gold Positive" if cg_score == 1 else "Copper/Gold Defensive")

if credit_score is not None:
    signals.append("Credit Risk On" if credit_score == 1 else "Credit Risk Off")

for s in signals:
    st.markdown(f"**• {s}**")
    explanation = SIGNAL_EXPLANATIONS.get(s)
    if explanation:
        st.caption(explanation)


# ================= IMPULSE GAUGE =================

st.subheader("Market Impulse Gauge")

impulse_score = 0
factors = 0

if y10 is not None and y3m is not None:
    impulse_score += 1 if (y10 - y3m) > 0 else -1
    factors += 1

if dxy is not None and len(dxy) > 5:
    impulse_score += -1 if dxy["Close"].iloc[-1] > dxy["Close"].iloc[-5] else 1
    factors += 1

if nifty is not None and len(nifty) > 20:
    ma20 = nifty["Close"].rolling(20).mean().iloc[-1]
    impulse_score += 1 if nifty["Close"].iloc[-1] > ma20 else -1
    factors += 1

fed = liquidity_data.get("Fed Balance Sheet")
if fed is not None and len(fed) > 1:
    impulse_score += 1 if fed["value"].iloc[-1] > fed["value"].iloc[-2] else -1
    factors += 1

if cg_score is not None:
    impulse_score += cg_score
    factors += 1

if credit_score is not None:
    impulse_score += credit_score
    factors += 1

normalized = impulse_score / factors if factors >= 3 else 0

fig = go.Figure(go.Indicator(
    mode="gauge+number",
    value=normalized,
    title={'text': "Market Impulse"},
    gauge={
        'axis': {'range': [-1, 1]},
        'steps': [
            {'range': [-1, -0.3], 'color': "red"},
            {'range': [-0.3, 0.3], 'color': "orange"},
            {'range': [0.3, 1], 'color': "green"},
        ],
    }
))

st.plotly_chart(fig, use_container_width=True)

# ================= FOOTER =================

st.markdown("---")
st.caption("Leading indicators help anticipate regime shifts before markets move.")