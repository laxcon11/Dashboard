import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import json
from NSE_Config import NIFTY_200
from data_fetch import batch_download, extract_price_data
from utils import setup_page, get_ui_detail_mode
import analytics


setup_page("Trading Journal")
view_mode = get_ui_detail_mode("Summary")

st.title("🚀 Trading Journal")
st.caption("Track your trades, analyze your performance, and refine your strategy.")

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
else:
    pre_symbol = _qp_scalar(query_params.get("symbol", ""), "")
    pre_strategy = _qp_scalar(query_params.get("strategy", "Swing Rank"), "Swing Rank")
    pre_side = _qp_scalar(query_params.get("side", "LONG"), "LONG")


# ==================== FILE HANDLING ====================
NOTES_DIR = Path("notes")
NOTES_DIR.mkdir(exist_ok=True)
JOURNAL_FILE = NOTES_DIR / "trading_journal.csv"
JOURNAL_META_FILE = NOTES_DIR / "trading_journal.meta.json"
JOURNAL_SCHEMA_VERSION = 2
JOURNAL_COLUMNS = [
    "Date", "Symbol", "Side", "Entry Price", "Exit Price", "Quantity", "Strategy", "Setup Family",
    "Status", "Notes", "Regime", "Liquidity", "Stance", "Trade Intent", "Factor Context",
    "Invalidation", "Invalidation %", "Mistake Tags", "Chart Link", "Exit Reason", "Exit Date",
    "Holding Days", "Outcome R", "Outcome Bucket"
]

def load_journal():
    if not JOURNAL_FILE.exists():
        return pd.DataFrame(columns=JOURNAL_COLUMNS)
    try:
        df = pd.read_csv(JOURNAL_FILE)
        for c in JOURNAL_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        # Ensure numeric fields remain numeric-friendly
        for nc in ["Entry Price", "Exit Price", "Quantity", "Invalidation", "Invalidation %", "Holding Days", "Outcome R"]:
            df[nc] = pd.to_numeric(df[nc], errors="coerce").fillna(0.0)
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

def save_entry(entry):
    df = load_journal()
    new_row = pd.DataFrame([entry])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(JOURNAL_FILE, index=False)
    return df

# ==================== SIDEBAR ====================
st.sidebar.header("Navigation")
page_mode = st.sidebar.radio("Go to", ["Log New Trade", "View History", "Performance Stats"])

# ==================== LOG NEW TRADE ====================
if page_mode == "Log New Trade":
    st.subheader("➕ Log a New Trade")
    
    with st.form("trade_form"):
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
            setup_family = st.selectbox("Setup Family", ["Momentum", "Pullback", "Volatility Contraction", "Breakout", "Mean Reversion", "Other"])
        
        with col2:
            entry_price = st.number_input("Entry Price", min_value=0.0, format="%.2f")
            quantity = st.number_input("Quantity", min_value=1, step=1)
            stop_loss = st.number_input("Stop Loss (Optional)", min_value=0.0, format="%.2f")
            target = st.number_input("Target (Optional)", min_value=0.0, format="%.2f")
            # Auto-Capture Market Context
            context = analytics.get_current_context() # Future: pass actual data if available
            invalidation = st.number_input("Invalidation Price (Optional)", min_value=0.0, format="%.2f", help="Price level where trade thesis is invalid.")

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
            
            notes = st.text_area("Notes", placeholder="Why this trade? What's the catalyst?")
            
        submitted = st.form_submit_button("💾 Save Trade")
        
        if submitted:
            # Determine final symbol
            final_symbol = custom_symbol if is_custom else selected_sym
            
            if final_symbol and entry_price > 0:
                entry = {
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
                    "Invalidation": invalidation if invalidation > 0 else 0.0,
                    "Invalidation %": (((entry_price - invalidation) / entry_price) * 100 if invalidation > 0 and entry_price > 0 else 0.0),
                    "Mistake Tags": ", ".join(mistakes) if mistakes else "",
                    "Chart Link": chart_link,
                    "Exit Reason": "",
                    "Exit Date": "",
                    "Holding Days": 0,
                    "Outcome R": 0.0,
                    "Outcome Bucket": "",
                }
                save_entry(entry)
                st.success(f"✅ Trade logged for {final_symbol}")
            else:
                st.error("⚠️ Please enter at least a Symbol and Entry Price.")

