"""
Main Configuration file for Trading Dashboard Suite
UPDATED: Removed Midcap indicator (broken symbol)
NSE-specific config moved to nse_config.py
"""

import os
import logging
from dotenv import load_dotenv

_log = logging.getLogger(__name__)

# ==================== LOAD ENVIRONMENT VARIABLES ====================
load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY", "")

if not FRED_API_KEY:
    _log.warning("FRED_API_KEY not found in .env - Liquidity dashboard features disabled")


# ==================== MAIN INDICES ====================
# Used across all dashboards for market overview

MAIN_INDICES = {
    '^NSEI': 'NIFTY 50',
    '^NSEBANK': 'BANK NIFTY',
    '^CNXSC': 'NIFTY SMALLCAP',
    '^CNXIT': 'NIFTY IT'
}


# ==================== GLOBAL MARKETS ====================

# Quick risk snapshot (top of Global Markets dashboard)
GLOBAL_RISK_SNAPSHOT = {
    "^GSPC": "S&P 500",
    "^NDX": "NASDAQ 100",
    "DX-Y.NYB": "Dollar Index",
    "^TNX": "US 10Y Yield",
    "CL=F": "Crude Oil",
    "GC=F": "Gold",
    "BTC-USD": "Bitcoin"
}

# All global indices
GLOBAL_INDICES = {
    "^GSPC": "S&P 500",
    "^NDX": "NASDAQ 100",
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
    "USDCAD=X": "USD/CAD",
    "USDINR=X": "USD/INR"
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
    "^IXIC": "NASDAQ COMP",
    "^NDX": "NASDAQ 100",
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
    "^NDX": "Nasdaq 100",
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
    "^NDX": 2,
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
    "^NDX": "NASDAQ 100",
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

# Additional FRED macro context series (separate from liquidity dashboard series)
FRED_SERIES_INDIA_MACRO = {
    "USD/INR Exchange Rate": "DEXINUS",
    "US CPI (YoY)": "CPIAUCSL",
    "US Core PCE": "PCEPILFE",
    "US Unemployment Rate": "UNRATE",
    "US Industrial Production": "INDPRO",
    "WTI Crude Oil Price": "DCOILWTICO",
    "Gold Price (FRED)": "GOLDAMGBD228NLBM",
    "US 10Y Yield": "DGS10",
    "ECB Balance Sheet (EUR bn)": "ECBASSETS",
    "US Credit Spread (BAA-AAA)": "BAA10Y",
}


# ==================== RSS NEWS FEEDS ====================
# Every feed maps directly to a tracked signal, sector, or macro factor.

RSS_FEEDS = {
    # Market overview & regime
    "ET Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Moneycontrol Markets": "https://www.moneycontrol.com/rss/marketsindia.xml",
    "Business Standard Markets": "https://www.business-standard.com/rss/markets-106.rss",
    "NSE Official Press": "https://nsearchives.nseindia.com/content/press/press.xml",
    "SEBI Orders & Circulars": "https://www.sebi.gov.in/sebiweb/other/RssFeed.jsp?sectionId=1",

    # Macro regime inputs
    "Reuters Fed/Economy": "https://feeds.reuters.com/reuters/businessNews",
    "FT Markets": "https://www.ft.com/rss/home",
    "Bloomberg Economics": "https://feeds.bloomberg.com/economics/news.rss",
    "WSJ Economy": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
    "ET Rupee / Forex": "https://economictimes.indiatimes.com/markets/forex/rssfeeds/1977588.cms",
    "Reuters Forex": "https://feeds.reuters.com/reuters/MBSfunds",
    "Reuters Oil": "https://feeds.reuters.com/reuters/businessNews",
    "ET Oil & Gas": "https://economictimes.indiatimes.com/industry/energy/oil-gas/rssfeeds/13358093.cms",
    "Platts/S&P Oil": "https://www.spglobal.com/commodityinsights/en/rss-feed/oil",
    "ET Commodities": "https://economictimes.indiatimes.com/markets/commodities/rssfeeds/1808152.cms",
    "Kitco Gold": "https://feeds.kitco.com/KitcoNewsRSS",
    "Reuters Credit": "https://feeds.reuters.com/reuters/businessNews",
    "RBI Press Releases": "https://rbi.org.in/scripts/rss.aspx",
    "ET RBI": "https://economictimes.indiatimes.com/news/economy/policy/rssfeeds/1373380680.cms",

    # Institutional flows
    "ET FII/DII Flows": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2143429.cms",
    "NSDL FPI Data": "https://www.fpi.nsdl.co.in/web/Reports/Rss.aspx",
    "Moneycontrol FII": "https://www.moneycontrol.com/rss/fiidii.xml",

    # Gift Nifty / pre-market
    "ET Gift Nifty / SGX": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2143429.cms",
    "Moneycontrol Pre-market": "https://www.moneycontrol.com/rss/marketsindia.xml",

    # Sectors
    "ET Banking & Finance": "https://economictimes.indiatimes.com/industry/banking/finance/rssfeeds/13358259.cms",
    "BS Banking": "https://www.business-standard.com/rss/finance-103.rss",
    "RBI Banking Regulation": "https://rbi.org.in/scripts/rss.aspx",
    "Moneycontrol Banking": "https://www.moneycontrol.com/rss/marketsindia.xml",
    "ET Technology": "https://economictimes.indiatimes.com/tech/rssfeeds/13357270.cms",
    "BS Tech": "https://www.business-standard.com/rss/technology-108.rss",
    "Nasscom": "https://nasscom.in/rss.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Information": "https://www.theinformation.com/feed",
    "ET Pharma": "https://economictimes.indiatimes.com/industry/healthcare/biotech/pharmaceuticals/rssfeeds/1520885659.cms",
    "BS Pharma": "https://www.business-standard.com/rss/companies-101.rss",
    "FDA Drug Approvals": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml",
    "FDA Warning Letters": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/warning-letters/rss.xml",
    "ET Energy": "https://economictimes.indiatimes.com/industry/energy/rssfeeds/2143429.cms",
    "Ministry of Power India": "https://powermin.gov.in/en/rss.xml",
    "Mercom India (Renewables)": "https://mercomindia.com/feed/",
    "IEA Oil Market": "https://www.iea.org/news/rss",
    "ET Metals": "https://economictimes.indiatimes.com/industry/indl-goods/svs/metals-mining/rssfeeds/13358209.cms",
    "Steel Mint": "https://www.steelmint.com/rss/news.rss",
    "Metal Miner": "https://agmetalminer.com/feed/",
    "ET Auto": "https://economictimes.indiatimes.com/industry/auto/rssfeeds/35443329.cms",
    "BS Auto": "https://www.business-standard.com/rss/automobile-104.rss",
    "SIAM (Auto Sales Data)": "https://www.siam.in/rss.aspx",
    "ET Real Estate": "https://economictimes.indiatimes.com/industry/services/property-/-cstruction/rssfeeds/13358319.cms",
    "PropTiger/Housing": "https://www.housing.com/news/feed/",
    "Knight Frank India": "https://www.knightfrank.co.in/blog/feed/",
    "ET Cement": "https://economictimes.indiatimes.com/industry/indl-goods/svs/cement/rssfeeds/13358319.cms",
    "Cement Manufacturers Assoc": "https://www.cmaindia.org/rss/news.xml",
    "ET FMCG": "https://economictimes.indiatimes.com/industry/cons-products/fmcg/rssfeeds/13358309.cms",
    "BS FMCG": "https://www.business-standard.com/rss/companies-101.rss",
    "ET Capital Goods": "https://economictimes.indiatimes.com/industry/indl-goods/svs/engineering/rssfeeds/13358199.cms",
    "Ministry of Defence India": "https://mod.gov.in/rss.xml",
    "Indian Defence Review": "https://www.indiandefencereview.com/feed/",
    "ET Telecom": "https://economictimes.indiatimes.com/industry/telecom/rssfeeds/13358249.cms",
    "Telecom Talk": "https://telecomtalk.info/feed/",
    "ET Consumer / Retail": "https://economictimes.indiatimes.com/industry/services/retail/rssfeeds/13358329.cms",
    "ET Hospitality": "https://economictimes.indiatimes.com/industry/services/hotels-/-restaurants/rssfeeds/13358339.cms",
    "ET Chemicals": "https://economictimes.indiatimes.com/industry/chemicals/rssfeeds/2143429.cms",
    "ICIS Chemical News": "https://www.icis.com/explore/resources/news/feed/",
    "ET Insurance": "https://economictimes.indiatimes.com/industry/banking/insurance/rssfeeds/13358269.cms",
    "IRDA Press": "https://irdai.gov.in/rss.xml",
    "ET Aviation": "https://economictimes.indiatimes.com/industry/transportation/airlines-/-aviation/rssfeeds/13358369.cms",
    "ET Shipping & Ports": "https://economictimes.indiatimes.com/industry/transportation/shipping-/-transport/rssfeeds/13358379.cms",
    "Reuters World Markets": "https://feeds.reuters.com/reuters/businessNews",
    "AP Business": "https://rsshub.app/ap/topics/apf-business",
    "Nikkei Asia": "https://asia.nikkei.com/rss/feed/nar",
    "ET Earnings": "https://economictimes.indiatimes.com/markets/earnings/rssfeeds/2143429.cms",
    "BS Results": "https://www.business-standard.com/rss/companies-101.rss",
}

RSS_FEED_TAGS = {
    "regime_overview": [
        "ET Markets", "Moneycontrol Markets", "Business Standard Markets", "NSE Official Press", "Reuters World Markets",
    ],
    "macro_us_fed": [
        "Reuters Fed/Economy", "FT Markets", "Bloomberg Economics", "WSJ Economy",
    ],
    "macro_crude_oil": [
        "Reuters Oil", "ET Oil & Gas", "Platts/S&P Oil", "IEA Oil Market",
    ],
    "macro_gold": [
        "ET Commodities", "Kitco Gold",
    ],
    "macro_dxy_usdinr": [
        "ET Rupee / Forex", "Reuters Forex",
    ],
    "macro_rbi": [
        "RBI Press Releases", "ET RBI",
    ],
    "fii_dii_flows": [
        "ET FII/DII Flows", "NSDL FPI Data", "Moneycontrol FII",
    ],
    "gift_nifty_premarket": [
        "ET Gift Nifty / SGX", "Moneycontrol Pre-market",
    ],
    "sector_banks_nbfc": [
        "ET Banking & Finance", "BS Banking", "RBI Banking Regulation", "Moneycontrol Banking",
    ],
    "sector_it_tech": [
        "ET Technology", "BS Tech", "Nasscom", "TechCrunch",
    ],
    "sector_pharma": [
        "ET Pharma", "BS Pharma", "FDA Drug Approvals", "FDA Warning Letters",
    ],
    "sector_energy": [
        "ET Energy", "Ministry of Power India", "Mercom India (Renewables)", "IEA Oil Market",
    ],
    "sector_metals": [
        "ET Metals", "Steel Mint", "Metal Miner",
    ],
    "sector_auto": [
        "ET Auto", "BS Auto", "SIAM (Auto Sales Data)",
    ],
    "sector_realestate": [
        "ET Real Estate", "PropTiger/Housing", "Knight Frank India",
    ],
    "sector_cement": [
        "ET Cement", "Cement Manufacturers Assoc",
    ],
    "sector_fmcg": [
        "ET FMCG", "BS FMCG",
    ],
    "sector_capital_goods_defence": [
        "ET Capital Goods", "Ministry of Defence India", "Indian Defence Review",
    ],
    "sector_telecom": [
        "ET Telecom", "Telecom Talk",
    ],
    "sector_consumer_services": [
        "ET Consumer / Retail", "ET Hospitality",
    ],
    "sector_chemicals": [
        "ET Chemicals", "ICIS Chemical News",
    ],
    "sector_insurance_cm": [
        "ET Insurance", "IRDA Press",
    ],
    "sector_services_ports_aviation": [
        "ET Aviation", "ET Shipping & Ports",
    ],
    "earnings_results": [
        "ET Earnings", "BS Results",
    ],
    "global_indices": [
        "Reuters World Markets", "AP Business", "Nikkei Asia", "FT Markets",
    ],
}

RSS_DEFAULT_ACTIVE = [
    "ET Markets",
    "Business Standard Markets",
    "Reuters Fed/Economy",
    "RBI Press Releases",
    "ET FII/DII Flows",
    "ET Banking & Finance",
    "ET Technology",
    "Kitco Gold",
    "ET Oil & Gas",
    "ET Earnings",
]

RSS_CACHE_TTL = 600
RSS_MAX_ITEMS_PER_FEED = 8
RSS_MAX_TOTAL_ITEMS = 60


# ==================== FINNHUB ====================

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
if not FINNHUB_API_KEY:
    _log.warning("FINNHUB_API_KEY not found in .env - Fundamentals features disabled")

FINNHUB_NSE_PREFIX = "NSE:"
FINNHUB_METRICS = [
    "peBasicExclExtraTTM",
    "pbAnnual",
    "epsBasicExclExtraItemsTTM",
    "revenueGrowthTTMYoy",
    "grossMarginTTM",
    "debtEquityAnnual",
    "dividendYieldIndicatedAnnual",
    "52WeekHigh",
    "52WeekLow",
    "beta",
]
FINNHUB_NEWS_TTL = 900
FINNHUB_FUNDAMENTALS_TTL = 3600
FINNHUB_RATE_LIMIT_PAUSE = 0.5


# ==================== EODHD ====================

EODHD_API_KEY = os.getenv("EODHD_API_KEY", "").strip()
if not EODHD_API_KEY:
    _log.warning("EODHD_API_KEY not found in .env - India fundamentals/news fallback disabled")

EODHD_BASE_URL = os.getenv("EODHD_BASE_URL", "https://eodhd.com").strip().rstrip("/")
EODHD_NSE_SUFFIX = ".NSE"
EODHD_NEWS_TTL = 900
EODHD_FUNDAMENTALS_TTL = 3600
EODHD_RATE_LIMIT_PAUSE = 0.3


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

# Price source consistency mode across pages:
# - close_only: always use latest cached/batch Close values (recommended for cross-page consistency)
# - live_first: try live ticker quote first, fallback to Close
PRICE_FETCH_MODE = os.getenv("PRICE_FETCH_MODE", "close_only").strip().lower()
if PRICE_FETCH_MODE not in {"close_only", "live_first"}:
    PRICE_FETCH_MODE = "close_only"

# Data health thresholds
DATA_STALENESS_WARN_DAYS = int(os.getenv("DATA_STALENESS_WARN_DAYS", "2"))
DATA_STALENESS_ERROR_DAYS = int(os.getenv("DATA_STALENESS_ERROR_DAYS", "5"))


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
# End-of-day authoritative reconcile policy:
# - Intraday: use local + API (Bhavcopy only as fallback for missing/stale failures)
# - After cutoff IST: overwrite latest NSE day from Bhavcopy for parity with exchange close
BHAVCOPY_EOD_RECONCILE_ENABLED = os.getenv("BHAVCOPY_EOD_RECONCILE_ENABLED", "1") == "1"
BHAVCOPY_EOD_RECONCILE_CUTOFF_IST_HOUR = int(os.getenv("BHAVCOPY_EOD_RECONCILE_CUTOFF_IST_HOUR", "20"))

# ==================== GIFT NIFTY OVERLAY (DISPLAY/ALERT ONLY) ====================

# Feature flags (default ON for operational readiness)
GIFT_NIFTY_DASHBOARD_CARD = os.getenv("GIFT_NIFTY_DASHBOARD_CARD", "1") == "1"
GIFT_NIFTY_INV_PREFLAG = os.getenv("GIFT_NIFTY_INV_PREFLAG", "1") == "1"
GIFT_NIFTY_MACRO_BADGE = os.getenv("GIFT_NIFTY_MACRO_BADGE", "1") == "1"

# Data source options:
# - API URL: optional endpoint returning JSON with price/timestamp fields.
# - Local snapshot: optional broker-fed local JSON fallback.
GIFT_NIFTY_API_URL = os.getenv("GIFT_NIFTY_API_URL", "").strip()
GIFT_NIFTY_API_KEY = os.getenv("GIFT_NIFTY_API_KEY", "").strip()
GIFT_NIFTY_LOCAL_SNAPSHOT = os.getenv("GIFT_NIFTY_LOCAL_SNAPSHOT", "./notes/gift_nifty_snapshot.json").strip()
GIFT_NIFTY_GROWW_FALLBACK = os.getenv("GIFT_NIFTY_GROWW_FALLBACK", "1") == "1"
GIFT_NIFTY_GROWW_URL = os.getenv(
    "GIFT_NIFTY_GROWW_URL",
    "https://groww.in/indices/global-indices/sgx-nifty",
).strip()
GIFT_NIFTY_MONEYCONTROL_FALLBACK = os.getenv("GIFT_NIFTY_MONEYCONTROL_FALLBACK", "0") == "1"
GIFT_NIFTY_MONEYCONTROL_URL = os.getenv("GIFT_NIFTY_MONEYCONTROL_URL", "").strip()

# Display behavior
GIFT_NIFTY_SESSION_START_IST_HOUR = int(os.getenv("GIFT_NIFTY_SESSION_START_IST_HOUR", "16"))
GIFT_NIFTY_COLLAPSE_IST_HOUR = int(os.getenv("GIFT_NIFTY_COLLAPSE_IST_HOUR", "10"))
GIFT_NIFTY_FLAT_THRESHOLD_PCT = float(os.getenv("GIFT_NIFTY_FLAT_THRESHOLD_PCT", "0.5"))
GIFT_NIFTY_STRESS_FLAG_PCT = float(os.getenv("GIFT_NIFTY_STRESS_FLAG_PCT", "1.0"))


# ==================== VALIDATION ====================

def validate_config():
    """Validate configuration on import"""
    issues = []

    # Validation logic here (currently none required for indices)
    pass

    if issues:
        _log.warning("Config issues:\n%s", "\n".join(issues))
        return False

    _log.info("Main config validated")
    return True


# Auto-validate on import
validate_config()
