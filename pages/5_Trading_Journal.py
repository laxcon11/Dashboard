import streamlit as st
import pandas as pd
from datetime import datetime
import pytz
from pathlib import Path
import json
import uuid
from contextlib import contextmanager
from NSE_Config import NIFTY_200, SECTOR_CATEGORIES
from config import (
    GIFT_NIFTY_INV_PREFLAG,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
    ATR_PERIOD,
)
from data_fetch import batch_download, extract_price_data
from gift_nifty import get_gift_nifty_snapshot, is_gift_session_active
from regime_state import load_regime_snapshot
from utils import setup_page, get_ui_detail_mode, get_ui_device_mode, make_page_diag_block, get_fno_lot_size
from indicators import calculate_rsi, calculate_ema, calculate_atr
import analytics
import scoring


setup_page("Trading Journal")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"
_summary_diag = st.expander("🔬 Open Diagnostics", expanded=False) if view_mode == "Summary" else None
page_diag_block = make_page_diag_block(view_mode, _summary_diag)


def _responsive_cols(n_or_spec):
    if is_mobile:
        count = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [st.container() for _ in range(count)]
    return st.columns(n_or_spec)


def safe_float(val, default=0.0):
    try:
        if val is None or (isinstance(val, str) and val.strip() == ""):
            # If default itself is invalid, return 0.0 to prevent infinite recursion or crash
            try:
                if default is None or (isinstance(default, str) and default.strip() == ""):
                    return 0.0
                return float(default)
            except (ValueError, TypeError):
                return 0.0
        return float(val)
    except (ValueError, TypeError):
        try:
            if default is None or (isinstance(default, str) and default.strip() == ""):
                return 0.0
            return float(default)
        except (ValueError, TypeError):
            return 0.0


def safe_int(val, default=1):
    try:
        if val is None or (isinstance(val, str) and val.strip() == ""):
            return int(default)
        return int(float(val)) # Handling float strings like "50.0"
    except (ValueError, TypeError):
        return int(default)


def _compact_table(
    df: pd.DataFrame,
    mobile_cols: list[str] | None = None,
    rows_summary: int = 20,
    rows_detail: int = 40,
) -> pd.DataFrame:
    out = df.copy()
    if is_mobile:
        if mobile_cols:
            keep = [c for c in mobile_cols if c in out.columns]
            if keep:
                out = out[keep]
        cap = rows_summary if view_mode == "Summary" else rows_detail
        out = out.head(cap)
    return out

