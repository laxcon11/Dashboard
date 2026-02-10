"""
Shared Utilities for Trading Dashboard Suite
Centralizes common functions to reduce code duplication
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import logging
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


# ==================== PRICE FORMATTING ====================

def format_price(price: Optional[float], symbol_type: str = 'equity') -> str:
    """
    Smart price formatting based on asset type and magnitude

    Args:
        price: Price value
        symbol_type: 'equity', 'forex', 'crypto', 'commodity', 'yield'

    Returns:
        Formatted string
    """
    if price is None or pd.isna(price):
        return "N/A"

    if symbol_type == 'yield':
        return f"{price:.2f}%"
    elif symbol_type == 'forex':
        return f"{price:.4f}"
    elif symbol_type == 'crypto':
        return f"${price:,.2f}"
    elif price > 1000:
        return f"{price:,.0f}"
    elif price > 10:
        return f"{price:.2f}"
    else:
        return f"{price:.4f}"


def format_change(change_pct: Optional[float]) -> str:
    """Format percentage change with + or - sign"""
    if change_pct is None or pd.isna(change_pct):
        return "N/A"
    return f"{change_pct:+.2f}%"


# ==================== CHART CREATION ====================

def create_line_chart(
    df: pd.DataFrame,
    title: str,
    y_column: str = 'Close',
    height: int = 300,
    color: str = '#1f77b4'
) -> go.Figure:
    """
    Create standardized line chart

    Args:
        df: DataFrame with datetime index
        title: Chart title
        y_column: Column to plot
        height: Chart height
        color: Line color

    Returns:
        Plotly figure
    """
    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df.index,
        y=df[y_column],
        mode='lines',
        name=title,
        line=dict(color=color, width=2)
    ))

    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        title=title,
        xaxis_title="Date",
        yaxis_title="Price",
        hovermode='x unified',
        showlegend=False
    )

    return fig


def create_multi_line_chart(
    data_dict: Dict[str, pd.DataFrame],
    title: str,
    y_column: str = 'Close',
    height: int = 400
) -> go.Figure:
    """
    Create chart with multiple lines

    Args:
        data_dict: {label: DataFrame} dictionary
        title: Chart title
        y_column: Column to plot
        height: Chart height

    Returns:
        Plotly figure
    """
    fig = go.Figure()

    for label, df in data_dict.items():
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df[y_column],
            mode='lines',
            name=label
        ))

    fig.update_layout(
        height=height,
        title=title,
        hovermode='x unified'
    )

    return fig


# ==================== PRICE FETCHING ====================

def get_live_price_safe(symbol: str, fallback_df: Optional[pd.DataFrame] = None) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Safely get live price with historical fallback

    Args:
        symbol: Yahoo Finance symbol
        fallback_df: Historical DataFrame to use if live fails

    Returns:
        (price, change, change_pct) tuple
    """
    from data_fetch import get_ticker_price, extract_price_data

    # Try live first
    price, change, change_pct = get_ticker_price(symbol)

    # Fallback to historical
    if price is None and fallback_df is not None:
        price, change, change_pct = extract_price_data(fallback_df)

    return price, change, change_pct


def display_price_metric(
    col,
    symbol: str,
    name: str,
    df: Optional[pd.DataFrame] = None,
    symbol_type: str = 'equity'
):
    """
    Display price metric with live data and fallback

    Args:
        col: Streamlit column
        symbol: Yahoo Finance symbol
        name: Display name
        df: Historical data fallback
        symbol_type: Asset type for formatting
    """
    price, change, change_pct = get_live_price_safe(symbol, df)

    if price is not None:
        formatted_price = format_price(price, symbol_type)
        delta = format_change(change_pct) if change_pct is not None else None
        col.metric(name, formatted_price, delta)
    else:
        col.metric(name, "No Data")


# ==================== SIGNAL CLASSIFICATION ====================

