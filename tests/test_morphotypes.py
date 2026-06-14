"""
PAC_v2 — Etapa 3b: tests unitarios de pac.morphotypes.

Cubre:
- build_training_mask (mask canónica, columna faltante, NaNs, override spec)
- build_feature_matrix (drop NaN, preservación de índice, columnas faltantes)
- fit_zscore / apply_zscore (roundtrip, std=0 → std=1)
- sweep_k (estructura, K reales)
- fit_kmeans (determinismo con random_state)
- int_to_greek (mapping, K > 10 raise, NaN handling)
- centroids_original_space (de-normalización correcta)
- persist_model + load_model (roundtrip)
- choose_k (heurística retorna K dentro de rango)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pac import morphotypes as mt
from pac.config import (
    MORPHOTYPE_FEATURES,
)


# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------
def _make_pool(n: int = 100, seed: int = 0) -> pd.DataFrame:
    """Pool sintético con 3 clusters bien separados + flags booleanos."""
    rng = np.random.default_rng(seed)
    # 3 gaussianas en espacio de 10 features (separadas por +/-3 en media).
    centers = [
        np.zeros(10),
        np.ones(10) * 3.0,
        np.ones(10) * -3.0,
    ]
    # Distribuir n filas en 3 grupos, el último absorbe el resto.
    base = n // 3
    sizes = [base, base, n - 2 * base]
    Xs = [rng.normal(loc=c, scale=0.5, size=(s, 10)) for c, s in zip(centers, sizes)]
    X = np.vstack(Xs)
    assert X.shape[0] == n
    df = pd.DataFrame(X, columns=MORPHOTYPE_FEATURES)
    # Flags mayormente True/False/True respectivamente.
    df["in_sleep"] = True
    df["near_gap"] = False
    df["meets_3pct"] = True
    # Marcamos algunos como "basura" (marginales) para la máscara.
    df.loc[::10, "in_sleep"] = False
    df.loc[1::20, "near_gap"] = True
    df.loc[2::15, "meets_3pct"] = False
    return df


# ---------------------------------------------------------------------------
# build_training_mask
# ---------------------------------------------------------------------------
def test_build_training_mask_default():
    pool = _make_pool(100)
    mask = mt.build_training_mask(pool)
    # Debe ser pd.Series booleana de misma longitud.
    assert isinstance(mask, pd.Series)
    assert mask.dtype == bool
    assert len(mask) == len(pool)
    # Las filas con in_sleep=False, near_gap=True, o meets_3pct=False se excluyen.
    expected = (
        (pool["in_sleep"] == True)
        & (pool["near_gap"] == False)
        & (pool["meets_3pct"] == True)
    )
    assert mask.equals(expected)


def test_build_training_mask_missing_column():
    # Si falta alguna columna del spec, la máscara entera queda False.
    pool = _make_pool(20).drop(columns=["meets_3pct"])
    mask = mt.build_training_mask(pool)
    assert mask.dtype == bool
    assert mask.sum() == 0


def test_build_training_mask_nan_treated_as_false():
    pool = _make_pool(50)
    pool.loc[0, "in_sleep"] = np.nan
    mask = mt.build_training_mask(pool)
    # fila 0 debe quedar excluida (NaN → False).
    assert not mask.iloc[0]


def test_build_training_mask_override_spec():
    pool = _make_pool(30)
    custom = {"meets_3pct": True}
    mask = mt.build_training_mask(pool, mask_spec=custom)
    expected = pool["meets_3pct"].astype(bool)
    assert mask.equals(expected)


# ---------------------------------------------------------------------------
# build_feature_matrix
# ---------------------------------------------------------------------------
def test_build_feature_matrix_basic():
    pool = _make_pool(50)
    X, idx = mt.build_feature_matrix(pool)
    assert X.shape == (50, 10)
    assert len(idx) == 50
    assert X.dtype == float


def test_build_feature_matrix_drops_nan_rows():
    pool = _make_pool(20)
    pool.loc[5, "duration_s"] = np.nan
    pool.loc[10, "ird_event"] = np.nan
    X, idx = mt.build_feature_matrix(pool)
    # 2 filas dropped → 18 sobreviven.
    assert X.shape == (18, 10)
    assert 5 not in idx
    assert 10 not in idx


def test_build_feature_matrix_raises_on_missing_col():
    pool = _make_pool(10).drop(columns=["ird_event"])
    with pytest.raises(KeyError, match="features faltantes"):
        mt.build_feature_matrix(pool)


# ---------------------------------------------------------------------------
# fit_zscore / apply_zscore
# ---------------------------------------------------------------------------
def test_zscore_roundtrip():
    rng = np.random.default_rng(0)
    X = rng.normal(loc=5.0, scale=2.0, size=(500, 10))
    z = mt.fit_zscore(X, list(MORPHOTYPE_FEATURES))
    Xz = mt.apply_zscore(X, z)
    # Xz debe tener mean ~0 y std ~1 por columna.
    assert np.allclose(Xz.mean(axis=0), 0.0, atol=1e-9)
    assert np.allclose(Xz.std(axis=0, ddof=0), 1.0, atol=1e-9)


def test_zscore_zero_std_safe():
    # Columna constante → std=0; debe forzarse a 1 sin crashear.
    X = np.array([[1.0, 2.0], [1.0, 4.0], [1.0, 6.0]])
    z = mt.fit_zscore(X, ["a", "b"])
    assert z.std[0] == 1.0  # forzado
    Xz = mt.apply_zscore(X, z)
    # Col 0 → todos 0 (mean=1, (1-1)/1 = 0).
    assert np.all(Xz[:, 0] == 0)


def test_zscore_dict_roundtrip():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(20, 3))
    z1 = mt.fit_zscore(X, ["x", "y", "z"])
    z2 = mt.ZScoreParams.from_dict(z1.to_dict())
    assert z1.feature_cols == z2.feature_cols
    assert np.allclose(z1.mean, z2.mean)
    assert np.allclose(z1.std, z2.std)


# ---------------------------------------------------------------------------
# sweep_k
# ---------------------------------------------------------------------------
def test_sweep_k_structure():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 4))
    df = mt.sweep_k(X, k_range=[2, 3, 4])
    assert list(df.columns) == ["k", "inertia", "silhouette", "davies_bouldin"]
    assert list(df["k"]) == [2, 3, 4]
    # Inertia debe ser decreciente en K.
    inertias = df["inertia"].tolist()
    assert inertias[0] > inertias[1] > inertias[2]


def test_sweep_k_small_n():
    # n chico pero suficiente: silhouette + DB devuelven floats.
    rng = np.random.default_rng(0)
    X = rng.normal(size=(30, 3))
    df = mt.sweep_k(X, k_range=[2, 3])
    for col in ("silhouette", "davies_bouldin"):
        assert df[col].notna().all()


# ---------------------------------------------------------------------------
# fit_kmeans
# ---------------------------------------------------------------------------
def test_fit_kmeans_determinism():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(100, 4))
    m1 = mt.fit_kmeans(X, k=3, random_state=42)
    m2 = mt.fit_kmeans(X, k=3, random_state=42)
    # Mismos centroides (hasta permutación, pero con mismo random_state son idénticos).
    assert np.allclose(m1.cluster_centers_, m2.cluster_centers_)


def test_fit_kmeans_separates_clusters():
    # Si los clusters están bien separados, silhouette > 0.5.
    from sklearn.metrics import silhouette_score
    pool = _make_pool(300)
    X, _ = mt.build_feature_matrix(pool)
    z = mt.fit_zscore(X, list(MORPHOTYPE_FEATURES))
    Xz = mt.apply_zscore(X, z)
    model = mt.fit_kmeans(Xz, k=3)
    labels = model.predict(Xz)
    sil = silhouette_score(Xz, labels)
    assert sil > 0.5, f"silhouette={sil} demasiado bajo — clusters no separados"


# ---------------------------------------------------------------------------
# int_to_greek
# ---------------------------------------------------------------------------
def test_int_to_greek_basic():
    labels = np.array([0, 1, 2, 1, 0])
    greek = mt.int_to_greek(labels)
    assert list(greek) == ["α", "β", "γ", "β", "α"]


def test_int_to_greek_empty():
    out = mt.int_to_greek(np.array([], dtype=int))
    assert len(out) == 0


def test_int_to_greek_too_many_clusters():
    labels = np.array([0, 1, 2, 10])  # K=11 excede los 10 símbolos disponibles
    with pytest.raises(ValueError, match="excede"):
        mt.int_to_greek(labels)


# ---------------------------------------------------------------------------
# centroids_original_space
# ---------------------------------------------------------------------------
def test_centroids_original_space():
    pool = _make_pool(300)
    X, _ = mt.build_feature_matrix(pool)
    z = mt.fit_zscore(X, list(MORPHOTYPE_FEATURES))
    Xz = mt.apply_zscore(X, z)
    model = mt.fit_kmeans(Xz, k=3)
    cen = mt.centroids_original_space(model, z)
    # Shape + index = letras griegas.
    assert cen.shape == (3, 10)
    assert list(cen.index) == ["α", "β", "γ"]
    assert list(cen.columns) == list(MORPHOTYPE_FEATURES)
    # Los centroides deben estar cerca de los centers sintéticos (0, ±3).
    rounded_means = cen.mean(axis=1).round(0).tolist()
    assert set(rounded_means) == {0.0, 3.0, -3.0}


# ---------------------------------------------------------------------------
# persist_model + load_model
# ---------------------------------------------------------------------------
def test_persist_and_load_roundtrip(tmp_path):
    pool = _make_pool(150)
    X, _ = mt.build_feature_matrix(pool)
    z = mt.fit_zscore(X, list(MORPHOTYPE_FEATURES))
    Xz = mt.apply_zscore(X, z)
    sweep = mt.sweep_k(Xz, k_range=[2, 3])
    model = mt.fit_kmeans(Xz, k=3)
    paths = mt.persist_model(
        model, z, k_sweep=sweep, n_training=150, models_dir=tmp_path
    )
    assert paths["kmeans_pkl"].exists()
    assert paths["zscore_json"].exists()
    assert paths["centroids_csv"].exists()
    assert paths["metadata_json"].exists()

    loaded_model, loaded_z, meta = mt.load_model(models_dir=tmp_path)
    assert loaded_model.n_clusters == 3
    assert np.allclose(loaded_model.cluster_centers_, model.cluster_centers_)
    assert np.allclose(loaded_z.mean, z.mean)
    assert np.allclose(loaded_z.std, z.std)
    assert meta["k"] == 3
    assert meta["n_training"] == 150
    assert meta["random_state"] == 42


# ---------------------------------------------------------------------------
# choose_k
# ---------------------------------------------------------------------------
def test_choose_k_returns_valid_k():
    sweep = pd.DataFrame({
        "k": [2, 3, 4, 5],
        "inertia": [100.0, 60.0, 40.0, 30.0],
        "silhouette": [0.4, 0.55, 0.50, 0.45],
        "davies_bouldin": [0.9, 0.7, 0.8, 1.0],
    })
    k = mt.choose_k(sweep)
    assert k in sweep["k"].tolist()
    # Con este sweep K=3 debería ganar (max sil con DB bajo).
    assert k == 3
