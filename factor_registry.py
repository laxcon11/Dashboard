"""
Single source of truth for cross-page factors and update modes.
"""

from __future__ import annotations


FACTOR_REGISTRY = {
    "NIFTY50": {
        "label": "NIFTY 50",
        "symbol": "^NSEI",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "BANKNIFTY": {
        "label": "Bank NIFTY",
        "symbol": "^NSEBANK",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "SPX": {
        "label": "S&P 500",
        "symbol": "^GSPC",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "NASDAQ": {
        "label": "NASDAQ",
        "symbol": "^IXIC",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "US10Y": {
        "label": "US 10Y Yield",
        "symbol": "^TNX",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "DXY": {
        "label": "Dollar Index",
        "symbol": "DX-Y.NYB",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "COPPER": {
        "label": "Copper",
        "symbol": "HG=F",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "GOLD": {
        "label": "Gold",
        "symbol": "GC=F",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "CRUDE": {
        "label": "Crude Oil",
        "symbol": "CL=F",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "BITCOIN": {
        "label": "Bitcoin",
        "symbol": "BTC-USD",
        "source": "Yahoo Finance",
        "update_mode": {"global_markets": "live_first", "default": "close_only"},
        "fallback": "Latest cached close",
    },
    "SOFR": {
        "label": "SOFR",
        "symbol": "SOFR",
        "source": "FRED",
        "update_mode": {"default": "close_only"},
        "fallback": "None",
    },
}


def get_factor_meta(key: str) -> dict:
    return FACTOR_REGISTRY.get(key, {})
