# Multi-Market Trading Dashboard - Setup Guide

## 🎯 What You Have

A **3-in-1 integrated trading dashboard** with:
1. **NSE Swing Trading** - Indian stocks (uses your config.py watchlist)
2. **Global Markets** - Indices, currencies, commodities
3. **Liquidity Dashboard** - Fed data, money supply

## 📁 File Structure

```
Dashboard/
├── app.py                      # Main landing page
├── config.py                   # ⭐ EDIT THIS - Your settings
├── data_fetch.py              # Shared data utilities
├── indicators.py              # Technical indicators
├── requirements.txt           # Dependencies
├── .env                       # API keys (create this)
│
├── pages/
│   ├── 0_NSE_Dashboard.py     # Indian stocks (uses config.py)
│   ├── 1_Global_Markets.py    # Global indices
│   └── 2_Money_Supply.py      # Liquidity data
│
├── logs/                      # Auto-created
├── notes/                     # Auto-created
└── exports/                   # Auto-created
```

## 🚀 Quick Start (3 Steps)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure FRED API (Optional - for Liquidity Dashboard)
```bash
# Create .env file
echo "FRED_API_KEY=your_key_here" > .env
```

Get free API key: https://fred.stlouisfed.org/docs/api/api_key.html

### Step 3: Run Dashboard
```bash
streamlit run app.py
```

Dashboard opens at: http://localhost:8501

## ✏️ How to Add Your Stocks

### Method 1: Edit config.py (Permanent)

Open `config.py` and find:

```python
WATCHLIST = [
    'RELIANCE.NS',
    'TCS.NS',
    'INFY.NS',
    # ADD YOUR STOCKS HERE:
    'KAYNES.NS',        # ← Your new stock
    'GODREJPROP.NS',    # ← Your new stock
]
```

**Important**: 
- NSE stocks must end with `.NS`
- One symbol per line
- Use uppercase

### Method 2: Use Sidebar (Temporary)

1. Run dashboard
2. Go to NSE Dashboard page
3. Edit watchlist in sidebar
4. Changes lost when you close browser

**👉 Recommendation**: Use Method 1 for permanent changes

## 📊 Available Dashboards

### 1. NSE Swing Trading Dashboard

**Location**: Pages → 0_NSE_Dashboard

**Features**:
- ✅ Uses `WATCHLIST` from config.py (your KAYNES.NS and GODREJPROP.NS will show!)
- Morning Review (gaps, volume)
- End of Day (breadth, RSI)
- Full Analysis (charts, EMAs)
- Swing Rankings (scored setups)

**Data Source**: Yahoo Finance (15-20 min delay)

### 2. Global Markets Dashboard

**Location**: Pages → 1_Global_Markets

**Shows**:
- Global indices (S&P, NASDAQ, DAX, Nikkei)
- Currency pairs
- Commodities (Oil, Gold)
- Crypto (BTC, ETH)
- Bond yields

**Use**: Check before trading Indian markets

### 3. Liquidity & Money Supply

**Location**: Pages → 2_Money_Supply

**Shows**:
- Fed balance sheet
- Reverse repo
- M2 money supply
- Treasury yields
- SOFR rates

**Requires**: FRED API key in .env file

## 🔧 Configuration Options

All in `config.py`:

```python
# Your NSE watchlist
WATCHLIST = ['RELIANCE.NS', 'TCS.NS', ...]

# Technical settings
RSI_PERIOD = 14
ATR_MULTIPLIER = 2
VOLUME_THRESHOLD = 1.5

# Cache duration (seconds)
CACHE_TTL = 300  # 5 minutes
```

## ❓ Troubleshooting

### Problem: Stocks from config.py not showing

**Solution**:
1. Check you're on "NSE Dashboard" page (not Global Markets)
2. Verify symbol format: `KAYNES.NS` not `KAYNES`
3. Refresh data (click 🔄 button)
4. Restart: `Ctrl+C` then `streamlit run app.py`

### Problem: FRED data not loading

**Solution**:
1. Create `.env` file in root directory
2. Add: `FRED_API_KEY=your_actual_key_here`
3. Get key from: https://fred.stlouisfed.org/
4. Restart dashboard

### Problem: No data showing

**Causes**:
- Market closed (Mon-Fri 9:15 AM - 3:30 PM IST)
- Internet connection
- Yahoo Finance API down

**Solutions**:
```bash
# Test your stocks manually
python3
>>> import yfinance as yf
>>> yf.download('KAYNES.NS', period='5d')

# Check logs
cat logs/nse_*.log
```

### Problem: Import errors

**Solution**:
```bash
# Make sure you're in the right directory
cd /path/to/Dashboard

# Verify file structure
ls
# Should see: app.py, config.py, pages/, etc.

# Reinstall dependencies
pip install -r requirements.txt
```

## 📝 Where Your Stocks Are Configured

**✅ NSE Dashboard**: Uses `WATCHLIST` from `config.py`
- Your KAYNES.NS ✓
- Your GODREJPROP.NS ✓

**❌ Global Markets**: Uses `GLOBAL_INDICES` from `config.py`
- Different symbols (S&P, NASDAQ, etc.)
- For global tracking, not trading

**❌ Liquidity**: Uses `FRED_SERIES` from `config.py`
- Economic data, not stocks

## 🎯 Workflow Recommendation

**Morning (Pre-Market)**:
1. Check **Global Markets** → Risk sentiment
2. Check **Liquidity Dashboard** → Money conditions
3. Go to **NSE Dashboard** → Morning Review mode
4. Scan your watchlist for gaps & volume
5. Plan trades

**Evening (Post-Market)**:
1. **NSE Dashboard** → End of Day mode
2. Review breadth & RSI
3. Check **Swing Rankings** for tomorrow
4. Save notes

## 🔐 Security Notes

- `.env` file contains API keys - never commit to Git
- Add to `.gitignore`:
  ```
  .env
  logs/
  notes/
  *.pyc
  __pycache__/
  ```

## 📈 Data Limitations

- **Yahoo Finance**: 15-20 min delayed
- **FRED**: Daily updates (not real-time)
- **Market Hours**: Mon-Fri 9:15 AM - 3:30 PM IST
- **Weekend**: Shows Friday's close

## 🆘 Still Having Issues?

1. **Check you edited config.py** (not any other file)
2. **Verify file location**: config.py in root, not in pages/
3. **Check symbol format**: Must be `KAYNES.NS` (with .NS)
4. **Test symbol works**:
   ```python
   import yfinance as yf
   print(yf.Ticker('KAYNES.NS').history(period='5d'))
   ```
5. **Check logs**: `cat logs/nse_*.log`

## ✅ Verification Checklist

After setup, verify:
- [ ] `app.py` runs without errors
- [ ] Can navigate to all 3 dashboards
- [ ] NSE Dashboard shows your stocks from config.py
- [ ] Can see KAYNES.NS and GODREJPROP.NS in watchlist
- [ ] Refresh button works
- [ ] Charts display correctly

## 🎉 Success!

If you see your stocks (KAYNES.NS, GODREJPROP.NS) in the NSE Dashboard, everything is working!

Navigate using sidebar → Select "0_NSE_Dashboard" → Your stocks appear!

---

**Version**: 3.0 Integrated Suite
**Support**: Check logs/ directory for errors
**Documentation**: See USER_GUIDE.md for features
