import math
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import (
    FRED_API_KEY,
    GIFT_NIFTY_MACRO_BADGE,
    GIFT_NIFTY_STRESS_FLAG_PCT,
    GIFT_NIFTY_SESSION_START_IST_HOUR,
    GIFT_NIFTY_COLLAPSE_IST_HOUR,
)
from data_fetch import batch_download, fetch_fred_series, fetch_india_vix, prepare_timeseries_for_chart
from gift_nifty import get_gift_nifty_snapshot, is_gift_session_active
from india_context import get_india_context_signals
from regime_model import load_regime_settings
from regime_state import save_regime_snapshot
from utils import (
    setup_page,
    render_key_observations,
    get_ui_detail_mode,
    render_source_freshness,
    render_regime_timeline_strip,
    render_decision_header,
)
from analytics import round_percentages_sum_to_100


setup_page("Macro Risk")
view_mode = get_ui_detail_mode("Summary")
st.title("🌍 India Macro Risk Dashboard")
st.caption("Configurable regime model combining Macro and Liquidity factors.")
_page_t0 = time.perf_counter()
_perf: dict[str, float] = {}

settings = load_regime_settings()
blend = settings["blend"]
macro_factors = settings["macro_factors"]
liquidity_factors = settings["liquidity_factors"]
REGIME_LOCK_FILE = Path("notes/regime_trend_lock.json")


def clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def normalize_weights(primary: float, secondary: float) -> tuple[float, float]:
    total = primary + secondary
    if total <= 0:
        return 0.5, 0.5
    return primary / total, secondary / total


def build_ratio_series(left: pd.Series, right: pd.Series) -> pd.Series:
    df = pd.concat([left.rename("left"), right.rename("right")], axis=1).ffill().dropna()
    if df.empty:
        return pd.Series(dtype=float)
    ratio = (df["left"] / df["right"]).replace([float("inf"), -float("inf")], pd.NA).dropna()
    return ratio


def with_offset(series: pd.Series, offset: int) -> pd.Series:
    if offset <= 0:
        return series
    if len(series) <= offset:
        return pd.Series(dtype=float)
    return series.iloc[:-offset]


def compute_series_signal(series: pd.Series, inverse: bool, fast_window: int, slow_window: int, fast_w: float, slow_w: float):
    s = series.dropna()
    minimum_required = max(fast_window + 1, slow_window + 2)
    if len(s) < minimum_required:
        return None

    fast_change_pct = ((s.iloc[-1] / s.iloc[-(fast_window + 1)]) - 1) * 100
    changes = (s.pct_change() * 100).dropna()
    fast_vol = changes.tail(60).std()
    if pd.isna(fast_vol) or fast_vol == 0:
        fast_score = 0.0 if abs(fast_change_pct) < 1e-9 else (1.0 if fast_change_pct > 0 else -1.0)
    else:
        fast_score = clip(fast_change_pct / (fast_vol * max(1.0, fast_window ** 0.5)), -2.0, 2.0)

    slow_ma = s.rolling(slow_window).mean().iloc[-1]
    if pd.isna(slow_ma) or slow_ma == 0:
        return None

    slow_dev_pct = ((s.iloc[-1] / slow_ma) - 1) * 100
    dev_hist = ((s / s.rolling(slow_window).mean()) - 1).dropna() * 100
    slow_vol = dev_hist.tail(120).std()
    if pd.isna(slow_vol) or slow_vol == 0:
        slow_score = 0.0 if abs(slow_dev_pct) < 1e-9 else (1.0 if slow_dev_pct > 0 else -1.0)
    else:
        slow_score = clip(slow_dev_pct / slow_vol, -2.0, 2.0)

    if inverse:
        fast_score *= -1
        slow_score *= -1

    combined = (fast_w * fast_score) + (slow_w * slow_score)
    combined = clip(combined, -2.0, 2.0)

    if combined > 0.2:
        sentiment = "Bullish"
    elif combined < -0.2:
        sentiment = "Bearish"
    else:
        sentiment = "Neutral"

    return {
        "fast": round(float(fast_score), 3),
        "slow": round(float(slow_score), 3),
        "combined": round(float(combined), 3),
        "sentiment": sentiment,
        "points": int(len(s)),
    }


fast_weight = float(blend.get("fast_weight", 0.4))
slow_weight = float(blend.get("slow_weight", 0.6))
impulse_influence = clip(float(blend.get("impulse_influence", 0.25)), 0.0, 0.6)
fast_window = int(blend.get("fast_window", 1))
slow_window = int(blend.get("slow_window", 10))
max_factor_weight = float(blend.get("max_factor_weight", 0.2))
neutral_band = float(blend.get("neutral_band", 0.35))
risk_on_threshold = float(blend.get("risk_on_threshold", 0.6))
risk_off_threshold = float(blend.get("risk_off_threshold", 0.6))
sofr_iorb_penalty_enabled = bool(blend.get("sofr_iorb_penalty_enabled", True))
sofr_iorb_warn_bps = max(0.0, float(blend.get("sofr_iorb_warn_bps", 5.0)))
sofr_iorb_full_penalty_bps = max(
    sofr_iorb_warn_bps + 0.1,
    float(blend.get("sofr_iorb_full_penalty_bps", 15.0)),
)
sofr_iorb_max_penalty = clip(float(blend.get("sofr_iorb_max_penalty", 0.25)), 0.0, 0.8)
sofr_iorb_persistence_days = max(1, int(blend.get("sofr_iorb_persistence_days", 3)))
sofr_iorb_persisted_max_penalty = clip(
    max(sofr_iorb_max_penalty, float(blend.get("sofr_iorb_persisted_max_penalty", 0.35))),
    0.0,
    0.9,
)
group_caps_cfg = blend.get("group_caps", {})
group_caps = {
    "Macro": clip(float(group_caps_cfg.get("Macro", 0.30)), 0.01, 1.0),
    "Liquidity": clip(float(group_caps_cfg.get("Liquidity", 0.35)), 0.01, 1.0),
    "Risk Appetite": clip(float(group_caps_cfg.get("Risk Appetite", 0.20)), 0.01, 1.0),
    "Rates/Currency": clip(float(group_caps_cfg.get("Rates/Currency", 0.20)), 0.01, 1.0),
    "Commodities": clip(float(group_caps_cfg.get("Commodities", 0.20)), 0.01, 1.0),
}

fast_slow_total = fast_weight + slow_weight
if fast_slow_total <= 0:
    fast_weight, slow_weight = 0.4, 0.6
else:
    fast_weight, slow_weight = fast_weight / fast_slow_total, slow_weight / fast_slow_total

enabled_macro = {k: v for k, v in macro_factors.items() if v.get("enabled", True)}
enabled_liquidity = {k: v for k, v in liquidity_factors.items() if v.get("enabled", True)}

