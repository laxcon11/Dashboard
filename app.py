import streamlit as st
from utils import setup_page, get_ui_detail_mode
from data_fetch import quick_data_health_summary
from factor_registry import FACTOR_REGISTRY
from config import RSS_FEEDS
from data_fetch import fetch_rss_feeds
from pathlib import Path
import json

setup_page("Dashboard Launcher")
view_mode = get_ui_detail_mode("Summary")
st.sidebar.success("Use grouped navigation below")

st.title("🚀 Dashboard Launcher")
st.caption("Decision-first macro-to-execution workflow for disciplined swing trading.")
st.caption(f"UI mode: **{view_mode}**")

health = quick_data_health_summary()
if health.get("ok"):
    st.success("Data Health: OK")
else:
    st.warning(f"Data Health Warning: {health.get('message')}")

trust_file = Path("logs/data_trust_latest.json")
if trust_file.exists():
    try:
        trust = json.loads(trust_file.read_text())
        status = str(trust.get("status", "UNKNOWN")).upper()
        score = trust.get("trust_score", "N/A")
        if status == "PASS":
            st.success(f"Data Trust: {status} ({score})")
        elif status == "WARN":
            st.warning(f"Data Trust: {status} ({score})")
        else:
            st.error(f"Data Trust: {status} ({score})")
    except Exception:
        st.info("Data Trust: report present but unreadable.")
else:
    st.info("Data Trust: not generated yet.")

st.subheader("🎯 Recommended Flow")
f1, f2, f3, f4, f5, f6, f7 = st.columns(7)
with f1:
    st.info("1) Global + Liquidity\n\nRead risk backdrop")
with f2:
    st.info("2) Macro Risk\n\nSet bias: Risk On / Neutral / Risk Off")
with f3:
    st.info("3) NSE Dashboard\n\nPick setups with gates")
with f4:
    st.info("4) Portfolio Risk\n\nCheck concentration/exposure")
with f5:
    st.info("5) Journal\n\nLog and review execution")
with f6:
    st.info("6) Ops\n\nRun EOD + alerts")
with f7:
    st.info("7) Prediction Integrity\n\nReview calibration + approvals")

with st.expander("🗂 Pages & Configuration", expanded=False):
    st.markdown("""
    **Pages**
    - `0_NSE_Dashboard.py`
    - `1_Global_Markets.py`
    - `2_Money_Supply.py`
    - `3_Macro_Risk.py`
    - `4_Leading_Indicators.py`
    - `5_Trading_Journal.py`
    - `6_Regime_Settings.py`
    - `7_Portfolio_Risk.py`
    - `8_Ops_Automation.py`
    - `9_Prediction_Integrity.py`
    - `10_Scoring_Audit.py`
    - `11_Tradable_Universe.py`
    - `12_Todo_Tracker.py`
    - `13_India_Macro_Context.py`
    - `14_News_Feed.py`
    - `15_Stock_Fundamentals.py`

    **Core files**
    - `NSE_Config.py` (universe/categories/watchlists)
    - `config.py` (global symbols and app settings)
    - `regime_model.py` (regime scoring settings)
    - `watchlist_manager.py` (saved watchlists)
    - `data_fetch.py` (data pipeline, fallback paths)
    """)

st.subheader("Additional Modules")
c1, c2, c3 = st.columns(3)
with c1:
    st.info("India Macro Context\n\nGlobal headwinds/tailwinds for Indian equities via FRED")
with c2:
    st.info("News Feed\n\nLive RSS headlines from Indian & global sources")
with c3:
    st.info("Stock EOD Profile\n\nEOD snapshot first; fundamentals only when provider allows")

with st.expander("📰 Today's Headlines", expanded=False):
    try:
        recent = fetch_rss_feeds(RSS_FEEDS, max_per_feed=2, max_total=5)
        if recent is None or recent.empty:
            st.caption("No headlines available right now.")
        else:
            for _, row in recent.iterrows():
                title = str(row.get("title", "")).strip()
                link = str(row.get("link", "")).strip()
                source = str(row.get("source", "")).strip()
                if link:
                    st.markdown(f"- [{title}]({link})  \n  `{source}`")
                else:
                    st.markdown(f"- {title}  \n  `{source}`")
    except Exception:
        st.caption("Headlines panel unavailable in this session.")

with st.expander("📊 Data Sources & Notes", expanded=False):
    st.markdown("""
    - **Yahoo Finance**: stock/index/market prices (typically delayed)
    - **FRED**: liquidity/economic series
    - **RSS**: contextual India/global news headlines
    - **EODHD / Finnhub**: profile/fundamentals/news (plan and key dependent)
    - **Fallback**: proxy and local fallback paths are used where configured
    - Regime output is a decision aid, not a guarantee
    - FRED API key: [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
    """)

with st.expander("🧭 Factor Registry (Single Source of Truth)", expanded=False):
    rows = []
    for key, meta in FACTOR_REGISTRY.items():
        rows.append(
            {
                "Factor": key,
                "Label": meta.get("label", ""),
                "Symbol": meta.get("symbol", ""),
                "Source": meta.get("source", ""),
                "Global Mode": meta.get("update_mode", {}).get("global_markets", ""),
                "Default Mode": meta.get("update_mode", {}).get("default", ""),
                "Fallback": meta.get("fallback", ""),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

st.subheader("🌳 Decision Flow (How Stocks Move To Tradable)")
st.markdown("""
```mermaid
flowchart TD
    A["Start: Selected Watchlist Stocks"] --> B{"Setup Qualification"}
    B -->|"Meets at least one setup family"| C["Scored Candidate"]
    B -->|"Fails all setup families"| X["Excluded for today"]
    C --> D{"Entry Safety Checks"}
    D -->|"Pass: Regime + Liquidity + Quality"| E{"Tier Classification"}
    D -->|"Fail any check"| M["Watch / Improve (with Block Reason)"]
    E -->|"A+ or A"| T["Tradable Now List"]
    E -->|"B or C"| W["Watchlist / Tier Buckets"]
```
""")

st.markdown("**Step Explanations**")
st.markdown("- **Setup Qualification**: Stock must satisfy at least one setup family rule (Momentum, Pullback, or Volatility Contraction).")
st.markdown("- **Entry Safety Checks**: Risk controls are applied: Regime check, Liquidity check, and Stock Quality check.")
st.markdown("- **Tier Classification**: Candidate is graded A+/A/B/C by score and tie-breakers.")
st.markdown("- **Tradable Now**: Only candidates with **A+/A** and **Entry Safety Checks = Pass** appear here.")
st.markdown("- **Watch / Improve**: Gate-blocked names or lower tiers stay visible with block reason/invalidation for monitoring.")

# Status indicators
col1, col2, col3 = st.columns(3)

with col1:
    st.info("💡 **Tip of the Day**\n\nStart with macro regime before scanning setups")

with col2:
    # Check if FRED key is set
    from config import FRED_API_KEY

    if FRED_API_KEY:
        st.success("✅ FRED API: Connected")
    else:
        st.warning("⚠️ FRED API: Not configured")

with col3:
    st.info("📚 **Pro Tip**\n\nUse Sector-wise categories first, then thematic overlays")

st.markdown("---")
st.caption("Dashboard Launcher | Feb 2026 Build")
