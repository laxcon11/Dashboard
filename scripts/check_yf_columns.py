import yfinance as yf
import pandas as pd

symbol = "RELIANCE.NS"
print(f"Checking data for {symbol}...")

try:
    # 1. Check Daily Data
    ticker = yf.Ticker(symbol)
    df_daily = ticker.history(period="5d", interval="1d")
    print("\n--- DAILY DATA COLUMNS ---")
    print(df_daily.columns.tolist())
    print(df_daily.tail(2))

    # 2. Check Intraday Data (5m)
    df_intra = ticker.history(period="1d", interval="5m")
    print("\n--- INTRADAY (5m) DATA COLUMNS ---")
    print(df_intra.columns.tolist())
    print(df_intra.tail(2))

    # 3. Check Ticker Info
    info = ticker.info
    print("\n--- TICKER INFO FIELDS (Containing 'vwap' or 'average') ---")
    for key in info:
        if 'vwap' in key.lower() or 'average' in key.lower() or 'price' in key.lower():
            print(f"{key}: {info[key]}")

except Exception as e:
    print(f"Error: {e}")
