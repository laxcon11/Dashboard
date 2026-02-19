import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import FRED_API_KEY
from data_fetch import batch_download, fetch_fred_series, fetch_india_vix, prepare_timeseries_for_chart
from regime_model import load_regime_settings
from utils import setup_page


setup_page("Dashboard Launcher")
st.title("🌍 India Macro Risk Dashboard")
st.caption("Configurable regime model combining Macro and Liquidity factors.")

settings = load_regime_settings()
blend = settings["blend"]
macro_factors = settings["macro_factors"]
liquidity_factors = settings["liquidity_factors"]


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
fast_window = int(blend.get("fast_window", 1))
slow_window = int(blend.get("slow_window", 10))
max_factor_weight = float(blend.get("max_factor_weight", 0.2))
neutral_band = float(blend.get("neutral_band", 0.35))
risk_on_threshold = float(blend.get("risk_on_threshold", 0.6))
risk_off_threshold = float(blend.get("risk_off_threshold", 0.6))

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
    market_data = batch_download(sorted(required_symbols), period="6mo")

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
        for sid in sorted(required_fred):
            fred_raw[sid] = fetch_fred_series(sid, FRED_API_KEY, days=365)
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

        if signal is None or capped_weight <= 0:
            rows.append({
                "Domain": domain_name,
                "Factor": factor.get("label", factor_id),
                "Base W": round(base_weight, 3),
                "Capped W": round(capped_weight, 3),
                "Eff W": 0.0,
                "Fast": "N/A",
                "Slow": "N/A",
                "Combined": "N/A",
                "Sentiment": "N/A",
                "Points": int(len(series.dropna())),
            })
            continue

        valid_count += 1
        valid_entries.append({
            "factor": factor.get("label", factor_id),
            "base_weight": base_weight,
            "capped_weight": capped_weight,
            "signal": signal,
            "points": signal["points"],
        })

    total_capped_weight = sum(item["capped_weight"] for item in valid_entries)
    weighted_sum = 0.0

    for item in valid_entries:
        eff_weight = (item["capped_weight"] / total_capped_weight) if total_capped_weight > 0 else 0.0
        weighted_sum += item["signal"]["combined"] * eff_weight
        rows.append({
            "Domain": domain_name,
            "Factor": item["factor"],
            "Base W": round(item["base_weight"], 3),
            "Capped W": round(item["capped_weight"], 3),
            "Eff W": round(eff_weight, 3),
            "Fast": item["signal"]["fast"],
            "Slow": item["signal"]["slow"],
            "Combined": item["signal"]["combined"],
            "Sentiment": item["signal"]["sentiment"],
            "Points": item["points"],
        })

    domain_raw = weighted_sum if total_capped_weight > 0 else 0.0
    domain_norm = clip(domain_raw / 2.0, -1.0, 1.0)
    quality = (valid_count / enabled_count) if enabled_count > 0 else 0.0

    return {
        "raw": domain_raw,
        "norm": domain_norm,
        "quality": quality,
        "enabled": enabled_count,
        "valid": valid_count,
        "rows": rows,
        "has_signal": total_capped_weight > 0,
    }


macro_result = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=0)
liquidity_result = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=0)

macro_weight, liquidity_weight = normalize_weights(
    float(blend.get("macro_weight", 0.6)),
    float(blend.get("liquidity_weight", 0.4)),
)

has_macro = macro_result["has_signal"]
has_liquidity = liquidity_result["has_signal"]

if not has_macro and not has_liquidity:
    st.error("No valid factor signals. Check data availability or enable valid factors in Regime Settings.")
    st.stop()

if has_macro and has_liquidity:
    final_score = (macro_result["norm"] * macro_weight) + (liquidity_result["norm"] * liquidity_weight)
    agreement = 1.0 - min(abs(macro_result["norm"] - liquidity_result["norm"]) / 2.0, 1.0)
    data_quality = (macro_result["quality"] + liquidity_result["quality"]) / 2.0
elif has_macro:
    final_score = macro_result["norm"]
    agreement = 1.0
    data_quality = macro_result["quality"]
else:
    final_score = liquidity_result["norm"]
    agreement = 1.0
    data_quality = liquidity_result["quality"]

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
confidence = clip(max_prob * agreement * data_quality, 0.0, 1.0)

if regime == "🟢 Risk On" and confidence >= 0.65:
    bias = "Long Bias Allowed"
elif regime == "🔴 Risk Off" and confidence >= 0.65:
    bias = "Short Bias Allowed"
else:
    bias = "Selective / Reduced Risk"

st.subheader("📊 Regime Overview")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Macro Score", f"{macro_result['norm']:+.2f}")
    st.caption(f"Valid factors: {macro_result['valid']}/{macro_result['enabled']}")
with col2:
    st.metric("Liquidity Score", f"{liquidity_result['norm']:+.2f}")
    st.caption(f"Valid factors: {liquidity_result['valid']}/{liquidity_result['enabled']}")
with col3:
    st.metric("Final Regime Score", f"{final_score:+.2f}")
    st.caption(f"Confidence: {confidence:.0%}")

if regime_color == "success":
    st.success(f"### {regime}")
elif regime_color == "error":
    st.error(f"### {regime}")
else:
    st.warning(f"### {regime}")

st.info(f"Actionable Bias: **{bias}**")
st.caption(f"Agreement: {agreement:.0%} | Data quality: {data_quality:.0%}")

st.subheader("🎯 Regime Probabilities")
p1, p2, p3 = st.columns(3)
p1.metric("Risk On", f"{p_risk_on:.0%}")
p2.metric("Neutral", f"{p_neutral:.0%}")
p3.metric("Risk Off", f"{p_risk_off:.0%}")

st.subheader("📋 Factor Breakdown")
factor_df = pd.DataFrame(macro_result["rows"] + liquidity_result["rows"])
if not factor_df.empty:
    st.dataframe(factor_df, use_container_width=True, hide_index=True)

st.subheader("📉 Regime Trend (Last 7 Sessions)")
trend_scores = []
trend_regimes = []

for offset in range(6, -1, -1):
    macro_day = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=offset)
    liquidity_day = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=offset)

    if macro_day["has_signal"] and liquidity_day["has_signal"]:
        score_day = (macro_day["norm"] * macro_weight) + (liquidity_day["norm"] * liquidity_weight)
    elif macro_day["has_signal"]:
        score_day = macro_day["norm"]
    elif liquidity_day["has_signal"]:
        score_day = liquidity_day["norm"]
    else:
        score_day = 0.0

    trend_scores.append(score_day)
    if score_day > neutral_band:
        trend_regimes.append("🟢 Risk On")
    elif score_day < -neutral_band:
        trend_regimes.append("🔴 Risk Off")
    else:
        trend_regimes.append("🟡 Neutral")

trend_df = pd.DataFrame({
    "Day": pd.date_range(end=pd.Timestamp.today(), periods=7).date,
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
st.plotly_chart(trend_fig, use_container_width=True)

st.subheader("📈 Enabled Macro Charts")
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
                st.plotly_chart(fig1, use_container_width=True)

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
                    st.plotly_chart(fig2, use_container_width=True)

st.subheader("💧 Liquidity Drivers")
for factor in enabled_liquidity.values():
    label = factor.get("label", "Liquidity")
    series = resolve_liquidity_series(factor, offset=0)
    if series.empty:
        continue
    with st.expander(label):
        st.line_chart(series)

st.markdown("---")
st.caption("Configure factor weights and enabled factors from the Regime Settings page.")
