# System Handover Document

> For new developers joining the Dashboard project.
> Last updated: 2026-03-05

---

## What This System Does

This is a **multi-page Streamlit dashboard** for Indian equity swing trading. It combines global market data, US macro/liquidity indicators, and NSE stock screening into a single decision-support tool for a disciplined swing trading workflow.

The dashboard integrates data from **Yahoo Finance** (stock/index/FX/commodity prices), **FRED** (US macro/liquidity series), **NSE BhavCopy** (official exchange settlement prices), and **60+ RSS feeds** (Indian/global market news). It computes a **regime classification** (Risk On / Selective / Defensive / Crisis) from a weighted multi-factor model, then screens the **NIFTY 200 universe** through setup families (Momentum, Pullback, Volatility Contraction) with quality gates.

Beyond screening, the system includes a **trading journal** with R-multiple tracking, a **prediction integrity framework** with immutable append-only forecasts and monthly calibration governance, **portfolio risk** monitoring, and an **EOD pipeline** for automated data collection and alerting.

---

## How to Set Up Locally

### Prerequisites
- Python 3.12+
- pip

### Steps

1. **Clone the repository**
   ```bash
   git clone <repo-url>
   cd Dashboard
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate   # macOS/Linux
   venv\Scripts\activate       # Windows
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   > ⚠️ Note: `requirements.txt` is currently incomplete. You may need to install packages manually as import errors arise. Key packages: `streamlit`, `pandas`, `numpy`, `plotly`, `yfinance`, `requests`, `feedparser`, `python-dotenv`, `pyarrow`.

4. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and add your API keys:

   | Key | Required | Source | Purpose |
   |-----|----------|--------|---------|
   | `FRED_API_KEY` | **Yes** (for liquidity/macro) | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) | US liquidity and macro data |
   | `FINNHUB_API_KEY` | Optional | [finnhub.io](https://finnhub.io) | Stock fundamentals / news |
   | `EODHD_API_KEY` | Optional | [eodhd.com](https://eodhd.com) | India fundamentals / news |

---

## How to Run

### Dashboard
```bash
streamlit run app.py
```
Opens in browser at `http://localhost:8501`. Navigate pages via the sidebar.

### EOD Pipeline (daily operations)
```bash
python scripts/eod_pipeline.py
```
Or use the **Ops Automation** page (page 8) to run interactively.

### Key operational scripts
```bash
python scripts/data_trust_score.py       # Data quality check
python scripts/scoring_audit_report.py   # Scoring consistency audit
python scripts/alert_engine.py           # Run alert checks
python scripts/prediction_integrity_cycle.py  # Daily prediction cycle
```

---

## Page-by-Page Guide

| # | Page | Purpose |
|---|------|---------|
| — | **Launcher** (`app.py`) | Entry point showing recommended workflow, data health, headlines |
| 0 | **NSE Dashboard** | Swing trading dashboard — morning review, EOD analysis, swing rankings with scoring gates |
| 1 | **Global Markets** | Snapshot of global indices, currencies, commodities, crypto, and bonds |
| 2 | **Money Supply** | FRED liquidity dashboard — Fed balance sheet, reverse repo, TGA, SOFR, money supply |
| 3 | **Macro Risk** | Multi-factor regime scoring engine producing Risk On/Selective/Defensive/Crisis classification |
| 4 | **Leading Indicators** | Early signals — copper/gold ratio, credit spread, dollar/yield trends, market impulse |
| 5 | **Trading Journal** | Log trades, manage entry/exit legs, track R-multiples and performance stats |
| 6 | **Regime Settings** | Configure regime model weights, thresholds, and factor enablement |
| 7 | **Portfolio Risk** | Portfolio concentration, sector exposure, correlation, and pre-trade checks |
| 8 | **Ops Automation** | Run EOD pipeline, alerts, and repair scripts from the UI |
| 9 | **Prediction Integrity** | Immutable prediction log, matured outcome scoring, monthly calibration governance |
| 10 | **Scoring Audit** | Deterministic audit of scoring logic, weight consistency, and cross-page parity |
| 11 | **Tradable Universe** | Full-refresh pipeline runner and tradable signals snapshot viewer |
| 12 | **Todo Tracker** | Roadmap/TODO task management for project development |
| 13 | **India Macro Context** | India-relevant FRED macro series (USD/INR, CPI, crude, credit spreads) |
| 14 | **News Feed** | RSS news aggregator with sector filters, keyword search, and feed health monitoring |
| 15 | **Stock Fundamentals** | EOD stock profile with price history, fundamentals, and news (provider-dependent) |
| 16 | **NIFTY Strategy Engine** | Tactical strategy decision engine (Mean Rev vs Trend) with institutional governance gates |
| 17 | **NSE Monthly Engine** | Monthly/Weekly term structure and GEX surface analysis |

---

## 🛰️ Nifty Strategy Engine (NDE) Architecture
The NDE is a specialized sub-system for options microstructure analysis.

