# 🛰️ NIFTY Strategy Engine (NDE): Institutional Usage Guide

The **NIFTY Strategy Engine (NDE)** is a multi-expiry, surface-aware decision core designed for institutional-grade options trading. It transitions from simple Greeks to **Market Microstructure Intelligence**, identifying where dealer hedging will accelerate trends or enforce mean reversion.

---

## 🏛️ 1. Architecture Overview
The engine is split into two primary modules:
1. **Tactical Strategy Engine (`17_NIFTY_Strategy_Engine`)**: Focused on today's execution. Selects the optimal strategy (Mean Rev vs. Trend) based on near-term Gamma Flips and Vanna flows.
2. **Monthly Surface Engine (`18_NSE_Monthly_Engine`)**: Focused on the medium-term horizon. Analyzes "Term Structure" (Weekly vs. Monthly) to detect fragility or anchoring in the broader market.

---

## 🌐 2. Data Ingestion (Institutional Pipeline)
The NDE prioritizes **Sensibull-derived institutional Greeks** for maximum analytical trust.

1. **📥 Sensibull Flow**: Export the option chain from Sensibull as a CSV and place it in the `data/option_chain` directory. The engine will automatically detect and convert these into institutional GEX sidecars.
2. **📂 Manual Hub**: Use the "Data Operations Hub" in the Strategy Engine sidebar to trigger a manual scan of the local folder or to purge expired data.
3. **🛡️ Central Governance**: Data ingestion is strictly gated by the **`NDEGovernance`** authority, enforcing high-trust resolution across UI and headless automation.

---

## 🏛️ 3. Decision-First UI (Cockpit)
The NDE UI is designed for **execution-speed decision making**:
- **Systematic Trade Action**: The primary hero headline is the explicit directive (e.g., FADE WALLS, FOLLOW MOMENTUM).
- **Actionable Level Map**: A unified horizontal axis showing Spot, Flip, Pain, and Walls in a single coordinate system.
- **"What Changed" Benchmarking**: Formally compares current state to the **Previous Day's Close** (Last dated snapshot) to identify Daily Drift.

### ✦ Gamma Flip (The Critical Pivot)
The price level where the dealer regime switches from **Long Gamma** (Supportive/Mean Reverting) to **Short Gamma** (Accelerative/Volatile).
- **Above Flip**: Market is "Sticky." Expect dips to be bought.
- **Below Flip**: Market is "Slippery." Expect moves to accelerate.

### 🌊 Vanna & Charm (Flow Vectors)
- **Vanna**: Sensitivity to Volatility. Positive Vanna favors a "buy the dip" regime as IV drops.
- **Charm**: Sensitivity to Time (Theta Decay). Bullish Charm exerts upward pressure on the market as the weekend or expiry approaches.

### ⚖️ TV Ratio (Regime Stability)
The ratio of **Theta to Vega**. 
- **High TV**: Premium decay is high relative to vol risk (Great for Mean Reversion/Selling).
- **Low TV**: Vol risk outweighs decay (Caution required).

---

## 🎯 4. Strategy Selection & Governance
The NDE uses an **Institutional Transition Gate** (Hysteresis) to prevent intraday strategy flip-flopping while allowing valid pivots.

### ⚖️ The Transition Gate (Governance)
A strategy shift is only permitted if one of the following "Hard-Breach" rules is met:
1. **Conviction Jump**: `New Quality Score - Current Quality Score >= 1.5` (on a 10-point scale).
2. **Priority Trigger**: `New Strategy == "GAMMA_FLIP"`.
3. **Regime Cross**: `Sign(New GEX Norm) != Sign(Current GEX Norm)` (e.g., flipping from positive to negative Gamma).

> [!NOTE]
> **Audit Trail**: Every rejected candidate is logged to `notes/nde_strategy_log.jsonl` with the rejection reason (e.g., "Delta 0.8 < 1.5"). This ensures full institutional traceability.

---

## 🕵️ 5. Data Trust & Provenance
Analytical integrity is anchored by our **Multi-Stage Metadata Resolution**:

1. **PROVENANCE (HIGH)**: `spot_at_fetch` from the original sidecar JSON. This is the institutional anchor for historical audit.
2. **STALE TRUSTED**: Metadata-anchored spot within a 24h window; preferred over live low-trust fallbacks when data drift is high.
3. **LIVE (TRUSTED)**: Real-time spot from exchange data (strictly gated by High-Trust metadata source verification).
4. **DEGRADED (WARNING)**: `df["strike"].mean()` fallback. Used ONLY when no other anchor is available; accompanied by a **red banner** alert.

---

## 🏛️ 6. Using the Monthly Engine
Navigating to `NSE Monthly Engine` gives you a 3D view of market risk:

### 🧭 Surface State Summary
- **Stable**: Dealers are positioned to absorb volatility.
- **Fragile**: High negative GEX concentration; a small move can trigger a cascade.
- **Anchor**: Monthly positioning is so large it acts as a magnet (Pinning).

### 🔥 GEX Density Heatmap
Visualizes the "Walls" across all expiries:
- **▲ Call Wall**: The ceiling where dealers will sell to keep price down.
- **▼ Put Wall**: The floor where dealers will buy to support price.
- **✧ Diamond**: The Gamma Flip level for that specific expiry.

---

## 🛠️ 7. Maintenance & Operations
- **🗑️ Cleanup**: Expired chains are automatically purged during **Headless Automation** runs. For manual operators, a "Cleanup Expired" button is available in the sidebar to prevent disk-thrashing.
- **🧹 Cache**: Use "Clear Cache" only if data feels stuck; otherwise, the engine uses efficient session-scoped vector caching.

---
**Institutional Grade | Lot-Invariant | Surface Aware**
*Designed for disciplined execution on the Nifty 50 Index.*
