"""
PAC_v2 — Etapa 2 Silver QC: tests unitarios de `pac.qc`.

Cubre:
  apply_range_qc
    1. rango simple: spo2 < 55 → invalid
    2. rango con max: hr fuera de [30, 200]
    3. valores en bordes (igual a vmin, vmax) NO son inválidos
    4. NaN pre-existente → invalid + clean=NaN
    5. no mutación de la columna original

  compute_gap_metrics
    6. DataFrame vacío
    7. 1 sola fila
    8. coverage=1.0 cuando no hay gaps
    9. n_gaps correcto con 2 gaps de distinta duración
   10. max_contiguous_gap_s = mayor gap, no suma

  compute_duration_flags
   11. aborted=True, short=True  (d < aborted_s)
   12. aborted=False, short=True (aborted_s ≤ d < min_s)
   13. aborted=False, short=False (d ≥ min_s)
   14. borde exacto: d == aborted_s → aborted=False
   15. validación: aborted_s > min_s → ValueError

  compute_coverage_flags
   16. coverage/max_gap bajo umbral → flags False
   17. coverage/max_gap sobre umbral → flags True

  Integración mínima
   18. qc pipeline completo sobre DataFrame sintético 1 Hz con gap y outliers
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.qc import (  # noqa: E402
    apply_range_qc,
    compute_coverage_flags,
    compute_duration_flags,
    compute_gap_metrics,
)


# ---------------------------------------------------------------------------
# apply_range_qc
# ---------------------------------------------------------------------------
def test_range_qc_simple_vmin():
    df = pd.DataFrame({"spo2": [0, 50, 54, 55, 80, 99, 100]})
    out = apply_range_qc(df, "spo2", vmin=55)
    assert out["spo2_invalid"].tolist() == [True, True, True, False, False, False, False]
    # clean: NaN donde invalid, valor original donde no
    assert np.isnan(out.loc[0, "spo2_clean"])
    assert out.loc[3, "spo2_clean"] == 55.0
    assert out.loc[6, "spo2_clean"] == 100.0


def test_range_qc_vmin_and_vmax():
    df = pd.DataFrame({"hr": [0, 29, 30, 100, 200, 201, 300]})
    out = apply_range_qc(df, "hr", vmin=30, vmax=200)
    assert out["hr_invalid"].tolist() == [True, True, False, False, False, True, True]


def test_range_qc_boundaries_inclusive():
    # vmin y vmax son inclusivos (>= vmin, <= vmax).
    df = pd.DataFrame({"hr": [30, 200]})
    out = apply_range_qc(df, "hr", vmin=30, vmax=200)
    assert out["hr_invalid"].tolist() == [False, False]


def test_range_qc_preexisting_nan():
    df = pd.DataFrame({"spo2": [np.nan, 60, 80]})
    out = apply_range_qc(df, "spo2", vmin=55)
    assert out["spo2_invalid"].tolist() == [True, False, False]
    assert np.isnan(out.loc[0, "spo2_clean"])


def test_range_qc_does_not_mutate_original():
    df = pd.DataFrame({"spo2": [0, 60, 80]})
    original = df["spo2"].copy()
    out = apply_range_qc(df, "spo2", vmin=55)
    # Original intacta
    assert (df["spo2"] == original).all()
    # `spo2` en out también intacta (no vaciada por el clean)
    assert out["spo2"].tolist() == [0, 60, 80]


def test_range_qc_raises_on_missing_column():
    df = pd.DataFrame({"a": [1, 2]})
    try:
        apply_range_qc(df, "spo2", vmin=55)
        raise AssertionError("debería haber raiseado KeyError")
    except KeyError:
        pass


def test_range_qc_requires_at_least_one_bound():
    df = pd.DataFrame({"x": [1, 2, 3]})
    try:
        apply_range_qc(df, "x")
        raise AssertionError("debería haber raiseado ValueError")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# compute_gap_metrics
# ---------------------------------------------------------------------------
def test_gap_metrics_empty_df():
    df = pd.DataFrame({"timestamp": pd.to_datetime([])})
    r = compute_gap_metrics(df)
    assert r["n_samples"] == 0
    assert r["coverage"] == 0.0
    assert r["n_gaps"] == 0
    assert r["max_contiguous_gap_s"] == 0


def test_gap_metrics_single_row():
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2026-01-01 00:00:00"])})
    r = compute_gap_metrics(df)
    assert r["n_samples"] == 1
    assert r["duration_s"] == 0.0
    assert r["coverage"] == 1.0
    assert r["n_gaps"] == 0


def test_gap_metrics_contiguous_no_gaps():
    # 10 muestras a 1 Hz, sin gaps
    ts = pd.date_range("2026-01-01", periods=10, freq="1s")
    df = pd.DataFrame({"timestamp": ts})
    r = compute_gap_metrics(df)
    assert r["n_samples"] == 10
    assert r["duration_s"] == 9.0
    assert r["n_expected"] == 10
    assert r["coverage"] == 1.0
    assert r["n_gaps"] == 0
    assert r["max_contiguous_gap_s"] == 0


def test_gap_metrics_multiple_gaps():
    # Muestras con 2 gaps:
    #   00:00:00 .. 00:00:04 (5 contiguas)  → no gap
    #   00:00:14                              → gap de 10s
    #   00:00:15 .. 00:00:16 (2 contiguas)   → no gap
    #   00:01:16                              → gap de 60s
    #   00:01:17                              → no gap
    ts = pd.to_datetime([
        "2026-01-01 00:00:00",
        "2026-01-01 00:00:01",
        "2026-01-01 00:00:02",
        "2026-01-01 00:00:03",
        "2026-01-01 00:00:04",
        "2026-01-01 00:00:14",  # gap de 10s (faltan 9 muestras)
        "2026-01-01 00:00:15",
        "2026-01-01 00:00:16",
        "2026-01-01 00:01:16",  # gap de 60s (faltan 59 muestras)
        "2026-01-01 00:01:17",
    ])
    df = pd.DataFrame({"timestamp": ts})
    r = compute_gap_metrics(df)
    assert r["n_samples"] == 10
    assert r["duration_s"] == 77.0           # 00:00:00 → 00:01:17
    assert r["n_expected"] == 78             # 77 + 1
    assert r["n_gaps"] == 2
    # max_contiguous_gap_s = el más grande = 60 - 1 = 59
    assert r["max_contiguous_gap_s"] == 59


def test_gap_metrics_max_is_max_not_sum():
    # 2 gaps, el primero de 5s y el segundo de 3s → max=4, no 6
    ts = pd.to_datetime([
        "2026-01-01 00:00:00",
        "2026-01-01 00:00:05",  # gap de 5s → faltan 4
        "2026-01-01 00:00:06",
        "2026-01-01 00:00:09",  # gap de 3s → faltan 2
        "2026-01-01 00:00:10",
    ])
    df = pd.DataFrame({"timestamp": ts})
    r = compute_gap_metrics(df)
    assert r["n_gaps"] == 2
    assert r["max_contiguous_gap_s"] == 4


# ---------------------------------------------------------------------------
# compute_duration_flags
# ---------------------------------------------------------------------------
def test_duration_flags_aborted():
    # d < aborted_s → ambos True
    r = compute_duration_flags(duration_s=1800, aborted_s=3600, min_s=10800)  # 30 min
    assert r == {"qc_duration_aborted": True, "qc_duration_short": True}


def test_duration_flags_short_not_aborted():
    # aborted_s ≤ d < min_s → aborted False, short True
    r = compute_duration_flags(duration_s=7200, aborted_s=3600, min_s=10800)  # 2 h
    assert r == {"qc_duration_aborted": False, "qc_duration_short": True}


def test_duration_flags_full_night():
    # d ≥ min_s → ambos False
    r = compute_duration_flags(duration_s=25200, aborted_s=3600, min_s=10800)  # 7 h
    assert r == {"qc_duration_aborted": False, "qc_duration_short": False}


def test_duration_flags_exact_boundary_aborted():
    # d == aborted_s → aborted=False (estricto <)
    r = compute_duration_flags(duration_s=3600, aborted_s=3600, min_s=10800)
    assert r["qc_duration_aborted"] is False
    assert r["qc_duration_short"] is True


def test_duration_flags_invalid_config():
    try:
        compute_duration_flags(duration_s=5000, aborted_s=10800, min_s=3600)
        raise AssertionError("debería haber raiseado ValueError")
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# compute_coverage_flags
# ---------------------------------------------------------------------------
def test_coverage_flags_fail():
    gm = {"coverage": 0.85, "max_contiguous_gap_s": 2000}
    r = compute_coverage_flags(gm, coverage_min=0.90, max_gap_s=1800)
    assert r == {"qc_coverage_ok": False, "qc_max_gap_ok": False}


def test_coverage_flags_pass():
    gm = {"coverage": 0.98, "max_contiguous_gap_s": 300}
    r = compute_coverage_flags(gm, coverage_min=0.90, max_gap_s=1800)
    assert r == {"qc_coverage_ok": True, "qc_max_gap_ok": True}


# ---------------------------------------------------------------------------
# Integración mínima — pipeline sobre DataFrame sintético realista
# ---------------------------------------------------------------------------
def test_integration_synthetic_night():
    """
    Noche sintética 1 Hz, 100 s de duración, con:
      - spo2 entre 90-98 salvo muestras 10, 20 con 0 (sensor desconectado)
      - hr entre 60-90 salvo muestra 5 con 250 (outlier)
      - 1 gap: salto de t=49 a t=55 → diff=6s → faltan 5 muestras (t=50..54)
    """
    # timestamps con gap
    ts_list = [pd.Timestamp("2026-01-01 00:00:00") + pd.Timedelta(seconds=i)
               for i in range(50)]   # t=0..49
    ts_list += [pd.Timestamp("2026-01-01 00:00:55") + pd.Timedelta(seconds=i)
                for i in range(46)]  # t=55..100
    assert len(ts_list) == 96

    spo2 = [95] * 96
    spo2[10] = 0
    spo2[20] = 0

    hr = [70] * 96
    hr[5] = 250

    df = pd.DataFrame({"timestamp": ts_list, "spo2": spo2, "hr": hr})

    # Range QC
    df = apply_range_qc(df, "spo2", vmin=55)
    df = apply_range_qc(df, "hr", vmin=30, vmax=200)
    assert df["spo2_invalid"].sum() == 2
    assert df["hr_invalid"].sum() == 1

    # Gaps
    gm = compute_gap_metrics(df, ts_col="timestamp", sampling_hz=1.0)
    assert gm["n_samples"] == 96
    assert gm["duration_s"] == 100.0
    assert gm["n_expected"] == 101
    assert abs(gm["coverage"] - 96.0 / 101.0) < 1e-9
    assert gm["n_gaps"] == 1
    assert gm["max_contiguous_gap_s"] == 5  # salto de 6s → 5 muestras faltantes

    # Duración flags
    dur = compute_duration_flags(
        duration_s=gm["duration_s"], aborted_s=3600, min_s=10800
    )
    assert dur["qc_duration_aborted"] is True   # 100 s < 1 h
    assert dur["qc_duration_short"] is True

    # Coverage flags
    cov = compute_coverage_flags(gm, coverage_min=0.90, max_gap_s=1800)
    assert cov["qc_coverage_ok"] is True   # 96/101 ≈ 0.95
    assert cov["qc_max_gap_ok"] is True    # 4 ≤ 1800


# ---------------------------------------------------------------------------
# Runner manual: python -m tests.test_qc
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    fail = 0
    for t in tests:
        try:
            t()
            print(f"  OK   {t.__name__}")
        except AssertionError as e:
            fail += 1
            print(f"  FAIL {t.__name__}: {e or '(assertion)'}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  FAIL {t.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    print()
    print(f"[tests/test_qc] {total - fail}/{total} OK")
    sys.exit(0 if fail == 0 else 1)
