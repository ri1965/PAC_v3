"""
PAC_v2 — Etapa 4: tests unitarios de pac.states.

Cubre:
  - build_training_mask           (default, override, missing col, NaN)
  - build_feature_matrix          (happy, NaN drop, missing cols)
  - ZScoreParams / fit / apply    (roundtrip, std=0 → 1)
  - sort_pool_for_training        (determinismo)
  - sweep_k                       (structure, 3 Ks)
  - fit_kmeans                    (determinismo con random_state)
  - predict_states                (shapes)
  - int_to_state_label            (mapping, NaN, scale inválida, empty)
  - centroids_original_space      (de-normalización correcta)
  - persist_model + load_model    (roundtrip, 3 escalas)
  - _paths_for_scale              (sufijos correctos)

Total: 22 tests. Fixtures sintéticos, sin I/O externo.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from pac import states as st
from pac.config import (
    PAC_WINDOW_FEATURES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_windows_pool(n: int = 100, seed: int = 0) -> pd.DataFrame:
    """
    Pool sintético de ventanas con las 24 features + metadata mínima
    (night_record_id, window_idx, coverage, frac_wake).

    Las features se generan como 3 gaussianas separadas en espacio de 24D.
    """
    rng = np.random.default_rng(seed)
    feature_cols = list(PAC_WINDOW_FEATURES)

    # 3 clusters bien separados
    centers = [
        np.zeros(len(feature_cols)),
        np.ones(len(feature_cols)) * 3.0,
        np.ones(len(feature_cols)) * -3.0,
    ]
    rows_per = n // 3
    X_list = []
    for c in centers:
        X_list.append(c + rng.normal(0, 0.3, size=(rows_per, len(feature_cols))))
    X = np.vstack(X_list)
    # Rellenar resto con el último cluster
    if X.shape[0] < n:
        extra = n - X.shape[0]
        X = np.vstack([X, centers[-1] + rng.normal(0, 0.3, size=(extra, len(feature_cols)))])

    df = pd.DataFrame(X, columns=feature_cols)
    df["night_record_id"] = [f"NR_{i // 10:03d}" for i in range(n)]
    df["window_idx"] = list(range(n))
    df["coverage"] = rng.uniform(0.8, 1.0, size=n)
    # frac_wake ya viene del feature vector; la sobre-escribimos con valores controlados
    df["frac_wake"] = rng.uniform(0.0, 0.9, size=n)
    return df


# ===========================================================================
# 1) build_training_mask
# ===========================================================================
class TestBuildTrainingMask:
    def test_default_mask_filters_by_frac_wake_and_coverage(self):
        """Default: frac_wake ≤ 0.5 AND coverage ≥ 0.5."""
        df = pd.DataFrame({
            "frac_wake": [0.1, 0.4, 0.6, 0.2],
            "coverage":  [0.9, 0.9, 0.9, 0.3],
        })
        mask = st.build_training_mask(df)
        assert list(mask) == [True, True, False, False]

    def test_override_mask_spec(self):
        df = pd.DataFrame({
            "frac_wake": [0.1, 0.4, 0.6],
            "coverage":  [0.9, 0.9, 0.9],
        })
        mask = st.build_training_mask(df, mask_spec={
            "frac_wake_max": 0.3,
            "coverage_min": 0.5,
        })
        assert list(mask) == [True, False, False]

    def test_missing_col_raises(self):
        df = pd.DataFrame({"frac_wake": [0.1, 0.2]})  # sin coverage
        with pytest.raises(KeyError, match="coverage"):
            st.build_training_mask(df)

    def test_nan_values_are_false(self):
        df = pd.DataFrame({
            "frac_wake": [0.1, np.nan, 0.3],
            "coverage":  [0.9, 0.9, np.nan],
        })
        mask = st.build_training_mask(df)
        assert list(mask) == [True, False, False]


# ===========================================================================
# 2) build_feature_matrix
# ===========================================================================
class TestBuildFeatureMatrix:
    def test_happy_path_returns_correct_shape(self):
        df = _make_windows_pool(60)
        X, idx = st.build_feature_matrix(df)
        assert X.shape == (60, len(PAC_WINDOW_FEATURES))
        assert len(idx) == 60

    def test_drops_rows_with_nan(self):
        df = _make_windows_pool(30)
        df.loc[5, "spo2_mean"] = np.nan
        df.loc[10, "hr_std"] = np.nan
        X, idx = st.build_feature_matrix(df)
        assert X.shape[0] == 28
        assert 5 not in idx
        assert 10 not in idx

    def test_missing_feature_raises(self):
        df = _make_windows_pool(10)
        df = df.drop(columns=["spo2_mean"])
        with pytest.raises(KeyError, match="spo2_mean"):
            st.build_feature_matrix(df)


# ===========================================================================
# 3) ZScoreParams / fit / apply
# ===========================================================================
class TestZScore:
    def test_fit_basic(self):
        X = np.array([[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]])
        p = st.fit_zscore(X, feature_cols=["a", "b"])
        assert np.allclose(p.mean, [2.0, 20.0])
        assert np.allclose(p.std, [np.std([1, 2, 3]), np.std([10, 20, 30])])

    def test_std_zero_forced_to_one(self):
        """Columna constante → std=1 (evita /0)."""
        X = np.array([[5.0, 1.0], [5.0, 2.0], [5.0, 3.0]])
        p = st.fit_zscore(X, feature_cols=["const", "var"])
        assert p.std[0] == 1.0

    def test_apply_roundtrip(self):
        X = np.random.default_rng(0).normal(size=(50, 4))
        p = st.fit_zscore(X, feature_cols=["a", "b", "c", "d"])
        Xz = st.apply_zscore(X, p)
        # mean ~ 0, std ~ 1 después de z-score
        assert np.allclose(Xz.mean(axis=0), 0.0, atol=1e-10)
        assert np.allclose(Xz.std(axis=0), 1.0, atol=1e-10)

    def test_serialization_roundtrip(self):
        X = np.random.default_rng(0).normal(size=(10, 3))
        p = st.fit_zscore(X, feature_cols=["x", "y", "z"])
        d = p.to_dict()
        p2 = st.ZScoreParams.from_dict(d)
        assert p2.feature_cols == p.feature_cols
        assert np.allclose(p2.mean, p.mean)
        assert np.allclose(p2.std, p.std)


# ===========================================================================
# 4) sort_pool_for_training
# ===========================================================================
class TestSortPool:
    def test_sort_deterministic(self):
        df = pd.DataFrame({
            "night_record_id": ["NR_002", "NR_001", "NR_001", "NR_002"],
            "window_idx":      [1, 5, 0, 0],
            "x":               [10.0, 20.0, 30.0, 40.0],
        })
        sorted_df = st.sort_pool_for_training(df)
        assert list(sorted_df["night_record_id"]) == ["NR_001", "NR_001", "NR_002", "NR_002"]
        assert list(sorted_df["window_idx"]) == [0, 5, 0, 1]

    def test_sort_without_night_record_id(self):
        df = pd.DataFrame({
            "window_idx": [3, 1, 2],
            "x":          [1.0, 2.0, 3.0],
        })
        sorted_df = st.sort_pool_for_training(df)
        assert list(sorted_df["window_idx"]) == [1, 2, 3]


# ===========================================================================
# 5) sweep_k
# ===========================================================================
class TestSweepK:
    def test_sweep_returns_one_row_per_k(self):
        df = _make_windows_pool(60, seed=1)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)
        sweep = st.sweep_k(Xz, k_range=[2, 3, 4])
        assert list(sweep.k) == [2, 3, 4]
        assert {"inertia", "silhouette", "davies_bouldin"}.issubset(sweep.columns)

    def test_inertia_monotonically_decreasing(self):
        """Más clusters → menor (o igual) inertia."""
        df = _make_windows_pool(90, seed=2)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)
        sweep = st.sweep_k(Xz, k_range=[2, 3, 4, 5])
        assert list(sweep.inertia) == sorted(sweep.inertia, reverse=True)


# ===========================================================================
# 6) fit_kmeans
# ===========================================================================
class TestFitKmeans:
    def test_determinism_with_same_seed(self):
        df = _make_windows_pool(60, seed=3)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)
        m1 = st.fit_kmeans(Xz, k=3, random_state=42)
        m2 = st.fit_kmeans(Xz, k=3, random_state=42)
        assert np.allclose(m1.cluster_centers_, m2.cluster_centers_)
        assert np.array_equal(m1.predict(Xz), m2.predict(Xz))


# ===========================================================================
# 7) predict_states
# ===========================================================================
class TestPredictStates:
    def test_output_shape(self):
        df = _make_windows_pool(30, seed=4)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)
        model = st.fit_kmeans(Xz, k=3)
        preds = st.predict_states(model, Xz)
        assert preds.shape == (30,)
        assert set(preds) <= {0, 1, 2}


# ===========================================================================
# 8) int_to_state_label
# ===========================================================================
class TestIntToStateLabel:
    def test_short_scale(self):
        arr = np.array([0, 1, 5, 6])
        out = st.int_to_state_label(arr, scale="s")
        assert list(out) == ["S0", "S1", "S5", "S6"]

    def test_medium_scale(self):
        out = st.int_to_state_label(np.array([0, 3]), scale="m")
        assert list(out) == ["M0", "M3"]

    def test_long_scale(self):
        out = st.int_to_state_label(np.array([0, 2]), scale="l")
        assert list(out) == ["L0", "L2"]

    def test_nan_becomes_none(self):
        arr = pd.Series([0.0, np.nan, 1.0])
        out = st.int_to_state_label(arr, scale="s")
        assert out[0] == "S0"
        assert out[1] is None
        assert out[2] == "S1"

    def test_invalid_scale_raises(self):
        with pytest.raises(ValueError, match="Scale desconocida"):
            st.int_to_state_label(np.array([0, 1]), scale="xl")

    def test_empty_input(self):
        out = st.int_to_state_label(np.array([]), scale="s")
        assert len(out) == 0


# ===========================================================================
# 9) centroids_original_space
# ===========================================================================
class TestCentroidsOriginalSpace:
    def test_denormalization_correct(self):
        """centroid_orig = centroid_z * std + mean."""
        X = np.array([[0.0, 0.0], [10.0, 20.0], [5.0, 10.0]])
        p = st.fit_zscore(X, feature_cols=["a", "b"])
        Xz = st.apply_zscore(X, p)
        model = st.fit_kmeans(Xz, k=2, random_state=42)
        cen_orig = st.centroids_original_space(model, p, scale="s")
        cen_z = model.cluster_centers_
        expected = cen_z * p.std + p.mean
        assert np.allclose(cen_orig.to_numpy(), expected)
        assert list(cen_orig.index) == ["S0", "S1"]
        assert list(cen_orig.columns) == ["a", "b"]


# ===========================================================================
# 10) persist_model + load_model + _paths_for_scale
# ===========================================================================
class TestPersistLoad:
    def test_paths_for_scale_suffixes(self):
        p_s = st._paths_for_scale("s")
        p_m = st._paths_for_scale("m")
        p_l = st._paths_for_scale("l")
        assert "pac_states_s" in p_s["kmeans_pkl"].name
        assert "pac_states_m" in p_m["kmeans_pkl"].name
        assert "pac_states_l" in p_l["kmeans_pkl"].name

    def test_paths_invalid_scale_raises(self):
        with pytest.raises(ValueError, match="Scale desconocida"):
            st._paths_for_scale("xl")

    def test_roundtrip_all_three_scales(self, tmp_path):
        """Un modelo por escala; load devuelve lo persistido."""
        df = _make_windows_pool(60, seed=5)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)

        for scale in ("s", "m", "l"):
            k = {"s": 4, "m": 3, "l": 2}[scale]
            model = st.fit_kmeans(Xz, k=k, random_state=42)
            paths = st.persist_model(
                model, p, scale=scale, n_training=60, models_dir=tmp_path,
            )
            # Confirmar los 4 archivos creados
            for path in paths.values():
                assert path.exists()

            # Load roundtrip
            m2, p2, meta = st.load_model(scale, models_dir=tmp_path)
            assert np.allclose(m2.cluster_centers_, model.cluster_centers_)
            assert np.allclose(p2.mean, p.mean)
            assert meta["scale"] == scale
            assert meta["k"] == k
            assert meta["n_training"] == 60
            assert len(meta["state_labels"]) == k

    def test_metadata_includes_k_sweep_when_provided(self, tmp_path):
        df = _make_windows_pool(40, seed=6)
        X, _ = st.build_feature_matrix(df)
        p = st.fit_zscore(X, feature_cols=list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, p)
        model = st.fit_kmeans(Xz, k=3, random_state=42)
        sweep = st.sweep_k(Xz, k_range=[2, 3, 4])
        paths = st.persist_model(
            model, p, scale="m", n_training=40, k_sweep=sweep, models_dir=tmp_path,
        )
        with open(paths["metadata_json"], "r", encoding="utf-8") as f:
            meta = json.load(f)
        assert "k_sweep" in meta
        assert len(meta["k_sweep"]) == 3