required_symbols = set()
for factor in enabled_macro.values():
    if "symbol" in factor:
        required_symbols.add(factor["symbol"])
    if "ratio" in factor:
        required_symbols.update(factor["ratio"])

with st.spinner("Fetching market data..."):
    _t_market = time.perf_counter()
    market_data = batch_download(sorted(required_symbols), period="6mo")
    _perf["market_fetch_s"] = round(time.perf_counter() - _t_market, 3)

vix_price, vix_change = fetch_india_vix()

fred_raw = {}
if FRED_API_KEY:
    required_fred = set()
    for factor in enabled_liquidity.values():
        if "fred" in factor:
            required_fred.add(factor["fred"])
        if "fred_spread" in factor:
            required_fred.update(factor["fred_spread"])

    with st.spinner("Fetching liquidity data..."):
        _t_fred = time.perf_counter()
        fred_ids = sorted(required_fred)
        if fred_ids:
            workers = min(8, max(1, len(fred_ids)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(fetch_fred_series, sid, FRED_API_KEY, 365): sid for sid in fred_ids}
                for future in as_completed(futures):
                    sid = futures[future]
                    try:
                        fred_raw[sid] = future.result()
                    except Exception:
                        fred_raw[sid] = None
        _perf["fred_fetch_s"] = round(time.perf_counter() - _t_fred, 3)
else:
    st.warning("FRED API key not found. Liquidity factors may be unavailable.")


market_series_cache = {}
for symbol, df in market_data.items():
    if df is not None and not df.empty and "Close" in df.columns:
        close = df["Close"].dropna()
        if not close.empty:
            market_series_cache[symbol] = close

fred_series_cache = {}
for sid, df in fred_raw.items():
    if df is not None and not df.empty and {"date", "value"}.issubset(df.columns):
        series = df.set_index("date")["value"].dropna()
        if not series.empty:
            fred_series_cache[sid] = series


def resolve_macro_series(factor: dict, offset: int = 0) -> pd.Series:
    if factor.get("symbol") == "INDIAVIX":
        if vix_price is None:
            return pd.Series(dtype=float)
        # No proper historical series from NSE endpoint here; keep disabled by default.
        return pd.Series([vix_price], index=[pd.Timestamp.today()])

    if "symbol" in factor:
        series = market_series_cache.get(factor["symbol"], pd.Series(dtype=float))
        return with_offset(series, offset)

    if "ratio" in factor:
        left = market_series_cache.get(factor["ratio"][0], pd.Series(dtype=float))
        right = market_series_cache.get(factor["ratio"][1], pd.Series(dtype=float))
        ratio = build_ratio_series(left, right)
        return with_offset(ratio, offset)

    return pd.Series(dtype=float)


def resolve_liquidity_series(factor: dict, offset: int = 0) -> pd.Series:
    if "fred" in factor:
        series = fred_series_cache.get(factor["fred"], pd.Series(dtype=float))
        return with_offset(series, offset)

    if "fred_spread" in factor:
        left = fred_series_cache.get(factor["fred_spread"][0], pd.Series(dtype=float))
        right = fred_series_cache.get(factor["fred_spread"][1], pd.Series(dtype=float))
        spread_df = pd.concat([left.rename("left"), right.rename("right")], axis=1).ffill().dropna()
        if spread_df.empty:
            return pd.Series(dtype=float)
        spread = spread_df["left"] - spread_df["right"]
        return with_offset(spread, offset)

    return pd.Series(dtype=float)


def compute_sofr_iorb_penalty(offset: int = 0) -> dict:
    if not sofr_iorb_penalty_enabled:
        return {
            "enabled": False,
            "applied": 0.0,
            "spread_bps": None,
            "base_penalty": 0.0,
            "penalty_cap": 0.0,
            "persist_count": 0,
            "persist_active": False,
        }

    sofr = fred_series_cache.get("SOFR", pd.Series(dtype=float))
    iorb = fred_series_cache.get("IORB", pd.Series(dtype=float))
    spread_df = pd.concat([sofr.rename("sofr"), iorb.rename("iorb")], axis=1).ffill().dropna()
    if spread_df.empty:
        return {
            "enabled": True,
            "applied": 0.0,
            "spread_bps": None,
            "base_penalty": 0.0,
            "penalty_cap": sofr_iorb_max_penalty,
            "persist_count": 0,
            "persist_active": False,
        }

    spread = with_offset((spread_df["sofr"] - spread_df["iorb"]), offset)
    spread = spread.dropna()
    if spread.empty:
        return {
            "enabled": True,
            "applied": 0.0,
            "spread_bps": None,
            "base_penalty": 0.0,
            "penalty_cap": sofr_iorb_max_penalty,
            "persist_count": 0,
            "persist_active": False,
        }

    spread_bps = float(spread.iloc[-1] * 100.0)
    if spread_bps <= sofr_iorb_warn_bps:
        base_penalty = 0.0
    elif spread_bps >= sofr_iorb_full_penalty_bps:
        base_penalty = sofr_iorb_max_penalty
    else:
        ramp = (spread_bps - sofr_iorb_warn_bps) / (sofr_iorb_full_penalty_bps - sofr_iorb_warn_bps)
        base_penalty = sofr_iorb_max_penalty * clip(ramp, 0.0, 1.0)

    persist_count = 0
    for val in reversed((spread * 100.0).tolist()):
        if float(val) > sofr_iorb_warn_bps:
            persist_count += 1
        else:
            break

    persist_active = persist_count >= sofr_iorb_persistence_days
    penalty_cap = sofr_iorb_persisted_max_penalty if persist_active else sofr_iorb_max_penalty

    if spread_bps <= sofr_iorb_warn_bps:
        applied = 0.0
    elif spread_bps >= sofr_iorb_full_penalty_bps:
        applied = penalty_cap
    else:
        ramp = (spread_bps - sofr_iorb_warn_bps) / (sofr_iorb_full_penalty_bps - sofr_iorb_warn_bps)
        applied = penalty_cap * clip(ramp, 0.0, 1.0)

    return {
        "enabled": True,
        "applied": clip(float(applied), 0.0, 1.0),
        "spread_bps": spread_bps,
        "base_penalty": clip(float(base_penalty), 0.0, 1.0),
        "penalty_cap": float(penalty_cap),
        "persist_count": int(persist_count),
        "persist_active": bool(persist_active),
    }


def default_group(domain_name: str, factor_id: str) -> str:
    if domain_name == "Liquidity":
        return "Liquidity"

    macro_group_map = {
        "nifty50": "Macro",
        "nasdaq": "Macro",
        "bank_nifty": "Macro",
        "bitcoin": "Risk Appetite",
        "credit_spread": "Risk Appetite",
        "dxy": "Rates/Currency",
        "usdinr": "Rates/Currency",
        "us10y": "Rates/Currency",
        "crude": "Commodities",
        "gold": "Commodities",
        "copper_gold": "Commodities",
    }
    return macro_group_map.get(factor_id, "Macro")


def score_domain(factors: dict, resolver, domain_name: str, offset: int = 0):
    enabled_count = 0
    valid_count = 0
    rows = []
    valid_entries = []

    for factor_id, factor in factors.items():
        if not factor.get("enabled", True):
            continue

        enabled_count += 1
        series = resolver(factor, offset=offset)
        signal = compute_series_signal(
            series=series,
            inverse=bool(factor.get("inverse", False)),
            fast_window=fast_window,
            slow_window=slow_window,
            fast_w=fast_weight,
            slow_w=slow_weight,
        )

        base_weight = float(factor.get("weight", 0.0))
        capped_weight = min(max(base_weight, 0.0), max_factor_weight)
        group = factor.get("group", default_group(domain_name, factor_id))

        if signal is None or capped_weight <= 0:
            rows.append({
                "Domain": domain_name,
                "Group": group,
                "Factor": factor.get("label", factor_id),
                "Base W": round(base_weight, 3),
                "Capped W": round(capped_weight, 3),
                "Adj W": 0.0,
                "Eff W": 0.0,
                "Fast": "N/A",
                "Slow": "N/A",
                "Combined": "N/A",
                "Impulse C": 0.0,
                "Directional C": 0.0,
                "Contribution": 0.0,
                "Sentiment": "N/A",
                "Points": int(len(series.dropna())),
            })
            continue

        valid_count += 1
        valid_entries.append({
            "id": factor_id,
            "factor": factor.get("label", factor_id),
            "group": group,
            "base_weight": base_weight,
            "capped_weight": capped_weight,
            "signal": signal,
            "points": signal["points"],
        })

    if not valid_entries:
        return {
            "raw": 0.0,
            "norm": 0.0,
            "impulse_raw": 0.0,
            "impulse_norm": 0.0,
            "directional_raw": 0.0,
            "directional_norm": 0.0,
            "quality": 0.0,
            "enabled": enabled_count,
            "valid": 0,
            "rows": rows,
            "has_signal": False,
        }

    group_totals = {}
    for item in valid_entries:
        g = item["group"]
        group_totals[g] = group_totals.get(g, 0.0) + item["capped_weight"]

    for item in valid_entries:
        g = item["group"]
        cap = float(group_caps.get(g, 1.0))
        g_total = float(group_totals.get(g, 0.0))
        if g_total > cap > 0:
            item["adj_weight"] = item["capped_weight"] * (cap / g_total)
        else:
            item["adj_weight"] = item["capped_weight"]

    total_adj_weight = sum(item["adj_weight"] for item in valid_entries)
    blended_raw = 0.0
    impulse_raw = 0.0
    directional_raw = 0.0
    for item in valid_entries:
        eff_weight = (item["adj_weight"] / total_adj_weight) if total_adj_weight > 0 else 0.0
        impulse_contrib = item["signal"]["fast"] * eff_weight
        directional_contrib = item["signal"]["slow"] * eff_weight
        blended_contrib = item["signal"]["combined"] * eff_weight
        impulse_raw += impulse_contrib
        directional_raw += directional_contrib
        blended_raw += blended_contrib
        rows.append({
            "Domain": domain_name,
            "Group": item["group"],
            "Factor": item["factor"],
            "Base W": round(item["base_weight"], 3),
            "Capped W": round(item["capped_weight"], 3),
            "Adj W": round(item["adj_weight"], 3),
            "Eff W": round(eff_weight, 3),
            "Fast": item["signal"]["fast"],
            "Slow": item["signal"]["slow"],
            "Combined": item["signal"]["combined"],
            "Impulse C": round(impulse_contrib, 3),
            "Directional C": round(directional_contrib, 3),
            "Contribution": round(blended_contrib, 3),
            "Sentiment": item["signal"]["sentiment"],
            "Points": item["points"],
        })

    domain_raw = blended_raw if total_adj_weight > 0 else 0.0
    domain_norm = clip(domain_raw / 2.0, -1.0, 1.0)
    impulse_norm = clip(impulse_raw / 2.0, -1.0, 1.0)
    directional_norm = clip(directional_raw / 2.0, -1.0, 1.0)
    quality = (valid_count / enabled_count) if enabled_count > 0 else 0.0

    return {
        "raw": domain_raw,
        "norm": domain_norm,
        "impulse_raw": impulse_raw,
        "impulse_norm": impulse_norm,
        "directional_raw": directional_raw,
        "directional_norm": directional_norm,
        "quality": quality,
        "enabled": enabled_count,
        "valid": valid_count,
        "rows": rows,
        "has_signal": total_adj_weight > 0,
    }


def _latest_business_day_local() -> pd.Timestamp:
    t = pd.Timestamp.today().normalize()
    if t.weekday() < 5:
        return t
    return t - pd.offsets.BDay(1)


def _load_regime_lock() -> dict:
    if not REGIME_LOCK_FILE.exists():
        return {}
    try:
        return json.loads(REGIME_LOCK_FILE.read_text())
    except Exception:
        return {}


def _save_regime_lock(payload: dict) -> None:
    REGIME_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGIME_LOCK_FILE.write_text(json.dumps(payload, indent=2))


def _build_day_signature(offset: int) -> str:
    """
    Build deterministic signature from input data used for a historical day.
    If this signature is unchanged, keep prior locked regime value.
    """
    hasher = hashlib.sha256()
    hasher.update(f"offset:{offset}|fast:{fast_window}|slow:{slow_window}".encode())

    def feed_series(fid: str, s: pd.Series) -> None:
        hasher.update(fid.encode())
        if s is None or s.empty:
            hasher.update(b"EMPTY")
            return
        tail = s.dropna().tail(180)
        hasher.update(str(len(tail)).encode())
        for idx, val in tail.items():
            hasher.update(str(pd.to_datetime(idx).date()).encode())
            hasher.update(f"{float(val):.8f}".encode())

    for fid, factor in sorted(enabled_macro.items(), key=lambda x: x[0]):
        if not factor.get("enabled", True):
            continue
        feed_series(f"macro:{fid}", resolve_macro_series(factor, offset=offset))

    for fid, factor in sorted(enabled_liquidity.items(), key=lambda x: x[0]):
        if not factor.get("enabled", True):
            continue
        feed_series(f"liq:{fid}", resolve_liquidity_series(factor, offset=offset))

    return hasher.hexdigest()


macro_result = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=0)
liquidity_result = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=0)

