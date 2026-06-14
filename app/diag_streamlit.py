"""
Streamlit diagnostic app — runs each pipeline step and shows results.

Usage:
    cd ~/Proyectos/PAC_v2
    streamlit run app/diag_streamlit.py --server.port 8502
"""
import sys
import tempfile
import os
import traceback
from pathlib import Path

import streamlit as st
import numpy as np
import pandas as pd

# ── Path setup (same as app.py) ─────────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent
_ROOT    = _APP_DIR.parent
_SRC     = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

st.title("🔬 PAC — Diagnóstico de Pipeline")
st.caption(f"_ROOT={_ROOT} | _SRC={_SRC}")

uploaded = st.file_uploader("Subí el Excel problemático", type=["xlsx"])
if uploaded is None:
    st.stop()

file_bytes = uploaded.getvalue()
st.success(f"✅ Archivo recibido: **{uploaded.name}** — {len(file_bytes):,} bytes")

# Write to tempfile
with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
    f.write(file_bytes)
    tmp_path = f.name
st.info(f"Tempfile: `{tmp_path}` ({os.path.getsize(tmp_path):,} bytes)")

# ── STEP 1: imports ──────────────────────────────────────────────────────────
st.header("1. Imports")
try:
    import pac.events as pe
    import pac.config as pc
    import pac.ingest as pi
    from pac.events import (
        characterize_edo, compute_baseline_moving, compute_gaps,
        detect_edo_candidates,
    )
    from pac.ingest import load_xlsx_night, normalize_signals
    from pac.config import (
        EDO_BASELINE_WINDOW_S, EDO_DROP_THRESHOLDS_PCT,
        EDO_MIN_DURATION_S, EDO_RECOVERY_PCT, EDO_RESAMPLE_N_POINTS,
        SAMPLING_HZ_NOMINAL, SPO2_MIN_VALID, IRD_WEIGHTS,
        HR_MIN_VALID, HR_MAX_VALID,
    )
    st.success(f"pac.events: `{pe.__file__}`")
    st.success(f"pac.config: `{pc.__file__}`")
    st.json({
        "EDO_MIN_DURATION_S": EDO_MIN_DURATION_S,
        "EDO_RECOVERY_PCT": EDO_RECOVERY_PCT,
        "EDO_DROP_THRESHOLDS_PCT": EDO_DROP_THRESHOLDS_PCT,
        "EDO_RESAMPLE_N_POINTS": EDO_RESAMPLE_N_POINTS,
        "SPO2_MIN_VALID": SPO2_MIN_VALID,
    })