### Core Logic Units
- **`nde_options_logic.py`**: Institutional exposure formulas (GEX/Vanna/Charm), TV-ratio calculations, and **Data Staleness Validation** (5-min market hour gating).
- **`nde_strategy_logic.py`**: Master strategy selection, **Risk Pre-Filter Governance** (halting execution when within 1.5 ATR of Gamma Flip), and explicit **Strict API Trade Schema Generation**.
- **`nde_automation_logic.py`**: Headless snapshot generator and metadata resolution.

### Governance & Data Trust
- **Data Quality Validator**: Dynamically intercepts stale files (`>5 mins` lag) and forcefully degrades the UI to prevent blind execution.
- **Audit Log**: All strategy transitions and rejections are logged to `notes/nde_strategy_log.jsonl`. Safely handles corrupted JSON lines via `JSONDecodeError` catches.
- **Hysteresis**: Intraday transitions are gated by a **1.5-point Quality Score delta** or **Regime Sign Cross**.
- **API Contracts**: The engine now outputs strict `api_schema` JSON dictionaries mapped to the `STRATEGY_REGISTRY`, acting as the foundation for the decoupled `TradingDashPro` backend.

### 🛣️ Next-Gen Architecture Migration
A comprehensive **JIRA-style blueprint** has been established to migrate this Streamlit monolithic logic into a decoupled React/FastAPI stack (`TradingDashPro`).
**Read [AGENT_EXECUTION_ROADMAP.md](./AGENT_EXECUTION_ROADMAP.md) before building new features.** It enforces explicit Interface Contracts, Data Adapters, and Circuit Breaker logic that must be adhered to.

### 🧪 Testing and Verification
The dashboard uses `pytest` for logic verification:
- **`tests/test_nde_logic.py`**: Verifies strategy transition gates, metadata resolution, and TV-ratio stability.
- **`scripts/verify_analytical_integrity.py`**: Legacy CLI-based analytical check.

---

## Known Issues and Limitations

### Critical
1. **`requirements.txt` is incomplete** — only lists `python-dotenv`; all other dependencies are missing.
2. **Duplicate helper functions** — `_responsive_cols()`, `_compact_table()`, `page_diag_block()` are copy-pasted across 12+ page files.
3. **`0_NSE_Dashboard.py` is 2288 lines** — mixes data fetching, scoring, and UI in one enormous file.
4. **Macro Risk and Swing regime paths are not unified** — changing macro thresholds doesn't affect swing gates.

### Moderate
5. **No formal test framework** — 3 test scripts in `scripts/` are standalone, not pytest-integrated.
6. **`data_fetch.py` is 2034 lines** — monolithic file mixing all data sources.
7. **`config.py` uses `print()` on import** — noise in logs on every Streamlit rerun.
8. **Relative file paths hardcoded** — assumes cwd is the project root.
9. **NIFTY_200 tuple has duplicates** in `NSE_Config.py`.
10. **RSS feed groupings duplicated** between `config.py` and `14_News_Feed.py`.
11. **`watchlist_manager.py` calls `logging.basicConfig()`** at module level, overriding app logging.

---

## ⚠️ What NOT to Touch Without Reading SCORING_LOGIC.md First

The following components contain carefully tuned scoring logic with documented governance:

- **`pages/3_Macro_Risk.py`** — Regime scoring engine (weights, thresholds, blend formula)
- **`pages/0_NSE_Dashboard.py`** — Swing rankings, setup families, gate definitions
- **`regime_model.py`** — Default settings (all values have documented rationale in §5 of SCORING_LOGIC.md)
- **`prediction_integrity/engine.py`** — Prediction issuance probability computation
- **`notes/regime_settings.json`** — Live configuration (changes require calibration proposal)

> Any parameter change should be **proposal-driven** via the prediction calibration workflow and documented with pre/post evidence. See `docs/SCORING_LOGIC.md` §8 for operator notes.

---

## Key Contacts, Data Sources & API Dependencies

### Data Sources

| Source | Used For | Reliability | Fallback |
|--------|----------|-------------|----------|
| Yahoo Finance (`yfinance`) | Stock/index/FX/commodity prices | Generally reliable; 15-20 min delay | BhavCopy for NSE equities |
| FRED API | US macro/liquidity series | Highly reliable | None (features disabled without key) |
| NSE India | India VIX, FII/DII flows, BhavCopy | Unreliable (anti-scraping); needs session warm-up | Cached/local data |
| RSS Feeds (60+) | Market news, sector news | Variable by feed | Feed health monitoring in News Feed page |
| EODHD | India fundamentals/news | Plan-dependent | Finnhub |
| Finnhub | Fundamentals/news | Plan-dependent | EODHD |

### Project Owner
- Laxman Acharya (Trading System Owner)

### Key Files
- `docs/SCORING_LOGIC.md` — Scoring governance (read this first!)
- `notes/regime_settings.json` — Live regime model configuration
- `data/prediction_integrity/` — Immutable prediction/outcome data
- `.env` — API credentials (never commit)
