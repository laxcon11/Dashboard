import yfinance as yf
import pandas as pd

try:
    ticker = yf.Ticker("RELIANCE.NS")
    
    # Check daily data
    print("--- DAILY DATA (1d) ---")
    hist = ticker.history(period="5d", interval="1d")
    print(hist.tail())
    
    # Check intraday data
    print("\n--- INTRADAY DATA (15m) ---")
    intra = ticker.history(period="1d", interval="15m")
    print(intra.tail())
    
except Exception as e:
    print(f"Error: {e}")
