# 🚀 Dashboard Launcher

A multi-page Streamlit dashboard that tracks market conditions, liquidity, and leading indicators to help evaluate **Risk-On / Risk-Off regimes** and macro trends.

This project combines:

* Global markets
* Liquidity indicators
* Credit and commodity signals
* Risk scoring models
* Leading indicators

The goal is to provide a **fast, practical view of market conditions** in one place.

---

## Features

### 1. NSE Dashboard

* Watchlist tracking
* Technical indicators
* Volume and momentum signals

### 2. Global Markets

* Major global indices
* Commodities
* Currencies
* Crypto snapshot

### 3. Liquidity Dashboard

* Fed Balance Sheet
* Reverse Repo
* Treasury General Account
* Money supply indicators

### 4. Macro Risk Dashboard

* Risk-On / Risk-Off scoring
* Weighted macro indicators
* Liquidity overlay
* Trend charts and gauges

### 5. Leading Indicators Dashboard

* Yield curve signal
* Copper / Gold ratio
* Credit spread proxy (HYG / LQD)
* Dollar and yield trends
* Market impulse gauge

### 6. Trading Journal

* Log and track trades
* Performance statistics
* Historical trade analysis

---


## Project Structure

```
project/
│
├── app.py
├── config.py
├── data_fetch.py
│
├── pages/
│   ├── 0_NSE_Dashboard.py
│   ├── 1_Global_Markets.py
│   ├── 2_Money_Supply.py
│   ├── 3_Macro_Risk.py
│   ├── 4_Leading_Indicators.py
│   ├── 5_Trading_Journal.py
│   ├── 6_Regime_Settings.py
│   ├── 7_Portfolio_Risk.py
│   ├── 8_Ops_Automation.py
│   ├── 9_Prediction_Integrity.py
│   ├── 10_Scoring_Audit.py
│   ├── 11_Tradable_Universe.py
│   └── 12_Todo_Tracker.py
│
├── requirements.txt
├── .env.example
├── docs/
│   └── SCORING_LOGIC.md

└── README.md
```

---

## Installation

### 1. Clone the repository

```
git clone https://github.com/yourusername/trading-dashboard.git
cd trading-dashboard
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Set environment variables

Create a `.env` file from template:

```
cp .env.example .env
```

---

## Running the Dashboard

```
streamlit run app.py
```

The dashboard will open in your browser.

---

## Data Sources

* Yahoo Finance (market data)
* FRED (liquidity and macro data)
* NSE India (VIX and indices)

---

## Design Principles

This project is designed for:

* Fast loading
* Clean modular structure
* Reusable data utilities
* Cached downloads
* Expandable dashboards

---

## Future Improvements

Planned upgrades:

* Global liquidity composite
* Market breadth indicators
* Earnings trend indicators
* Sector rotation signals
* Risk regime history database

---

## Disclaimer

This dashboard is for educational and research purposes only.
Not investment advice.

---

## Documentation

Detailed scoring and governance logic:
- `docs/SCORING_LOGIC.md`

Recommended onboarding docs:
- `docs/USER_GUIDE.md`
- `docs/WORKFLOW.md`

---

## Author

Built using:

* Python
* Streamlit
* Pandas
* Plotly
* Yahoo Finance API
* FRED API
