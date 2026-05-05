import json
from pathlib import Path
from typing import Dict, Optional
import time
from contextlib import contextmanager

import numpy as np
import pandas as pd
import streamlit as st

from NSE_Config import SECTOR_CATEGORIES, FNO_DELTA_STOCKS, FNO_MOST_TRADED_30, NSE_SECTOR_INDICES
from data_fetch import batch_download, extract_price_data
from regime_state import load_regime_snapshot
from utils import setup_page, get_ui_detail_mode, get_ui_device_mode, make_page_diag_block


setup_page("Portfolio Risk")
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


def _compact_table(
    df: pd.DataFrame,
    mobile_cols: list[str] | None = None,
    rows_summary: int = 15,
    rows_detail: int = 30,
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

st.title("🛡 Portfolio Risk & Execution Control")
st.caption("Concentration, correlation, exposure, and pre-trade checks.")
st.caption(f"Device mode: **{device_mode}**")
_page_t0 = time.perf_counter()
_perf: dict[str, float] = {}

JOURNAL_FILE = Path("notes/trading_journal.csv")
RULES_FILE = Path("notes/portfolio_rules.json")
FNO_LOT_FILE = Path("notes/fno_lot_sizes.json")

EMOJI_REGIME_MAP = {
    "Risk On": "🟢 Risk On",
    "Selective": "🟡 Selective",
    "Defensive": "🟠 Defensive",
    "Crisis": "🔴 Crisis",
    "Unknown": "Unknown"
}

DEFAULT_RULES = {
    "max_concurrent_trades": 6,
    "max_sector_weight_pct": 35.0,
    "max_single_trade_risk_pct": 1.0,
    "regime_size_hints": {
        "🟢 Risk On": 1.0,
        "🟡 Selective": 0.65,
        "🟠 Defensive": 0.50,
        "🔴 Crisis": 0.25,
        "Unknown": 0.5,
    },
}

REQUIRED_JOURNAL_COLS = [
    "Symbol", "Status", "Side", "Quantity", "Entry Price", "Invalidation"
]

FNO_TRACKED_SYMBOLS = set(FNO_DELTA_STOCKS) | set(FNO_MOST_TRADED_30)


def normalize_symbol(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if not s:
        return s
    return s if s.endswith(".NS") else f"{s}.NS"


def default_qty_for_symbol(symbol: str) -> int:
    sym = normalize_symbol(symbol)
    lot = FNO_LOT_MAP.get(sym)
    if lot is not None and lot > 0:
        return int(lot)
    return 1 if sym in FNO_TRACKED_SYMBOLS else 100


@st.cache_data(ttl=300, show_spinner=False)
def fetch_cached_ltp(symbol: str) -> Optional[float]:
    data = batch_download([symbol], period="1mo")
    return extract_price_data(data.get(symbol))[0]


def load_fno_lot_map() -> dict[str, int]:
    if not FNO_LOT_FILE.exists():
        return {}
    try:
        payload = json.loads(FNO_LOT_FILE.read_text())
        lots = payload.get("lot_sizes", {})
        out: dict[str, int] = {}
        if isinstance(lots, dict):
            for k, v in lots.items():
                try:
                    iv = int(v)
                    if iv > 0:
                        out[normalize_symbol(k)] = iv
                except Exception:
                    continue
        return out
    except Exception:
        return {}


def load_journal() -> pd.DataFrame:
    if not JOURNAL_FILE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(JOURNAL_FILE)
        for col in REQUIRED_JOURNAL_COLS:
            if col not in df.columns:
                df[col] = 0.0 if col in {"Quantity", "Entry Price", "Invalidation"} else ""
        return df
    except Exception:
        return pd.DataFrame()


def load_rules() -> dict:
    if RULES_FILE.exists():
        try:
            payload = json.loads(RULES_FILE.read_text())
            merged = DEFAULT_RULES.copy()
            merged.update(payload)
            merged["regime_size_hints"] = {**DEFAULT_RULES["regime_size_hints"], **payload.get("regime_size_hints", {})}
            return merged
        except Exception:
            return DEFAULT_RULES.copy()
    return DEFAULT_RULES.copy()


def save_rules(rules: dict) -> None:
    RULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(rules, indent=2))


def build_symbol_sector_map() -> Dict[str, str]:
    mapper: Dict[str, str] = {}
    for sector_name, symbols in SECTOR_CATEGORIES.items():
        clean_name = sector_name.split(" ", 1)[-1] if " " in sector_name else sector_name
        for symbol in symbols:
            mapper[symbol] = clean_name
    return mapper


df = load_journal()
FNO_LOT_MAP = load_fno_lot_map()
if df.empty:
    st.info("No journal entries found yet. Log trades first to use portfolio controls.")
    st.stop()

open_trades = df[df.get("Status", "OPEN").astype(str).str.upper() == "OPEN"].copy()
if open_trades.empty:
    st.info("No open trades currently. Portfolio risk metrics require open positions.")
    st.stop()

rules = load_rules()

with st.expander("⚙️ Trade Budget Rules", expanded=True):
    c1, c2, c3 = _responsive_cols(3)
    with c1:
        rules["max_concurrent_trades"] = st.number_input(
            "Max Concurrent Trades", min_value=1, max_value=30, value=int(rules["max_concurrent_trades"]), step=1
        )
    with c2:
        rules["max_sector_weight_pct"] = st.slider(
            "Max Sector Concentration (%)", min_value=10.0, max_value=80.0, value=float(rules["max_sector_weight_pct"]), step=1.0
        )
    with c3:
        rules["max_single_trade_risk_pct"] = st.slider(
            "Max Single-Trade Risk (% of equity)", min_value=0.25, max_value=3.0, value=float(rules["max_single_trade_risk_pct"]), step=0.05
        )

    st.markdown("**Regime Size Hints**")
    r1, r2, r3, r4, r5 = _responsive_cols(5)
    rules["regime_size_hints"]["🟢 Risk On"] = r1.slider("Risk On", 0.25, 1.5, float(rules["regime_size_hints"].get("🟢 Risk On", 1.0)), 0.05)
    rules["regime_size_hints"]["🟡 Selective"] = r2.slider("Selective", 0.25, 1.5, float(rules["regime_size_hints"].get("🟡 Selective", 0.65)), 0.05)
    rules["regime_size_hints"]["🟠 Defensive"] = r3.slider("Defensive", 0.1, 1.0, float(rules["regime_size_hints"].get("🟠 Defensive", 0.50)), 0.05)
    rules["regime_size_hints"]["🔴 Crisis"] = r4.slider("Crisis", 0.05, 0.5, float(rules["regime_size_hints"].get("🔴 Crisis", 0.25)), 0.05)
    rules["regime_size_hints"]["Unknown"] = r5.slider("Unknown", 0.25, 1.0, float(rules["regime_size_hints"].get("Unknown", 0.5)), 0.05)

    if st.button("💾 Save Portfolio Rules"):
        save_rules(rules)
        st.success("Portfolio rules saved.")


symbols = sorted(open_trades["Symbol"].dropna().unique().tolist())
open_trades["Symbol_Norm"] = open_trades["Symbol"].map(normalize_symbol)
symbols_norm = sorted(open_trades["Symbol_Norm"].dropna().unique().tolist())
with st.spinner("Fetching live values and risk inputs..."):
    _t_fetch = time.perf_counter()
    mkt = batch_download(symbols_norm, period="6mo")
    _perf["data_fetch_s"] = round(time.perf_counter() - _t_fetch, 3)

prices = {}
for sym in symbols_norm:
    prices[sym] = extract_price_data(mkt.get(sym))[0]

open_trades["Quantity"] = pd.to_numeric(open_trades["Quantity"], errors="coerce").fillna(0.0)
open_trades = open_trades[open_trades["Quantity"] > 0].copy()
open_trades["LTP"] = open_trades["Symbol_Norm"].map(prices)
open_trades = open_trades[open_trades["LTP"].notna()].copy()
if open_trades.empty:
    st.warning("Could not fetch LTP for open trades.")
    st.stop()

open_trades["Notional"] = open_trades["LTP"] * pd.to_numeric(open_trades["Quantity"], errors="coerce").fillna(0.0)
open_trades["Signed Notional"] = np.where(open_trades["Side"].astype(str).str.upper() == "SHORT", -open_trades["Notional"], open_trades["Notional"])

sector_map = build_symbol_sector_map()
open_trades["Sector"] = open_trades["Symbol_Norm"].map(sector_map).fillna("Other")

total_gross = float(open_trades["Notional"].sum())
total_net = float(open_trades["Signed Notional"].sum())
long_notional = float(open_trades.loc[open_trades["Signed Notional"] > 0, "Signed Notional"].sum())
short_notional = abs(float(open_trades.loc[open_trades["Signed Notional"] < 0, "Signed Notional"].sum()))

col1, col2, col3, col4 = _responsive_cols(4)
col1.metric("Open Trades", int(len(open_trades)))
col2.metric("Gross Exposure", f"₹{total_gross:,.0f}")
col3.metric("Net Exposure", f"₹{total_net:,.0f}")
col4.metric("Directional Split", f"L {long_notional:,.0f} / S {short_notional:,.0f}")

st.markdown("### 🧭 Risk Dashboard")
left, right = _responsive_cols(2)

with left:
    # Fetch Sector Index Performance
    with st.spinner("Fetching sector index performance..."):
        index_symbols = list(NSE_SECTOR_INDICES.keys())
        index_data = batch_download(index_symbols, period="2d")
        sector_perf = {}
        for idx_sym, clean_label in NSE_SECTOR_INDICES.items():
            df_idx = index_data.get(idx_sym)
            if df_idx is not None and not df_idx.empty:
                prices = pd.to_numeric(df_idx["Close"], errors="coerce").dropna()
                if len(prices) >= 2:
                    perf = ((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2]) * 100.0
                    sector_perf[clean_label] = perf
                elif len(prices) == 1:
                    sector_perf[clean_label] = 0.0

    st.markdown("**Sector Concentration**")
    sector_df = (
        open_trades.groupby("Sector", as_index=False)["Notional"].sum()
        .sort_values("Notional", ascending=False)
    )
    sector_df["Weight %"] = np.where(total_gross > 0, sector_df["Notional"] / total_gross * 100.0, 0.0)
    
    # Add Sector Perf Column
    sector_df["Sector Perf (%)"] = sector_df["Sector"].map(sector_perf)
    
    st.dataframe(
        _compact_table(
            sector_df.assign(
                Notional=sector_df["Notional"].map(lambda x: f"₹{x:,.0f}"),
                **{
                    "Weight %": sector_df["Weight %"].map(lambda x: f"{x:.1f}%"),
                    "Sector Perf (%)": sector_df["Sector Perf (%)"].map(lambda x: f"{x:+.2f}%" if pd.notnull(x) else "N/A")
                }
            ),
            mobile_cols=["Sector", "Notional", "Weight %", "Sector Perf (%)"],
            rows_summary=12,
            rows_detail=20,
        ),
        use_container_width=True,
        hide_index=True,
    )

with right:
    st.markdown("**Directional Exposure by Sector**")
    exposure_df = (
        open_trades.groupby("Sector", as_index=False)["Signed Notional"].sum()
        .sort_values("Signed Notional", ascending=False)
    )
    st.bar_chart(exposure_df.set_index("Sector")["Signed Notional"], height=280)

with page_diag_block("🔗 Correlation & Beta Proxy"):
    ret_series = {}
    for sym in symbols_norm:
        d = mkt.get(sym)
        if d is None or d.empty or "Close" not in d.columns:
            continue
        c = pd.to_numeric(d["Close"], errors="coerce").dropna()
        if len(c) < 40:
            continue
        ret_series[sym] = c.pct_change().dropna()

    if len(ret_series) >= 3:
        ret_df = pd.DataFrame(ret_series).dropna()
        corr = ret_df.corr()
        if is_mobile:
            corr_show = _compact_table(corr.reset_index().rename(columns={"index": "Symbol"}), rows_summary=8, rows_detail=12)
            st.dataframe(corr_show, use_container_width=True, hide_index=True)
        else:
            st.dataframe(corr.style.background_gradient(cmap="RdYlGn_r"), use_container_width=True)

        if "^NSEI" not in mkt:
            mkt_idx = batch_download(["^NSEI"], period="6mo")
        else:
            mkt_idx = mkt
        ndf = mkt_idx.get("^NSEI")
        beta_rows = []
        if ndf is not None and not ndf.empty and "Close" in ndf.columns:
            bret = pd.to_numeric(ndf["Close"], errors="coerce").dropna().pct_change().dropna()
            for sym, sret in ret_series.items():
                joined = pd.concat([sret.rename("s"), bret.rename("b")], axis=1).dropna()
                if len(joined) < 30 or joined["b"].var() == 0:
                    continue
                beta = joined["s"].cov(joined["b"]) / joined["b"].var()
                beta_rows.append({"Symbol": sym, "Beta Proxy": beta})
        if beta_rows:
            beta_df = pd.DataFrame(beta_rows).sort_values("Beta Proxy", ascending=False)
            st.dataframe(
                _compact_table(
                    beta_df.assign(**{"Beta Proxy": beta_df["Beta Proxy"].map(lambda x: f"{x:.2f}")}),
                    mobile_cols=["Symbol", "Beta Proxy"],
                    rows_summary=12,
                    rows_detail=20,
                ),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("Not enough overlapping return history to compute stable correlation/beta matrix.")

st.markdown("### ✅ Trade Checklist Engine")
candidate_options = sorted(set(symbols_norm + list(sector_map.keys())))
regime_snapshot = st.session_state.get("macro_regime_snapshot") or load_regime_snapshot()
regime_options = ["🟢 Risk On", "🟡 Selective", "🟠 Defensive", "🔴 Crisis", "Unknown"]

raw_regime = str(regime_snapshot.get("regime_label", "Unknown")) if isinstance(regime_snapshot, dict) else "Unknown"
regime_default = EMOJI_REGIME_MAP.get(raw_regime, "Unknown")

if regime_default not in regime_options:
    regime_default = "Unknown"

if isinstance(regime_snapshot, dict) and regime_snapshot:
    prob = regime_snapshot.get("probabilities", {}) if isinstance(regime_snapshot.get("probabilities", {}), dict) else {}
    if view_mode == "Detail":
        st.caption(
            f"Macro SSOT: {regime_default} | "
            f"Confidence: {float(regime_snapshot.get('confidence', 0.0) or 0.0):.0%} | "
            f"Score: {float(regime_snapshot.get('final_score', 0.0) or 0.0):+.2f} | "
            f"P(On/S/D/C): {float(prob.get('risk_on', 0.0) or 0.0):.0%}/"
            f"{float(prob.get('selective', 0.0) or 0.0):.0%}/"
            f"{float(prob.get('defensive', 0.0) or 0.0):.0%}/"
            f"{float(prob.get('crisis', 0.0) or 0.0):.0%}"
        )

with st.form("trade_checklist_form", clear_on_submit=False):
    candidate_symbol = st.selectbox("Symbol", options=candidate_options)
    candidate_side = st.selectbox("Side", options=["LONG", "SHORT"])
    candidate_regime = st.selectbox(
        "Regime",
        options=regime_options,
        index=regime_options.index(regime_default),
    )
    portfolio_equity = st.number_input("Portfolio Equity (₹)", min_value=100000.0, value=1000000.0, step=50000.0)
    candidate_ltp = prices.get(candidate_symbol)
    if candidate_ltp is None:
        candidate_ltp = fetch_cached_ltp(candidate_symbol)
    entry_default = float(candidate_ltp) if candidate_ltp is not None and not pd.isna(candidate_ltp) else 100.0
    c_ltp_col, c_entry_col, c_stop_col = _responsive_cols(3)
    with c_ltp_col:
        st.metric("LTP", f"₹{entry_default:,.2f}" if entry_default > 0 else "N/A")
    with c_entry_col:
        entry = st.number_input("Entry", min_value=0.0, value=float(entry_default), step=0.5)
    with c_stop_col:
        stop_default = (entry * 0.975) if candidate_side == "LONG" else (entry * 1.025)
        stop = st.number_input("Stop", min_value=0.0, value=float(stop_default), step=0.5)
    submitted = st.form_submit_button("Run Checklist", use_container_width=True)

qty_key = "trade_checklist_qty"
sym_key = "trade_checklist_last_symbol"
norm_candidate_symbol = normalize_symbol(candidate_symbol)
desired_default_qty = default_qty_for_symbol(norm_candidate_symbol)

if qty_key not in st.session_state:
    st.session_state[qty_key] = desired_default_qty
if st.session_state.get(sym_key) != norm_candidate_symbol:
    st.session_state[qty_key] = desired_default_qty
    st.session_state[sym_key] = norm_candidate_symbol

qty = st.number_input("Quantity", min_value=1, step=1, key=qty_key)
if norm_candidate_symbol in FNO_TRACKED_SYMBOLS:
    lot_txt = FNO_LOT_MAP.get(norm_candidate_symbol)
    if lot_txt:
        st.caption(f"F&O lot default: {lot_txt}")
    else:
        st.caption("F&O lot size missing; default 1.")
else:
    st.caption("Cash symbol default: 100")

check_state_key = "trade_checklist_last_run"
if submitted or check_state_key not in st.session_state:
    st.session_state[check_state_key] = {
        "candidate_symbol": candidate_symbol,
        "candidate_side": candidate_side,
        "candidate_regime": candidate_regime,
        "portfolio_equity": float(portfolio_equity),
        "entry": float(entry),
        "stop": float(stop),
        "qty": int(qty),
    }

check_state = st.session_state.get(check_state_key, {})
candidate_symbol = check_state.get("candidate_symbol", candidate_symbol)
candidate_side = check_state.get("candidate_side", candidate_side)
candidate_regime = check_state.get("candidate_regime", candidate_regime)
portfolio_equity = float(check_state.get("portfolio_equity", portfolio_equity))
entry = float(check_state.get("entry", entry))
stop = float(check_state.get("stop", stop))
qty = int(check_state.get("qty", qty))

candidate_notional = entry * qty
candidate_sector = sector_map.get(normalize_symbol(candidate_symbol), "Other")
sector_existing = float(open_trades.loc[open_trades["Sector"] == candidate_sector, "Notional"].sum())
sector_after = sector_existing + candidate_notional
gross_after = total_gross + candidate_notional
sector_after_pct = (sector_after / portfolio_equity * 100.0) if portfolio_equity > 0 else 0.0

risk_per_share = max(entry - stop, 0.0) if candidate_side == "LONG" else max(stop - entry, 0.0)
trade_risk_amt = risk_per_share * qty
risk_pct_equity = (trade_risk_amt / portfolio_equity * 100.0) if portfolio_equity > 0 else 0.0

reasons = []
rule_rows = []
if len(open_trades) + 1 > int(rules["max_concurrent_trades"]):
    msg = f"Max concurrent trades exceeded ({len(open_trades)+1} > {int(rules['max_concurrent_trades'])})."
    reasons.append(msg)
    rule_rows.append({"Rule": "Max Concurrent Trades", "Status": "FAIL", "Depends On Symbol": "No", "Detail": msg})
else:
    rule_rows.append({"Rule": "Max Concurrent Trades", "Status": "PASS", "Depends On Symbol": "No", "Detail": f"{len(open_trades)+1} <= {int(rules['max_concurrent_trades'])}"})
if sector_after_pct > float(rules["max_sector_weight_pct"]):
    msg = f"Sector concentration breach ({sector_after_pct:.1f}% > {rules['max_sector_weight_pct']:.1f}%)."
    reasons.append(msg)
    rule_rows.append({"Rule": "Sector Concentration", "Status": "FAIL", "Depends On Symbol": "Yes", "Detail": msg})
else:
    rule_rows.append({"Rule": "Sector Concentration", "Status": "PASS", "Depends On Symbol": "Yes", "Detail": f"{sector_after_pct:.1f}% <= {rules['max_sector_weight_pct']:.1f}%"})
if risk_pct_equity > float(rules["max_single_trade_risk_pct"]):
    msg = f"Single-trade risk too high ({risk_pct_equity:.2f}% > {rules['max_single_trade_risk_pct']:.2f}%)."
    reasons.append(msg)
    rule_rows.append({"Rule": "Single-Trade Risk", "Status": "FAIL", "Depends On Symbol": "Partly", "Detail": msg})
else:
    rule_rows.append({"Rule": "Single-Trade Risk", "Status": "PASS", "Depends On Symbol": "Partly", "Detail": f"{risk_pct_equity:.2f}% <= {rules['max_single_trade_risk_pct']:.2f}%"})
if (candidate_regime == "🟠 Defensive" or candidate_regime == "🔴 Crisis") and candidate_side == "LONG":
    msg = f"{candidate_regime} policy restricts new long entries."
    reasons.append(msg)
    rule_rows.append({"Rule": "Regime Policy", "Status": "FAIL", "Depends On Symbol": "No", "Detail": msg})
else:
    rule_rows.append({"Rule": "Regime Policy", "Status": "PASS", "Depends On Symbol": "No", "Detail": f"{candidate_regime} / {candidate_side}"})

if candidate_side == "LONG":
    stop_valid = stop < entry
    validity_detail = f"LONG requires Stop < Entry ({stop:.2f} < {entry:.2f})"
else:
    stop_valid = stop > entry
    validity_detail = f"SHORT requires Stop > Entry ({stop:.2f} > {entry:.2f})"

if not stop_valid:
    msg = "Invalid entry/stop combination for selected side."
    reasons.append(msg)
    rule_rows.append({"Rule": "Entry/Stop Validity", "Status": "FAIL", "Depends On Symbol": "No", "Detail": validity_detail})
else:
    rule_rows.append({"Rule": "Entry/Stop Validity", "Status": "PASS", "Depends On Symbol": "No", "Detail": validity_detail})

if trade_risk_amt <= 0:
    msg = "Trade risk computed as zero; adjust Entry/Stop."
    reasons.append(msg)
    rule_rows.append({"Rule": "Non-zero Risk", "Status": "FAIL", "Depends On Symbol": "No", "Detail": msg})
else:
    rule_rows.append({"Rule": "Non-zero Risk", "Status": "PASS", "Depends On Symbol": "No", "Detail": f"₹{trade_risk_amt:,.2f}"})

size_hint = float(rules["regime_size_hints"].get(candidate_regime, rules["regime_size_hints"]["Unknown"]))
suggested_qty = int(max(1, qty * size_hint))

if reasons:
    st.error("Status: BLOCKED")
    for r in reasons:
        st.write(f"- {r}")
else:
    st.success("Status: ALLOWED")
    st.write("- Checklist passed for current portfolio rules.")

if view_mode == "Summary":
    st.caption(
        f"Sector: {candidate_sector} | Qty hint: {suggested_qty} | "
        f"Sector wt: {sector_after_pct:.1f}% | Risk: {risk_pct_equity:.2f}%"
    )
else:
    st.caption(
        f"Candidate sector: {candidate_sector} | Regime size hint: {size_hint:.2f}x | Suggested qty: {suggested_qty} | "
        f"Projected sector weight: {sector_after_pct:.1f}% of equity | Trade risk: {risk_pct_equity:.2f}% of equity | "
        f"Projected gross deployed: ₹{gross_after:,.0f}"
    )

with page_diag_block("Checklist Rule Breakdown"):
    if rule_rows:
        st.dataframe(
            _compact_table(
                pd.DataFrame(rule_rows),
                mobile_cols=["Rule", "Status", "Depends On Symbol"],
                rows_summary=10,
                rows_detail=20,
            ),
            use_container_width=True,
            hide_index=True,
        )

    symbol_independent_fails = [r["Rule"] for r in rule_rows if r["Status"] == "FAIL" and r["Depends On Symbol"] == "No"]
    if symbol_independent_fails:
        st.info(
            "Status may not change across symbols because these blockers are symbol-independent: "
            + ", ".join(symbol_independent_fails)
        )

_perf["checklist_eval_s"] = round(time.perf_counter() - _page_t0 - _perf.get("data_fetch_s", 0.0), 3)
_perf["total_page_s"] = round(time.perf_counter() - _page_t0, 3)
if st.sidebar.checkbox("Show Performance Diagnostics", value=False):
    st.sidebar.dataframe(
        pd.DataFrame([{"Step": k, "Seconds": v} for k, v in _perf.items()]),
        use_container_width=True,
        hide_index=True,
    )
