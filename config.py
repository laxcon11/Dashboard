"""
Configuration file for Trading Dashboard
Central place to customize symbols, indicators, and dashboard behavior
"""

import os
from dotenv import load_dotenv

# ==================== LOAD ENVIRONMENT VARIABLES ====================
load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")

if not FRED_API_KEY:
    print("Warning: FRED_API_KEY not found. Liquidity dashboard will not load data.")


# ==================== WATCHLIST (USED BY NSE DASHBOARD) ====================

WATCHLIST = [
    'RELIANCE.NS',
    'TCS.NS',
    'INFY.NS',
    'HDFCBANK.NS',
    'ICICIBANK.NS',
    'SBIN.NS',
    'HINDUNILVR.NS',
    'ITC.NS',
    'BHARTIARTL.NS',
    'KOTAKBANK.NS',
    'KAYNES.NS',
    'GODREJPROP.NS'
]


# ==================== INDIAN INDICES ====================

MAIN_INDICES = {
    '^NSEI': 'NIFTY 50',
    '^NSEBANK': 'BANK NIFTY',
    'NIFTYMID50.NS': 'NIFTY MIDCAP 50',
    '^CNXIT': 'NIFTY IT'
}


# ==================== GLOBAL SNAPSHOT ====================

GLOBAL_RISK_SNAPSHOT = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "DX-Y.NYB": "Dollar Index",
    "^TNX": "US 10Y Yield",
    "CL=F": "Crude Oil",
    "GC=F": "Gold",
    "BTC-USD": "Bitcoin"
}


# ==================== GLOBAL INDICES ====================

GLOBAL_INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "^DJI": "Dow Jones",
    "^FTSE": "FTSE 100",
    "^FCHI": "CAC 40",
    "^GDAXI": "DAX",
    "000001.SS": "Shanghai Composite",
    "^HSI": "Hang Seng",
    "^N225": "Nikkei 225",
    "^KS11": "KOSPI"
}


# ==================== CURRENCIES ====================

CURRENCIES = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "NZDUSD=X": "NZD/USD",
    "USDCHF=X": "USD/CHF",
    "USDCAD=X": "USD/CAD"
}


# ==================== COMMODITIES ====================

COMMODITIES = {
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Crude Oil",
    "HG=F": "Copper",
    "ZNC=F": "Zinc"
}


# ==================== CRYPTO ====================

CRYPTO = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum"
}


# ==================== BOND MARKETS ====================

BOND_MARKETS = {
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield"
}


# ==================== FRED SERIES (LIQUIDITY DASHBOARD) ====================

FRED_SERIES = {
    "M2SL": "US M2 Money Supply",
    "WALCL": "Fed Balance Sheet",
    "RRPONTSYD": "Reverse Repo",
    "DGS10": "US 10Y Treasury Yield",
    "SOFR": "SOFR Rate",
    "IORB": "Interest on Reserve Balances (IORB)",
    "DFF": "Effective Fed Funds Rate",
    "WTREGEN": "Treasury General Account (TGA)"
}


# ==================== TECHNICAL SETTINGS ====================

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
ATR_PERIOD = 14
ATR_MULTIPLIER = 2
BREAKOUT_WINDOW = 20
VOLUME_THRESHOLD = 1.5


# ==================== SWING SCORING ====================

SWING_SCORE_WEIGHTS = {
    "gap": 2,
    "volume": 3,
    "relative_strength": 3,
    "breakout": 3,
    "trend": 2
}

# ==================== MACRO THRESHOLDS ====================

MACRO_THRESHOLDS = {
    "equity": 0.5,
    "dxy": 0.5,
    "yield": 0.5,
    "crude": 0.5,
    "gold": 0.7,
    "vix": 2.0
}



# ==================== CHART SETTINGS ====================

CHART_PERIODS = {
    'Short Term': '1mo',
    'Medium Term': '3mo',
    'Long Term': '6mo',
    'Yearly': '1y'
}

DEFAULT_CHART_PERIOD = '3mo'


# ==================== DATA REFRESH ====================

CACHE_TTL = 300


# ==================== PATH SETTINGS ====================

EXPORT_PATH = './exports/'
NOTES_PATH = './notes/'
LOG_PATH = './logs/'


# ==================== TRADING RULES ====================

TRADING_RULES = """
My Trading Rules:
1. Never risk more than 2% per trade
2. Always use stop losses
3. Cut losses quickly, let profits run
4. Avoid trading on major news days
5. Review trades weekly
"""
