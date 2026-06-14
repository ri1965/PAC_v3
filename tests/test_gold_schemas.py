"""
Tests para los schemas Gold (Etapa 5 paso 1) en src/pac/schemas.py.

Cobertura:
- GOLD_*_SCHEMA tienen las cols esperadas (incluyendo bloques transversales).
- list_layers() incluye los 5 layers gold.
- get_schema('events_gold' / etc.) devuelve copia mutable-aislada.
- validate_*_gold ok-path sobre DataFrames mínimos.
- validate_events_gold raise si falta una flag de cohorte (strict).
- validate_nights_gold y validate_patients_gold permiten extras (skeleton).
"""

from __future__ import annotations


import numpy as np
import pandas as pd
import pytest

from pac.schemas import (
    GOLD_EVENTS_CURVES_SCHEMA,
    GOLD_EVENTS_SCHEMA,
    GOLD_STATES_SCHEMA,
    SchemaError,
    get_schema,
    list_layers,
    validate_events_curves_gold,
    validate_events_gold,
    validate_nights_gold,
    validate_patients_gold,
    validate_states_gold,
)


# --------------------------------------------------------------------- #
# Builders mínimos
# --------------------------------------------------------------------- #


def _make_events_gold() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"],
            "ts_start": pd.to_datetime(["2026-01-01 00:00:00"]),
            "ts_end": pd.to_datetime(["2026-01-01 00:00:30"]),
            "duration_s": [30.0],
            "baseline_spo2": [97.0],
            "nadir_spo2": [88.0],
            "drop_pct": [9.0],
            "slope_desat_pct_s": [-0.5],
            "slope_recov_pct_s": [0.4],
            "auc_spo2_pct_s": [120.0],
            "delta_hr_bpm": [8.0],
            "baseline_hr_bpm": [62.0],
            "peak_mov": [3.0],
            "baseline_mov": [1.0],
            "ird_spo2_comp": [10.0],
            "ird_hr_comp": [3.0],
            "ird_mov_comp": [1.0],
            "ird_event": [14.0],
            "near_gap": [False],
            "in_sleep": [True],
            "meets_2pct": [True],
            "meets_3pct": [True],
            "meets_4pct": [True],
            "meets_5pct": [True],
            "morphotype": ["α"],
            "user_id": ["U001"],
            "model_version": ["v1"],
            "in_quality": [True],
            "in_strict": [True],
            "in_high_tst": [True],
            "flag_for_review": [False],
            "b2_fail": [False],
        }
    )


def _make_events_curves_gold() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"],
            "ts_start": pd.to_datetime(["2026-01-01 00:00:00"]),
            "spo2_curve": [list(range(30))],
            "hr_curve": [list(range(30))],
            "mov_curve": [list(range(30))],
        }
    )


def _make_states_gold() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"],
            "scale": ["s"],
            "window_idx": np.array([0], dtype="int64"),
            "t_start": pd.to_datetime(["2026-01-01 00:00:00"]),
            "t_end": pd.to_datetime(["2026-01-01 00:00:30"]),
            "t_start_s": [0.0],
            "t_end_s": [30.0],
            "state_label": ["S0"],
            "cluster_int": np.array([0], dtype="int64"),
            "dist_to_centroid": [0.5],
            "coverage": [1.0],
            "frac_wake": [0.0],
            "frac_light_sleep": [0.5],
            "frac_deep_sleep": [0.5],
            "training_eligible": [True],
            "user_id": ["U001"],
            "model_version": ["v1"],
            "in_quality": [True],
            "in_strict": [True],
            "in_high_tst": [True],
            "flag_for_review": [False],
            "b2_fail": [False],
        }
    )


def _make_nights_gold_skeleton() -> pd.DataFrame:
    """Skeleton mínimo del schema definido en paso 1."""
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"],
            "user_id": ["U001"],
            "model_version": ["v1"],
            "in_quality": [True],
            "in_strict": [True],
            "in_high_tst": [True],
            "flag_for_review": [False],
            "b2_fail": [False],
        }
    )


