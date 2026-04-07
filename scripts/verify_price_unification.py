import yfinance as yf
import pandas as pd
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


from data_fetch import get_ticker_price, extract_price_data, batch_download
from config import CACHE_TTL

symbol = "DX-Y.NYB"
print(f"Testing Symbol: {symbol}")

# 1. Fetch via batch_download (Historical - what Leading Indicators used previously)
data = batch_download([symbol], period="1y")
df = data.get(symbol)
hist_price, _, _ = extract_price_data(df)
print(f"Historical (Close Only): {hist_price}")

# 2. Fetch via get_ticker_price (Live - what Global Markets uses)
live_price, _, _ = get_ticker_price(symbol)
print(f"Live (LTP): {live_price}")

# 3. Simulate get_live_price_safe(mode='live_first')
# This is what Leading Indicators now uses for display
if live_price is not None:
    final_price = live_price
else:
    final_price = hist_price
print(f"Unified Display Mode (Live First): {final_price}")

if live_price is not None and hist_price is not None:
    diff = abs(live_price - hist_price)
    print(f"Difference: {diff:.4f} ({ (diff/hist_price)*100:.2f}%)")
