import streamlit as st

st.set_page_config(
    page_title="Trading Dashboard Suite",
    page_icon="📊",
    layout="wide"
)

st.title("📊 Multi-Market Trading Dashboard Suite")

st.markdown("""
Welcome to your integrated trading dashboard.

## 🎯 Quick Start Guide

### 1️⃣ Global Macro Dashboard
Start here to understand overall market sentiment:
- Global indices (S&P 500, NASDAQ, etc.)
- Currency markets
- Commodities (Oil, Gold)
- Bond yields

**Use case**: Identify risk-on vs risk-off environment

---

### 2️⃣ Liquidity & Money Supply
Check monetary conditions:
- Fed balance sheet
- Reverse repo operations  
- Money supply (M2)
- Interest rates

**Use case**: Understand if liquidity supports rally

---

### 3️⃣ NSE Swing Trading ⭐
Your main trading dashboard:
- Indian stock watchlist from `config.py`
- Gap scanner
- Breakout detection
- Swing rankings
- Technical analysis

**Use case**: Find and analyze swing trade setups

---

## 🔧 Configuration

All settings in **`config.py`**:
- `WATCHLIST` - Your NSE stocks (edit here!)
- `GLOBAL_INDICES` - Markets to track
- `FRED_API_KEY` - For liquidity data

**To add stocks:**
1. Open `config.py`
2. Add to `WATCHLIST` list (format: `'SYMBOL.NS'`)
3. Refresh dashboard

---

## 📊 Data Sources
- **Yahoo Finance**: Stock/index prices (15-20 min delay)
- **FRED**: US economic data (requires free API key)

---

## ⚠️ Important Notes
- Markets: Mon-Fri 9:15 AM - 3:30 PM IST
- Data delay: 15-20 minutes
- FRED API: Get free key at [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)

---

**👈 Select a dashboard from the sidebar to begin**
""")

# Status indicators
col1, col2, col3 = st.columns(3)

with col1:
    st.info("💡 **Tip of the Day**\n\nCheck global markets before trading NSE stocks")

with col2:
    # Check if FRED key is set
    from config import FRED_API_KEY
    if FRED_API_KEY:
        st.success("✅ FRED API: Connected")
    else:
        st.warning("⚠️ FRED API: Not configured")

with col3:
    st.info("📚 **Pro Tip**\n\nUse Swing Rankings to find best setups")

st.markdown("---")
st.caption("Trading Dashboard Suite v3.0 | Integrated multi-market analysis")
st.caption("Version 1.0 | Updated Feb 2026")