macro_weight, liquidity_weight = normalize_weights(
    float(blend.get("macro_weight", 0.6)),
    float(blend.get("liquidity_weight", 0.4)),
)

has_macro = macro_result["has_signal"]
has_liquidity = liquidity_result["has_signal"]
sofr_penalty = compute_sofr_iorb_penalty(offset=0)

liq_directional_pre_penalty = float(liquidity_result.get("directional_norm", 0.0))
liq_impulse_pre_penalty = float(liquidity_result.get("impulse_norm", 0.0))
if has_liquidity and sofr_penalty.get("applied", 0.0) > 0:
    penalty = float(sofr_penalty["applied"])
    liquidity_result["directional_norm"] = clip(liq_directional_pre_penalty - penalty, -1.0, 1.0)
    liquidity_result["impulse_norm"] = clip(liq_impulse_pre_penalty - penalty, -1.0, 1.0)

if not has_macro and not has_liquidity:
    st.error("No valid factor signals. Check data availability or enable valid factors in Regime Settings.")
    st.stop()

if has_macro and has_liquidity:
    final_impulse = (macro_result["impulse_norm"] * macro_weight) + (liquidity_result["impulse_norm"] * liquidity_weight)
    final_directional = (macro_result["directional_norm"] * macro_weight) + (liquidity_result["directional_norm"] * liquidity_weight)
    agreement = 1.0 - min(abs(macro_result["directional_norm"] - liquidity_result["directional_norm"]) / 2.0, 1.0)
    data_quality = (macro_result["quality"] + liquidity_result["quality"]) / 2.0
