"""
Tests para scripts/build_nights_gold.py (Etapa 5 paso 5).

Cobertura:
- Cardinalidad: 1 fila × noche, 560 filas en corpus actual.
- Schema mínimo (skeleton GOLD_NIGHTS_SCHEMA) + cols esperadas presentes.
- Distribución de morfotipos: 4 cols, suma == 1.0 por noche (cuando hay EDOs).
- Distribución de PAC states: 20 cols (6+8+6), suma == 1.0 por escala por noche.
- Transiciones y entropía: 6 cols, n_transitions ∈ ints≥0, entropy ∈ floats≥0.
- Cross-night cohort-relative: ahi_3_pct_corpus uniforme en [0,1] sobre quality.
- Cross-night patient-relative: media ≈ 0 sobre quality (por construcción).
- Flags de cohorte consistentes con pac.cohorts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_nights_gold", REPO_ROOT / "scripts" / "build_nights_gold.py"
)
build_nights_gold_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_nights_gold_module)

from pac.cohorts import (
    get_cohort_high_tst,
    get_cohort_quality,
    get_cohort_strict,
)
from pac.schemas import GOLD_NIGHTS_SCHEMA, validate_nights_gold


@pytest.fixture(scope="module")
def df_gold():
    # Requiere events/, gold/events.parquet, gold/states.parquet
    if not (REPO_ROOT / "gold" / "events.parquet").exists():
        pytest.skip("Falta gold/events.parquet (correr build_events_gold.py).")
    if not (REPO_ROOT / "gold" / "states.parquet").exists():
        pytest.skip("Falta gold/states.parquet (correr build_states_gold.py).")
    if not list((REPO_ROOT / "events").glob("NR_*_indices.parquet")):
        pytest.skip("Falta events/NR_*_indices.parquet (CI fresco).")
    return build_nights_gold_module.build_nights_gold(verbose=False)


# --------------------------------------------------------------------- #
# Cardinalidad y schema base
# --------------------------------------------------------------------- #


class TestCardinality:
    def test_one_row_per_night(self, df_gold):
        n_dup = df_gold.duplicated(subset=["night_record_id"]).sum()
        assert n_dup == 0

    def test_n_nights_in_range(self, df_gold):
        assert 550 <= len(df_gold) <= 600


class TestSkeletonContract:
    def test_validates_against_skeleton(self, df_gold):
        r = validate_nights_gold(df_gold, source="<test>", strict=True)
        assert r.ok

    def test_has_minimum_skeleton_cols(self, df_gold):
        for col in GOLD_NIGHTS_SCHEMA.keys():
            assert col in df_gold.columns, f"falta {col}"


# --------------------------------------------------------------------- #
# Distribución de morfotipos
# --------------------------------------------------------------------- #


class TestMorphotypeDistribution:
    def test_four_morpho_cols_present(self, df_gold):
        for m in ["α", "β", "γ", "δ"]:
            assert f"frac_morpho_{m}" in df_gold.columns

    def test_sums_to_one_when_has_edos(self, df_gold):
        cols = [f"frac_morpho_{m}" for m in ["α", "β", "γ", "δ"]]
        sums = df_gold[cols].sum(axis=1)
        # Permitir noches sin EDOs (sum=0); pero las que tienen, deben sumar 1.0
        with_edos = sums > 0
        assert np.allclose(sums.loc[with_edos], 1.0, atol=1e-9)

    def test_no_negative_fractions(self, df_gold):
        cols = [f"frac_morpho_{m}" for m in ["α", "β", "γ", "δ"]]
        assert (df_gold[cols] >= 0).all().all()


# --------------------------------------------------------------------- #
# Distribución de PAC states
# --------------------------------------------------------------------- #


class TestStateDistribution:
    def test_twenty_state_cols(self, df_gold):
        # s: S0-S5 (6), m: M0-M7 (8), l: L0-L5 (6) = 20
        for sc, n in [("s", 6), ("m", 8), ("l", 6)]:
            cols = [f"frac_state_{sc}_{sc.upper()}{i}" for i in range(n)]
            for c in cols:
                assert c in df_gold.columns, f"falta {c}"

    def test_sums_to_one_per_scale(self, df_gold):
        for sc, n in [("s", 6), ("m", 8), ("l", 6)]:
            cols = [f"frac_state_{sc}_{sc.upper()}{i}" for i in range(n)]
            sums = df_gold[cols].sum(axis=1)
            with_data = sums > 0
            assert np.allclose(sums.loc[with_data], 1.0, atol=1e-9), (
                f"escala {sc} no suma 1.0"
            )

    def test_no_negative_fractions(self, df_gold):
        for sc, n in [("s", 6), ("m", 8), ("l", 6)]:
            cols = [f"frac_state_{sc}_{sc.upper()}{i}" for i in range(n)]
            assert (df_gold[cols] >= 0).all().all()


# --------------------------------------------------------------------- #
# Transiciones y entropía
# --------------------------------------------------------------------- #


class TestTransitionsEntropy:
    def test_six_cols(self, df_gold):
        for sc in ["s", "m", "l"]:
            assert f"n_transitions_state_{sc}" in df_gold.columns
            assert f"entropy_state_{sc}" in df_gold.columns

    def test_n_transitions_non_negative_int(self, df_gold):
        for sc in ["s", "m", "l"]:
            col = f"n_transitions_state_{sc}"
            assert (df_gold[col] >= 0).all()

    def test_entropy_non_negative(self, df_gold):
        for sc in ["s", "m", "l"]:
            assert (df_gold[f"entropy_state_{sc}"] >= 0).all()

    def test_entropy_upper_bound(self, df_gold):
        """Entropía Shannon en bits ≤ log2(K) para cada escala."""
        for sc, k in [("s", 6), ("m", 8), ("l", 6)]:
            upper = np.log2(k)
            assert (df_gold[f"entropy_state_{sc}"] <= upper + 1e-9).all()

    def test_n_transitions_relation_s_gt_m_gt_l(self, df_gold):
        """A nivel mediana: s tiene más transiciones que m que l (más ventanas)."""
        med_s = df_gold["n_transitions_state_s"].median()
        med_m = df_gold["n_transitions_state_m"].median()
        med_l = df_gold["n_transitions_state_l"].median()
        assert med_s > med_m > med_l


# --------------------------------------------------------------------- #
# Cross-night
# --------------------------------------------------------------------- #


class TestCrossNightCohort:
    def test_pct_corpus_cols_present(self, df_gold):
        for m in ["ahi_3", "t90_frac", "odi_3"]:
            assert f"{m}_pct_corpus" in df_gold.columns

    def test_pct_corpus_in_unit_interval(self, df_gold):
        col = "ahi_3_pct_corpus"
        assert (df_gold[col].dropna() >= 0).all()
        assert (df_gold[col].dropna() <= 1).all()

    def test_pct_corpus_uniform_on_quality(self, df_gold):
        """Por construcción, percentile-rank sobre quality es ~uniforme [0,1]."""
        qual = df_gold.loc[df_gold["in_quality"]]
        col = "ahi_3_pct_corpus"
        assert abs(qual[col].mean() - 0.5) < 0.05  # mean ≈ 0.5
        assert abs(qual[col].median() - 0.5) < 0.05


class TestCrossNightPatient:
    def test_delta_cols_present(self, df_gold):
        for m in ["ahi_3", "t90_frac", "odi_3"]:
            assert f"delta_{m}_vs_baseline_patient" in df_gold.columns

    def test_delta_centers_at_zero_on_quality(self, df_gold):
        """Por construcción, delta vs baseline-patient sobre quality ≈ 0."""
        qual = df_gold.loc[df_gold["in_quality"]]
        col = "delta_ahi_3_vs_baseline_patient"
        # Tolerancia laxa: leave-one-out introduce ruido; ≤0.5 es OK
        assert abs(qual[col].dropna().mean()) < 0.5


# --------------------------------------------------------------------- #
# Flags de cohorte
# --------------------------------------------------------------------- #


class TestCohortFlags:
    def test_in_quality_matches_module(self, df_gold):
        in_df = set(df_gold.loc[df_gold["in_quality"], "night_record_id"])
        assert in_df == get_cohort_quality()

    def test_in_strict_matches_module(self, df_gold):
        in_df = set(df_gold.loc[df_gold["in_strict"], "night_record_id"])
        assert in_df == get_cohort_strict()

    def test_in_high_tst_matches_module(self, df_gold):
        in_df = set(df_gold.loc[df_gold["in_high_tst"], "night_record_id"])
        assert in_df == get_cohort_high_tst(min_tst_h=4.0)

    def test_strict_subset_quality(self, df_gold):
        bad = df_gold.loc[df_gold["in_strict"] & ~df_gold["in_quality"]]
        assert len(bad) == 0


# --------------------------------------------------------------------- #
# Trazabilidad
# --------------------------------------------------------------------- #


class TestTraceability:
    def test_model_version_not_null(self, df_gold):
        assert df_gold["model_version"].notna().all()

    def test_user_id_not_null(self, df_gold):
        # user_id viene de _indices.parquet (no del lookup)
        assert df_gold["user_id"].notna().all()
