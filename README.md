# 🚀 NSE Swing Trading Dashboard

A multi-page Streamlit dashboard for Indian equity swing trading. Tracks market conditions, liquidity, regime scoring, and leading indicators to evaluate **Risk-On / Selective / Defensive / Crisis** regimes.

---

## Features

| # | Page | What it does |
|---|------|-------------|
| 0 | **NSE Dashboard** | Watchlist tracking, swing rankings, technical indicators, volume/momentum signals |
| 1 | **Global Markets** | Global indices, commodities, currencies, crypto snapshot |
| 2 | **Money Supply** | Fed balance sheet, reverse repo, TGA, M2, SOFR-IORB spread |
| 3 | **Macro Risk** | Risk-On/Off scoring, weighted macro & liquidity indicators, regime classification |
| 4 | **Leading Indicators** | Yield curve, copper/gold ratio, credit spreads (HYG/LQD), dollar & yield trends |
| 5 | **Trading Journal** | Trade logging with legs, R-multiples, performance stats |
| 6 | **Regime Settings** | Tunable macro/liquidity weights and thresholds |
| 7 | **Portfolio Risk** | Concentration, sector exposure, risk checks |
| 8 | **Ops Automation** | EOD pipeline, alerts, data trust scoring, recovery tools |
| 9 | **Prediction Integrity** | Immutable prediction log, Brier score, calibration proposals |
| 10 | **Scoring Audit** | Regime scoring transparency and audit reports |
| 11 | **Tradable Universe** | NIFTY 200 screener with setup family detection |
| 12 | **Todo Tracker** | Project roadmap and task tracking |
| 13 | **India Macro Context** | FII/DII flows, India-specific macro signals |
| 14 | **News Feed** | 60+ curated RSS feeds with health monitoring |
| 15 | **Stock Fundamentals** | EODHD/Finnhub fundamentals and stock-level news |

---

## Project Structure

```
Dashboard/
├── app.py                     # Entry point / launcher
├── config.py                  # Global settings, API keys, thresholds
├── NSE_Config.py              # NIFTY 200 stocks by sector, preset watchlists
├── data_fetch.py              # Central data pipeline (Yahoo, FRED, BhavCopy, RSS, EODHD, Finnhub)
├── utils.py                   # Shared UI components, charts, price formatting
├── analytics.py               # Scoring logic (momentum, pullback, liquidity)
├── indicators.py              # RSI, EMA, ATR, MACD, Bollinger, Stochastic
├── regime_model.py            # Regime settings load/save/defaults
├── regime_state.py            # Regime snapshot persistence
├── factor_registry.py         # Cross-page factor metadata (SSOT)
├── gift_nifty.py              # GIFT Nifty multi-source overlay
├── india_context.py           # FII/DII flows, India macro signals
├── trading_calendar.py        # NSE holiday-aware business days
├── watchlist_manager.py       # JSON-backed watchlist CRUD
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variable template
├── setup.sh / setup.bat       # Quick-start setup scripts
│
├── pages/                     # 16 Streamlit sub-pages (see table above)
├── scripts/                   # Operational & test scripts (19 files)
├── prediction_integrity/      # Prediction engine, store, schema
├── data/                      # Parquet history, BhavCopy, snapshots
├── notes/                     # JSON config/state (regime, journal, holidays)
├── logs/                      # Runtime logs, parity reports, trust scores
├── exports/                   # Generated PDF reports
└── docs/                      # Documentation (14 files)
```

---

## Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd Dashboard

# Option A: Use setup script
./setup.sh    # macOS/Linux
setup.bat     # Windows

# Option B: Manual
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure API keys
cp .env.example .env
# Edit .env with your FRED, Finnhub, EODHD keys

# Run
streamlit run app.py
```

---

## Data Sources

| Source | Used For |
|--------|----------|
| Yahoo Finance | Market data (stocks, indices, FX, crypto, commodities) |
| FRED | Liquidity & macro data (Fed balance sheet, yields, M2, etc.) |
| NSE India | VIX, BhavCopy (official exchange close prices) |
| RSS Feeds | 60+ curated India/global market headlines |
| EODHD | Fundamentals & news (plan-dependent) |
| Finnhub | Fundamentals & news (key-dependent) |

---

## Documentation

| File | Purpose |
|------|---------|
| [CHANGELOG.md](docs/CHANGELOG.md) | Version history |
| [CODE_MANIFEST.md](docs/CODE_MANIFEST.md) | File-by-file inventory |
| [DECISIONS.md](docs/DECISIONS.md) | Architecture Decision Records |
| [HANDOVER.md](docs/HANDOVER.md) | New developer onboarding |
| [SCORING_LOGIC.md](docs/SCORING_LOGIC.md) | Regime scoring & governance |
| [USER_GUIDE.md](docs/USER_GUIDE.md) | End-user guide |
| [WORKFLOW.md](docs/WORKFLOW.md) | Development workflow |

---

## Disclaimer

This dashboard is for educational and research purposes only. Not investment advice.
