"""
Shared Utilities for Trading Dashboard Suite
Centralizes common functions to reduce code duplication
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
import logging
from contextlib import contextmanager
import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from config import PRICE_FETCH_MODE
from regime_state import load_regime_snapshot

logger = logging.getLogger(__name__)


# ==================== PAGE SETUP ====================

def _render_grouped_sidebar_nav() -> None:
    """Clear, non-toggle sidebar navigation."""
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Navigation")

    groups = {
        "Core": [
            ("Launcher", "app.py"),
            ("NSE Dashboard", "pages/0_NSE_Dashboard.py"),
            ("Tradable Universe", "pages/11_Tradable_Universe.py"),
            ("Macro & Regime Decision", "pages/3_Macro_Risk.py"),
            ("Nifty Strategy Engine", "pages/17_NIFTY_Strategy_Engine.py"),
            ("NSE Monthly Engine", "pages/18_NSE_Monthly_Engine.py"),
            ("Arbitrage Scanner", "pages/19_Arbitrage_Scanner.py"),
        ],
        "Market": [
            ("Global Markets", "pages/1_Global_Markets.py"),
            ("Liquidity & Money Supply", "pages/2_Money_Supply.py"),
            ("Leading Indicators", "pages/4_Leading_Indicators.py"),
            ("India Macro Context", "pages/13_India_Macro_Context.py"),
            ("News Feed", "pages/14_News_Feed.py"),
        ],
        "Journal": [
            ("Trading Journal", "pages/5_Trading_Journal.py"),
            ("Portfolio Risk", "pages/7_Portfolio_Risk.py"),
            ("Prediction Integrity", "pages/9_Prediction_Integrity.py"),
            ("Stock EOD Profile", "pages/15_Stock_Fundamentals.py"),
        ],
        "Admin / Ops": [
            ("Regime Settings", "pages/6_Regime_Settings.py"),
            ("Ops & Automation", "pages/8_Ops_Automation.py"),
            ("Scoring Audit", "pages/10_Scoring_Audit.py"),
            ("Roadmap TODO", "pages/12_Todo_Tracker.py"),
            ("NDE Automation", "pages/16_NDE_Automation.py"),
        ],
        "Documentation": [
            ("📖 NDE Usage Guide", "docs/NDE_USAGE_GUIDE.md"),
        ],
    }

    page_link_fn = getattr(st.sidebar, "page_link", None)
    if not callable(page_link_fn):
        # Fallback for older Streamlit builds.
        st.sidebar.caption("Grouped navigation unavailable on this Streamlit version.")
        return

    # Full visible navigation: all sections + all pages, no toggles/dropdowns.
    for section, links in groups.items():
        st.sidebar.markdown(f"**{section}**")
        for label, path in links:
            try:
                st.sidebar.page_link(path, label=label)
            except Exception:
                continue
        st.sidebar.caption("")


def setup_page(title: str, layout: str = "wide"):
    """Standardized page configuration and styling"""
    st.set_page_config(
        page_title=title,
        page_icon="🚀",
        layout=layout
    )
    
    # Common shared CSS for consistent aesthetics
    st.markdown("""
    <style>
        .main-title {
            font-size: 2.2rem;
            font-weight: 700;
            color: #1f77b4;
            margin-bottom: 0.2rem;
        }
        .stMetric {
            background-color: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
            border-left: 3px solid #1f77b4;
        }
        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] .stButton button {
            font-size: 0.82rem !important;
        }
        section[data-testid="stSidebar"] h3 {
            font-size: 0.95rem !important;
        }
    </style>
    """, unsafe_allow_html=True)
    _render_grouped_sidebar_nav()


def get_ui_detail_mode(default: str = "Summary") -> str:
    """Global page density control for summary/detail rendering."""
    if "ui_detail_mode" not in st.session_state:
        st.session_state["ui_detail_mode"] = default
    mode = st.sidebar.radio(
        "View Mode",
        options=["Summary", "Detail"],
        index=0 if st.session_state["ui_detail_mode"] == "Summary" else 1,
        help="Summary: decision-first minimal UI. Detail: full diagnostics and tables.",
        key="ui_detail_mode",
    )
    return mode


def get_ui_device_mode(default: str = "Desktop") -> str:
    """Global device density control for responsive rendering."""
    if "ui_device_mode" not in st.session_state:
        st.session_state["ui_device_mode"] = default
    mode = st.sidebar.radio(
        "Device Mode",
        options=["Desktop", "Mobile"],
        index=0 if st.session_state["ui_device_mode"] == "Desktop" else 1,
        help="Desktop: wider card grids and denser panels. Mobile: compact cards and reduced columns.",
        key="ui_device_mode",
    )
    return mode


def is_mobile_mode() -> bool:
    return st.session_state.get("ui_device_mode", "Desktop") == "Mobile"


def responsive_cols(n: int, spec=None):
    """
    Canonical responsive column helper.

    Returns st.columns on Desktop; returns a list of st.container on Mobile.
    Pages should import this instead of defining their own _responsive_cols.

    Args:
        n: Number of columns (used for both Desktop and Mobile container count).
        spec: Optional column spec passed to st.columns (e.g., [1, 2, 1]).
    """
    if is_mobile_mode():
        return [st.container() for _ in range(n)]
    return st.columns(spec if spec is not None else n)


def compact_table(df, preferred_cols: list[str]):
    """
    Canonical compact table helper for mobile-friendly column filtering.

    Returns the DataFrame unchanged on Desktop; on Mobile, filters to
    preferred_cols only.  Pages with row-truncation or view-mode-dependent
    logic should keep their own variant and note it in CODE_MANIFEST.md.
    """
    if not is_mobile_mode() or df is None or df.empty:
        return df
    keep = [c for c in preferred_cols if c in df.columns]
    return df[keep] if keep else df


def make_page_diag_block(view_mode: str, summary_container):
    """
    Factory that returns a ``page_diag_block`` context manager.

    In *Detail* mode each block becomes its own st.expander.
    In *Summary* mode blocks are appended inside a shared container
    (typically an st.expander("Open Diagnostics")).

    Usage (in page top-level)::

        page_diag_block = make_page_diag_block(view_mode, _summary_diag)

        with page_diag_block("Section Title"):
            st.write("...")
    """
    @contextmanager
    def _block(title: str, expanded: bool = False):
        if view_mode == "Detail":
            with st.expander(title, expanded=expanded):
                yield
        else:
            with summary_container:
                st.markdown(f"#### {title}")
                yield
                st.markdown("---")
    return _block


# ==================== UI COMPONENTS ====================

def display_market_breadth(advances: int, declines: int, unchanged: int):
    """Standardized market breadth display"""
    total = advances + declines + unchanged
    if total == 0:
        st.info("No data available for market breadth")
        return

    cols = st.columns(4)
    with cols[0]:
        st.metric("Advances", advances, f"{(advances/total)*100:.1f}%")
    with cols[1]:
        st.metric("Declines", declines, f"{(declines/total)*100:.1f}%")
    with cols[2]:
        st.metric("Unchanged", unchanged, f"{(unchanged/total)*100:.1f}%")
    with cols[3]:
        ad_ratio = advances / declines if declines > 0 else (advances if advances > 0 else 0)
        st.metric("A/D Ratio", f"{ad_ratio:.2f}")

    if advances > declines * 1.5:
        st.success("✅ Strong advancing day - Bullish sentiment")
    elif declines > advances * 1.5:
        st.error("⚠️ Strong declining day - Bearish sentiment")
    else:
        st.info("➡️ Mixed market - Neutral sentiment")


def render_key_observations(observations: list[str], title: str = "🔎 Key Observations", max_items: int = 5):
    """Render compact key observations block with top bullet points."""
    clean = [str(x).strip() for x in observations if str(x).strip()]
    if not clean:
        return

    st.markdown(f"### {title}")
    for item in clean[:max_items]:
        st.markdown(f"- {item}")


def render_decision_header(
    regime_label: Optional[str] = None,
    final_score: Optional[float] = None,
    confidence: Optional[float] = None,
    bias: Optional[str] = None,
    source: Optional[str] = None,
) -> None:
    """
    Compact command-strip style decision header.
    Falls back to SSOT snapshot when values are omitted.
    """
    snap = load_regime_snapshot()
    regime = regime_label if regime_label is not None else str(snap.get("regime_label", "Unknown"))
    score = final_score if final_score is not None else snap.get("final_score")
    conf = confidence if confidence is not None else snap.get("confidence")
    decision_bias = bias if bias is not None else snap.get("bias")
    src = source if source is not None else snap.get("source")

    def _fmt_score(v):
        try:
            return f"{float(v):+.2f}"
        except Exception:
            return "N/A"

    def _fmt_conf(v):
        try:
            return f"{float(v):.0%}"
        except Exception:
            return "N/A"

    c1, c2, c3, c4 = st.columns(4)
    
    is_weak = False
    try:
        if conf is not None and float(conf) < 0.3:
            is_weak = True
    except Exception:
        pass

    with c1:
        label_text = str(regime)
        if is_weak:
            label_text = f"⚠️ {label_text} (WEAK)"
        st.metric("Regime", label_text)
    with c2:
        st.metric("Score", _fmt_score(score))
    with c3:
        conf_val = _fmt_conf(conf)
        st.metric("Confidence", conf_val, delta="LOW" if is_weak else None, delta_color="inverse" if is_weak else "normal")
    with c4:
        st.metric("Bias", str(decision_bias or "N/A"))
        
    if is_weak:
        st.warning(
            "⚠️ **Low Confidence Signal** ( < 30% ): Current regime is near a boundary or experiencing high intraday volatility. \n\n"
            "**Trading Guidance**: Favor defensive positioning, reduced initial sizing (0.25R - 0.5R), and tighter trailing stops until signal stabilizes."
        )

    if src:
        st.caption(f"SSOT source: {src}")


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

def get_live_price_safe(
    symbol: str,
    fallback_df: Optional[pd.DataFrame] = None,
    mode: Optional[str] = None
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Safely get live price with historical fallback

    Args:
        symbol: Yahoo Finance symbol
        fallback_df: Historical DataFrame to use if live fails
        mode: "close_only" or "live_first" (defaults to PRICE_FETCH_MODE)

    Returns:
        (price, change, change_pct) tuple
    """
    from data_fetch import get_ticker_price, extract_price_data

    fetch_mode = (mode or PRICE_FETCH_MODE or "close_only").strip().lower()
    
    # Use the requested or global default mode.
        
    if fetch_mode not in {"close_only", "live_first"}:
        fetch_mode = "close_only"

    if fetch_mode == "close_only":
        if fallback_df is not None:
            return extract_price_data(fallback_df)
        return None, None, None

    # live_first mode
    price, change, change_pct = get_ticker_price(symbol)
    if price is None and fallback_df is not None:
        return extract_price_data(fallback_df)

    return price, change, change_pct


