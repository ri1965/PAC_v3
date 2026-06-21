"""
PAC App — pipeline.py

Thin wrapper over src/pac/ + trained models.
Processes a single-night Excel file end-to-end and returns a structured
result dict ready for the Streamlit app and report generator.

Pipeline:
  1. Ingest    — parse Excel (3-block format)
  2. QC        — range checks on SpO2 / HR
  3. Events    — baseline detection + EDO characterization
  4. Morphotypes — curve C1-C5 + scalar α/β/γ/δ
  5. Windows   — S/M/L windows + feature vectors (24 features)
  6. States    — KMeans state assignment per scale
  7. Features  — NB06 A1 (event rolling) + A2 (night aggregates)
  8. Predict   — LGBM event severity + LR night risk tier
  9. Risk Score— 0.4×P_event + 0.6×P_night → 0..100

Usage:
    from app.pipeline import run_pipeline
    result = run_pipeline("path/to/exam.xlsx", models_dir="models/")
"""
from __future__ import annotations

import json
import pickle
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import entropy as scipy_entropy

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Path defaults
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent                          # PAC_v2 root
_SRC  = _ROOT / "src"
_MODELS_DEFAULT = _ROOT / "models"

import sys
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from pac.ingest import load_xlsx_night, normalize_signals, reconstruct_timestamps
from pac.events import (
    characterize_edo,
    compute_baseline_moving,
    compute_gaps,
    detect_edo_candidates,
)
from pac.morphotypes_curve import (
    load_curve_model,
    predict_curve_cluster,
)
from pac.morphotypes import (
    load_model as load_scalar_morpho_model,
    apply_zscore as scalar_apply_zscore,
    int_to_greek as scalar_int_to_label,
)
from pac.windows import build_windows_for_night
from pac.states import (
    apply_zscore as state_apply_zscore,
    int_to_state_label,
    load_model as load_state_model,
    predict_states,
)
from pac.config import (
    EDO_BASELINE_WINDOW_S,
    EDO_DROP_THRESHOLDS_PCT,
    EDO_MIN_DURATION_S,
    EDO_RECOVERY_PCT,
    EDO_RESAMPLE_N_POINTS,
    HR_MAX_VALID,
    HR_MIN_VALID,
    IRD_WEIGHTS,
    MORPHOTYPE_FEATURES as SCALAR_MORPH_FEATURES,
    SAMPLING_HZ_NOMINAL,
    SPO2_MIN_VALID,
)


# ---------------------------------------------------------------------------
# Constants derived from NB05/NB06 training
# (from nb06_config.json — loaded at module init)
# ---------------------------------------------------------------------------
_CONFIG_CACHE: Optional[dict] = None


def _load_config(models_dir: Path) -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        with open(models_dir / "nb06_config.json") as f:
            _CONFIG_CACHE = json.load(f)
    return _CONFIG_CACHE


# ---------------------------------------------------------------------------
# Step 1+2 — Ingest + QC
# ---------------------------------------------------------------------------

