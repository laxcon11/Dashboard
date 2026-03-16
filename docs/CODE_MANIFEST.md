# Code Manifest

> Living reference for every source file in the Dashboard project.
> Last updated: 2026-03-05

---

## Root Modules

| File | Lines | Role | Key Exports / Functions | Dependencies | Notes |
|------|------:|------|-------------------------|--------------|-------|
| `app.py` | 189 | Streamlit entry point / launcher | `setup_page`, flow display, headlines | `utils`, `data_fetch`, `factor_registry`, `config` | Entry point — run via `streamlit run app.py` |
| `config.py` | 548 | Global settings, API keys, symbols, thresholds | `FRED_API_KEY`, `FINNHUB_API_KEY`, `EODHD_API_KEY`, `RSS_FEEDS`, `RSS_FEED_TAGS`, `MACRO_SYMBOLS`, `MAIN_INDICES`, all `*_THRESHOLD` dicts | `os`, `dotenv` | ⚠️ Uses `print()` instead of logging — cleanup pending |
| `NSE_Config.py` | 328 | NIFTY 200 universe by sector, preset watchlists | `NIFTY_200`, `SECTOR_CATEGORIES`, `THEMATIC_CATEGORIES`, `PRESET_WATCHLISTS`, `STOCK_CATEGORIES` | — | ⚠️ NIFTY_200 has duplicate entries — cleanup pending |
| `data_fetch.py` | 2033 | Central data pipeline (Yahoo, FRED, BhavCopy, RSS, EODHD, Finnhub) | `batch_download`, `extract_price_data`, `fetch_fred_series`, `fetch_fred_batch`, `fetch_rss_feeds`, `fetch_rss_feeds_by_keys`, `fetch_rss_feed_health`, `fetch_equity_fundamentals`, `fetch_india_vix`, `load_latest_bhavcopy_prices`, `get_last_batch_telemetry`, `quick_data_health_summary`, `probe_market_data_providers`, `is_eodhd_eod_only` | `config`, `trading_calendar`, `yfinance`, `requests`, `feedparser` | Largest file in project |
| `utils.py` | 833 | Shared UI components, charts, price formatting | `setup_page`, `get_ui_detail_mode`, `get_ui_device_mode`, `is_mobile_mode`, `display_price_metric`, `format_price`, `format_change`, `create_line_chart`, `create_multi_line_chart`, `get_live_price_safe`, `classify_signal`, `create_price_table`, `render_source_freshness`, `render_decision_header`, `render_key_observations`, `render_regime_timeline_strip`, `safe_operation`, `calculate_trend`, `get_momentum` | `config`, `regime_state`, `plotly`, `streamlit` | Canonical home for shared page helpers |
| `analytics.py` | 514 | Scoring calculations, signals, context capture | `calculate_momentum_score`, `calculate_pullback_score`, `calculate_liquidity_score`, `get_liquidity_stance`, `calculate_copper_gold_signal`, `calculate_credit_spread_signal`, `calculate_dollar_trend_signal`, `calculate_yield_trend_signal`, `detect_gap`, `calculate_volume_ratio`, `calculate_vwap`, `detect_breakout`, `detect_nr7`, `calculate_relative_strength`, `get_current_context` | `indicators`, `config` | |
| `indicators.py` | 243 | Technical indicator calculations | `calculate_rsi`, `calculate_ema`, `calculate_atr`, `calculate_change`, `calculate_sma`, `calculate_bollinger_bands`, `calculate_macd`, `calculate_stochastic` | `pandas`, `numpy` | Pure computation — no Streamlit dependency |
| `regime_model.py` | 89 | Regime scoring settings persistence | `load_regime_settings`, `save_regime_settings`, `reset_regime_settings`, `DEFAULT_REGIME_SETTINGS` | `json`, `pathlib` | Reads/writes `notes/regime_settings.json` |
| `regime_state.py` | 51 | Current regime snapshot load/save | `save_regime_snapshot`, `load_regime_snapshot` | `json`, `pathlib` | Reads `notes/current_regime_snapshot.json` + `data/snapshots/eod_*.json` |
| `factor_registry.py` | 90 | SSOT for cross-page factor metadata | `FACTOR_REGISTRY`, `get_factor_meta` | — | Maps factor keys to symbols, sources, update modes |
| `gift_nifty.py` | 339 | GIFT Nifty multi-source overlay (display only) | `get_gift_nifty_snapshot`, `is_gift_session_active` | `config`, `requests` | Scrape-based fallbacks (Groww, Moneycontrol) |
| `india_context.py` | 510 | FII/DII flows, GST Trends, Yield Curve signals | `get_india_macro_signals_v1` | `data_fetch`, `pandas` | Processed GST and India Yield signals |
| `trading_calendar.py` | 61 | NSE holiday-aware business day calculations | `is_nse_trading_day`, `latest_nse_business_day`, `nse_business_days_between`, `nse_business_day_age` | `pandas` | References `notes/nse_holidays.json` (file may not exist) |
| `watchlist_manager.py` | 65 | JSON-backed watchlist CRUD | `load_watchlists`, `save_watchlists`, `add_watchlist`, `delete_watchlist`, `get_watchlist_names`, `get_symbols` | `NSE_Config` | ⚠️ Has `logging.basicConfig()` at module level — cleanup pending |

