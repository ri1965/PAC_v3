"""
Diagnostic script — run from PAC_v2 root:
    python diag_events.py path/to/exam.xlsx
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from pac.ingest import load_xlsx_night, normalize_signals
from pac.events import compute_baseline_moving, detect_edo_candidates
from pac.config import (
    EDO_BASELINE_WINDOW_S,
    EDO_DROP_THRESHOLDS_PCT,
    EDO_MIN_DURATION_S,
    EDO_RECOVERY_PCT,
    SAMPLING_HZ_NOMINAL,
    SPO2_MIN_VALID,
)
from datetime import datetime

excel_path = sys.argv[1] if len(sys.argv) > 1 else "uploads/exam_11550.xlsx"

print(f"=== Diagnostic for {excel_path} ===\n")

# Step 1: load raw
meta, _classical, signals_raw = load_xlsx_night(Path(excel_path))
print(f"[1] load_xlsx_night OK: {len(signals_raw)} rows, columns={list(signals_raw.columns)}")
print(f"    signals_raw dtypes:\n{signals_raw.dtypes}\n")
print(f"    signals_raw head:\n{signals_raw.head(3)}\n")

# Step 2: normalize
ts_start_str = str(meta.get("time_start", "")).strip()
print(f"[2] ts_start_str = '{ts_start_str}'")
try:
    ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %I:%M:%S %p")
except ValueError:
    try:
        ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        ts_start = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
print(f"    ts_start parsed: {ts_start}\n")

sig, _diag = normalize_signals(signals_raw, ts_start)
print(f"[3] normalize_signals OK: {len(sig)} rows, columns={list(sig.columns)}")
print(f"    sig dtypes:\n{sig.dtypes}\n")
print(f"    sig['spo2'] describe:\n{sig['spo2'].describe()}\n")

# Step 3: QC
sig["spo2_invalid"] = sig["spo2"].isna() | (sig["spo2"] < SPO2_MIN_VALID)
sig["spo2_clean"]   = sig["spo2"].where(~sig["spo2_invalid"]).astype(float)

n_invalid = sig["spo2_invalid"].sum()
n_clean   = sig["spo2_clean"].notna().sum()
print(f"[4] SPO2_MIN_VALID = {SPO2_MIN_VALID}")
print(f"    spo2_invalid: {n_invalid}/{len(sig)} ({100*n_invalid/len(sig):.1f}%)")
print(f"    spo2_clean valid: {n_clean}/{len(sig)}")
print(f"    spo2_clean describe:\n{sig['spo2_clean'].describe()}\n")

# Step 4: baseline
ts         = sig["timestamp"]
spo2_clean = sig["spo2_clean"]

baseline = compute_baseline_moving(
    spo2_clean,
    window_s=EDO_BASELINE_WINDOW_S,
    sampling_hz=float(SAMPLING_HZ_NOMINAL),
)
print(f"[5] baseline computed: {baseline.notna().sum()} valid values")
print(f"    baseline describe:\n{pd.Series(baseline).describe()}\n")

# Step 5: candidate detection
print(f"[6] Detection params:")
print(f"    EDO_MIN_DURATION_S     = {EDO_MIN_DURATION_S}")
print(f"    EDO_RECOVERY_PCT       = {EDO_RECOVERY_PCT}")
print(f"    EDO_DROP_THRESHOLDS_PCT= {EDO_DROP_THRESHOLDS_PCT}")
print(f"    min_drop_pct           = {min(EDO_DROP_THRESHOLDS_PCT)}")

candidates = detect_edo_candidates(
    spo2_clean=spo2_clean,
    ts=ts,
    baseline=baseline,
    min_duration_s=EDO_MIN_DURATION_S,
    recovery_pct=EDO_RECOVERY_PCT,
    min_drop_pct=float(min(EDO_DROP_THRESHOLDS_PCT)),
)
print(f"\n[7] detect_edo_candidates → {len(candidates)} candidates")
if candidates:
    print(f"    First candidate: {candidates[0]}")
