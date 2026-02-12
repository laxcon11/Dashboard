# Quick Reference Card

## 🚀 Starting the Dashboard

```bash
streamlit run app.py
```

Opens at: http://localhost:8501

---

## ✏️ Adding Your Stocks (MOST COMMON TASK)

### Option 1: Permanent (Recommended)

**File**: `config.py`  
**Line**: ~25

```python
WATCHLIST = [
    'RELIANCE.NS',
    'TCS.NS',
    'KAYNES.NS',        # ← Add here
    'GODREJPROP.NS',    # ← Add here
]
```

**After editing**: Restart dashboard (Ctrl+C, then run again)

### Option 2: Temporary

1. Run dashboard
2. Navigate to "NSE Dashboard" (sidebar)
3. Edit watchlist text area in sidebar
4. Click "Refresh Data"

---

## 📊 Dashboard Navigation

```
Main Page (app.py)
├── NSE Dashboard          ← Your stocks (KAYNES.NS shows here!)
├── Global Markets         ← S&P 500, NASDAQ, etc.
└── Liquidity & Money      ← Fed data (needs API key)
```

---

## 🔧 File Purposes

| File | Purpose | Edit? |
|------|---------|-------|
| `config.py` | ⭐ **Your settings** | ✅ YES - Add stocks here |
| `app.py` | Landing page | ❌ No need |
| `data_fetch.py` | Shared utilities | ❌ No need |
| `indicators.py` | RSI, EMA, ATR | ❌ No need |
| `pages/0_NSE_Dashboard.py` | Main trading dashboard | ❌ No need |
| `pages/1_Global_Markets.py` | Global indices | ❌ No need |
| `pages/2_Money_Supply.py` | Liquidity data | ❌ No need |

**👉 Only edit `config.py` for adding stocks!**

---

## ⚡ Common Commands

```bash
# Start dashboard
streamlit run app.py

# Stop dashboard
Ctrl + C

# Install dependencies
pip install -r requirements.txt

# Test a symbol
python3 -c "import yfinance as yf; print(yf.download('KAYNES.NS', period='5d'))"

# View logs
cat logs/nse_*.log
```

---

## 🐛 Quick Fixes

### "Stocks not showing"
1. Check you're on **NSE Dashboard** page (not Global Markets)
2. Verify `config.py` has your stocks with `.NS`
3. Restart dashboard

### "Import error"
```bash
pip install -r requirements.txt
```

### "FRED data not loading"
1. Create `.env` file
2. Add: `FRED_API_KEY=your_key`
3. Restart

---

## 📝 Symbol Format

✅ **Correct**: `KAYNES.NS`  
❌ **Wrong**: `KAYNES`, `kaynes.ns`, `KAYNES.NSE`

---

## 🎯 Where Your Stocks Appear

✅ **NSE Dashboard** (pages/0_NSE_Dashboard.py)  
- Uses `WATCHLIST` from config.py  
- KAYNES.NS and GODREJPROP.NS will show here!

❌ **Global Markets** (pages/1_Global_Markets.py)  
- Uses `GLOBAL_INDICES` from config.py  
- For global tracking only

---

## 📁 Directory Structure

```
Dashboard/
├── app.py                 # Run this
├── config.py              # ⭐ Edit this
├── data_fetch.py
├── indicators.py
├── requirements.txt
├── .env                   # Create this for FRED
│
└── pages/
    ├── 0_NSE_Dashboard.py
    ├── 1_Global_Markets.py
    └── 2_Money_Supply.py
```

---

## ✅ Verification

After adding stocks to `config.py`:

1. ✅ Restart dashboard
2. ✅ Go to "NSE Dashboard" (sidebar)
3. ✅ See KAYNES.NS in watchlist
4. ✅ See GODREJPROP.NS in watchlist
5. ✅ Click "Refresh Data"
6. ✅ Prices appear!

---

## 🆘 Still Not Working?

**Check these in order:**

1. File location
   ```bash
   pwd
   ls config.py  # Should exist
   ```

2. Symbol format in config.py
   ```python
   'KAYNES.NS',  # ✅ Correct
   'KAYNES',     # ❌ Wrong
   ```

3. Restart dashboard
   ```bash
   # Stop: Ctrl+C
   # Start: streamlit run app.py
   ```

4. Check symbol exists
   ```bash
   python3 -c "import yfinance as yf; print(yf.Ticker('KAYNES.NS').info['symbol'])"
   ```

5. View logs
   ```bash
   cat logs/nse_*.log | grep KAYNES
   ```

---

**Success Indicator**: You see your stocks in NSE Dashboard with live prices! 🎉
