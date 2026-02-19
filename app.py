import streamlit as st
from utils import setup_page

setup_page("Dashboard Launcher")
st.sidebar.success("Select a dashboard above")

st.title("🚀 Dashboard Launcher")

st.markdown("""
Integrated macro-to-execution workflow for disciplined swing trading.

## 🎯 Workflow (Top-Down)

### 1️⃣ Global Markets
- Global indices, FX, commodities, rates, and crypto snapshot
- First read on risk-on / risk-off

### 2️⃣ Money Supply & Liquidity
- Fed balance sheet, RRP, M2, rates, and liquidity context
- Validates whether liquidity supports trend continuation

### 3️⃣ Macro Risk Dashboard
- Composite macro + liquidity regime assessment
- Regime tags for directional bias (Risk On / Neutral / Risk Off)

### 4️⃣ Leading Indicators Dashboard
- Forward-looking triggers (yield curve, copper/gold, credit, USD)
- Daily and directional impulse context

### 5️⃣ NSE Dashboard ⭐
- Core universe: 230 tracked stocks (base universe + F&O delta)
- Stock selection modes:
  - Preset watchlists
  - Category view: Sector-wise (first pass) or Thematic
  - Custom selection
- Swing engine + rankings + one-click journal handoff

### 6️⃣ Trading Journal 📔
- Log setups/trades, track lifecycle, and review performance

### 7️⃣ Regime Settings ⚙️
- Edit factor weights and directional controls
- Prevent single-factor dominance and tune model behavior

---

## 🔧 Configuration

Core files:
- `NSE_Config.py` - Universe, sector/thematic categories, preset watchlists
- `config.py` - Global markets and macro symbol settings
- `regime_model.py` - Regime scoring logic
- `watchlist_manager.py` - Persistent watchlists
- `data_fetch.py` - Data access and fallback paths
- `FRED_API_KEY` in `config.py` - Required for liquidity series

## 🗂 Dashboard Structure

Pages:
- 0_NSE_Dashboard.py
- 1_Global_Markets.py
- 2_Money_Supply.py
- 3_Macro_Risk.py
- 4_Leading_Indicators.py
- 5_Trading_Journal.py
- 6_Regime_Settings.py

---

## 📊 Data Sources
- **Yahoo Finance**: Stock/index prices (typically delayed)
- **FRED**: US economic/liquidity data (free API key)
- **Fallback behavior**: Some indicators use proxy/fallback mappings when primary series is unavailable

---

## ⚠️ Important Notes
- Markets: Mon-Fri 9:15 AM - 3:30 PM IST
- Data can be delayed depending on source availability
- FRED API key: [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
- Regime output is a decision aid, not a prediction guarantee

---

**👈 Select a dashboard from the sidebar to begin**
""")

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
