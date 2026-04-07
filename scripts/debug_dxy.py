import yfinance as yf
import pandas as pd
from datetime import datetime

symbols = ['DX-Y.NYB', 'DX-Y.NYB', 'DXY']
results = []

for s in symbols:
    try:
        ticker = yf.Ticker(s)
        df = ticker.history(period='5d')
        if not df.empty:
            last_date = df.index.max()
            last_price = df['Close'].iloc[-1]
            results.append({
                'Symbol': s,
                'Last Date': last_date,
                'Last Price': round(last_price, 3),
                'Status': 'OK'
            })
        else:
            results.append({'Symbol': s, 'Status': 'Empty'})
    except Exception as e:
        results.append({'Symbol': s, 'Status': f'Error: {e}'})

print(pd.DataFrame(results))
print(f"\nCurrent Time (Local): {datetime.now()}")
