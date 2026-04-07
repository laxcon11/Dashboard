import yfinance as yf
import pandas as pd
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


from data_fetch import get_ticker_price, extract_price_data, batch_download
from utils import get_live_price_safe
from config import CACHE_TTL

symbol = "^IXIC"
print(f"Testing Symbol: {symbol}")

# 1. Fetch via batch_download (Historical)
data = batch_download([symbol], period="5d")
df = data.get(symbol)
hist_price, _, _ = extract_price_data(df)
print(f"Historical (Close Only): {hist_price}")

# 2. Fetch via get_live_price_safe(mode='close_only')
# This should now return hist_price even for ^IXIC
price_close, _, _ = get_live_price_safe(symbol, df, mode="close_only")
print(f"utils.get_live_price_safe(mode='close_only'): {price_close}")

# 3. Fetch via get_live_price_safe(mode='live_first')
price_live, _, _ = get_live_price_safe(symbol, df, mode="live_first")
print(f"utils.get_live_price_safe(mode='live_first'): {price_live}")

if price_close == hist_price:
    print("SUCCESS: Index now respects close_only mode.")
else:
    print("FAILURE: Index still forcing live_first.")
