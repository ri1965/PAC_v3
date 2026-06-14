"""
Tests para scripts/build_events_curves_gold.py (Etapa 5 paso 3).

Cobertura:
- DataFrame respeta GOLD_EVENTS_CURVES_SCHEMA.
- 560 noches únicas (matching events_gold).
- Cardinalidad de filas == events_gold (1 EDO ↔ 1 fila de curvas).
- Las 3 listas (spo2_curve, hr_curve, mov_curve) son no vacías.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Importar dinámicamente
_spec1 = importlib.util.spec_from_file_location(
    "build_events_curves_gold",
    REPO_ROOT / "scripts" / "build_events_curves_gold.py",
)
build_events_curves_gold_module = importlib.util.module_from_spec(_spec1)
_spec1.loader.exec_module(build_events_curves_gold_module)

_spec2 = importlib.util.spec_from_file_location(
    "build_events_gold", REPO_ROOT / "scripts" / "build_events_gold.py"
)
build_events_gold_module = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(build_events_gold_module)

from pac.schemas import (
    GOLD_EVENTS_CURVES_SCHEMA,
    validate_events_curves_gold,
)


@pytest.fixture(scope="module")
def df_curves():
    events_dir = REPO_ROOT / "events"
    if not list(events_dir.glob("NR_*_edo_curves.parquet")):
        pytest.skip("Sin events/_edo_curves.parquet en el repo (CI fresco).")
    return build_events_curves_gold_module.build_events_curves_gold(verbose=False)


@pytest.fixture(scope="module")
def df_events():
    events_dir = REPO_ROOT / "events"
    if not list(events_dir.glob("NR_*_edos.parquet")):
        pytest.skip("Sin events/_edos.parquet en el repo (CI fresco).")
    return build_events_gold_module.build_events_gold(verbose=False)


class TestSchemaContract:
    def test_columns_match(self, df_curves):
        assert list(df_curves.columns) == list(GOLD_EVENTS_CURVES_SCHEMA.keys())

    def test_validates_against_schema(self, df_curves):
        r = validate_events_curves_gold(df_curves, source="<test>", strict=True)
        assert r.ok


class TestCardinality:
    def test_same_n_as_events_gold(self, df_curves, df_events):
        """1 EDO en events_gold ↔ 1 fila en events_curves_gold."""
        assert len(df_curves) == len(df_events)

    def test_same_nights_as_events_gold(self, df_curves, df_events):
        nrs_curves = set(df_curves["night_record_id"].unique())
        nrs_events = set(df_events["night_record_id"].unique())
        assert nrs_curves == nrs_events

    def test_join_key_unique(self, df_curves):
        """(NR, ts_start) debe ser key única."""
        n_dup = df_curves.duplicated(subset=["night_record_id", "ts_start"]).sum()
        assert n_dup == 0


class TestCurveContents:
    def test_curves_non_empty(self, df_curves):
        """Las primeras 100 filas deben tener listas no vacías."""
        sample = df_curves.head(100)
        for _, row in sample.iterrows():
            assert len(row["spo2_curve"]) > 0
            assert len(row["hr_curve"]) > 0
            assert len(row["mov_curve"]) > 0

    def test_three_curves_same_length_per_row(self, df_curves):
        """spo2/hr/mov deben tener la misma longitud dentro de un EDO."""
        sample = df_curves.head(100)
        for _, row in sample.iterrows():
            assert (
                len(row["spo2_curve"])
                == len(row["hr_curve"])
                == len(row["mov_curve"])
            )
