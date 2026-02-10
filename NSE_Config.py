"""
NSE-Specific Configuration
Contains NIFTY 200 stocks categorized by sectors for easy selection
"""

# ==================== SECTOR INDICES ====================

NSE_SECTOR_INDICES = {
    '^NSEBANK': 'Banking',
    '^CNXCAP': 'Capital Market',  # Added
    '^CNXIT': 'IT',
    '^CNXAUTO': 'Auto',
    '^CNXPHARMA': 'Pharma',
    '^CNXFMCG': 'FMCG',
    '^CNXMETAL': 'Metal',
    '^CNXREALTY': 'Realty',
    '^CNXENERGY': 'Energy'
}

# ==================== NIFTY 200 STOCKS BY SECTOR ====================

# Banking & Financial Services
BANKING_STOCKS = [
    'HDFCBANK.NS',
    'ICICIBANK.NS',
    'SBIN.NS',
    'KOTAKBANK.NS',
    'AXISBANK.NS',
    'INDUSINDBK.NS',
    'BANDHANBNK.NS',
    'FEDERALBNK.NS',
    'IDFCFIRSTB.NS',
    'PNB.NS',
    'BANKBARODA.NS',
    'AUBANK.NS'
]

# Capital Markets & Insurance
CAPITAL_MARKET_STOCKS = [
    'BAJAJFINSV.NS',
    'BAJFINANCE.NS',
    'HDFCLIFE.NS',
    'SBILIFE.NS',
    'ICICIGI.NS',
    'HDFCAMC.NS',
    'MUTHOOTFIN.NS',
    'CHOLAFIN.NS',
    'LICHSGFIN.NS',
    'CDSL.NS'
]

# IT & Technology
IT_STOCKS = [
    'TCS.NS',
    'INFY.NS',
    'WIPRO.NS',
    'HCLTECH.NS',
    'TECHM.NS',
    'LTIM.NS',
    'COFORGE.NS',
    'PERSISTENT.NS',
    'MPHASIS.NS',
    'LTTS.NS'
]

# Auto & Auto Components
AUTO_STOCKS = [
    'MARUTI.NS',
    'TATAMOTORS.NS',
    'M&M.NS',
    'BAJAJ-AUTO.NS',
    'EICHERMOT.NS',
    'HEROMOTOCO.NS',
    'TVSMOTOR.NS',
    'MOTHERSON.NS',
    'BOSCHLTD.NS',
    'BHARATFORG.NS'
]

# Pharma & Healthcare
PHARMA_STOCKS = [
    'SUNPHARMA.NS',
    'DRREDDY.NS',
    'DIVISLAB.NS',
    'CIPLA.NS',
    'AUROPHARMA.NS',
    'LUPIN.NS',
    'TORNTPHARM.NS',
    'ALKEM.NS',
    'BIOCON.NS',
    'LAURUSLABS.NS'
]

# FMCG & Consumer
FMCG_STOCKS = [
    'HINDUNILVR.NS',
    'ITC.NS',
    'NESTLEIND.NS',
    'BRITANNIA.NS',
    'DABUR.NS',
    'MARICO.NS',
    'GODREJCP.NS',
    'COLPAL.NS',
    'TATACONSUM.NS',
    'UBL.NS'
]

# Metals & Mining
METAL_STOCKS = [
    'TATASTEEL.NS',
    'JSWSTEEL.NS',
    'HINDALCO.NS',
    'VEDL.NS',
    'COALINDIA.NS',
    'NATIONALUM.NS',
    'JINDALSTEL.NS',
    'SAIL.NS',
    'NMDC.NS',
    'HINDZINC.NS'
]

# Real Estate & Infrastructure
REALTY_STOCKS = [
    'DLF.NS',
    'GODREJPROP.NS',
    'OBEROIRLTY.NS',
    'PRESTIGE.NS',
    'PHOENIXLTD.NS',
    'BRIGADE.NS',
    'SOBHA.NS',
    'LODHA.NS',
    'SUNTECK.NS',
    'IBREALEST.NS'
]