elif has_macro:
    final_impulse = macro_result["impulse_norm"]
    final_directional = macro_result["directional_norm"]
    agreement = 1.0
    data_quality = macro_result["quality"]
else:
    final_impulse = liquidity_result["impulse_norm"]
    final_directional = liquidity_result["directional_norm"]
    agreement = 1.0
    data_quality = liquidity_result["quality"]

final_score = clip((final_directional * (1.0 - impulse_influence)) + (final_impulse * impulse_influence), -1.0, 1.0)

k = 3.0
risk_on_raw = math.exp(k * (final_score - neutral_band))
risk_off_raw = math.exp(k * (-final_score - neutral_band))
neutral_raw = math.exp(k * (neutral_band - abs(final_score)))

prob_total = risk_on_raw + risk_off_raw + neutral_raw
p_risk_on = risk_on_raw / prob_total
p_risk_off = risk_off_raw / prob_total
p_neutral = neutral_raw / prob_total


if p_risk_on >= risk_on_threshold and p_risk_on > p_risk_off and p_risk_on > p_neutral:
    regime = "🟢 Risk On"
    regime_color = "success"
elif p_risk_off >= risk_off_threshold and p_risk_off > p_risk_on and p_risk_off > p_neutral:
    regime = "🔴 Risk Off"
    regime_color = "error"
else:
    regime = "🟡 Neutral"
    regime_color = "warning"

max_prob = max(p_risk_on, p_risk_off, p_neutral)
confidence = clip(max_prob * agreement * data_quality * (0.6 + 0.4 * abs(final_directional)), 0.0, 1.0)

if regime == "🟢 Risk On" and confidence >= 0.65:
    bias = "Long Bias Allowed"
elif regime == "🔴 Risk Off" and confidence >= 0.65:
    bias = "Short Bias Allowed"
else:
    bias = "Selective / Reduced Risk"

render_decision_header(
    regime_label=regime,
    final_score=final_score,
    confidence=confidence,
    bias=bias,
    source="macro_risk_live",
)

with st.expander("📊 Regime Overview (Details)", expanded=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Macro Directional", f"{macro_result['directional_norm']:+.2f}")
        st.caption(f"Impulse: {macro_result['impulse_norm']:+.2f} | Valid: {macro_result['valid']}/{macro_result['enabled']}")
    with col2:
        st.metric("Liquidity Directional", f"{liquidity_result['directional_norm']:+.2f}")
        liq_caption = f"Impulse: {liquidity_result['impulse_norm']:+.2f} | Valid: {liquidity_result['valid']}/{liquidity_result['enabled']}"
        if sofr_penalty.get("applied", 0.0) > 0 and sofr_penalty.get("spread_bps") is not None:
            liq_caption += (
                f" | SOFR-IORB: {sofr_penalty['spread_bps']:+.1f} bps | "
                f"Penalty: -{sofr_penalty['applied']:.2f}"
            )
        st.caption(liq_caption)
    with col3:
        st.metric("Final Directional", f"{final_directional:+.2f}")
        st.caption(f"Final Impulse: {final_impulse:+.2f} | Confidence: {confidence:.0%}")
        st.caption(
            f"Formula: ({macro_weight:.2f} x {macro_result['directional_norm']:+.2f}) + "
            f"({liquidity_weight:.2f} x {liquidity_result['directional_norm']:+.2f}) = {final_directional:+.2f}"
        )

if regime_color == "success":
    st.success(f"### {regime}")
elif regime_color == "error":
    st.error(f"### {regime}")
else:
    st.warning(f"### {regime}")

st.info(f"Actionable Bias: **{bias}**")
gift_observations = []
if GIFT_NIFTY_MACRO_BADGE and is_gift_session_active(
    session_start_hour=GIFT_NIFTY_SESSION_START_IST_HOUR,
    cutoff_hour=GIFT_NIFTY_COLLAPSE_IST_HOUR,
):
    try:
        nd = market_data.get("^NSEI")
        prev_close = None
        if nd is not None and not nd.empty and "Close" in nd.columns:
            c = pd.to_numeric(nd["Close"], errors="coerce").dropna()
            if len(c) >= 1:
                prev_close = float(c.iloc[-1])
        gift = get_gift_nifty_snapshot(prev_nifty_close=prev_close)
        if gift.get("available", False):
            prem = gift.get("premium_pct_vs_prev_close")
            badge = "N/A" if prem is None else f"{float(prem):+.2f}%"
            gift_label = str(gift.get("implied_label", "Unknown"))
            if gift_label == "Gap Up":
                gift_tag = "🟢 Green"
            elif gift_label == "Gap Down":
                gift_tag = "🔴 Red"
            else:
                gift_tag = "🟠 Orange"
            gift_price = gift.get("price")
            price_txt = "N/A" if gift_price is None else f"{float(gift_price):,.2f}"
            gift_observations.append(f"{gift_tag} GIFT NIFTY {price_txt} | {badge} ({gift_label}).")
            if gift.get("quality_note"):
                st.caption(f"Normalization: {gift.get('quality_note')}")
    except Exception:
        pass
if sofr_penalty.get("applied", 0.0) > 0 and sofr_penalty.get("spread_bps") is not None:
    persist_tag = (
        f" (persistent {sofr_penalty['persist_count']}d)"
        if sofr_penalty.get("persist_active", False)
        else ""
    )
    st.warning(
        "SOFR/IORB liquidity stress penalty active: "
        f"{sofr_penalty['spread_bps']:+.1f} bps -> -{sofr_penalty['applied']:.2f} on Liquidity score{persist_tag}."
    )
st.caption(
    f"Agreement: {agreement:.0%} | Data quality: {data_quality:.0%} | "
    f"Final blend: {(1.0 - impulse_influence):.0%} directional + {impulse_influence:.0%} impulse"
)

ctx = get_india_context_signals()
flows = ctx.get("flows", {})
vix_ctx = ctx.get("vix", {})
breadth_ctx = ctx.get("breadth", {})
curve_ctx = ctx.get("curve", {})
gst_ctx = ctx.get("gst", {})
history_rows = flows.get("history_rows", [])
monthly_rows = flows.get("monthly_history_rows", [])
as_of = pd.to_datetime(flows.get("as_of"), errors="coerce")

observations = [
    f"{regime.split(' ')[0]} Regime {regime.split(' ', 1)[1]} with {confidence:.0%} confidence.",
]
if abs(macro_result["directional_norm"] - liquidity_result["directional_norm"]) >= 0.4:
    observations.append("Macro and Liquidity are diverging materially; reduce position size.")
if abs(final_impulse) > abs(final_directional) + 0.2:
    observations.append("Short-term impulse is dominating trend; expect higher noise.")
if sofr_penalty.get("applied", 0.0) > 0 and sofr_penalty.get("spread_bps") is not None:
    observations.append(
        f"Interbank stress: SOFR-IORB {sofr_penalty['spread_bps']:+.1f} bps, "
        f"Liquidity penalty -{sofr_penalty['applied']:.2f} applied."
    )
observations.extend(gift_observations)

# India flow context in key observations (daily + current month + streak flips).
if history_rows:
    hist_df = pd.DataFrame(history_rows)
    hist_df["date"] = pd.to_datetime(hist_df["date"], errors="coerce")
    hist_df["fii_net"] = pd.to_numeric(hist_df["fii_net"], errors="coerce")
    hist_df = hist_df.dropna(subset=["date"]).sort_values("date")
    if not hist_df.empty:
        last = hist_df.iloc[-1]
        daily_net = float(last["fii_net"])
        daily_tag = "🟢" if daily_net > 0 else ("🔴" if daily_net < 0 else "🟠")
        observations.append(f"{daily_tag} FII Daily: ₹{daily_net:,.0f} Cr.")

        ref_as_of = as_of if not pd.isna(as_of) else pd.to_datetime(last["date"], errors="coerce")
        if not pd.isna(ref_as_of):
            cur_month = ref_as_of.to_period("M")
            cur_daily = hist_df[hist_df["date"].dt.to_period("M") == cur_month].copy()
            if not cur_daily.empty:
                mtd_net = float(cur_daily["fii_net"].sum())
                mtd_tag = "🟢" if mtd_net > 0 else ("🔴" if mtd_net < 0 else "🟠")
                observations.append(f"{mtd_tag} FII {cur_month.strftime('%b %Y')} MTD: ₹{mtd_net:,.0f} Cr.")

                # If a red streak flips green today, call it out explicitly.
                signs = cur_daily["fii_net"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)).tolist()
                if len(signs) >= 2 and signs[-1] == 1 and signs[-2] == -1:
                    streak = 1
                    idx = len(signs) - 2
                    while idx >= 0 and signs[idx] == -1:
                        streak += 1
                        idx -= 1
                    observations.append(f"🟢 FII regime flip: {streak} negative days turned positive today.")
