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
impulse_influence = clip(float(blend.get("impulse_influence", 0.25)), 0.0, 0.6)
fast_window = int(blend.get("fast_window", 1))
slow_window = int(blend.get("slow_window", 10))
max_factor_weight = float(blend.get("max_factor_weight", 0.2))
neutral_band = float(blend.get("neutral_band", 0.35))
risk_on_threshold = float(blend.get("risk_on_threshold", 0.6))
risk_off_threshold = float(blend.get("risk_off_threshold", 0.6))
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


def rounded_percentages_sum_to_100(values):
    """Round probabilities to whole percentages while forcing exact sum=100."""
    raw = [max(0.0, float(v)) * 100.0 for v in values]
    floors = [int(math.floor(v)) for v in raw]
    remainder = 100 - sum(floors)
    # Largest remainder method
    frac_order = sorted(range(len(raw)), key=lambda i: (raw[i] - floors[i]), reverse=True)
    out = floors[:]
    for i in frac_order[: max(0, remainder)]:
        out[i] += 1
    return out

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

st.subheader("📊 Regime Overview")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Macro Directional", f"{macro_result['directional_norm']:+.2f}")
    st.caption(f"Impulse: {macro_result['impulse_norm']:+.2f} | Valid: {macro_result['valid']}/{macro_result['enabled']}")
with col2:
    st.metric("Liquidity Directional", f"{liquidity_result['directional_norm']:+.2f}")
    st.caption(f"Impulse: {liquidity_result['impulse_norm']:+.2f} | Valid: {liquidity_result['valid']}/{liquidity_result['enabled']}")
with col3:
    st.metric("Final Directional", f"{final_directional:+.2f}")
    st.caption(f"Final Impulse: {final_impulse:+.2f} | Confidence: {confidence:.0%}")

if regime_color == "success":
    st.success(f"### {regime}")
elif regime_color == "error":
    st.error(f"### {regime}")
else:
    st.warning(f"### {regime}")

st.info(f"Actionable Bias: **{bias}**")
st.caption(
    f"Agreement: {agreement:.0%} | Data quality: {data_quality:.0%} | "
    f"Final blend: {(1.0 - impulse_influence):.0%} directional + {impulse_influence:.0%} impulse"
)

st.subheader("🎯 Regime Probabilities")
p1, p2, p3 = st.columns(3)
disp_risk_on, disp_neutral, disp_risk_off = rounded_percentages_sum_to_100(
    [p_risk_on, p_neutral, p_risk_off]
)
p1.metric("Risk On", f"{disp_risk_on}%")
p2.metric("Neutral", f"{disp_neutral}%")
p3.metric("Risk Off", f"{disp_risk_off}%")

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

    st.subheader("🧮 Score Formula")
    st.caption(f"Macro Directional = {macro_formula_terms} = {macro_result['directional_norm']:+.3f}")
    st.caption(
        f"Final Directional = ({macro_weight:.2f} x {macro_result['directional_norm']:+.3f}) + "
        f"({liquidity_weight:.2f} x {liquidity_result['directional_norm']:+.3f}) = {final_directional:+.3f}"
    )
    st.caption(
        f"Final Score = ({1.0 - impulse_influence:.2f} x {final_directional:+.3f}) + "
        f"({impulse_influence:.2f} x {final_impulse:+.3f}) = {final_score:+.3f}"
    )

    with st.expander("📦 Advanced Details (Expand)", expanded=False):
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
            st.write("**Top Bullish Drivers**")
            if top_bull:
                for item in top_bull:
                    st.write(f"- {item}")
            else:
                st.write("- None")
            st.write("**Top Bearish Drivers**")
            if top_bear:
                for item in top_bear:
                    st.write(f"- {item}")
            else:
                st.write("- None")
            st.write("**Top Neutral Drivers**")
            if neutral_list:
                for item in neutral_list:
                    st.write(f"- {item}")
            else:
                st.write("- None")

st.subheader("📉 Regime Trend (Last 7 Sessions)")
trend_scores = []
trend_regimes = []

for offset in range(6, -1, -1):
    macro_day = score_domain(enabled_macro, resolve_macro_series, "Macro", offset=offset)
    liquidity_day = score_domain(enabled_liquidity, resolve_liquidity_series, "Liquidity", offset=offset)

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
st.plotly_chart(trend_fig, width='stretch')

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
