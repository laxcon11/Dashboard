# Scoring Logic Reference (Current Production Design)

Document Version: v1.2
Last Updated: 2026-02-21
Owner: Laxman Acharya (Trading System Owner)
Review Cadence: Monthly with calibration cycle (or immediately after scoring logic changes)

## Change Log
- v1.2 (2026-02-21)
- Added metadata header (version/owner/cadence).
- Expanded Prediction Integrity to schema-level detail and invariants.
- Added engine dependency join map (Macro -> Swing -> Prediction paths).
- Expanded judgment register with current values, rationale, sensitivity, and triggers.
- Added explicit operational pass/fail policy by script.
- Added owners and target dates for known limitations.
- v1.1 (2026-02-21)
- Initial scoring documentation baseline.

## Purpose
This document is the single source of truth for:
- how regime, directional, impulse, and setup scores are computed,
- where subjective judgment exists,
- why those choices are currently the best practical approach,
- and what evidence should trigger recalibration.

## Scope
Covered modules/pages:
- `pages/3_Macro_Risk.py`
- `pages/4_Leading_Indicators.py`
- `pages/0_NSE_Dashboard.py` (Swing Rankings / gates)
- `prediction_integrity/*` and calibration scripts
- validation checks in `scripts/scoring_audit_report.py` and `scripts/data_trust_score.py`

---

## 0) Engine Join Map (Critical Dependency Section)

## 0.1 Current join behavior (as implemented)
- Macro Risk engine (`pages/3_Macro_Risk.py`) computes regime from multi-factor macro/liquidity model.
- Swing engine (`pages/0_NSE_Dashboard.py`, Swing Rankings mode) currently computes its own regime from:
  - `trend_signal(^NSEI) + trend_signal(^NSEBANK)` and
  - breadth threshold by strictness profile.
- Prediction Integrity issuance currently derives from EOD snapshot (`scripts/eod_pipeline.py`) regime, not Macro Risk probability distribution.

## 0.2 Dependency implication
Changing Macro Risk thresholds (`neutral_band`, regime probability thresholds) does **not** automatically change Swing gate outcomes today. Swing gates are tied to its own regime path unless explicitly unified in future.

## 0.3 Gate input definitions (explicit)
- Swing `Regime Gate`: `regime_label != "🔴 Risk Off"` from Swing-local regime classification.
- Swing `Liquidity Gate`: pass when local liquidity score is `>= 0`.
- Swing `Hard Gate`: `Regime Gate AND Liquidity Gate AND Quality Gate`.

---

## 1) Macro Risk Engine

## 1.1 Factor signal construction
Each factor builds two components from timeseries:
- `Fast` (impulse): short-horizon move normalized by recent volatility
- `Slow` (directional): deviation vs slow moving average normalized by history

Both are clipped to `[-2, +2]`.
If factor is marked `inverse=True`, signs are flipped.

## 1.2 Weight pipeline
For every enabled factor:
1. `Base W` = configured weight from settings
2. `Capped W` = `min(Base W, max_factor_weight)`
3. Group cap applied proportionally inside each group -> `Adj W`
4. Domain normalization -> `Eff W = Adj W / sum(Adj W in domain)`

Notes:
- `max_factor_weight` is a **per-factor** cap.
- `group_caps` are **upper bounds**, not target allocations.
- `Eff W` is the effective contribution weight and sums ~1 in each domain.

## 1.3 Domain rollups
Per domain (`Macro`, `Liquidity`):
- `impulse_raw = sum(Fast * Eff W)`
- `directional_raw = sum(Slow * Eff W)`
- `blend_raw = sum(Combined * Eff W)`

Normalized:
- `impulse_norm = clip(impulse_raw / 2, -1, +1)`
- `directional_norm = clip(directional_raw / 2, -1, +1)`

## 1.4 Final regime math
If both domains valid:
- `final_impulse = macro_impulse_norm*macro_weight + liquidity_impulse_norm*liquidity_weight`
- `final_directional = macro_directional_norm*macro_weight + liquidity_directional_norm*liquidity_weight`
- `final_score = final_directional*(1-impulse_influence) + final_impulse*impulse_influence`

Regime probabilities are softmax-style transforms of `final_score` and `neutral_band`, then normalized to sum to 1.

Confidence combines:
- max regime probability,
- macro/liquidity agreement,
- data quality (valid factors ratio),
- directional strength magnitude.

## 1.5 Why this design (best course for now)
- Volatility normalization avoids overreacting to raw scale differences.
- Per-factor and per-group caps prevent concentration/bias from one theme.
- Dual horizon (fast/slow) captures both shock and trend context.
- Confidence is evidence-weighted, not just score thresholded.

---

## 2) Leading Indicators Engine

## 2.1 Daily vs Directional definition
- `Daily`: near-term pulse (latest move with noise deadband)
- `Directional`: slower backdrop/trend proxy

Current implementation:
- Daily score uses sign of latest pct move with deadband for noise.
- Directional uses factor-specific trend regime signals (MA-based or structural ratio logic).
- Liquidity directional uses multi-print lookback (`lookback_days=4`) and is not tied to daily.