render_key_observations(observations, max_items=8)

with st.expander("🇮🇳 India Domestic Risk (Context Only - Not Scored Yet)", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        vix_val = vix_ctx.get("value")
        vix_chg = vix_ctx.get("change_pct")
        st.metric("India VIX", "N/A" if vix_val is None else f"{vix_val:.2f}", None if vix_chg is None else f"{vix_chg:+.2f}%")
        st.caption(f"{vix_ctx.get('status', 'STALE')} | {vix_ctx.get('source', 'NSE')}")
    with c2:
        adv = breadth_ctx.get("advances")
        dec = breadth_ctx.get("declines")
        ratio = breadth_ctx.get("ratio")
        val = "N/A"
        if adv is not None and dec is not None:
            val = f"{int(adv)}:{int(dec)}"
        st.metric("A/D Breadth", val, None if ratio is None else f"{float(ratio):.2f}")
        st.caption(f"{breadth_ctx.get('status', 'STALE')} | {breadth_ctx.get('as_of', 'N/A')}")

    d1, d2 = st.columns(2)
    with d1:
        curve_value = curve_ctx.get("value")
        st.metric("India Curve (10Y-3M)", "N/A" if curve_value is None else f"{float(curve_value):+.2f}")
        st.caption(f"{curve_ctx.get('status', 'UNAVAILABLE')} | {curve_ctx.get('source', 'pending')}")
    with d2:
        gst_yoy = gst_ctx.get("gst_yoy")
        st.metric("GST YoY", "N/A" if gst_yoy is None else f"{float(gst_yoy):+.1f}%")
        st.caption(f"{gst_ctx.get('status', 'UNAVAILABLE')} | {gst_ctx.get('source', 'pending')}")

    st.info(
        "Phase A visibility mode: domestic context signals are shown for monitoring only. "
        "They are not included in regime score yet."
    )

with st.expander("🎯 Regime Probabilities", expanded=False):
    p1, p2, p3 = st.columns(3)
    disp_risk_on, disp_neutral, disp_risk_off = round_percentages_sum_to_100(
        [p_risk_on, p_neutral, p_risk_off]
    )
    p1.metric("Risk On", f"{disp_risk_on}%")
    p2.metric("Neutral", f"{disp_neutral}%")
    p3.metric("Risk Off", f"{disp_risk_off}%")

# Publish canonical regime payload for cross-page consistency.
regime_payload = {
    "regime_label": regime,
    "confidence": round(float(confidence), 4),
    "final_score": round(float(final_score), 4),
    "final_directional": round(float(final_directional), 4),
    "final_impulse": round(float(final_impulse), 4),
    "macro_directional": round(float(macro_result.get("directional_norm", 0.0)), 4),
    "liquidity_directional": round(float(liquidity_result.get("directional_norm", 0.0)), 4),
    "bias": bias,
    "probabilities": {
        "risk_on": round(float(p_risk_on), 6),
        "neutral": round(float(p_neutral), 6),
        "risk_off": round(float(p_risk_off), 6),
    },
    "sofr_iorb_penalty": {
        "applied": round(float(sofr_penalty.get("applied", 0.0) or 0.0), 4),
        "spread_bps": (
            round(float(sofr_penalty.get("spread_bps")), 3)
            if sofr_penalty.get("spread_bps") is not None
            else None
        ),
        "persist_count": int(sofr_penalty.get("persist_count", 0) or 0),
        "persist_active": bool(sofr_penalty.get("persist_active", False)),
    },
    "source": "macro_risk_page",
}
save_regime_snapshot(regime_payload)
st.session_state["macro_regime_snapshot"] = regime_payload

# 90-day pulse-tape timeline (bottom of overview panel)
timeline_rows = []
for offset in range(89, -1, -1):
    macro_day = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=offset)
    liquidity_day = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=offset)
    sofr_penalty_day = compute_sofr_iorb_penalty(offset=offset)
    if liquidity_day["has_signal"] and sofr_penalty_day.get("applied", 0.0) > 0:
        penalty_day = float(sofr_penalty_day["applied"])
        liquidity_day["directional_norm"] = clip(float(liquidity_day["directional_norm"]) - penalty_day, -1.0, 1.0)
        liquidity_day["impulse_norm"] = clip(float(liquidity_day["impulse_norm"]) - penalty_day, -1.0, 1.0)

    if macro_day["has_signal"] and liquidity_day["has_signal"]:
        impulse_day = (macro_day["impulse_norm"] * macro_weight) + (liquidity_day["impulse_norm"] * liquidity_weight)
        directional_day = (macro_day["directional_norm"] * macro_weight) + (liquidity_day["directional_norm"] * liquidity_weight)
        score_day = (directional_day * (1.0 - impulse_influence)) + (impulse_day * impulse_influence)
        agreement_day = 1.0 - min(abs(macro_day["directional_norm"] - liquidity_day["directional_norm"]) / 2.0, 1.0)
        quality_day = (macro_day["quality"] + liquidity_day["quality"]) / 2.0
    elif macro_day["has_signal"]:
        score_day = (macro_day["directional_norm"] * (1.0 - impulse_influence)) + (macro_day["impulse_norm"] * impulse_influence)
        agreement_day = 1.0
        quality_day = macro_day["quality"]
    elif liquidity_day["has_signal"]:
        score_day = (liquidity_day["directional_norm"] * (1.0 - impulse_influence)) + (liquidity_day["impulse_norm"] * impulse_influence)
        agreement_day = 1.0
        quality_day = liquidity_day["quality"]
    else:
        score_day = 0.0
        agreement_day = 0.0
        quality_day = 0.0

    conf_score = clip((0.55 * abs(score_day)) + (0.25 * agreement_day) + (0.20 * quality_day), 0.0, 1.0)
    if conf_score >= 0.67:
        conf_label = "HIGH"
    elif conf_score >= 0.45:
        conf_label = "MEDIUM"
    else:
        conf_label = "LOW"

    if score_day >= max(risk_on_threshold, 0.55):
        day_regime = "RISK_ON"
    elif score_day <= -max(risk_off_threshold, 0.55):
        day_regime = "CRISIS"
    elif score_day < -neutral_band:
        day_regime = "DEFENSIVE"
    else:
        day_regime = "SELECTIVE"

    day_ts = (pd.Timestamp.today().normalize() - pd.Timedelta(days=offset)).strftime("%Y-%m-%d")
    timeline_rows.append(
        {
            "ts": day_ts,
            "regime": day_regime,
            "score": round(float(score_day * 10.0), 2),  # display scale -10..+10
            "confidence": conf_label,
        }
    )

