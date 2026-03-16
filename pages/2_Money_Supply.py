"""
Money Supply Dashboard - ENHANCED VERSION
Includes:
- Alerts & Insights for major liquidity shifts
- Educational tooltips and "How to Read" guide
- SOFR vs IORB spread (Banking Stress Indicator)
- Color-coded metrics for all FRED indicators
"""

import streamlit as st
import pandas as pd

from config import FRED_SERIES, FRED_API_KEY, LIQUIDITY_THRESHOLDS
from data_fetch import fetch_fred_series, batch_download
from india_context import get_india_macro_signals_v1
# ... other imports

from utils import setup_page, render_key_observations, get_ui_detail_mode, get_ui_device_mode, responsive_cols as _responsive_cols

setup_page("Liquidity & Money Supply")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"


# _responsive_cols imported from utils

# ==================== EDUCATIONAL GUIDE ====================

INDICATOR_GUIDE = {
    "WALCL": {
        "title": "Fed Balance Sheet (WALCL)",
        "logic": "Fed buys assets, injecting cash into banks.",
        "up": "🟢 Injection (Bullish)",
        "down": "🔴 Contraction (QT/Bearish)",
        "desc": "Represents the size of the Federal Reserve's balance sheet. Growth = More Liquidity."
    },
    "RRPONTSYD": {
        "title": "Reverse Repo Balance (RRP)",
        "logic": "Money 'parked' at the Fed, out of the system.",
        "up": "🔴 Draining (Bearish)",
        "down": "🟢 Releasing (Bullish)",
        "desc": "Money leaving the facility (balance falling) acts as a liquidity injection into the banking system."
    },
    "WTREGEN": {
        "title": "Treasury General Account (TGA)",
        "logic": "The government's 'checking account'.",
        "up": "🔴 Draining (Bearish)",
        "down": "🟢 Releasing (Bullish)",
        "desc": "Rising TGA (taxes/debt issuance) pulls liquidity. Falling TGA (Govt spending) releases it."
    },
    "SOFR": {
        "title": "SOFR Rate",
        "logic": "Cost of overnight interbank loans.",
        "up": "🔴 Stress (Funding tight)",
        "down": "🟢 Normal (Funding loose)",
        "desc": "The broad measure of the cost of borrowing cash overnight collateralized by Treasury securities."
    },
    "IORB": {
        "title": "Interest on Reserve Balances (IORB)",
        "logic": "Rate Fed pays banks on their reserves.",
        "up": "⚪ Neutral (Policy Floor)",
        "down": "⚪ Neutral",
        "desc": "Serves as a floor for the SOFR rate. If SOFR > IORB, it signals systemic cash scarcity."
    },
    "M2SL": {
        "title": "US M2 Money Supply",
        "logic": "Total money in circulation (cash, checking, etc).",
        "up": "🟢 Expansion (Bullish)",
        "down": "🔴 Contraction (Bearish)",
        "desc": "A foundational measure of money supply. Declines are extremely rare and signal severe tightening."
    },
    "DGS10": {
        "title": "US 10Y Treasury Yield",
        "logic": "The benchmark 'risk-free' rate.",
        "up": "🔴 Pressure (Risk Off)",
        "down": "🟢 Supportive (Risk On)",
        "desc": "Rising yields increase the cost of capital and put pressure on equity valuations."
    },
    "DFF": {
        "title": "Fed Funds Rate",
        "logic": "The Fed's primary policy lever.",
        "up": "🔴 Tightening (Bearish)",
        "down": "🟢 Easing (Bullish)",
        "desc": "The interest rate banks charge each other for overnight loans."
    }
}

st.title("💰 Liquidity & Money Supply Dashboard")
st.caption(f"Device mode: **{device_mode}**")

