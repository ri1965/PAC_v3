"""
PAC_v2 — Etapa 4: tests unitarios de pac.windows.

Cubre las 5 funciones públicas:
  - partition_windows        (5 tests)
  - aggregate_signal_stats   (4 tests)
  - count_morphotype_densities (4 tests)
  - compute_sleep_composition (4 tests)
  - build_windows_for_night  (4 tests)

Total: 21 tests. Sólo fixtures sintéticos, sin I/O real.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pac.windows import (
    WINDOW_META_COLS,
    aggregate_signal_stats,
    build_windows_for_night,
    compute_sleep_composition,
    count_morphotype_densities,
    partition_windows,
)
from pac.config import (
    PAC_SLEEP_CATEGORIES,
    PAC_WINDOW_DURATIONS_S,
    PAC_WINDOW_FEATURES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_silver(n_samples: int, seed: int = 0, nan_frac: float = 0.0) -> pd.DataFrame:
    """
    DataFrame silver sintético a 1 Hz. n_samples segundos desde 2026-01-01 00:00:00.

    Opcional: nan_frac (0..1) de los samples tienen spo2_clean=NaN.
    """
    rng = np.random.default_rng(seed)
    ts0 = pd.Timestamp("2026-01-01 00:00:00")
    timestamps = pd.date_range(ts0, periods=n_samples, freq="1s")

    spo2 = rng.integers(90, 99, size=n_samples).astype(np.int64)
    spo2_invalid = np.zeros(n_samples, dtype=bool)
    spo2_clean = spo2.astype(float)
    if nan_frac > 0:
        n_nan = int(n_samples * nan_frac)
        idx_nan = rng.choice(n_samples, size=n_nan, replace=False)
        spo2_clean[idx_nan] = np.nan
        spo2_invalid[idx_nan] = True

    hr = rng.integers(55, 75, size=n_samples).astype(np.int64)
    hr_invalid = np.zeros(n_samples, dtype=bool)
    hr_clean = hr.astype(float)

    mov = rng.integers(0, 20, size=n_samples).astype(np.int64)

    # sleep_stage: mezcla fija para testeo (primer tercio wake=0, segundo
    # tercio stage_1=1, último tercio stage_3=3).
    ss = np.zeros(n_samples, dtype=np.int64)
    t1 = n_samples // 3
    t2 = 2 * n_samples // 3
    ss[t1:t2] = 1
    ss[t2:] = 3

    return pd.DataFrame({
        "timestamp": timestamps,
        "spo2": spo2,
        "spo2_invalid": spo2_invalid,
        "spo2_clean": spo2_clean,
        "hr": hr,
        "hr_invalid": hr_invalid,
        "hr_clean": hr_clean,
        "mov": mov,
        "sleep_stage": pd.array(ss, dtype="Int64"),
    })


def _make_edos_at(ts_starts, morphotypes, ird_values=None) -> pd.DataFrame:
    """Fábrica de EDOs con ts_start, morphotype e ird_event custom."""
    n = len(ts_starts)
    if ird_values is None:
        ird_values = [0.5] * n
    return pd.DataFrame({
        "night_record_id": ["NR_test"] * n,
        "ts_start": pd.to_datetime(ts_starts),
        "ts_end": pd.to_datetime(ts_starts) + pd.Timedelta(seconds=20),
        "duration_s": [20.0] * n,
        "morphotype": morphotypes,
        "ird_event": ird_values,
    })


# ===========================================================================
# 1) partition_windows
# ===========================================================================
class TestPartitionWindows:
    def test_empty_df_returns_empty_frame_with_cols(self):
        silver = pd.DataFrame(columns=["timestamp", "spo2_clean"])
        out = partition_windows(silver, "s")
        assert len(out) == 0
        # Todas las meta columns están presentes
        for c in WINDOW_META_COLS:
            assert c in out.columns

    def test_exact_multiple_no_tail(self):
        """Noche = 3 ventanas medium completas → 3 ventanas, ningún is_tail."""
        duration = PAC_WINDOW_DURATIONS_S["m"]  # 300
        silver = _make_silver(3 * duration)
        out = partition_windows(silver, "m")
        assert len(out) == 3
        assert out.is_tail.sum() == 0
        assert all(out.n_samples_raw == duration)
        assert all(out.coverage == 1.0)
        # t_end - t_start == timedelta(duration) para cada ventana
        deltas = (out.t_end - out.t_start).dt.total_seconds().unique()
        assert list(deltas) == [float(duration)]

    def test_tail_kept_when_coverage_ok(self):
        """Tail con 60% de duration y 100% de datos válidos → se incluye."""
        duration = PAC_WINDOW_DURATIONS_S["m"]  # 300
        n = 2 * duration + int(0.6 * duration)  # 2 completas + tail de 180s
        silver = _make_silver(n)
        out = partition_windows(silver, "m", tail_coverage_min=0.5)
        assert len(out) == 3
        assert out.iloc[-1].is_tail
        # Coverage sobre duration nominal: 180/300 = 0.6
        assert abs(out.iloc[-1].coverage - 0.6) < 1e-9

    def test_tail_dropped_when_coverage_below_threshold(self):
        """Tail con 30% de duration → se descarta."""
        duration = PAC_WINDOW_DURATIONS_S["m"]
        n = 2 * duration + int(0.3 * duration)
        silver = _make_silver(n)
        out = partition_windows(silver, "m", tail_coverage_min=0.5)
        assert len(out) == 2
        assert out.is_tail.sum() == 0

    def test_invalid_scale_raises(self):
        silver = _make_silver(100)
        with pytest.raises(ValueError, match="Scale desconocida"):
            partition_windows(silver, "xl")

    def test_all_three_scales_count_ratio(self):
        """Noche de 3600s: debe dar 120 (s), 12 (m), 2 (l)."""
        silver = _make_silver(3600)  # 1 hora exacta
        n_s = len(partition_windows(silver, "s"))
        n_m = len(partition_windows(silver, "m"))
        n_l = len(partition_windows(silver, "l"))
        assert n_s == 120
        assert n_m == 12
        assert n_l == 2


# ===========================================================================
# 2) aggregate_signal_stats
# ===========================================================================
class TestAggregateSignalStats:
    def test_all_nan_returns_nan_for_each_stat(self):
        chunk = pd.DataFrame({"spo2_clean": [np.nan, np.nan, np.nan]})
        out = aggregate_signal_stats(chunk, "spo2_clean", ("mean", "std", "p10"), "spo2")
        assert set(out.keys()) == {"spo2_mean", "spo2_std", "spo2_p10"}
        for v in out.values():
            assert np.isnan(v)

    def test_partial_nan_nan_aware(self):
        """mean ignora NaN; [1,2,3,NaN] → mean=2."""
        chunk = pd.DataFrame({"x_clean": [1.0, 2.0, 3.0, np.nan]})
        out = aggregate_signal_stats(chunk, "x_clean", ("mean", "min", "max"), "x")
        assert out["x_mean"] == 2.0
        assert out["x_min"] == 1.0
        assert out["x_max"] == 3.0

    def test_percentiles(self):
        """p10 y p90 coherentes con numpy."""
        vals = np.arange(1, 101, dtype=float)  # 1..100
        chunk = pd.DataFrame({"x": vals})
        out = aggregate_signal_stats(chunk, "x", ("p10", "p90"), "x")
        assert abs(out["x_p10"] - np.percentile(vals, 10)) < 1e-9
        assert abs(out["x_p90"] - np.percentile(vals, 90)) < 1e-9

    def test_unsupported_stat_raises(self):
        chunk = pd.DataFrame({"x": [1.0, 2.0]})
        with pytest.raises(ValueError, match="Stat no soportado"):
            aggregate_signal_stats(chunk, "x", ("median",), "x")


# ===========================================================================
# 3) count_morphotype_densities
# ===========================================================================
class TestCountMorphotypeDensities:
    def test_empty_edos_returns_zeros(self):
        edos = pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])
        t0 = pd.Timestamp("2026-01-01 00:00:00")
        t1 = t0 + pd.Timedelta(seconds=300)
        out = count_morphotype_densities(edos, t0, t1)
        assert out["n_edos_total"] == 0
        for f in ["n_alpha", "n_beta", "n_gamma", "n_delta"]:
            assert out[f] == 0
        assert out["ird_mean_local"] == 0.0

    def test_edo_on_t_start_counts_edo_on_t_end_does_not(self):
        """Regla [t_start, t_end): inclusivo izq, exclusivo der (Q5=A)."""
        t0 = pd.Timestamp("2026-01-01 00:00:00")
        t1 = t0 + pd.Timedelta(seconds=300)
        edos = _make_edos_at(
            [t0, t1],                # uno en t_start, otro EN t_end exacto
            ["α", "β"],
            [0.5, 0.9],
        )
        out = count_morphotype_densities(edos, t0, t1)
        assert out["n_edos_total"] == 1
        assert out["n_alpha"] == 1
        assert out["n_beta"] == 0  # el β está en t_end → no cuenta
        assert out["ird_mean_local"] == 0.5

    def test_morpho_counts_all_letters(self):
        t0 = pd.Timestamp("2026-01-01 00:00:00")
        t1 = t0 + pd.Timedelta(seconds=300)
        inside = t0 + pd.Timedelta(seconds=100)
        edos = _make_edos_at(
            [inside] * 5,
            ["α", "α", "β", "γ", "δ"],
            [0.1, 0.3, 0.2, 0.8, 0.4],
        )
        out = count_morphotype_densities(edos, t0, t1)
        assert out["n_edos_total"] == 5
        assert out["n_alpha"] == 2
        assert out["n_beta"] == 1
        assert out["n_gamma"] == 1
        assert out["n_delta"] == 1
        # ird_mean sobre los 5
        assert abs(out["ird_mean_local"] - np.mean([0.1, 0.3, 0.2, 0.8, 0.4])) < 1e-9

    def test_none_morphotype_counted_in_total_not_in_letters(self):
        """Un EDO con morphotype=None se contabiliza en n_edos_total pero no
        en ninguna letra (consistente con morfotipos "no-asignados")."""
        t0 = pd.Timestamp("2026-01-01 00:00:00")
        t1 = t0 + pd.Timedelta(seconds=300)
        inside = t0 + pd.Timedelta(seconds=100)
        edos = _make_edos_at([inside, inside], [None, "α"], [0.3, 0.5])
        out = count_morphotype_densities(edos, t0, t1)
        assert out["n_edos_total"] == 2
        assert out["n_alpha"] == 1
        assert out["n_beta"] == 0
        # ird_mean sobre ambos (ambos tienen ird_event válido)
        assert abs(out["ird_mean_local"] - 0.4) < 1e-9


# ===========================================================================
# 4) compute_sleep_composition
# ===========================================================================
class TestComputeSleepComposition:
    def test_empty_series_returns_zeros(self):
        s = pd.Series([], dtype="Int64")
        out = compute_sleep_composition(s)
        for cat in PAC_SLEEP_CATEGORIES:
            assert out[f"frac_{cat}"] == 0.0

    def test_pure_wake(self):
        s = pd.Series([0, 0, 0, 0], dtype="Int64")
        out = compute_sleep_composition(s)
        assert out["frac_wake"] == 1.0
        assert out["frac_light_sleep"] == 0.0
        assert out["frac_deep_sleep"] == 0.0

    def test_mapping_collapse_1_and_2_to_light(self):
        """raw 1 y raw 2 → ambos light_sleep, raw 3 → deep_sleep."""
        s = pd.Series([1, 1, 2, 3], dtype="Int64")
        out = compute_sleep_composition(s)
        assert out["frac_wake"] == 0.0
        assert out["frac_light_sleep"] == 0.75   # 3/4
        assert out["frac_deep_sleep"] == 0.25    # 1/4

    def test_invalid_stage_counts_as_unknown_not_in_fractions(self):
        """Un valor 99 no está en COLLAPSE_MAP → no cuenta para ninguna frac;
        el denominador sigue siendo len(series), así sum(fracs) < 1."""
        s = pd.Series([0, 99, 1, 3], dtype="Int64")
        out = compute_sleep_composition(s)
        total = sum(out.values())
        assert total == pytest.approx(0.75)  # 3/4 mapeados, 1/4 unknown
        assert out["frac_wake"] == 0.25
        assert out["frac_light_sleep"] == 0.25
        assert out["frac_deep_sleep"] == 0.25


# ===========================================================================
# 5) build_windows_for_night (orquestadora)
# ===========================================================================
class TestBuildWindowsForNight:
    def test_output_schema_has_all_features(self):
        """El DataFrame devuelto tiene 7 cols metadata + 24 features = 31."""
        silver = _make_silver(900)  # 3 ventanas medium
        edos = pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])
        out = build_windows_for_night(silver, edos, "m")

        assert len(out) == 3
        expected = list(WINDOW_META_COLS) + list(PAC_WINDOW_FEATURES)
        assert list(out.columns) == expected
        assert len(out.columns) == 7 + 24

    def test_empty_silver_returns_empty_frame_with_schema(self):
        silver = pd.DataFrame(columns=[
            "timestamp", "spo2_clean", "hr_clean", "mov", "sleep_stage",
        ])
        edos = pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])
        out = build_windows_for_night(silver, edos, "s")
        assert len(out) == 0
        # Mantiene el schema canónico
        for c in list(WINDOW_META_COLS) + list(PAC_WINDOW_FEATURES):
            assert c in out.columns

    def test_tail_is_marked_correctly(self):
        """Tail de 180s en escala medium → is_tail=True, coverage=0.6."""
        silver = _make_silver(780)  # 2 completas (600s) + tail 180s
        edos = pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])
        out = build_windows_for_night(silver, edos, "m")
        assert len(out) == 3
        assert out.iloc[-1].is_tail
        assert not out.iloc[0].is_tail
        assert not out.iloc[1].is_tail
        assert abs(out.iloc[-1].coverage - 0.6) < 1e-9

    def test_edos_no_double_counting_across_windows(self):
        """Sum(n_edos_total) sobre todas las ventanas = #EDOs dentro del tiempo cubierto."""
        silver = _make_silver(900)  # 3 ventanas medium (0..300, 300..600, 600..900)
        ts_all = pd.Timestamp("2026-01-01 00:00:00")
        # 5 EDOs en total: 2 en w0, 2 en w1, 1 en w2
        edos = _make_edos_at(
            [
                ts_all + pd.Timedelta(seconds=10),   # w0
                ts_all + pd.Timedelta(seconds=200),  # w0
                ts_all + pd.Timedelta(seconds=300),  # w1 (borde izq, cuenta)
                ts_all + pd.Timedelta(seconds=500),  # w1
                ts_all + pd.Timedelta(seconds=800),  # w2
            ],
            ["α", "β", "γ", "δ", "α"],
        )
        out = build_windows_for_night(silver, edos, "m")
        assert int(out.n_edos_total.sum()) == 5
        # w0: 2, w1: 2, w2: 1
        assert list(out.n_edos_total) == [2, 2, 1]