render_regime_timeline_strip(timeline_rows, key="macro_regime_timeline_90d")

if view_mode == "Detail":
    render_source_freshness(
        {
            "^TNX": "US 10Y Yield",
            "DX-Y.NYB": "Dollar Index",
            "GC=F": "Gold",
            "CL=F": "Crude Oil",
            "BTC-USD": "Bitcoin",
            "^NSEI": "NIFTY 50",
        },
        market_data,
        title="Core Macro Inputs: Source & Freshness",
    )

factor_df = pd.DataFrame(macro_result["rows"] + liquidity_result["rows"])

if not factor_df.empty:
    rollup_df = factor_df.copy()
    for col in ["Base W", "Capped W", "Adj W", "Eff W", "Impulse C", "Directional C", "Contribution"]:
        rollup_df[col] = pd.to_numeric(rollup_df[col], errors="coerce").fillna(0.0)

    group_rollup = (
        rollup_df.groupby(["Domain", "Group"], dropna=False)
        .agg({
            "Base W": "sum",
            "Capped W": "sum",
            "Adj W": "sum",
            "Eff W": "sum",
            "Impulse C": "sum",
            "Directional C": "sum",
            "Contribution": "sum",
            "Factor": "count",
        })
        .reset_index()
        .rename(columns={"Factor": "Factors"})
    )

    macro_groups = group_rollup[group_rollup["Domain"] == "Macro"].copy()
    liquidity_groups = group_rollup[group_rollup["Domain"] == "Liquidity"].copy()
    for df in [macro_groups, liquidity_groups]:
        if not df.empty:
            df["Impulse (Norm)"] = (df["Impulse C"] / 2.0).round(3)
            df["Directional (Norm)"] = (df["Directional C"] / 2.0).round(3)
            df["Blend (Norm)"] = (df["Contribution"] / 2.0).round(3)

    if not macro_groups.empty:
        macro_terms = [f"{row['Group']} {row['Directional (Norm)']:+.3f}" for _, row in macro_groups.iterrows()]
        macro_formula_terms = " + ".join(macro_terms)
    else:
        macro_formula_terms = "No valid groups"

    with st.expander("🧮 Score Formula", expanded=(view_mode == "Detail")):
        st.caption(f"Macro Directional = {macro_formula_terms} = {macro_result['directional_norm']:+.3f}")
        if sofr_penalty.get("applied", 0.0) > 0 and sofr_penalty.get("spread_bps") is not None:
            st.caption(
                "Liquidity penalty: "
                f"{liq_directional_pre_penalty:+.3f} -> {liquidity_result['directional_norm']:+.3f} "
                f"(SOFR-IORB {sofr_penalty['spread_bps']:+.1f} bps, penalty -{sofr_penalty['applied']:.3f}, "
                f"warn>{sofr_iorb_warn_bps:.1f}, full@{sofr_iorb_full_penalty_bps:.1f} bps)"
            )
        st.caption(
            f"Final Directional = ({macro_weight:.2f} x {macro_result['directional_norm']:+.3f}) + "
            f"({liquidity_weight:.2f} x {liquidity_result['directional_norm']:+.3f}) = {final_directional:+.3f}"
        )
        st.caption(
            f"Final Score = ({1.0 - impulse_influence:.2f} x {final_directional:+.3f}) + "
            f"({impulse_influence:.2f} x {final_impulse:+.3f}) = {final_score:+.3f}"
        )

    with st.expander("📦 Advanced Details (Expand)", expanded=(view_mode == "Detail")):
        st.markdown("**Macro Group Rollup**")
        if not macro_groups.empty:
            st.dataframe(
                macro_groups[["Group", "Factors", "Base W", "Capped W", "Adj W", "Eff W", "Impulse (Norm)", "Directional (Norm)", "Blend (Norm)"]],
                width='stretch',
                hide_index=True,
            )
        else:
            st.info("No valid macro group contributions.")

        st.markdown("**Liquidity Group Rollup**")
        if not liquidity_groups.empty:
            st.dataframe(
                liquidity_groups[["Group", "Factors", "Base W", "Capped W", "Adj W", "Eff W", "Impulse (Norm)", "Directional (Norm)", "Blend (Norm)"]],
                width='stretch',
                hide_index=True,
            )
        else:
            st.info("No valid liquidity group contributions.")

        st.markdown("**Factor Breakdown**")
        st.dataframe(factor_df, width='stretch', hide_index=True)

        st.markdown("**Why This Regime?**")
        explain_df = factor_df.copy()
        for col in ["Eff W", "Impulse C", "Directional C", "Contribution"]:
            explain_df[col] = pd.to_numeric(explain_df[col], errors="coerce").fillna(0.0)
        explain_df["Abs Contribution"] = explain_df["Contribution"].abs()
        explain_df = explain_df.sort_values("Abs Contribution", ascending=False)
        top_df = explain_df.head(8)

        c1, c2 = st.columns([2, 1])
        with c1:
            st.dataframe(
                top_df[["Domain", "Group", "Factor", "Eff W", "Impulse C", "Directional C", "Contribution", "Sentiment"]],
                width='stretch',
                hide_index=True,
            )
        with c2:
            top_bull = top_df[top_df["Contribution"] > 0].head(3)["Factor"].tolist()
            top_bear = top_df[top_df["Contribution"] < 0].head(3)["Factor"].tolist()
            neutral_df = explain_df[explain_df["Sentiment"] == "Neutral"].copy()
            neutral_list = neutral_df.head(3)["Factor"].tolist()
            st.markdown("<span style='color:#2e7d32;font-weight:700'>Top Bullish Drivers</span>", unsafe_allow_html=True)
            if top_bull:
                for item in top_bull:
                    st.markdown(f"<span style='color:#2e7d32'>- {item}</span>", unsafe_allow_html=True)
            else:
                st.write("- None")
            st.markdown("<span style='color:#c62828;font-weight:700'>Top Bearish Drivers</span>", unsafe_allow_html=True)
            if top_bear:
                for item in top_bear:
                    st.markdown(f"<span style='color:#c62828'>- {item}</span>", unsafe_allow_html=True)
            else:
                st.write("- None")
            st.markdown("<span style='color:#f9a825;font-weight:700'>Top Neutral Drivers</span>", unsafe_allow_html=True)
            if neutral_list:
                for item in neutral_list:
                    st.markdown(f"<span style='color:#f9a825'>- {item}</span>", unsafe_allow_html=True)
            else:
                st.write("- None")
            if sofr_penalty.get("applied", 0.0) > 0 and sofr_penalty.get("spread_bps") is not None:
                st.markdown(
                    "<span style='color:#c62828;font-weight:700'>Liquidity Stress Override</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<span style='color:#c62828'>- SOFR-IORB {sofr_penalty['spread_bps']:+.1f} bps "
                    f"-> Liquidity penalty -{sofr_penalty['applied']:.2f}</span>",
                    unsafe_allow_html=True,
                )