with st.expander("📖 Financial Plumbing Guide (How to read this)", expanded=False):
    st.markdown("""
    ### Understanding Global Liquidity
    *   **Net Liquidity Formula**: Roughly `(Fed Balance Sheet) - (TGA) - (Reverse Repo)`. 
    *   **SOFR/IORB Spread**: Keep an eye on the difference between SOFR and IORB. **If SOFR > IORB**, liquidity is scarce.
    *   **Risk On**: Liquidity is rising when the Fed expands (WALCL up) OR money leaves storage (TGA/RRP down).
    *   **Risk Off**: Liquidity is falling when the Fed shrinks (QT) OR money is sucked into TGA/RRP.
    """)
    
    st.markdown("#### Primary Indicators")
    cols = _responsive_cols(4)
    primary = ["WALCL", "RRPONTSYD", "WTREGEN", "SOFR"]
    for i, key in enumerate(primary):
        info = INDICATOR_GUIDE[key]
        with cols[i]:
            st.write(f"**{info['title']}**")
            st.caption(info['desc'])

st.markdown("---")

# ==================== API KEY CHECK ====================

if not FRED_API_KEY:
    st.error("⚠️ FRED API key not found in .env file")
    st.stop()

# ==================== FETCH DATA ====================

series_data = {}
alerts = []
stress_score = 0

with st.spinner("Analyzing liquidity data..."):
    for name, series_id in FRED_SERIES.items():
        df = fetch_fred_series(series_id, FRED_API_KEY, days=90)
        
        if df is not None and len(df) >= 2:
            latest = df["value"].iloc[-1]
            prev = df["value"].iloc[-2]
            
            # Weekly change for alerts
            weekly_prev = df["value"].iloc[-6] if len(df) >= 6 else df["value"].iloc[0]
            
            change_abs = latest - prev
            change_pct = (change_abs / prev) * 100 if prev != 0 else 0
            
            weekly_change_pct = ((latest - weekly_prev) / weekly_prev) * 100 if weekly_prev != 0 else 0
            weekly_change_abs = (latest - weekly_prev)
            
            series_data[series_id] = {
                "name": name,
                "df": df,
                "latest": latest,
                "change_pct": change_pct,
                "weekly_change_pct": weekly_change_pct,
                "date": df["date"].iloc[-1].date(),
                "id": series_id
            }
            
            # --- Alert Detection ---
            threshold = LIQUIDITY_THRESHOLDS.get(series_id, {})
            
            if series_id == "WALCL":
                if weekly_change_pct <= -threshold.get("weekly_pct", 1.0):
                    alerts.append(f"📉 **QT Alert**: Fed balance sheet shrinking (-{abs(weekly_change_pct):.2f}% this week).")
                    stress_score -= 1
                elif weekly_change_pct >= threshold.get("weekly_pct", 1.0):
                    alerts.append(f"🏦 **QE Alert**: Fed balance sheet expanding (+{weekly_change_pct:.2f}% this week).")
                    stress_score += 1
            
            if series_id == "SOFR" and abs(change_abs) >= threshold.get("absolute_change", 0.10):
                alerts.append(f"🚨 **SOFR Stress**: Interbank rates jumped {change_abs:+.2f}% today.")
                stress_score -= 2

            if series_id in ["WTREGEN", "RRPONTSYD"]:
                abs_change_bn = weekly_change_abs / 1000 if series_id == "WTREGEN" else weekly_change_abs
                if abs(abs_change_bn) >= threshold.get("weekly_abs", 50.0):
                    is_drain = weekly_change_abs > 0
                    impact = "Draining" if is_drain else "Releasing"
                    alerts.append(f"💧 **{name} {impact} Liquidity**: {abs_change_bn:+.1f}B shift this week.")
                    stress_score += (-1 if is_drain else 1)

# Use a single source of truth for US 10Y across all pages: Yahoo ^TNX
with st.spinner("Syncing US 10Y yield source..."):
    tnx_data = batch_download(["^TNX"], period="6mo")