except Exception as e:
    st.error(f"Import error: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 2: load_xlsx_night ──────────────────────────────────────────────────
st.header("2. load_xlsx_night")
try:
    meta, _cls, signals_raw = load_xlsx_night(Path(tmp_path))
    st.success(f"{len(signals_raw)} filas — columnas: {list(signals_raw.columns)}")
    st.write("**dtypes:**", dict(signals_raw.dtypes))
    st.write("**head:**")
    st.dataframe(signals_raw.head(5))
    st.json({k: str(v) for k, v in meta.items()})
except Exception as e:
    st.error(f"load_xlsx_night failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 3: normalize_signals ────────────────────────────────────────────────
st.header("3. normalize_signals")
try:
    from datetime import datetime
    ts_start_str = str(meta.get("time_start", "")).strip()
    try:
        ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %I:%M:%S %p")
    except ValueError:
        try:
            ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts_start = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)
    st.write(f"ts_start: `{ts_start}`")

    sig, _diag = normalize_signals(signals_raw, ts_start)
    st.success(f"{len(sig)} filas — columnas: {list(sig.columns)}")
    st.write("**dtypes:**", dict(sig.dtypes))
    st.dataframe(sig.head(5))
    st.write("**spo2 describe:**")
    st.dataframe(sig["spo2"].describe().to_frame())
except Exception as e:
    st.error(f"normalize_signals failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 4: QC ───────────────────────────────────────────────────────────────
st.header("4. QC SpO2 + HR")
try:
    # SpO2
    sig["spo2_invalid"] = sig["spo2"].isna() | (sig["spo2"] < SPO2_MIN_VALID)
    sig["spo2_clean"]   = sig["spo2"].where(~sig["spo2_invalid"]).astype(float)
    n_inv = int(sig["spo2_invalid"].sum())
    n_ok  = int(sig["spo2_clean"].notna().sum())
    st.success(f"spo2_invalid: {n_inv}/{len(sig)} | spo2_clean válidos: {n_ok}")
    st.dataframe(sig["spo2_clean"].describe().to_frame())

    # HR — requerido por characterize_edo (busca hr_clean en el DataFrame)
    sig["hr_invalid"] = (
        sig["hr"].isna() | (sig["hr"] < HR_MIN_VALID) | (sig["hr"] > HR_MAX_VALID)
    )
    sig["hr_clean"] = sig["hr"].where(~sig["hr_invalid"]).astype(float)
    n_hr_inv = int(sig["hr_invalid"].sum())
    n_hr_ok  = int(sig["hr_clean"].notna().sum())
    st.success(f"hr_invalid: {n_hr_inv}/{len(sig)} | hr_clean válidos: {n_hr_ok}")
    st.dataframe(sig["hr_clean"].describe().to_frame())
except Exception as e:
    st.error(f"QC failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 5: baseline ─────────────────────────────────────────────────────────
st.header("5. compute_baseline_moving")
try:
    ts         = sig["timestamp"]
    spo2_clean = sig["spo2_clean"]
    baseline = compute_baseline_moving(
        spo2_clean,
        window_s=EDO_BASELINE_WINDOW_S,
        sampling_hz=float(SAMPLING_HZ_NOMINAL),
    )
    n_base = int(pd.notna(baseline).sum()) if hasattr(baseline, '__len__') else "?"
    st.success(f"baseline: {n_base} válidos")
    st.write("**baseline describe:**")
    st.dataframe(pd.Series(baseline).describe().to_frame())
except Exception as e:
    st.error(f"compute_baseline_moving failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 6: detect_edo_candidates ────────────────────────────────────────────
st.header("6. detect_edo_candidates")
try:
    candidates = detect_edo_candidates(
        spo2_clean=spo2_clean,
        ts=ts,
        baseline=baseline,
        min_duration_s=EDO_MIN_DURATION_S,
        recovery_pct=EDO_RECOVERY_PCT,
        min_drop_pct=float(min(EDO_DROP_THRESHOLDS_PCT)),
    )
    st.success(f"**{len(candidates)} candidatos** detectados")
    if candidates:
        st.write("Primer candidato:", candidates[0])
except Exception as e:
    st.error(f"detect_edo_candidates failed: {e}")
    st.code(traceback.format_exc())
    st.stop()

# ── STEP 7: characterize_edo (first candidate) ───────────────────────────────
st.header("7. characterize_edo (primer candidato)")
if not candidates:
    st.warning("Sin candidatos — no se puede testear characterize_edo")
else:
    try:
        char = characterize_edo(
            candidates[0],
            sig,
            drop_thresholds_pct=EDO_DROP_THRESHOLDS_PCT,
            n_resample_points=EDO_RESAMPLE_N_POINTS,
            context_window_s=60,
            ird_weights=IRD_WEIGHTS,
        )
        # Remove numpy array for display
        char_display = {k: (v.tolist() if hasattr(v, 'tolist') else str(v))
                        for k, v in char.items() if k != "_spo2_curve"}
        st.success("characterize_edo OK")
        st.json(char_display)
    except Exception as e:
        st.error(f"characterize_edo FAILED: {type(e).__name__}: {e}")
        st.code(traceback.format_exc())
        st.write("**sig dtypes al momento del error:**")
        st.write(dict(sig.dtypes))
        st.write("**sig head:**")
        st.dataframe(sig.head(5))

# ── STEP 8: full characterize loop ───────────────────────────────────────────
st.header("8. Loop completo (todos los candidatos)")
if candidates:
    ok, fail = 0, 0
    first_err = None
    for edo in candidates:
        try:
            characterize_edo(
                edo, sig,
                drop_thresholds_pct=EDO_DROP_THRESHOLDS_PCT,
                n_resample_points=EDO_RESAMPLE_N_POINTS,
                context_window_s=60,
                ird_weights=IRD_WEIGHTS,
            )
            ok += 1
        except Exception as e:
            fail += 1
            if first_err is None:
                first_err = traceback.format_exc()
    st.metric("Exitosos", ok)
    st.metric("Fallidos", fail)
    if first_err:
        st.error("Primer error:")
        st.code(first_err)

os.unlink(tmp_path)
st.success("✅ Diagnóstico completo")
