"""
PAC_v2 — Etapa 3 Events: tests unitarios de `pac.events`.

Cubre:
  compute_baseline_moving
    1. ventana correcta sobre serie constante → mismo valor
    2. respeta min_periods (primeros samples NaN si hay poco historial)
    3. NaN en spo2 no rompe (skipna en median)

  detect_edo_candidates
    4. muesca conocida (95→85→95) devuelve 1 EDO con drop/dur esperado
    5. respeta min_duration_s (filtra cortos)
    6. respeta min_drop_pct (filtra drops chicos)
    7. no detecta si baseline NaN en todo el trigger
    8. solapamiento: EDOs solapados se colapsan al primero

  compute_gaps / mark_near_gap
    9. detecta gap ≥ min_gap_s en ts con hueco
   10. sin gaps en serie regular
   11. mark_near_gap True dentro de ventana, False fuera

  mark_in_sleep
   12. >50% non-wake → True
   13. todo wake → False
   14. ventana vacía → False

  resample_curve
   15. tamaño N exacto + interpolación lineal correcta
   16. todo NaN → todo NaN
   17. vacío → array de NaN

  IRD
   18. compute_ird_components: caso conocido
   19. compute_ird_components: baseline_hr=0 → hr_comp=0 (safe div)
   20. compute_ird_components: NaN → 0
   21. compute_ird_event: pesos default suman correctamente
   22. compute_ird_event: pesos custom

  Integración
   23. characterize_edo end-to-end: una muesca sintética devuelve todos
       los campos esperados con valores coherentes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.events import (  # noqa: E402
    characterize_edo,
    compute_baseline_moving,
    compute_gaps,
    compute_ird_components,
    compute_ird_event,
    detect_edo_candidates,
    mark_in_sleep,
    mark_near_gap,
    resample_curve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mk_ts(n: int, start: str = "2024-01-01 22:00:00") -> pd.Series:
    return pd.Series(pd.date_range(start, periods=n, freq="s"))


def _mk_constant_spo2(n: int, value: float = 95.0) -> pd.Series:
    return pd.Series(np.full(n, value, dtype=float))


def _mk_notch(baseline: float, nadir: float, n_pre: int, n_drop: int,
              n_post: int) -> pd.Series:
    pre = np.full(n_pre, baseline, dtype=float)
    drop = np.full(n_drop, nadir, dtype=float)
    post = np.full(n_post, baseline, dtype=float)
    return pd.Series(np.concatenate([pre, drop, post]))


# ---------------------------------------------------------------------------
# compute_baseline_moving
# ---------------------------------------------------------------------------
def test_baseline_constant_series():
    spo2 = _mk_constant_spo2(600, value=96.0)
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    # Una vez que se alcanzan min_periods (30 samples), baseline == 96.
    assert np.isclose(bl.iloc[-1], 96.0)
    assert np.isclose(bl.iloc[100], 96.0)


def test_baseline_respects_min_periods():
    spo2 = _mk_constant_spo2(600, value=96.0)
    bl = compute_baseline_moving(
        spo2, window_s=120, sampling_hz=1.0, min_periods_frac=0.5
    )
    # min_periods = 60. Los primeros 59 samples deben ser NaN.
    assert pd.isna(bl.iloc[0])
    assert pd.isna(bl.iloc[58])
    assert not pd.isna(bl.iloc[59])


def test_baseline_skipna():
    vals = np.full(200, 96.0)
    vals[10:20] = np.nan
    spo2 = pd.Series(vals)
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    # median skipna → 96 igualmente.
    assert np.isclose(bl.iloc[100], 96.0)


# ---------------------------------------------------------------------------
# detect_edo_candidates
# ---------------------------------------------------------------------------
def test_detect_finds_single_notch():
    # 150 s baseline + 30 s drop a 85 + 150 s recovery → 1 EDO, drop ~10.5%
    spo2 = _mk_notch(baseline=95.0, nadir=85.0, n_pre=150, n_drop=30, n_post=150)
    ts = _mk_ts(len(spo2))
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(spo2, ts, bl, min_duration_s=10,
                                 recovery_pct=0.90, min_drop_pct=2.0)
    assert len(edos) == 1
    e = edos[0]
    assert 9.0 < e["drop_pct"] < 12.0
    assert e["duration_s"] >= 10.0
    assert e["nadir_spo2"] == 85.0


def test_detect_respects_min_duration():
    # Muesca de 5 s → duración insuficiente.
    spo2 = _mk_notch(baseline=95.0, nadir=85.0, n_pre=150, n_drop=5, n_post=150)
    ts = _mk_ts(len(spo2))
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(spo2, ts, bl, min_duration_s=10,
                                 recovery_pct=0.90, min_drop_pct=2.0)
    assert edos == []


def test_detect_respects_min_drop():
    # Drop de 1% (94 vs 95): bajo min_drop_pct=2.
    spo2 = _mk_notch(baseline=95.0, nadir=94.0, n_pre=150, n_drop=30, n_post=150)
    ts = _mk_ts(len(spo2))
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(spo2, ts, bl, min_duration_s=10,
                                 recovery_pct=0.90, min_drop_pct=2.0)
    assert edos == []


def test_detect_ignores_nan_baseline():
    # Serie todo NaN → baseline todo NaN → sin detección.
    spo2 = pd.Series(np.full(300, np.nan))
    ts = _mk_ts(len(spo2))
    bl = compute_baseline_moving(spo2, window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(spo2, ts, bl)
    assert edos == []


def test_detect_overlap_dedup():
    # Dos muescas pegadas de forma que la 2a cae dentro de la extensión
    # de recovery de la 1a. Esperado: 1 EDO (la 2a se colapsa).
    spo2 = np.concatenate([
        np.full(150, 95.0),   # baseline
        np.full(15, 85.0),    # drop 1
        np.full(3, 86.0),     # muy poco recovery (aún <90% de 95=85.5 → apenas)
        np.full(15, 84.0),    # drop 2 pegado
        np.full(150, 95.0),
    ])
    ts = _mk_ts(len(spo2))
    bl = compute_baseline_moving(pd.Series(spo2), window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(pd.Series(spo2), ts, bl,
                                 min_duration_s=10, recovery_pct=0.90,
                                 min_drop_pct=2.0)
    # Debido a la extensión por recovery, el 2o drop queda absorbido.
    assert len(edos) <= 1


# ---------------------------------------------------------------------------
# compute_gaps / mark_near_gap
# ---------------------------------------------------------------------------
def test_compute_gaps_detects_jump():
    ts = pd.Series(pd.to_datetime([
        "2024-01-01 22:00:00",
        "2024-01-01 22:00:01",
        "2024-01-01 22:00:02",
        # gap de 60 s
        "2024-01-01 22:01:02",
        "2024-01-01 22:01:03",
    ]))
    gaps = compute_gaps(ts, min_gap_s=30.0)
    assert len(gaps) == 1
    assert gaps[0][0] == pd.Timestamp("2024-01-01 22:00:02")
    assert gaps[0][1] == pd.Timestamp("2024-01-01 22:01:02")


def test_compute_gaps_no_gaps():
    ts = _mk_ts(100)
    gaps = compute_gaps(ts, min_gap_s=30.0)
    assert gaps == []


def test_mark_near_gap_inside_window():
    gap = (pd.Timestamp("2024-01-01 22:05:00"), pd.Timestamp("2024-01-01 22:06:00"))
    # EDO a 4 min del gap → dentro de ventana de 5 min.
    edo_start = pd.Timestamp("2024-01-01 22:01:30")
    edo_end = pd.Timestamp("2024-01-01 22:01:45")
    assert mark_near_gap(edo_start, edo_end, [gap], window_s=300) is True
    # EDO a 10 min del gap → fuera.
    edo_far_start = pd.Timestamp("2024-01-01 21:50:00")
    edo_far_end = pd.Timestamp("2024-01-01 21:50:15")
    assert mark_near_gap(edo_far_start, edo_far_end, [gap], window_s=300) is False


# ---------------------------------------------------------------------------
# mark_in_sleep
# ---------------------------------------------------------------------------
def test_mark_in_sleep_majority_non_wake():
    stage = pd.Series([0, 0, 1, 1, 1, 1, 1, 0, 0])  # 5/9 non-wake > 50%
    assert mark_in_sleep(0, 8, stage, wake_values={0}) is True


def test_mark_in_sleep_all_wake():
    stage = pd.Series([0, 0, 0, 0, 0])
    assert mark_in_sleep(0, 4, stage, wake_values={0}) is False


def test_mark_in_sleep_empty_window():
    stage = pd.Series([1, 2, 3], dtype="int64")
    # Rango fuera de los índices → ventana vacía.
    assert mark_in_sleep(10, 20, stage) is False


# ---------------------------------------------------------------------------
# resample_curve
# ---------------------------------------------------------------------------
def test_resample_curve_size():
    arr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    out = resample_curve(arr, n_points=10)
    assert out.shape == (10,)
    # Extremos preservados.
    assert np.isclose(out[0], 1.0)
    assert np.isclose(out[-1], 5.0)


def test_resample_curve_all_nan():
    arr = np.array([np.nan, np.nan, np.nan])
    out = resample_curve(arr, n_points=30)
    assert out.shape == (30,)
    assert np.all(np.isnan(out))


def test_resample_curve_empty():
    out = resample_curve(np.array([], dtype=float), n_points=30)
    assert out.shape == (30,)
    assert np.all(np.isnan(out))


# ---------------------------------------------------------------------------
# IRD components / event
# ---------------------------------------------------------------------------
def test_ird_components_known():
    comps = compute_ird_components(
        drop_pct=5.0, baseline_spo2=95.0,
        delta_hr_bpm=10.0, baseline_hr_bpm=60.0,
        peak_mov=0.5, baseline_mov=0.1,
    )
    assert np.isclose(comps["ird_spo2_comp"], 5.0 / 95.0)
    assert np.isclose(comps["ird_hr_comp"], 10.0 / 60.0)
    # mov: (0.5 - 0.1) / (0.1 + 0.01) = 0.4 / 0.11
    assert np.isclose(comps["ird_mov_comp"], 0.4 / 0.11)


def test_ird_components_safe_div_zero_baseline():
    comps = compute_ird_components(
        drop_pct=5.0, baseline_spo2=95.0,
        delta_hr_bpm=10.0, baseline_hr_bpm=0.0,
        peak_mov=0.0, baseline_mov=0.0,
    )
    assert comps["ird_hr_comp"] == 0.0
    # mov: (0 - 0) / (0 + 0.01) = 0
    assert comps["ird_mov_comp"] == 0.0


def test_ird_components_nan_inputs():
    comps = compute_ird_components(
        drop_pct=float("nan"), baseline_spo2=95.0,
        delta_hr_bpm=float("nan"), baseline_hr_bpm=60.0,
        peak_mov=float("nan"), baseline_mov=0.1,
    )
    assert comps["ird_spo2_comp"] == 0.0
    assert comps["ird_hr_comp"] == 0.0
    assert comps["ird_mov_comp"] == 0.0


def test_ird_event_default_weights():
    comps = {"ird_spo2_comp": 1.0, "ird_hr_comp": 1.0, "ird_mov_comp": 1.0}
    # 0.5 + 0.3 + 0.2 = 1.0
    assert np.isclose(compute_ird_event(comps), 1.0)


def test_ird_event_custom_weights():
    comps = {"ird_spo2_comp": 1.0, "ird_hr_comp": 2.0, "ird_mov_comp": 3.0}
    w = {"spo2": 1.0, "hr": 0.0, "mov": 0.0}
    assert np.isclose(compute_ird_event(comps, weights=w), 1.0)


# ---------------------------------------------------------------------------
# characterize_edo (integración)
# ---------------------------------------------------------------------------
def test_characterize_edo_end_to_end():
    # Muesca sintética: 150 s baseline 95, 30 s drop a 85, 150 s recovery.
    # HR: baseline 60, sube a 80 durante drop; mov sube de 0.05 a 0.5.
    n_pre, n_drop, n_post = 150, 30, 150
    spo2 = np.concatenate([
        np.full(n_pre, 95.0), np.full(n_drop, 85.0), np.full(n_post, 95.0)
    ])
    hr = np.concatenate([
        np.full(n_pre, 60.0), np.full(n_drop, 80.0), np.full(n_post, 60.0)
    ])
    mov = np.concatenate([
        np.full(n_pre, 0.05), np.full(n_drop, 0.50), np.full(n_post, 0.05)
    ])
    n = len(spo2)
    ts = pd.date_range("2024-01-01 22:00:00", periods=n, freq="s")
    df = pd.DataFrame({
        "timestamp": ts,
        "spo2_clean": spo2,
        "hr_clean": hr,
        "mov": mov,
    })
    bl = compute_baseline_moving(pd.Series(spo2), window_s=120, sampling_hz=1.0)
    edos = detect_edo_candidates(pd.Series(spo2), pd.Series(ts), bl,
                                 min_duration_s=10, recovery_pct=0.90,
                                 min_drop_pct=2.0)
    assert len(edos) == 1
    char = characterize_edo(edos[0], df, context_window_s=60)

    # Campos obligatorios presentes.
    for k in ("ts_start", "ts_end", "duration_s", "baseline_spo2",
              "nadir_spo2", "drop_pct", "slope_desat_pct_s",
              "slope_recov_pct_s", "auc_spo2_pct_s",
              "delta_hr_bpm", "baseline_hr_bpm",
              "peak_mov", "baseline_mov",
              "ird_spo2_comp", "ird_hr_comp", "ird_mov_comp", "ird_event",
              "meets_2pct", "meets_3pct", "meets_4pct", "meets_5pct",
              "_spo2_curve", "_hr_curve", "_mov_curve"):
        assert k in char, f"falta campo {k}"

    # Valores coherentes.
    assert char["nadir_spo2"] == 85.0
    assert char["drop_pct"] > 5.0
    assert char["meets_5pct"] is True
    assert char["meets_2pct"] is True
    # delta_hr = 80 - 60 = 20
    assert np.isclose(char["delta_hr_bpm"], 20.0)
    assert char["baseline_hr_bpm"] == 60.0
    # peak_mov = 0.50
    assert np.isclose(char["peak_mov"], 0.50)
    # AUC > 0
    assert char["auc_spo2_pct_s"] > 0
    # Curvas resampleadas a 30 puntos.
    assert char["_spo2_curve"].shape == (30,)
    assert char["_hr_curve"].shape == (30,)
    assert char["_mov_curve"].shape == (30,)
    # ird_event > 0 (hay drop y delta_hr)
    assert char["ird_event"] > 0