# Energy & Power
ENERGY_STOCKS = [
    'RELIANCE.NS',
    'ONGC.NS',
    'BPCL.NS',
    'IOC.NS',
    'NTPC.NS',
    'POWERGRID.NS',
    'ADANIGREEN.NS',
    'TATAPOWER.NS',
    'ADANIPOWER.NS',
    'TORNTPOWER.NS'
]

# Telecom & Communication
TELECOM_STOCKS = [
    'BHARTIARTL.NS',
    'IDEA.NS',
    'INDUSINDBK.NS',
    'TATACOMM.NS'
]

# Cement & Construction
CEMENT_STOCKS = [
    'ULTRACEMCO.NS',
    'GRASIM.NS',
    'SHREECEM.NS',
    'AMBUJACEM.NS',
    'ACC.NS',
    'JKCEMENT.NS',
    'RAMCOCEM.NS',
    'HEIDELBERG.NS'
]

# Diversified & Conglomerates
DIVERSIFIED_STOCKS = [
    'LT.NS',
    'ADANIENT.NS',
    'SIEMENS.NS',
    'ABB.NS',
    'HAVELLS.NS',
    'VOLTAS.NS',
    'CUMMINSIND.NS',
    'THERMAX.NS'
]

# Mid-Cap High Growth
MIDCAP_STOCKS = [
    'KAYNES.NS',
    'POLYCAB.NS',
    'DIXON.NS',
    'ZOMATO.NS',
    'PAYTM.NS',
    'NYKAA.NS',
    'DMART.NS',
    'ASTRAL.NS',
    'FLUOROCHEM.NS',
    'CAMS.NS',
    'ZYDUSLIFE.NS',
    'PAGEIND.NS'
]

# Small-Cap High Potential
SMALLCAP_STOCKS = [
    'TATAELXSI.NS',
    'CHAMBLFERT.NS',
    'DEEPAKNTR.NS',
    'APLAPOLLO.NS',
    'TIINDIA.NS',
    'ATUL.NS',
    'CLEAN.NS',
    'IRCTC.NS',
    'ALKYLAMINE.NS',
    'VAIBHAVGBL.NS'
]

# ==================== CATEGORIZED STOCK GROUPS ====================

STOCK_CATEGORIES = {
    '🏦 Banking': BANKING_STOCKS,
    '💰 Capital Markets': CAPITAL_MARKET_STOCKS,
    '💻 IT & Tech': IT_STOCKS,
    '🚗 Auto': AUTO_STOCKS,
    '💊 Pharma': PHARMA_STOCKS,
    '🛒 FMCG': FMCG_STOCKS,
    '⚙️ Metals': METAL_STOCKS,
    '🏗️ Real Estate': REALTY_STOCKS,
    '⚡ Energy': ENERGY_STOCKS,
    '📱 Telecom': TELECOM_STOCKS,
    '🏭 Cement': CEMENT_STOCKS,
    '🔧 Diversified': DIVERSIFIED_STOCKS,
    '📈 Mid-Cap Growth': MIDCAP_STOCKS,
    '🌟 Small-Cap': SMALLCAP_STOCKS
}

# ==================== NIFTY 200 COMPLETE LIST ====================
# Consolidated list of all stocks
NIFTY_200 = (
        BANKING_STOCKS +
        CAPITAL_MARKET_STOCKS +
        IT_STOCKS +
        AUTO_STOCKS +
        PHARMA_STOCKS +
        FMCG_STOCKS +
        METAL_STOCKS +
        REALTY_STOCKS +
        ENERGY_STOCKS +
        TELECOM_STOCKS +
        CEMENT_STOCKS +
        DIVERSIFIED_STOCKS +
        MIDCAP_STOCKS +
        SMALLCAP_STOCKS
)

# Remove duplicates
NIFTY_200 = list(dict.fromkeys(NIFTY_200))

# ==================== PRESET WATCHLISTS ====================