def display_price_metric(
    col,
    symbol: str,
    name: str,
    df: Optional[pd.DataFrame] = None,
    symbol_type: str = 'equity',
    mode: Optional[str] = None
):
    """
    Display price metric with live data and fallback

    Args:
        col: Streamlit column
        symbol: Yahoo Finance symbol
        name: Display name
        df: Historical data fallback
        symbol_type: Asset type for formatting
        mode: "close_only" or "live_first" (defaults to PRICE_FETCH_MODE)
    """
    price, change, change_pct = get_live_price_safe(symbol, df, mode=mode)

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
    columns: Optional[list] = None,
    mode: Optional[str] = None,
    include_meta: bool = False,
) -> pd.DataFrame:
    """
    Create standardized price table

    Args:
        symbols_dict: {symbol: name} dictionary
        data: {symbol: DataFrame} dictionary
        columns: Custom column names
        mode: "close_only" or "live_first" (defaults to PRICE_FETCH_MODE)

    Returns:
        DataFrame ready for display
    """
    if columns is None:
        columns = ["Asset", "Price", "Change %"]

    telemetry_map: Dict[str, Dict[str, Any]] = {}
    if include_meta:
        try:
            from data_fetch import get_last_batch_telemetry
            telem = get_last_batch_telemetry()
            if telem is not None and not telem.empty:
                for _, row in telem.iterrows():
                    telemetry_map[str(row.get("symbol"))] = {
                        "source": row.get("source", "UNKNOWN"),
                        "age_bdays": row.get("age_bdays"),
                    }
        except Exception:
            telemetry_map = {}

    rows = []
    for symbol, name in symbols_dict.items():
        df = data.get(symbol)
        price, change, change_pct = get_live_price_safe(symbol, df, mode=mode)
        as_of = "N/A"
        if df is not None and not df.empty:
            idx = getattr(df, "index", None)
            if isinstance(idx, pd.DatetimeIndex) and len(idx) > 0:
                as_of = idx[-1].strftime("%Y-%m-%d")

        row = {
            columns[0]: name,
            columns[1]: format_price(price),
            columns[2]: format_change(change_pct)
        }
        if include_meta:
            meta = telemetry_map.get(symbol, {})
            row["Source"] = meta.get("source", "API")
            age = meta.get("age_bdays")
            row["Age(BD)"] = "-" if age is None or pd.isna(age) else int(age)
            row["As Of"] = as_of
        rows.append(row)

    return pd.DataFrame(rows)


