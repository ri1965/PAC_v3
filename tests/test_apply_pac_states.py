"""
PAC_v2 — Etapa 4 paso 7: tests para scripts/apply_pac_states.py.

Cubre el núcleo de labeling (label_night + write_states_parquet) sin
depender de los modelos persistidos en models/ ni de los parquets reales
en silver/. Toda la fixture es sintética y reproducible.

Tests (6):
  - schema_and_dtypes        : OUTPUT_COLS + dtypes correctos por col.
  - state_label_prefix       : "s"→S0..S{k-1}, "m"→M..., "l"→L...
  - idempotent_byte_for_byte : 2 llamadas seguidas producen df idéntico.
  - nan_feature_window       : ventana con NaN en feature → cluster=-1,
                               state_label=None, dist=NaN.
  - training_eligible_flag   : Q6=C predicate (frac_wake≤0.5 AND coverage≥0.5).
  - parquet_roundtrip        : write → read preserva schema + KV metadata.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.cluster import KMeans

# El script vive en scripts/ — lo importamos haciendo append al sys.path.
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import apply_pac_states as ap  # noqa: E402

from pac import states as st
from pac.config import (
    PAC_STATE_PREFIXES,
    PAC_STATE_SCALES,
    PAC_STATES_TRAINING_MASK,
    PAC_WINDOW_FEATURES,
)


# ===========================================================================
# Fixtures sintéticas
# ===========================================================================
def _make_synthetic_silver(n_seconds: int = 7200, seed: int = 0) -> pd.DataFrame:
    """
    Silver sintético compatible con windows.partition_windows:
      cols: timestamp, spo2_clean, hr_clean, mov, sleep_stage.
    n_seconds = 7200 → 2 horas → 4 ventanas l, 24 ventanas m, 240 ventanas s.
    """
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2026-04-24 22:00:00")
    return pd.DataFrame({
        "timestamp": pd.date_range(t0, periods=n_seconds, freq="s"),
        "spo2_clean": rng.uniform(85, 99, size=n_seconds),
        "hr_clean":   rng.uniform(50, 90, size=n_seconds),
        "mov":        rng.uniform(0, 100, size=n_seconds),
        # Stage mayoritariamente sueño liviano + algo de wake/deep.
        "sleep_stage": pd.Series(
            rng.choice([0, 1, 2, 3], size=n_seconds, p=[0.1, 0.5, 0.2, 0.2]),
            dtype="Int64",
        ),
    })


def _make_synthetic_edos() -> pd.DataFrame:
    """EDOs vacíos (no afectan el clustering, sólo morphotype densities=0)."""
    return pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])


def _make_synthetic_models(k_per_scale: dict | None = None) -> dict:
    """
    Construye un dict {scale: {model, zparams, centroids_z, k, prefix}}
    con KMeans tiny entrenados sobre features sintéticas. NO toca disk.
    """
    if k_per_scale is None:
        k_per_scale = {"s": 3, "m": 3, "l": 2}
    rng = np.random.default_rng(42)
    feature_cols = list(PAC_WINDOW_FEATURES)
    n = 200
    X = rng.normal(0, 1, size=(n, len(feature_cols)))
    zparams = st.fit_zscore(X, feature_cols)
    Xz = st.apply_zscore(X, zparams)

    out = {}
    for scale in PAC_STATE_SCALES:
        k = k_per_scale[scale]
        km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(Xz)
        out[scale] = {
            "model": km,
            "zparams": zparams,
            "centroids_z": np.asarray(km.cluster_centers_, dtype=float),
            "k": k,
            "prefix": PAC_STATE_PREFIXES[scale],
        }
    return out


# ===========================================================================
# Tests
# ===========================================================================
class TestLabelNightSchema:
    def test_schema_and_dtypes(self, tmp_path: Path):
        """OUTPUT_COLS exactos + dtypes correctos por columna."""
        silver = _make_synthetic_silver()
        edos = _make_synthetic_edos()
        sp = tmp_path / "NR_test000001.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models()
        df, _ = ap.label_night(sp, None, models)

        # Schema
        assert list(df.columns) == ap.OUTPUT_COLS, \
            f"cols mismatch: {df.columns.tolist()}"

        # Dtypes
        assert df["scale"].dtype == object
        assert df["window_idx"].dtype == np.int64
        assert pd.api.types.is_datetime64_any_dtype(df["t_start"])
        assert pd.api.types.is_datetime64_any_dtype(df["t_end"])
        assert df["t_start_s"].dtype == np.float64
        assert df["t_end_s"].dtype == np.float64
        assert df["state_label"].dtype == object
        assert df["cluster_int"].dtype == np.int64
        assert df["dist_to_centroid"].dtype == np.float64
        assert df["coverage"].dtype == np.float64
        assert df["training_eligible"].dtype == np.bool_

        # 3 escalas presentes
        assert set(df["scale"].unique()) == {"s", "m", "l"}

        # Sort order: (scale, window_idx)
        for scale in ("l", "m", "s"):  # orden alfabético
            sub = df[df["scale"] == scale]
            assert sub["window_idx"].tolist() == sorted(sub["window_idx"].tolist())


class TestLabelNightStateLabels:
    def test_state_label_prefix_per_scale(self, tmp_path: Path):
        """Labels respetan el prefijo de su escala."""
        silver = _make_synthetic_silver()
        sp = tmp_path / "NR_prefix0001.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models(k_per_scale={"s": 3, "m": 3, "l": 2})
        df, _ = ap.label_night(sp, None, models)

        for scale, prefix in (("s", "S"), ("m", "M"), ("l", "L")):
            sub = df[(df["scale"] == scale) & (df["state_label"].notna())]
            assert (sub["state_label"].str[0] == prefix).all(), \
                f"scale {scale} produjo labels con prefijo distinto a {prefix}"
            # Los ints deben caer en [0, k-1]
            k = models[scale]["k"]
            ints = sub["state_label"].str[1:].astype(int)
            assert ints.min() >= 0 and ints.max() < k


class TestLabelNightIdempotent:
    def test_idempotent_byte_for_byte(self, tmp_path: Path):
        """label_night llamada dos veces produce DataFrames idénticos."""
        silver = _make_synthetic_silver(n_seconds=3600, seed=7)
        sp = tmp_path / "NR_idempotnt.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models()
        df1, stats1 = ap.label_night(sp, None, models)
        df2, stats2 = ap.label_night(sp, None, models)

        pd.testing.assert_frame_equal(df1, df2)
        assert stats1 == stats2


class TestLabelNightNaN:
    def test_nan_feature_window_dropped(self, tmp_path: Path):
        """Ventana con todos NaN en spo2_clean → cluster=-1, label=None, dist=NaN."""
        silver = _make_synthetic_silver(n_seconds=3600, seed=3)
        # Forzar todos los samples spo2_clean a NaN en los primeros 30s
        # → la ventana s[0] tendrá spo2_* todos NaN → drop.
        silver.loc[:29, "spo2_clean"] = np.nan
        sp = tmp_path / "NR_nantest001.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models()
        df, stats = ap.label_night(sp, None, models)

        s_first = df[(df["scale"] == "s") & (df["window_idx"] == 0)]
        assert len(s_first) == 1
        row = s_first.iloc[0]
        assert row["cluster_int"] == -1
        assert row["state_label"] is None
        assert pd.isna(row["dist_to_centroid"])
        # El reporte debe contar el drop
        assert stats["by_scale"]["s"]["n_dropped_nan"] >= 1


class TestTrainingEligibleFlag:
    def test_training_eligible_matches_q6c_predicate(self, tmp_path: Path):
        """training_eligible = (frac_wake ≤ 0.5) AND (coverage ≥ 0.5)."""
        silver = _make_synthetic_silver(n_seconds=3600, seed=11)
        sp = tmp_path / "NR_eligible01.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models()
        df, _ = ap.label_night(sp, None, models)

        fw_max = PAC_STATES_TRAINING_MASK["frac_wake_max"]
        cov_min = PAC_STATES_TRAINING_MASK["coverage_min"]

        expected = (df["frac_wake"] <= fw_max) & (df["coverage"] >= cov_min)
        # Las NaN en frac_wake/coverage se interpretan como False
        expected = expected.fillna(False)
        pd.testing.assert_series_equal(
            df["training_eligible"].rename("x"),
            expected.rename("x"),
        )


class TestParquetRoundtrip:
    def test_write_and_read_preserves_schema_and_kv(self, tmp_path: Path):
        """write_states_parquet + read preserva schema + KV metadata."""
        silver = _make_synthetic_silver(n_seconds=1800, seed=13)
        sp = tmp_path / "NR_roundtrip1.parquet"
        silver.to_parquet(sp)

        models = _make_synthetic_models()
        df, _ = ap.label_night(sp, None, models)

        out_path = tmp_path / "states" / "NR_roundtrip1.parquet"
        # Etapa 6.1: ahora write_states_parquet requiere models_sha256.
        fake_sha = "abcdef0123456789"
        ap.write_states_parquet(
            df, out_path, "NR_roundtrip1", sp, None, models, fake_sha
        )

        # Schema preservado
        df2 = pd.read_parquet(out_path)
        assert list(df2.columns) == ap.OUTPUT_COLS
        pd.testing.assert_frame_equal(
            df2.reset_index(drop=True),
            df.reset_index(drop=True),
        )

        # KV metadata
        tbl = pq.read_table(out_path)
        kv = {k.decode(): v.decode() for k, v in (tbl.schema.metadata or {}).items()
              if not k.startswith(b"pandas")}
        assert kv["night_record_id"] == "NR_roundtrip1"
        assert "applied_at" in kv
        assert "algorithm_version" in kv
        assert "k_per_scale" in kv
        # Etapa 6.1: SHA del modelo persistido
        assert kv["model_centroids_sha256"] == fake_sha
