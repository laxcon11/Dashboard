# Agent Execution Roadmap: Trading System Architecture

This document provides a strictly structured, task-oriented blueprint (JIRA style) for an AI agent to systematically implement the Trading System architecture. 

Each task is defined by a **Task Contract**, establishing strict `INPUT → OUTPUT → RULES` boundaries. It heavily enforces **Interface Contracts** so outputs chain safely, preventing agents from breaking downstream tasks by changing JSON keys.

---

## 🔵 LAYER 1: Core Engine Tasks

### Task 1: Regime Engine Refactor
**Goal:** Extract regime detection logic into a pure, stateless function.
*   **Contract:**
    *   **INPUT:** Canonical Macro Data, Flow metrics, Historical Context.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "regime": "str(RISK_ON|SELECTIVE|DEFENSIVE|CRISIS)",
          "probability": { "RISK_ON": "float", "SELECTIVE": "float", "DEFENSIVE": "float", "CRISIS": "float" },
          "confidence": "float"
        }
        ```
    *   **RULES:** Must incorporate horizon decay and transition priors.

### Task 2: Market State Engine
**Goal:** Implement options-flow derived micro-states to provide context beyond broad regimes.
*   **Contract:**
    *   **INPUT:** GEX profile, OI walls, Implied Volatility.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "micro_state": "str(PINNED_RANGE|VOL_EXPANSION|SQUEEZE_BUILDUP|LIQUIDITY_VACUUM)"
        }
        ```

### Task 3: Options Analytics Engine
**Goal:** Calculate Greeks, advanced options flow metrics, and locate key dealer levels.
*   **Contract:**
    *   **INPUT:** Canonical Option Chain, Spot Price, Time to Expiry, Risk-Free Rate.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "greeks": {
            "delta": "float", "gamma": "float", "vega": "float", "theta": "float"
          },
          "gex_profile": {
            "total_gex": "float", "per_strike": "array"
          },
          "gamma_flip": "float",
          "walls": { "call": "float", "put": "float" }
        }
        ```

### Task 4: Risk Pre-Filter
**Goal:** Early rejection of dangerous conditions before a strategy is even selected.
*   **Contract:**
    *   **INPUT:** Spot Price, Gamma Flip, ATR, State, Data Quality Score, Expiry Phase.
    *   **OUTPUT SCHEMA:**
        ```json
        {
          "timestamp": "str(ISO8601)",
          "distance_to_flip": "float",
          "can_trade": "bool",
          "reason_code": "str(NEAR_FLIP|REGIME_INSTABILITY|POOR_DATA_QUALITY|NONE)"
        }
        ```
    *   **RULES:** 
        `distance_to_flip = abs(spot - gamma_flip) / ATR`
        ```python
        if distance_to_flip < 1.5 and expiry_phase in ("PRE_EXPIRY", "EXPIRY_RISK"):
            can_trade = False
        elif distance_to_flip < 0.8:
            can_trade = False
        if Data Quality is LOW:
            can_trade = False
        ```

### Task 5: NDE Decision Engine
**Goal:** Determine the exact strategy and action based on the state.
*   **Contract:**
    *   **INPUT:** State (Regime + Micro-state), Risk Pre-Filter output, Volatility Regime.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "action": "str(ENTER|WAIT|EXIT)",
          "strategy": "str",
          "confidence": "float"
        }
        ```
    *   **RULES:**
        *   Must pull strategies ONLY from the predefined `STRATEGY_REGISTRY` mapping defined in `contracts.py`.
        *   Enforce `action = WAIT if confidence < 0.6 or can_trade = false`.

### Task 6: Swing Trade Engine
**Goal:** Filter the equity universe to generate disciplined, momentum-based swing trade signals.
*   **Contract:**
    *   **INPUT:** Canonical EOD Equity Data, Strictness Profile.
    *   **OUTPUT SCHEMA:** `List[{ "timestamp": "str(ISO8601)", "symbol": "str", "setup": "str(LONG|SHORT|WATCH)", "swing_score": "int", "stop_loss": "float" }]`

