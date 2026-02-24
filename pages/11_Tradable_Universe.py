import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from NSE_Config import NIFTY_200
from utils import setup_page, get_ui_detail_mode


setup_page("Tradable Universe")
view_mode = get_ui_detail_mode("Summary")
st.title("✅ Tradable Universe")
st.caption("Consolidated tradable setups across categories with 20-day context.")

SNAPSHOT_PATH = Path("data/snapshots/tradable_signals.parquet")
SNAPSHOT_META_PATH = Path("data/snapshots/tradable_signals_meta.json")
BASE_DIR = Path(__file__).resolve().parents[1]


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


def _write_tradable_heartbeat() -> None:
    run_date = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    SNAPSHOT_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_META_PATH.write_text(
        json.dumps(
            {
                "last_run_date": str(run_date.date()),
                "rows_written_today": None,
                "updated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
                "source": "tradable_universe_full_refresh",
            },
            indent=2,
        )
    )


ctl1, ctl2 = st.columns([1, 3])
with ctl1:
    if st.button("Run Full Refresh", width="stretch"):
        run_logs = []
        rc, out = _run_script("eod_pipeline.py")
        run_logs.append(f"$ scripts/eod_pipeline.py\n{out}")
        rc2, out2 = _run_script("alert_engine.py")
        run_logs.append(f"$ scripts/alert_engine.py\n{out2}")
        rc3, out3 = _run_script("data_trust_score.py")
        run_logs.append(f"$ scripts/data_trust_score.py\n{out3}")
        _write_tradable_heartbeat()
        if rc == 0 and rc2 == 0 and rc3 == 0:
            st.success("Full refresh completed.")
        else:
            st.warning("Full refresh completed with warnings/errors. Review logs below.")
        st.code("\n\n".join(run_logs)[-12000:], language="text")
        st.rerun()
with ctl2:
    st.caption("Runs EOD pipeline, alerts, and trust score, then updates today heartbeat.")


def _strip_ns(sym: str) -> str:
    s = str(sym or "").strip().upper()
    return s[:-3] if s.endswith(".NS") else s


def _is_trading_day(d: pd.Timestamp) -> bool:
    return int(d.weekday()) < 5


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
if SNAPSHOT_META_PATH.exists():
    try:
        meta = pd.read_json(SNAPSHOT_META_PATH, typ="series")
        meta_d = pd.to_datetime(meta.get("last_run_date"), errors="coerce")
        if not pd.isna(meta_d):
            latest_run_date = meta_d.normalize()
    except Exception:
        pass
lookback_dates = all_dates[-20:] if len(all_dates) >= 20 else all_dates
hist20 = hist[hist["date"].isin(lookback_dates)].copy()
today_rows = hist[hist["date"] == latest_date].copy()
prev_date = all_dates[-2] if len(all_dates) >= 2 else None
prev_rows = hist[hist["date"] == prev_date].copy() if prev_date is not None else pd.DataFrame(columns=hist.columns)

master_universe = {_strip_ns(s) for s in NIFTY_200}
orphan_master = sorted(set(hist20["symbol"].unique()) - master_universe)
if orphan_master:
    hist20 = hist20[~hist20["symbol"].isin(orphan_master)].copy()
    today_rows = today_rows[~today_rows["symbol"].isin(orphan_master)].copy()
    prev_rows = prev_rows[~prev_rows["symbol"].isin(orphan_master)].copy()

today_keys = set(zip(today_rows["symbol"], today_rows["setup_type"]))
prev_keys = set(zip(prev_rows.get("symbol", pd.Series(dtype=str)), prev_rows.get("setup_type", pd.Series(dtype=str))))
dropped_keys = sorted(list(prev_keys - today_keys))