with st.expander("📉 Regime Trend & Diagnostics (Expand)", expanded=(view_mode == "Detail")):
    trend_scores = []
    trend_regimes = []
    trend_days = []
    latest_bd_local = _latest_business_day_local()
    lock_payload = _load_regime_lock()
    lock_changed = False

    for offset in range(6, -1, -1):
        day = (latest_bd_local - pd.offsets.BDay(offset)).normalize()
        day_key = str(day.date())
        macro_day = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=offset)
        liquidity_day = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=offset)
        sofr_penalty_day = compute_sofr_iorb_penalty(offset=offset)
        if liquidity_day["has_signal"] and sofr_penalty_day.get("applied", 0.0) > 0:
            penalty_day = float(sofr_penalty_day["applied"])
            liquidity_day["directional_norm"] = clip(float(liquidity_day["directional_norm"]) - penalty_day, -1.0, 1.0)
            liquidity_day["impulse_norm"] = clip(float(liquidity_day["impulse_norm"]) - penalty_day, -1.0, 1.0)

        if macro_day["has_signal"] and liquidity_day["has_signal"]:
            impulse_day = (macro_day["impulse_norm"] * macro_weight) + (liquidity_day["impulse_norm"] * liquidity_weight)
            directional_day = (macro_day["directional_norm"] * macro_weight) + (liquidity_day["directional_norm"] * liquidity_weight)
            score_day = (directional_day * (1.0 - impulse_influence)) + (impulse_day * impulse_influence)
        elif macro_day["has_signal"]:
            score_day = (macro_day["directional_norm"] * (1.0 - impulse_influence)) + (macro_day["impulse_norm"] * impulse_influence)
        elif liquidity_day["has_signal"]:
            score_day = (liquidity_day["directional_norm"] * (1.0 - impulse_influence)) + (liquidity_day["impulse_norm"] * impulse_influence)
        else:
            score_day = 0.0

        if score_day > neutral_band:
            regime_day = "🟢 Risk On"
        elif score_day < -neutral_band:
            regime_day = "🔴 Risk Off"
        else:
            regime_day = "🟡 Neutral"

        # Lock historical values unless that day's source-data signature changes.
        sig = _build_day_signature(offset)
        locked = lock_payload.get(day_key)
        is_latest = day == latest_bd_local
        if (not is_latest) and isinstance(locked, dict) and locked.get("signature") == sig:
            trend_scores.append(float(locked.get("score", score_day)))
            trend_regimes.append(str(locked.get("regime", regime_day)))
        else:
            trend_scores.append(score_day)
            trend_regimes.append(regime_day)
            lock_payload[day_key] = {
                "score": float(score_day),
                "regime": regime_day,
                "signature": sig,
                "updated_at": pd.Timestamp.now().isoformat(),
            }
            if not is_latest:
                lock_changed = True
        trend_days.append(day.date())

    # Keep lock store bounded (approx last 400 calendar days)
    cutoff_day = (latest_bd_local - pd.Timedelta(days=400)).date()
    old_keys = [k for k in lock_payload.keys() if pd.to_datetime(k, errors="coerce").date() < cutoff_day]
    for k in old_keys:
        lock_payload.pop(k, None)
        lock_changed = True
    if lock_changed:
        _save_regime_lock(lock_payload)

    trend_df = pd.DataFrame({
        "Day": trend_days,
        "Score": trend_scores,
        "Regime": trend_regimes,
    })

    trend_fig = go.Figure()
    trend_fig.add_trace(go.Scatter(
        x=trend_df["Day"],
        y=trend_df["Score"],
        mode="lines+markers",
        marker=dict(
            color=["green" if r == "🟢 Risk On" else ("red" if r == "🔴 Risk Off" else "orange") for r in trend_df["Regime"]],
            size=10,
        ),
        line=dict(width=2),
        name="Regime Score",
    ))
    trend_fig.update_layout(height=300, yaxis_title="Score (-1 to +1)")
    st.plotly_chart(trend_fig, width='stretch')

    st.markdown("### 📈 Enabled Macro Charts")
    macro_chart_items = []
    for factor in enabled_macro.values():
        if "symbol" in factor and factor["symbol"] in market_data:
            macro_chart_items.append((factor["label"], factor["symbol"]))

    for idx in range(0, len(macro_chart_items), 2):
        c1, c2 = st.columns(2)
        label1, symbol1 = macro_chart_items[idx]
        with c1:
            df1 = market_data.get(symbol1)
            if df1 is not None and not df1.empty:
                with st.expander(label1):
                    fig1 = go.Figure()
                    chart_df = prepare_timeseries_for_chart(df1)
                    fig1.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Close"], mode="lines", name=label1))
                    fig1.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
                    st.plotly_chart(fig1, width='stretch')

        if idx + 1 < len(macro_chart_items):
            label2, symbol2 = macro_chart_items[idx + 1]
            with c2:
                df2 = market_data.get(symbol2)
                if df2 is not None and not df2.empty:
                    with st.expander(label2):
                        fig2 = go.Figure()
                        chart_df = prepare_timeseries_for_chart(df2)
                        fig2.add_trace(go.Scatter(x=chart_df.index, y=chart_df["Close"], mode="lines", name=label2))
                        fig2.update_layout(height=260, margin=dict(l=10, r=10, t=30, b=10), showlegend=False)
                        st.plotly_chart(fig2, width='stretch')

    st.markdown("### 💧 Liquidity Drivers")
    for factor in enabled_liquidity.values():
        label = factor.get("label", "Liquidity")
        series = resolve_liquidity_series(factor, offset=0)
        if series.empty:
            continue
        with st.expander(label):
            st.line_chart(series)