### Task 7: Arbitrage & Relative Value Engine
**Goal:** Scan options and futures for riskless or statistical arbitrage opportunities.
*   **Contract:**
    *   **INPUT:** Canonical Spot Price, Futures Price, Option Chain.
    *   **OUTPUT SCHEMA:** `List[{ "timestamp": "str(ISO8601)", "arb_type": "str", "net_edge": "float", "execution_readiness_score": "float", "legs": [] }]`
    *   **RULES:** 
        *   Must calculate `net_edge` explicitly modeling friction.
        *   `liquidity_score = clip(min(call_oi, put_oi) / 1000, 0, 1)`
        *   `spread_score = clip(1 - (bid_ask_spread / ltp), 0, 1)`
        *   `margin_score = clip(1 - (required_margin / available_capital), 0, 1)`
        *   `execution_readiness_score = 0.4*liquidity_score + 0.35*spread_score + 0.25*margin_score`

---

## 🟢 LAYER 2: Execution Readiness

### Task 8: Trade Schema Validator
**Goal:** Ensure any strategy generated matches the strict API-ready output schema.
*   **Contract:**
    *   **INPUT:** Raw strategy payload.
    *   **OUTPUT SCHEMA:** `TradeSchema` as defined in `contracts.py`:
        ```json
        {
          "trade_id": "str(UUID)",
          "strategy": "str(from STRATEGY_REGISTRY)",
          "legs": [{
              "instrument": "str",
              "action": "str(BUY|SELL)",
              "strike": "float",
              "expiry": "str(YYYY-MM-DD)",
              "qty_lots": "int"
          }],
          "risk_limits": {
              "max_loss_pts": "float",
              "stop_trigger": "float"
          }
        }
        ```

### Task 9: Strategy → Trade Mapper
**Goal:** Convert a generic strategy into exact tradable strikes.
*   **Contract:**
    *   **INPUT:** Strategy Type, Canonical Option Chain.
    *   **OUTPUT SCHEMA:** `List[{ "type": "str(CE|PE)", "strike": "float" }]`

### Task 10: Position Sizing Engine
**Goal:** Compute the exact quantity to trade based on confidence and capital.
*   **Contract:**
    *   **INPUT:** Quality Score, Confidence Score, Base Capital.
    *   **OUTPUT SCHEMA:** `{ "qty_multiplier": "int", "qty_lots": "int" }`

### Task 11: Risk Post-Validation Engine
**Goal:** Final mathematical safety gate applying position limits and standardizing failure reasons.
*   **Contract:**
    *   **INPUT:** Proposed Strikes, Risk Limits Config, Position Sizing.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "approved": "bool",
          "max_loss_pts": "float",
          "reason_code": "str(EXCEEDS_MARGIN|LOW_LIQUIDITY|HIGH_SLIPPAGE|NONE)"
        }
        ```

### Task 12: State Manager (Persistence Layer)
**Goal:** Provide statefulness to the system to track trades and lifecycle.
*   **Contract:**
    *   **INPUT:** Trade Outputs, Execution Updates.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "open_positions": "array",
          "realized_pnl": "float",
          "unrealized_pnl": "float",
          "lifecycle_state": "str(ACTIVE|PENDING_EXIT)"
        }
        ```

---

## 🟡 LAYER 3: Orchestration & Data Infrastructure

**Global Source Priority Mapping:**
*   **Spot**: Primary [Kite], Backup [NSE]
*   **Futures**: Primary [Kite], Backup [NSE]
*   **Options**: Primary [Kite], Backup [NSE]
*   **Macro**: Primary [FRED], Backup [None]
*   **EOD**: Primary [Yahoo], Backup [None]

### Task 13: Orchestrator
**Goal:** Coordinate the entire pipeline flow chronologically using Dependency Inversion.
*   **Contract:**
    *   **FLOW:** `Data Fetch → Data Adapters → Canonical Normalizer → Data Quality Validator → Analytics → State → Risk Pre-Filter → Strategy Selection → Trade Mapper → Position Sizer → Risk Post-Validation → State Manager → Output`
    *   **RULES:** 
        *   Must operate asynchronously. Must NOT hold direct references to data source APIs; must rely on a generic `DataInterface` to easily swap providers (Kite/NSE).
        *   **Time-Alignment Tolerance:** Must strictly align explicit staleness per data type. Operations wait until `data_timestamps` delta is within the `staleness_delta`. This parameter MUST be configured per regime (e.g., 3 minutes in NORMAL, tightened to 30 seconds in CRISIS).

### Task 14: Data Fetch Orchestrator
**Goal:** Coordinate multiple data sources.
*   **Contract:**
    *   **INPUT:** Source config.
    *   **OUTPUT:** Raw API responses from endpoints.
    *   **RULES:** MUST NOT normalize data. Retry logic: 2-3 times on timeout.