tnx_df = tnx_data.get("^TNX")
if tnx_df is not None and not tnx_df.empty and "Close" in tnx_df.columns:
    tnx_close = tnx_df["Close"].dropna()
    if len(tnx_close) >= 2:
        tnx_series = pd.DataFrame(
            {"date": pd.to_datetime(tnx_close.index), "value": pd.to_numeric(tnx_close.values, errors="coerce")}
        ).dropna(subset=["value"])
        if len(tnx_series) >= 2:
            latest = tnx_series["value"].iloc[-1]
            prev = tnx_series["value"].iloc[-2]
            weekly_prev = tnx_series["value"].iloc[-6] if len(tnx_series) >= 6 else tnx_series["value"].iloc[0]
            change_abs = latest - prev
            change_pct = (change_abs / prev) * 100 if prev != 0 else 0
            weekly_change_pct = ((latest - weekly_prev) / weekly_prev) * 100 if weekly_prev != 0 else 0
            series_data["DGS10"] = {
                "name": "US 10Y Treasury Yield",
                "df": tnx_series,
                "latest": latest,
                "change_pct": change_pct,
                "weekly_change_pct": weekly_change_pct,
                "date": tnx_series["date"].iloc[-1].date(),
                "id": "DGS10",
            }

import analytics

# ==================== SOFR - IORB SPREAD ====================

spread = 0
if "SOFR" in series_data and "IORB" in series_data:
    sofr = series_data["SOFR"]["latest"]
    iorb = series_data["IORB"]["latest"]
    spread = (sofr - iorb) * 100 # bps
    
    if spread > 5:
        alerts.insert(0, f"🔥 **CRITICAL STRESS**: SOFR is {spread:.1f}bps ABOVE IORB. Banking reserves are extremely tight.")
    elif spread > 0:
        alerts.append(f"🟡 **Liquidity Tightening**: SOFR ({sofr:.3f}%) higher than IORB ({iorb:.3f}%).")

# ==================== AUTOMATED STANCE ====================

# Prepare data for analytics
liq_dfs = {
    "Fed Balance Sheet": series_data.get("WALCL", {}).get("df"),
    "Reverse Repo": series_data.get("RRPONTSYD", {}).get("df"),
    "Treasury General Account": series_data.get("WTREGEN", {}).get("df")
}

regime, color, decision_msg = analytics.get_liquidity_stance(liq_dfs, sofr_spread=spread)

# ==================== SUMMARY & ALERTS ====================

col_l, col_r = _responsive_cols(2, [1, 1])

with col_l:
    st.subheader("🏁 Automated Market Stance")
    
    if color == "success":
        st.success(f"### {regime}")
    elif color == "error":
        st.error(f"### {regime}")
    elif color == "warning":
        st.warning(f"### {regime}")
    else:
        st.info(f"### {regime}")
        
    st.markdown(f"> {decision_msg}")

with col_r:
    if alerts:
        render_key_observations(alerts, title="🔎 Key Observations")
    else:
        st.subheader("✅ Alert Status")
        st.write("Liquidity plumbing appears stable.")

st.markdown("---")

observations = []
if regime:
    observations.append(f"Liquidity stance: {regime.replace('###', '').strip()}")
for alert in alerts[:3]:
    observations.append(alert.replace("**", ""))
if "DGS10" in series_data:
    dgs = series_data["DGS10"]
    observations.append(f"US 10Y daily move: {dgs['change_pct']:+.2f}%")
if view_mode == "Detail":
    render_key_observations(observations, title="🔎 Summary Tape")

# ==================== METRICS GRID ====================

with st.expander("📊 Full Liquidity Pulse (Expand)", expanded=False):
    grid_cols = _responsive_cols(4)
    for i, (sid, data) in enumerate(series_data.items()):
        info = INDICATOR_GUIDE.get(sid, {"desc": "Federal Reserve Data", "title": data["name"]})

        is_positive_liquidity = True
        if sid in ["WTREGEN", "RRPONTSYD", "SOFR", "DGS10", "DFF"] and data["change_pct"] > 0:
            is_positive_liquidity = False
        elif sid in ["WALCL", "M2SL"] and data["change_pct"] < 0:
            is_positive_liquidity = False

        val_str = f"{data['latest']:,.2f}"
        if sid in ["SOFR", "IORB", "DGS10", "DFF"]:
            val_str += "%"
        elif sid in ["M2SL"]:
            val_str = f"${data['latest']:,.0f}B"

        with grid_cols[i % 4]:
            st.metric(
                label=data["name"],
                value=val_str,
                delta=f"{data['change_pct']:+.2f}% (Daily)",
                delta_color="normal" if is_positive_liquidity else "inverse",
                help=info["desc"]
            )
            st.caption(f"📅 {data['date']}")

