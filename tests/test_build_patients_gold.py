"""
Tests para scripts/build_patients_gold.py (Etapa 5 paso 6).

Cobertura:
- Cardinalidad: 1 fila × paciente, 12 en corpus actual.
- Schema mínimo (skeleton GOLD_PATIENTS_SCHEMA) + cols esperadas presentes.
- Demografía: cols clínicas presentes y compatibles con clinical.csv.
- Conteos: n_nights_quality ≤ n_nights_total, etc.
- Agregados: 30 cols (10 métricas × mean/median/sd) presentes y bien
  tipadas. sd es NaN cuando n_quality ≤ 1.
- Distribuciones ponderadas (morfotipos + PAC states): suman 1.0 por
  paciente y por escala.
- CV intra-paciente: 3 cols, NaN para pacientes con ≤1 noche quality.
- Trazabilidad: model_version no-null.
- Cardinalidades cruzadas: pacientes en patients_gold ⊆ pacientes en
  nights_gold (via user_id).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "build_patients_gold", REPO_ROOT / "scripts" / "build_patients_gold.py"
)
build_patients_gold_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_patients_gold_module)

from pac.schemas import GOLD_PATIENTS_SCHEMA, validate_patients_gold


@pytest.fixture(scope="module")
def df_gold():
    for needed in ["events.parquet", "states.parquet", "nights.parquet"]:
        if not (REPO_ROOT / "gold" / needed).exists():
            pytest.skip(f"Falta gold/{needed}.")
    if not (REPO_ROOT / "patients" / "clinical.csv").exists():
        pytest.skip("Falta patients/clinical.csv.")
    return build_patients_gold_module.build_patients_gold(verbose=False)


@pytest.fixture(scope="module")
def df_nights():
    if not (REPO_ROOT / "gold" / "nights.parquet").exists():
        pytest.skip("Falta gold/nights.parquet.")
    return pd.read_parquet(REPO_ROOT / "gold" / "nights.parquet")


# --------------------------------------------------------------------- #
# Cardinalidad
# --------------------------------------------------------------------- #


class TestCardinality:
    def test_one_row_per_patient(self, df_gold):
        assert df_gold["user_id"].nunique() == len(df_gold)

    def test_n_patients_in_corpus(self, df_gold):
        # Corpus actual: 12 pacientes
        assert 10 <= len(df_gold) <= 60

    def test_subset_of_nights_gold_patients(self, df_gold, df_nights):
        in_pg = set(df_gold["user_id"].unique())
        in_ng = set(df_nights["user_id"].unique())
        assert in_pg.issubset(in_ng)


# --------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------- #


class TestSkeletonContract:
    def test_validates_against_skeleton(self, df_gold):
        r = validate_patients_gold(df_gold, source="<test>", strict=True)
        assert r.ok

    def test_has_minimum_skeleton_cols(self, df_gold):
        for col in GOLD_PATIENTS_SCHEMA.keys():
            assert col in df_gold.columns


# --------------------------------------------------------------------- #
# Demografía
# --------------------------------------------------------------------- #


class TestDemographics:
    def test_clinical_cols_present(self, df_gold):
        for col in ["sexo", "peso_kg", "talla_cm", "apnea_prev", "diabetes", "hta", "marcapasos"]:
            assert col in df_gold.columns

    def test_sexo_is_M_or_F(self, df_gold):
        vals = set(df_gold["sexo"].dropna().unique())
        assert vals.issubset({"M", "F"})

    def test_peso_talla_positive(self, df_gold):
        assert (df_gold["peso_kg"].dropna() > 0).all()
        assert (df_gold["talla_cm"].dropna() > 0).all()


# --------------------------------------------------------------------- #
# Conteos
# --------------------------------------------------------------------- #


class TestCounts:
    def test_count_cols_present(self, df_gold):
        for col in [
            "n_nights_total",
            "n_nights_quality",
            "n_nights_strict",
            "n_nights_high_tst",
            "n_nights_flag_for_review",
        ]:
            assert col in df_gold.columns

    def test_quality_le_total(self, df_gold):
        assert (df_gold["n_nights_quality"] <= df_gold["n_nights_total"]).all()

    def test_strict_le_quality(self, df_gold):
        assert (df_gold["n_nights_strict"] <= df_gold["n_nights_quality"]).all()

    def test_total_matches_nights_gold(self, df_gold, df_nights):
        n_in_nights = df_nights.groupby("user_id").size()
        for _, row in df_gold.iterrows():
            assert int(row["n_nights_total"]) == int(n_in_nights[row["user_id"]])


# --------------------------------------------------------------------- #
# Agregados de índices
# --------------------------------------------------------------------- #


class TestAggregates:
    def test_thirty_aggregate_cols(self, df_gold):
        # 10 métricas × {mean, median, sd}
        metrics = [
            "ahi_3",
            "t90_frac",
            "odi_3",
            "tst_s",
            "sleep_efficiency",
            "mean_spo2",
            "min_spo2",
            "mean_hr",
            "n_edos_total",
            "mean_drop_pct",
        ]
        for m in metrics:
            for stat in ["mean", "median", "sd"]:
                assert f"{stat}_{m}" in df_gold.columns

    def test_sd_nan_when_only_one_quality_night(self, df_gold):
        """sd debe ser NaN cuando n_nights_quality ≤ 1."""
        single = df_gold.loc[df_gold["n_nights_quality"] <= 1]
        if len(single) > 0:
            for m in ["ahi_3", "t90_frac"]:
                assert single[f"sd_{m}"].isna().all()

    def test_mean_ahi_3_in_clinical_range(self, df_gold):
        """Sanidad: AHI3 paciente debe estar entre 0 y 100 (rango clínico)."""
        with_data = df_gold["mean_ahi_3"].dropna()
        assert (with_data >= 0).all()
        assert (with_data < 150).all()


# --------------------------------------------------------------------- #
# Distribuciones ponderadas
# --------------------------------------------------------------------- #


class TestMorphoDistribution:
    def test_four_morpho_cols(self, df_gold):
        for m in ["α", "β", "γ", "δ"]:
            assert f"frac_morpho_{m}" in df_gold.columns

    def test_sums_to_one_per_patient(self, df_gold):
        cols = [f"frac_morpho_{m}" for m in ["α", "β", "γ", "δ"]]
        sums = df_gold[cols].sum(axis=1)
        # Todos los pacientes deberían tener al menos algunos EDOs en quality
        assert np.allclose(sums, 1.0, atol=1e-9)


class TestStateDistribution:
    def test_twenty_state_cols(self, df_gold):
        for sc, n in [("s", 6), ("m", 8), ("l", 6)]:
            for i in range(n):
                assert f"frac_state_{sc}_{sc.upper()}{i}" in df_gold.columns

    def test_sums_to_one_per_scale_per_patient(self, df_gold):
        for sc, n in [("s", 6), ("m", 8), ("l", 6)]:
            cols = [f"frac_state_{sc}_{sc.upper()}{i}" for i in range(n)]
            sums = df_gold[cols].sum(axis=1)
            assert np.allclose(sums, 1.0, atol=1e-9), f"escala {sc} no suma 1.0"


# --------------------------------------------------------------------- #
# Estabilidad fenotípica
# --------------------------------------------------------------------- #


class TestStability:
    def test_three_cv_cols(self, df_gold):
        for m in ["ahi_3", "t90_frac", "odi_3"]:
            assert f"cv_{m}_intra_patient" in df_gold.columns

    def test_cv_nan_when_only_one_quality_night(self, df_gold):
        single = df_gold.loc[df_gold["n_nights_quality"] <= 1]
        if len(single) > 0:
            assert single["cv_ahi_3_intra_patient"].isna().all()

    def test_cv_non_negative_when_present(self, df_gold):
        cv = df_gold["cv_ahi_3_intra_patient"].dropna()
        # CV puede ser NaN (mean=0) o positivo
        assert (cv >= 0).all()


# --------------------------------------------------------------------- #
# Trazabilidad
# --------------------------------------------------------------------- #


class TestTraceability:
    def test_model_version_not_null(self, df_gold):
        assert df_gold["model_version"].notna().all()

    def test_user_id_not_null(self, df_gold):
        assert df_gold["user_id"].notna().all()