def render_source_freshness(symbols_dict: Dict[str, str], data: Dict[str, pd.DataFrame], title: str = "Source & Freshness"):
    """Render compact source/freshness telemetry table."""
    rows = []
    telem_map: Dict[str, Dict[str, Any]] = {}
    try:
        from data_fetch import get_last_batch_telemetry
        telem = get_last_batch_telemetry()
        if telem is not None and not telem.empty:
            for _, row in telem.iterrows():
                telem_map[str(row.get("symbol"))] = {
                    "source": row.get("source", "API"),
                    "age": row.get("age_bdays"),
                    "severity": row.get("severity", "OK"),
                }
    except Exception:
        pass

    for symbol, label in symbols_dict.items():
        df = data.get(symbol)
        as_of = "N/A"
        if df is not None and not df.empty:
            idx = getattr(df, "index", None)
            if isinstance(idx, pd.DatetimeIndex) and len(idx) > 0:
                as_of = idx[-1].strftime("%Y-%m-%d")
        meta = telem_map.get(symbol, {})
        rows.append(
            {
                "Factor": label,
                "Symbol": symbol,
                "Source": meta.get("source", "API"),
                "As Of": as_of,
                "Age(BD)": "-" if meta.get("age") is None or pd.isna(meta.get("age")) else int(meta["age"]),
                "Status": meta.get("severity", "OK"),
            }
        )

    if rows:
        st.markdown(f"#### {title}")
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_manual_data_staleness_alerts(india_ctx: Dict[str, Any]) -> None:
    """
    Renders prominent warnings if manual data sources (GST/Yield Curve) are stale.
    Thresholds: 35 days for GST (Monthly), 3 Business Days for Yield Curve.
    """
    gst = india_ctx.get("gst", {})
    curve = india_ctx.get("curve", {})
    
    warnings = []
    
    # GST Check (Manual CSV/JSON)
    gst_age = gst.get("age_days")
    if gst_age is not None and gst_age > 35:
        warnings.append(f"🔴 **GST Data Stale**: Last updated {gst_age:.1f} days ago. (Threshold: 35 days)")
    elif gst.get("status") == "UNAVAILABLE":
        warnings.append("🔴 **GST Data Unavailable**: Manual file missing or corrupted.")
        
    # Curve Check (Manual JSON)
    curve_age = curve.get("age_days")
    if curve_age is not None and curve_age > 3:
        # Note: Ideally this would be Business Days, but 3 calendar days is a good proxy for manual checks.
        warnings.append(f"🔴 **Yield Curve Stale**: Last updated {curve_age:.1f} days ago. (Threshold: 3 days)")
    elif curve.get("status") == "UNAVAILABLE":
        warnings.append("🔴 **Yield Curve Unavailable**: Manual file missing or corrupted.")
        
    if warnings:
        with st.container():
            for w in warnings:
                st.warning(w)
            
            if st.session_state.get("ui_detail_mode") == "Detail":
                st.info(
                    "**Action Required**: Please update the manual context files in `notes/` "
                    "or `data/gst_monthly.csv` to ensure accurate macro scoring. "
                    "Regime classification depends heavily on these leading indicators."
                )


