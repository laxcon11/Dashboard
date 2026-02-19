"""
Main Configuration file for Trading Dashboard Suite
UPDATED: Removed Midcap indicator (broken symbol)
NSE-specific config moved to nse_config.py
"""

import os
from dotenv import load_dotenv

# ==================== LOAD ENVIRONMENT VARIABLES ====================
load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")

if not FRED_API_KEY:
    print("⚠️  FRED_API_KEY not found in .env - Liquidity dashboard features disabled")


# ==================== MAIN INDICES ====================
# Used across all dashboards for market overview

MAIN_INDICES = {
    '^NSEI': 'NIFTY 50',
    '^NSEBANK': 'BANK NIFTY',
    'NIFTY_MIDCAP_100.NS': 'NIFTY MIDCAP',
    '^CNXSC': 'NIFTY SMALLCAP',
    '^CNXIT': 'NIFTY IT'
}


# ==================== GLOBAL MARKETS ====================

# Quick risk snapshot (top of Global Markets dashboard)
GLOBAL_RISK_SNAPSHOT = {
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ",
    "DX-Y.NYB": "Dollar Index",
    "^TNX": "US 10Y Yield",
    "CL=F": "Crude Oil",
    "GC=F": "Gold",
    "BTC-USD": "Bitcoin"
}

# All global indices
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

# Currency pairs
CURRENCIES = {
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "USDJPY=X": "USD/JPY",
    "AUDUSD=X": "AUD/USD",
    "NZDUSD=X": "NZD/USD",
    "USDCHF=X": "USD/CHF",
    "USDCAD=X": "USD/CAD"
}

# Commodities
COMMODITIES = {
    "GC=F": "Gold",
    "SI=F": "Silver",
    "CL=F": "Crude Oil",
    "HG=F": "Copper",
    "ZNC=F": "Zinc"
}

# Fallback/proxy symbols when primary Yahoo commodity ticker is unavailable
COMMODITY_FALLBACKS = {
    "ZNC=F": ["DBB"],  # Invesco DB Base Metals ETF proxy
}

# Cryptocurrencies
CRYPTO = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum"
}

# Bond markets
BOND_MARKETS = {
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield"
}


# ==================== MARKET OVERVIEW SYMBOLS ====================
MARKET_SYMBOLS = {
    "^IXIC": "NASDAQ",
    "^NSEI": "NIFTY 50",
    "DX-Y.NYB": "Dollar Index",
    "USDINR=X": "USD/INR",
    "GC=F": "Gold",
    "^TNX": "US 10Y Yield",
    "^IRX": "US 3M Yield"
}


# ==================== MACRO RISK DASHBOARD ====================

MACRO_SYMBOLS = {
    "^DJI": "Dow Jones",
    "^IXIC": "Nasdaq",
    "^NSEI": "NIFTY 50",
    "^NSEBANK": "Bank NIFTY",
    "DX-Y.NYB": "Dollar Index",
    "USDINR=X": "USD/INR",
    "^TNX": "US 10Y Yield",
    "GC=F": "Gold",
    "CL=F": "Crude Oil",
    "BTC-USD": "Bitcoin"
}

MACRO_WEIGHTS = {
    "^DJI": 2,
    "^IXIC": 2,
    "^NSEI": 2,
    "^NSEBANK": 1,
    "DX-Y.NYB": 2,
    "^TNX": 2,
    "CL=F": 1,
    "GC=F": 1,
    "BTC-USD": 1,
    "USDINR=X": 1
}

MACRO_THRESHOLDS = {
    "equity": 0.5,
    "dxy": 0.5,
    "yield": 0.5,
    "crude": 0.5,
    "gold": 0.7,
    "vix": 2.0
}


# ==================== LEADING INDICATORS ====================

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


# ==================== LIQUIDITY MONITORING (MONEY MARKET) ====================

LIQUIDITY_THRESHOLDS = {
    "WALCL": {"weekly_pct": 1.0, "description": "Fed Balance Sheet Change"},
    "RRPONTSYD": {"weekly_abs": 50.0, "description": "Reverse Repo Shift ($B)"},
    "WTREGEN": {"weekly_abs": 50.0, "description": "TGA Fiscal Drain ($B)"},
    "SOFR": {"absolute_change": 0.10, "description": "Interbank Stress (10bps move)"}
}


# ==================== FRED SERIES (LIQUIDITY DASHBOARD) ====================

FRED_SERIES = {
    "Fed Balance Sheet": "WALCL",
    "Reverse Repo": "RRPONTSYD",
    "Treasury General Account (TGA)": "WTREGEN",
    "US M2 Money Supply": "M2SL",
    "US 10Y Treasury Yield": "DGS10",
    "SOFR Rate": "SOFR",
    "Interest on Reserve Balances (IORB)": "IORB",
    "Effective Fed Funds Rate": "DFF"
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


# ==================== CHART SETTINGS ====================

CHART_PERIODS = {
    'Short Term': '1mo',
    'Medium Term': '3mo',
    'Long Term': '6mo',
    'Yearly': '1y'
}

DEFAULT_CHART_PERIOD = '3mo'
DEFAULT_PERIOD = "3mo"
DEFAULT_SHORT_PERIOD = "1mo"


# ==================== DATA REFRESH ====================

CACHE_TTL = 300  # 5 minutes


# ==================== PATH SETTINGS ====================

EXPORT_PATH = './exports/'
NOTES_PATH = './notes/'
LOG_PATH = './logs/'

# Local NSE history parquet (parquet-first fetch for NSE symbols)
LOCAL_NSE_HISTORY_ENABLED = os.getenv("LOCAL_NSE_HISTORY_ENABLED", "1") == "1"
LOCAL_NSE_HISTORY_PATH = os.getenv("LOCAL_NSE_HISTORY_PATH", "./data/nse_230_history.parquet")
LOCAL_NSE_HISTORY_WRITEBACK = os.getenv("LOCAL_NSE_HISTORY_WRITEBACK", "1") == "1"

# Local Bhavcopy fallback settings (used when Yahoo data is unavailable)
BHAVCOPY_FALLBACK_ENABLED = os.getenv("BHAVCOPY_FALLBACK_ENABLED", "1") == "1"
BHAVCOPY_DIR = os.getenv("BHAVCOPY_DIR", "")
BHAVCOPY_LOCAL_DIR = os.getenv("BHAVCOPY_LOCAL_DIR", "./data/bhavcopy")
BHAVCOPY_AUTO_DOWNLOAD = os.getenv("BHAVCOPY_AUTO_DOWNLOAD", "1") == "1"
BHAVCOPY_LOOKBACK_DAYS = int(os.getenv("BHAVCOPY_LOOKBACK_DAYS", "10"))
BHAVCOPY_SCAN_DIRS = [
    p for p in [
        BHAVCOPY_LOCAL_DIR,
        BHAVCOPY_DIR,
        "./data",
        os.path.expanduser("~/Desktop/Bhavcopy"),
        os.path.expanduser("~/Downloads"),
    ] if p
]
BHAVCOPY_MAX_FILES_PER_DIR = int(os.getenv("BHAVCOPY_MAX_FILES_PER_DIR", "200"))


# ==================== VALIDATION ====================

def validate_config():
    """Validate configuration on import"""
    issues = []

    # Validation logic here (currently none required for indices)
    pass

    if issues:
        print("\n".join(issues))
        return False

    print("✅ Main config validated")
    return True


# Auto-validate on import
validate_config()
