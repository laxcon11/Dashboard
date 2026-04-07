import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from NSE_Config import NIFTY_200, PRESET_WATCHLISTS, SECTOR_CATEGORIES
from trading_calendar import is_nse_trading_day
from utils import setup_page, get_ui_detail_mode, get_ui_device_mode, responsive_cols as _responsive_cols, compact_table as _compact_table


setup_page("Tradable Universe")
view_mode = get_ui_detail_mode("Summary")
device_mode = get_ui_device_mode("Desktop")
is_mobile = device_mode == "Mobile"
st.title("✅ Tradable Universe")
st.caption("Consolidated tradable setups across categories with 20-day context.")
st.caption(f"Device mode: **{device_mode}**")

SNAPSHOT_PATH = Path("data/snapshots/tradable_signals.parquet")
SNAPSHOT_META_PATH = Path("data/snapshots/tradable_signals_meta.json")
STATUS_PATH = Path("data/snapshots/tradable_refresh_status.json")
BASE_DIR = Path(__file__).resolve().parents[1]


# _responsive_cols imported from utils

# _compact_table imported from utils


def _run_script(script_name: str, args: list[str] | None = None) -> tuple[int, str]:
    cmd = [sys.executable, f"scripts/{script_name}"]
    if args:
        cmd.extend(args)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(BASE_DIR), timeout=1800)
        out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return proc.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, f"Timeout while running {' '.join(cmd)}"
    except Exception as exc:
        return 1, f"Failed to run {' '.join(cmd)}: {exc}"


def _write_tradable_heartbeat(success: bool, details: str = "") -> None:
    run_date = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    SNAPSHOT_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_META_PATH.write_text(
        json.dumps(
            {
                "last_run_date": str(run_date.date()),
                "rows_written_today": None,
                "updated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
                "source": "tradable_universe_full_refresh",
                "run_status": "SUCCESS" if success else "FAILED",
        "run_details": str(details or "")[:5000],
            },
            indent=2,
        )
    )


ctl1, ctl2 = _responsive_cols(2, [1, 3])
with ctl1:
    if st.button("Run Full Refresh", width="stretch"):
        cmd = [sys.executable, "scripts/tradable_universe_refresh.py"]
        subprocess.Popen(cmd, cwd=str(BASE_DIR))
        st.session_state["is_refreshing"] = True
        st.rerun()

if st.session_state.get("is_refreshing"):
    if STATUS_PATH.exists():
        try:
            status_data = json.loads(STATUS_PATH.read_text())
            progress = status_data.get("progress", 0)
            msg = status_data.get("message", "Refreshing...")
            is_done = (status_data.get("status") == "SUCCESS" and progress == 100)
            
            # Show progress bar
            st.info(f"⏳ **Scan in Progress:** {msg}")
            st.progress(progress / 100.0)
            
            if is_done:
                st.session_state["is_refreshing"] = False
                st.success("Tradable universe refresh completed.")
                st.rerun()
            else:
                import time
                time.sleep(1)
                st.rerun()
        except Exception:
            pass
with ctl2:
    st.caption("Scans all presets + sectors with swing-ranking scoring and writes combined tradable_signals.parquet.")


def _strip_ns(sym: str) -> str:
    s = str(sym or "").strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def _is_trading_day(d: pd.Timestamp) -> bool:
    return bool(is_nse_trading_day(d))


def _calc_streak(date_set: set[pd.Timestamp], ordered_dates: list[pd.Timestamp], current_d: pd.Timestamp) -> int:
    if current_d not in date_set or current_d not in ordered_dates:
        return 0
    idx = ordered_dates.index(current_d)
    count = 0
    for j in range(idx, -1, -1):
        if ordered_dates[j] in date_set:
            count += 1
        else:
            break
    return count


if not SNAPSHOT_PATH.exists():
    st.info("No tradable snapshots found yet. Run Swing Rankings first to generate snapshots.")
    st.stop()

try:
    hist = pd.read_parquet(SNAPSHOT_PATH)
except Exception as exc:
    st.error(f"Could not read snapshot file: {exc}")
    st.stop()