def classify_signal(
    value: float,
    thresholds: Dict[str, float],
    signal_type: str = 'default'
) -> Tuple[str, str]:
    """
    Classify signal into categories

    Args:
        value: Signal value
        thresholds: Dictionary with 'high' and 'low' keys
        signal_type: Type of signal for custom logic

    Returns:
        (label, color) tuple where color is 'success', 'warning', or 'error'
    """
    if signal_type == 'risk_score':
        high = thresholds.get('high', 4)
        low = thresholds.get('low', -4)

        if value >= high:
            return "🟢 Risk On", "success"
        elif value <= low:
            return "🔴 Risk Off", "error"
        else:
            return "🟡 Neutral", "warning"

    elif signal_type == 'rsi':
        if value >= thresholds.get('overbought', 70):
            return "Overbought", "error"
        elif value <= thresholds.get('oversold', 30):
            return "Oversold", "success"
        else:
            return "Neutral", "warning"

    else:
        # Generic classification
        if value > thresholds.get('positive', 0):
            return "Positive", "success"
        elif value < thresholds.get('negative', 0):
            return "Negative", "error"
        else:
            return "Neutral", "warning"


# ==================== DATA TABLE CREATION ====================

def create_price_table(
    symbols_dict: Dict[str, str],
    data: Dict[str, pd.DataFrame],
    columns: Optional[list] = None
) -> pd.DataFrame:
    """
    Create standardized price table

    Args:
        symbols_dict: {symbol: name} dictionary
        data: {symbol: DataFrame} dictionary
        columns: Custom column names

    Returns:
        DataFrame ready for display
    """
    if columns is None:
        columns = ["Asset", "Price", "Change %"]

    rows = []
    for symbol, name in symbols_dict.items():
        df = data.get(symbol)
        price, change, change_pct = get_live_price_safe(symbol, df)

        rows.append({
            columns[0]: name,
            columns[1]: format_price(price),
            columns[2]: format_change(change_pct)
        })

    return pd.DataFrame(rows)


# ==================== ERROR HANDLING ====================

def safe_operation(func, default_value=None, log_error=True):
    """
    Wrapper for safe operations with error handling

    Args:
        func: Function to execute
        default_value: Value to return on error
        log_error: Whether to log errors

    Returns:
        Function result or default_value on error
    """
    try:
        return func()
    except Exception as e:
        if log_error:
            logger.error(f"Operation failed: {e}")
        return default_value


# ==================== DISPLAY HELPERS ====================

def show_status_indicator(condition: bool, true_text: str, false_text: str):
    """Show status with appropriate styling"""
    if condition:
        st.success(f"✅ {true_text}")
    else:
        st.warning(f"⚠️ {false_text}")


def create_debug_expander(data_dict: Dict[str, Any], title: str = "🔍 Debug Info"):
    """
    Create collapsible debug section

    Args:
        data_dict: Dictionary of debug information
        title: Expander title
    """
    with st.expander(title, expanded=False):
        for key, value in data_dict.items():
            st.write(f"**{key}**: {value}")


# ==================== REGIME/TREND HELPERS ====================

def calculate_trend(series: pd.Series, window: int = 20) -> str:
    """
    Calculate trend direction

    Args:
        series: Price series
        window: MA window

    Returns:
        'Up', 'Down', or 'Neutral'
    """
    if len(series) < window:
        return 'Neutral'

    ma = series.rolling(window).mean().iloc[-1]
    current = series.iloc[-1]

    if current > ma * 1.02:
        return 'Up'
    elif current < ma * 0.98:
        return 'Down'
    else:
        return 'Neutral'


def get_momentum(series: pd.Series, periods: int = 5) -> float:
    """
    Calculate momentum

    Args:
        series: Price series
        periods: Lookback period

    Returns:
        Momentum percentage
    """
    if len(series) < periods + 1:
        return 0.0

    current = series.iloc[-1]
    previous = series.iloc[-(periods+1)]

    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100