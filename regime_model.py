import copy
import json
from pathlib import Path
from typing import Any, Dict


SETTINGS_FILE = Path("notes/regime_settings.json")


DEFAULT_REGIME_SETTINGS: Dict[str, Any] = {
    "blend": {
        "macro_weight": 0.60,
        "liquidity_weight": 0.40,
        "fast_weight": 0.40,
        "slow_weight": 0.60,
        "impulse_influence": 0.25,
        "fast_window": 1,
        "slow_window": 10,
        "max_factor_weight": 0.20,
        "neutral_band": 0.30,
        "risk_on_threshold": 0.60,
        "risk_off_threshold": 0.60,
        "sofr_iorb_penalty_enabled": True,
        "sofr_iorb_warn_bps": 5.0,
        "sofr_iorb_full_penalty_bps": 15.0,
        "sofr_iorb_max_penalty": 0.25,
        "sofr_iorb_persistence_days": 3,
        "sofr_iorb_persisted_max_penalty": 0.35,
        "group_caps": {
            "Macro": 0.30,
            "Liquidity": 0.35,
            "Risk Appetite": 0.20,
            "Rates/Currency": 0.20,
            "Commodities": 0.20,
        },
    },
    "macro_factors": {
        "nifty50": {"label": "NIFTY 50", "symbol": "^NSEI", "inverse": False, "weight": 0.13, "enabled": True, "group": "Macro"},
        "nasdaq": {"label": "NASDAQ", "symbol": "^IXIC", "inverse": False, "weight": 0.11, "enabled": True, "group": "Macro"},
        "bank_nifty": {"label": "Bank NIFTY", "symbol": "^NSEBANK", "inverse": False, "weight": 0.09, "enabled": True, "group": "Macro"},
        "dxy": {"label": "Dollar Index", "symbol": "DX-Y.NYB", "inverse": True, "weight": 0.10, "enabled": True, "group": "Rates/Currency"},
        "usdinr": {"label": "USD/INR", "symbol": "USDINR=X", "inverse": True, "weight": 0.08, "enabled": True, "group": "Rates/Currency"},
        "us10y": {"label": "US 10Y Yield", "symbol": "^TNX", "inverse": True, "weight": 0.10, "enabled": True, "group": "Rates/Currency"},
        "crude": {"label": "Crude Oil", "symbol": "CL=F", "inverse": True, "weight": 0.08, "enabled": True, "group": "Commodities"},
        "gold": {"label": "Gold", "symbol": "GC=F", "inverse": True, "weight": 0.06, "enabled": True, "group": "Commodities"},
        "bitcoin": {"label": "Bitcoin", "symbol": "BTC-USD", "inverse": False, "weight": 0.07, "enabled": True, "group": "Risk Appetite"},
        "credit_spread": {"label": "Credit Spread (HYG/LQD)", "ratio": ["HYG", "LQD"], "inverse": False, "weight": 0.09, "enabled": True, "group": "Risk Appetite"},
        "copper_gold": {"label": "Copper/Gold Ratio", "ratio": ["HG=F", "GC=F"], "inverse": False, "weight": 0.09, "enabled": True, "group": "Commodities"},
    },
    "liquidity_factors": {
        "walcl": {"label": "Fed Balance Sheet (WALCL)", "fred": "WALCL", "inverse": False, "weight": 0.26, "enabled": True, "group": "Liquidity"},
        "rrp": {"label": "Reverse Repo (RRPONTSYD)", "fred": "RRPONTSYD", "inverse": True, "weight": 0.22, "enabled": True, "group": "Liquidity"},
        "tga": {"label": "Treasury General Account (WTREGEN)", "fred": "WTREGEN", "inverse": True, "weight": 0.22, "enabled": True, "group": "Liquidity"},
        "m2": {"label": "Money Supply (M2SL)", "fred": "M2SL", "inverse": False, "weight": 0.16, "enabled": True, "group": "Liquidity"},
        "sofr_iorb": {"label": "SOFR - IORB Spread", "fred_spread": ["SOFR", "IORB"], "inverse": True, "weight": 0.14, "enabled": True, "group": "Liquidity"},
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