if hist.empty:
    st.info("Snapshot file is empty.")
    st.stop()

hist["date"] = pd.to_datetime(hist.get("date"), errors="coerce").dt.normalize()
hist["symbol"] = hist.get("symbol", pd.Series(dtype=str)).astype(str).map(_strip_ns)
hist["setup_type"] = hist.get("setup_type", pd.Series(dtype=str)).astype(str)
hist = hist.dropna(subset=["date", "symbol", "setup_type"])

all_dates = sorted(hist["date"].unique().tolist())
if not all_dates:
    st.info("No valid dated rows in snapshot.")
    st.stop()

latest_date = all_dates[-1]
latest_run_date = latest_date
latest_run_status = "UNKNOWN"
if SNAPSHOT_META_PATH.exists():
    try:
        # Using a more robust JSON read than pd.read_json typ="series"
        with open(SNAPSHOT_META_PATH, 'r') as f:
            meta = json.load(f)
        meta_d = pd.to_datetime(meta.get("last_run_date"), errors="coerce")
        if not pd.isna(meta_d):
            latest_run_date = meta_d.normalize()
        latest_run_status = str(meta.get("run_status", "UNKNOWN")).upper()
    except Exception:
        pass

# IMPORTANT: latest_date for UI filtering should be the last actual run date
latest_date = latest_run_date

# Category filter
all_categories = sorted(hist["category_label"].dropna().unique().tolist())
sel_categories = st.multiselect(
    "Filter by Category",
    options=all_categories,
    default=[],
    placeholder="Showing All Categories (or select specific ones)",
)
if sel_categories:
    hist = hist[hist["category_label"].isin(sel_categories)].copy()

lookback_dates = all_dates[-20:] if len(all_dates) >= 20 else all_dates
hist20 = hist[hist["date"].isin(lookback_dates)].copy()
today_rows = hist[hist["date"] == latest_date].copy()
prev_date = all_dates[-2] if len(all_dates) >= 2 else None
prev_rows = hist[hist["date"] == prev_date].copy() if prev_date is not None else pd.DataFrame(columns=hist.columns)

# Build known universe from NIFTY 200 + all preset/sector lists
master_universe = {_strip_ns(s) for s in NIFTY_200}
for _stocks in PRESET_WATCHLISTS.values():
    master_universe.update(_strip_ns(s) for s in _stocks)
for _stocks in SECTOR_CATEGORIES.values():
    master_universe.update(_strip_ns(s) for s in _stocks)
orphan_master = sorted(set(hist20["symbol"].unique()) - master_universe)
if orphan_master:
    hist20 = hist20[~hist20["symbol"].isin(orphan_master)].copy()
    today_rows = today_rows[~today_rows["symbol"].isin(orphan_master)].copy()
    prev_rows = prev_rows[~prev_rows["symbol"].isin(orphan_master)].copy()

today_keys = set(zip(today_rows["symbol"], today_rows["setup_type"]))
today_symbols = set(today_rows["symbol"].unique())
prev_keys = set(zip(prev_rows.get("symbol", pd.Series(dtype=str)), prev_rows.get("setup_type", pd.Series(dtype=str))))
# Only show in dropped if the *symbol* is completely gone from today's list
dropped_keys = sorted([(s, t) for s, t in (prev_keys - today_keys) if s not in today_symbols])

