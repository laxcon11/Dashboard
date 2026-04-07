"""
Tradable Universe Full Refresh
Scans ALL preset watchlists + sector categories using the same
scoring pipeline as the Swing Rankings page.  Writes combined
tradable_signals.parquet for the Tradable Universe page.

Usage:
    python scripts/tradable_universe_refresh.py [--strictness Balanced]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import analytics
from config import BREAKOUT_WINDOW, ATR_PERIOD
from data_fetch import batch_download
from indicators import calculate_rsi, calculate_ema, calculate_atr
from NSE_Config import NIFTY_200, PRESET_WATCHLISTS, SECTOR_CATEGORIES, NSE_SECTOR_INDICES
import scoring
from regime_state import load_regime_snapshot
from trading_calendar import is_nse_trading_day

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SNAPSHOT_PATH = Path("data/snapshots/tradable_signals.parquet")
SNAPSHOT_META_PATH = Path("data/snapshots/tradable_signals_meta.json")
SNAPSHOT_COLS = [
    "date", "symbol", "setup_type", "tier", "score", "quality_score",
    "quality_band", "regime", "liquidity", "category_label",
    "is_continuation", "is_overlap", "ltp",
    "suggested_entry", "suggested_stop", "target_price", 
    "position_size", "order_type", "valid_until", "audit_reason"
]
STATUS_PATH = Path("data/snapshots/tradable_refresh_status.json")


def _update_status(progress: int, message: str, status: str = "RUNNING"):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps({
        "progress": progress,
        "message": message,
        "status": status,
        "updated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
    }, indent=2))

# Strictness configs and helpers moved to scoring.py


def _strip_ns(sym: str) -> str:
    s = str(sym or "").strip().upper()
    return s[:-3] if s.endswith(".NS") else s


# ── Regime & liquidity from snapshot ──────────────────────────
def _derive_regime_and_liquidity(
    nifty_df: pd.DataFrame | None,
    bank_df: pd.DataFrame | None,
    selected_data: dict[str, pd.DataFrame],
    cfg: dict,
) -> tuple[str, str, bool, bool, float]:
    """Return (regime_label, liquidity_label, regime_gate, liquidity_gate, regime_adj)."""
    # Breadth from the selected stocks
    advances, declines = 0, 0
    for sym, df in selected_data.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue
        close = pd.to_numeric(df["Close"], errors="coerce").dropna()
        if len(close) >= 2 and close.iloc[-2] != 0:
            chg = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2]) * 100
            if chg > 0.1:
                advances += 1
            elif chg < -0.1:
                declines += 1

    breadth_ratio = (advances / declines) if declines > 0 else (float(advances) if advances > 0 else 0.0)

    # Regime
    regime_score = scoring.trend_signal(nifty_df) + scoring.trend_signal(bank_df)
    if regime_score >= 1 and breadth_ratio >= cfg["risk_on_breadth"]:
        regime_label = "🟢 Risk On"
        regime_adj = 0.7
    elif regime_score <= -1 and breadth_ratio <= cfg["risk_off_breadth"]:
        regime_label = "🔴 Risk Off"
        regime_adj = -1.0
    else:
        regime_label = "🟡 Neutral"
        regime_adj = 0.0
    regime_gate = regime_label != "🔴 Risk Off"

    # Liquidity
    liq_score = 0
    liq_score += 1 if breadth_ratio >= 1.05 else -1
    liq_score += 1 if advances > declines else -1
    liq_score += 1 if scoring.trend_signal(nifty_df) >= 0 else -1
    liq_score += 1 if scoring.trend_signal(bank_df) >= 0 else -1
    if liq_score >= 2:
        liquidity_label = "🟢 Healthy"
        liquidity_gate = True
    elif liq_score >= 0:
        liquidity_label = "🟡 Neutral"
        liquidity_gate = True
    else:
        liquidity_label = "🔴 Tight"
        liquidity_gate = False

    return regime_label, liquidity_label, regime_gate, liquidity_gate, regime_adj


def _get_next_trading_day(start_date: pd.Timestamp, n: int) -> pd.Timestamp:
    """Find the Nth trading day from start_date (exclusive)."""
    curr = start_date
    found = 0
    while found < n:
        curr += pd.Timedelta(days=1)
        if is_nse_trading_day(curr):
            found += 1
    return curr


# ── Score a batch of symbols ──────────────────────────────────
def score_symbols(
    symbols: list[str],
    all_data: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame | None,
    cfg: dict,
    regime_gate: bool,
    liquidity_gate: bool,
    regime_adj: float,
    hist_df: pd.DataFrame = pd.DataFrame(),
) -> pd.DataFrame:
    """
    Apply the full swing-ranking scoring pipeline to a list of symbols.
    Returns a DataFrame of rows that pass A+/A + hard gate.
    """
    raw_rows = []
    for symbol in symbols:
        # Reset variables to avoid stale data leakage
        price, rs, rs_ema3, rs_blend = np.nan, np.nan, np.nan, np.nan
        vol_ratio, rsi, dist_ema20 = np.nan, np.nan, np.nan
        trend_bull, breakout, nr7, inside_day = False, False, False, False
        ema20, ema50, atr14 = np.nan, np.nan, np.nan
        dd_penalty, streak_penalty = 1.0, 1.0
        momentum_pass, pullback_pass, vol_contract_pass = False, False, False
        is_breakout_continuation, is_overlap = False, False
        
        df = all_data.get(symbol)
        if df is None or len(df) < 50:
            continue
        try:
            close = pd.to_numeric(df["Close"], errors="coerce").dropna()
            if close.empty:
                continue
            price = float(close.iloc[-1])
            if price <= 0:
                continue

            vol_ratio = analytics.calculate_volume_ratio(df, adjust_live=False)
            rs = analytics.calculate_relative_strength(df, nifty_df, period=20)
            rs_ema3 = scoring.rs_spread_ema3(df, nifty_df)
            rsi = calculate_rsi(df).iloc[-1] if len(df) > 14 else np.nan
            ema20_series = calculate_ema(df, 20)
            ema20 = ema20_series.iloc[-1]
            ema50 = calculate_ema(df, 50).iloc[-1]
            atr_series = calculate_atr(df, ATR_PERIOD) if len(df) > ATR_PERIOD else pd.Series(dtype=float)
            atr14 = atr_series.iloc[-1] if len(atr_series) > 0 else np.nan
            trend_bull = bool(price > ema20 > ema50)
            breakout = analytics.detect_breakout(df)
            nr7 = analytics.detect_nr7(df)
            dist_ema20 = ((price - ema20) / ema20 * 100) if ema20 else 0
            inside_day = bool(
                len(df) >= 2
                and (df["High"].iloc[-1] <= df["High"].iloc[-2])
                and (df["Low"].iloc[-1] >= df["Low"].iloc[-2])
            )
            atr_pct = ((atr14 / price) * 100.0) if (price and pd.notna(atr14) and atr14 > 0) else np.nan

            # New metrics for Correction & Momentum Protection
            high_20d = float(df["High"].tail(20).max())
            drawdown = (high_20d - price) / high_20d if high_20d > 0 else 0.0
            
            # Calculate consecutive red days (Close < Prev Close)
            diffs = close.diff().dropna()
            consecutive_red = 0
            for val in reversed(diffs.values):
                if val < 0:
                    consecutive_red += 1
                else:
                    break
            
            dd_penalty = scoring.drawdown_penalty(price, high_20d)
            streak_penalty = scoring.streak_penalty(consecutive_red)

            # Relative std
            rel_std = np.nan
            if nifty_df is not None and "Close" in nifty_df.columns:
                merged = pd.concat(
                    [close.rename("s"), nifty_df["Close"].dropna().rename("b")], axis=1
                ).dropna()
                if len(merged) >= 30:
                    rel_ret = merged["s"].pct_change() - merged["b"].pct_change()
                    rel_std = rel_ret.tail(20).std()

            trend_align = 1.0 if trend_bull else 0.0
            vol_quality = scoring.clip01(vol_ratio / 2.0)
            rs_blend = (0.7 * rs) + (0.3 * rs_ema3)

            # Setup pass
            # Phase 8: Volume Gate for Momentum (>= 1.2)
            momentum_pass = bool(trend_bull and breakout and (vol_ratio >= 1.2) and (rsi >= 52) and (rsi <= 78))
            pullback_pass = bool(trend_bull and (-2.5 <= dist_ema20 <= 1.5) and (40 <= rsi <= 58) and (not breakout))
            vol_contract_pass = bool(nr7 and inside_day and (abs(dist_ema20) <= 4.0) and (pd.isna(atr_pct) or atr_pct <= 4.0))

            is_breakout_continuation = False
            # Phase 8: Breakout Persistence (Continuation)
            # If it broke out yesterday and is consolidating within 2.5% of the high, keep it.
            if not momentum_pass and not pullback_pass and not vol_contract_pass:
                if not hist_df.empty:
                    s_key = _strip_ns(symbol)
                    p_data = hist_df[hist_df["symbol"] == s_key]
                    if not p_data.empty:
                        # Get most recent entry
                        p_last = p_data.sort_values("date").iloc[-1]
                        # If it was a momentum setup recently (within 2 sessions)
                        age = (pd.Timestamp.now().normalize() - p_last["date"]).days
                        if p_last["setup_type"] == "Momentum 🚀" and age <= 3:
                            # Consolidation Check: must be within striking distance of high
                            # and not in a deep drawdown
                            if drawdown <= 0.03: # Within 3% of 20d high
                                momentum_pass = True
                                is_breakout_continuation = True
                                log.debug("Persistence: Keeping %s (Breakout Continuation)", symbol)

            # Phase 8: Overlap detection
            is_overlap = bool((int(momentum_pass) + int(pullback_pass) + int(vol_contract_pass)) > 1)

            # Phase 8: Pullback Maturity Cap
            # If it has been a pullback for > 7 days, drop it to 'PAUSED' (by failing the pass here)
            if pullback_pass and not hist_df.empty:
                s_key = _strip_ns(symbol)
                p_data = hist_df[(hist_df["symbol"] == s_key) & (hist_df["setup_type"] == "Pullback 🟢")]
                if not p_data.empty:
                    # Sort by date descending
                    p_dates = sorted(p_data["date"].unique(), reverse=True)
                    # Check streak
                    streak = 0
                    # Simulating the UI streak calc
                    # This is imperfect because we don't have the full date vector easily here, 
                    # but we can count recent entries.
                    recent_dates = [pd.Timestamp.now().normalize() - pd.Timedelta(days=i) for i in range(1, 15)]
                    for rd in recent_dates:
                        if rd in p_dates:
                            streak += 1
                        else:
                            # If it's a trading day and missing, streak ends
                            if is_nse_trading_day(rd):
                                break
                    if streak >= 7:
                        log.debug("Maturity: Capping %s (Pullback streak %d >= 7)", symbol, streak)
                        pullback_pass = False

            if not (momentum_pass or pullback_pass or vol_contract_pass):
                continue

            # Heavy gate: Reject if drawdown > 10% (strict correction limit)
            if pd.isna(drawdown) or drawdown >= 0.10:
                continue
            
            # Final Sanity Check: Ensure price and EMAs are semi-valid
            if pd.isna(price) or pd.isna(ema20) or pd.isna(ema50):
                continue

            hard_gate = bool(regime_gate and liquidity_gate)

            raw_rows.append({
                "symbol": symbol,
                "price": price,
                "rs": rs,
                "rs_ema3": rs_ema3,
                "rs_blend": rs_blend,
                "vol_ratio": vol_ratio,
                "rsi": rsi,
                "dist_ema20": dist_ema20,
                "trend_bull": trend_bull,
                "breakout": breakout,
                "nr7": nr7,
                "inside_day": inside_day,
                "trend_align": trend_align,
                "vol_quality": vol_quality,
                "rel_std": rel_std,
                "momentum_pass": momentum_pass,
                "pullback_pass": pullback_pass,
                "vol_contract_pass": vol_contract_pass,
                "is_continuation": is_breakout_continuation,
                "is_overlap": is_overlap,
                "hard_gate": hard_gate,
                "dd_penalty": dd_penalty,
                "streak_penalty": streak_penalty,
                "mom_base": analytics.calculate_momentum_score(df, nifty_df),
                "pb_base": analytics.calculate_pullback_score(df, nifty_df),
                "atr14": atr14,
                "ema20": ema20,
                "ema50": ema50,
                "df_local": df # Pass for execution calc
            })
        except Exception as exc:
            log.debug("Error scoring %s: %s", symbol, exc)

    if not raw_rows:
        return pd.DataFrame()

    sdf = pd.DataFrame(raw_rows)

    # RS stability calibration
    rel_std_s = pd.to_numeric(sdf["rel_std"], errors="coerce").dropna()
    if len(rel_std_s) >= 20:
        q10 = float(rel_std_s.quantile(0.10))
        q90 = float(rel_std_s.quantile(0.90))
        denom = max(q90 - q10, 1e-6)
        rs_stab_slope = 0.8 / denom
        rs_stab_intercept = 0.9 + (rs_stab_slope * q10)
    else:
        rs_stab_slope = 35.0
        rs_stab_intercept = 1.0

    sdf["rs_stability"] = (
        rs_stab_intercept - (rs_stab_slope * pd.to_numeric(sdf["rel_std"], errors="coerce"))
    ).clip(lower=0.0, upper=1.0).fillna(0.5)
    sdf["rs_quality"] = ((pd.to_numeric(sdf["rs_blend"], errors="coerce").fillna(0.0) + 10.0) / 20.0).clip(0.0, 1.0)
    sdf["quality_score_base"] = (
        0.40 * sdf["vol_quality"] + 0.30 * sdf["rs_quality"] + 0.30 * sdf["rs_stability"]
    )
    rs_floor_penalty = float(cfg.get("rs_floor_penalty", 0.10))
    sdf["rs_floor_penalty"] = np.where(
        sdf["rs_blend"] < float(cfg.get("min_rs", -3.0)), rs_floor_penalty, 0.0
    )
    # Apply Drawdown and Streak penalties to the final quality score
    # These are in points (0-10 scale), so we divide by 10 to normalize to 0-1 quality score
    sdf["quality_score"] = (
        sdf["quality_score_base"] - sdf["rs_floor_penalty"] - (sdf["dd_penalty"] / 10.0) - (sdf["streak_penalty"] / 10.0)
    ).clip(0.0, 1.0)
    sdf["quality_band"] = np.where(sdf["quality_score"] >= 0.65, "Strong", np.where(sdf["quality_score"] >= 0.45, "Pass-Caution", "Blocked"))
    sdf["quality_gate"] = (sdf["vol_ratio"] >= float(cfg["min_vol_ratio"])) & (sdf["quality_score"] >= 0.45)
    sdf["hard_gate"] = sdf["hard_gate"] & sdf["quality_gate"]

    # Percentile ranks
    sdf["rs_pct"] = sdf["rs"].rank(pct=True).fillna(0.5)
    sdf["vol_pct"] = sdf["vol_ratio"].rank(pct=True).fillna(0.5)

    # Momentum Score
    sdf["momentum_score"] = (
        3.0 + (0.55 * sdf["mom_base"])
        + (sdf["breakout"] | sdf["is_continuation"]).apply(lambda x: 1.6 if x else -0.8)
        + sdf["trend_bull"].apply(lambda x: 1.2 if x else -1.0)
        + 2.3 * sdf["rs_pct"]
        + 1.6 * sdf["vol_pct"]
        + 1.0 * sdf["rs_stability"]
        + regime_adj
    ).apply(scoring.clamp_score)

    # Pullback Score
    sdf["pullback_score"] = (
        2.8 + (0.60 * sdf["pb_base"])
        + sdf["dist_ema20"].apply(lambda x: 1.4 if -2.5 <= x <= 1.5 else -0.6)
        + sdf["rsi"].apply(lambda x: 1.2 if 40 <= x <= 58 else -0.6)
        + sdf["trend_bull"].apply(lambda x: 1.0 if x else -0.8)
        + 1.8 * sdf["rs_pct"]
        + 1.1 * sdf["rs_stability"]
        + (regime_adj * 0.8)
    ).apply(scoring.clamp_score)

    # Volatility Score
    sdf["volatility_score"] = (
        1.8
        + sdf["nr7"].apply(lambda x: 2.8 if x else 0.0)
        + sdf["inside_day"].apply(lambda x: 1.2 if x else 0.0)
        + sdf["dist_ema20"].apply(lambda x: 1.3 if abs(x) <= 4 else -0.4)
        + 1.5 * sdf["vol_pct"]
        + 1.0 * sdf["rs_pct"]
        + 0.9 * sdf["rs_stability"]
        + (regime_adj * 0.5)
    ).apply(scoring.clamp_score)

    def _setup_tier(score: float) -> str:
        return scoring.setup_tier(score, cfg)

    # Build family rows
    result_rows = []
    for _, row in sdf.iterrows():
        if not row["hard_gate"]:
            continue
        families = []
        if row["momentum_pass"]:
            families.append(("Momentum 🚀", row["momentum_score"]))
        if row["pullback_pass"]:
            families.append(("Pullback 🛒", row["pullback_score"]))
        if row["vol_contract_pass"]:
            families.append(("Volatility Contraction 🌀", row["volatility_score"]))
        for setup_type, score in families:
            tier = _setup_tier(score)
            if tier not in ("A+", "A"):
                continue
            
            df_local = row["df_local"]
            curr_p = float(row["price"])
            
            if "BSE" in str(row["symbol"]) or "TITAN" in str(row["symbol"]):
                log.info("DEBUG: symbol=%s setup=%s curr_p=%s", row["symbol"], setup_type, curr_p)
            
            # Determine execution parameters based on setup
            entry, stop, order_t, audit = np.nan, np.nan, "N/A", "OK"
            
            # 1. Momentum / Breakout 🚀
            if setup_type == "Momentum 🚀":
                # Use standard BREAKOUT_WINDOW (20) to align with detection
                prev_high = float(df_local["High"].iloc[:-1].tail(BREAKOUT_WINDOW).max())
                entry = max(prev_high * 1.002, prev_high + row["atr14"] * 0.1)
                # Structural stop
                struct_stop = float(df_local["Low"].iloc[-1])
                # Unified Ceiling Guard
                stop = scoring.get_unified_stop_loss(entry, struct_stop, row["atr14"])
                
                # Logic Guard: If already far above entry, mark as Extended
                if curr_p > entry * 1.03:
                    audit = "EXTENDED_MOMENTUM"
                
                # Order type: If price already > entry, it's a MARKET/LIMIT Buy, not STOP BUY
                order_t = "STOP BUY" if curr_p < entry else "BUY"
            
            # 2. Pullback 🟢
            elif setup_type == "Pullback 🛒":
                recent_pb_low = scoring.pullback_leg_low(df_local)
                ema20 = float(row["ema20"])
                entry = min(ema20, recent_pb_low)
                struct_stop = float(row["ema50"])
                # Unified Ceiling Guard
                stop = scoring.get_unified_stop_loss(entry, struct_stop, row["atr14"])
                order_t = "LIMIT BUY"
                # Pullback Guard: only if current price is within 2% of entry
                if curr_p > entry * 1.02:
                    audit = "PRICE_TOO_FAR_FROM_ENTRY"

            # 3. Volatility Contraction 🌀 (VCP)
            elif setup_type == "Volatility Contraction 🌀":
                swing_high_10d = float(df_local["High"].tail(10).max())
                entry = swing_high_10d
                # Contraction low proxy - ensure it's not NaN
                c_low = scoring.pullback_leg_low(df_local)
                if np.isnan(c_low):
                    c_low = float(df_local["Low"].tail(10).min())
                # Unified Ceiling Guard
                stop = scoring.get_unified_stop_loss(entry, c_low, row["atr14"])
                order_t = "STOP BUY"

            # Shared Guards & Calcs
            if np.isnan(entry) or np.isnan(stop):
                audit = "MISSING_PARAMETERS"
            
            if not np.isnan(entry):
                entry = round(float(entry), 2)
            if not np.isnan(stop):
                stop = round(float(stop), 2)
                
            risk_dist = entry - stop if (not np.isnan(entry) and not np.isnan(stop)) else 0
            if (not np.isnan(entry) and not np.isnan(stop)) and (risk_dist <= 0 or entry <= 0):
                if audit == "OK": # Don't override price-guards
                    audit = "INVALID_RISK_PARAMETERS"
            
            # 4. Wide Stop Guard (>10% Risk)
            if not np.isnan(entry) and entry > 0 and (risk_dist / entry) > 0.10:
                if audit == "OK":
                    audit = "WIDE_STOP_LOSS"
            
            if "BSE" in str(row["symbol"]):
                 pass
            
            target = round(entry + 2 * risk_dist, 2) if (risk_dist > 0 and not np.isnan(entry)) else np.nan
            
            # Position Sizing
            # TODO: Load from portfolio_rules.json if available
            port_val = 1000000.0
            risk_pct = 0.01
            cash_risk = port_val * risk_pct
            
            raw_size = cash_risk / risk_dist if risk_dist > 0 else 0
            size_cap = (port_val * 0.2) / entry if entry > 0 else 0
            
            # Use float min then convert to int safely
            final_size = min(float(raw_size), float(size_cap)) if audit == "OK" else 0.0
            pos_size = int(final_size) if not np.isnan(final_size) else 0
            
            # Validity
            valid_until = _get_next_trading_day(pd.Timestamp.now().normalize(), 3)

            result_rows.append({
                "symbol": _strip_ns(str(row["symbol"])),
                "setup_type": setup_type,
                "tier": tier,
                "score": round(float(score), 2),
                "quality_score": round(float(row["quality_score"]), 4),
                "quality_band": str(row["quality_band"]),
                "is_continuation": bool(row["is_continuation"]),
                "is_overlap": bool(row["is_overlap"]),
                "ltp": round(float(row.get("price", np.nan)), 2) if pd.notna(row.get("price")) else np.nan,
                "suggested_entry": round(entry, 2),
                "suggested_stop": round(stop, 2),
                "target_price": round(target, 2),
                "position_size": pos_size,
                "order_type": order_t,
                "valid_until": valid_until.strftime("%Y-%m-%d"),
                "audit_reason": audit
            })

    return pd.DataFrame(result_rows) if result_rows else pd.DataFrame()


def _build_primary_category(
    preset_watchlists: dict[str, list[str]],
    sector_categories: dict[str, list[str]],
) -> dict[str, str]:
    """Map each symbol to its *first* matching category (presets first)."""
    sym_to_cat: dict[str, str] = {}
    # Presets take priority
    for name, stocks in preset_watchlists.items():
        if name == "NIFTY 200":
            continue
        label = f"Preset: {name}"
        for s in stocks:
            key = _strip_ns(s)
            if key not in sym_to_cat:
                sym_to_cat[key] = label
    # Then sectors
    for name, stocks in sector_categories.items():
        label = f"Sector: {name}"
        for s in stocks:
            key = _strip_ns(s)
            if key not in sym_to_cat:
                sym_to_cat[key] = label
    return sym_to_cat


# ── Main ──────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Tradable Universe Full Refresh")
    parser.add_argument("--strictness", default="Balanced", choices=["Strict", "Balanced", "Aggressive"])
    args = parser.parse_args()
    # Map 'Strict' to 'Conservative' if needed by scoring.py
    internal_strictness = "Conservative" if args.strictness == "Strict" else args.strictness
    cfg = scoring.STRICTNESS_CFG[internal_strictness]

    run_date = pd.Timestamp.now(tz="Asia/Kolkata").normalize().tz_localize(None)
    log.info("Tradable Universe refresh starting (strictness=%s, date=%s)", args.strictness, run_date.date())
    _update_status(0, "Starting refresh...")

    # 1) Build combined symbol universe — fully deduped
    _update_status(10, "Building symbol universe...")
    all_symbols: set[str] = set()
    for name, stocks in PRESET_WATCHLISTS.items():
        if name == "NIFTY 200":
            continue
        all_symbols.update(stocks)
    for stocks in SECTOR_CATEGORIES.values():
        all_symbols.update(stocks)
    all_symbols.update(NIFTY_200)
    unique_list = sorted(all_symbols)

    # Primary category map: sym → first matching preset/sector
    sym_to_category = _build_primary_category(PRESET_WATCHLISTS, SECTOR_CATEGORIES)

    log.info("Downloading data for %d unique symbols", len(unique_list))
    _update_status(20, f"Downloading data for {len(unique_list)} symbols...")

    # 2) Download once - 1y to maintain deep history for 200DMA
    all_data = batch_download(unique_list, period="1y")
    log.info("Downloaded %d / %d symbols", len([s for s in all_data if all_data[s] is not None and not all_data[s].empty]), len(unique_list))

    # Also download indices
    index_syms = ["^NSEI", "^NSEBANK"]
    idx_data = batch_download(index_syms, period="1y")
    nifty_df = idx_data.get("^NSEI")
    bank_df = idx_data.get("^NSEBANK")
    _update_status(60, "Deriving regime & liquidity...")

    # 3) Derive regime & liquidity from full universe
    regime_label, liquidity_label, regime_gate, liquidity_gate, regime_adj = _derive_regime_and_liquidity(
        nifty_df, bank_df, all_data, cfg
    )
    log.info("Regime: %s | Liquidity: %s | regime_adj=%.1f", regime_label, liquidity_label, regime_adj)
    _update_status(70, "Scoring symbols...")

    # 4) Score ALL symbols in one pass (no per-category loop)
    hist_for_scoring = pd.DataFrame()
    if SNAPSHOT_PATH.exists():
        try:
            hist_for_scoring = pd.read_parquet(SNAPSHOT_PATH)
            hist_for_scoring["date"] = pd.to_datetime(hist_for_scoring["date"]).dt.normalize()
            hist_for_scoring["symbol"] = hist_for_scoring["symbol"].map(_strip_ns)
        except Exception:
            pass

    tradable_df = score_symbols(unique_list, all_data, nifty_df, cfg, regime_gate, liquidity_gate, regime_adj, hist_df=hist_for_scoring)

    if tradable_df.empty:
        log.info("No tradable setups found.")
        _update_status(100, "No setups found.", status="SUCCESS")
        _write_meta(run_date, 0, "SUCCESS")
        return 0

    _update_status(90, "Finalizing snapshot...")
    # Assign primary category to each symbol
    tradable_df["category_label"] = tradable_df["symbol"].map(
        lambda s: sym_to_category.get(s, "NIFTY 200")
    )
    # Deduplicate: one row per symbol+setup_type (keep highest score)
    tradable_df = tradable_df.sort_values("score", ascending=False).drop_duplicates(
        subset=["symbol", "setup_type"], keep="first"
    )

    log.info("Tradable setups: %d (unique symbol+setup pairs)", len(tradable_df))

    # 5) Build snapshot rows
    snap = tradable_df.copy()
    snap["date"] = run_date
    snap["regime"] = regime_label
    snap["liquidity"] = liquidity_label
    snap = snap[SNAPSHOT_COLS]

    # 6) Append-deduplicate parquet
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SNAPSHOT_PATH.exists():
        try:
            hist = pd.read_parquet(SNAPSHOT_PATH)
        except Exception:
            hist = pd.DataFrame(columns=SNAPSHOT_COLS)
    else:
        hist = pd.DataFrame(columns=SNAPSHOT_COLS)

    hist = pd.concat([hist, snap], ignore_index=True)
    hist["date"] = pd.to_datetime(hist["date"], errors="coerce").dt.normalize()
    hist = hist.dropna(subset=["date", "symbol", "setup_type"])
    hist = hist.drop_duplicates(subset=["date", "symbol", "setup_type"], keep="last")
    hist = hist[hist["date"] >= (run_date - pd.Timedelta(days=600))]
    hist = hist.sort_values(["date", "symbol", "setup_type"])
    hist.to_parquet(SNAPSHOT_PATH, index=False)

    log.info("Wrote %d rows to %s (today: %d)", len(hist), SNAPSHOT_PATH, len(snap))
    _update_status(100, "Refresh complete.", status="SUCCESS")
    _write_meta(run_date, len(snap), "SUCCESS")
    return 0


def _write_meta(run_date: pd.Timestamp, rows: int, status: str) -> None:
    SNAPSHOT_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_META_PATH.write_text(json.dumps({
        "last_run_date": str(run_date.date()),
        "rows_written_today": rows,
        "updated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": "tradable_universe_refresh",
        "run_status": status,
    }, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