def render_regime_timeline_strip(timeline: list[Dict[str, Any]], key: str = "regime_timeline") -> None:
    """
    Render a 90-day pulse-tape regime timeline with transition markers.
    Input row format:
      {"ts":"YYYY-MM-DD","regime":"RISK_ON|SELECTIVE|DEFENSIVE|CRISIS","score":float,"confidence":"HIGH|MEDIUM|LOW"}
    """
    if not timeline:
        st.info("No regime timeline available.")
        return

    rows = timeline[-90:]
    payload = json.dumps(rows)
    html = f"""
    <div id="{key}" class="rt-wrap">
      <div class="rt-head">
        <div class="rt-title">REGIME TIMELINE (90D)</div>
        <div class="rt-sub">Pulse Tape</div>
      </div>
      <div class="rt-legend">
        <div class="rt-leg-item"><span class="rt-leg-dot" style="background:#10b981"></span><span><b>Risk On</b>: broad risk appetite</span></div>
        <div class="rt-leg-item"><span class="rt-leg-dot" style="background:#0ea5e9"></span><span><b>Selective</b>: mixed, stock/sector selective</span></div>
        <div class="rt-leg-item"><span class="rt-leg-dot" style="background:#f59e0b"></span><span><b>Defensive</b>: cautious, lower beta preference</span></div>
        <div class="rt-leg-item"><span class="rt-leg-dot" style="background:#ef4444"></span><span><b>Crisis</b>: risk-off stress regime</span></div>
      </div>
      <div class="rt-scroll">
        <div class="rt-track"></div>
      </div>
      <div class="rt-tip" id="{key}-tip"></div>
    </div>
    <style>
      .rt-wrap {{
        width: 100%;
        font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #d9e2ec;
      }}
      .rt-head {{
        display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;
      }}
      .rt-title {{
        font-size: 11px; font-weight: 700; letter-spacing: .1em; color: #cfd9e2;
      }}
      .rt-sub {{
        font-size: 10px; color: #7f93a7;
      }}
      .rt-legend {{
        display: flex; flex-wrap: wrap; gap: 10px 14px;
        margin-bottom: 8px; font-size: 11px; color: #b9c7d4;
      }}
      .rt-leg-item {{
        display: inline-flex; align-items: center; gap: 6px;
      }}
      .rt-leg-dot {{
        width: 10px; height: 10px; border-radius: 50%;
        border: 1px solid rgba(255,255,255,.2);
        box-shadow: 0 0 0 1px rgba(0,0,0,.35) inset;
      }}
      .rt-scroll {{
        overflow-x: auto; overflow-y: hidden; scroll-behavior: smooth;
        border: 1px solid #23303d; border-radius: 8px; background: #0b1116;
        padding: 8px 8px 6px 8px;
      }}
      .rt-track {{
        position: relative; height: 56px; min-width: 600px;
        display: flex; align-items: center;
      }}
      .rt-base {{
        position: absolute; left: 0; right: 0; top: 50%;
        transform: translateY(-50%);
        height: 1px; background: rgba(94,116,136,.45);
      }}
      .rt-seg-wrap {{
        position: relative; width: 10px; height: 56px; flex: 0 0 10px;
      }}
      .rt-seg {{
        position: absolute; bottom: 10px; left: 1px; right: 1px;
        border-radius: 2px; transition: all .4s ease;
      }}
      .rt-transition {{
        position: absolute; left: 0; top: 2px; bottom: 2px;
        width: 2px; background: rgba(255,255,255,.86);
        box-shadow: 0 0 8px rgba(255,255,255,.35);
      }}
      .rt-current-dot {{
        position: absolute; top: 1px; left: 50%; transform: translateX(-50%);
        width: 5px; height: 5px; border-radius: 50%;
        background: #ffffff; box-shadow: 0 0 8px rgba(255,255,255,.85);
      }}
      .rt-current-pulse {{
        position: absolute; top: 1px; left: 50%; transform: translateX(-50%);
        width: 5px; height: 5px; border-radius: 50%;
        background: rgba(255,255,255,.6); animation: rtPulse 1.4s infinite;
      }}
      .rt-tip {{
        position: fixed; z-index: 9999; pointer-events: none;
        display: none; min-width: 190px; max-width: 240px;
        background: rgba(5,10,14,.96); border: 1px solid #2a3a49; border-radius: 8px;
        padding: 8px 10px; color: #dbe4ec; font-size: 11px; line-height: 1.25;
        box-shadow: 0 10px 30px rgba(0,0,0,.45);
      }}
      .rt-tip .d {{ font-weight: 700; margin-bottom: 4px; }}
      .rt-tip .r {{ margin-top: 2px; }}
      @keyframes rtPulse {{
        0% {{ transform: translateX(-50%) scale(1); opacity: .9; }}
        100% {{ transform: translateX(-50%) scale(2.4); opacity: 0; }}
      }}
    </style>
    <script>
      (() => {{
        const data = {payload};
        const root = document.getElementById("{key}");
        if (!root || !Array.isArray(data) || !data.length) return;
        const scroll = root.querySelector(".rt-scroll");
        const track = root.querySelector(".rt-track");
        const tip = document.getElementById("{key}-tip");
        const colors = {{
          "RISK_ON": "#10b981",
          "SELECTIVE": "#0ea5e9",
          "DEFENSIVE": "#f59e0b",
          "CRISIS": "#ef4444"
        }};
        const confOpacity = {{ "HIGH": 1.0, "MEDIUM": 0.8, "LOW": 0.6 }};
        track.style.minWidth = Math.max(600, data.length * 10) + "px";
        const base = document.createElement("div");
        base.className = "rt-base";
        track.appendChild(base);
        function showTip(evt, row, isTransition) {{
          const score = Number(row.score || 0);
          const rawConf = Number(row.confidence_val || (row.confidence === "HIGH" ? 0.9 : (row.confidence === "MEDIUM" ? 0.6 : 0.3)));
          const confPct = Math.round(rawConf * 100);
          const strengthColor = rawConf < 0.3 ? "#ef4444" : (rawConf < 0.6 ? "#f59e0b" : "#10b981");
          
          tip.innerHTML = `
            <div class="d">${{row.ts || ""}}</div>
            <div class="r">Regime: <b>${{row.regime || "N/A"}}</b>${{isTransition ? " • Transition Day" : ""}}</div>
            <div class="r">Score: <b>${{score > 0 ? "+" : ""}}${{score.toFixed(2)}}</b></div>
            <div class="r" style="margin-top:6px; display:flex; align-items:center; gap:8px;">
               <span>Strength:</span>
               <div style="flex:1; height:4px; background:#23303d; border-radius:2px; overflow:hidden;">
                 <div style="width:${{confPct}}%; height:100%; background:${{strengthColor}};"></div>
               </div>
               <b style="color:${{strengthColor}}">${{confPct}}%</b>
            </div>`;
          tip.style.display = "block";
          const margin = 10;
          const maxX = window.innerWidth - tip.offsetWidth - margin;
          const maxY = window.innerHeight - tip.offsetHeight - margin;
          const x = Math.min(maxX, Math.max(margin, evt.clientX + 12));
          const y = Math.min(maxY, Math.max(margin, evt.clientY - 12));
          tip.style.left = x + "px";
          tip.style.top = y + "px";
        }}
        function hideTip() {{ tip.style.display = "none"; }}
        data.forEach((row, i) => {{
          const w = document.createElement("div");
          w.className = "rt-seg-wrap";
          const s = document.createElement("div");
          s.className = "rt-seg";
          const scoreAbs = Math.min(2, Math.abs(Number(row.score || 0)));
          const h = 18 + (scoreAbs * 7);
          s.style.height = h + "px";
          s.style.background = colors[row.regime] || "#64748b";
          s.style.opacity = String(confOpacity[row.confidence] ?? 0.7);
          const isTransition = i > 0 && data[i-1].regime !== row.regime;
          if (isTransition) {{
            const t = document.createElement("div");
            t.className = "rt-transition";
            w.appendChild(t);
          }}
          if (i === data.length - 1) {{
            const d = document.createElement("div");
            d.className = "rt-current-dot";
            w.appendChild(d);
            const p = document.createElement("div");
            p.className = "rt-current-pulse";
            w.appendChild(p);
          }}
          w.appendChild(s);
          w.addEventListener("mousemove", (e) => showTip(e, row, isTransition));
          w.addEventListener("mouseenter", (e) => showTip(e, row, isTransition));
          w.addEventListener("mouseleave", hideTip);
          track.appendChild(w);
        }});
        requestAnimationFrame(() => {{
          scroll.scrollLeft = scroll.scrollWidth;
        }});
      }})();
    </script>
    """
    components.html(html, height=108, scrolling=False)


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
# ==================== DATA HELPERS ====================

def get_fno_lot_size(symbol: str) -> int:
    """Fetch F&O lot size for a symbol from the JSON database."""
    try:
        LOT_FILE = Path(__file__).parent / "notes" / "fno_lot_sizes.json"
        if not LOT_FILE.exists():
            return 100 # Safe default for cash
        
        payload = json.loads(LOT_FILE.read_text())
        lots = payload.get("lot_sizes", {})
        
        # Normalize symbol
        s = str(symbol or "").strip().upper()
        if s.endswith(".NS"):
            s = s[:-3]
            
        return int(lots.get(s, 100))
    except Exception:
        return 100