ctx_rows = []
for _, r in today_rows.iterrows():
    sym = str(r["symbol"])
    stype = str(r["setup_type"])
    h_setup = hist20[(hist20["symbol"] == sym) & (hist20["setup_type"] == stype)]
    setup_dates = sorted(h_setup["date"].unique().tolist())
    setup_days = len(setup_dates)
    setup_streak = _calc_streak(set(setup_dates), lookback_dates, latest_date)
    qhist = pd.to_numeric(h_setup.get("quality_score"), errors="coerce").dropna().tail(5)
    qtrend = float(qhist.iloc[-1] - qhist.iloc[0]) if len(qhist) >= 3 else 0.0
    is_new = setup_days == 1
    is_fading = setup_days >= 8 and qtrend <= -0.06
    is_continuation = bool(r.get("is_continuation", False))
    is_overlap = bool(r.get("is_overlap", False))
    
    tags = []
    icons = ""
    if is_new and not is_continuation:
        tags.append("NEW")
        icons += "🆕"
    elif is_continuation:
        tags.append("CONTINUATION")
        icons += "⏩"
        
    if is_fading:
        tags.append("FADING")
        icons += " ⚠️"
        
    if is_overlap:
        tags.append("OVERLAP")
        icons += " 💠"

    # Specific icon for setup type if not already decorated
    if stype == "Momentum 🚀" and "🚀" not in icons: icons += " 🚀"
    if stype == "Pullback 🟢" and "🟢" not in icons: icons += " 🟢"
    if stype == "Vol Contraction 💎" and "💎" not in icons: icons += " 💎"

    ctx_rows.append(
        {
            "Tag": icons.strip(),
            "Symbol": sym,
            "Setup": stype,
            "Tier": str(r.get("tier", "")),
            "Score": float(r.get("score", 0.0)),
            "Category": str(r.get("category_label", "")),
            "Streak": setup_streak,
            "Days in 20D": setup_days,
            "Quality Trend(5)": qtrend,
            "LTP": float(r.get("ltp", 0.0)),
            "Quality History": qhist.tolist(),
            "Entry": float(r.get("suggested_entry", 0.0)),
            "Stop": float(r.get("suggested_stop", 0.0)),
            "Target": float(r.get("target_price", 0.0)),
            "Size": int(r.get("position_size")) if pd.notna(r.get("position_size")) else 0,
            "Order": str(r.get("order_type", "N/A")),
            "Valid": str(r.get("valid_until", "N/A")),
            "Audit": str(r.get("audit_reason", "OK")),
            "Link": f"/Stock_Fundamentals?symbol={sym}",
            "Status Tag": ", ".join(tags) if tags else "ACTIVE",
        }
    )

dropped_rows = []
for sym, stype in dropped_keys:
    h_setup = hist20[(hist20["symbol"] == sym) & (hist20["setup_type"] == stype)]
    setup_days = int(h_setup["date"].nunique())
    label = "PAUSED" if setup_days >= 8 else "DROPPED"
    dropped_rows.append(
        {
            "Tag": "🔁" if label == "PAUSED" else "🔻",
            "Symbol": sym,
            "Setup": stype,
            "Days in 20D": setup_days,
            "Status Tag": label,
        }
    )

tradable_df = pd.DataFrame(ctx_rows).sort_values(
    ["Tier", "Score", "Streak"], ascending=[True, False, False]
) if ctx_rows else pd.DataFrame()
dropped_df = pd.DataFrame(dropped_rows).sort_values(
    ["Days in 20D", "Symbol"], ascending=[False, True]
) if dropped_rows else pd.DataFrame()

today_ist = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
stale_today = _is_trading_day(today_ist) and (latest_run_date != today_ist)

top1, top2, top3, top4 = _responsive_cols(4)
top1.metric("Tradable Today", int(len(tradable_df)))
top2.metric("Fresh Setups", int((tradable_df["Status Tag"].str.contains("NEW")).sum()) if not tradable_df.empty else 0)
top3.metric("Continuations", int((tradable_df["Status Tag"].str.contains("CONTINUATION")).sum()) if not tradable_df.empty else 0)
top4.metric("Dropped/Paused", int(len(dropped_df)))

st.subheader("📊 Sector Dominance")
if not tradable_df.empty:
    import plotly.express as px
    # Calculate counts and ensure we use 'Category' as the label
    # Use 'Category' as column name for clarity
    sector_summary = tradable_df.groupby("Category").size().reset_index(name="Setup Count")
    sector_summary = sector_summary.sort_values("Setup Count", ascending=True) # Ascending for better display in horizontal bar
    
    fig_sector = px.bar(
        sector_summary,
        x="Setup Count",
        y="Category",
        orientation="h",
        color="Setup Count",
        color_continuous_scale="Turbo",
        template="plotly_dark",
        height=min(300, 100 + 40 * len(sector_summary)),
        text="Setup Count", # Show labels on bars
    )
    fig_sector.update_layout(
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
        xaxis_title="Count of Tradable Setups",
        yaxis_title=None,
    )
    fig_sector.update_traces(textposition='outside')
    st.plotly_chart(fig_sector, use_container_width=True, config={"displayModeBar": False})