ctx_rows = []
for _, r in today_rows.iterrows():
    sym = str(r["symbol"])
    stype = str(r["setup_type"])
    h_setup = hist20[(hist20["symbol"] == sym) & (hist20["setup_type"] == stype)]
    h_sym = hist20[hist20["symbol"] == sym]
    setup_dates = sorted(h_setup["date"].unique().tolist())
    sym_dates = sorted(h_sym["date"].unique().tolist())
    setup_days = len(setup_dates)
    sym_days = len(sym_dates)
    setup_streak = _calc_streak(set(setup_dates), lookback_dates, latest_date)
    sym_streak = _calc_streak(set(sym_dates), lookback_dates, latest_date)
    qhist = pd.to_numeric(h_setup.get("quality_score"), errors="coerce").dropna().tail(5)
    qtrend = float(qhist.iloc[-1] - qhist.iloc[0]) if len(qhist) >= 3 else 0.0
    is_new = setup_days == 1
    is_fading = setup_days >= 8 and qtrend <= -0.06
    tags = []
    icons = ""
    if is_new:
        tags.append("NEW")
        icons += "🆕"
    if is_fading:
        tags.append("FADING")
        icons += " ⚠️"
    ctx_rows.append(
        {
            "Tag": icons.strip(),
            "Symbol": sym,
            "Setup": stype,
            "Tier": str(r.get("tier", "")),
            "Score": float(r.get("score", 0.0)),
            "Quality": float(r.get("quality_score", 0.0)),
            "Quality Band": str(r.get("quality_band", "")),
            "Category": str(r.get("category_label", "")),
            "Setup Streak": setup_streak,
            "Symbol Streak": sym_streak,
            "Days in 20D": setup_days,
            "Symbol Days 20D": sym_days,
            "Quality Trend(5)": qtrend,
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
    ["Score", "Quality", "Setup Streak"], ascending=[False, False, False]
) if ctx_rows else pd.DataFrame()
dropped_df = pd.DataFrame(dropped_rows).sort_values(
    ["Days in 20D", "Symbol"], ascending=[False, True]
) if dropped_rows else pd.DataFrame()

today_ist = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
stale_today = _is_trading_day(today_ist) and (latest_run_date != today_ist)

top1, top2, top3, top4 = st.columns(4)
top1.metric("Tradable Today", int(len(tradable_df)))
top2.metric("New Entrants", int((tradable_df["Status Tag"] == "NEW").sum()) if not tradable_df.empty else 0)
top3.metric("Fading", int((tradable_df["Status Tag"].str.contains("FADING")).sum()) if not tradable_df.empty else 0)
top4.metric("Dropped/Paused", int(len(dropped_df)))

with st.expander("ℹ️ How to Use", expanded=(view_mode == "Summary")):
    st.markdown(
        "- Tradable Today: names passing all gates in latest snapshot.\n"
        "- Setup Streak: consecutive trading-day streak for same setup.\n"
        "- Days in 20D: total setup appearances in last 20 trading days.\n"
        "- 🆕 New: first appearance in current 20D window (alert state; trigger may still take 1-2 sessions).\n"
        "- 🔻 Dropped: tradable yesterday, not today. If holding: reassess risk. If watching: remove from active list.\n"
        "- 🔁 Paused Leader: strong 20D presence but currently off-list; watch for re-entry.\n"
        "- ⚠️ Fading: still tradable but quality trend has declined; monitor closely before fresh sizing."
    )

if orphan_master:
    show = ", ".join(orphan_master[:12])
    suffix = "" if len(orphan_master) <= 12 else f" +{len(orphan_master)-12} more"
    st.warning(f"⚠️ Not in current master universe (excluded from streak math): {show}{suffix}")

if stale_today:
    st.warning(f"Snapshot is stale for trading day {today_ist.date()} (latest run: {latest_run_date.date()}).")

st.caption(f"Latest run: {latest_run_date.date()} | Lookback days loaded: {len(lookback_dates)}")

if tradable_df.empty:
    st.info("No tradable setups in latest snapshot.")
else:
    show_df = tradable_df.copy()
    show_df["Score"] = show_df["Score"].map(lambda x: f"{x:.2f}")
    show_df["Quality"] = show_df["Quality"].map(lambda x: f"{x:.2f}")
    show_df["Quality Trend(5)"] = show_df["Quality Trend(5)"].map(lambda x: f"{x:+.2f}")
    st.dataframe(show_df, width="stretch", hide_index=True)

if not dropped_df.empty:
    st.markdown("**Dropped / Paused Since Previous Trading Day**")
    st.dataframe(dropped_df, width="stretch", hide_index=True)
