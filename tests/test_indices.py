"""
PAC_v2 — Etapa 3 Events: tests unitarios de `pac.indices`.

Cubre:
  SpO2 family
    1. compute_odi: 10 eventos / 28800 s = 1.25/h
    2. compute_odi: tst=0 → 0
    3. compute_t_under: fracción correcta con NaN
    4. compute_ct_under: minutos correctos
    5. compute_spo2_stats: stats conocidas
    6. compute_spo2_stats: todo NaN → todo NaN
    7. compute_hypoxic_burden: caso conocido
    8. compute_hypoxic_burden: todo ≥ threshold → 0

  HR family
    9. compute_hr_stats: valores conocidos
   10. count_sustained_extremes '<': episodio de 15s cuenta 1
   11. count_sustained_extremes: episodio corto no cuenta
   12. count_sustained_extremes: comparador inválido → ValueError
   13. compute_delta_hr_stats: valores conocidos
   14. compute_delta_hr_stats: sin eventos → NaN

  Movement
   15. compute_mov_stats: movement_index_per_h > 0 con picos conocidos

  Sleep
   16. compute_sleep_stats: caso con WASO y stage shifts
   17. compute_sleep_stats: fallback sin staging → TST=duration
   18. compute_sleep_stats: wake-only → TST=0, latency=duration

  Event-based
   19. compute_ird_night: caso conocido
   20. compute_ird_night: tst=0 → 0
   21. compute_ird_event_stats: valores conocidos
   22. compute_ird_event_stats: vacío → NaN
   23. compute_odi_ahi_family: con in_sleep filter
   24. compute_odi_ahi_family: sin eventos → todo 0.0
   25. compute_edo_morphology_stats: valores conocidos
   26. compute_edo_morphology_stats: vacío → n=0

  Validación quinteto
   27. compute_diff_vs_device: caso bajo threshold → flag False
   28. compute_diff_vs_device: caso sobre threshold → flag True
   29. compute_diff_vs_device: device=0, pac_v2>0 → diff_rel=inf, flag False
   30. compute_diff_vs_device: device=NaN → todo NaN
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.indices import (  # noqa: E402
    compute_ahi,
    compute_ct_under,
    compute_delta_hr_stats,
    compute_diff_vs_device,
    compute_edo_morphology_stats,
    compute_hr_stats,
    compute_hypoxic_burden,
    compute_ird_event_stats,
    compute_ird_night,
    compute_mov_stats,
    compute_odi,
    compute_odi_ahi_family,
    compute_sleep_stats,
    compute_spo2_stats,
    compute_t_under,
    count_sustained_extremes,
)


# ---------------------------------------------------------------------------
# SpO2 — ODI / AHI
# ---------------------------------------------------------------------------
def test_odi_basic():
    # 10 eventos en 8 h → 1.25/h
    assert np.isclose(compute_odi(10, tst_s=28800.0), 1.25)


def test_odi_zero_tst():
    assert compute_odi(5, tst_s=0.0) == 0.0


def test_ahi_alias():
    # ahi == odi (se define igual; diferencia es in_sleep filter upstream)
    assert compute_ahi(5, tst_s=28800.0) == compute_odi(5, tst_s=28800.0)


# ---------------------------------------------------------------------------
# SpO2 — T< y CT<
# ---------------------------------------------------------------------------
def test_t_under_with_nan():
    spo2 = pd.Series([95, 88, 89, 91, np.nan, np.nan, 92, 85])
    # Valid: 6 samples. <90: 88, 89, 85 → 3 / 6 = 0.5
    assert np.isclose(compute_t_under(spo2, 90.0), 0.5)


def test_ct_under_minutes():
    # 60 samples < 90 a 1 Hz → 60 s → 1.0 min
    spo2 = pd.Series(np.concatenate([np.full(60, 85.0), np.full(60, 95.0)]))
    assert np.isclose(compute_ct_under(spo2, 90.0, sampling_hz=1.0), 1.0)


def test_spo2_stats_known():
    spo2 = pd.Series([90.0, 92.0, 94.0, 96.0, 98.0])
    s = compute_spo2_stats(spo2)
    assert np.isclose(s["mean_spo2"], 94.0)
    assert np.isclose(s["median_spo2"], 94.0)
    assert s["min_spo2"] == 90.0


def test_spo2_stats_all_nan():
    spo2 = pd.Series([np.nan, np.nan, np.nan])
    s = compute_spo2_stats(spo2)
    for k in ("mean_spo2", "median_spo2", "min_spo2", "std_spo2"):
        assert np.isnan(s[k])


# ---------------------------------------------------------------------------
# SpO2 — Hypoxic Burden
# ---------------------------------------------------------------------------
def test_hypoxic_burden_known():
    # 3600 s: 60 s a 85 (deficit=5) → 300 %·s = 5 %·min
    # Normalizado a %·min/h: 5 * 3600 / 3600 = 5
    n = 3600
    spo2 = np.concatenate([np.full(60, 85.0), np.full(n - 60, 95.0)])
    ts = pd.date_range("2024-01-01 22:00:00", periods=n, freq="s")
    hb = compute_hypoxic_burden(
        pd.Series(spo2), pd.Series(ts), threshold_pct=90.0, sampling_hz=1.0
    )
    # np.trapezoid sobre step function tiene un pequeño efecto de borde; ventana ~5
    assert 4.5 < hb < 5.5


def test_hypoxic_burden_all_above_threshold():
    spo2 = pd.Series(np.full(3600, 95.0))
    ts = pd.Series(pd.date_range("2024-01-01", periods=3600, freq="s"))
    hb = compute_hypoxic_burden(spo2, ts, threshold_pct=90.0)
    assert hb == 0.0


# ---------------------------------------------------------------------------
# HR family
# ---------------------------------------------------------------------------
def test_hr_stats_known():
    hr = pd.Series([60.0, 65.0, 70.0, 75.0, 80.0])
    s = compute_hr_stats(hr)
    assert np.isclose(s["mean_hr"], 70.0)
    assert s["min_hr"] == 60.0
    assert s["max_hr"] == 80.0


def test_sustained_extremes_below_threshold():
    hr = np.full(3600, 75.0)
    hr[100:115] = 40.0  # 15 s bradicardia
    hr[200:205] = 40.0  # 5 s (muy corto)
    n = count_sustained_extremes(
        pd.Series(hr), threshold=50, comparator="<",
        min_duration_s=10, sampling_hz=1.0,
    )
    assert n == 1


def test_sustained_extremes_short_episode_excluded():
    hr = np.full(100, 75.0)
    hr[10:15] = 40.0  # 5 s
    n = count_sustained_extremes(
        pd.Series(hr), threshold=50, comparator="<",
        min_duration_s=10,
    )
    assert n == 0


def test_sustained_extremes_invalid_comparator():
    with pytest.raises(ValueError):
        count_sustained_extremes(
            pd.Series([1.0]), threshold=0, comparator="==",
        )


def test_delta_hr_stats_known():
    events = pd.DataFrame({"delta_hr_bpm": [5.0, 10.0, 15.0, 20.0]})
    s = compute_delta_hr_stats(events)
    assert np.isclose(s["mean_delta_hr_per_edo"], 12.5)
    assert np.isclose(s["p90_delta_hr_per_edo"], 18.5)  # q90 lineal


def test_delta_hr_stats_empty():
    empty = pd.DataFrame({"delta_hr_bpm": []})
    s = compute_delta_hr_stats(empty)
    assert np.isnan(s["mean_delta_hr_per_edo"])


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------
def test_mov_stats_index_positive():
    n = 3600
    rng = np.random.default_rng(0)
    mov = rng.normal(0.05, 0.005, n)
    mov[100:120] = 1.0  # 20 s de pico
    mov[500:510] = 1.0  # 10 s
    ts = pd.Series(pd.date_range("2024-01-01", periods=n, freq="s"))
    s = compute_mov_stats(pd.Series(mov), ts, sampling_hz=1.0)
    assert s["movement_index_per_h"] > 0


# ---------------------------------------------------------------------------
# Sleep
# ---------------------------------------------------------------------------
def test_sleep_stats_with_waso():
    # 1800 wake + 10800 stage 1 + 1800 wake + 14400 stage 2 = 28800
    stage = np.concatenate([
        np.zeros(1800, dtype=np.int8),
        np.ones(10800, dtype=np.int8),
        np.zeros(1800, dtype=np.int8),
        np.full(14400, 2, dtype=np.int8),
    ])
    ts = pd.Series(pd.date_range("2024-01-01", periods=28800, freq="s"))
    s = compute_sleep_stats(pd.Series(stage), ts, wake_values={0})
    assert s["tst_s"] == 25200.0
    assert s["sleep_latency_s"] == 1800.0
    assert s["waso_s"] == 1800.0
    assert s["n_stage_shifts"] == 3
    # Efficiency con dur = 28799 (N-1 samples a 1Hz)
    assert abs(s["sleep_efficiency"] - 25200.0 / 28799.0) < 1e-6


def test_sleep_stats_fallback_no_staging():
    ts = pd.Series(pd.date_range("2024-01-01", periods=3600, freq="s"))
    empty_stage = pd.Series([], dtype=float)
    s = compute_sleep_stats(empty_stage, ts)
    assert s["tst_s"] == 3599.0  # dur_s = N-1
    assert s["sleep_efficiency"] == 1.0
    assert s["waso_s"] == 0.0


def test_sleep_stats_wake_only():
    ts = pd.Series(pd.date_range("2024-01-01", periods=1000, freq="s"))
    stage = pd.Series(np.zeros(1000, dtype=np.int8))
    s = compute_sleep_stats(stage, ts, wake_values={0})
    assert s["tst_s"] == 0.0
    assert s["sleep_latency_s"] == 999.0  # dur_s = N-1
    assert s["waso_s"] == 0.0
    assert s["sleep_efficiency"] == 0.0


# ---------------------------------------------------------------------------
# Event-based indices
# ---------------------------------------------------------------------------
def test_ird_night_known():
    events = pd.DataFrame({
        "ird_event": [0.5, 1.0, 2.0],
        "duration_s": [20.0, 30.0, 40.0],
    })
    # Σ = 0.5*20 + 1.0*30 + 2.0*40 = 120
    # / tst = 25200 → 0.004762
    assert np.isclose(compute_ird_night(events, tst_s=25200.0), 120.0 / 25200.0)


def test_ird_night_zero_tst():
    events = pd.DataFrame({"ird_event": [1.0], "duration_s": [10.0]})
    assert compute_ird_night(events, tst_s=0.0) == 0.0


def test_ird_event_stats_known():
    events = pd.DataFrame({"ird_event": [1.0, 2.0, 3.0, 4.0]})
    s = compute_ird_event_stats(events)
    assert np.isclose(s["mean_ird_event"], 2.5)


def test_ird_event_stats_empty():
    s = compute_ird_event_stats(pd.DataFrame({"ird_event": []}))
    assert np.isnan(s["mean_ird_event"])


def test_odi_ahi_family_with_in_sleep():
    events = pd.DataFrame({
        "meets_3pct": [True, True, True],
        "meets_4pct": [False, True, True],
        "in_sleep":   [True, True, False],
        "duration_s": [10.0, 20.0, 30.0],
    })
    tst_s = 25200.0
    f = compute_odi_ahi_family(events, tst_s=tst_s, thresholds=(3, 4))
    # ODI_3: 3 eventos; AHI_3: 2 (in_sleep)
    assert np.isclose(f["odi_3"], 3 * 3600 / tst_s)
    assert np.isclose(f["ahi_3"], 2 * 3600 / tst_s)
    assert f["n_edos_3pct"] == 3
    assert np.isclose(f["odi_4"], 2 * 3600 / tst_s)
    assert np.isclose(f["ahi_4"], 1 * 3600 / tst_s)


def test_odi_ahi_family_no_events():
    empty = pd.DataFrame(columns=["meets_3pct", "in_sleep", "duration_s"])
    f = compute_odi_ahi_family(empty, tst_s=25200.0, thresholds=(3,))
    assert f["odi_3"] == 0.0
    assert f["ahi_3"] == 0.0
    assert f["n_edos_3pct"] == 0


def test_edo_morphology_stats_known():
    events = pd.DataFrame({
        "drop_pct": [3.0, 5.0, 7.0],
        "duration_s": [15.0, 25.0, 40.0],
    })
    s = compute_edo_morphology_stats(events)
    assert s["n_edos_total"] == 3
    assert np.isclose(s["mean_drop_pct"], 5.0)
    assert s["max_duration_s"] == 40.0


def test_edo_morphology_stats_empty():
    s = compute_edo_morphology_stats(pd.DataFrame())
    assert s["n_edos_total"] == 0
    assert np.isnan(s["mean_drop_pct"])


# ---------------------------------------------------------------------------
# Validación quinteto vs sidecar classical
# ---------------------------------------------------------------------------
def test_diff_below_flag_threshold():
    # diff_rel = 0.2 → |0.2| > 0.2 es False (strict)
    q = compute_diff_vs_device(12.0, 10.0, flag_threshold=0.20)
    assert np.isclose(q["diff_rel"], 0.2)
    assert q["diff_flag"] is False


def test_diff_above_flag_threshold():
    # 30% de diff → flag True
    q = compute_diff_vs_device(13.0, 10.0, flag_threshold=0.20)
    assert q["diff_flag"] is True


def test_diff_device_zero():
    q = compute_diff_vs_device(5.0, 0.0, flag_threshold=0.20)
    assert q["diff_rel"] == float("inf")
    # inf no es finito → flag False (no comparable)
    assert q["diff_flag"] is False


def test_diff_device_nan():
    q = compute_diff_vs_device(5.0, float("nan"))
    assert np.isnan(q["device"])
    assert np.isnan(q["diff_abs"])
    assert np.isnan(q["diff_rel"])
    assert q["diff_flag"] is False
