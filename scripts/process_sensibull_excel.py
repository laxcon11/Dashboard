import pandas as pd
from pathlib import Path
import re
import shutil

import json
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
TARGET = PROJECT_ROOT / "data" / "option_chain"
QUARANTINE_DIR = PROJECT_ROOT / "data" / "quarantine"
TARGET.mkdir(parents=True, exist_ok=True)
QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

def process_all_downloads(extra_dir: Path = None) -> int:
    """
    Scans the data/option_chain directory for Sensibull Excel/CSV files and ingests them.
    Catches any .xlsx/.csv containing 'NIFTY' in the filename.
    """
    search_dirs = [TARGET, PROJECT_ROOT / "data" / "sensibull"]
    if extra_dir:
        search_dirs.append(extra_dir)

    all_files = []
    patterns = ["nifty", "sensex", "banknifty"]
    for d in search_dirs:
        if d.exists():
            for p in patterns:
                # Match any Excel/CSV with standard index names, but EXCLUDE Standard NDE files
                all_files += [f for f in d.glob("*.xlsx") if p in f.name.lower() and not f.name.startswith("option-chain-ED-sensi-")]
                all_files += [f for f in d.glob("*.csv")  if p in f.name.lower() and not f.name.startswith("option-chain-ED-sensi-")]

    # Deduplicate
    seen = set()
    unique_files = []
    for f in all_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)
    all_files = unique_files

    count = 0
    
    for f in all_files:
        try:
            if f.suffix == ".xlsx":
                df_raw = pd.read_excel(f, nrows=10)
            else:
                df_raw = pd.read_csv(f, nrows=10)
                
            # Sensibull exports often have a header on row 0 or 1. Let's find the "Strike" column.
            header_idx = 0
            for i in range(len(df_raw)):
                row_vals = [str(x).lower() for x in df_raw.iloc[i].values]
                if any("strike" in x for x in row_vals):
                    header_idx = i
                    break
            
            if f.suffix == ".xlsx":
                df = pd.read_excel(f, header=header_idx)
            else:
                df = pd.read_csv(f, header=header_idx)
                
            cols = [str(c).lower().strip() for c in df.columns]
            
            # The structure has CALLS on the left, PUTS on the right, STRIKE in the middle.
            strike_idx = -1
            for i, c in enumerate(cols):
                if "strike" in c:
                    strike_idx = i
                    break
            
            if strike_idx == -1:
                print(f"Warning: 'Strike' column not found in {f.name}")
                continue
                
            out_rows = []
            for _, row in df.iterrows():
                try:
                    strike = float(row.iloc[strike_idx])
                except:
                    continue # Skip empty/junk rows
                
                # Helper to find value in specific side of the table
                def get_val(matcher, start, end, default=0.0):
                    for i in range(start, end):
                        if matcher in cols[i]:
                            try:
                                val = row.iloc[i]
                                if pd.isna(val) or val == '-':
                                    return default
                                return float(str(val).replace(',', ''))
                            except:
                                return default
                    return default
                    
                # Calls are left of strike
                ce_delta = get_val("delta", 0, strike_idx)
                ce_gamma = get_val("gamma", 0, strike_idx)
                ce_theta = get_val("theta", 0, strike_idx)
                ce_vega = get_val("vega", 0, strike_idx)
                ce_oi = get_val("oi", 0, strike_idx, default=0.0) * 100000  # Sensibull uses Lakhs
                ce_ltp = get_val("ltp", 0, strike_idx)
                ce_iv = get_val("iv", 0, strike_idx, default=0.0)
                ce_volume = get_val("volume", 0, strike_idx, default=0.0)
                ce_oi_chng = get_val("oi chng", 0, strike_idx, default=0.0)
                if ce_oi_chng == 0.0:
                    ce_oi_chng = get_val("chng in oi", 0, strike_idx, default=0.0)
                
                # Puts are right of strike
                pe_delta = get_val("delta", strike_idx+1, len(cols))
                pe_gamma = get_val("gamma", strike_idx+1, len(cols))
                pe_theta = get_val("theta", strike_idx+1, len(cols))
                pe_vega = get_val("vega", strike_idx+1, len(cols))
                pe_oi = get_val("oi", strike_idx+1, len(cols), default=0.0) * 100000
                pe_ltp = get_val("ltp", strike_idx+1, len(cols))
                pe_iv = get_val("iv", strike_idx+1, len(cols), default=0.0)
                pe_volume = get_val("volume", strike_idx+1, len(cols), default=0.0)
                pe_oi_chng = get_val("oi chng", strike_idx+1, len(cols), default=0.0)
                if pe_oi_chng == 0.0:
                    pe_oi_chng = get_val("chng in oi", strike_idx+1, len(cols), default=0.0)
                
                out_rows.append({
                    "STRIKE": strike,
                    "OI": ce_oi, "IV": ce_iv if ce_iv > 0 else 15.0, "LTP": ce_ltp,
                    "OI.1": pe_oi, "IV.1": pe_iv if pe_iv > 0 else 15.0, "LTP.1": pe_ltp,
                    "CE_DELTA": ce_delta, "CE_GAMMA": ce_gamma, "CE_THETA": ce_theta, "CE_VEGA": ce_vega,
                    "PE_DELTA": pe_delta, "PE_GAMMA": pe_gamma, "PE_THETA": pe_theta, "PE_VEGA": pe_vega,
                    "CE_VOLUME": ce_volume, "PE_VOLUME": pe_volume,
                    "CE_OI_CHNG": ce_oi_chng, "PE_OI_CHNG": pe_oi_chng
                })
            
            if not out_rows:
                shutil.move(str(f), str(QUARANTINE_DIR / f.name))
                continue
                
            out_df = pd.DataFrame(out_rows)

            # Derive Spot at Fetch (Phase 42 Hardening)
            spot_at_fetch = None
            intrinsic_col = "call intrinsic value(spot)"
            if intrinsic_col in cols:
                col_idx = cols.index(intrinsic_col)
                # Filter for ITM calls
                itm_spots = []
                for _, row in df.iterrows():
                    try:
                        iv_val = float(str(row.iloc[col_idx]).replace(',', ''))
                        strike_val = float(str(row.iloc[strike_idx]).replace(',', ''))
                        if iv_val > 0:
                            itm_spots.append(iv_val + strike_val)
                    except: continue
                if itm_spots:
                    spot_at_fetch = float(np.median(itm_spots))
            
            if spot_at_fetch is None:
                spot_at_fetch = float(out_df["STRIKE"].median())
            
            # Validate Data Quality
            quality_score = 1.0
            validation_flags = []

            if out_df["CE_GAMMA"].sum() == 0 and out_df["PE_GAMMA"].sum() == 0:
                quality_score -= 0.5
                validation_flags.append("MISSING_VENDOR_GREEKS")
            
            if len(out_df) < 10:
                quality_score -= 0.5
                validation_flags.append("LOW_STRIKE_COUNT")
                
            if not out_df["STRIKE"].is_monotonic_increasing:
                quality_score -= 1.0
                validation_flags.append("NON_MONOTONIC_STRIKES")
                
            # ATM structural density check (enhanced: ±2% band)
            median_strike = out_df["STRIKE"].median()
            atm_band = median_strike * 0.02
            atm_rows = out_df[(out_df["STRIKE"] >= median_strike - atm_band) & (out_df["STRIKE"] <= median_strike + atm_band)]
            if len(atm_rows) > 0:
                atm_greek_count = ((atm_rows["CE_GAMMA"].abs() > 0) | (atm_rows["PE_GAMMA"].abs() > 0)).sum()
                if atm_greek_count < 3:
                    quality_score -= 0.3
                    validation_flags.append("ATM_GREEK_SPARSE")

            # Delta Symmetry Check
            if len(atm_rows) > 0 and atm_rows["CE_DELTA"].abs().sum() > 0:
                ce_delta_sum = atm_rows["CE_DELTA"].sum()
                pe_delta_sum = atm_rows["PE_DELTA"].sum()
                if abs(ce_delta_sum + pe_delta_sum) > len(atm_rows) * 0.3:
                    validation_flags.append("DELTA_ASYMMETRY")

            # IV Fidelity Check (Phase 42: separate trust dimension)
            iv_vals = out_df["IV"].tolist() + out_df["IV.1"].tolist()
            real_iv_count = sum(1 for v in iv_vals if v != 15.0 and v > 0)
            iv_is_synthetic = real_iv_count == 0
            if iv_is_synthetic:
                quality_score -= 0.2
                validation_flags.append("IV_SYNTHETIC")

            # Derive integrity status
            if quality_score < 0.5:
                integrity_status = "FAIL"
            elif validation_flags:
                integrity_status = "WARN"
            else:
                integrity_status = "PASS"

            if integrity_status == "FAIL":
                print(f"❌ Failed Quality Check {f.name}: {validation_flags}")
                shutil.move(str(f), str(QUARANTINE_DIR / f.name))
                continue
            
            # Determine expiry date (Phase 41 Hardening)
            def _parse_exp(name):
                # ISO 2026-04-07
                m1 = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
                if m1: return f"{m1.group(3)}-{datetime.strptime(m1.group(2), '%m').strftime('%b')}-{m1.group(1)}"
                
                # DD-Mon-YYYY or DD_Mon_YYYY
                m2 = re.search(r"(\d{2})[-_]([A-Za-z]{3})[-_](\d{4})", name)
                if m2: return f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
                
                # DDMonYYYY
                m3 = re.search(r"(\d{2})([A-Za-z]{3})(\d{4})", name)
                if m3: return f"{m3.group(1)}-{m3.group(2)}-{m3.group(3)}"
                return None

            expiry_str = _parse_exp(f.name)
            if not expiry_str:
                expiry_str = f"UNKNOWN_{count}"
                
            index_name = "NIFTY"
            if "sensex" in f.name.lower(): index_name = "SENSEX"
            elif "banknifty" in f.name.lower(): index_name = "BANKNIFTY"
            
            header = f"EXPIRY DATE: {expiry_str}\nVERSION: Sensibull Multi-Expiry Override\n"
            out_path = TARGET / f"option-chain-ED-sensi-{index_name}-{expiry_str}.csv"
            
            csv_str = out_df.to_csv(index=False)
            out_path.write_text(header + csv_str)
            
            # Write metadata sidecar (Phase 42: multi-dimensional trust)
            meta = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "conversion_time": datetime.now().timestamp(),
                "expiry": expiry_str,
                "source_file": f.name,
                "source_mode": "SENSIBULL_VENDOR_GREEKS" if "MISSING_VENDOR_GREEKS" not in validation_flags else "FAILED_VENDOR_FALLBACK",
                "strikes": len(out_rows),
                "data_quality_score": quality_score,
                "integrity_status": integrity_status,
                "iv_is_synthetic": iv_is_synthetic,
                "validation_flags": validation_flags,
                "spot_at_fetch": spot_at_fetch,
                "engine_version": "1.4"
            }
            meta_path = TARGET / out_path.name.replace(".csv", "_meta.json")
            meta_path.write_text(json.dumps(meta, indent=2))
            
            # Archive the file so it's not processed twice
            archive_dir = PROJECT_ROOT / "data" / "archive"
            archive_dir.mkdir(exist_ok=True)
            shutil.move(str(f), str(archive_dir / f.name))
            
            count += 1
            print(f"✅ Transformed {f.name} -> {out_path.name}  (Quality: {quality_score:.1f})")
            
        except Exception as e:
            print(f"❌ Error processing {f.name}: {e}")
            
    return count

if __name__ == "__main__":
    c = process_all_downloads()
    print(f"Total processed: {c}")