---

## Pages

| File | Lines | Role | Key Imports | Notes |
|------|------:|------|-------------|-------|
| `pages/0_NSE_Dashboard.py` | 2287 | Swing trading dashboard (morning review, EOD, rankings) | `data_fetch`, `analytics`, `indicators`, `utils`, `gift_nifty`, `NSE_Config`, `config` | Largest page — DUPLICATE HELPERS: `_responsive_cols`, `_compact_table` |
| `pages/1_Global_Markets.py` | 209 | Global indices, FX, commodities, crypto, bonds snapshot | `data_fetch`, `utils`, `config` | DUPLICATE HELPERS: `_compact_table` |
| `pages/2_Money_Supply.py` | 375 | FRED liquidity dashboard (Fed BS, RRP, TGA, SOFR) | `data_fetch`, `analytics`, `utils`, `config` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/3_Macro_Risk.py` | 1256 | Regime scoring engine (macro + liquidity blend) | `data_fetch`, `regime_model`, `regime_state`, `utils`, `config` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/4_Leading_Indicators.py` | 722 | Leading signals (copper/gold, credit, dollar, yields) | `data_fetch`, `analytics`, `utils`, `config` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/5_Trading_Journal.py` | 1254 | Trade logging, legs, performance stats | `utils`, `config`, `NSE_Config`, `gift_nifty`, `data_fetch`, `analytics` | DUPLICATE HELPERS: `_responsive_cols`, `_compact_table`, `page_diag_block` |
| `pages/6_Regime_Settings.py` | 197 | UI for regime model weight/threshold tuning | `regime_model`, `regime_state`, `utils` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/7_Portfolio_Risk.py` | 521 | Portfolio concentration, correlation, pre-trade checks | `utils`, `data_fetch`, `NSE_Config` | DUPLICATE HELPERS: `_responsive_cols`, `_compact_table`, `page_diag_block` |
| `pages/8_Ops_Automation.py` | 282 | EOD pipeline, alerts, script runner UI | `utils`, `regime_state` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/9_Prediction_Integrity.py` | 256 | Prediction log, outcomes, calibration governance | `prediction_integrity`, `utils` | DUPLICATE HELPERS: `_responsive_cols`, `_compact_table` |
| `pages/10_Scoring_Audit.py` | 124 | Scoring logic consistency audit | `utils` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/11_Tradable_Universe.py` | 288 | EOD pipeline runner, tradable signals snapshot | `utils`, `NSE_Config`, `trading_calendar` | DUPLICATE HELPERS: `_responsive_cols`, `_compact_table` |
| `pages/12_Todo_Tracker.py` | 224 | Roadmap/TODO task management | `utils` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/13_India_Macro_Context.py` | 175 | India-relevant FRED macro series | `data_fetch`, `utils`, `config` | DUPLICATE HELPERS: `_responsive_cols` |
| `pages/14_News_Feed.py` | 173 | RSS news feed with filters | `data_fetch`, `utils`, `config` | ⚠️ Duplicates `FEED_GROUPS` dict already derivable from `config.RSS_FEED_TAGS` |
| `pages/15_Stock_Fundamentals.py` | 359 | EOD stock profile, fundamentals, news | `data_fetch`, `utils`, `config`, `NSE_Config`, `watchlist_manager` | DUPLICATE HELPERS: `_responsive_cols` |

---

## Prediction Integrity Package

| File | Lines | Role | Key Exports | Notes |
|------|------:|------|-------------|-------|
| `prediction_integrity/__init__.py` | 13 | Package init, re-exports | `run_daily_cycle`, `generate_monthly_calibration`, `apply_approved_proposal` | |
| `prediction_integrity/engine.py` | 553 | Prediction issuance, evaluation, calibration | `issue_predictions`, `evaluate_matured`, `run_daily_cycle`, `generate_monthly_calibration`, `apply_approved_proposal`, `ensure_model_version` | Core governance engine |
| `prediction_integrity/store.py` | 111 | Parquet persistence layer | `load_predictions`, `load_outcomes`, `save_predictions`, `save_outcomes`, `append_immutable`, `latest_calibration_proposal` | Append-only by design |
| `prediction_integrity/schema.py` | 87 | Data classes, validation, canonical labels | `PredictionRecord`, `OutcomeRecord`, `REGIMES`, `validate_probs`, `canonical_regime`, `top_regime` | |

---

## Scripts

| File | Lines | Role | Referenced From | Notes |
|------|------:|------|-----------------|-------|
| `scripts/eod_pipeline.py` | 136 | End-of-day data pipeline orchestrator | `8_Ops_Automation.py`, `11_Tradable_Universe.py` | KEEP — core operational script |
| `scripts/alert_engine.py` | 132 | Multi-rule alert engine | `8_Ops_Automation.py` | KEEP |
| `scripts/data_trust_score.py` | 256 | Data quality trust scoring | `8_Ops_Automation.py`, `11_Tradable_Universe.py` | KEEP |
| `scripts/scoring_audit_report.py` | 320 | Scoring logic consistency audit | `10_Scoring_Audit.py` | KEEP |
| `scripts/bhavcopy_parity_report.py` | 118 | BhavCopy vs Yahoo price parity check | `8_Ops_Automation.py` | KEEP |
| `scripts/build_nse230_history.py` | 184 | Build local NIFTY 230 parquet history | — (manual/CLI) | KEEP |
| `scripts/repair_stale_from_bhavcopy.py` | 147 | Repair stale Yahoo data from BhavCopy | `8_Ops_Automation.py` | KEEP |
| `scripts/phase0_health_check.py` | 96 | Pre-flight health check | `8_Ops_Automation.py` | KEEP |
| `scripts/poll_gift_nifty.py` | 101 | Poll GIFT Nifty and save snapshot | Scheduled/CLI | KEEP |
| `scripts/update_gift_snapshot.py` | 61 | Update GIFT Nifty local snapshot | CLI | KEEP |
| `scripts/update_fno_lot_sizes_from_fo_bhavcopy.py` | 119 | Update F&O lot sizes | CLI | KEEP |
| `scripts/recovery_tools.py` | 76 | Data recovery utilities | `8_Ops_Automation.py` | KEEP |
| `scripts/prediction_integrity_cycle.py` | 21 | Daily prediction cycle runner | `8_Ops_Automation.py` | KEEP |
| `scripts/prediction_calibration_monthly.py` | 26 | Monthly calibration runner | `9_Prediction_Integrity.py` | KEEP |
| `scripts/prediction_apply_proposal.py` | 27 | Apply approved calibration proposal | `9_Prediction_Integrity.py` | KEEP |
| `scripts/regime_sanity_tests.py` | 40 | Regime model sanity tests | — (manual) | KEEP — basic test script |
| `scripts/diagnose.py` | 122 | Diagnostics / debug utility | — (manual) | KEEP |
| `scripts/test_indicators.py` | 134 | Indicator calculation tests | — (manual) | KEEP — test script |
| `scripts/test_prediction_integrity_engine.py` | 44 | Prediction engine tests | — (manual) | KEEP — test script |
| `scripts/test_regime_model.py` | 60 | Regime model tests | — (manual) | KEEP — test script |
| `scripts/check_vwap.py` | 18 | One-off VWAP debugging script | — (unreferenced) | NEEDS REVIEW — tiny debug script |
| `scripts/check_yf_columns.py` | 29 | One-off Yahoo Finance column check | — (unreferenced) | NEEDS REVIEW — tiny debug script |

---

## Config & Data Files

| File | Role | Notes |
|------|------|-------|
| `.env` | API keys (FRED, FINNHUB, EODHD, GIFT NIFTY flags) | Gitignored |
| `.env.example` | Template for `.env` | |
| `.streamlit/config.toml` | Streamlit settings (`showSidebarNavigation = false`) | |
| `.gitignore` | Git exclusions | |
| `qodana.yaml` | Qodana CI config | ⚠️ Placeholder linter — non-functional |
| `requirements.txt` | Python dependencies | ⚠️ Only lists `python-dotenv` — incomplete |
| `setup.sh` / `setup.bat` | Setup scripts | Reference incomplete `requirements.txt` |
| `watchlists.json` | User watchlist data | |
| `data/nifty200.csv`, `data/nifty200_refined.csv` | NIFTY 200 reference lists | |
| `data/nse_230_history.parquet` | Local NSE OHLCV history | |
| `data/bhavcopy/` | Downloaded NSE BhavCopy zips | |
| `data/snapshots/` | EOD regime snapshots, tradable signals | |
| `data/prediction_integrity/` | Prediction/outcome parquets, calibration | |
| `notes/` | JSON state files (regime, journal, flows, settings) | |
| `logs/` | Log files (data trust, parity, alerts, scoring audit) | |

---

## Documentation

| File | Role |
|------|------|
| `README.md` | Project overview, features, setup |
| `docs/SCORING_LOGIC.md` | Scoring governance reference (v1.2) |
| `docs/USER_GUIDE.md` | End-user guide |
| `docs/WORKFLOW.md` | Operational workflow |
| `docs/DEPLOYMENT.md` | Deployment guide |
| `docs/CHANGELOG.md` | Historical changelog |
| `docs/QUICK_REFERENCE.md` | Quick reference card |
| `docs/IMPLEMENTATION_SUMMARY.md` | Implementation summary |
| `docs/INTEGRATED_SETUP.md` | Integrated setup guide |
| `docs/INTEGRATION_COMPLETE.md` | Integration completion record |
| `docs/TEAM_HANDOFF_STREAMLIT_MODEL.md` | Team handoff for Streamlit model |
| `CODE_MANIFEST.md` | This file |
| `DECISIONS.md` | Architecture Decision Records |
| `CHANGELOG.md` | Keep-a-Changelog format |
| `HANDOVER.md` | System handover document |
