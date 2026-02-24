import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import json
import uuid
from NSE_Config import NIFTY_200
from config import (
    GIFT_NIFTY_INV_PREFLAG,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
)
from data_fetch import batch_download, extract_price_data
from gift_nifty import get_gift_nifty_snapshot, is_gift_session_active
from regime_state import load_regime_snapshot
from utils import setup_page, get_ui_detail_mode
import analytics


setup_page("Trading Journal")
view_mode = get_ui_detail_mode("Summary")

st.title("🚀 Trading Journal")
st.caption("Track your trades, analyze your performance, and refine your strategy.")
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
    "Initial Risk Amount", "Planned R Target", "Actual R", "Slippage R", "Exit Trigger", "Exit Quality"
]
LEGS_COLUMNS = ["Trade ID", "Leg Type", "Date", "Price", "Quantity", "Notes"]


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _new_trade_id(symbol: str) -> str:
    sym = str(symbol or "NA").replace(".NS", "").upper()
    return f"{datetime.now():%Y%m%d%H%M%S}_{sym}_{uuid.uuid4().hex[:6]}"

def load_journal():
    if not JOURNAL_FILE.exists():
        return pd.DataFrame(columns=JOURNAL_COLUMNS)
    try:
        df = pd.read_csv(JOURNAL_FILE)
        for c in JOURNAL_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        # Ensure numeric fields remain numeric-friendly
        for nc in [
            "Entry Price", "Exit Price", "Quantity", "Invalidation", "Invalidation %",
            "Holding Days", "Outcome R", "Locked Invalidation", "Locked Invalidation %",
            "Scanner Invalidation (At Entry)", "Target Price", "Entry Risk %", "Entry Risk (ATR)",
            "MFE %", "MAE %", "Bars to Invalidation", "Bars to Target", "Remaining Quantity",
            "Entry Regime Confidence", "Entry RiskOn Prob", "Entry Neutral Prob", "Entry RiskOff Prob",
            "Entry Quality Score", "Entry Vol Ratio", "Entry RS Blend", "Initial Risk Amount",
            "Planned R Target", "Actual R", "Slippage R"
        ]:
            df[nc] = pd.to_numeric(df[nc], errors="coerce").fillna(0.0)
        if "Trade ID" in df.columns:
            missing_tid = df["Trade ID"].astype(str).str.strip().eq("")
            if missing_tid.any():
                df.loc[missing_tid, "Trade ID"] = [
                    _new_trade_id(sym) for sym in df.loc[missing_tid, "Symbol"].tolist()
                ]
        if "Remaining Quantity" in df.columns:
            df["Remaining Quantity"] = df["Remaining Quantity"].where(df["Remaining Quantity"] > 0, df["Quantity"])
        # Auto-migration marker
        meta = {"schema_version": JOURNAL_SCHEMA_VERSION, "updated_at": datetime.now().isoformat()}
        try:
            if JOURNAL_META_FILE.exists():
                old = json.loads(JOURNAL_META_FILE.read_text())
                if int(old.get("schema_version", 0)) < JOURNAL_SCHEMA_VERSION:
                    df.to_csv(JOURNAL_FILE, index=False)
            else:
                df.to_csv(JOURNAL_FILE, index=False)
            JOURNAL_META_FILE.write_text(json.dumps(meta, indent=2))
        except Exception:
            pass
        return df[JOURNAL_COLUMNS]
    except Exception as e:
        st.error(f"Error loading journal: {e}")
        return pd.DataFrame()


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


def history_period_for_window(entry_dt: pd.Timestamp, exit_dt: pd.Timestamp) -> str:
    days = max(int((exit_dt - entry_dt).days), 1)
    if days <= 120:
        return "6mo"
    if days <= 260:
        return "1y"
    if days <= 520:
        return "2y"
    if days <= 1300:
        return "5y"
    return "max"


def compute_path_metrics(
    symbol: str,
    side: str,
    entry_price: float,
    invalidation: float,
    target_price: float,
    entry_dt: pd.Timestamp,
    exit_dt: pd.Timestamp,
) -> dict:
    out = {
        "mfe_pct": 0.0,
        "mae_pct": 0.0,
        "bars_to_invalidation": 0,
        "bars_to_target": 0,
        "hit_invalidation_first": "No",
        "hit_target_first": "No",
        "path_source": "NONE",
    }
    if entry_price <= 0 or entry_dt > exit_dt:
        return out

    period = history_period_for_window(entry_dt, exit_dt)
    data = batch_download([symbol], period=period)
    df = data.get(symbol)
    if df is None or df.empty or not {"High", "Low"}.issubset(df.columns):
        return out

    idx = pd.to_datetime(df.index, errors="coerce")
    window = df.loc[(idx >= entry_dt) & (idx <= exit_dt)].copy()
    if window.empty:
        return out

    highs = pd.to_numeric(window["High"], errors="coerce").dropna()
    lows = pd.to_numeric(window["Low"], errors="coerce").dropna()
    if highs.empty or lows.empty:
        return out

    side_txt = str(side).upper()
    if side_txt == "LONG":
        out["mfe_pct"] = float(((highs.max() - entry_price) / entry_price) * 100.0)
        out["mae_pct"] = float(((entry_price - lows.min()) / entry_price) * 100.0)
    else:
        out["mfe_pct"] = float(((entry_price - lows.min()) / entry_price) * 100.0)
        out["mae_pct"] = float(((highs.max() - entry_price) / entry_price) * 100.0)

    # Hit-order checks start from next trading bar after entry.
    scan = window.iloc[1:].copy() if len(window) > 1 else window.iloc[0:0].copy()
    if scan.empty:
        out["path_source"] = f"YF:{period}"
        return out

    scan_hi = pd.to_numeric(scan["High"], errors="coerce")
    scan_lo = pd.to_numeric(scan["Low"], errors="coerce")

    inv_hits = pd.Series(dtype=bool)
    if invalidation > 0:
        inv_hits = (scan_lo <= invalidation) if side_txt == "LONG" else (scan_hi >= invalidation)
    tgt_hits = pd.Series(dtype=bool)
    if target_price > 0:
        tgt_hits = (scan_hi >= target_price) if side_txt == "LONG" else (scan_lo <= target_price)

    inv_pos = int(inv_hits.values.argmax() + 1) if len(inv_hits) > 0 and bool(inv_hits.any()) else 0
    tgt_pos = int(tgt_hits.values.argmax() + 1) if len(tgt_hits) > 0 and bool(tgt_hits.any()) else 0

    out["bars_to_invalidation"] = inv_pos
    out["bars_to_target"] = tgt_pos
    if inv_pos > 0 and (tgt_pos == 0 or inv_pos < tgt_pos):
        out["hit_invalidation_first"] = "Yes"
        out["hit_target_first"] = "No"
    elif tgt_pos > 0 and (inv_pos == 0 or tgt_pos < inv_pos):
        out["hit_invalidation_first"] = "No"
        out["hit_target_first"] = "Yes"
    elif tgt_pos > 0 and inv_pos > 0 and tgt_pos == inv_pos:
        out["hit_invalidation_first"] = "Tie"
        out["hit_target_first"] = "Tie"

    out["path_source"] = f"YF:{period}"
    return out