## 2.2 Aggregation
- `daily_normalized = average(daily factor scores)`
- `directional_normalized = average(directional factor scores)`
- Requires minimum factor count to avoid thin-signal distortion.

## 2.3 Why this design
- Keeps page interpretable and fast for pre-open use.
- Preserves separation between short-term movement and medium trend posture.
- Accepts lower complexity than Macro Risk in exchange for speed and readability.

---

## 3) Swing Rankings Engine

## 3.1 Setup families
- Momentum
- Pullback
- Volatility Contraction

Each family uses strict feature checks (trend structure, breakout/NR7, RSI zones, distance from EMA, etc.) and yields a bounded 0-10 score.

## 3.2 Gates
- Regime gate
- Liquidity gate
- Stock quality gate

Hard gate pass requires all three.

## 3.3 Tiers
- A+, A, B, C by score thresholds (strictness profile dependent)

Execution mode:
- Tradable list shows only A+/A with hard gate pass.
- Discovery mode shows blocked/watch context too.

## 3.4 Why this design
- Supports objective filtering first, discretionary override second.
- Reduces overtrading by requiring context + quality alignment.

---

## 4) Prediction Integrity & Calibration (Specification Level)

## 4.1 Prediction record schema (immutable)
Storage: `data/prediction_integrity/predictions.parquet`

Required fields:
- `prediction_id` (unique immutable key)
- `date_issued` (issue date)
- `target_date` (maturity date)
- `horizon_days` (`1`, `5`, `20`)
- `pred_regime_probs` (JSON probabilities summing to 1)
- `pred_score_range_low`
- `pred_score_range_high`
- `pred_score_mid`
- `confidence` (`HIGH`, `MEDIUM`, `LOW`)
- `model_version`
- `input_signature` (deterministic hash of inputs)
- `created_at`

Invariants:
- Append-only (no update/delete path).
- One `prediction_id` written at most once.
- Probabilities normalized to sum exactly 1.

## 4.2 Outcome record schema (matured only)
Storage: `data/prediction_integrity/outcomes.parquet`

Required fields:
- `prediction_id` (foreign key to prediction)
- `evaluated_at`
- `actual_regime`
- `actual_score`
- `brier_score`
- `log_loss`
- `score_mae`
- `in_band`
- `regime_correct`

Invariants:
- Appended only when `target_date <= as_of_date` and actual is available.
- One outcome per `prediction_id`.
- Historical prediction/outcome rows are not repainted.

## 4.3 Model version schema
Storage: `data/prediction_integrity/model_versions.parquet`

Fields:
- `model_version`
- `settings_hash`
- `settings_snapshot`
- `created_at`
- `notes`

Invariant:
- New version added only when settings hash changes.

## 4.4 Calibration governance schema
Monthly artifacts:
- Report: `data/prediction_integrity/calibration/monthly_calibration_YYYY_MM.json`
- Proposal: `data/prediction_integrity/calibration/proposals/proposal_YYYY_MM.json`

Proposal states:
- `PENDING_APPROVAL`
- `APPROVED`
- `REJECTED`
- `MODIFY_REQUESTED`
- `IMPLEMENTED` / `NO_OP` after apply step

Invariant:
- Apply path executes only when state is `APPROVED`.

## 4.5 Why this design
- Enables true forecast accountability.
- Prevents hindsight contamination.
- Creates closed-loop improvement with auditable governance.

---

## 5) Judgment Register (Governance Format)

Reference settings source: `notes/regime_settings.json` (current values as of 2026-02-21).