def _make_patients_gold_skeleton() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": ["U001"],
            "model_version": ["v1"],
            "n_nights_total": np.array([5], dtype="int64"),
        }
    )


# --------------------------------------------------------------------- #
# Schemas — estructura
# --------------------------------------------------------------------- #


class TestSchemaStructure:
    def test_events_gold_extends_events_edos(self):
        # 25 cols originales + user_id + model_version + 5 flags = 32
        assert len(GOLD_EVENTS_SCHEMA) == 32
        # Verificar bloques transversales
        for col in [
            "user_id",
            "model_version",
            "in_quality",
            "in_strict",
            "in_high_tst",
            "flag_for_review",
            "b2_fail",
        ]:
            assert col in GOLD_EVENTS_SCHEMA, f"falta {col} en GOLD_EVENTS_SCHEMA"

    def test_events_curves_gold_no_extra_block(self):
        # events_curves se accede por join con events_gold; no duplicar flags
        assert len(GOLD_EVENTS_CURVES_SCHEMA) == 5
        assert "user_id" not in GOLD_EVENTS_CURVES_SCHEMA
        assert "in_quality" not in GOLD_EVENTS_CURVES_SCHEMA

    def test_states_gold_extends_states(self):
        # 15 cols originales + user_id + model_version + 5 flags = 22
        assert len(GOLD_STATES_SCHEMA) == 22
        for col in ["user_id", "model_version", "in_quality"]:
            assert col in GOLD_STATES_SCHEMA

    def test_list_layers_includes_gold(self):
        layers = list_layers()
        for ly in [
            "events_gold",
            "events_curves_gold",
            "states_gold",
            "nights_gold",
            "patients_gold",
        ]:
            assert ly in layers

    def test_get_schema_gold_mutation_isolated(self):
        s = get_schema("events_gold")
        s["foo"] = "bar"
        assert "foo" not in GOLD_EVENTS_SCHEMA


# --------------------------------------------------------------------- #
# Validators — happy path
# --------------------------------------------------------------------- #


class TestGoldValidatorsHappy:
    def test_events_gold_ok(self):
        r = validate_events_gold(_make_events_gold(), source="<test>")
        assert r.ok
        assert r.layer == "events_gold"
        assert r.missing == []

    def test_events_curves_gold_ok(self):
        r = validate_events_curves_gold(_make_events_curves_gold(), source="<test>")
        assert r.ok

    def test_states_gold_ok(self):
        r = validate_states_gold(_make_states_gold(), source="<test>")
        assert r.ok

    def test_nights_gold_skeleton_ok(self):
        r = validate_nights_gold(_make_nights_gold_skeleton(), source="<test>")
        assert r.ok

    def test_patients_gold_skeleton_ok(self):
        r = validate_patients_gold(_make_patients_gold_skeleton(), source="<test>")
        assert r.ok


# --------------------------------------------------------------------- #
# Validators — detección de problemas
# --------------------------------------------------------------------- #


class TestGoldValidatorsDetect:
    def test_events_gold_missing_flag_raises(self):
        df = _make_events_gold().drop(columns=["in_quality"])
        with pytest.raises(SchemaError) as excinfo:
            validate_events_gold(df, source="<test>", strict=True)
        assert "in_quality" in str(excinfo.value)

    def test_events_gold_missing_model_version_raises(self):
        df = _make_events_gold().drop(columns=["model_version"])
        with pytest.raises(SchemaError) as excinfo:
            validate_events_gold(df, source="<test>", strict=True)
        assert "model_version" in str(excinfo.value)

    def test_events_gold_wrong_dtype_in_flag(self):
        df = _make_events_gold().copy()
        df["in_quality"] = [1]  # int en vez de bool
        with pytest.raises(SchemaError):
            validate_events_gold(df, source="<test>", strict=True)

    def test_nights_gold_skeleton_allows_extras(self):
        """nights_gold en paso 1 es skeleton; cols extra no rompen."""
        df = _make_nights_gold_skeleton().copy()
        df["custom_metric"] = 1.5
        df["another_one"] = "foo"
        r = validate_nights_gold(df, source="<test>", strict=True)
        assert r.ok
        assert "custom_metric" in r.extras
