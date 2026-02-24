# Streamlit Model Handoff (Parity Guide)

## Purpose
Use this note to brief the team on what the current Streamlit system does and which parameters must be mirrored in the institutional system so outputs stay consistent.

## System Flow (What the model does)
1. Data Layer
- Local-first OHLCV/parquet load for stock universe.
- Intraday API refresh for live scanning where needed.
- Bhavcopy fallback/overwrite path for EOD integrity.

2. Regime Engine (Macro Risk)
- Two domains: `Macro` and `Liquidity`.
- Two horizons: `impulse` (fast) and `directional` (slow).
- Weighted blend produces final regime score and probability split.
- Output labels: `BULLISH`, `NEUTRAL`, `BEARISH` style posture (shown as Risk On / Neutral / Risk Off equivalents in UI).

3. Swing Engine
- Setup families: Momentum, Pullback, Volatility Contraction.
- Hard gates + quality gate + regime filter decide tradable eligibility.
- Ranking produces A+/A/B/C tiers and top pick/watch/monitor tables.

4. Execution / Checklist
- Trade checklist applies risk constraints (capital, stop, concentration, quantity defaults, lot-size logic where available).
- Final state: `ALLOWED` / `BLOCKED` with rule-level breakdown.

5. Journal / Learning
- Trade logging stores entry context (regime, setup, invalidation).
- Post-trade analytics used for calibration and threshold review.

## Single Source of Truth (SSOT)
- Regime defaults + loader: `/Users/laxmanacharya/Desktop/BhavCopy/Dashboard/regime_model.py`
- Active runtime overrides: `/Users/laxmanacharya/Desktop/BhavCopy/Dashboard/notes/regime_settings.json`
- Swing strictness thresholds and gating logic: `/Users/laxmanacharya/Desktop/BhavCopy/Dashboard/pages/0_NSE_Dashboard.py`
- Scoring method spec: `/Users/laxmanacharya/Desktop/BhavCopy/Dashboard/docs/SCORING_LOGIC.md`

## Current Regime Parameters (must match)
From `notes/regime_settings.json`.

### Blend
- `macro_weight`: `0.60`
- `liquidity_weight`: `0.40`
- `fast_weight`: `0.40`
- `slow_weight`: `0.60`
- `impulse_influence`: `0.25`
- `fast_window`: `1`
- `slow_window`: `10`
- `max_factor_weight`: `0.20`
- `neutral_band`: `0.30`
- `risk_on_threshold`: `0.60`
- `risk_off_threshold`: `0.60`
- `sofr_iorb_penalty_enabled`: `true`
- `sofr_iorb_warn_bps`: `5.0`
- `sofr_iorb_full_penalty_bps`: `15.0`
- `sofr_iorb_max_penalty`: `0.25`
- `sofr_iorb_persistence_days`: `3`
- `sofr_iorb_persisted_max_penalty`: `0.35`

### Group Caps
- `Macro`: `0.30`
- `Liquidity`: `0.35`
- `Risk Appetite`: `0.20`
- `Rates/Currency`: `0.20`
- `Commodities`: `0.20`

### Macro Factors
- `nifty50`: weight `0.13`, inverse `false`, group `Macro`
- `nasdaq`: weight `0.11`, inverse `false`, group `Macro`
- `bank_nifty`: weight `0.09`, inverse `false`, group `Macro`
- `dxy`: weight `0.10`, inverse `true`, group `Rates/Currency`
- `usdinr`: weight `0.08`, inverse `true`, group `Rates/Currency`
- `us10y`: weight `0.10`, inverse `true`, group `Rates/Currency`
- `crude`: weight `0.08`, inverse `true`, group `Commodities`
- `gold`: weight `0.06`, inverse `true`, group `Commodities`
- `bitcoin`: weight `0.07`, inverse `false`, group `Risk Appetite`
- `credit_spread (HYG/LQD)`: weight `0.09`, inverse `false`, group `Risk Appetite`
- `copper_gold (HG=F/GC=F)`: weight `0.09`, inverse `false`, group `Commodities`

### Liquidity Factors
- `walcl`: weight `0.26`, inverse `false`, group `Liquidity`
- `rrp`: weight `0.22`, inverse `true`, group `Liquidity`
- `tga`: weight `0.22`, inverse `true`, group `Liquidity`
- `m2`: weight `0.16`, inverse `false`, group `Liquidity`
- `sofr_iorb`: weight `0.14`, inverse `true`, group `Liquidity`

## Current Swing Strictness Profiles (must match)
From `pages/0_NSE_Dashboard.py` (`strictness_cfg`).

### Strict
- `tier_a_plus`: `8.8`
- `tier_a`: `8.0`
- `min_vol_ratio`: `1.0`
- `min_rs`: `-1.0`
- `rs_floor_penalty`: `0.15`
- `risk_on_breadth`: `1.2`
- `risk_off_breadth`: `0.85`
- `risk_off_min_score`: `9.4`
- `top_n`: `2`
- `watchlist_n`: `4`

### Balanced
- `tier_a_plus`: `8.5`
- `tier_a`: `7.5`
- `min_vol_ratio`: `0.8`
- `min_rs`: `-3.0`
- `rs_floor_penalty`: `0.10`
- `risk_on_breadth`: `1.1`
- `risk_off_breadth`: `0.9`
- `risk_off_min_score`: `9.0`
- `top_n`: `3`
- `watchlist_n`: `5`

### Aggressive
- `tier_a_plus`: `8.2`
- `tier_a`: `7.0`
- `min_vol_ratio`: `0.6`
- `min_rs`: `-5.0`
- `rs_floor_penalty`: `0.08`
- `risk_on_breadth`: `1.0`
- `risk_off_breadth`: `0.95`
- `risk_off_min_score`: `8.6`
- `top_n`: `4`
- `watchlist_n`: `8`

## Parity Rules (for both systems)
1. Do not hardcode duplicate thresholds in multiple places. Read from one config source.
2. Keep directionality (`inverse`) identical per factor.
3. Apply the same capping sequence: base weight -> per-factor cap -> group cap scaling -> domain normalization.
4. Use the same classification thresholds for regime labeling.
5. For swing outputs, keep strictness profile values synchronized before comparing candidate lists.
6. Log configuration hash/version in both systems for audit parity.

## Team Handoff Message (Use this verbatim)
"Our Streamlit stack is a dual-horizon regime + gated swing decision system with local-first data reliability. Parity depends on mirroring: (1) regime blend/caps/thresholds, (2) factor weights and inverse flags, and (3) swing strictness profile thresholds. SSOT is `regime_model.py` + `notes/regime_settings.json` + `strictness_cfg` in `pages/0_NSE_Dashboard.py`. Any change must be versioned and applied to both systems in the same release window."
