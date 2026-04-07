"""
process_sensibull_csv.py
=========================
Converts Sensibull-exported CSVs (already in data/option_chain/)
from the format:
  NIFTY_2026-04-07_option_chain_<timestamp>.csv
into the NDE-standard wide CSV that nde_options_logic can parse.
"""

import pandas as pd
import numpy as np
import re
import json
import shutil
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
OPTION_CHAIN_DIR = PROJECT_ROOT / "data" / "option_chain"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
OPTION_CHAIN_DIR.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

def _safe_float(val, default=0.0):
    try:
        if pd.isna(val) or str(val).strip() in ("--", "", "nan"):
            return default
        return float(str(val).replace(",", ""))
    except Exception:
        return default

def _parse_expiry_from_filename(name: str) -> str | None:
    """
    Attempts multiple regex patterns to extract an expiry date.
    Returns ISO 8601 string (YYYY-MM-DD) or None.
    """
    # Pattern 1: ISO 2026-04-07
    m1 = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if m1:
        return f"{m1.group(1)}-{m1.group(2)}-{m1.group(3)}"
    
    # Pattern 2: DD-Mon-YYYY (07-Apr-2026)
    m2 = re.search(r"(\d{2})-([A-Za-z]{3})-(\d{4})", name)
    if m2:
        try:
            dt = datetime.strptime(m2.group(0), "%d-%b-%Y")
            return dt.strftime("%Y-%m-%d")
        except: pass

    # Pattern 3: DDMonYYYY (07Apr2026)
    m3 = re.search(r"(\d{2})([A-Za-z]{3})(\d{4})", name)
    if m3:
        try:
            dt = datetime.strptime(m3.group(0), "%d%b%Y")
            return dt.strftime("%Y-%m-%d")
        except: pass

    return None

