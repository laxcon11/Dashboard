import requests
import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime

logger = logging.getLogger(__name__)

class NSEv3Client:
    """
    Institutional-grade NSE v3 Client.
    Handles multi-stage session handshakes, exponential backoff, and v3 JSON parsing.
    """
    BASE = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.nseindia.com/option-chain",
        "Connection": "keep-alive",
        "X-Requested-With": "XMLHttpRequest"
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._init_session()

    def _init_session(self):
        """Mandatory 2-stage warmup: Lander -> Option Chain Page."""
        try:
            logger.info("Initializing NSE Session (Handshake v3)...")
            # Step 1: Base Lander
            self.session.get(self.BASE, timeout=10)
            time.sleep(1.0)
            # Step 2: Option Chain Bridge (Sets nsit cookie)
            self.session.get(f"{self.BASE}/option-chain", timeout=10)
            time.sleep(1.0)
            logger.info("✅ NSE Session Initialized Successfully.")
        except Exception as e:
            logger.error(f"❌ NSE Session Init Failed: {e}")

    def fetch_chain(self, symbol="NIFTY", expiry=None):
        """
        Fetch option chain with 4-stage exponential backoff.
        """
        url = f"{self.BASE}/api/option-chain-v3?type=Indices&symbol={symbol}"
        if expiry:
            url += f"&expiryDate={expiry}"

        for i in range(4):
            try:
                resp = self.session.get(url, timeout=15)
                
                if resp.status_code == 200:
                    data = resp.json()
                    # Validation
                    if "records" not in data or "data" not in data["records"]:
                        logger.warning(f"Attempt {i+1}: Invalid payload structure. Retrying...")
                    else:
                        return data
                
                # Session expired or blocked -> Re-init
                if resp.status_code in [401, 403]:
                    logger.warning(f"Attempt {i+1}: Session Blocked ({resp.status_code}). Re-initializing...")
                    self._init_session()
                else:
                    logger.warning(f"Attempt {i+1}: Fetch failed with status {resp.status_code}.")

            except Exception as e:
                logger.warning(f"Attempt {i+1}: Networking error: {e}")
                self._init_session()

            sleep_time = min(2**i, 5)
            time.sleep(sleep_time)

        logger.error(f"❌ Failed to fetch NSE chain for {symbol} after 4 attempts.")
        return None

def parse_v3_chain(data: dict):
    """
    Transforms v3 JSON structure into high-fidelity NDE DataFrame.
    """
    if not data or "records" not in data:
        return pd.DataFrame(), 0.0

    spot = data["records"].get("underlyingValue", 0.0)
    rows = []
    
    for item in data["records"]["data"]:
        strike = item.get("strikePrice")
        expiry = item.get("expiryDate")
        
        ce = item.get("CE", {})
        pe = item.get("PE", {})
        
        rows.append({
            "strike": strike,
            "expiry": expiry,
            "call_ltp": ce.get("lastPrice", 0.0),
            "put_ltp": pe.get("lastPrice", 0.0),
            "call_oi": ce.get("openInterest", 0.0),
            "put_oi": pe.get("openInterest", 0.0),
            "call_iv": ce.get("impliedVolatility", 0.0),
            "put_iv": pe.get("impliedVolatility", 0.0),
        })
        
    df = pd.DataFrame(rows)
    
    # Minimal validation: Drop rows without a strike
    df = df.dropna(subset=["strike"])
    
    # Cast to numeric to ensure safety in Greeks engine
    numeric_cols = ["strike", "call_ltp", "put_ltp", "call_oi", "put_oi", "call_iv", "put_iv"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        
    return df, spot

def clean_chain(df: pd.DataFrame, spot: float, atr: float = 250.0, aggressive: bool = False):
    """
    Deterministic ATR-dynamic strike cleaning.
    Clamps range with +/- 5% floor to maintain coverage in low-vol regimes.
    """
    if df.empty or spot <= 0:
        return df
        
    mult = 2.0 if aggressive else 1.5
    
    # Clamping: Ensure at least +/- 5% coverage even in compressed volatility regimes.
    # This prevents the terminal from looking 'empty' when ATR is very low (< 200).
    lower = min(spot * 0.95, spot - mult * atr)
    upper = max(spot * 1.05, spot + mult * atr)
    
    # Filter by range
    df = df[(df["strike"] >= lower) & (df["strike"] <= upper)]
    
    # Edge Case Filter: Drop strikes with zero OI on both sides (illiquid/noise)
    df = df[(df["call_oi"] > 0) | (df["put_oi"] > 0)]
    
    return df