with st.expander("ℹ️ How to Use", expanded=(view_mode == "Summary")):
    st.markdown(
        "- Tradable Today: names passing all gates in latest snapshot.\n"
        "- Setup Streak: consecutive trading-day streak for same setup.\n"
        "- 🆕 New: first appearance in current 20D window (Actionable Trigger).\n"
        "- ⏩ Continuation: breakout that remains within striking distance after Day 0.\n"
        "- 💠 Overlap: stock triggering multiple technical setups simultaneously (High Probability).\n"
        "- 🔻 Dropped: tradable yesterday, not today. If holding: reassess risk.\n"
        "- 🔁 Paused: strong 20D presence but currently cooling off. Capped at 7 days for pullbacks.\n"
        "- ⚠️ Fading: still tradable but quality trend has declined significantly."
    )

if orphan_master:
    show = ", ".join(orphan_master[:12])
    suffix = "" if len(orphan_master) <= 12 else f" +{len(orphan_master)-12} more"
    st.warning(f"⚠️ Not in current master universe (excluded from streak math): {show}{suffix}")

if stale_today:
    st.warning(f"Snapshot is stale for trading day {today_ist.date()} (latest run: {latest_run_date.date()}).")
elif latest_run_status == "FAILED":
    st.warning("Latest full refresh failed. Snapshot date is current but generation steps reported errors.")

st.caption(f"Latest run: {latest_run_date.date()} | Lookback days loaded: {len(lookback_dates)}")

if tradable_df.empty:
    st.info("No tradable setups in latest snapshot.")
else:
    show_df = tradable_df.copy()
    show_df["Score"] = show_df["Score"].map(lambda x: f"{x:.2f}")
    show_df["Quality Trend(5)"] = show_df["Quality Trend(5)"].map(lambda x: f"{x:+.2f}")
    st.dataframe(
        show_df,
        column_config={
            "Link": st.column_config.LinkColumn(
                "Symbol",
                help="Click to view Stock Fundamentals",
                validate="^/Stock_Fundamentals",
                display_text=r"^/Stock_Fundamentals\?symbol=(.*)$",
            ),
            "Entry": st.column_config.NumberColumn("Entry", format="%.2f", help="Strict trigger price"),
            "Stop": st.column_config.NumberColumn("Stop", format="%.2f"),
            "Target": st.column_config.NumberColumn("Target", format="%.2f"),
            "Size": st.column_config.NumberColumn("Size", format="%d", help="Shares (Capped at 20% capital)"),
            "Valid": st.column_config.TextColumn("Until", width="small"),
            "Audit": st.column_config.TextColumn("Audit", help="Risk/Validity check status"),
            "Quality History": st.column_config.LineChartColumn(
                "Quality (5D)",
                help="5-day quality score trend",
                y_min=0,
                y_max=1,
            ),
            "Score": st.column_config.TextColumn("Score"),
            "Quality Trend(5)": st.column_config.TextColumn("Q-Trend"),
            "LTP": st.column_config.NumberColumn("LTP", format="%.2f", help="Last Traded Price"),
        },
        column_order=[
            "Tag", "Link", "Setup", "Audit", "LTP", "Entry", "Stop", "Target", "Size", "Order",
            "Valid", "Category", "Tier", "Score", "Quality History", "Streak", "Status Tag"
        ],
        width="stretch",
        hide_index=True,
    )

if not dropped_df.empty:
    st.markdown("**Dropped / Paused Since Previous Trading Day**")
    st.dataframe(
        _compact_table(dropped_df, ["Tag", "Symbol", "Setup", "Days in 20D", "Status Tag"]),
        width="stretch",
        hide_index=True,
    )