PRESET_WATCHLISTS = {
    'Top 20 by Market Cap': [
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS',
        'HINDUNILVR.NS', 'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'KOTAKBANK.NS',
        'LT.NS', 'AXISBANK.NS', 'BAJFINANCE.NS', 'MARUTI.NS', 'HCLTECH.NS',
        'SUNPHARMA.NS', 'NTPC.NS', 'ULTRACEMCO.NS', 'TATAMOTORS.NS', 'ONGC.NS'
    ],

    'High Growth Mid-Caps': [
        'KAYNES.NS', 'DIXON.NS', 'POLYCAB.NS', 'DMART.NS', 'ASTRAL.NS',
        'ZOMATO.NS', 'NYKAA.NS', 'FLUOROCHEM.NS', 'CAMS.NS', 'ZYDUSLIFE.NS',
        'PAGEIND.NS', 'PERSISTENT.NS', 'COFORGE.NS', 'MPHASIS.NS', 'LTTS.NS',
        'GODREJPROP.NS', 'PRESTIGE.NS', 'OBEROIRLTY.NS', 'PHOENIXLTD.NS', 'BRIGADE.NS'
    ],

    'Banking & Finance': [
        'HDFCBANK.NS', 'ICICIBANK.NS', 'SBIN.NS', 'KOTAKBANK.NS', 'AXISBANK.NS',
        'INDUSINDBK.NS', 'BAJFINANCE.NS', 'BAJAJFINSV.NS', 'HDFCLIFE.NS', 'SBILIFE.NS',
        'ICICIGI.NS', 'HDFCAMC.NS', 'CHOLAFIN.NS', 'MUTHOOTFIN.NS', 'BANDHANBNK.NS',
        'FEDERALBNK.NS', 'IDFCFIRSTB.NS', 'PNB.NS', 'BANKBARODA.NS', 'AUBANK.NS'
    ],

    'IT & Digital': [
        'TCS.NS', 'INFY.NS', 'HCLTECH.NS', 'WIPRO.NS', 'TECHM.NS',
        'LTIM.NS', 'PERSISTENT.NS', 'COFORGE.NS', 'MPHASIS.NS', 'LTTS.NS',
        'TATAELXSI.NS', 'ZOMATO.NS', 'NYKAA.NS', 'PAYTM.NS', 'IRCTC.NS',
        'BHARTIARTL.NS', 'TATACOMM.NS', 'DIXON.NS', 'KAYNES.NS', 'POLYCAB.NS'
    ],

    'Dividend Aristocrats': [
        'ITC.NS', 'HINDUNILVR.NS', 'COALINDIA.NS', 'NTPC.NS', 'POWERGRID.NS',
        'VEDL.NS', 'NMDC.NS', 'ONGC.NS', 'IOC.NS', 'BPCL.NS',
        'HINDZINC.NS', 'SBIN.NS', 'ICICIBANK.NS', 'HDFCBANK.NS', 'TATASTEEL.NS',
        'JSWSTEEL.NS', 'HINDALCO.NS', 'BHARTIARTL.NS', 'MARICO.NS', 'DABUR.NS'
    ],

    'Swing Trading Favorites': [
        'RELIANCE.NS', 'TATAMOTORS.NS', 'TATASTEEL.NS', 'JSWSTEEL.NS', 'BAJFINANCE.NS',
        'AXISBANK.NS', 'ICICIBANK.NS', 'MARUTI.NS', 'M&M.NS', 'LT.NS',
        'SUNPHARMA.NS', 'DRREDDY.NS', 'BHARTIARTL.NS', 'ADANIENT.NS', 'VEDL.NS',
        'HINDALCO.NS', 'ULTRACEMCO.NS', 'GRASIM.NS', 'INDUSINDBK.NS', 'BAJAJ-AUTO.NS'
    ]
}


# ==================== VALIDATION ====================

def get_stocks_by_category(category_name):
    """Get stocks for a specific category"""
    return STOCK_CATEGORIES.get(category_name, [])


def get_preset_watchlist(preset_name):
    """Get stocks for a preset watchlist"""
    return PRESET_WATCHLISTS.get(preset_name, [])


def validate_nse_config():
    """Validate NSE configuration"""
    print(f"✅ NSE Config loaded")
    print(f"   Total stocks in NIFTY 200: {len(NIFTY_200)}")
    print(f"   Categories available: {len(STOCK_CATEGORIES)}")
    print(f"   Preset watchlists: {len(PRESET_WATCHLISTS)}")

    # Check for duplicates
    if len(NIFTY_200) != len(set(NIFTY_200)):
        print("⚠️  Warning: Duplicate stocks found in NIFTY_200")

    return True


# Auto-validate on import
validate_nse_config()