# ==================== SIDEBAR ====================
st.sidebar.header("Navigation")
page_mode = st.sidebar.radio("Go to", ["Log New Trade", "View History", "Performance Stats"])
st.markdown(
    "<div class='tj-card'><b>Workflow</b><br>"
    "<span class='tj-pill'>1. Log</span>"
    "<span class='tj-pill'>2. Manage</span>"
    "<span class='tj-pill'>3. Review</span>"
    "<div class='tj-muted'>Use locked invalidation and leg-level updates for consistent R analytics.</div></div>",
    unsafe_allow_html=True,
)

# ==================== LOG NEW TRADE ====================
if page_mode == "Log New Trade":
    st.subheader("➕ Log a New Trade")
    existing_df = load_journal()
    open_for_prefill = existing_df[existing_df["Status"].astype(str).str.upper() == "OPEN"].copy() if not existing_df.empty else pd.DataFrame()
    selected_prefill = None
    if not open_for_prefill.empty:
        opt_map = {
            f"{row['Trade ID']} | {row['Symbol']} | {row['Side']} | RemQty {int(_to_int(row.get('Remaining Quantity', row.get('Quantity', 0))))}": idx
            for idx, row in open_for_prefill.iterrows()
        }
        selected_lbl = st.selectbox("Prefill From Existing Open Trade (optional)", options=["(None)"] + list(opt_map.keys()))
        if selected_lbl != "(None)":
            selected_prefill = open_for_prefill.loc[opt_map[selected_lbl]]
            pre_symbol = str(selected_prefill.get("Symbol", pre_symbol))
            pre_side = str(selected_prefill.get("Side", pre_side))
            pre_strategy = str(selected_prefill.get("Strategy", pre_strategy))
            pre_setup_family = str(selected_prefill.get("Setup Family", pre_setup_family))
            pre_entry_price = _to_float(selected_prefill.get("Entry Price", pre_entry_price), pre_entry_price)
            pre_stop_loss = _to_float(selected_prefill.get("Locked Invalidation", pre_stop_loss), pre_stop_loss)
            pre_invalidation = _to_float(selected_prefill.get("Locked Invalidation", pre_invalidation), pre_invalidation)
            pre_quantity = _to_int(selected_prefill.get("Remaining Quantity", selected_prefill.get("Quantity", pre_quantity)), pre_quantity)
            st.caption("Prefill applied from open trade context (entry/side/setup/locked invalidation).")
    
    with st.form("trade_form"):
        st.markdown("<div class='tj-card'><b>Trade Details</b></div>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        
        with col1:
            date = st.date_input("Date", datetime.now())
            
            # Use NIFTY 200 list for the selectbox
            symbol_options = sorted(list(NIFTY_200))
            
            # Pre-select symbol if provided in query params
            default_index = 0
            if pre_symbol and not pre_symbol.endswith(".NS"):
                with_suffix = f"{pre_symbol}.NS"
                if with_suffix in symbol_options:
                    pre_symbol = with_suffix
            if pre_symbol in symbol_options:
                default_index = symbol_options.index(pre_symbol)
            
            # Custom Instrument Toggle
            is_custom = st.checkbox("Custom Instrument", value=(pre_symbol and pre_symbol not in symbol_options), help="Check this to manually enter a symbol not in NIFTY 200")
            
            if is_custom:
                selected_sym = None
                custom_symbol = st.text_input("Enter Symbol (e.g., BTCUSD, ^NSEI)", value=pre_symbol).upper()
            else:
                selected_sym = st.selectbox("Symbol", options=symbol_options, index=default_index, help="Search and select from NIFTY 200 stocks")
                custom_symbol = ""
            
            side_options = ["LONG", "SHORT"]
            side = st.selectbox("Side", side_options, index=side_options.index(pre_side) if pre_side in side_options else 0)
            
            strategy_options = ["Gap Up/Down", "Swing Ranking", "EMA Crossover", "Breakout", "Oversold Reversal", "Other"]
            strategy = st.selectbox("Strategy", 
                strategy_options,
                index=strategy_options.index(pre_strategy) if pre_strategy in strategy_options else 0
            )
            setup_family_options = ["Momentum", "Pullback", "Volatility Contraction", "Breakout", "Mean Reversion", "Other"]
            setup_family = st.selectbox(
                "Setup Family",
                setup_family_options,
                index=setup_family_options.index(pre_setup_family) if pre_setup_family in setup_family_options else 0,
            )
        
        with col2:
            entry_price = st.number_input("Entry Price", min_value=0.0, format="%.2f", value=max(0.0, pre_entry_price))
            quantity = st.number_input("Quantity", min_value=1, value=max(1, int(pre_quantity)), step=1)
            stop_loss = st.number_input("Stop Loss (Optional)", min_value=0.0, format="%.2f", value=max(0.0, pre_stop_loss))
            target = st.number_input("Target (Optional)", min_value=0.0, format="%.2f", value=max(0.0, pre_target_price))
            # Auto-Capture Market Context
            context = analytics.get_current_context() # Future: pass actual data if available
            regime_snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
            if isinstance(regime_snapshot, dict) and regime_snapshot:
                context["regime"] = regime_snapshot.get("regime_label", context.get("regime", "Unknown"))
                context["liquidity"] = f"{float(regime_snapshot.get('liquidity_directional', 0.0) or 0.0):+.2f}"
                context["stance"] = regime_snapshot.get("bias", context.get("stance", "Neutral"))
                st.markdown(
                    "<div class='tj-card'>"
                    f"<b>Macro SSOT</b><br><span class='tj-pill'>{context['regime']}</span>"
                    f"<span class='tj-pill'>Conf {float(regime_snapshot.get('confidence', 0.0) or 0.0):.0%}</span>"
                    f"<span class='tj-pill'>Score {float(regime_snapshot.get('final_score', 0.0) or 0.0):+.2f}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
            probs = regime_snapshot.get("probabilities", {}) if isinstance(regime_snapshot, dict) else {}
            e1, e2, e3 = st.columns(3)
            with e1:
                entry_regime_conf = st.number_input(
                    "Entry Regime Confidence",
                    min_value=0.0,
                    max_value=1.0,
                    value=float(regime_snapshot.get("confidence", 0.0) or 0.0) if isinstance(regime_snapshot, dict) else 0.0,
                    step=0.01,
                )
            with e2:
                entry_vol_ratio = st.number_input("Entry Vol Ratio", min_value=0.0, value=1.0, step=0.05)
            with e3:
                entry_rs_blend = st.number_input("Entry RS Blend", value=0.0, step=0.1)
            q1, q2, q3 = st.columns(3)
            with q1:
                entry_quality_score = st.number_input("Entry Quality Score (0-1)", min_value=0.0, max_value=1.0, value=0.5, step=0.01)
            with q2:
                entry_gate_status = st.selectbox("Entry Gate Status", ["PASS", "BLOCKED", "WATCH", "UNKNOWN"], index=0)
            with q3:
                planned_r_target = st.number_input("Planned R Target", min_value=0.0, value=2.0, step=0.25)
            invalidation = st.number_input(
                "Invalidation Price (Optional)",
                min_value=0.0,
                format="%.2f",
                value=max(0.0, pre_invalidation if pre_invalidation > 0 else pre_stop_loss),
                help="Price level where trade thesis is invalid."
            )

            # --- NEW FIELDS ---
            col1, col2 = st.columns(2)
            with col1:
                intent = st.selectbox("Trade Intent", 
                    ["Swing Breakout", "Pullback", "Mean Reversion", "Position", "Experimental", "Intraday"])
            with col2:
                chart_link = st.text_input("Chart / Screenshot Link", placeholder="TradingView or Imgur link")
            factor_context = st.multiselect(
                "Factor Context",
                ["Regime Risk On", "Regime Neutral", "Regime Risk Off", "Liquidity Improving", "Liquidity Tightening",
                 "Sector Strength", "Market Breadth Positive", "Market Breadth Weak", "High Volatility", "Event Risk"]
            )
            
            mistakes = st.multiselect("Mistake Tags (Leave empty if none)", 
                ["Early Entry", "Ignored Regime", "Oversized Position", "Chased Price", "No Stop Loss", "Emotional Entry"])
            
            notes = st.text_area("Notes", value=pre_notes, placeholder="Why this trade? What's the catalyst?")
            st.caption("Mode: Scanner invalidation is live; trade invalidation is locked at entry in Journal.")
            
        submitted = st.form_submit_button("💾 Save Trade")
        
        if submitted:
            # Determine final symbol
            final_symbol = custom_symbol if is_custom else selected_sym
            
            if final_symbol and entry_price > 0:
                final_invalidation = invalidation if invalidation > 0 else (stop_loss if stop_loss > 0 else 0.0)
                final_invalidation_pct = (((entry_price - final_invalidation) / entry_price) * 100 if final_invalidation > 0 and entry_price > 0 else 0.0)
                trigger_policy = pre_trigger_policy or "Close < Invalidation (locked) | gap exception as captured at entry"
                trade_id = _new_trade_id(final_symbol)
                side_txt = str(side).upper()
                risk_per_share = (entry_price - final_invalidation) if side_txt == "LONG" else (final_invalidation - entry_price)
                initial_risk_amt = max(risk_per_share * quantity, 0.0)
                prob_on = float(probs.get("risk_on", 0.0) or 0.0) if isinstance(probs, dict) else 0.0
                prob_neutral = float(probs.get("neutral", 0.0) or 0.0) if isinstance(probs, dict) else 0.0
                prob_off = float(probs.get("risk_off", 0.0) or 0.0) if isinstance(probs, dict) else 0.0
                entry = {
                    "Trade ID": trade_id,
                    "Date": date.strftime("%Y-%m-%d"),
                    "Symbol": final_symbol,
                    "Side": side,
                    "Entry Price": entry_price,
                    "Exit Price": 0.0,
                    "Quantity": quantity,
                    "Strategy": strategy,
                    "Setup Family": setup_family,
                    "Status": "OPEN",
                    "Notes": notes,
                    "Regime": context.get("regime", "Unknown"),
                    "Liquidity": context.get("liquidity", "Unknown"),
                    "Stance": context.get("stance", "Neutral"),
                    "Trade Intent": intent,
                    "Factor Context": ", ".join(factor_context) if factor_context else "",
                    "Invalidation": final_invalidation,
                    "Invalidation %": final_invalidation_pct,
                    "Mistake Tags": ", ".join(mistakes) if mistakes else "",
                    "Chart Link": chart_link,
                    "Exit Reason": "",
                    "Exit Date": "",
                    "Holding Days": 0,
                    "Outcome R": 0.0,
                    "Outcome Bucket": "",
                    "Invalidation Mode": "LOCKED_AT_ENTRY",
                    "Locked Invalidation": final_invalidation,
                    "Locked Invalidation %": final_invalidation_pct,
                    "Scanner Invalidation (At Entry)": final_invalidation,
                    "Trigger Policy": trigger_policy,
                    "Target Price": target if target > 0 else 0.0,
                    "Entry Risk %": final_invalidation_pct,
                    "Entry Risk (ATR)": pre_entry_risk_atr if pre_entry_risk_atr > 0 else 0.0,
                    "MFE %": 0.0,
                    "MAE %": 0.0,
                    "Bars to Invalidation": 0,
                    "Bars to Target": 0,
                    "Hit Invalidation First": "",
                    "Hit Target First": "",
                    "Path Metrics Source": "",
                    "Remaining Quantity": int(quantity),
                    "Entry Regime Confidence": float(entry_regime_conf),
                    "Entry RiskOn Prob": prob_on,
                    "Entry Neutral Prob": prob_neutral,
                    "Entry RiskOff Prob": prob_off,
                    "Entry Quality Score": float(entry_quality_score),
                    "Entry Gate Status": str(entry_gate_status),
                    "Entry Vol Ratio": float(entry_vol_ratio),
                    "Entry RS Blend": float(entry_rs_blend),
                    "Initial Risk Amount": float(initial_risk_amt),
                    "Planned R Target": float(planned_r_target),
                    "Actual R": 0.0,
                    "Slippage R": 0.0,
                    "Exit Trigger": "",
                    "Exit Quality": "",
                }
                save_entry(entry)
                save_leg(
                    {
                        "Trade ID": trade_id,
                        "Leg Type": "ENTRY",
                        "Date": date.strftime("%Y-%m-%d"),
                        "Price": float(entry_price),
                        "Quantity": int(quantity),
                        "Notes": str(notes or ""),
                    }
                )
                st.success(f"✅ Trade logged for {final_symbol}")
            else:
                st.error("⚠️ Please enter at least a Symbol and Entry Price.")

# ==================== VIEW HISTORY ====================
elif page_mode == "View History":
    st.subheader("📜 Trade History")
    
    df = load_journal()
    
    if not df.empty:
        st.markdown("### 🔍 Filter & Analyze")
        st.markdown(
            "<div class='tj-card'><span class='tj-pill tj-open'>OPEN</span>"
            "<span class='tj-pill tj-closed'>CLOSED</span>"
            "<span class='tj-muted'>Live P&L updates for open trades, full diagnostics for closed trades.</span></div>",
            unsafe_allow_html=True,
        )
        
        # Formatting for display
        display_df = df.copy()
        
        # Filter options
        filter_status = st.multiselect("Filter by Status", ["OPEN", "CLOSED"], default=["OPEN", "CLOSED"])
        if filter_status:
            display_df = display_df[display_df["Status"].isin(filter_status)]

        # LTP and Unrealized P&L for Open Trades
        open_indices = display_df[display_df["Status"] == "OPEN"].index
        if not open_indices.empty:
            open_symbols = display_df.loc[open_indices, "Symbol"].unique().tolist()
            with st.spinner("🔄 Fetching current prices..."):
                current_data = batch_download(open_symbols, period="1d")
                
            prices = {}
            for sym in open_symbols:
                price, _, _ = extract_price_data(current_data.get(sym))
                if price:
                    prices[sym] = price

            def get_ltp(row):
                if row["Status"] == "OPEN":
                    return prices.get(row["Symbol"], 0.0)
                return 0.0

            def calculate_unrealized(row):
                if row["Status"] == "OPEN":
                    ltp = prices.get(row["Symbol"])
                    if ltp:
                        if row["Side"] == "LONG":
                            return (ltp - row["Entry Price"]) * row["Quantity"]
                        else:
                            return (row["Entry Price"] - ltp) * row["Quantity"]
                return 0.0

            display_df["LTP"] = display_df.apply(get_ltp, axis=1)
            display_df["Unrealized P&L"] = display_df.apply(calculate_unrealized, axis=1)

            if GIFT_NIFTY_INV_PREFLAG and is_gift_session_active(
                session_start_hour=GIFT_NIFTY_SESSION_START_IST_HOUR,
                cutoff_hour=GIFT_NIFTY_COLLAPSE_IST_HOUR,
            ):
                prev_close = None
                try:
                    ndf = batch_download(["^NSEI"], period="5d").get("^NSEI")
                    if ndf is not None and not ndf.empty and "Close" in ndf.columns:
                        nclose = pd.to_numeric(ndf["Close"], errors="coerce").dropna()
                        if len(nclose) >= 1:
                            prev_close = float(nclose.iloc[-1])
                except Exception:
                    prev_close = None

                gift = get_gift_nifty_snapshot(prev_nifty_close=prev_close)
                prem = gift.get("premium_pct_vs_prev_close")
                if gift.get("available", False) and prem is not None:
                    alerts = []
                    open_only = display_df[display_df["Status"] == "OPEN"].copy()
                    for _, r in open_only.iterrows():
                        side = str(r.get("Side", "")).upper()
                        entry = _to_float(r.get("Entry Price", 0.0), 0.0)
                        inv = _to_float(r.get("Locked Invalidation", r.get("Invalidation", 0.0)), 0.0)
                        risk_atr = _to_float(r.get("Entry Risk (ATR)", 0.0), 0.0)
                        if entry <= 0 or inv <= 0:
                            continue
                        implied_open = entry * (1.0 + float(prem) / 100.0)  # Index-implied approximation
                        gap_buffer = (0.25 * risk_atr) if risk_atr > 0 else (0.0025 * entry)
                        long_breach = side == "LONG" and implied_open < (inv - gap_buffer)
                        short_breach = side == "SHORT" and implied_open > (inv + gap_buffer)
                        if long_breach or short_breach:
                            alerts.append(
                                {
                                    "Symbol": r.get("Symbol"),
                                    "Side": side,
                                    "Entry": round(entry, 2),
                                    "Locked Inv": round(inv, 2),
                                    "Implied Open (Index-Based)": round(implied_open, 2),
                                    "Gap Buffer": round(gap_buffer, 2),
                                    "Trigger Risk": "Likely Breach",
                                }
                            )
                    if alerts:
                        delay_txt = "N/A"
                        if gift.get("delay_min") is not None:
                            delay_txt = f"{float(gift.get('delay_min')):.0f} min"
                        st.warning(
                            f"Pre-market invalidation risk: GIFT NIFTY {float(prem):+.2f}% "
                            f"({gift.get('implied_label','Unknown')}) suggests possible gap-trigger breaches."
                        )
                        st.caption(
                            f"As of: {gift.get('as_of_ist','N/A')} | Delay: {delay_txt} | "
                            "Index-implied approximation; stock-level gaps may vary."
                        )
                        if gift.get("unverified", False):
                            st.warning("GIFT source is scrape-based (unverified). Alert is informational only.")
                        if gift.get("quality_note"):
                            st.caption(f"Normalization: {gift.get('quality_note')}")
                        st.dataframe(pd.DataFrame(alerts), width="stretch", hide_index=True)

        # Reorder columns for better view
        cols = display_df.columns.tolist()
        if "Unrealized P&L" in cols:
            # Move LTP and P&L after Entry Price
            entry_idx = cols.index("Entry Price")
            for col in ["LTP", "Unrealized P&L"]:
                if col in cols: # Ensure column exists before trying to remove/insert
                    cols.remove(col)
                    cols.insert(entry_idx + 1, col)
                    entry_idx += 1
        
        if view_mode == "Summary":
            display_df = display_df.sort_values("Date", ascending=False).head(200)

        if "Unrealized P&L" in display_df.columns:
            styled = display_df[cols].style.map(
                lambda x: "color: #00AA00" if isinstance(x, (int, float)) and x > 0 else ("color: #CC0000" if isinstance(x, (int, float)) and x < 0 else ""),
                subset=["Unrealized P&L"]
            )
            st.dataframe(styled, width="stretch", hide_index=True)
        else:
            st.dataframe(display_df[cols], width="stretch", hide_index=True)

        with st.expander("🧾 Trade Legs (Entry/Exit/Pyramid)", expanded=False):
            legs = load_legs()
            if legs.empty:
                st.info("No trade legs recorded yet.")
            else:
                st.dataframe(
                    legs.sort_values(["Date", "Trade ID"], ascending=[False, True]).head(500),
                    width="stretch",
                    hide_index=True,
                )

        with st.expander("🧪 Data Integrity Checks", expanded=False):
            checks = []
            tmp = df.copy()
            for i, r in tmp.iterrows():
                side_txt = str(r.get("Side", "")).upper()
                entry_px = _to_float(r.get("Entry Price", 0.0))
                exit_px = _to_float(r.get("Exit Price", 0.0))
                qty = _to_float(r.get("Quantity", 0.0))
                inv = _to_float(r.get("Locked Invalidation", r.get("Invalidation", 0.0)))
                if entry_px <= 0:
                    checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "Entry <= 0"})
                if qty <= 0:
                    checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "Quantity <= 0"})
                if side_txt == "LONG" and inv > 0 and inv >= entry_px:
                    checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "LONG invalidation >= entry"})
                if side_txt == "SHORT" and inv > 0 and inv <= entry_px:
                    checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "SHORT invalidation <= entry"})
                if str(r.get("Status", "")).upper() == "CLOSED" and exit_px <= 0:
                    checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "Closed trade missing exit price"})
                try:
                    d0 = pd.to_datetime(r.get("Date"))
                    d1 = pd.to_datetime(r.get("Exit Date")) if str(r.get("Exit Date", "")).strip() else None
                    if d1 is not None and d1 < d0:
                        checks.append({"Trade ID": r.get("Trade ID", i), "Issue": "Exit date before entry date"})
                except Exception:
                    pass
            if checks:
                st.warning(f"{len(checks)} integrity issue(s) found.")
                st.dataframe(pd.DataFrame(checks), width="stretch", hide_index=True)
            else:
                st.success("No integrity issues found in current journal rows.")
        
        # Close Trade UI
        st.markdown("### 🔒 Close a Trade")
        open_trades = df[df["Status"] == "OPEN"]
        legs_df = load_legs()
        
        if not open_trades.empty:
            # Display open trades for selection
            for idx, row in open_trades.iterrows():
                trade_id = str(row.get("Trade ID", ""))
                remaining_qty = _to_int(row.get("Remaining Quantity", row.get("Quantity", 0)), 0)
                st.markdown(
                    "<div class='tj-card'>"
                    f"<b>{row['Symbol']}</b> ({row['Side']})<br>"
                    f"<span class='tj-pill'>Trade ID {trade_id}</span>"
                    f"<span class='tj-pill'>Entry {float(_to_float(row['Entry Price'], 0.0)):.2f}</span>"
                    f"<span class='tj-pill'>Rem Qty {remaining_qty}</span>"
                    "</div>",
                    unsafe_allow_html=True,
                )
                with st.form(f"close_trade_form_{idx}"):
                    exit_price = st.number_input(f"Exit Price for {row['Symbol']}", value=float(row['Entry Price']), key=f"exit_{idx}")
                    close_qty = st.number_input(
                        "Exit Quantity",
                        min_value=1,
                        max_value=max(1, remaining_qty),
                        value=max(1, min(remaining_qty, _to_int(remaining_qty))),
                        step=1,
                        key=f"close_qty_{idx}",
                    )
                    exit_reason = st.selectbox("Exit Reason", 
                        ["Target Hit", "Stop Loss", "Regime Change", "Weak Sector", "Discretionary", "Time Exit"],
                        key=f"reason_{idx}")
                    exit_trigger = st.selectbox(
                        "Exit Trigger",
                        ["Price Trigger", "Time Stop", "Regime Flip", "Manual Override", "Risk Cut", "Partial Profit"],
                        key=f"trigger_{idx}",
                    )
                    exit_quality = st.selectbox(
                        "Exit Quality",
                        ["Good", "Early", "Late", "Forced", "Unknown"],
                        key=f"exit_quality_{idx}",
                    )
                    close_notes = st.text_area("Closing Notes (Lessons)", key=f"notes_{idx}")
                    
                    if st.form_submit_button(f"Confirm Close {row['Symbol']}", key=f"conf_{idx}"):
                        now_dt = datetime.now().strftime("%Y-%m-%d")
                        close_qty = int(close_qty)
                        new_remaining = max(0, remaining_qty - close_qty)
                        df.at[idx, "Remaining Quantity"] = new_remaining
                        df.at[idx, "Exit Reason"] = exit_reason
                        df.at[idx, "Exit Trigger"] = exit_trigger
                        df.at[idx, "Exit Quality"] = exit_quality
                        save_leg(
                            {
                                "Trade ID": trade_id,
                                "Leg Type": "EXIT",
                                "Date": now_dt,
                                "Price": float(exit_price),
                                "Quantity": int(close_qty),
                                "Notes": str(close_notes or exit_reason),
                            }
                        )

                        if close_notes:
                            existing_notes = df.at[idx, "Notes"]
                            existing_notes = "" if pd.isna(existing_notes) else str(existing_notes)
                            sep = " | " if existing_notes else ""
                            df.at[idx, "Notes"] = f"{existing_notes}{sep}Exit: {close_notes}"

                        if new_remaining > 0:
                            df.to_csv(JOURNAL_FILE, index=False)
                            st.success(f"Recorded partial exit for {row['Symbol']} (qty {close_qty}). Remaining {new_remaining}.")
                            st.rerun()

                        trade_legs = load_legs()
                        exits = trade_legs[
                            (trade_legs["Trade ID"].astype(str) == trade_id) &
                            (trade_legs["Leg Type"].astype(str).str.upper() == "EXIT")
                        ].copy()
                        exit_qty_total = pd.to_numeric(exits["Quantity"], errors="coerce").fillna(0).sum()
                        if exit_qty_total > 0:
                            weighted_exit = (
                                (pd.to_numeric(exits["Price"], errors="coerce").fillna(0.0) *
                                 pd.to_numeric(exits["Quantity"], errors="coerce").fillna(0.0)).sum()
                                / float(exit_qty_total)
                            )
                        else:
                            weighted_exit = float(exit_price)

                        df.at[idx, "Exit Price"] = float(weighted_exit)
                        df.at[idx, "Status"] = "CLOSED"
                        df.at[idx, "Exit Date"] = now_dt

                        try:
                            entry_dt = pd.to_datetime(df.at[idx, "Date"])
                            exit_dt = pd.to_datetime(df.at[idx, "Exit Date"])
                            holding_days = max(int((exit_dt - entry_dt).days), 0)
                        except Exception:
                            holding_days = 0
                        df.at[idx, "Holding Days"] = holding_days

                        entry_px = _to_float(df.at[idx, "Entry Price"], 0.0)
                        qty = _to_float(df.at[idx, "Quantity"], 0.0)
                        side_txt = str(df.at[idx, "Side"]).upper()
                        pnl = ((weighted_exit - entry_px) * qty) if side_txt == "LONG" else ((entry_px - weighted_exit) * qty)

                        locked_invalidation = _to_float(df.at[idx, "Locked Invalidation"], 0.0)
                        invalidation = locked_invalidation if locked_invalidation > 0 else _to_float(df.at[idx, "Invalidation"], 0.0)
                        if invalidation > 0 and entry_px > 0 and qty > 0:
                            risk_per_share = (entry_px - invalidation) if side_txt == "LONG" else (invalidation - entry_px)
                            risk_amt = max(risk_per_share * qty, 0.0)
                            outcome_r = (pnl / risk_amt) if risk_amt > 0 else 0.0
                        else:
                            risk_amt = _to_float(df.at[idx, "Initial Risk Amount"], 0.0)
                            outcome_r = (pnl / risk_amt) if risk_amt > 0 else 0.0
                        df.at[idx, "Outcome R"] = outcome_r
                        df.at[idx, "Actual R"] = outcome_r

                        if invalidation > 0 and entry_px > 0:
                            if side_txt == "LONG":
                                theoretical_stop_pnl = ((invalidation - entry_px) * qty)
                            else:
                                theoretical_stop_pnl = ((entry_px - invalidation) * qty)
                            slippage_r = ((pnl - theoretical_stop_pnl) / risk_amt) if risk_amt > 0 else 0.0
                            df.at[idx, "Slippage R"] = slippage_r

                        if outcome_r >= 2:
                            bucket = "Strong Win"
                        elif outcome_r > 0:
                            bucket = "Win"
                        elif outcome_r <= -1:
                            bucket = "Full Loss"
                        elif outcome_r < 0:
                            bucket = "Loss"
                        else:
                            bucket = "Flat"
                        df.at[idx, "Outcome Bucket"] = bucket
                        target_px = _to_float(df.at[idx, "Target Price"], 0.0)
                        try:
                            path = compute_path_metrics(
                                symbol=str(df.at[idx, "Symbol"]),
                                side=side_txt,
                                entry_price=entry_px,
                                invalidation=invalidation,
                                target_price=target_px,
                                entry_dt=pd.to_datetime(df.at[idx, "Date"]),
                                exit_dt=pd.to_datetime(df.at[idx, "Exit Date"]),
                            )
                            df.at[idx, "MFE %"] = float(path.get("mfe_pct", 0.0))
                            df.at[idx, "MAE %"] = float(path.get("mae_pct", 0.0))
                            df.at[idx, "Bars to Invalidation"] = int(path.get("bars_to_invalidation", 0))
                            df.at[idx, "Bars to Target"] = int(path.get("bars_to_target", 0))
                            df.at[idx, "Hit Invalidation First"] = str(path.get("hit_invalidation_first", "No"))
                            df.at[idx, "Hit Target First"] = str(path.get("hit_target_first", "No"))
                            df.at[idx, "Path Metrics Source"] = str(path.get("path_source", "NONE"))
                        except Exception:
                            df.at[idx, "Path Metrics Source"] = "ERROR"

                        df.to_csv(JOURNAL_FILE, index=False)
                        st.success(f"Closed {row['Symbol']} with weighted exit {weighted_exit:.2f}")
                        st.rerun()
            with st.expander("➕ Add Pyramid Entry Leg", expanded=False):
                pyr_options = {
                    f"{r['Trade ID']} | {r['Symbol']} | RemQty {int(_to_int(r.get('Remaining Quantity', r.get('Quantity', 0))))}": i
                    for i, r in open_trades.iterrows()
                }
                if pyr_options:
                    pyr_pick = st.selectbox("Open Trade", options=list(pyr_options.keys()))
                    pyr_idx = pyr_options[pyr_pick]
                    pyr_row = open_trades.loc[pyr_idx]
                    p_col1, p_col2, p_col3 = st.columns(3)
                    with p_col1:
                        pyr_qty = st.number_input("Add Quantity", min_value=1, value=1, step=1, key=f"pyr_qty_{pyr_idx}")
                    with p_col2:
                        pyr_price = st.number_input("Add Price", min_value=0.0, value=float(_to_float(pyr_row.get("Entry Price", 0.0))), step=0.5, key=f"pyr_px_{pyr_idx}")
                    with p_col3:
                        if st.button("Add Pyramid Leg", key=f"pyr_btn_{pyr_idx}", use_container_width=True):
                            old_qty = _to_float(df.at[pyr_idx, "Quantity"], 0.0)
                            old_entry = _to_float(df.at[pyr_idx, "Entry Price"], 0.0)
                            add_qty = float(pyr_qty)
                            new_qty = old_qty + add_qty
                            new_entry = ((old_entry * old_qty) + (float(pyr_price) * add_qty)) / new_qty if new_qty > 0 else old_entry
                            df.at[pyr_idx, "Quantity"] = new_qty
                            df.at[pyr_idx, "Remaining Quantity"] = _to_float(df.at[pyr_idx, "Remaining Quantity"], old_qty) + add_qty
                            df.at[pyr_idx, "Entry Price"] = new_entry
                            save_leg(
                                {
                                    "Trade ID": str(df.at[pyr_idx, "Trade ID"]),
                                    "Leg Type": "ENTRY",
                                    "Date": datetime.now().strftime("%Y-%m-%d"),
                                    "Price": float(pyr_price),
                                    "Quantity": int(pyr_qty),
                                    "Notes": "Pyramid entry",
                                }
                            )
                            df.to_csv(JOURNAL_FILE, index=False)
                            st.success("Pyramid leg added and weighted entry updated.")
                            st.rerun()
        else:
            st.info("No open trades to close.")
            
    else:
        st.info("No trades logged yet. Go to 'Log New Trade' to start.")