# ==================== TREND CHARTS ====================
st.markdown("---")
with st.expander("📈 Historical Trends (90 Days) (Expand)", expanded=(view_mode == "Detail")):
    if series_data:
        chart_cols = _responsive_cols(2)
        display_charts = ["WALCL", "RRPONTSYD", "WTREGEN", "SOFR", "M2SL", "DFF"]

        chart_idx = 0
        for sid in display_charts:
            if sid in series_data:
                data = series_data[sid]
                with chart_cols[chart_idx % 2]:
                    st.write(f"**{data['name']} Trend**")
                    df_chart = data["df"].set_index("date")
                    st.line_chart(df_chart["value"], height=200)
                    chart_idx += 1
    else:
        st.info("No trend data available")

if view_mode == "Detail":
    meta_rows = []
    for sid, payload in series_data.items():
        src = "Yahoo (^TNX)" if sid == "DGS10" else "FRED"
        meta_rows.append(
            {
                "Factor": payload.get("name", sid),
                "Series": sid,
                "Source": src,
                "As Of": str(payload.get("date", "")),
                "Freshness": "Close-only",
            }
        )
    if meta_rows:
        st.markdown("#### Source & Freshness")
        st.dataframe(pd.DataFrame(meta_rows), width="stretch", hide_index=True)

with st.expander("🇮🇳 India Domestic Cross-Check (Context Only - Not in Liquidity Score)", expanded=False):
    ctx = get_india_macro_signals_v1()
    flows = ctx.get("flows", {})
    vix_ctx = ctx.get("vix", {})
    breadth_ctx = ctx.get("breadth", {})
    curve_ctx = ctx.get("curve", {})
    gst_ctx = ctx.get("gst", {})

    c1, c2, c3 = _responsive_cols(3)
    with c1:
        fii = flows.get("fii_net")
        dii = flows.get("dii_net")
        st.metric("FII / DII Net (Daily)", "N/A" if fii is None else f"{fii:,.0f} / {dii:,.0f} Cr")
        st.caption(f"{flows.get('status', 'STALE')} | {flows.get('as_of', 'N/A')}")
    with c2:
        dom = flows.get("fii_dii_dominance")
        st.metric("FII Dominance", "N/A" if dom is None else f"{dom:+.2f}")
        st.caption("FII/(|FII|+|DII|)")
    with c3:
        vix_val = vix_ctx.get("value")
        st.metric("India VIX", "N/A" if vix_val is None else f"{vix_val:.2f}")
        st.caption(f"{vix_ctx.get('status', 'STALE')} | {vix_ctx.get('source', 'NSE')}")

    d1, d2, d3 = _responsive_cols(3)
    with d1:
        st.metric(
            "A/D Breadth",
            f"{breadth_ctx.get('advances', 'N/A')}:{breadth_ctx.get('declines', 'N/A')}",
            None if breadth_ctx.get("ratio") is None else f"{float(breadth_ctx.get('ratio')):.2f}",
        )
        st.caption(f"{breadth_ctx.get('status', 'STALE')} | {breadth_ctx.get('as_of', 'N/A')}")
    with d2:
        curve_value = curve_ctx.get("value")
        st.metric("India Curve (10Y-3M)", "N/A" if curve_value is None else f"{float(curve_value):+.2f}")
        st.caption(f"{curve_ctx.get('status', 'UNAVAILABLE')} | {curve_ctx.get('source', 'pending')}")
    with d3:
        gst_yoy = gst_ctx.get("gst_yoy")
        st.metric("GST YoY", "N/A" if gst_yoy is None else f"{float(gst_yoy):+.1f}%")
        st.caption(f"{gst_ctx.get('status', 'UNAVAILABLE')} | {gst_ctx.get('source', 'pending')}")

    st.page_link("pages/13_India_Macro_Context.py", label="View Detailed India Macro Context", icon="🇮🇳")
    st.info("Cross-check only. These India-specific signals are not part of Liquidity score in Phase A.")

st.markdown("---")
st.caption("Data source: FRED for liquidity series; US 10Y synchronized to Yahoo ^TNX (same as other dashboards). Values: WALCL/TGA in $M, RRP in $B, SOFR/Rates in %. | Net Liquidity View.")