with st.expander("💼 FII / DII Flows", expanded=False):
    c1, c2, c3 = st.columns(3)
    with c1:
        fii = flows.get("fii_net")
        st.metric("FII Net (Daily)", "N/A" if fii is None else f"₹{fii:,.0f} Cr")
        st.caption(f"{flows.get('status', 'STALE')} | {flows.get('as_of', 'N/A')}")
    with c2:
        fii20 = flows.get("fii_20d")
        st.metric("FII Net (20D)", "N/A" if fii20 is None else f"₹{fii20:,.0f} Cr")
        st.caption(f"Rows: {flows.get('rows', 0)} | Source: {flows.get('source', 'N/A')}")
    with c3:
        dom = flows.get("fii_dii_dominance")
        st.metric("FII Dominance", "N/A" if dom is None else f"{dom:+.2f}")
        st.caption("FII/(|FII|+|DII|)")

    if flows.get("note"):
        st.caption(str(flows.get("note")))

    if history_rows:
        hist_df = pd.DataFrame(history_rows)
        hist_df["date"] = pd.to_datetime(hist_df["date"], errors="coerce")
        hist_df["fii_net"] = pd.to_numeric(hist_df["fii_net"], errors="coerce")
        hist_df["dii_net"] = pd.to_numeric(hist_df["dii_net"], errors="coerce")
        hist_df = hist_df.dropna(subset=["date"]).sort_values("date")
        if not hist_df.empty and not pd.isna(as_of):
            cur_month = as_of.to_period("M")
            cur_daily = hist_df[hist_df["date"].dt.to_period("M") == cur_month].copy()
            if not cur_daily.empty:
                cur_daily = cur_daily.sort_values("date", ascending=False)
                st.markdown("#### 📆 Current Month (Daily FII/DII Net)")
                cur_view = cur_daily.copy()
                cur_view["Date"] = cur_view["date"].dt.strftime("%Y-%m-%d")
                cur_view["FII Net"] = cur_view["fii_net"].map(lambda x: f"₹{x:,.0f}")
                cur_view["DII Net"] = cur_view["dii_net"].map(lambda x: f"₹{x:,.0f}")
                cur_view["FII Bias"] = cur_daily["fii_net"].apply(
                    lambda x: "Buy" if x > 0 else ("Sell" if x < 0 else "Flat")
                )
                st.dataframe(cur_view[["Date", "FII Net", "DII Net", "FII Bias"]], width="stretch", hide_index=True)
                st.caption("Daily values are live/cache based and update with each data refresh.")

    if monthly_rows:
        mdf = pd.DataFrame(monthly_rows)
        mdf["month_start"] = pd.to_datetime(mdf["month_start"], errors="coerce")
        mdf["fii_net"] = pd.to_numeric(mdf["fii_net"], errors="coerce")
        mdf["dii_net"] = pd.to_numeric(mdf["dii_net"], errors="coerce")
        mdf = mdf.dropna(subset=["month_start"]).sort_values("month_start")
        if not mdf.empty:
            if not pd.isna(as_of):
                mdf = mdf[mdf["month_start"] < as_of.normalize().replace(day=1)]
            if not mdf.empty:
                st.markdown("#### 📅 Prior Months (Monthly FII Net)")
                m1, m2 = st.columns(2)
                latest_month = mdf.iloc[-1]
                prev_month_val = mdf.iloc[-2]["fii_net"] if len(mdf) >= 2 else None
                with m1:
                    st.metric(
                        "Latest Prior Month FII Net",
                        f"₹{latest_month['fii_net']:,.0f} Cr",
                        None if prev_month_val is None else f"{(latest_month['fii_net'] - prev_month_val):+,.0f} vs prior",
                    )
                with m2:
                    st.metric("Latest Prior Month", latest_month["month_start"].strftime("%Y-%m"))
                mshow = mdf.copy()
                mshow["Month"] = mshow["month_start"].dt.strftime("%Y-%m")
                mshow["NetValue"] = mshow["fii_net"]
                mshow["Net"] = mshow["NetValue"].map(lambda x: f"₹{x:,.0f}")
                mshow["Regime"] = mshow["NetValue"].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
                mshow["RegimeChange"] = mshow["Regime"].ne(mshow["Regime"].shift(1)).fillna(False)
                out = mshow[["Month", "Net", "RegimeChange"]].copy().sort_values("Month", ascending=False)

                def _style_regime_change(row):
                    if bool(row["RegimeChange"]):
                        return ["", "color: #2e7d32; font-weight: 700;", ""]
                    return ["", "", ""]

                st.dataframe(
                    out.style.apply(_style_regime_change, axis=1).hide(axis="columns", subset=["RegimeChange"]),
                    width="stretch",
                    hide_index=True,
                )
                st.caption("Prior month history sourced from imported FIIDII workbook.")
    elif not history_rows:
        st.caption("FII/DII history not available yet.")

st.markdown("---")
st.caption("Configure factor weights and enabled factors from the Regime Settings page.")
_perf["total_page_s"] = round(time.perf_counter() - _page_t0, 3)
if st.sidebar.checkbox("Show Performance Diagnostics", value=False):
    st.sidebar.dataframe(
        pd.DataFrame([{"Step": k, "Seconds": v} for k, v in _perf.items()]),
        width="stretch",
        hide_index=True,
    )