| Parameter | Current Value | Rationale | Sensitivity | Recalibration Trigger |
|---|---:|---|---|---|
| `blend.macro_weight` | 0.60 | Keeps macro state primary while preserving liquidity influence. | Latest scoring audit: ±10% relative shift changes final directional by max ~0.0187. | If macro/liquidity disagreement persists >20 sessions and hit-rate degrades by >10%. |
| `blend.liquidity_weight` | 0.40 | Ensures liquidity affects stance without dominating broad macro basket. | Complementary to macro weight; same sensitivity envelope as above. | Same as macro weight trigger. |
| `blend.fast_weight` | 0.40 | Prevents short-horizon shock from overpowering trend baseline. | Higher values increase impulse variance and regime flip frequency. | If false-positive flips increase materially (tracked in monthly calibration). |
| `blend.slow_weight` | 0.60 | Anchors directional bias on slower state. | Lowering reduces trend persistence and increases whipsaw risk. | If lag cost rises (late detection of regime shifts) for 2+ monthly cycles. |
| `blend.impulse_influence` | 0.25 | Allows tactical sensitivity while preserving directional anchor. | Formula sensitivity from current state: +/-20% relative changes final score by about 0.006-0.008. | If near-term miss rate in T+1 materially worsens vs T+5/T+20. |
| `blend.neutral_band` | 0.35 | Avoids over-classification into Risk On/Risk Off when signal is weak. | Narrower band increases regime flips; wider band increases Neutral frequency. | If Neutral bucket underperforms directional buckets for 30+ matured predictions. |
| `blend.risk_on_threshold` | 0.60 | Requires stronger posterior to classify pro-risk. | Lowering increases Risk On labels, potentially early entries. | If missed upside cycles dominate and Brier/log-loss improve after simulation. |
| `blend.risk_off_threshold` | 0.60 | Symmetric confidence requirement for risk-off classification. | Lowering increases defensive labels and can reduce participation. | If drawdown protection is weak despite bearish macro/liquidity evidence. |
| `blend.sofr_iorb_*` penalty controls | warn=5bps, full=15bps, max=0.25, persisted=0.35, days=3 | Adds interbank stress override to Liquidity directional/impulse when SOFR exceeds IORB. | Higher max/earlier trigger increases defensive tilt during funding stress. | If penalty causes false risk-off bias without drawdown benefit over 2+ calibration cycles. |
| `blend.max_factor_weight` | 0.20 | Prevents one factor from dominating domain output. | Raising increases concentration risk; lowering can over-dilute high-quality signals. | If single-factor contribution repeatedly exceeds governance tolerance. |
| `blend.fast_window` | 1 | Captures immediate move for impulse channel. | Increasing reduces sensitivity to daily shocks. | If daily impulse noise causes repeated false tactical calls. |
| `blend.slow_window` | 10 | Balances trend responsiveness and stability. | Larger window smoother but slower; smaller window noisier. | If directional lag or whipsaw rises across 2 calibration cycles. |
| Swing `quality_score` gate | >=0.45 | Ensures minimum micro-quality before regime gating. | Raising lowers trade count, improves selectivity. | If overtrading persists without expectancy gain. |
| Swing `min_vol_ratio` (Balanced) | >=0.80 | Requires participation quality. | Lower values admit illiquid/noisy names. | If slippage and failed follow-through increase. |
| Swing `min_rs` (Balanced) | >=-3.0 | Allows early turnarounds but blocks severe laggards. | Higher values force relative leadership bias. | If blocked high-quality reversals exceed acceptable miss threshold. |

Governance note:
- Any parameter change should be proposal-driven via prediction calibration workflow and documented with pre/post evidence.
- SOFR/IORB is an intentional dual-path signal today: it contributes as a continuous liquidity factor and can also trigger explicit stress penalty adjustments.

---

## 6) Known Limits, Owners, and Target Dates

| Limitation | Owner | Target Date | Action |
|---|---|---|---|
| Macro Risk and Swing regime paths are not unified. | Laxman Acharya | 2026-04-15 | Decide canonical regime provider and wire Swing gate to single source. |
| Prediction issuance currently uses EOD snapshot regime path, not full Macro Risk posterior. | Laxman Acharya | 2026-04-30 | Evaluate migration of issuance input to canonical regime API. |
| Some directional proxies remain simple MA/ratio states. | Laxman Acharya | 2026-05-15 | Add richer state tests and compare against baseline via scoring audit. |
| Thresholds are not yet statistically re-estimated with large samples. | Laxman Acharya | 2026-06-01 | Introduce minimum-sample re-estimation routine in calibration workflow. |
| Live-vs-close timing differences may create temporary cross-page divergence. | Laxman Acharya | 2026-03-31 | Publish source/freshness policy per page and enforce badge visibility. |

---

## 7) Operational Validation Policy (Script-Level Pass/Fail)

## 7.1 Daily checks
- `scripts/data_trust_score.py`
- `scripts/scoring_audit_report.py`
- optional: `scripts/bhavcopy_parity_report.py`

## 7.2 Monthly checks
- `scripts/prediction_calibration_monthly.py`
- proposal review/approval/apply flow

## 7.3 Pass/fail rules
- Data Trust (`logs/data_trust_latest.json`):
  - `PASS` if trust >= 95 and no hard-fail reasons.
  - `WARN` if 85 <= trust < 95 and no hard-fail reasons.
  - `FAIL` if trust < 85 or any hard-fail reason present.
- Scoring Audit (`logs/scoring_audit_latest.json`):
  - `PASS` if overall >= 95 and no hard-fail reasons.
  - `WARN` if 85 <= overall < 95 and no hard-fail reasons.
  - `FAIL` otherwise.
- Bhavcopy parity (policy for manual interpretation):
  - Prefer close mismatch rate <= 2% universe-wide.
  - Prefer volume mismatch rate <= 20% threshold count minimal and non-clustered.

## 7.4 Release gate recommendation
Block strategy-setting changes when any of the following is true:
- Scoring Audit = `FAIL`
- Data Trust = `FAIL`
- Prediction sample sufficiency not met for target horizon

---

## 8) Quick Operator Notes
- If you change regime thresholds, review `0) Engine Join Map` first.
- If you change gate thresholds, annotate rationale in calibration proposal comments.
- If you change any judgment parameter without proposal flow, update this document in the same commit.
