import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
from NSE_Config import NIFTY_200
from data_fetch import batch_download, extract_price_data
from utils import setup_page
import analytics


setup_page("Dashboard Launcher")

st.title("🚀 Trading Journal")
st.caption("Track your trades, analyze your performance, and refine your strategy.")

# --- PRE-FILL HANDLING ---
journal_prefill = st.session_state.pop("journal_prefill", None)
query_params = st.query_params

if isinstance(journal_prefill, dict):
    pre_symbol = str(journal_prefill.get("symbol", ""))
    pre_strategy = str(journal_prefill.get("strategy", "Swing Ranking"))
    pre_side = str(journal_prefill.get("side", "LONG"))
else:
    pre_symbol = query_params.get("symbol", "")
    pre_strategy = query_params.get("strategy", "Swing Rank")
    pre_side = query_params.get("side", "LONG")


# ==================== FILE HANDLING ====================
NOTES_DIR = Path("notes")
NOTES_DIR.mkdir(exist_ok=True)
JOURNAL_FILE = NOTES_DIR / "trading_journal.csv"

def load_journal():
    if JOURNAL_FILE.exists():
        try:
            return pd.read_csv(JOURNAL_FILE)
        except Exception as e:
            st.error(f"Error loading journal: {e}")
            return pd.DataFrame()
    else:
        # Create empty dataframe with columns
        return pd.DataFrame(columns=[
            "Date", "Symbol", "Side", "Entry Price", "Exit Price", 
            "Quantity", "Strategy", "Status", "Notes",
            "Regime", "Liquidity", "Stance", "Trade Intent", "Mistake Tags", "Chart Link", "Exit Reason"
        ])

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
        
        with col2:
            entry_price = st.number_input("Entry Price", min_value=0.0, format="%.2f")
            quantity = st.number_input("Quantity", min_value=1, step=1)
            stop_loss = st.number_input("Stop Loss (Optional)", min_value=0.0, format="%.2f")
            target = st.number_input("Target (Optional)", min_value=0.0, format="%.2f")
            # Auto-Capture Market Context
            context = analytics.get_current_context() # Future: pass actual data if available
            
            # --- NEW FIELDS ---
            col1, col2 = st.columns(2)
            with col1:
                intent = st.selectbox("Trade Intent", 
                    ["Swing Breakout", "Pullback", "Mean Reversion", "Position", "Experimental", "Intraday"])
            with col2:
                chart_link = st.text_input("Chart / Screenshot Link", placeholder="TradingView or Imgur link")
            
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
                    "Status": "OPEN",
                    "Notes": notes,
                    "Regime": context.get("regime", "Unknown"),
                    "Liquidity": context.get("liquidity", "Unknown"),
                    "Stance": context.get("stance", "Neutral"),
                    "Trade Intent": intent,
                    "Mistake Tags": ", ".join(mistakes) if mistakes else "",
                    "Chart Link": chart_link,
                    "Exit Reason": ""
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
        
        st.dataframe(
            display_df[cols].style.applymap(
                lambda x: 'color: #00FF00' if isinstance(x, (int, float)) and x > 0 else ('color: #FF0000' if isinstance(x, (int, float)) and x < 0 else ''),
                subset=["Unrealized P&L"] if "Unrealized P&L" in display_df.columns else []
            ),
            width='stretch', 
            hide_index=True
        )
        
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
    closed_trades = df[df["Status"] == "CLOSED"]
    
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
        
    else:
        st.info("No closed trades to analyze yet.")
