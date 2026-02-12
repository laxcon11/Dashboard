"""
Diagnostic script to understand yfinance batch download structure
Run this to see what's actually being returned
"""

import yfinance as yf
import pandas as pd

# Test with a small set of different symbol types
test_symbols = [
    "^GSPC",      # S&P 500 (index)
    "^IXIC",      # NASDAQ (index)
    "EURUSD=X",   # EUR/USD (forex)
    "GBPUSD=X",   # GBP/USD (forex)
    "GC=F",       # Gold (commodity)
    "BTC-USD",    # Bitcoin (crypto)
]

print("="*60)
print("TESTING BATCH DOWNLOAD STRUCTURE")
print("="*60)

# Test batch download
print("\n1. Batch downloading symbols...")
data = yf.download(
    test_symbols,
    period="5d",
    group_by="ticker",
    progress=False,
    threads=True,
    auto_adjust=False
)

print(f"\nData type: {type(data)}")
print(f"Data shape: {data.shape if hasattr(data, 'shape') else 'N/A'}")

if hasattr(data, 'columns'):
    print(f"\nColumn structure: {data.columns}")
    print(f"Column levels: {data.columns.nlevels if hasattr(data.columns, 'nlevels') else 'N/A'}")

print("\n" + "="*60)
print("EXTRACTING INDIVIDUAL SYMBOLS")
print("="*60)

for symbol in test_symbols:
    print(f"\n--- {symbol} ---")
    try:
        # Method 1: Direct access
        if len(test_symbols) == 1:
            df = data
        else:
            df = data[symbol]

        print(f"Type: {type(df)}")
        print(f"Shape: {df.shape if hasattr(df, 'shape') else 'N/A'}")

        if isinstance(df, pd.DataFrame) and not df.empty:
            print(f"Columns: {df.columns.tolist()}")
            print(f"Length: {len(df)}")

            # Try to get Close price
            if 'Close' in df.columns:
                latest = df['Close'].iloc[-1]
                print(f"Latest Close: {latest}")
                print(f"Is NaN?: {pd.isna(latest)}")
            else:
                print("ERROR: No 'Close' column found!")

        else:
            print(f"ERROR: Empty or invalid DataFrame")

    except Exception as e:
        print(f"ERROR: {e}")

print("\n" + "="*60)
print("TESTING AUTO_ADJUST IMPACT")
print("="*60)

print("\nWith auto_adjust=True:")
data_adjusted = yf.download(
    ["^GSPC", "EURUSD=X"],
    period="5d",
    group_by="ticker",
    progress=False,
    auto_adjust=True
)

for symbol in ["^GSPC", "EURUSD=X"]:
    try:
        df = data_adjusted[symbol]
        if 'Close' in df.columns:
            print(f"{symbol}: {df['Close'].iloc[-1]:.2f}")
    except:
        print(f"{symbol}: FAILED")

print("\nWith auto_adjust=False:")
data_not_adjusted = yf.download(
    ["^GSPC", "EURUSD=X"],
    period="5d",
    group_by="ticker",
    progress=False,
    auto_adjust=False
)

for symbol in ["^GSPC", "EURUSD=X"]:
    try:
        df = data_not_adjusted[symbol]
        if 'Close' in df.columns:
            print(f"{symbol}: {df['Close'].iloc[-1]:.2f}")
    except:
        print(f"{symbol}: FAILED")

print("\n" + "="*60)
print("RECOMMENDATIONS")
print("="*60)

print("""
Based on results above:
1. Check if multi-level columns are causing issues
2. Verify 'Close' column exists and has data
3. Test if auto_adjust affects certain symbol types
4. Check for NaN values in the data
""")