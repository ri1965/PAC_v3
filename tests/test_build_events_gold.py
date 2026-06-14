"""
Tests para scripts/build_events_gold.py (Etapa 5 paso 2).

Cobertura:
- build_events_gold() devuelve DataFrame con schema GOLD_EVENTS_SCHEMA.
- cardinalidad: una fila por EDO, sin duplicados sobre (NR, ts_start).
- todas las cols de cohorte son bool.
- model_version no es null.
- user_id resuelto para todos los EDOs (silver_qc cubre todas las noches).
- flags de cohorte son consistentes con pac.cohorts.

NO mockea I/O — corre contra el corpus real. Si el repo está fresco
(sin events/), todos los tests fallan en build, lo cual es lo deseado
(no hay nada que validar).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Importar el módulo build_events_gold dinámicamente (es un script, no un módulo de pac)
_spec = importlib.util.spec_from_file_location(
    "build_events_gold", REPO_ROOT / "scripts" / "build_events_gold.py"
)
build_events_gold_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_events_gold_module)

from pac.cohorts import (
    get_cohort_high_tst,
    get_cohort_quality,
    get_cohort_strict,
)
from pac.schemas import GOLD_EVENTS_SCHEMA, validate_events_gold


@pytest.fixture(scope="module")
def df_gold():
    """Construye una sola vez (compartido entre tests del módulo)."""
    events_dir = REPO_ROOT / "events"
    if not list(events_dir.glob("NR_*_edos.parquet")):
        pytest.skip("Sin events/_edos.parquet en el repo (CI fresco).")
    return build_events_gold_module.build_events_gold(verbose=False)


class TestSchemaContract:
    def test_columns_match_schema(self, df_gold):
        assert list(df_gold.columns) == list(GOLD_EVENTS_SCHEMA.keys())

    def test_validates_against_schema(self, df_gold):
        r = validate_events_gold(df_gold, source="<test>", strict=True)
        assert r.ok

    def test_no_duplicate_edos(self, df_gold):
        """No debe haber 2 EDOs con el mismo (NR, ts_start)."""
        n_dup = df_gold.duplicated(subset=["night_record_id", "ts_start"]).sum()
        assert n_dup == 0


class TestCohortFlagsConsistency:
    def test_in_quality_matches_cohort_module(self, df_gold):
        """Las filas con in_quality=True deben estar exactamente en get_cohort_quality()."""
        q_in_df = set(df_gold.loc[df_gold["in_quality"], "night_record_id"])
        q_module = get_cohort_quality()
        assert q_in_df == q_module

    def test_in_strict_matches_cohort_module(self, df_gold):
        s_in_df = set(df_gold.loc[df_gold["in_strict"], "night_record_id"])
        s_module = get_cohort_strict()
        assert s_in_df == s_module

    def test_in_high_tst_matches_cohort_module(self, df_gold):
        h_in_df = set(df_gold.loc[df_gold["in_high_tst"], "night_record_id"])
        h_module = get_cohort_high_tst(min_tst_h=4.0)
        assert h_in_df == h_module

    def test_strict_subset_quality(self, df_gold):
        """A nivel filas: si in_strict, entonces in_quality."""
        bad = df_gold.loc[df_gold["in_strict"] & ~df_gold["in_quality"]]
        assert len(bad) == 0


class TestTraceability:
    def test_model_version_not_null(self, df_gold):
        assert df_gold["model_version"].notna().all()

    def test_model_version_is_v1(self, df_gold):
        # En el corpus actual hay un solo modelo v1
        assert (df_gold["model_version"] == "v1").all()

    def test_user_id_resolved_for_all_rows(self, df_gold):
        """silver_qc cubre todas las noches; ningún EDO debería quedar sin user_id."""
        n_missing = df_gold["user_id"].isna().sum()
        assert n_missing == 0


class TestSanityChecks:
    def test_n_nights_consistent(self, df_gold):
        """560 noches en el corpus actual."""
        n_unique = df_gold["night_record_id"].nunique()
        assert 550 <= n_unique <= 600  # rango laxo para tolerar drift

    def test_morphotype_values_canonical(self, df_gold):
        """Solo 4 morfotipos griegos válidos."""
        vals = set(df_gold["morphotype"].dropna().unique())
        assert vals.issubset({"α", "β", "γ", "δ"})

    def test_drop_pct_positive(self, df_gold):
        """drop_pct nunca debe ser negativo (es un drop)."""
        assert (df_gold["drop_pct"] >= 0).all()
