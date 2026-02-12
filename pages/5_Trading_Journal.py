import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import os
from NSE_Config import NIFTY_200
from data_fetch import batch_download, extract_price_data
from utils import setup_page

setup_page("Dashboard Launcher")

st.title("🚀 Trading Journal")
st.caption("Track your trades, analyze your performance, and refine your strategy.")

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
            "Quantity", "Strategy", "Status", "Notes"
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
            
            # Combine NIFTY 200 with Custom option
            symbol_options = ["Other / Custom Instrument"] + sorted(list(NIFTY_200))
            selected_sym = st.selectbox("Symbol", options=symbol_options, help="Select from NIFTY 200 or pick 'Other' to type manually")
            
            # Show text input only if 'Other' is selected
            custom_symbol = ""
            if selected_sym == "Other / Custom Instrument":
                custom_symbol = st.text_input("Enter Manual Symbol (e.g., BTCUSD, ^NSEI)").upper()
                
            side = st.selectbox("Side", ["LONG", "SHORT"])
            strategy = st.selectbox("Strategy", [
                "Gap Up/Down", "Swing Ranking", "EMA Crossover", "Breakout", "Oversold Reversal", "Other"
            ])
        
        with col2:
            entry_price = st.number_input("Entry Price", min_value=0.0, format="%.2f")
            quantity = st.number_input("Quantity", min_value=1, step=1)
            stop_loss = st.number_input("Stop Loss (Optional)", min_value=0.0, format="%.2f")
            target = st.number_input("Target (Optional)", min_value=0.0, format="%.2f")
            notes = st.text_area("Notes / Rationale")
            
        submitted = st.form_submit_button("💾 Save Trade")
        
        if submitted:
            # Determine final symbol
            final_symbol = custom_symbol if selected_sym == "Other / Custom Instrument" else selected_sym
            
            if final_symbol and entry_price > 0:
                entry = {
                    "Date": date.strftime("%Y-%m-%d"),
                    "Symbol": final_symbol,
                    "Side": side,
                    "Entry Price": entry_price,
                    "Exit Price": 0.0,  # Open trade
                    "Quantity": quantity,
                    "Strategy": strategy,
                    "Status": "OPEN",
                    "Notes": notes
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
                cols.remove(col)
                cols.insert(entry_idx + 1, col)
                entry_idx += 1
        
        st.dataframe(
            display_df[cols].style.applymap(
                lambda x: 'color: #00FF00' if isinstance(x, (int, float)) and x > 0 else ('color: #FF0000' if isinstance(x, (int, float)) and x < 0 else ''),
                subset=["Unrealized P&L"] if "Unrealized P&L" in display_df.columns else []
            ),
            use_container_width=True, 
            hide_index=True
        )
        
        # Close Trade UI
        st.markdown("### 🔒 Close a Trade")
        open_trades = df[df["Status"] == "OPEN"]
        
        if not open_trades.empty:
            trade_to_close = st.selectbox(
                "Select Trade to Close", 
                options=open_trades.index,
                format_func=lambda x: f"{df.loc[x, 'Date']} - {df.loc[x, 'Symbol']} ({df.loc[x, 'Side']})"
            )
            
            with st.form("close_trade_form"):
                exit_price = st.number_input("Exit Price", min_value=0.0, format="%.2f")
                close_notes = st.text_area("Closing Notes (Lessons)")
                
                close_submitted = st.form_submit_button("✅ Close Trade")
                
                if close_submitted:
                    df.loc[trade_to_close, "Exit Price"] = exit_price
                    df.loc[trade_to_close, "Status"] = "CLOSED"
                    if close_notes:
                        df.loc[trade_to_close, "Notes"] += f" | Exit: {close_notes}"
                    
                    df.to_csv(JOURNAL_FILE, index=False)
                    st.success("🎉 Trade Closed!")
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