def convert_sensibull_csv(src: Path) -> str | None:
    """
    Convert a single Sensibull CSV → NDE-standard sensi CSV.
    Returns the output filename on success, None on failure.
    """
    expiry_iso = _parse_expiry_from_filename(src.name)
    if not expiry_iso:
        print(f"⚠️  Skipping {src.name} — can't parse expiry date from filename")
        return None

    expiry_dt  = datetime.strptime(expiry_iso, "%Y-%m-%d")
    expiry_str = expiry_dt.strftime("%d-%b-%Y")       # "07-Apr-2026"

    # Avoid processing already-standard files to prevent loops
    if src.name == f"option-chain-ED-sensi-NIFTY-{expiry_str}.csv":
        return None

    try:
        df = pd.read_csv(src)
    except Exception as e:
        print(f"❌ Error reading {src.name}: {e}")
        return None

    # Normalise column names
    df.columns = [c.strip() for c in df.columns]

    out_rows = []
    for _, row in df.iterrows():
        strike = _safe_float(row.get("Strike"), default=None)
        if strike is None:
            continue

        # IV in middle (single column in some CSVs, double in others)
        iv_val = _safe_float(row.get("IV"), default=15.0)
        
        out_rows.append({
            # ── Core fields expected by parse_nse_option_chain_csv ──
            "STRIKE":   strike,

            # Call side
            "OI":       _safe_float(row.get("Call OI")),
            "IV":       iv_val,
            "LTP":      _safe_float(row.get("Call LTP")),

            # Put side
            "OI.1":     _safe_float(row.get("Put OI")),
            "IV.1":     iv_val,
            "LTP.1":    _safe_float(row.get("Put LTP")),

            # ── Institutional Greeks (sensi_* override fields) ──
            "CE_DELTA": _safe_float(row.get("Call Delta")),
            "CE_GAMMA": _safe_float(row.get("Call Gamma")),
            "CE_THETA": _safe_float(row.get("Call Theta")),
            "CE_VEGA":  _safe_float(row.get("Call Vega")),
            "PE_DELTA": _safe_float(row.get("Put Delta")),
            "PE_GAMMA": _safe_float(row.get("Put Gamma")),
            "PE_THETA": _safe_float(row.get("Put Theta")),
            "PE_VEGA":  _safe_float(row.get("Put Vega")),

            # ── High-Fidelity Flow (Phase 42) ──
            "CE_VOLUME": _safe_float(row.get("Call Volume")),
            "PE_VOLUME": _safe_float(row.get("Put Volume")),
            "CE_OI_CHNG": _safe_float(row.get("Call OI Change")),
            "PE_OI_CHNG": _safe_float(row.get("Put OI Change")),
        })

    if not out_rows:
        print(f"❌ No valid rows in {src.name}")
        shutil.move(str(src), str(QUARANTINE_DIR / src.name))
        return None

    out_df = pd.DataFrame(out_rows)

    # Validate Data Quality (Density)
    quality_score = 1.0
    validation_flags = []

    # Check missing Gamma density vs standard requirements
    if out_df["CE_GAMMA"].sum() == 0 and out_df["PE_GAMMA"].sum() == 0:
        quality_score -= 0.5
        validation_flags.append("MISSING_VENDOR_GREEKS")
    
    if len(out_df) < 10:
        quality_score -= 0.5
        validation_flags.append("LOW_STRIKE_COUNT")
        
    if not out_df["STRIKE"].is_monotonic_increasing:
        quality_score -= 1.0
        validation_flags.append("NON_MONOTONIC_STRIKES")
        
    # IV Fidelity Check (Phase 42)
    iv_vals = out_df["IV"].tolist()
    real_iv_count = sum(1 for v in iv_vals if v != 15.0 and v > 0)
    iv_is_synthetic = real_iv_count == 0
    if iv_is_synthetic:
        quality_score -= 0.2
        validation_flags.append("IV_SYNTHETIC")

    if quality_score < 0.5:
        print(f"❌ Failed Quality Check {src.name}: {validation_flags}")
        shutil.move(str(src), str(QUARANTINE_DIR / src.name))
        return None

    # Write with NDE header format
    out_name = f"option-chain-ED-sensi-NIFTY-{expiry_str}.csv"
    out_path  = OPTION_CHAIN_DIR / out_name
    header    = f"EXPIRY DATE: {expiry_str}\nVERSION: Sensibull High-Fidelity Greeks\n"
    out_path.write_text(header + out_df.to_csv(index=False))

    # Write metadata sidecar
    meta = {
        "timestamp":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "conversion_time": datetime.now().timestamp(),
        "expiry":       expiry_str,
        "source_file":  src.name,
        "source_mode":  "SENSIBULL_VENDOR_GREEKS" if "MISSING_VENDOR_GREEKS" not in validation_flags else "FAILED_VENDOR_FALLBACK",
        "strikes":      len(out_rows),
        "data_quality_score": quality_score,
        "iv_is_synthetic": iv_is_synthetic,
        "validation_flags": validation_flags,
        "engine_version": "1.3"
    }
    meta_path = OPTION_CHAIN_DIR / out_name.replace(".csv", "_meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    print(f"✅ {src.name}  →  {out_name}  ({len(out_rows)} strikes | Quality: {quality_score:.1f})")
    
    # Archive the original instead of leaving it
    archive_dir = PROJECT_ROOT / "data" / "archive"
    archive_dir.mkdir(exist_ok=True)
    shutil.move(str(src), str(archive_dir / src.name))
    
    return out_name


def convert_all_sensibull_csvs() -> int:
    """
    Scan both the standard dir and the incoming sensibull drop zone.
    Returns count of successfully converted files.
    """
    search_dirs = [OPTION_CHAIN_DIR, PROJECT_ROOT / "data" / "sensibull"]
    
    raw_files = []
    for d in search_dirs:
        if d.exists():
            raw_files.extend(sorted(d.glob("NIFTY_*_option_chain_*.csv")))
            
    if not raw_files:
        return 0

    # If multiple files for same expiry exist, keep only the newest
    by_expiry = {}
    for f in raw_files:
        m = re.search(r"NIFTY_(\d{4}-\d{2}-\d{2})_option_chain", f.name)
        if m:
            key = m.group(1)
            if key not in by_expiry or f.stat().st_mtime > by_expiry[key].stat().st_mtime:
                by_expiry[key] = f

    count = 0
    for f in by_expiry.values():
        result = convert_sensibull_csv(f)
        if result:
            count += 1

    return count


if __name__ == "__main__":
    n = convert_all_sensibull_csvs()
    print(f"\nConverted {n} files.")
