# Architecture Decision Records (ADR)

> Log of significant design decisions in the Dashboard project.
> Format: [ADR-NNN] Title — Status — Date

---

## ADR-001: Monolith Streamlit Multi-Page Architecture

**Status:** Accepted
**Date:** 2026-02 (initial build)

### Context
The project needed a rapid-iteration dashboard for Indian equity swing trading combining macro analysis, stock screening, journaling, and operational tools. The developer is a solo operator requiring fast UI development with embedded data processing.

### Decision
Build as a single Streamlit multi-page application with all modules in one repository. Streamlit's `pages/` directory convention provides automatic page routing. All data fetching, analytics, and UI rendering coexist in the same Python process.

### Consequences
- ✅ Fastest development velocity for a solo developer
- ✅ Shared state via `st.session_state` across pages
- ✅ Single deployment unit
- ❌ No horizontal scaling — all pages share one process
- ❌ Large files emerge as features accumulate (`data_fetch.py` 2034 lines, `0_NSE_Dashboard.py` 2288 lines)
- ❌ Testing Streamlit pages requires mocking the framework

---

## ADR-002: JSON Snapshot Persistence for Regime State

**Status:** Accepted
**Date:** 2026-02

### Context
The regime scoring engine produces a regime classification (Risk On / Selective / Defensive / Crisis) that needs to be available across page loads, EOD pipeline runs, and prediction integrity issuance. A database would add operational complexity for a single-user tool.

### Decision
Persist regime state as JSON files in the `notes/` directory (`current_regime_snapshot.json`) and `data/snapshots/` directory (timestamped EOD snapshots `eod_YYYYMMDD.json`). The `regime_state.py` module provides `save_regime_snapshot()` and `load_regime_snapshot()` with a fallback chain: live snapshot → latest EOD snapshot.

### Consequences
- ✅ Zero infrastructure dependency (no database)
- ✅ Human-readable state files for debugging
- ✅ Easy backup/restore
- ❌ No concurrent write safety (acceptable for single-user)
- ❌ No historical query beyond what EOD snapshots provide

---

## ADR-003: Append-Only Prediction Integrity with Parquet Storage

**Status:** Accepted
**Date:** 2026-02

### Context
The prediction integrity framework needed to prevent hindsight contamination — once a prediction is issued, it must never be modified. A database with row-level locking was considered but rejected for the same reasons as ADR-002.

### Decision
Store predictions and outcomes in Parquet files (`data/prediction_integrity/predictions.parquet`, `outcomes.parquet`) using an append-only pattern. The `store.py` module provides `append_immutable()` which deduplicates by key column before appending. No update or delete paths exist by design.

### Consequences
- ✅ Immutability guarantees — impossible to repaint predictions
- ✅ Parquet provides efficient columnar storage and fast reads
- ✅ Governance audit trail is inherent
- ❌ Cannot fix bad data without manual parquet manipulation
- ❌ File grows unbounded (acceptable at current volume)

---

## ADR-004: BhavCopy Fallback for NSE Price Data

**Status:** Accepted
**Date:** 2026-02

### Context
Yahoo Finance can be unreliable for Indian stock prices — data can be stale, missing, or delayed. NSE's official BhavCopy (end-of-day settlement files) provides authoritative prices but requires downloading and parsing ZIP/CSV files.

### Decision
Implement a multi-layer price resolution strategy:
1. Local parquet history (fastest, pre-built)
2. Yahoo Finance batch download
3. BhavCopy fallback for NSE equity symbols when Yahoo data is stale or missing
4. EOD reconciliation after cutoff hour (overwrite latest day from BhavCopy)

BhavCopy files are scanned from multiple directories (`data/bhavcopy/`, `~/Desktop/Bhavcopy`, `~/Downloads`). Auto-download from NSE archives is supported.

### Consequences
- ✅ Authoritative exchange close prices available as fallback
- ✅ Resilient to Yahoo Finance outages
- ✅ EOD reconciliation ensures consistency for regime scoring
- ❌ BhavCopy parsing is complex (multiple column formats across years)
- ❌ Auto-download may fail if NSE changes archive URL format

---

## ADR-005: Regime and Swing Score Separation

**Status:** Accepted (with documented unification target)
**Date:** 2026-02

### Context
Two independent regime classification paths exist:
1. **Macro Risk engine** (`3_Macro_Risk.py`) — multi-factor weighted model producing probabilities
2. **Swing engine** (`0_NSE_Dashboard.py`) — simplified regime from NIFTY/Bank NIFTY trend + breadth

These evolved independently as features were added incrementally. See `docs/SCORING_LOGIC.md` §0 ("Engine Join Map").

### Decision
Keep both paths operational for now. The Macro Risk engine is the authoritative regime source for prediction integrity and cross-page display (via `regime_state.py` SSOT). The Swing engine uses its own local regime for gate decisions.

### Consequences
- ❌ Changing Macro Risk thresholds does not automatically affect Swing gates
- ❌ Two potentially conflicting regime signals confuse interpretation
- ✅ Each engine can be tested/calibrated independently
- 📅 **Target unification date: 2026-04-15** (documented in SCORING_LOGIC.md §6)

---

## ADR-006: Streamlit Cache Strategy (`@st.cache_data`)

**Status:** Accepted
**Date:** 2026-02

### Context
Data fetching (Yahoo Finance, FRED, RSS) is slow and rate-limited. Every Streamlit interaction reruns the page script. Without caching, each widget click would trigger full data re-download.

### Decision
Use Streamlit's `@st.cache_data` decorator on all data-fetching functions in `data_fetch.py` with configurable TTL (`CACHE_TTL = 300` seconds by default). Individual cache TTLs are set per data source (e.g., `FINNHUB_NEWS_TTL = 900`, `EODHD_FUNDAMENTALS_TTL = 3600`).

### Consequences
- ✅ Sub-second page reloads after initial data fetch
- ✅ Respects API rate limits
- ❌ Stale data possible within TTL window (acceptable for dashboard use)
- ❌ Cache invalidation requires manual page refresh or `st.cache_data.clear()`

---

## ADR-007: Sidebar Navigation Disabled in Streamlit Config

**Status:** Accepted
**Date:** 2026-02

### Context
Streamlit's default sidebar auto-generates a flat list of all pages. With 16 pages, this becomes unwieldy and lacks logical grouping.

### Decision
Disable default sidebar nav (`showSidebarNavigation = false` in `.streamlit/config.toml`) and implement custom grouped navigation in `utils.py` (`_render_grouped_sidebar_nav()`).

### Consequences
- ✅ Pages grouped by workflow phase (Markets, Analysis, Operations, etc.)
- ✅ Better user orientation for the recommended flow
- ❌ New pages require manual addition to the nav function
- ❌ Loses Streamlit's automatic URL routing for new pages (must manually add)

---

## ADR-008: Price Source Consistency Mode

**Status:** Accepted
**Date:** 2026-02

### Context
Different pages may display the same symbol with different freshness — one page using live ticker quotes, another using cached close values. This creates confusing discrepancies.

### Decision
Introduce `PRICE_FETCH_MODE` config (`close_only` or `live_first`). Global Markets page overrides to `live_first`; all other pages default to `close_only` for cross-page consistency. The `Factor Registry` documents the intended mode per factor per page.

### Consequences
- ✅ Consistent prices across regime scoring, swing rankings, and portfolio risk
- ❌ Non-live prices may feel stale during market hours
- ✅ Explicit per-page mode override prevents accidental cross-page divergence
