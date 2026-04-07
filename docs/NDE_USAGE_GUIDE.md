# 🛰️ NIFTY Strategy Engine (NDE): Institutional Usage Guide

The **NIFTY Strategy Engine (NDE)** is a multi-expiry, surface-aware decision core designed for institutional-grade options trading. It transitions from simple Greeks to **Market Microstructure Intelligence**, identifying where dealer hedging will accelerate trends or enforce mean reversion.

---

## 🏛️ 1. Architecture Overview
The engine is split into two primary modules:
1. **Tactical Strategy Engine (`17_NIFTY_Strategy_Engine`)**: Focused on today's execution. Selects the optimal strategy (Mean Rev vs. Trend) based on near-term Gamma Flips and Vanna flows.
2. **Monthly Surface Engine (`18_NSE_Monthly_Engine`)**: Focused on the medium-term horizon. Analyzes "Term Structure" (Weekly vs. Monthly) to detect fragility or anchoring in the broader market.

---

## 🌐 2. Data Ingestion (The NSE v3 Handshake)
The NDE uses a hardened **NSE v3 Client** to bypass traditional security blocks.
- **🚀 Fetch Live Chains**: Click this in the sidebar to perform a multi-stage handshake with the NSE. It shards data into `Weekly Near`, `Weekly Next`, and `Monthly Near` automatically.
- **📂 Manual Upload**: If the API is rate-limited, you can upload an NSE-style CSV. The engine will automatically clean the data and center it around the current Nifty ATR.

---

## 📊 3. Understanding Core Metrics

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

## 🎯 4. Strategy Selection Logic
The engine automatically grades strategies based on a **Confidence Hierarchy**:

| Strategy | Ideal Conditions | Logic Trigger |
| :--- | :--- | :--- |
| **Trend Acceleration** | Below Flip + Negative Vanna | `spot < flip` + `vanna_bias == Negative` |
| **Mean Reversion** | Above Flip + High TV Ratio | `spot > flip` + `tv_norm > 1.2` |
| **Gamma Flip Trade** | Spot within 0.25% of Flip | `flip_dist < 0.0025` + `High delta GEX` |

> [!IMPORTANT]
> **Institutional Gate**: If the Monthly Engine detects **Fragility** in the next week's expiry (W2), Mean Reversion trades for W1 are automatically downgraded or blocked to prevent "Pinning Failure" risk.

---

## 🏛️ 5. Using the Monthly Engine
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

## 🛠️ 6. Pro Tips for Execution
1. **The Pro Toggle**: Switch to **Pro Mode (Per-Lot)** in the Monthly Engine to see GEX normalized by lot size. This lets you compare a Weekly expiry directly to a Monthly expiry fairly.
2. **Migration Tracking**: In the Monthly Engine, look for `( +12 Cr )` next to GEX levels. This shows intraday positioning shifts. Positive migration at a support level is a high-conviction "Long" signal.
3. **Execution Mode**: Use the sidebar in the Strategy Engine to toggle between **Defensive** (targets farther strikes) and **Aggressive** (targets tighter strikes).

---
**Institutional Grade | Lot-Invariant | Surface Aware**
*Designed for disciplined execution on the Nifty 50 Index.*