### Task 15: Source-Specific Data Adapters
**Goal:** Convert source-specific data into an intermediate standardized format.
*   **Contract:**
    *   **INPUT:** Raw API response.
    *   **OUTPUT:** Structured intermediate format.
    *   **RULES:** One adapter per source. No business logic allowed.

### Task 16: Canonical Data Normalizer
**Goal:** Convert all adapter outputs into the `CanonicalMarketData` schema defined in `contracts.py`.
*   **Contract:**
    *   **INPUT:** Adapter outputs.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "spot_price": "float",
          "futures_price": "float",
          "option_chain": [
            { "strike": "float", "expiry": "str(YYYY-MM-DD)", "type": "str(CE|PE)", "ltp": "float", "iv": "float", "oi": "float", "volume": "float" }
          ],
          "macro_data": { "rates": "float", "liquidity_index": "float" },
          "data_timestamps": { "spot": "str(ISO8601)", "options": "str(ISO8601)", "macro": "str(ISO8601)" },
          "source_meta": { "spot": "str", "options": "str", "macro": "str" }
        }
        ```
    *   **RULES:** Enforces `CE|PE` mapping globally.

### Task 17: Data Quality Validator (Trust Layer)
**Goal:** Provide a mathematical trust score assessing staleness *per source*.
*   **Contract:**
    *   **INPUT:** Canonical Data Schema.
    *   **OUTPUT SCHEMA:**
        ```json
        {
          "data_quality": "str(HIGH|MEDIUM|LOW)",
          "staleness_seconds": { "spot": "int", "options": "int" },
          "missing_fields": "array"
        }
        ```

### Task 18: API Layer
**Goal:** Expose the core engines via REST endpoints.
*   **Contract:**
    *   **INPUT:** HTTP GET/POST Requests.
    *   **OUTPUT SCHEMA:** Strict Trade Output JSON.

### Task 19: UI / Presentation Layer
**Goal:** Render the Trade Outputs and Playbooks in a clear, actionable dashboard.
*   **Contract:**
    *   **INPUT:** Validated Trade Schema JSON.
    *   **OUTPUT:** Rendered UI Components (Streamlit/React).

---

## 🔴 LAYER 4: Execution Layer & Controls

### Task 20: Order Builder
**Goal:** Translate validated trade schemas into broker-specific payloads.
*   **Contract:**
    *   **INPUT:** Validated Trade Schema.
    *   **OUTPUT SCHEMA:** Broker API Order Payload (e.g., Kite Connect).

### Task 21: Pre-trade Validator
**Goal:** The final safety checkpoint immediately before hitting the market.
*   **Contract:**
    *   **INPUT:** Broker Order Payload, Live Market Data.
    *   **OUTPUT SCHEMA:** 
        ```json
        {
          "timestamp": "str(ISO8601)",
          "can_execute": "bool",
          "reason_code": "str(LOW_LIQUIDITY|MARGIN_SHORTFALL|WIDE_SPREAD|NONE)"
        }
        ```
    *   **RULES:** `ENTER` only if `confidence > 0.6 AND execution_readiness_score > 0.8`.

### Task 22: Circuit Breaker & Error Budget
**Goal:** Institutional-grade loss controls to halt trading during systemic failures or bad days.
*   **Contract:**
    *   **INPUT:** State Manager PnL, Consecutive Loss Count, Data Quality Score.
    *   **RULES:** 
        *   **Drawdown:** If 3 consecutive trades hit stop-loss, or daily loss limit is breached, kill the pipeline for the session. 
        *   **Information Entropy:** If `data_quality` stays at LOW or MEDIUM for an extended period, the circuit breaker MUST trigger. Trading on degraded data is equivalent to blind risk.
        *   Transition state to `CRISIS_HALT`.

### Task 23: Monitoring & Alerting
**Goal:** Track data latency and execution stagnation.
*   **Contract:**
    *   **RULES:** Send alerts if `data_quality == LOW` for > 15 minutes, or if a trade approaches within 0.1% of its stop-loss trigger.

### Task 24: Execution Shadow Layer (Paper Trading)
**Goal:** Safe production validation before live capital deployment.
*   **Contract:**
    *   **INPUT:** Order Builder Payload.
    *   **RULES:** Must intercept the Order Builder output and log it to the State Manager as a virtual fill *without* sending it to the broker. Allows comparison of "ideal" algorithmic performance against "actual" execution fills.
