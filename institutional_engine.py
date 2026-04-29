import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import FRED_API_KEY
from data_fetch import batch_download, fetch_fred_series, fetch_india_vix, load_local_nse_history
from india_context import get_india_macro_signals_v1
from regime_model import load_regime_settings
import regime_scoring as scoring
import regime_classification as classification
from NSE_Config import NIFTY_200

def generate_institutional_regime(offset: int = 0) -> dict:
    settings = load_regime_settings()
    blend = settings["blend"]
    global_factors = settings.get("global_factors", {})
    macro_factors = settings.get("macro_factors", {})
    liquidity_factors = settings.get("liquidity_factors", {})
    risk_factors = settings.get("risk_factors", {})
    
    def clip(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    fast_weight = float(blend.get("fast_weight", 0.4))
    slow_weight = float(blend.get("slow_weight", 0.6))
    fast_slow_total = fast_weight + slow_weight
    if fast_slow_total <= 0:
        fast_weight, slow_weight = 0.4, 0.6
    else:
        fast_weight, slow_weight = fast_weight / fast_slow_total, slow_weight / fast_slow_total

    enabled_global = {k: v for k, v in global_factors.items() if v.get("enabled", True)}
    enabled_macro = {k: v for k, v in macro_factors.items() if v.get("enabled", True)}
    enabled_liquidity = {k: v for k, v in liquidity_factors.items() if v.get("enabled", True)}
    enabled_risk = {k: v for k, v in risk_factors.items() if v.get("enabled", True)}

    required_symbols = set()
    required_fred = set()
    for phase in [enabled_global, enabled_macro, enabled_liquidity, enabled_risk]:
        for factor in phase.values():
            if "symbol" in factor: required_symbols.add(factor["symbol"])
            if "ratio" in factor: required_symbols.update(factor["ratio"])
            if "fred" in factor: required_fred.add(factor["fred"])
            if "fred_spread" in factor: required_fred.update(factor["fred_spread"])

    required_symbols.update(["^GSPC", "^IXIC", "BTC-USD", "GC=F", "CL=F"])

    india_signals = get_india_macro_signals_v1()
    market_data = batch_download(sorted(required_symbols), period="1y")
    
    nse_history = load_local_nse_history(days=400)
    breadth_series = scoring.compute_nifty_200_breadth_series(nse_history, NIFTY_200)
    
    vix_price, vix_change = fetch_india_vix()
    
    fred_raw = {}
    if FRED_API_KEY and required_fred:
        fred_ids = sorted(required_fred)
        workers = min(8, max(1, len(fred_ids)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(fetch_fred_series, sid, FRED_API_KEY, 365): sid for sid in fred_ids}
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    fred_raw[sid] = future.result()
                except Exception:
                    fred_raw[sid] = None

    market_series_cache = {}
    for symbol, df in market_data.items():
        if df is not None and not df.empty and "Close" in df.columns:
            market_series_cache[symbol] = df["Close"].dropna()

    fred_series_cache = {}
    for sid, df in fred_raw.items():
        if df is not None and not df.empty and {"date", "value"}.issubset(df.columns):
            fred_series_cache[sid] = df.set_index("date")["value"].dropna()

    def build_ratio_series(left: pd.Series, right: pd.Series) -> pd.Series:
        if left.empty or right.empty:
            return pd.Series(dtype=float)
        common = pd.concat([left, right], axis=1).ffill().dropna()
        return common.iloc[:,0] / common.iloc[:,1]

    def resolve_factor_series(factor: dict, offset: int = 0) -> pd.Series:
        def apply_offset(s: pd.Series) -> pd.Series:
            if offset <= 0 or s.empty: return s
            return s.iloc[:-offset]

        if factor.get("id") == "INDIAVIX" or factor.get("symbol") == "INDIAVIX":
            if "INDIAVIX" in market_series_cache:
                return apply_offset(market_series_cache["INDIAVIX"])
            if vix_price and offset == 0:
                return pd.Series([vix_price], index=[pd.Timestamp.today()])
            return pd.Series(dtype=float)

        if factor.get("local"):
            loc_key = factor["local"]
            if loc_key == "gst_monthly":
                gst_hist = india_signals.get("gst_history", [])
                if gst_hist:
                    df_gst = pd.DataFrame(gst_hist)
                    if "yoy_growth" in df_gst.columns and "month" in df_gst.columns:
                        s = df_gst.set_index("month")["yoy_growth"].dropna()
                        return apply_offset(s)
            
            sig_data = india_signals.get(loc_key)
            if isinstance(sig_data, dict) and "value" in sig_data:
                val = sig_data["value"]
                if val is not None:
                    return pd.Series([val])
            for cat in ["macro", "liquidity", "risk"]:
                cat_data = india_signals.get(cat, {})
                if loc_key in cat_data:
                    val = cat_data[loc_key]
                    if isinstance(val, (pd.Series, pd.DataFrame)):
                        return apply_offset(val)
                    if isinstance(val, (int, float)):
                        return pd.Series([val])

            return pd.Series(dtype=float)

        if "symbol" in factor:
            return apply_offset(market_series_cache.get(factor["symbol"], pd.Series(dtype=float)))

        if "ratio" in factor:
            left = market_series_cache.get(factor["ratio"][0], pd.Series(dtype=float))
            right = market_series_cache.get(factor["ratio"][1], pd.Series(dtype=float))
            if not left.empty and not right.empty:
                return apply_offset(build_ratio_series(left, right))
            return pd.Series(dtype=float)

        if "fred" in factor:
            return apply_offset(fred_series_cache.get(factor["fred"], pd.Series(dtype=float)))

        if "fred_spread" in factor:
            left = fred_series_cache.get(factor["fred_spread"][0], pd.Series(dtype=float))
            right = fred_series_cache.get(factor["fred_spread"][1], pd.Series(dtype=float))
            if not left.empty and not right.empty:
                common = pd.concat([left, right], axis=1).ffill().dropna()
                return apply_offset(common.iloc[:,0] - common.iloc[:,1])
            return pd.Series(dtype=float)

        return pd.Series(dtype=float)

    all_rows = []
    phases = [
        ("Global", enabled_global, blend.get("global_weight", 0.40)),
        ("Growth", enabled_macro, blend.get("macro_weight", 0.20)),
        ("Liquidity", enabled_liquidity, blend.get("liquidity_weight", 0.25)),
        ("Risk", enabled_risk, blend.get("risk_weight", 0.15)),
    ]
    
    pillar_scores = {}
    final_score = 0.0
    for phase_name, factors, phase_weight in phases:
        phase_weighted_sum = 0.0
        sum_of_weights = 0.0
        
        for fid, factor in factors.items():
            if fid == "breadth":
                val = 0.0
                if not breadth_series.empty:
                    if offset < len(breadth_series):
                        val = breadth_series.iloc[-(offset + 1)]
                score = scoring.calculate_breadth_score(val / 100.0) 
                sentiment = "Neutral" if score == 0 else ("Bullish" if score > 0 else "Bearish")
                series = pd.Series([val])
            else:
                series = resolve_factor_series(factor, offset=offset)
                if series.empty:
                    all_rows.append({
                        "Pillar": phase_name,
                        "Factor": factor.get("label", fid),
                        "Value": "N/A",
                        "Score": 0.0,
                        "Sentiment": "Neutral",
                        "Weight": factor.get("weight", 0.0)
                    })
                    continue
                if phase_name == "Liquidity":
                    score, sentiment = scoring.calculate_impulse_sentiment(series)
                elif fid == "india_vix":
                    val = series.iloc[-1]
                    score = scoring.calculate_vix_score(val)
                    sentiment = "Neutral" if score == 0 else ("Bullish" if score > 0 else "Bearish")
                elif fid == "us_yield_curve":
                    val = series.iloc[-1]
                    score = scoring.calculate_yield_curve_score(val)
                    sentiment = "Neutral" if score == 0 else ("Bullish" if score > 0 else "Bearish")
                else:
                    score, sentiment = scoring.calculate_z_score_sentiment(series, inverse=factor.get("inverse", False))
                
            f_weight = factor.get("weight", 0.0)
            phase_weighted_sum += score * f_weight
            sum_of_weights += f_weight
            
            val_precision = 2
            if "ratio" in factor or "symbol" in factor and any(x in factor["symbol"] for x in ["=", "X"]):
                val_precision = 4
                
            all_rows.append({
                "Pillar": phase_name,
                "Factor": factor.get("label", fid),
                "Value": round(series.iloc[-1], val_precision) if not series.empty else "N/A",
                "Score": round(score, 3),
                "Sentiment": sentiment,
                "Weight": f_weight
            })
            
        # Normalize to [-1, 1] then apply intended pillar weight
        raw_pillar_score = (phase_weighted_sum / sum_of_weights) if sum_of_weights > 0 else 0.0
        pillar_scores[phase_name] = raw_pillar_score
        final_score += raw_pillar_score * phase_weight

    regime = classification.classify_regime(final_score)
    probs = classification.calculate_regime_probabilities(final_score, regime)
    
    vix_val = vix_price if vix_price else 0.0
    is_crisis, crisis_reason = classification.check_crisis_overrides(vix_val, 0.0) 
    
    settings_stb = {"persistence_days": 3, "momentum_threshold": 0.05}
    raw_regime = "Crisis" if is_crisis else regime
    st_result = classification.apply_stability_filters(final_score, raw_regime, settings_stb)
    
    return {
        "final_score": st_result["current_score"],
        "regime": st_result["current_regime"],
        "confidence": st_result.get("confidence", 50.0),
        "pillar_scores": pillar_scores,
        "rows": all_rows,
        "probabilities": probs,
        "crisis_reason": crisis_reason,
        "is_pending": st_result.get("pending_regime") is not None,
        "market_data": market_data,
        "india_ctx": india_signals,
        "blend": blend,
        "vix_price": vix_price,
        "breadth_series": breadth_series
    }
