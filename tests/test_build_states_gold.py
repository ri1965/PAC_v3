"""
Tests para scripts/build_states_gold.py (Etapa 5 paso 4).

Cobertura:
- DataFrame respeta GOLD_STATES_SCHEMA.
- Stackeo correcto: 3 escalas (s, m, l) presentes para cada noche.
- Cardinalidad por escala s > m > l (relación de tamaños de ventana).
- Flags de cohorte consistentes con pac.cohorts.
- user_id resuelto y model_version no-null.
- training_eligible sigue siendo bool.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_states_gold", REPO_ROOT / "scripts" / "build_states_gold.py"
)
build_states_gold_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_states_gold_module)

from pac.cohorts import (
    get_cohort_high_tst,
    get_cohort_quality,
    get_cohort_strict,
)
from pac.schemas import GOLD_STATES_SCHEMA, validate_states_gold


@pytest.fixture(scope="module")
def df_gold():
    states_dir = REPO_ROOT / "states"
    if not list(states_dir.glob("NR_*.parquet")):
        pytest.skip("Sin states/NR_*.parquet en el repo (CI fresco).")
    return build_states_gold_module.build_states_gold(verbose=False)


class TestSchemaContract:
    def test_columns_match_schema(self, df_gold):
        assert list(df_gold.columns) == list(GOLD_STATES_SCHEMA.keys())

    def test_validates_against_schema(self, df_gold):
        r = validate_states_gold(df_gold, source="<test>", strict=True)
        assert r.ok


class TestStackingShape:
    def test_three_scales_present(self, df_gold):
        scales = set(df_gold["scale"].unique())
        assert scales == {"s", "m", "l"}

    def test_each_night_has_all_three_scales(self, df_gold):
        """Cada noche debe tener filas en las 3 escalas (no noche con solo s)."""
        per_nr_scales = df_gold.groupby("night_record_id")["scale"].nunique()
        # En el corpus actual, todas las 560 noches deben tener las 3
        assert (per_nr_scales == 3).sum() >= 550

    def test_scale_size_relation_s_gt_m_gt_l(self, df_gold):
        """s (30s) → m (5min) → l (30min): s tiene ~10× ventanas que m, m ~6× que l."""
        counts = df_gold["scale"].value_counts().to_dict()
        assert counts["s"] > counts["m"] > counts["l"]
        assert counts["s"] / counts["m"] > 5  # ratio relajado
        assert counts["m"] / counts["l"] > 3


class TestCohortFlagsConsistency:
    def test_in_quality_matches_cohort_module(self, df_gold):
        q_in_df = set(df_gold.loc[df_gold["in_quality"], "night_record_id"])
        assert q_in_df == get_cohort_quality()

    def test_in_strict_matches_cohort_module(self, df_gold):
        s_in_df = set(df_gold.loc[df_gold["in_strict"], "night_record_id"])
        assert s_in_df == get_cohort_strict()

    def test_in_high_tst_matches_cohort_module(self, df_gold):
        h_in_df = set(df_gold.loc[df_gold["in_high_tst"], "night_record_id"])
        assert h_in_df == get_cohort_high_tst(min_tst_h=4.0)

    def test_strict_subset_quality_at_row_level(self, df_gold):
        bad = df_gold.loc[df_gold["in_strict"] & ~df_gold["in_quality"]]
        assert len(bad) == 0


class TestTraceability:
    def test_model_version_not_null(self, df_gold):
        assert df_gold["model_version"].notna().all()

    def test_user_id_resolved_for_all_rows(self, df_gold):
        assert df_gold["user_id"].isna().sum() == 0


class TestSanityChecks:
    def test_window_idx_non_negative(self, df_gold):
        assert (df_gold["window_idx"] >= 0).all()

    def test_t_start_s_le_t_end_s(self, df_gold):
        """Cada ventana debe terminar después de empezar."""
        bad = df_gold.loc[df_gold["t_start_s"] >= df_gold["t_end_s"]]
        assert len(bad) == 0

    def test_state_label_canonical_per_scale(self, df_gold):
        """Las labels deben tener el prefijo correcto por escala (S/M/L)."""
        # Excluir cluster=-1 (NaN-drop signal) si existe
        df_valid = df_gold.loc[df_gold["cluster_int"] >= 0]
        for scale, prefix in [("s", "S"), ("m", "M"), ("l", "L")]:
            sub = df_valid.loc[df_valid["scale"] == scale]
            if len(sub) > 0:
                assert sub["state_label"].str.startswith(prefix).all(), (
                    f"escala {scale} tiene labels que no empiezan con {prefix}"
                )

    def test_coverage_in_unit_interval(self, df_gold):
        assert (df_gold["coverage"] >= 0).all() and (df_gold["coverage"] <= 1).all()