# ==================== VIEW HISTORY ====================
elif page_mode == "View History":
    st.subheader("📜 Trade History")
    
    df = load_journal()
    
    if not df.empty:
        st.markdown("### 🔍 Filter & Analyze")
        
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
        
        # Close Trade UI
        st.markdown("### 🔒 Close a Trade")
        open_trades = df[df["Status"] == "OPEN"]
        
        if not open_trades.empty:
            # Display open trades for selection
            for idx, row in open_trades.iterrows():
                st.write(f"**Trade ID:** {idx} | **Symbol:** {row['Symbol']} | **Side:** {row['Side']} | **Entry:** {row['Entry Price']}")
                with st.form(f"close_trade_form_{idx}"):
                    exit_price = st.number_input(f"Exit Price for {row['Symbol']}", value=float(row['Entry Price']), key=f"exit_{idx}")
                    exit_reason = st.selectbox("Exit Reason", 
                        ["Target Hit", "Stop Loss", "Regime Change", "Weak Sector", "Discretionary", "Time Exit"],
                        key=f"reason_{idx}")
                    close_notes = st.text_area("Closing Notes (Lessons)", key=f"notes_{idx}")
                    
                    if st.form_submit_button(f"Confirm Close {row['Symbol']}", key=f"conf_{idx}"):
                        df.at[idx, 'Exit Price'] = exit_price
                        df.at[idx, 'Status'] = 'CLOSED'
                        df.at[idx, 'Exit Reason'] = exit_reason
                        df.at[idx, 'Exit Date'] = datetime.now().strftime("%Y-%m-%d")

                        # Holding period + R multiple outcome
                        try:
                            entry_dt = pd.to_datetime(df.at[idx, 'Date'])
                            exit_dt = pd.to_datetime(df.at[idx, 'Exit Date'])
                            holding_days = max(int((exit_dt - entry_dt).days), 0)
                        except Exception:
                            holding_days = 0
                        df.at[idx, 'Holding Days'] = holding_days

                        entry_px = float(df.at[idx, 'Entry Price']) if pd.notna(df.at[idx, 'Entry Price']) else 0.0
                        qty = float(df.at[idx, 'Quantity']) if pd.notna(df.at[idx, 'Quantity']) else 0.0
                        side_txt = str(df.at[idx, 'Side']).upper()
                        pnl = ((exit_price - entry_px) * qty) if side_txt == "LONG" else ((entry_px - exit_price) * qty)

                        invalidation = float(df.at[idx, 'Invalidation']) if pd.notna(df.at[idx, 'Invalidation']) else 0.0
                        if invalidation > 0 and entry_px > 0 and qty > 0:
                            risk_per_share = (entry_px - invalidation) if side_txt == "LONG" else (invalidation - entry_px)
                            risk_amt = max(risk_per_share * qty, 0.0)
                            outcome_r = (pnl / risk_amt) if risk_amt > 0 else 0.0
                        else:
                            outcome_r = 0.0
                        df.at[idx, 'Outcome R'] = outcome_r
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
                        df.at[idx, 'Outcome Bucket'] = bucket

                        if close_notes:
                            existing_notes = df.at[idx, 'Notes']
                            existing_notes = "" if pd.isna(existing_notes) else str(existing_notes)
                            sep = " | " if existing_notes else ""
                            df.at[idx, 'Notes'] = f"{existing_notes}{sep}Exit: {close_notes}"
                        df.to_csv(JOURNAL_FILE, index=False)
                        st.success(f"Closed {row['Symbol']} at {exit_price}")
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
        if view_mode == "Detail":
            st.markdown("### 🧩 Performance Slicing")
            s1, s2, s3 = st.columns(3)
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
        
    else:
        st.info("No closed trades to analyze yet.")