# ==================== PERFORMANCE STATS ====================
elif page_mode == "Performance Stats":
    st.subheader("📊 Performance Statistics")
    
    df = load_journal()
    closed_trades = df[df["Status"] == "CLOSED"].copy()
    
    if not closed_trades.empty:
        # Calculate P&L
        # Long: (Exit - Entry) * Qty
        # Short: (Entry - Exit) * Qty
        
        def calculate_pnl(row):
            if row["Side"] == "LONG":
                return (row["Exit Price"] - row["Entry Price"]) * row["Quantity"]
            else:
                return (row["Entry Price"] - row["Exit Price"]) * row["Quantity"]
        
        closed_trades["PnL"] = closed_trades.apply(calculate_pnl, axis=1)
        
        total_pnl = closed_trades["PnL"].sum()
        win_rate = (len(closed_trades[closed_trades["PnL"] > 0]) / len(closed_trades)) * 100
        
        col1, col2, col3, col4 = st.columns(4)
        
        # Open P&L Calculation
        open_trades = df[df["Status"] == "OPEN"]
        total_unrealized = 0.0
        if not open_trades.empty:
            open_symbols = open_trades["Symbol"].unique().tolist()
            current_data = batch_download(open_symbols, period="1d")
            for _, row in open_trades.iterrows():
                price, _, _ = extract_price_data(current_data.get(row["Symbol"]))
                if price:
                    if row["Side"] == "LONG":
                        total_unrealized += (price - row["Entry Price"]) * row["Quantity"]
                    else:
                        total_unrealized += (row["Entry Price"] - price) * row["Quantity"]

        with col1:
            st.metric("Total Realized P&L", f"₹{total_pnl:.2f}", delta_color="normal")
            
        with col2:
            st.metric("Total Unrealized P&L", f"₹{total_unrealized:.2f}", 
                      delta=f"{total_unrealized:.2f}",
                      delta_color="normal")
            
        with col3:
            st.metric("Win Rate", f"{win_rate:.1f}%")
            
        with col4:
            st.metric("Total Trades", len(closed_trades))
            
        st.markdown("### 📈 Recent Performance")
        st.bar_chart(closed_trades["PnL"])

        # Expectancy slicing
        closed_trades["Holding Days"] = pd.to_numeric(closed_trades["Holding Days"], errors="coerce").fillna(0).astype(int)
        closed_trades["Outcome R"] = pd.to_numeric(closed_trades["Outcome R"], errors="coerce").fillna(0.0)
        closed_trades["Holding Bucket"] = pd.cut(
            closed_trades["Holding Days"],
            bins=[-1, 2, 7, 21, 10000],
            labels=["0-2D", "3-7D", "8-21D", "22D+"]
        )

        def summarize_expectancy(df_in: pd.DataFrame, group_col: str) -> pd.DataFrame:
            if df_in.empty or group_col not in df_in.columns:
                return pd.DataFrame()
            out = (
                df_in.groupby(group_col, dropna=False)
                .agg(
                    Trades=("PnL", "count"),
                    WinRate=("PnL", lambda s: (s > 0).mean() * 100),
                    AvgPnL=("PnL", "mean"),
                    ExpectancyR=("Outcome R", "mean"),
                )
                .reset_index()
            )
            return out.sort_values("ExpectancyR", ascending=False)

        by_setup = summarize_expectancy(closed_trades, "Setup Family")
        by_regime = summarize_expectancy(closed_trades, "Regime")
        by_holding = summarize_expectancy(closed_trades, "Holding Bucket")
        closed_trades["Entry Regime Confidence"] = pd.to_numeric(
            closed_trades.get("Entry Regime Confidence", 0.0), errors="coerce"
        ).fillna(0.0)
        closed_trades["Confidence Bucket"] = pd.cut(
            closed_trades["Entry Regime Confidence"],
            bins=[-0.001, 0.39, 0.64, 1.0],
            labels=["Low", "Medium", "High"],
        )
        by_conf = summarize_expectancy(closed_trades, "Confidence Bucket")
        if view_mode == "Detail":
            st.markdown("### 🧩 Performance Slicing")
            s1, s2, s3, s4 = st.columns(4)
            with s1:
                st.write("**By Setup Family**")
                if not by_setup.empty:
                    st.dataframe(
                        by_setup.assign(
                            WinRate=by_setup["WinRate"].map(lambda x: f"{x:.1f}%"),
                            AvgPnL=by_setup["AvgPnL"].map(lambda x: f"₹{x:,.0f}"),
                            ExpectancyR=by_setup["ExpectancyR"].map(lambda x: f"{x:.2f}")
                        ),
                        width="stretch",
                        hide_index=True
                    )
            with s2:
                st.write("**By Regime at Entry**")
                if not by_regime.empty:
                    st.dataframe(
                        by_regime.assign(
                            WinRate=by_regime["WinRate"].map(lambda x: f"{x:.1f}%"),
                            AvgPnL=by_regime["AvgPnL"].map(lambda x: f"₹{x:,.0f}"),
                            ExpectancyR=by_regime["ExpectancyR"].map(lambda x: f"{x:.2f}")
                        ),
                        width="stretch",
                        hide_index=True
                    )
            with s3:
                st.write("**By Holding Period**")
                if not by_holding.empty:
                    st.dataframe(
                        by_holding.assign(
                            WinRate=by_holding["WinRate"].map(lambda x: f"{x:.1f}%"),
                            AvgPnL=by_holding["AvgPnL"].map(lambda x: f"₹{x:,.0f}"),
                            ExpectancyR=by_holding["ExpectancyR"].map(lambda x: f"{x:.2f}")
                        ),
                        width="stretch",
                        hide_index=True
                    )
            with s4:
                st.write("**By Regime Confidence**")
                if not by_conf.empty:
                    st.dataframe(
                        by_conf.assign(
                            WinRate=by_conf["WinRate"].map(lambda x: f"{x:.1f}%"),
                            AvgPnL=by_conf["AvgPnL"].map(lambda x: f"₹{x:,.0f}"),
                            ExpectancyR=by_conf["ExpectancyR"].map(lambda x: f"{x:.2f}")
                        ),
                        width="stretch",
                        hide_index=True
                    )

        st.markdown("### 📚 Setup Scorecards")
        for fam in ["Momentum", "Pullback", "Volatility Contraction"]:
            sdf = closed_trades[closed_trades["Setup Family"].astype(str) == fam].copy()
            t1, t2, t3, t4, t5 = st.columns(5)
            if sdf.empty:
                t1.metric(f"{fam} Trades", 0)
                t2.metric("Win Rate", "N/A")
                t3.metric("Expectancy R", "N/A")
                t4.metric("Avg MAE", "N/A")
                t5.metric("Avg MFE", "N/A")
            else:
                t1.metric(f"{fam} Trades", int(len(sdf)))
                t2.metric("Win Rate", f"{((sdf['PnL'] > 0).mean()*100):.1f}%")
                t3.metric("Expectancy R", f"{pd.to_numeric(sdf['Outcome R'], errors='coerce').fillna(0.0).mean():.2f}")
                t4.metric("Avg MAE", f"{pd.to_numeric(sdf.get('MAE %', 0.0), errors='coerce').fillna(0.0).mean():.2f}%")
                t5.metric("Avg MFE", f"{pd.to_numeric(sdf.get('MFE %', 0.0), errors='coerce').fillna(0.0).mean():.2f}%")

        # Feedback loop suggestions
        st.markdown("### 🔁 Feedback Loop Suggestions")
        suggestions = []
        if not by_setup.empty:
            weak_setup = by_setup[by_setup["Trades"] >= 3].sort_values("ExpectancyR").head(1)
            if not weak_setup.empty and weak_setup["ExpectancyR"].iloc[0] < 0:
                suggestions.append(
                    f"Reduce weight on setup `{weak_setup['Setup Family'].iloc[0]}` (ExpectancyR {weak_setup['ExpectancyR'].iloc[0]:.2f})."
                )
        if not by_regime.empty:
            riskoff = by_regime[by_regime["Regime"].astype(str).str.contains("Risk Off", case=False, na=False)]
            if not riskoff.empty and riskoff["ExpectancyR"].iloc[0] < 0:
                suggestions.append("Avoid new discretionary longs in Risk Off regime; tighten checklist.")
        tag_counts = (
            closed_trades["Mistake Tags"]
            .fillna("")
            .str.split(",")
            .explode()
            .str.strip()
        )
        tag_counts = tag_counts[tag_counts != ""].value_counts()
        if not tag_counts.empty:
            suggestions.append(f"Most frequent mistake tag: `{tag_counts.index[0]}` ({int(tag_counts.iloc[0])} times).")

        if suggestions:
            for s in suggestions[:5]:
                st.write(f"- {s}")
        else:
            st.write("- Not enough evidence yet for robust suggestions.")

        st.markdown("### 👀 Review Queue")
        review = closed_trades.copy()
        review["Needs Review"] = (
            review["Notes"].fillna("").astype(str).str.len().lt(8) |
            review["Mistake Tags"].fillna("").astype(str).str.len().eq(0) |
            (pd.to_numeric(review.get("MAE %", 0.0), errors="coerce").fillna(0.0) > 8.0) |
            (pd.to_numeric(review.get("MFE %", 0.0), errors="coerce").fillna(0.0) > 20.0)
        )
        rq = review[review["Needs Review"]].copy()
        if not rq.empty:
            st.dataframe(
                rq[["Trade ID", "Date", "Symbol", "Setup Family", "Outcome R", "MAE %", "MFE %", "Notes", "Mistake Tags"]]
                .sort_values("Date", ascending=False)
                .head(50),
                width="stretch",
                hide_index=True,
            )
        else:
            st.success("No trades currently flagged for review.")

        st.markdown("### 🗓 Monthly Learning Summary")
        mdf = closed_trades.copy()
        mdf["Month"] = pd.to_datetime(mdf["Exit Date"], errors="coerce").dt.to_period("M").astype(str)
        month_opts = sorted([m for m in mdf["Month"].dropna().unique().tolist() if m and m != "NaT"], reverse=True)
        if month_opts:
            month_pick = st.selectbox("Select Month", options=month_opts)
            month_df = mdf[mdf["Month"] == month_pick].copy()
            if not month_df.empty:
                wr = (month_df["PnL"] > 0).mean() * 100
                exr = pd.to_numeric(month_df["Outcome R"], errors="coerce").fillna(0.0).mean()
                best_setup = month_df.groupby("Setup Family")["Outcome R"].mean().sort_values(ascending=False).head(1)
                weak_setup = month_df.groupby("Setup Family")["Outcome R"].mean().sort_values(ascending=True).head(1)
                st.write(f"- Trades: {len(month_df)} | Win rate: {wr:.1f}% | ExpectancyR: {exr:.2f}")
                if not best_setup.empty:
                    st.write(f"- Best setup: `{best_setup.index[0]}` ({best_setup.iloc[0]:.2f}R avg)")
                if not weak_setup.empty:
                    st.write(f"- Weakest setup: `{weak_setup.index[0]}` ({weak_setup.iloc[0]:.2f}R avg)")
                top_mistake = month_df["Mistake Tags"].fillna("").str.split(",").explode().str.strip()
                top_mistake = top_mistake[top_mistake != ""].value_counts()
                if not top_mistake.empty:
                    st.write(f"- Most common mistake: `{top_mistake.index[0]}` ({int(top_mistake.iloc[0])})")
        else:
            st.info("No closed trades with valid Exit Date for monthly summary.")
        
    else:
        st.info("No closed trades to analyze yet.")