def _ingest_and_qc(excel_path: str | Path) -> tuple[dict, pd.DataFrame]:
    """
    Load Excel and apply range QC.

    Returns
    -------
    meta : dict   — exam metadata (user_id, exam_id, start/end timestamps)
    sig  : DataFrame — columns: timestamp, spo2, spo2_invalid, spo2_clean,
                                hr, hr_invalid, hr_clean, mov, sleep_stage
    """
    meta, _classical, signals_raw = load_xlsx_night(Path(excel_path))

    # Parse ts_start from meta (format: ' 2025-10-31 22:41:02')
    from datetime import datetime
    ts_start_str = str(meta.get("time_start", "")).strip()
    try:
        ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %I:%M:%S %p")
    except ValueError:
        try:
            ts_start = datetime.strptime(ts_start_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts_start = datetime.now().replace(hour=22, minute=0, second=0, microsecond=0)

    # Normalize to canonical 5-column format (timestamp, spo2, hr, mov, sleep_stage)
    sig, _diag = normalize_signals(signals_raw, ts_start)

    # Range QC
    sig["spo2_invalid"] = sig["spo2"].isna() | (sig["spo2"] < SPO2_MIN_VALID)
    sig["spo2_clean"] = sig["spo2"].where(~sig["spo2_invalid"]).astype(float)
    sig["hr_invalid"] = (
        sig["hr"].isna() | (sig["hr"] < HR_MIN_VALID) | (sig["hr"] > HR_MAX_VALID)
    )
    sig["hr_clean"] = sig["hr"].where(~sig["hr_invalid"]).astype(float)

    # Ensure sleep_stage and mov are clean
    sig["sleep_stage"] = sig["sleep_stage"].fillna(0).astype(int)
    sig["mov"] = sig["mov"].fillna(0.0).astype(float)

    # Enrich meta
    meta["user_id"] = str(meta.get("user_id", "")).strip()
    meta["exam_id"]  = str(meta.get("id", "")).strip()
    meta["start_time"] = ts_start
    try:
        ts_end_str = str(meta.get("time_end", "")).strip()
        meta["end_time"] = datetime.strptime(ts_end_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        meta["end_time"] = None

    return meta, sig


# ---------------------------------------------------------------------------
# Step 3 — Event detection + characterization
# ---------------------------------------------------------------------------

def _detect_events(sig: pd.DataFrame) -> list[dict]:
    """
    Detect and characterize all EDO candidates from the night.

    Returns list of characterization dicts (one per event) including:
    ts_start, ts_end, duration_s, baseline_spo2, nadir_spo2, drop_pct,
    slope_desat_pct_s, slope_recov_pct_s, auc_spo2_pct_s, delta_hr_bpm,
    baseline_hr_bpm, peak_mov, baseline_mov, ird_spo2_comp, ird_hr_comp,
    ird_mov_comp, ird_event, _spo2_curve (30-pt array), meets_Npct flags.
    """
    ts         = sig["timestamp"]
    spo2_clean = sig["spo2_clean"]

    baseline = compute_baseline_moving(
        spo2_clean,
        window_s=EDO_BASELINE_WINDOW_S,
        sampling_hz=float(SAMPLING_HZ_NOMINAL),
    )
    candidates = detect_edo_candidates(
        spo2_clean=spo2_clean,
        ts=ts,
        baseline=baseline,
        min_duration_s=EDO_MIN_DURATION_S,
        recovery_pct=EDO_RECOVERY_PCT,
        min_drop_pct=float(min(EDO_DROP_THRESHOLDS_PCT)),
    )
    gaps = compute_gaps(ts, min_gap_s=30.0)

    events: list[dict] = []
    for edo in candidates:
        try:
            char = characterize_edo(
                edo,
                sig,
                drop_thresholds_pct=EDO_DROP_THRESHOLDS_PCT,
                n_resample_points=EDO_RESAMPLE_N_POINTS,
                context_window_s=60,
                ird_weights=IRD_WEIGHTS,
            )
            events.append(char)
        except Exception:
            continue

    return events


# ---------------------------------------------------------------------------
# Step 4 — Morphotype assignment
# ---------------------------------------------------------------------------

def _assign_morphotypes(
    events: list[dict],
    models_dir: Path,
) -> list[dict]:
    """
    Adds 'morphotype_curve' (C1-C5) and 'morphotype' (α/β/γ/δ) to each event.
    """
    if not events:
        return events

    # ── Curve morphotypes (C1-C5) ─────────────────────────────────────────
    curve_model, _meta = load_curve_model(models_dir)
    # Model expects ΔSpO2 = absolute_curve - baseline_spo2 (30-point, each row)
    curves_abs = np.vstack([e["_spo2_curve"] for e in events])   # shape (N, 30)
    baselines  = np.array([e["baseline_spo2"] for e in events]).reshape(-1, 1)
    curves = curves_abs - baselines                               # ΔSpO2 (N, 30)
    curve_labels = predict_curve_cluster(curve_model, curves)  # e.g. ["C1","C3",...]

    # ── Scalar morphotypes (α/β/γ/δ) ─────────────────────────────────────
    scalar_km, scalar_zp, _scalar_meta = load_scalar_morpho_model(models_dir)
    feat_matrix = np.array(
        [[e.get(f, np.nan) for f in SCALAR_MORPH_FEATURES] for e in events]
    )
    feat_matrix_z = scalar_apply_zscore(feat_matrix, scalar_zp)
    # Replace NaN with column mean before predicting (safety net)
    col_means = np.nanmean(feat_matrix_z, axis=0)
    nan_mask = np.isnan(feat_matrix_z)
    feat_matrix_z[nan_mask] = np.take(col_means, np.where(nan_mask)[1])
    scalar_ints   = scalar_km.predict(feat_matrix_z)
    scalar_labels = scalar_int_to_label(scalar_ints)   # e.g. ["α","β","γ",...]

    for i, ev in enumerate(events):
        ev["morphotype_curve"] = curve_labels[i]
        ev["morphotype"]       = scalar_labels[i]

    return events


# ---------------------------------------------------------------------------
# Step 5+6 — Windows + state assignment
# ---------------------------------------------------------------------------

def _build_state_windows(
    sig: pd.DataFrame,
    edos_df: pd.DataFrame,
    models_dir: Path,
) -> dict[str, pd.DataFrame]:
    """
    Build windows and assign PAC states for all three scales (S, M, L).

    Returns dict: {'s': df_s, 'm': df_m, 'l': df_l}
    Each DataFrame has columns: scale, window_idx, t_start, t_end,
    coverage, state_label (e.g. 'M2'), state_int, + 24 features.
    """
    result: dict[str, pd.DataFrame] = {}

    for scale in ("s", "m", "l"):
        # Build feature windows
        win_df = build_windows_for_night(
            silver_df=sig,
            edos_df=edos_df,
            scale=scale,
        )
        if win_df.empty:
            result[scale] = win_df
            continue

        # Load state model for this scale
        km, zp, _meta = load_state_model(scale, models_dir)

        # Feature matrix (24 cols)
        from pac.config import PAC_WINDOW_FEATURES
        feat_cols = [c for c in PAC_WINDOW_FEATURES if c in win_df.columns]
        X = win_df[feat_cols].values.astype(float)
        Xz = state_apply_zscore(X, zp)

        # Impute NaN with column means (safety net for incomplete windows)
        col_means = np.nanmean(Xz, axis=0)
        nan_mask = np.isnan(Xz)
        if nan_mask.any():
            Xz[nan_mask] = np.take(col_means, np.where(nan_mask)[1])
        # Final fallback: replace any remaining NaN with 0
        Xz = np.nan_to_num(Xz, nan=0.0)

        # Predict
        labels_int = predict_states(km, Xz)
        win_df["state_int"]   = labels_int
        win_df["state_label"] = int_to_state_label(labels_int, scale)

        result[scale] = win_df

    return result


# ---------------------------------------------------------------------------
# Step 7 — Map events to states
# ---------------------------------------------------------------------------

def _map_events_to_states(
    events: list[dict],
    state_windows: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    For each event, find the state window active at that event's ts_start.

    Returns a DataFrame with one row per event, columns include:
    ts_start, ts_end, duration_s, morphotype_curve, morphotype, ird_event,
    state_m_label, state_s_label, state_l_label, pre_state_m, is_severe.
    """
    if not events:
        return pd.DataFrame()

    ev_df = pd.DataFrame(events)
    # Remove internal array columns
    drop_cols = [c for c in ev_df.columns if c.startswith("_")]
    ev_df = ev_df.drop(columns=drop_cols)

    for scale, win_df in state_windows.items():
        col = f"state_{scale}_label"
        ev_df[col] = None
        if win_df.empty:
            continue
        for _, win in win_df.iterrows():
            mask = (ev_df["ts_start"] >= win["t_start"]) & (
                ev_df["ts_start"] < win["t_end"]
            )
            ev_df.loc[mask, col] = win["state_label"]

    # Sort by time
    ev_df = ev_df.sort_values("ts_start").reset_index(drop=True)

    # pre_state_m: previous M-state label for each event
    ev_df["pre_state_m"] = ev_df["state_m_label"].shift(1)

    # is_severe: C4 or C5
    ev_df["is_severe"] = ev_df["morphotype_curve"].isin(["C4", "C5"]).astype(int)

    return ev_df


# ---------------------------------------------------------------------------
# Step 8 — NB06 A1: event-level rolling features
# ---------------------------------------------------------------------------

# Pathological M-states (from NB06 config, derived from training)
_PATH_M_DEFAULT = {1, 3}  # M1, M3 — canonical pathological states (PAC_v3, NB04)

def _compute_event_features(
    ev_df: pd.DataFrame,
    config: dict,
    window: int = 30,
) -> pd.DataFrame:
    """
    Compute NB06 A1 rolling features for each event in ev_df.

    Replicates exactly the rolling_event_features() logic from NB06.
    """
    path_m = set(config.get("pathological_states_m", list(_PATH_M_DEFAULT)))
    morph_num = {"C1": 0, "C2": 1, "C3": 2, "C4": 3, "C5": 4}

    def encode_state(label):
        """'M2' → 2.0"""
        if pd.isna(label):
            return np.nan
        import re
        m = re.search(r"(\d+)$", str(label))
        return float(m.group(1)) if m else np.nan

    ev = ev_df.copy()
    ev["state_m_enc"]   = ev["state_m_label"].apply(encode_state)
    ev["state_s_enc"]   = ev["state_s_label"].apply(encode_state)
    ev["state_l_enc"]   = ev["state_l_label"].apply(encode_state)
    ev["pre_state_m_enc"] = ev["pre_state_m"].apply(
        lambda x: float(str(x)[1:]) if pd.notna(x) and len(str(x)) > 1 else np.nan
    )
    ev["pre_eq_current"] = (ev["pre_state_m"] == ev["state_m_label"]).astype(float)
    ev["morph_num"]      = ev["morphotype_curve"].map(morph_num)

    n = len(ev)
    is_sev     = ev["is_severe"].values
    morph_n    = ev["morph_num"].values
    state_m    = ev["state_m_enc"].values
    in_path_m  = np.array([1.0 if (not np.isnan(s) and int(s) in path_m) else 0.0
                           for s in state_m])

    frac_path_prev = np.full(n, np.nan)
    recent_morph   = np.full(n, np.nan)
    ci_so_far      = np.full(n, np.nan)
    n_severe_sofar = np.full(n, np.nan)
    event_position = np.arange(n) / max(n - 1, 1)

    cumul_severe = 0
    cumul_total  = 0
    for i in range(n):
        if cumul_total > 0:
            ci_so_far[i] = cumul_severe / cumul_total
        n_severe_sofar[i] = float(cumul_severe)
        lo = max(0, i - window)
        if i > lo:
            frac_path_prev[i] = in_path_m[lo:i].mean()
            recent_morph[i]   = float(np.nanmean(morph_n[lo:i]))
        if is_sev[i]:
            cumul_severe += 1
        cumul_total += 1

    ev["frac_path_m_30ev"]  = frac_path_prev
    ev["recent_morph_mean"] = recent_morph
    ev["ci_so_far"]         = ci_so_far
    ev["n_severe_so_far"]   = n_severe_sofar
    ev["event_position"]    = event_position

    return ev


# ---------------------------------------------------------------------------
# Step 9 — NB06 A2: night-level features
# ---------------------------------------------------------------------------

def _compute_night_features(
    ev_df: pd.DataFrame,
    state_windows: dict[str, pd.DataFrame],
    config: dict,
    models_dir: Path,
) -> dict:
    """
    Compute all 16 NB06 night-level features for a single night.
    """
    path_m = set(config.get("pathological_states_m", list(_PATH_M_DEFAULT)))  # M1, M3
    path_s = set(config.get("pathological_states_s", [2, 4, 6]))              # S2, S4, S6
    path_l = set(config.get("pathological_states_l", [0, 1]))                 # L0, L1

    import re

    def state_num(label):
        if pd.isna(label):
            return None
        m = re.search(r"(\d+)$", str(label))
        return int(m.group(1)) if m else None

    # ── frac_state_m_M0..M4 (K=5, PAC_v3 canonical) ──────────────────────
    # NOTE: legacy config may reference M5-M7; those columns are padded with 0.0
    # so nb06_night_lr.pkl (trained with M5-M7=0) still receives correct inputs.
    win_m = state_windows.get("m", pd.DataFrame())
    frac_m = {f"frac_state_m_M{i}": 0.0 for i in range(8)}  # pad to 8 for model compat
    entropy_m = np.nan
    n_transitions_m = 0

    if not win_m.empty and "state_label" in win_m.columns:
        labels_m = win_m["state_label"].dropna().tolist()
        if labels_m:
            counts = pd.Series(labels_m).value_counts()
            total  = len(labels_m)
            for i in range(5):  # only M0-M4 exist in K=5 model
                lbl = f"M{i}"
                frac_m[f"frac_state_m_M{i}"] = float(counts.get(lbl, 0)) / total
            # Entropy
            probs = np.array(list(frac_m.values()))
            probs = probs[probs > 0]
            entropy_m = float(scipy_entropy(probs, base=np.e)) if len(probs) > 1 else 0.0
            # Transitions
            seq = win_m["state_label"].tolist()
            n_transitions_m = sum(1 for a, b in zip(seq, seq[1:]) if a != b and pd.notna(a) and pd.notna(b))

    # ── Coupling indices (ci_s, ci_m, ci_l) ───────────────────────────────
    # Computed directly from state_windows (bypasses ev_df column mapping,
    # which can be None if event timestamps fall outside window boundaries).
    sev_ev = ev_df[ev_df["is_severe"] == 1] if not ev_df.empty else pd.DataFrame()

    def _ci_direct(win_df: pd.DataFrame, path_set: set) -> float:
        """
        Fraction of severe events whose ts_start falls in a pathological-state window.
        Robust: uses vectorised window lookup instead of relying on ev_df label columns.
        """
        if sev_ev.empty or win_df.empty or "state_label" not in win_df.columns:
            return np.nan
        # Convert to int64 (nanoseconds) to avoid any dtype/tz comparison issues
        t_starts = pd.to_datetime(win_df["t_start"]).values.astype("int64")
        t_ends   = pd.to_datetime(win_df["t_end"]).values.astype("int64")
        labels   = win_df["state_label"].values
        sev_ts   = pd.to_datetime(sev_ev["ts_start"]).values.astype("int64")
        count_total = 0
        count_path  = 0
        for ts in sev_ts:
            # Use <= t_end to handle nominal boundary events
            mask = (t_starts <= ts) & (ts <= t_ends)
            idx  = np.where(mask)[0]
            if len(idx) > 0:
                m = re.search(r"(\d+)$", str(labels[idx[0]]))
                if m:
                    count_total += 1
                    if int(m.group(1)) in path_set:
                        count_path += 1
        return float(count_path / count_total) if count_total > 0 else np.nan

    ci_s = _ci_direct(state_windows.get("s", pd.DataFrame()), path_s)
    ci_m = _ci_direct(state_windows.get("m", pd.DataFrame()), path_m)
    ci_l = _ci_direct(state_windows.get("l", pd.DataFrame()), path_l)

    # coupling_index = ci_m (from NB06 Gold verification: corr = 1.000)
    coupling_index = ci_m if not np.isnan(ci_m) else np.nan

    # ── pct_severe ─────────────────────────────────────────────────────────
    pct_severe = float(ev_df["is_severe"].mean()) if not ev_df.empty else 0.0

    # ── mean_ari (ARI normalizado, fórmula canónica NB02/T1) ──────────────
    # ARI = 0.6·P(hr_gain) + 0.4·P(mov_gain)  donde P = percentil corpus
    # hr_gain  = delta_hr_bpm / drop_pct
    # mov_gain = (peak_mov - baseline_mov) / drop_pct
    # Distribuciones del corpus (n=85.277 quality events) en models/
    _ari_hr_path  = models_dir / "ari_hr_gain_sorted.npy"
    _ari_mov_path = models_dir / "ari_mov_gain_sorted.npy"
    _ari_cols     = ["delta_hr_bpm", "drop_pct", "peak_mov", "baseline_mov"]
    if (
        not ev_df.empty
        and all(c in ev_df.columns for c in _ari_cols)
        and _ari_hr_path.exists()
        and _ari_mov_path.exists()
    ):
        _c_hr  = np.load(str(_ari_hr_path))
        _c_mov = np.load(str(_ari_mov_path))
        _ev_a  = ev_df.dropna(subset=_ari_cols).copy()
        _ev_a  = _ev_a[_ev_a["drop_pct"] > 0]
        if len(_ev_a) > 0:
            _hr_g  = (_ev_a["delta_hr_bpm"] / _ev_a["drop_pct"]).values
            _mov_g = ((_ev_a["peak_mov"] - _ev_a["baseline_mov"]) / _ev_a["drop_pct"]).values
            _P_hr  = np.searchsorted(_c_hr,  _hr_g)  / len(_c_hr)
            _P_mov = np.searchsorted(_c_mov, _mov_g) / len(_c_mov)
            mean_ari = float(np.mean(0.6 * _P_hr + 0.4 * _P_mov))   # 0–1, mediana corpus ~0.50
        else:
            mean_ari = np.nan
    else:
        # Fallback: raw ird_event si faltan archivos o columnas
        mean_ari = float(ev_df["ird_event"].mean()) if ("ird_event" in ev_df.columns and not ev_df.empty) else np.nan

    # ── night_traj_cluster ─────────────────────────────────────────────────
    traj_features = config.get("traj_features",
        ["frac_state_m_M1","frac_state_m_M3","mean_ari",
         "n_transitions_state_m","entropy_state_m",
         "frac_state_l_L0","frac_state_s_S4"])

    # Build L and S fractions for traj features
    _win_l = state_windows.get("l", pd.DataFrame())
    _frac_l: dict = {}
    if not _win_l.empty and "state_label" in _win_l.columns:
        _lbl_l = _win_l["state_label"].dropna().tolist()
        _tot_l = len(_lbl_l) or 1
        for _i in range(4):
            _frac_l[f"frac_state_l_L{_i}"] = _lbl_l.count(f"L{_i}") / _tot_l
    _win_s = state_windows.get("s", pd.DataFrame())
    _frac_s: dict = {}
    if not _win_s.empty and "state_label" in _win_s.columns:
        _lbl_s = _win_s["state_label"].dropna().tolist()
        _tot_s = len(_lbl_s) or 1
        for _i in range(7):
            _frac_s[f"frac_state_s_S{_i}"] = _lbl_s.count(f"S{_i}") / _tot_s

    traj_vec = {
        **frac_m,
        **_frac_l,
        **_frac_s,
        "pct_severe": pct_severe,
        "mean_ari": mean_ari if not np.isnan(mean_ari) else 0.0,
        "coupling_index": coupling_index if not np.isnan(coupling_index) else 0.0,
        "n_transitions_state_m": float(n_transitions_m),
        "entropy_state_m": entropy_m if not np.isnan(entropy_m) else 0.0,
    }
    traj_vec_arr = np.array([[traj_vec.get(f, 0.0) for f in traj_features]])

    night_traj_cluster = 1  # default: Carga Intermedia (mid risk)
    night_traj_name    = "Carga Intermedia"
    try:
        with open(models_dir / "nb05_traj_kmeans.pkl", "rb") as f:
            traj_model = pickle.load(f)
        Xsc = traj_model["scaler"].transform(traj_vec_arr)
        raw_cluster = int(traj_model["kmeans"].predict(Xsc)[0])
        night_traj_cluster = int(traj_model["cluster_map"][raw_cluster])
        night_traj_name    = traj_model["cluster_names"][night_traj_cluster]
    except Exception:
        pass

    night_feats = {
        **frac_m,
        "ci_s": ci_s,
        "ci_m": ci_m,
        "ci_l": ci_l,
        "coupling_index": coupling_index,
        "entropy_state_m": entropy_m,
        "n_transitions_state_m": float(n_transitions_m),
        "pct_severe": pct_severe,
        "mean_ari": mean_ari,
        "night_traj_cluster": float(night_traj_cluster),
        "night_traj_name": night_traj_name,
    }
    return night_feats


# ---------------------------------------------------------------------------
# Step 10 — Predict + Risk Score
# ---------------------------------------------------------------------------

def _predict(
    ev_df_feat: pd.DataFrame,
    night_feats: dict,
    models_dir: Path,
    config: dict,
) -> dict:
    """
    Run LGBM (event severity) + LR (night risk) and compute risk score.

    Returns dict with predictions and risk score.
    """
    EVENT_FEATURES = config["EVENT_FEATURES"]
    NIGHT_FEATURES = config["NIGHT_FEATURES"]
    event_thr  = config["event_threshold"]
    night_thr  = config["night_threshold"]
    w_event    = config["risk_w_event"]
    w_night    = config["risk_w_night"]
    risk_lo    = config["risk_low_max"]
    risk_hi    = config["risk_high_min"]

    # Load models
    with open(models_dir / "nb06_event_lgbm.pkl", "rb") as f:
        event_model = pickle.load(f)
    with open(models_dir / "nb06_night_lr.pkl", "rb") as f:
        night_model = pickle.load(f)

    # ── Event predictions ──────────────────────────────────────────────────
    ev_preds: dict = {"p_severe": [], "is_severe_pred": []}
    p_severe_mean = np.nan
    p_severe_p90  = np.nan

    if not ev_df_feat.empty:
        ev_valid = ev_df_feat.dropna(subset=EVENT_FEATURES)
        if not ev_valid.empty:
            X_ev = ev_valid[EVENT_FEATURES].values
            p_sev = event_model.predict_proba(X_ev)[:, 1]
            # Map back to full event index
            ev_df_feat = ev_df_feat.copy()
            ev_df_feat["p_severe"] = np.nan
            ev_df_feat.loc[ev_valid.index, "p_severe"] = p_sev
            ev_df_feat["is_severe_pred"] = (ev_df_feat["p_severe"] >= event_thr).astype(float)

            p_arr = ev_df_feat["p_severe"].dropna().values
            if len(p_arr) > 0:
                p_severe_mean = float(np.mean(p_arr))
                p_severe_p90  = float(np.percentile(p_arr, 90))

    # ── Night prediction ───────────────────────────────────────────────────
    X_ni = np.array([[night_feats.get(f, np.nan) for f in NIGHT_FEATURES]])
    # Replace NaN with 0 for inference
    X_ni = np.nan_to_num(X_ni, nan=0.0)
    p_night = float(night_model.predict_proba(X_ni)[0, 1])
    is_high_risk_night = int(p_night >= night_thr)

    # ── Risk Score ─────────────────────────────────────────────────────────
    # Normalise p_severe_mean by the corpus ceiling = p_ev.max() de NB07 (Bloque D),
    # que es el percentil 99 de p_severe_mean sobre la cohorte estricta (494 noches).
    # Antes estaba 0.30 (aprox. incorrecta): inflaba el Risk Score ~25 pts respecto del batch.
    P_SEVERE_CEILING = 0.7431  # = np.percentile(p_severe_mean, 99) del corpus PAC_v3 (NB07 c29)
    p_ev_norm = min(p_severe_mean / P_SEVERE_CEILING, 1.0) if not np.isnan(p_severe_mean) else 0.0
    risk_score = round(
        float(np.clip((w_event * p_ev_norm + w_night * p_night) * 100, 0, 100)),
        1,
    )

    if risk_score < risk_lo:
        risk_label = "Bajo"
    elif risk_score < risk_hi:
        risk_label = "Moderado"
    else:
        risk_label = "Alto"

    return {
        "ev_df": ev_df_feat,
        "p_severe_mean": p_severe_mean,
        "p_severe_p90":  p_severe_p90,
        "p_night":       p_night,
        "is_high_risk_night": is_high_risk_night,
        "risk_score":    risk_score,
        "risk_label":    risk_label,
    }


# ---------------------------------------------------------------------------
# Public API — run_pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    excel_path: str | Path,
    models_dir: str | Path | None = None,
    verbose: bool = True,
) -> dict:
    """
    Full PAC pipeline for a single night Excel file.

    Parameters
    ----------
    excel_path : str | Path
        Path to the exam Excel file (3-block format: metadata, summary, 1-Hz signals).
    models_dir : str | Path | None
        Directory containing all pkl/json model files.  Defaults to PAC_v2/models/.
    verbose : bool
        Print progress messages.

    Returns
    -------
    dict with keys:
        meta          — exam metadata dict
        sig           — QC'd signal DataFrame (1Hz)
        events        — list of event characterization dicts
        ev_df         — event DataFrame with states + NB06 features + predictions
        state_windows — {'s': df, 'm': df, 'l': df} with PAC states
        night_feats   — dict of 16 NB06 night-level features
        risk_score    — float 0-100
        risk_label    — str "Bajo" | "Moderado" | "Alto"
        p_night       — float, P(high risk night)
        p_severe_mean — float, mean P(severe event)
        p_severe_p90  — float, 90th pct P(severe event)
        is_high_risk_night — int 0/1
        n_events      — int, total EDOs detected
        n_severe      — int, events classified as severe (C4/C5)
        traj_name     — str, night trajectory cluster name
    """
    models_dir = Path(models_dir) if models_dir else _MODELS_DEFAULT
    config = _load_config(models_dir)

    def _log(msg):
        if verbose:
            print(f"[PAC] {msg}")

    # ── 1+2. Ingest + QC ──────────────────────────────────────────────────
    _log("Ingesting Excel...")
    meta, sig = _ingest_and_qc(excel_path)
    _log(f"  {len(sig):,} samples | {meta.get('user_id','?')} | "
         f"{meta.get('start_time','?')} → {meta.get('end_time','?')}")

    # ── 3. Event detection ────────────────────────────────────────────────
    _log("Detecting EDOs...")
    events = _detect_events(sig)
    _log(f"  {len(events)} events detected")

    if not events:
        _log("WARNING: no events detected — returning empty result")
        return {
            "meta": meta, "sig": sig, "events": [],
            "ev_df": pd.DataFrame(), "state_windows": {},
            "night_feats": {}, "risk_score": np.nan, "risk_label": "Desconocido",
            "p_night": np.nan, "p_severe_mean": np.nan, "p_severe_p90": np.nan,
            "is_high_risk_night": 0, "n_events": 0, "n_severe": 0,
            "traj_name": "Desconocido",
        }

    # ── 4. Morphotype assignment ───────────────────────────────────────────
    _log("Assigning morphotypes (C1-C5 + α/β/γ/δ)...")
    events = _assign_morphotypes(events, models_dir)

    # Build edos_df for window computation
    edos_df = pd.DataFrame([
        {
            "ts_start": e["ts_start"],
            "ts_end":   e["ts_end"],
            "morphotype": e.get("morphotype", None),
            "morphotype_curve": e.get("morphotype_curve", None),
            "ird_event": e.get("ird_event", np.nan),
            "drop_pct": e.get("drop_pct", np.nan),
            "duration_s": e.get("duration_s", np.nan),
            "nadir_spo2": e.get("nadir_spo2", np.nan),
            "baseline_spo2": e.get("baseline_spo2", np.nan),
        }
        for e in events
    ])
    _log(f"  C4+C5: {edos_df['morphotype_curve'].isin(['C4','C5']).sum()} severe")

    # ── 5+6. Windows + States ─────────────────────────────────────────────
    _log("Building PAC state windows (S/M/L)...")
    state_windows = _build_state_windows(sig, edos_df, models_dir)
    for sc, df in state_windows.items():
        _log(f"  {sc.upper()}-scale: {len(df)} windows, "
             f"states: {sorted(df['state_label'].dropna().unique()) if not df.empty else []}")

    # ── 7. Map events to states ───────────────────────────────────────────
    _log("Mapping events to states...")
    ev_df = _map_events_to_states(events, state_windows)

    # ── 8. NB06 A1: event-level features ─────────────────────────────────
    _log("Computing NB06 A1 event features...")
    ev_df = _compute_event_features(ev_df, config)

    # ── 9. NB06 A2: night features ────────────────────────────────────────
    _log("Computing NB06 A2 night features...")
    night_feats = _compute_night_features(ev_df, state_windows, config, models_dir)
    _log(f"  ci_m={night_feats.get('ci_m', np.nan):.3f}  "
         f"pct_severe={night_feats.get('pct_severe', 0):.3f}  "
         f"traj={night_feats.get('night_traj_name','?')}")

    # ── 10. Predict + Risk Score ──────────────────────────────────────────
    _log("Predicting (LGBM event + LR night)...")
    preds = _predict(ev_df, night_feats, models_dir, config)
    ev_df = preds.pop("ev_df")

    _log(f"  Risk Score: {preds['risk_score']} ({preds['risk_label']}) | "
         f"P_night={preds['p_night']:.3f} | "
         f"P_sev_mean={preds.get('p_severe_mean', np.nan):.3f}")

    return {
        "meta":          meta,
        "sig":           sig,
        "events":        events,
        "ev_df":         ev_df,
        "state_windows": state_windows,
        "night_feats":   night_feats,
        "n_events":      len(events),
        "n_severe":      int(edos_df["morphotype_curve"].isin(["C4","C5"]).sum()),
        "traj_name":     night_feats.get("night_traj_name", "?"),
        **preds,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        print("Usage: python pipeline.py <excel_path>")
        sys.exit(1)
    result = run_pipeline(path, verbose=True)
    print("\n── Result summary ──")
    print(f"  n_events      : {result['n_events']}")
    print(f"  n_severe      : {result['n_severe']}")
    print(f"  risk_score    : {result['risk_score']}")
    print(f"  risk_label    : {result['risk_label']}")
    print(f"  p_night       : {result['p_night']:.3f}")
    print(f"  traj_name     : {result['traj_name']}")
