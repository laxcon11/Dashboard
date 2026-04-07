import copy
import json
from pathlib import Path
from typing import Any, Dict


SETTINGS_FILE = Path("notes/regime_settings.json")


DEFAULT_REGIME_SETTINGS: Dict[str, Any] = {
    "blend": {
        "global_weight": 0.40,
        "macro_weight": 0.20,
        "liquidity_weight": 0.25,
        "risk_weight": 0.15,
        "fast_weight": 0.40,
        "slow_weight": 0.60,
        "impulse_influence": 0.25,
        "fast_window": 1,
        "slow_window": 10,
        "max_factor_weight": 0.20,
        "neutral_band": 0.35,
        "risk_on_threshold": 0.45,
        "risk_off_threshold": 0.45,
        "persistence_days": 3,
        "momentum_threshold": 0.10,
        "sofr_iorb_penalty_enabled": True,
        "sofr_iorb_warn_bps": 5.0,
        "sofr_iorb_full_penalty_bps": 15.0,
        "sofr_iorb_max_penalty": 0.25,
    },
    "global_factors": {
        "us10y_3m": {"label": "US Yield Curve (10Y-3M)", "fred": "T10Y3M", "inverse": False, "weight": 0.07, "enabled": True},
        "copper_gold": {"label": "Copper/Gold Ratio", "ratio": ["HG=F", "GC=F"], "inverse": False, "weight": 0.07, "enabled": True},
        "dxy": {"label": "Dollar Index", "symbol": "DX-Y.NYB", "inverse": True, "weight": 0.07, "enabled": True},
        "vix": {"label": "VIX (US)", "symbol": "^VIX", "inverse": True, "weight": 0.07, "enabled": True},
        "global_pmi": {"label": "Global PMI Proxy", "symbol": "ACWI", "inverse": False, "weight": 0.06, "enabled": True},
        "global_credit": {"label": "Global Credit Spread", "ratio": ["HYG", "LQD"], "inverse": False, "weight": 0.06, "enabled": True},
    },
    "macro_factors": {
        "gst_yoy": {"label": "GST YoY Growth", "local": "gst_monthly", "inverse": False, "weight": 0.06, "enabled": True},
        "india_pmi": {"label": "India Mfg PMI", "local": "pmi_india", "inverse": False, "weight": 0.04, "enabled": True},
        "auto_sales": {"label": "Auto Sales Growth", "local": "auto_sales", "inverse": False, "weight": 0.04, "enabled": True},
        "exports": {"label": "Exports Growth", "local": "exports_india", "inverse": False, "weight": 0.03, "enabled": True},
        "usdinr": {"label": "USD/INR Trend", "symbol": "USDINR=X", "inverse": True, "weight": 0.03, "enabled": True},
    },
    "liquidity_factors": {
        "walcl": {"label": "Fed Balance Sheet", "fred": "WALCL", "inverse": False, "weight": 0.06, "enabled": True, "impulse": True},
        "tga": {"label": "Treasury Account (TGA)", "fred": "WTREGEN", "inverse": True, "weight": 0.04, "enabled": True, "impulse": True},
        "rrp": {"label": "Reverse Repo (RRP)", "fred": "RRPONTSYD", "inverse": True, "weight": 0.04, "enabled": True, "impulse": True},
        "m2": {"label": "Money Supply (M2)", "fred": "M2SL", "inverse": False, "weight": 0.03, "enabled": True},
        "rbi_liq": {"label": "RBI System Liquidity", "local": "rbi_liq", "inverse": False, "weight": 0.04, "enabled": True},
        "india_curve": {"label": "India Yield Curve", "local": "india_curve", "inverse": False, "weight": 0.03, "enabled": True},
        "real_rate": {"label": "Real Interest Rate", "local": "real_rate", "inverse": True, "weight": 0.01, "enabled": True},
    },
    "risk_factors": {
        "india_vix": {"label": "India VIX", "symbol": "INDIAVIX", "inverse": True, "weight": 0.04, "enabled": True},
        "breadth": {"label": "Market Breadth (>200DMA)", "local": "breadth_n200", "inverse": False, "weight": 0.03, "enabled": True},
        "nifty_200dma": {"label": "Nifty 200DMA Trend", "symbol": "^NSEI", "inverse": False, "weight": 0.03, "enabled": True},
        "bank_nifty": {"label": "Bank Nifty Trend", "symbol": "^NSEBANK", "inverse": False, "weight": 0.03, "enabled": True},
        "nasdaq": {"label": "Nasdaq 100 Trend", "symbol": "^NDX", "inverse": False, "weight": 0.02, "enabled": True},
        "bitcoin": {"label": "Bitcoin Trend", "symbol": "BTC-USD", "inverse": False, "weight": 0.015, "enabled": True},
        "brent_gold": {"label": "Brent / Gold Ratio", "ratio": ["BZ=F", "GC=F"], "inverse": True, "weight": 0.015, "enabled": True},
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_regime_settings() -> Dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_REGIME_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            user_settings = json.loads(SETTINGS_FILE.read_text())
            settings = _deep_merge(settings, user_settings)
        except Exception:
            pass
    return settings


def save_regime_settings(settings: Dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2))


def reset_regime_settings() -> Dict[str, Any]:
    settings = copy.deepcopy(DEFAULT_REGIME_SETTINGS)
    save_regime_settings(settings)
    return settings
