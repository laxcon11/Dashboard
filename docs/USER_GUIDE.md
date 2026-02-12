# NSE Market Dashboard Pro - Complete User Guide

## Table of Contents
1. [Quick Start](#quick-start)
2. [Understanding Indicators](#understanding-indicators)
3. [Dashboard Modes](#dashboard-modes)
4. [How to Add Symbols](#how-to-add-symbols)
5. [Data Limitations](#data-limitations)
6. [Trading Strategies](#trading-strategies)
7. [Troubleshooting](#troubleshooting)

---

## Quick Start

### Installation
```bash
pip install streamlit yfinance pandas plotly numpy
streamlit run nse_dashboard_pro.py
```

### First Time Setup
1. Dashboard opens in browser automatically
2. Default watchlist is pre-loaded
3. Click "Refresh Data" to fetch latest prices
4. Choose your dashboard mode from sidebar

---

## Understanding Indicators

### 📊 RSI (Relative Strength Index)
**What it is**: Momentum oscillator measuring speed of price changes

**Calculation**: Wilder's RSI (EMA-based)
- Period: 14 days
- Range: 0 to 100
- Formula: RSI = 100 - (100 / (1 + RS))
  - RS = Average Gain / Average Loss (EMA smoothed)

**How to use**:
- **> 70**: Overbought (potential sell signal)
- **< 30**: Oversold (potential buy signal)
- **50-70**: Bullish zone
- **30-50**: Bearish zone

**Example**:
```
Stock at RSI 75 → Overbought, consider taking profits
Stock at RSI 28 → Oversold, watch for reversal
Stock at RSI 55 → Neutral bullish, can hold
```

**Matches**: TradingView, Bloomberg, professional platforms

---

### 📈 EMA (Exponential Moving Average)

**What it is**: Trend indicator that gives more weight to recent prices

**Dashboard shows**:
- 20 EMA (short-term trend)
- 50 EMA (medium-term trend)

**How to use**:

**Trend Identification**:
- Price > 20 EMA > 50 EMA = **Strong Bullish** 🟢
- Price > 20 EMA (but 20 < 50) = **Weak Bullish** 🟢
- Price < 20 EMA < 50 EMA = **Strong Bearish** 🔴
- Price < 20 EMA (but 20 > 50) = **Weak Bearish** 🔴

**Trading Signals**:
- 20 EMA crosses above 50 EMA = **Golden Cross** (bullish)
- 20 EMA crosses below 50 EMA = **Death Cross** (bearish)

**Example**:
```
INFY: ₹1,450
20 EMA: ₹1,420
50 EMA: ₹1,380
→ Strong Bullish trend, safe to hold
```

---

### 🛡️ ATR (Average True Range)

**What it is**: Volatility indicator measuring price range

**Calculation**:
- Period: 14 days
- Measures: High - Low, |High - Previous Close|, |Low - Previous Close|
- Takes maximum of these three

**How to use for Stop-Loss**:
```
Stop-Loss = Entry Price - (2 × ATR)
```

**Example**:
```
Stock: ₹2,500
ATR: ₹50
Stop-Loss: ₹2,500 - (2 × ₹50) = ₹2,400

Wide stop for volatile stocks, tight stop for stable stocks
```

**Why 2×ATR?**:
- 1×ATR: Too tight, frequent stop-outs
- 2×ATR: Balanced, accounts for normal volatility
- 3×ATR: Too wide, large potential loss

---

### 🚀 Gap Detection

**What it is**: Price difference between yesterday's close and today's open

**Calculation**:
```
Gap % = ((Today's Open - Yesterday's Close) / Yesterday's Close) × 100
```

**Types**:
- **Gap-Up** (> +1%): Bullish momentum
- **Gap-Down** (< -1%): Bearish pressure
- **Small gaps** (±0.5%): Normal fluctuation

**Trading Strategy**:
```
Gap-Up + High Volume + Strong Trend = Buy signal
Gap-Down + Low Volume + Support near = Reversal play
```

**Example**:
```
Yesterday Close: ₹1,000
Today Open: ₹1,030
Gap: +3% (Gap-Up)

Action: Watch for continuation or fade
```

---

### 💪 Relative Strength vs NIFTY

**What it is**: How stock performs compared to market

**Calculation**:
```
Stock Return = (Current Price / Price 1mo ago - 1) × 100
NIFTY Return = (Current NIFTY / NIFTY 1mo ago - 1) × 100
RS = Stock Return - NIFTY Return
```

**How to interpret**:
- **RS > +2%**: Strong outperformer (buy/hold)
- **RS 0% to +2%**: Mild outperformer
- **RS -2% to 0%**: Mild underperformer
- **RS < -2%**: Strong underperformer (avoid/sell)

**Example**:
```
RELIANCE: +8% in 1 month
NIFTY: +3% in 1 month
RS = +5%
→ RELIANCE is outperforming, sector strength
```

---

### 🔔 Breakout Detection

**What it is**: Price breaking above/below recent range

**Calculation**:
```
Checks if today's close > highest high of last 20 days
OR
today's close < lowest low of last 20 days
```

**Signals**:
- **BREAKOUT HIGH**: Close above 20-day high
- **BREAKDOWN LOW**: Close below 20-day low

**Trading Strategy**:
```
Breakout + Volume > 1.5x + RS > 0 = High probability trade
```

---

### 🔊 Volume Ratio

**What it is**: Current volume compared to average

**Calculation**:
```
Volume Ratio = Today's Volume / 20-day Average Volume
```

**Interpretation**:
- **> 2.0x**: Exceptional activity (news/event)
- **1.5-2.0x**: Unusual activity (highlighted)
- **1.0-1.5x**: Above average
- **< 1.0x**: Below average

**Trading Use**:
```
High volume confirms breakouts
Low volume breakouts often fail
```

---

### 📏 Support & Resistance

**What it is**: Price levels where stock tends to bounce/reverse

**Calculation**:
```
Support = Lowest Low of last 20 days
Resistance = Highest High of last 20 days
```

**How to use**:
- Buy near support with stop below it
- Sell near resistance or when it breaks
- Breakout above resistance = new uptrend
- Breakdown below support = new downtrend

**Example**:
```
Support: ₹2,300
Resistance: ₹2,500
Current: ₹2,320

Strategy: Buy at ₹2,310, stop at ₹2,280, target ₹2,480
```

---

## Dashboard Modes

### 1. Morning Review 🌅
**When to use**: Before market opens or within first hour

**What you see**:
- Market overview (indices)
- Sector performance
- Gap-up/down stocks
- Unusual volume
- Support/resistance levels

**Workflow**:
1. Check overall market sentiment (NIFTY, BANKNIFTY)
2. Identify hot sectors
3. Scan gap stocks for opportunities
4. Note stocks with unusual volume
5. Plan day's trades

---

### 2. End of Day Review 🌆
**When to use**: After market close

**What you see**:
- Market breadth (advances vs declines)
- RSI extremes (overbought/oversold)
- Sector rotation

**Workflow**:
1. Review market breadth
2. Identify oversold stocks for next day
3. Note overbought stocks to avoid
4. Track sector trends
5. Save trading notes

---

### 3. Full Analysis 🔍
**When to use**: Deep dive on specific stocks

**What you see**:
- Interactive charts with EMAs
- Volume analysis
- RSI charts
- ATR and stop-loss levels
- Complete technical picture

**Workflow**:
1. Select stock from watchlist
2. Analyze trend (EMA alignment)
3. Check RSI for entry timing
4. Note support/resistance
5. Calculate stop-loss using ATR
6. Plan entry/exit strategy

---

### 4. Swing Rankings 🎯
**When to use**: Finding best swing trade setups

**What you see**:
- Stocks ranked by "swing score"
- Top 3 candidates highlighted
- Multi-factor analysis

**Scoring factors**:
- Gap percentage (0-3 points)
- Volume ratio (0-3 points)
- Relative strength (0-3 points)
- Breakout signal (0-3 points)
- Trend strength (0-2 points)

**Maximum score**: 14 points

**How to use**:
1. Check rankings daily
2. Focus on top 5 stocks
3. Verify fundamentals separately
4. Plan trades for highest-scoring setups

---

## How to Add Symbols

### Method 1: Sidebar (Easiest)
1. Click on watchlist text area
2. Add symbol, one per line
3. Format: `SYMBOLNAME.NS`
4. Press Enter after each symbol

### Method 2: Code (Permanent)
Edit `DEFAULT_WATCHLIST` in code:
```python
DEFAULT_WATCHLIST = [
    'RELIANCE.NS',
    'TCS.NS',
    'INFY.NS',
    # Your symbols here
]
```

### Symbol Format Rules

**NSE Stocks** (National Stock Exchange):
```
Format: SYMBOL.NS
Examples: RELIANCE.NS, TCS.NS, INFY.NS
```

**BSE Stocks** (Bombay Stock Exchange):
```
Format: SYMBOL.BO
Examples: RELIANCE.BO, TCS.BO
```

**Indices**:
```
Format: ^SYMBOL
Examples: ^NSEI (NIFTY 50), ^NSEBANK (BANK NIFTY)
```

### Finding Symbol Names

**Option 1**: Yahoo Finance
1. Go to finance.yahoo.com
2. Search for company name
3. Look for ".NS" symbols for NSE

**Option 2**: NSE Website
1. Go to nseindia.com
2. Find symbol on stock page
3. Add ".NS" suffix

### Common Symbols
```
Indices:
^NSEI - NIFTY 50
^NSEBANK - BANK NIFTY
^CNXIT - NIFTY IT
^CNXAUTO - NIFTY AUTO

Stocks:
RELIANCE.NS - Reliance Industries
TCS.NS - Tata Consultancy Services
INFY.NS - Infosys
HDFCBANK.NS - HDFC Bank
ICICIBANK.NS - ICICI Bank
```

---

## Data Limitations

### Data Source
- **Provider**: Yahoo Finance
- **Coverage**: NSE, BSE, major indices
- **Cost**: Free (no API key required)

### Delays
- **Live data**: 15-20 minutes delayed
- **Historical**: Accurate
- **Weekend**: Shows Friday's close

### Availability
- **Market hours**: Mon-Fri, 9:15 AM - 3:30 PM IST
- **Data updates**: During and after market hours
- **Holidays**: No updates on market holidays

### Limitations
1. **No real-time data**
   - Use for swing trading, not intraday scalping
   
2. **No options data** (in current version)
   - No Put-Call Ratio
   - No Open Interest
   - Planned for future update

3. **No FII/DII data**
   - Check NSE website manually
   - Institutional flows not automated

4. **Historical limits**
   - Maximum: Several years
   - Dashboard uses: 1 month for calculations

### What This Means for Trading

✅ **Good for**:
- Swing trading (2+ days)
- Position trading (weeks)
- End-of-day analysis
- Planning next day's trades

❌ **Not suitable for**:
- Day trading (scalping)
- Real-time decisions
- Options strategies (without additional data)

---

## Trading Strategies

### Strategy 1: Gap & Volume Swing
**Setup**:
- Gap-up > 1.5%
- Volume > 2x average
- RS vs NIFTY > 0
- Trend: Strong Bullish

**Entry**: On pullback to 20 EMA
**Stop**: 2×ATR below entry
**Target**: Resistance level

**Example**:
```
Stock gaps up 2%, volume 2.5x, RS +3%
Wait for dip to 20 EMA
Buy at ₹1,400 (near 20 EMA)
Stop at ₹1,350 (2×ATR = ₹50)
Target: ₹1,500 (resistance)
```

---

### Strategy 2: Oversold Reversal
**Setup**:
- RSI < 30
- Price near support
- Still in bullish trend (price > 50 EMA)
- Volume spike on reversal day

**Entry**: When RSI crosses back above 30
**Stop**: Below support
**Target**: 50% retracement

---

### Strategy 3: Breakout Trading
**Setup**:
- BREAKOUT HIGH signal
- Volume > 1.5x
- RSI 50-70 (not overbought)
- RS > 0 (outperforming)

**Entry**: Close above prior high
**Stop**: Prior high (now support)
**Target**: ATR-based or next resistance

---

### Strategy 4: EMA Crossover
**Setup**:
- 20 EMA crosses above 50 EMA (Golden Cross)
- Volume increasing
- RSI > 50
- RS improving

**Entry**: On pullback after crossover
**Stop**: Below 50 EMA
**Target**: Ride trend until 20 EMA crosses below 50 EMA

---

### Risk Management Rules

1. **Position Sizing**:
   ```
   Risk per trade = 1-2% of capital
   Position size = (Account × Risk %) / (Entry - Stop)
   
   Example:
   Account: ₹5,00,000
   Risk: 2% = ₹10,000
   Entry: ₹1,000, Stop: ₹950
   Position: ₹10,000 / ₹50 = 200 shares
   ```

2. **Stop-Loss**:
   - Always use stop-loss
   - Place below support or 2×ATR
   - Never move stop down, only up (trailing)

3. **Profit Targets**:
   - Take partial profits at 2:1 reward/risk
   - Trail stop on remaining position
   - Exit if trend reverses (20 EMA cross)

4. **Diversification**:
   - Maximum 3-5 positions at once
   - Different sectors
   - Don't over-concentrate

---

## Troubleshooting

### Problem: No Data Showing

**Possible Causes**:
1. Market is closed
2. Internet issue
3. Symbol format wrong
4. Yahoo Finance API down

**Solutions**:
```bash
# 1. Check market hours
Are we Mon-Fri, 9:15 AM - 3:30 PM IST?

# 2. Run diagnostic
python diagnose.py

# 3. Upgrade yfinance
pip install --upgrade yfinance

# 4. Clear cache
Click "Refresh Data" button

# 5. Check logs
Look in logs/ directory for errors
```

---

### Problem: Slow Loading

**Causes**:
- Large watchlist (>20 stocks)
- Slow internet
- Old computer

**Solutions**:
```
1. Reduce watchlist to 10-15 stocks
2. Close other browser tabs
3. Increase cache duration (edit code):
   @st.cache_data(ttl=600)  # 10 minutes
```

---

### Problem: Wrong RSI Values

**Check**:
1. Dashboard uses Wilder's RSI (industry standard)
2. 14-period EMA smoothing
3. Should match TradingView

**If still wrong**:
- Run unit tests: `python test_indicators.py`
- Check data quality (missing days?)
- Compare with TradingView on same date

---

### Problem: Symbol Not Found

**Error**: "Invalid symbol"

**Solutions**:
1. **Check format**:
   - NSE: `SYMBOL.NS` (not just `SYMBOL`)
   - Correct: `RELIANCE.NS`
   - Wrong: `RELIANCE`

2. **Verify symbol exists**:
   - Search on finance.yahoo.com
   - Copy exact symbol from there

3. **Try alternative**:
   - Some stocks: try `.BO` instead of `.NS`

---

### Problem: Indicators Not Calculating

**Error**: Shows "N/A" for RSI, EMA, ATR

**Cause**: Insufficient data (<14 days)

**Solution**:
- Wait for more trading days
- New stocks need 14+ days for RSI
- 20+ days for 20 EMA
- 50+ days for 50 EMA

---

## Advanced Tips

### 1. Multi-Timeframe Analysis
```
Daily chart: Swing direction (use dashboard)
Weekly chart: Overall trend (check separately)
Entry rule: Align both timeframes
```

### 2. Combining Indicators
```
Best setups require 3+ confirmations:
✓ Breakout signal
✓ Volume > 1.5x
✓ RS > 0
✓ Trend: Strong Bullish
✓ RSI 50-70
```

### 3. Watchlist Organization
```
Create themed watchlists:
- Banking stocks
- IT stocks
- Breakout candidates
- Oversold plays
```

### 4. Note-Taking System
```
Daily format:
Market: Bullish/Bearish/Neutral
Top movers: [list]
Trades planned: [details]
Risk: [amount]
```

---

## Keyboard Shortcuts

While in dashboard:
- `Ctrl/Cmd + R`: Refresh page
- `F5`: Reload
- `Ctrl/Cmd + F`: Find on page

---

## Getting Help

### Self-Help
1. Read this guide
2. Check CHANGELOG.md for recent updates
3. Run diagnose.py
4. Check logs/ directory

### Common Resources
- NSE India: https://www.nseindia.com
- Yahoo Finance: https://finance.yahoo.com
- TradingView: https://www.tradingview.com

---

## Glossary

**Swing Trading**: Holding positions for 2-10 days  
**Breakout**: Price moving above resistance  
**Gap**: Difference between open and prior close  
**Volume**: Number of shares traded  
**EMA**: Exponential Moving Average  
**RSI**: Relative Strength Index  
**ATR**: Average True Range  
**Support**: Price level where buying appears  
**Resistance**: Price level where selling appears  

---

**Document Version**: 3.0  
**Last Updated**: February 2024  
**For**: NSE Dashboard Pro v3.0
