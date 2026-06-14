"""
Tests para src/pac/schemas.py (Etapa 4.6).

Cobertura:
- Cada validador con un DataFrame válido (mínimo) → ok=True
- Detección de columnas faltantes → SchemaError en strict
- Detección de dtypes incorrectos → SchemaError en strict
- Modo strict=False emite UserWarning sin raise
- get_schema() y list_layers() devuelven definiciones correctas
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from pac.schemas import (
    BRONZE_SCHEMA,
    SchemaError,
    get_schema,
    list_layers,
    validate_bronze,
    validate_events_curves,
    validate_events_edos,
    validate_silver,
    validate_states,
)


# --------------------------------------------------------------------- #
# Builders mínimos
# --------------------------------------------------------------------- #


def _make_bronze() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="s"),
            "spo2": np.array([95, 96, 94], dtype="int64"),
            "hr": np.array([70, 72, 71], dtype="int64"),
            "mov": np.array([0, 1, 0], dtype="int64"),
            "sleep_stage": np.array([0, 1, 1], dtype="int64"),
        }
    )


def _make_silver() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="s"),
            "spo2": np.array([95, 96, 94], dtype="int64"),
            "spo2_invalid": np.array([False, False, False]),
            "spo2_clean": np.array([95.0, 96.0, 94.0]),
            "hr": np.array([70, 72, 71], dtype="int64"),
            "hr_invalid": np.array([False, False, False]),
            "hr_clean": np.array([70.0, 72.0, 71.0]),
            "mov": np.array([0, 1, 0], dtype="int64"),
            "sleep_stage": np.array([0, 1, 1], dtype="int64"),
        }
    )


def _make_events_edos() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"] * 2,
            "ts_start": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 00:05:00"]),
            "ts_end": pd.to_datetime(["2026-01-01 00:00:30", "2026-01-01 00:05:45"]),
            "duration_s": [30.0, 45.0],
            "baseline_spo2": [97.0, 98.0],
            "nadir_spo2": [88.0, 86.0],
            "drop_pct": [9.0, 12.0],
            "slope_desat_pct_s": [-0.5, -0.6],
            "slope_recov_pct_s": [0.4, 0.3],
            "auc_spo2_pct_s": [120.0, 200.0],
            "delta_hr_bpm": [8.0, 12.0],
            "baseline_hr_bpm": [62.0, 65.0],
            "peak_mov": [3.0, 5.0],
            "baseline_mov": [1.0, 1.0],
            "ird_spo2_comp": [10.0, 15.0],
            "ird_hr_comp": [3.0, 5.0],
            "ird_mov_comp": [1.0, 2.0],
            "ird_event": [14.0, 22.0],
            "near_gap": [False, False],
            "in_sleep": [True, True],
            "meets_2pct": [True, True],
            "meets_3pct": [True, True],
            "meets_4pct": [True, True],
            "meets_5pct": [True, True],
            "morphotype": ["α", "β"],
        }
    )


def _make_events_curves() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"] * 2,
            "ts_start": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-01 00:05:00"]),
            "spo2_curve": [list(range(30)), list(range(30))],
            "hr_curve": [list(range(30)), list(range(30))],
            "mov_curve": [list(range(30)), list(range(30))],
        }
    )


def _make_states() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "night_record_id": ["NR_test"] * 3,
            "scale": ["s", "m", "l"],
            "window_idx": np.array([0, 0, 0], dtype="int64"),
            "t_start": pd.to_datetime(
                ["2026-01-01 00:00:00", "2026-01-01 00:00:00", "2026-01-01 00:00:00"]
            ),
            "t_end": pd.to_datetime(
                ["2026-01-01 00:00:30", "2026-01-01 00:05:00", "2026-01-01 00:30:00"]
            ),
            "t_start_s": [0.0, 0.0, 0.0],
            "t_end_s": [30.0, 300.0, 1800.0],
            "state_label": ["S0", "M0", "L0"],
            "cluster_int": np.array([0, 0, 0], dtype="int64"),
            "dist_to_centroid": [0.5, 0.6, 0.7],
            "coverage": [1.0, 1.0, 1.0],
            "frac_wake": [0.0, 0.0, 0.0],
            "frac_light_sleep": [0.5, 0.5, 0.5],
            "frac_deep_sleep": [0.5, 0.5, 0.5],
            "training_eligible": [True, True, True],
        }
    )


# --------------------------------------------------------------------- #
# Tests "happy path"
# --------------------------------------------------------------------- #


class TestHappyPath:
    def test_bronze_ok(self):
        r = validate_bronze(_make_bronze(), source="<test>")
        assert r.ok
        assert r.layer == "bronze"
        assert r.missing == []
        assert r.wrong_dtype == []
        assert r.n_rows == 3

    def test_silver_ok(self):
        r = validate_silver(_make_silver(), source="<test>")
        assert r.ok
        assert r.layer == "silver"

    def test_events_edos_ok(self):
        r = validate_events_edos(_make_events_edos(), source="<test>")
        assert r.ok
        assert r.layer == "events_edos"

    def test_events_curves_ok(self):
        r = validate_events_curves(_make_events_curves(), source="<test>")
        assert r.ok

    def test_states_ok(self):
        r = validate_states(_make_states(), source="<test>")
        assert r.ok


# --------------------------------------------------------------------- #
# Tests de detección de problemas
# --------------------------------------------------------------------- #


class TestMissingColumns:
    def test_bronze_missing_raises_in_strict(self):
        df = _make_bronze().drop(columns=["sleep_stage"])
        with pytest.raises(SchemaError) as excinfo:
            validate_bronze(df, source="<test>", strict=True)
        assert "sleep_stage" in str(excinfo.value)

    def test_bronze_missing_warns_in_permissive(self):
        df = _make_bronze().drop(columns=["sleep_stage"])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = validate_bronze(df, source="<test>", strict=False)
        assert not r.ok
        assert "sleep_stage" in r.missing
        assert len(w) == 1


class TestWrongDtype:
    def test_silver_int_in_bool_col_raises(self):
        df = _make_silver().copy()
        df["spo2_invalid"] = [0, 0, 0]  # int en vez de bool
        with pytest.raises(SchemaError) as excinfo:
            validate_silver(df, source="<test>", strict=True)
        assert "spo2_invalid" in str(excinfo.value)

    def test_states_str_in_int_col_raises(self):
        df = _make_states().copy()
        df["window_idx"] = ["0", "0", "0"]  # str en vez de int
        with pytest.raises(SchemaError):
            validate_states(df, source="<test>", strict=True)


class TestExtras:
    def test_extras_ok_by_default(self):
        df = _make_bronze().copy()
        df["custom_col"] = 0
        r = validate_bronze(df, source="<test>", strict=True)
        assert r.ok
        assert "custom_col" in r.extras

    def test_int_subtypes_compatible(self):
        """int8, int16, int32, int64 deben ser todos válidos como 'int'."""
        for dt in ("int8", "int16", "int32", "int64"):
            df = _make_bronze().copy()
            df["spo2"] = df["spo2"].astype(dt)
            r = validate_bronze(df, source="<test>", strict=True)
            assert r.ok, f"int subtype {dt} debería ser válido"

    def test_float_subtypes_compatible(self):
        for dt in ("float32", "float64"):
            df = _make_silver().copy()
            df["spo2_clean"] = df["spo2_clean"].astype(dt)
            r = validate_silver(df, source="<test>", strict=True)
            assert r.ok, f"float subtype {dt} debería ser válido"


class TestPublicHelpers:
    def test_list_layers(self):
        layers = list_layers()
        # Etapa 4.6 (5 base) + Etapa 5 (5 gold) = 10 layers
        assert set(layers) == {
            "bronze",
            "silver",
            "events_edos",
            "events_curves",
            "states",
            "events_gold",
            "events_curves_gold",
            "states_gold",
            "nights_gold",
            "patients_gold",
        }

    def test_get_schema_bronze(self):
        s = get_schema("bronze")
        assert s == BRONZE_SCHEMA
        # Mutación no debe afectar el original
        s["foo"] = "bar"
        assert "foo" not in BRONZE_SCHEMA

    def test_get_schema_unknown_raises(self):
        with pytest.raises(KeyError):
            get_schema("gold")