st.title("🚀 Trading Journal")
st.caption("Log trades, manage risk, and review execution.")
st.caption(f"Device mode: **{device_mode}**")
st.markdown(
    """
    <style>
    .tj-card {
        border: 1px solid rgba(120,120,120,0.25);
        border-radius: 12px;
        padding: 12px 14px;
        background: rgba(20,20,20,0.25);
        margin-bottom: 10px;
    }
    .tj-pill {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        border: 1px solid rgba(180,180,180,0.25);
        margin-right: 6px;
    }
    .tj-open { color:#0f9d58; background:rgba(15,157,88,0.12); }
    .tj-closed { color:#c0392b; background:rgba(192,57,43,0.12); }
    .tj-muted { color:#b0b0b0; font-size:0.86rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- PRE-FILL HANDLING ---
journal_prefill = st.session_state.pop("journal_prefill", None)
query_params = st.query_params

def _qp_scalar(value, default: str = "") -> str:
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else default
    if value is None:
        return default
    return str(value)

if isinstance(journal_prefill, dict):
    pre_symbol = str(journal_prefill.get("symbol", ""))
    pre_strategy = str(journal_prefill.get("strategy", "Swing Ranking"))
    pre_side = str(journal_prefill.get("side", "LONG"))
    pre_setup_family = str(journal_prefill.get("setup_family", "Momentum"))
    pre_entry_price = float(journal_prefill.get("entry_price", 0.0) or 0.0)
    pre_stop_loss = float(journal_prefill.get("stop_loss", 0.0) or 0.0)
    pre_invalidation = float(journal_prefill.get("invalidation", 0.0) or 0.0)
    pre_notes = str(journal_prefill.get("notes", ""))
    pre_trigger_policy = str(journal_prefill.get("trigger_policy", ""))
    pre_entry_risk_atr = float(journal_prefill.get("entry_risk_atr", 0.0) or 0.0)
    pre_target_price = float(journal_prefill.get("target_price", 0.0) or 0.0)
    pre_quantity = int(journal_prefill.get("quantity", 1) or 1)
else:
    pre_symbol = _qp_scalar(query_params.get("symbol", ""), "")
    pre_strategy = _qp_scalar(query_params.get("strategy", "Swing Rank"), "Swing Rank")
    pre_side = _qp_scalar(query_params.get("side", "LONG"), "LONG")
    pre_setup_family = _qp_scalar(query_params.get("setup_family", "Momentum"), "Momentum")
    try:
        pre_entry_price = float(_qp_scalar(query_params.get("entry_price", "0"), "0") or 0.0)
    except Exception:
        pre_entry_price = 0.0
    try:
        pre_stop_loss = float(_qp_scalar(query_params.get("stop_loss", "0"), "0") or 0.0)
    except Exception:
        pre_stop_loss = 0.0
    try:
        pre_invalidation = float(_qp_scalar(query_params.get("invalidation", "0"), "0") or 0.0)
    except Exception:
        pre_invalidation = 0.0
    pre_notes = _qp_scalar(query_params.get("notes", ""), "")
    pre_trigger_policy = _qp_scalar(query_params.get("trigger_policy", ""), "")
    try:
        pre_entry_risk_atr = float(_qp_scalar(query_params.get("entry_risk_atr", "0"), "0") or 0.0)
    except Exception:
        pre_entry_risk_atr = 0.0
    try:
        pre_target_price = float(_qp_scalar(query_params.get("target_price", "0"), "0") or 0.0)
    except Exception:
        pre_target_price = 0.0
    try:
        pre_quantity = int(float(_qp_scalar(query_params.get("quantity", "1"), "1") or 1))
    except Exception:
        pre_quantity = 1


# ==================== FILE HANDLING ====================
NOTES_DIR = Path("notes")
NOTES_DIR.mkdir(exist_ok=True)
JOURNAL_FILE = NOTES_DIR / "trading_journal.csv"
JOURNAL_META_FILE = NOTES_DIR / "trading_journal.meta.json"
JOURNAL_LEGS_FILE = NOTES_DIR / "trading_journal_legs.csv"
JOURNAL_SCHEMA_VERSION = 5
JOURNAL_COLUMNS = [
    "Trade ID",
    "Date", "Symbol", "Side", "Entry Price", "Exit Price", "Quantity", "Strategy", "Setup Family",
    "Status", "Notes", "Regime", "Liquidity", "Stance", "Trade Intent", "Factor Context",
    "Invalidation", "Invalidation %", "Mistake Tags", "Chart Link", "Exit Reason", "Exit Date",
    "Holding Days", "Outcome R", "Outcome Bucket", "Invalidation Mode", "Locked Invalidation",
    "Locked Invalidation %", "Scanner Invalidation (At Entry)", "Trigger Policy", "Target Price",
    "Entry Risk %", "Entry Risk (ATR)", "MFE %", "MAE %", "Bars to Invalidation", "Bars to Target",
    "Hit Invalidation First", "Hit Target First", "Path Metrics Source",
    "Remaining Quantity", "Entry Regime Confidence", "Entry RiskOn Prob", "Entry Neutral Prob",
    "Entry RiskOff Prob", "Entry Quality Score", "Entry Gate Status", "Entry Vol Ratio", "Entry RS Blend",
    "Initial Risk Amount", "Planned R Target", "Actual R", "Slippage R", "Exit Trigger", "Exit Quality",
    "Sector", "Execution Mode", "Trail Type", "High Since Entry"
]
LEGS_COLUMNS = ["Trade ID", "Leg Type", "Date", "Price", "Quantity", "Notes"]


def _to_float(v, default: float = 0.0) -> float:
    try:
        if pd.isna(v): return default
        return float(v)
    except Exception:
        return default


def _to_int(v, default: int = 0) -> int:
    try:
        if pd.isna(v): return default
        return int(v)
    except Exception:
        return default


def _new_trade_id(symbol: str) -> str:
    sym = str(symbol or "NA").replace(".NS", "").upper()
    return f"{datetime.now():%Y%m%d%H%M%S}_{sym}_{uuid.uuid4().hex[:6]}"

def get_symbol_category(symbol: str) -> str:
    """Find the category for a symbol in SECTOR_CATEGORIES."""
    sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
    for cat, stocks in SECTOR_CATEGORIES.items():
        if sym in stocks:
            return cat
    return "Other"

def load_journal():
    if not JOURNAL_FILE.exists():
        return pd.DataFrame(columns=JOURNAL_COLUMNS)
    try:
        df = pd.read_csv(JOURNAL_FILE)
        for c in JOURNAL_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        # Ensure numeric fields remain numeric-friendly
        numeric_cols = [
            "Entry Price", "Exit Price", "Quantity", "Invalidation", "Invalidation %",
            "Holding Days", "Outcome R", "Locked Invalidation", "Locked Invalidation %",
            "Scanner Invalidation (At Entry)", "Target Price", "Entry Risk %", "Entry Risk (ATR)",
            "Planned R Target", "Actual R", "Slippage R", "MFE %", "MAE %", "High Since Entry"
        ]
        for nc in numeric_cols:
            if nc in df.columns:
                df[nc] = pd.to_numeric(df[nc], errors="coerce").fillna(0.0)
        
        if "Trade ID" in df.columns:
            missing_tid = df["Trade ID"].astype(str).str.strip().eq("")
            if missing_tid.any():
                df.loc[missing_tid, "Trade ID"] = [
                    _new_trade_id(sym) for sym in df.loc[missing_tid, "Symbol"].tolist()
                ]
        if "Remaining Quantity" in df.columns:
            df["Remaining Quantity"] = df["Remaining Quantity"].where(df["Remaining Quantity"] > 0, df["Quantity"])
        
        # Meta handling
        meta = {"schema_version": JOURNAL_SCHEMA_VERSION, "updated_at": datetime.now().isoformat()}
        JOURNAL_META_FILE.write_text(json.dumps(meta, indent=2))
        
        # Ensure Sector column is populated
        if "Execution Mode" in df.columns:
            df["Execution Mode"] = df["Execution Mode"].fillna("MANUAL").replace("", "MANUAL")
        else:
            df["Execution Mode"] = "MANUAL"

        return df[JOURNAL_COLUMNS]
    except Exception as e:
        st.error(f"Error loading journal: {e}")
        return pd.DataFrame(columns=JOURNAL_COLUMNS)


def load_legs() -> pd.DataFrame:
    if not JOURNAL_LEGS_FILE.exists():
        return pd.DataFrame(columns=LEGS_COLUMNS)
    try:
        df = pd.read_csv(JOURNAL_LEGS_FILE)
        for c in LEGS_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(0.0)
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(int)
        return df[LEGS_COLUMNS]
    except Exception:
        return pd.DataFrame(columns=LEGS_COLUMNS)


def save_leg(leg: dict) -> None:
    legs = load_legs()
    legs = pd.concat([legs, pd.DataFrame([leg])], ignore_index=True)
    legs.to_csv(JOURNAL_LEGS_FILE, index=False)


def save_entry(entry):
    df = load_journal()
    new_row = pd.DataFrame([entry])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(JOURNAL_FILE, index=False)
    return df

def get_technical_suggestions(symbol: str, side: str, setup_family: str):
    """Fetch data and suggest invalidation/gate status."""
    if not symbol:
        return None
    
    try:
        data = batch_download([symbol, "^NSEI"], period="6mo")
        df = data.get(symbol)
        nifty_df = data.get("^NSEI")
        
        if df is None or df.empty or len(df) < 50:
            return None
            
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        price = float(close.iloc[-1])
        ema20_series = calculate_ema(df, 20)
        atr_series = calculate_atr(df, ATR_PERIOD)
        
        side_txt = str(side).upper()
        inv_price = 0.0
        
        # 1. Invalidation Suggestion
        if "Pullback" in setup_family:
            inv_price = scoring.pullback_leg_low(df)
        elif "Momentum" in setup_family:
            inv_price = scoring.momentum_leg_low(close, ema20_series, df["Low"])
        else:
            atr = atr_series.iloc[-1] if not atr_series.empty else 0.05 * price
            inv_price = price - (2.0 * atr) if side_txt == "LONG" else price + (2.0 * atr)
            
        # 2. Global Risk Ceiling Guard (3x ATR Cap)
        atr_now = atr_series.iloc[-1] if not atr_series.empty else (0.05 * price)
        inv_price = scoring.get_unified_stop_loss(price, inv_price, atr_now, side_txt)
        
        # 2. Gate Status Check
        regime_snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
        regime_label = regime_snapshot.get("regime_label", "Unknown") if isinstance(regime_snapshot, dict) else "Unknown"
        
        metrics = scoring.calculate_quality_metrics(df, nifty_df)
        quality_score = 0.0
        if metrics:
            vol_q = scoring.clip01(metrics.get("vol_ratio", 1.0) / 2.0)
            rs_q = metrics.get("rs_quality", 0.5)
            quality_score = 0.4 * vol_q + 0.6 * rs_q
            
        gate_status = "PASS"
        if "Risk Off" in regime_label and side_txt == "LONG":
            gate_status = "BLOCKED"
        elif quality_score < 0.45:
            gate_status = "WATCH"
            
        return {
            "suggested_invalidation": round(inv_price, 2),
            "gate_status": gate_status,
            "quality_score": round(quality_score, 2),
            "price": round(price, 2),
            "atr": round(atr_series.iloc[-1], 2) if not atr_series.empty else 0.0,
            "vol_ratio": round(metrics.get("vol_ratio", 1.0), 2) if metrics else 1.0,
            "rs_blend": round(metrics.get("rs_blend", 0.5), 2) if metrics else 0.5
        }
    except Exception as e:
        return None

def get_risk_budget_check(symbol: str, entry_price: float, quantity: int, invalidation: float):
    """Check if the proposed trade breaches portfolio rules."""
    RULES_FILE = Path("notes/portfolio_rules.json")
    if not RULES_FILE.exists():
        return None
        
    try:
        rules = json.loads(RULES_FILE.read_text())
        df = load_journal()
        open_trades = df[df["Status"].astype(str).str.upper() == "OPEN"].copy()
        
        # 1. Total Count
        if len(open_trades) + 1 > rules.get("max_concurrent_trades", 6):
            return {"type": "WARNING", "msg": "Max concurrent trades limit reached."}
            
        # 2. Sector Concentration
        sector = get_symbol_category(symbol)
        proposed_notional = entry_price * quantity
        
        sector_notional = 0.0
        total_notional = proposed_notional
        
        for _, row in open_trades.iterrows():
            row_notional = float(row.get("Entry Price", 0)) * int(row.get("Quantity", 0))
            total_notional += row_notional
            if row.get("Sector", get_symbol_category(str(row["Symbol"]))) == sector:
                sector_notional += row_notional
        
        concentration = (sector_notional + proposed_notional) / (total_notional or 1) * 100
        if concentration > rules.get("max_sector_weight_pct", 35.0):
            return {"type": "CAUTION", "msg": f"High Sector Concentration: {sector} would be {concentration:.1f}%."}
            
        # 3. Single Trade Risk
        risk_per_share = abs(entry_price - invalidation)
        trade_risk = risk_per_share * quantity
        max_r = rules.get("max_risk_per_trade_amt", 10000) # Fallback
        if trade_risk > max_r:
            return {"type": "WARNING", "msg": f"Trade risk ₹{trade_risk:,.0f} exceeds budget ₹{max_r:,.0f}."}
            
        return None
    except Exception:
        return None

def history_period_for_window(start: datetime, end: datetime) -> str:
    days = (end - start).days
    if days < 5: return "5d"
    if days < 28: return "1mo"
    if days < 180: return "6mo"
    if days < 365: return "1y"
    return "5y"

def compute_path_metrics(symbol: str, side: str, entry_price: float, invalidation: float, target_price: float, entry_dt: datetime, exit_dt: datetime) -> dict:
    out = {"mfe_pct": 0.0, "mae_pct": 0.0, "bars_to_invalidation": 0, "bars_to_target": 0, "hit_invalidation_first": "No", "hit_target_first": "No", "path_source": "NONE"}
    if entry_price <= 0 or entry_dt >= exit_dt: return out
    try:
        period = history_period_for_window(entry_dt, exit_dt)
        data = batch_download([symbol], period=period).get(symbol)
        if data is None or data.empty: return out
        
        idx = pd.to_datetime(data.index).tz_localize(None)
        window = data.loc[(idx >= entry_dt) & (idx <= exit_dt)].copy()
        if window.empty: return out
        
        highs = window["High"]
        lows = window["Low"]
        side_txt = str(side).upper()
        
        if side_txt == "LONG":
            out["mfe_pct"] = float(((highs.max() - entry_price) / entry_price) * 100.0)
            out["mae_pct"] = float(((entry_price - lows.min()) / entry_price) * 100.0)
        else:
            out["mfe_pct"] = float(((entry_price - lows.min()) / entry_price) * 100.0)
            out["mae_pct"] = float(((highs.max() - entry_price) / entry_price) * 100.0)
            
        # Path order
        inv_hits = (lows <= invalidation) if side_txt == "LONG" else (highs >= invalidation)
        tgt_hits = (highs >= target_price) if side_txt == "LONG" else (lows <= target_price)
        
        inv_pos = int(inv_hits.values.argmax() + 1) if inv_hits.any() else 0
        tgt_pos = int(tgt_hits.values.argmax() + 1) if tgt_hits.any() else 0
        
        out["bars_to_invalidation"] = inv_pos
        out["bars_to_target"] = tgt_pos
        if inv_pos > 0 and (tgt_pos == 0 or inv_pos < tgt_pos): out["hit_invalidation_first"] = "Yes"
        elif tgt_pos > 0 and (inv_pos == 0 or tgt_pos < inv_pos): out["hit_target_first"] = "Yes"
        
        out["path_source"] = f"YF:{period}"
    except Exception:
        out["path_source"] = "ERROR"
    return out


# ==================== SIDEBAR ====================
st.sidebar.header("Navigation")
page_mode = st.sidebar.radio("Go to", ["Log New Trade", "View History", "Performance Stats"])


# ==================== LOG NEW TRADE ====================
if page_mode == "Log New Trade":
    st.subheader("➕ Log a New Trade")
    
    # 1. Inputs (Symbol, Side, Setup) - OUTSIDE FORM for real-time reactivity
    st.markdown("<div class='tj-card'><b>Step 1: Define Setup</b></div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        symbol_options = sorted(list(NIFTY_200))
        default_sym_idx = 0
        if pre_symbol in symbol_options:
            default_sym_idx = symbol_options.index(pre_symbol)
        selected_sym = st.selectbox("Symbol", options=symbol_options, index=default_sym_idx)
    with c2:
        side_options = ["LONG", "SHORT"]
        side = st.selectbox("Side", options=side_options, index=side_options.index(pre_side) if pre_side in side_options else 0)
    with c3:
        setup_family_options = ["Momentum", "Pullback", "Volatility Contraction", "Breakout", "Other"]
        setup_family = st.selectbox("Setup Family", options=setup_family_options, index=setup_family_options.index(pre_setup_family) if pre_setup_family in setup_family_options else 0)

    # 1.1 Execution Mode & Sync Selection
    st.markdown("<div class='tj-card'><b>Step 2: Execution Mode</b></div>", unsafe_allow_html=True)
    m1, m2 = st.columns([2, 1])
    with m1:
        exec_mode = st.radio("Mode", ["MANUAL", "AUTO", "DUMMY"], horizontal=True, label_visibility="collapsed")
    with m2:
        if exec_mode == "AUTO":
            sync_universe = st.checkbox("Sync with Universe", value=True)
        else:
            sync_universe = False

    # 1.2 Bulk Sync Logic
    if exec_mode == "AUTO" and sync_universe:
        st.info("💡 Auto-Trade will bulk-log all new symbols from the Tradable Universe with a 3:1 RR target and F&O based default sizing.")
        if st.button("🔄 Execute Auto-Trade Sync", type="primary"):
            ist = pytz.timezone('Asia/Kolkata')
            now_ist = datetime.now(ist)
            
            # Enforce Market Hours (09:15 to 15:30 IST)
            market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
            market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if not (market_open <= now_ist <= market_close):
                st.error(f"🛑 Auto-Trade Sync is disabled outside of live market hours (09:15 - 15:30 IST). Current IST Time: {now_ist.strftime('%H:%M')}")
                st.stop()
                
            sig_file = Path("data/snapshots/tradable_signals.parquet")
            if not sig_file.exists():
                st.error("No Tradable Universe data found. Run the Scanner first.")
            else:
                with st.spinner("Processing Auto-Trades..."):
                    df_sigs = pd.read_parquet(sig_file)
                    df_jrnl = load_journal()
                    
                    if df_sigs.empty:
                        st.warning("No signals found in the Universe file.")
                        st.stop()
                    
                    # 1. Identify Latest Signal Date
                    latest_sig_date = df_sigs["date"].max()
                    df_sigs = df_sigs[df_sigs["date"] == latest_sig_date]
                    
                    open_trades = df_jrnl[df_jrnl["Status"] == "OPEN"]["Symbol"].unique()
                    
                    regime_snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
                    
                    logged_count = 0
                    for row in df_sigs.itertuples():
                        raw_sym = str(row.symbol)
                        sym = raw_sym if raw_sym.endswith(".NS") else f"{raw_sym}.NS"
                        if sym in open_trades: continue
                        
                        # Strict Guard: Audit Reason must be OK
                        audit = getattr(row, "audit_reason", "OK")
                        if audit != "OK":
                            continue

                        setup_fam = str(row.setup_type).split(" ")[0].strip() # Clean emojis
                        side = "LONG"
                        
                        # Use deterministic precomputed values from Playbook
                        entry_price = float(getattr(row, "suggested_entry", 0.0))
                        inv = float(getattr(row, "suggested_stop", 0.0))
                        target = float(getattr(row, "target_price", 0.0))
                        
                        raw_qty = getattr(row, "position_size", 0)
                        qty = int(raw_qty) if pd.notna(raw_qty) else 0
                        
                        if entry_price <= 0 or inv <= 0 or qty <= 0:
                            continue
                        
                        risk = abs(entry_price - inv)
                        trade_id = _new_trade_id(sym)
                        now_s = datetime.now().strftime("%Y-%m-%d")
                        
                        entry = {
                            "Trade ID": trade_id,
                            "Date": now_s,
                            "Symbol": sym,
                            "Side": side,
                            "Entry Price": entry_price,
                            "Quantity": qty,
                            "Strategy": "Universe Sync",
                            "Setup Family": setup_fam,
                            "Status": "OPEN",
                            "Notes": f"Auto-Trade triggered from Execution Playbook. Validity until: {getattr(row, 'valid_until', 'N/A')}",
                            "Sector": get_symbol_category(sym),
                            "Invalidation": inv,
                            "Target Price": target,
                            "Entry Regime Confidence": regime_snapshot.get("confidence", 0.0) if regime_snapshot else 0.5,
                            "Entry Quality Score": float(getattr(row, "quality_score", 0.0)),
                            "Entry Gate Status": "PASSED (Playbook)",
                            "Initial Risk Amount": risk * qty,
                            "Remaining Quantity": qty,
                            "Planned R Target": 2.0, # Updated to 2.0 per strict R:R plan
                            "Execution Mode": "AUTO",
                            "Trail Type": "ATR", # Default for auto-trades
                            "High Since Entry": entry_price
                        }
                        
                        save_entry(entry)
                        save_leg({
                            "Trade ID": trade_id,
                            "Leg Type": "ENTRY",
                            "Date": now_s,
                            "Price": entry_price,
                            "Quantity": qty,
                            "Notes": "Auto-Trade Initial Entry"
                        })
                        open_trades = list(open_trades) + [sym] # Prevent duplicates
                        logged_count += 1
                        
                    st.success(f"Synced {logged_count} new Auto-Trades from Universe!")
                    if logged_count > 0: st.balloons()
            st.stop() # Stop rendering the rest of the form since we just bulk synced

    # 2. System Guidance
    suggestions = get_technical_suggestions(selected_sym, side, setup_family)
    if suggestions:
        sg1, sg2, sg3 = st.columns(3)
        with sg1:
            st.metric("Suggested Inv", f"₹{suggestions['suggested_invalidation']}")
        with sg2:
            st.metric("Gate Status", suggestions["gate_status"])
        with sg3:
            st.metric("Quality Score", suggestions["quality_score"])

    # 3. Main Form
    if exec_mode == "AUTO":
        st.warning("⚠️ AUTO trades must be logged via the **Sync with Universe** button above. Manual entry is disabled.")
        st.stop()
        
    with st.form("trade_form"):
        st.markdown("<div class='tj-card'><b>Step 3: Execution Details</b></div>", unsafe_allow_html=True)
        f1, f2, f3 = st.columns(3)
        with f1:
            date_val = st.date_input("Entry Date", datetime.now())
            entry_price = st.number_input("Entry Price", value=safe_float(suggestions['price']) if suggestions else pre_entry_price, step=0.05)
        with f2:
            default_qty = get_fno_lot_size(selected_sym)
            quantity = st.number_input("Quantity", value=safe_int(default_qty or 1), min_value=1)
            
            suggested_inv = safe_float(suggestions['suggested_invalidation']) if suggestions else pre_invalidation
            invalidation = st.number_input("Invalidation Price", value=suggested_inv, step=0.05)
        with f3:
            # Auto Calc Target if 3:1 RR requested for AUTO mode
            default_target = pre_target_price
            if exec_mode == "AUTO" and invalidation > 0 and entry_price != invalidation:
                risk = abs(entry_price - invalidation)
                if side == "LONG":
                    default_target = entry_price + (3.0 * risk)
                else:
                    default_target = entry_price - (3.0 * risk)
            
            target = st.number_input("Target Price", value=default_target, step=0.05)
            strategy_options = [
                "Swing Rank", 
                "Technical - Momentum",
                "Technical - Mean Reversion",
                "Technical - Breakout",
                "Technical - VCP",
                "Fundamental / Catalyst",
                "Macro / Sector Rotation",
                "Discretionary / Gut Feel",
                "System Override",
                "Universe Sync"
            ]
            strategy = st.selectbox("Execution Strategy", strategy_options, index=strategy_options.index(pre_strategy) if pre_strategy in strategy_options else 0)
            trail_type = st.selectbox("Trail Type", ["OFF", "EMA", "ATR"], index=0)

        notes = st.text_area("Notes / Logic", value=pre_notes)
        
        # Risk Budget Check
        risk_check = get_risk_budget_check(selected_sym, entry_price, quantity, invalidation)
        if risk_check:
            st.info(f"{risk_check['type']}: {risk_check['msg']}")

        if st.form_submit_button("🚀 Log Trade"):
            # 0. Global Risk Ceiling Guard
            # Fetch ATR14 for the symbol if possible to apply ceiling
            with st.spinner("Applying Risk Ceiling..."):
                hist_data = batch_download([selected_sym], period="3mo")
                s_df = hist_data.get(selected_sym)
                atr_val = calculate_atr(s_df, 14).iloc[-1] if s_df is not None and not s_df.empty else (0.05 * entry_price)
                
                # Apply Unified Ceiling to the user-entered invalidation
                final_invalidation = scoring.get_unified_stop_loss(entry_price, invalidation, atr_val, side)
            
            regime_snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
            trade_id = str(uuid.uuid4())[:8] # Changed to UUID for uniqueness
            
            entry = {
                "Trade ID": trade_id,
                "Date": date_val.strftime("%Y-%m-%d"),
                "Symbol": selected_sym,
                "Side": side,
                "Entry Price": safe_float(entry_price),
                "Quantity": int(quantity),
                "Strategy": strategy,
                "Setup Family": setup_family,
                "Status": "OPEN",
                "Notes": notes,
                "Sector": get_symbol_category(selected_sym),
                "Invalidation": safe_float(final_invalidation), # Use the unified invalidation
                "Target Price": target,
                "Entry Regime Confidence": regime_snapshot.get("confidence", 0.0) if regime_snapshot else 0.5,
                "Entry Quality Score": suggestions["quality_score"] if suggestions else 0.0,
                "Entry Gate Status": suggestions["gate_status"] if suggestions else "UNKNOWN",
                "Initial Risk Amount": abs(entry_price - invalidation) * quantity,
                "Remaining Quantity": quantity,
                "Planned R Target": (abs(target - entry_price) / abs(entry_price - invalidation)) if (target > 0 and abs(entry_price - invalidation) > 0) else 0.0,
                "Execution Mode": exec_mode,
                "Trail Type": trail_type,
                "High Since Entry": entry_price
            }
            save_entry(entry)
            save_leg({
                "Trade ID": trade_id,
                "Leg Type": "ENTRY",
                "Date": date_val.strftime("%Y-%m-%d"),
                "Price": safe_float(entry_price),
                "Quantity": safe_int(quantity),
                "Notes": "Initial Entry"
            })
            st.success(f"Logged {selected_sym} trade!")
            st.balloons()


# ==================== VIEW HISTORY ====================
elif page_mode == "View History":
    st.subheader("📜 Trade History")
    df = load_journal()
    if not df.empty:
        # Filter & Display
        f_status = st.multiselect("Filter Status", ["OPEN", "CLOSED"], default=["OPEN", "CLOSED"])
        display_df = df[df["Status"].isin(f_status)]
        
        # Live Price Logic
        open_mask = display_df["Status"] == "OPEN"
        if open_mask.any():
            open_symbols = display_df.loc[open_mask, "Symbol"].unique().tolist()
            with st.spinner("Fetching 6mo data for open trades..."):
                current_data = batch_download(open_symbols, period="6mo")
                prices = {}
                for s in open_symbols:
                    s_df = current_data.get(s)
                    if s_df is not None and not s_df.empty:
                        prices[s] = safe_float(s_df["Close"].iloc[-1])
                
                display_df.loc[open_mask, "LTP"] = display_df.loc[open_mask, "Symbol"].map(prices)
                
                def calc_unrealized(row):
                    if row["Status"] == "OPEN" and not pd.isna(row.get("LTP")):
                        pnl = (row["LTP"] - row["Entry Price"]) if row["Side"]=="LONG" else (row["Entry Price"] - row["LTP"])
                        return pnl * row["Remaining Quantity"]
                    return 0.0
                display_df.loc[open_mask, "P&L"] = display_df.apply(calc_unrealized, axis=1)

                # Trailing SL & Auto-Close Interceptor
                auto_closed = False
                journal_updated = False
                now_s = datetime.now().strftime("%Y-%m-%d")
                
                for idx, row in display_df[open_mask].iterrows():
                    sym = row["Symbol"]
                    s_df = current_data.get(sym)
                    if s_df is None or s_df.empty: continue
                    
                    ltp = prices.get(sym)
                    if not ltp: continue
                    
                    trail = str(row.get("Trail Type", "OFF")).upper()
                    if trail != "OFF":
                        # 1. Update High Since Entry
                        curr_high = safe_float(s_df["High"].iloc[-1])
                        old_high = safe_float(row.get("High Since Entry"), row["Entry Price"])
                        new_high = max(old_high, curr_high) if row["Side"] == "LONG" else min(old_high, curr_high)
                        
                        # 2. Recalculate Stop
                        atr14 = calculate_atr(s_df, 14).iloc[-1]
                        ema20 = calculate_ema(s_df, 20)
                        
                        new_inv = scoring.get_trailing_stop_loss(
                            side=row["Side"],
                            entry_price=row["Entry Price"],
                            initial_stop=safe_float(row.get("Scanner Invalidation (At Entry)"), row["Invalidation"]),
                            current_price=ltp,
                            high_since_entry=new_high,
                            atr14=atr14,
                            ema20=ema20,
                            trail_type=trail
                        )
                        
                        # Apply if improved
                        old_inv = safe_float(row["Invalidation"])
                        if row["Side"] == "LONG":
                            final_inv = max(old_inv, new_inv)
                        else:
                            final_inv = min(old_inv, new_inv)
                            
                        # Update df and display_df
                        if final_inv != old_inv or new_high != old_high:
                            df.at[idx, "Invalidation"] = final_inv
                            df.at[idx, "High Since Entry"] = new_high
                            display_df.at[idx, "Invalidation"] = final_inv
                            journal_updated = True
                            # Refresh row for subsequent check
                            row["Invalidation"] = final_inv
                    
                    # 3. Check Exits (Existing logic)
                    if str(row.get("Execution Mode")).upper() == "AUTO":
                        ltp = row.get("LTP")
                        if pd.isna(ltp) or ltp <= 0: continue
                        side = str(row.get("Side", "LONG")).upper()
                        inv = safe_float(row.get("Invalidation"), 0)
                        tgt = safe_float(row.get("Target Price"), 0)
                        qty = safe_int(row.get("Remaining Quantity"), 0)
                        
                        exit_price = 0.0
                        reason = ""
                        if side == "LONG":
                            if tgt > 0 and ltp >= tgt: exit_price, reason = tgt, "Target Hit"
                            elif inv > 0 and ltp <= inv: exit_price, reason = inv, "Stop Loss"
                        else:
                            if tgt > 0 and ltp <= tgt: exit_price, reason = tgt, "Target Hit"
                            elif inv > 0 and ltp >= inv: exit_price, reason = inv, "Stop Loss"
                            
                        if reason and qty > 0:
                            save_leg({"Trade ID": row["Trade ID"], "Leg Type": "EXIT", "Date": now_s, "Price": exit_price, "Quantity": qty, "Notes": f"Auto-Close: {reason}"})
                            df.at[idx, "Remaining Quantity"] = 0
                            df.at[idx, "Status"] = "CLOSED"
                            df.at[idx, "Exit Price"] = exit_price
                            df.at[idx, "Exit Date"] = now_s
                            
                            pnl_gross = (exit_price - row["Entry Price"]) if side=="LONG" else (row["Entry Price"] - exit_price)
                            trade_val = (exit_price + row["Entry Price"]) * qty
                            pnl_net = (pnl_gross * qty) - (trade_val * 0.002)
                            risk = row.get("Initial Risk Amount", 0.0)
                            df.at[idx, "Actual R"] = (pnl_net / risk) if risk > 0 else 0.0
                            df.at[idx, "Outcome R"] = df.at[idx, "Actual R"]
                            auto_closed = True
                
                if auto_closed or journal_updated:
                    df.to_csv(JOURNAL_FILE, index=False)
                    if auto_closed:
                        st.success("Auto-Trades processed automatic exits!")
                    if journal_updated:
                        st.info("Dynamic Trailing SLs updated based on price action.")
                    st.rerun()
        # Reorder for display
        def map_exec_mode(mode):
            m = str(mode).upper()
            if m == "AUTO": return "🤖 AUTO"
            elif m == "MANUAL": return "🧑‍💻 MANUAL"
            elif m == "DUMMY": return "🧪 DUMMY"
            return m
            
        display_df["Mode"] = display_df["Execution Mode"].apply(map_exec_mode)

        cols = ["Date", "Symbol", "Side", "Status", "Mode", "Trail Type", "Entry Price", "Quantity", "Invalidation", "Sector"]
        if "LTP" in display_df.columns: cols.append("LTP")
        if "P&L" in display_df.columns: cols.append("P&L")
        
        st.dataframe(display_df[cols].sort_values("Date", ascending=False), width="stretch", hide_index=True)

        # Close Trade UI
        st.markdown("### 🔒 Close Trade")
        open_trades = df[df["Status"] == "OPEN"]
        if not open_trades.empty:
            for idx, row in open_trades.iterrows():
                with st.expander(f"Close {row['Symbol']} (ID: {row['Trade ID']})"):
                    with st.form(f"close_{idx}"):
                        exit_price = st.number_input("Exit Price", value=row["Entry Price"])
                        exit_qty = st.number_input("Quantity", value=int(row["Remaining Quantity"]), max_value=int(row["Remaining Quantity"]))
                        reason = st.selectbox("Reason", ["Target Hit", "Stop Loss", "Regime Change", "Manual"])
                        if st.form_submit_button("Confirm"):
                            # Logic for partial/full exit
                            now_s = datetime.now().strftime("%Y-%m-%d")
                            save_leg({"Trade ID": row["Trade ID"], "Leg Type": "EXIT", "Date": now_s, "Price": exit_price, "Quantity": exit_qty, "Notes": reason})
                            
                            new_rem = row["Remaining Quantity"] - exit_qty
                            df.at[idx, "Remaining Quantity"] = new_rem
                            
                            # Calculate weighted exit if full close
                            if new_rem <= 0:
                                trade_legs = load_legs()
                                trade_exits = trade_legs[(trade_legs["Trade ID"] == row["Trade ID"]) & (trade_legs["Leg Type"] == "EXIT")]
                                total_exit_notional = (trade_exits["Price"] * trade_exits["Quantity"]).sum()
                                total_exit_qty = trade_exits["Quantity"].sum()
                                weighted_exit = total_exit_notional / total_exit_qty if total_exit_qty > 0 else exit_price
                                
                                df.at[idx, "Status"] = "CLOSED"
                                df.at[idx, "Exit Price"] = weighted_exit
                                df.at[idx, "Exit Date"] = now_s
                                # Path Metrics
                                path = compute_path_metrics(row["Symbol"], row["Side"], row["Entry Price"], row["Invalidation"], row["Target Price"], pd.to_datetime(row["Date"]), datetime.now())
                                for k, v in path.items(): df.at[idx, k] = v
                                
                                # Final P&L
                                pnl_gross = (weighted_exit - row["Entry Price"]) if row["Side"]=="LONG" else (row["Entry Price"] - weighted_exit)
                                trade_value = (weighted_exit + row["Entry Price"]) * exit_qty
                                t_cost = trade_value * 0.002  # 0.2% transaction charges
                                pnl_net = (pnl_gross * row["Quantity"]) - t_cost
                                
                                risk = row["Initial Risk Amount"]
                                df.at[idx, "Actual R"] = (pnl_net / risk) if risk > 0 else 0.0
                                df.at[idx, "Outcome R"] = df.at[idx, "Actual R"]
                                
                            df.to_csv(JOURNAL_FILE, index=False)
                            st.rerun()

                # Option to totally delete Dummy trades
                if str(row.get("Execution Mode", "")).upper() == "DUMMY":
                    if st.button(f"🗑️ Delete Dummy {row['Symbol']}", key=f"del_{idx}"):
                        df = df.drop(idx)
                        df.to_csv(JOURNAL_FILE, index=False)
                        
                        # Remove legs too
                        trade_legs = load_legs()
                        trade_legs = trade_legs[trade_legs["Trade ID"] != row["Trade ID"]]
                        trade_legs.to_csv(JOURNAL_LEGS_FILE, index=False)
                        st.rerun()

# ==================== PERFORMANCE STATS ====================
elif page_mode == "Performance Stats":
    st.subheader("📊 Performance Statistics")
    df = load_journal()
    
    # Exclude Dummy Trades
    real_trades = df[df["Execution Mode"].astype(str).str.upper() != "DUMMY"].copy()
    closed = real_trades[real_trades["Status"] == "CLOSED"].copy()
    
    if not closed.empty:
        # PnL includes 0.2% transaction charges on total trade value
        def calc_net_pnl(r):
            q = r["Quantity"]
            pnl_gross = (r["Exit Price"] - r["Entry Price"])*q if r["Side"]=="LONG" else (r["Entry Price"] - r["Exit Price"])*q
            trade_value = (r["Exit Price"] + r["Entry Price"]) * q
            t_cost = trade_value * 0.002
            return pnl_gross - t_cost
            
        closed["PnL"] = closed.apply(calc_net_pnl, axis=1)
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Realized P&L (Net)", f"₹{closed['PnL'].sum():,.0f}")
        m2.metric("Win Rate", f"{((closed['PnL'] > 0).mean()*100):.1f}%")
        m3.metric("Avg R", f"{closed['Actual R'].mean():.2f}")

        st.markdown("### 🧩 Performance Slicing")
        
        # Row 1: Sector & Setup Family
        s1, s2 = st.columns(2)
        with s1:
            st.write("**By Sector**")
            sector_stats = closed.groupby("Sector").agg(Trades=("PnL", "count"), AvgR=("Actual R", "mean")).reset_index()
            st.dataframe(sector_stats.sort_values("AvgR", ascending=False), hide_index=True)
        with s2:
            st.write("**By Setup Family**")
            setup_stats = closed.groupby("Setup Family").agg(Trades=("PnL", "count"), AvgR=("Actual R", "mean")).reset_index()
            st.dataframe(setup_stats.sort_values("AvgR", ascending=False), hide_index=True)

        st.markdown("---")
        
        # Row 2: Execution Mode & Strategy
        s3, s4 = st.columns(2)
        with s3:
            st.write("**By Execution Mode**")
            mode_stats = closed.groupby("Execution Mode").agg(Trades=("PnL", "count"), AvgR=("Actual R", "mean")).reset_index()
            st.dataframe(mode_stats.sort_values("AvgR", ascending=False), hide_index=True)
        with s4:
            st.write("**By Strategy**")
            strat_stats = closed.groupby("Strategy").agg(Trades=("PnL", "count"), AvgR=("Actual R", "mean")).reset_index()
            st.dataframe(strat_stats.sort_values("AvgR", ascending=False), hide_index=True)
    else:
        st.info("No closed trades to analyze.")
