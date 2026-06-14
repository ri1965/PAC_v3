"""
PAC_v2 — Etapa 3b: clustering no-supervisado de EDOs (morphotyping).

Este módulo expone funciones puras (sin side-effects de archivos excepto las
que explícitamente persisten) para:

1. Consolidar el pool de EDOs (~78k filas) desde events/{NR}_edos.parquet.
2. Definir la máscara de training (EDOs "canónicos":
   in_sleep & ~near_gap & meets_3pct) — Q3=B.
3. Construir la matriz de features (10 cols, Q1=B: 6 morfología + 4 IRD).
4. Ajustar z-score pooled (fit en training, apply a cualquier pool).
5. Sweep K=2..10 con inertia + silhouette + Davies-Bouldin (Q2=B).
6. Fit KMeans final con K elegido, random_state=42 (reproducibilidad).
7. Predict → map int → letra griega (Q4=A).
8. Persistir (pickle + centroides CSV + metadata JSON).

Nada de I/O en las funciones puras excepto `load_edo_pool` y `persist_model`.
Los scripts `train_morphotypes.py` y `apply_morphotypes.py` orquestan.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.cluster import KMeans
from sklearn.metrics import davies_bouldin_score, silhouette_score

from pac.config import (
    ALGORITHM_VERSION_MORPHOTYPES,
    EVENTS_DIR,
    MODELS_DIR,
    MORPHOTYPE_FEATURES,
    MORPHOTYPE_GREEK_LETTERS,
    MORPHOTYPE_K_RANGE,
    MORPHOTYPE_RANDOM_STATE,
    MORPHOTYPE_TRAINING_MASK,
    MORPHOTYPES_SCHEMA_VERSION,
)


KMEANS_PKL = MODELS_DIR / "edo_morphotype_kmeans.pkl"
CENTROIDS_CSV = MODELS_DIR / "edo_morphotype_centroids.csv"
METADATA_JSON = MODELS_DIR / "edo_morphotype_metadata.json"
ZSCORE_JSON = MODELS_DIR / "edo_morphotype_zscore.json"


# ---------------------------------------------------------------------------
# Pool consolidation
# ---------------------------------------------------------------------------
def load_edo_pool(events_dir: Path = EVENTS_DIR) -> pd.DataFrame:
    """
    Consolida todos los events/NR_*_edos.parquet en un DataFrame pooled.

    No filtra: devuelve los ~78k EDOs de las 560 noches.
    """
    paths = sorted(events_dir.glob("NR_*_edos.parquet"))
    if not paths:
        raise RuntimeError(f"No se encontraron *_edos.parquet en {events_dir}")
    frames = [pq.read_table(p).to_pandas() for p in paths]
    pool = pd.concat(frames, ignore_index=True)
    return pool


# ---------------------------------------------------------------------------
# Training mask (Q3=B)
# ---------------------------------------------------------------------------
def build_training_mask(
    pool: pd.DataFrame,
    mask_spec: dict | None = None,
) -> pd.Series:
    """
    Máscara booleana del universo de training (EDOs "canónicos").

    Por default: in_sleep=True & near_gap=False & meets_3pct=True.
    Cualquier columna faltante o con NaN se interpreta como False.
    """
    if mask_spec is None:
        mask_spec = MORPHOTYPE_TRAINING_MASK
    mask = pd.Series(True, index=pool.index)
    for col, want in mask_spec.items():
        if col not in pool.columns:
            return pd.Series(False, index=pool.index)
        col_bool = pool[col].fillna(False).astype(bool)
        mask &= (col_bool == bool(want))
    return mask


# ---------------------------------------------------------------------------
# Feature matrix + z-score
# ---------------------------------------------------------------------------
def build_feature_matrix(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
) -> tuple[np.ndarray, pd.Index]:
    """
    Extrae X (n_rows × n_features) con las columnas pedidas, elimina filas con
    NaN en cualquier feature, devuelve (X, row_index_preservado).

    Raises si falta alguna columna en df (contrato estricto).
    """
    if feature_cols is None:
        feature_cols = list(MORPHOTYPE_FEATURES)
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise KeyError(f"features faltantes en df: {missing}")
    sub = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    keep = sub.notna().all(axis=1)
    sub = sub.loc[keep]
    return sub.to_numpy(dtype=float), sub.index


@dataclass
class ZScoreParams:
    """Parámetros de normalización z-score (fit en training, apply a cualquier X)."""
    mean: np.ndarray
    std: np.ndarray
    feature_cols: list[str]

    def to_dict(self) -> dict:
        return {
            "feature_cols": list(self.feature_cols),
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ZScoreParams":
        return cls(
            mean=np.asarray(d["mean"], dtype=float),
            std=np.asarray(d["std"], dtype=float),
            feature_cols=list(d["feature_cols"]),
        )


def fit_zscore(X: np.ndarray, feature_cols: list[str]) -> ZScoreParams:
    """Calcula mean/std por columna. std=0 se fuerza a 1 para evitar /0."""
    mean = X.mean(axis=0)
    std = X.std(axis=0, ddof=0)
    std = np.where(std < 1e-12, 1.0, std)
    return ZScoreParams(mean=mean, std=std, feature_cols=list(feature_cols))


def apply_zscore(X: np.ndarray, params: ZScoreParams) -> np.ndarray:
    """Aplica (X - mean) / std."""
    return (X - params.mean) / params.std


# ---------------------------------------------------------------------------
# K-sweep + fit
# ---------------------------------------------------------------------------
def sweep_k(
    Xz: np.ndarray,
    k_range: list[int] | None = None,
    random_state: int = MORPHOTYPE_RANDOM_STATE,
    silhouette_sample: int = 5000,
) -> pd.DataFrame:
    """
    Para cada K en k_range, fit KMeans y computa:
      - inertia (para elbow)
      - silhouette (sobre subsample de hasta silhouette_sample filas)
      - davies_bouldin (cuanto menor, mejor)

    Devuelve DataFrame con 1 fila por K.
    """
    if k_range is None:
        k_range = list(MORPHOTYPE_K_RANGE)
    rng = np.random.default_rng(random_state)
    # Subsample índices para silhouette (KMeans usa todo).
    n = Xz.shape[0]
    if n > silhouette_sample:
        sub_idx = rng.choice(n, size=silhouette_sample, replace=False)
    else:
        sub_idx = np.arange(n)

    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(Xz)
        sil = float(silhouette_score(Xz[sub_idx], labels[sub_idx])) \
              if len(np.unique(labels[sub_idx])) > 1 else float("nan")
        db = float(davies_bouldin_score(Xz, labels)) \
             if len(np.unique(labels)) > 1 else float("nan")
        rows.append({
            "k": int(k),
            "inertia": float(km.inertia_),
            "silhouette": round(sil, 6) if not np.isnan(sil) else None,
            "davies_bouldin": round(db, 6) if not np.isnan(db) else None,
        })
    return pd.DataFrame(rows)


def fit_kmeans(
    Xz: np.ndarray,
    k: int,
    random_state: int = MORPHOTYPE_RANDOM_STATE,
) -> KMeans:
    """Fit KMeans final con K elegido. n_init=10 para estabilidad."""
    km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    km.fit(Xz)
    return km


# ---------------------------------------------------------------------------
# Predict + mapping int → letra griega (Q4=A)
# ---------------------------------------------------------------------------
def predict_morphotype(model: KMeans, Xz: np.ndarray) -> np.ndarray:
    """Devuelve array de ints (cluster labels)."""
    return model.predict(Xz)


def int_to_greek(labels_int: np.ndarray | pd.Series) -> np.ndarray:
    """Mapea 0,1,2,… → α,β,γ,… (MORPHOTYPE_GREEK_LETTERS)."""
    arr = np.asarray(labels_int)
    if arr.size == 0:
        return np.array([], dtype=object)
    max_lbl = int(np.nanmax(arr)) if np.any(~pd.isna(arr)) else -1
    if max_lbl >= len(MORPHOTYPE_GREEK_LETTERS):
        raise ValueError(
            f"K={max_lbl+1} excede los {len(MORPHOTYPE_GREEK_LETTERS)} "
            f"símbolos disponibles en MORPHOTYPE_GREEK_LETTERS."
        )
    out = np.empty(arr.shape, dtype=object)
    for i, v in enumerate(arr):
        if pd.isna(v):
            out[i] = None
        else:
            out[i] = MORPHOTYPE_GREEK_LETTERS[int(v)]
    return out


# ---------------------------------------------------------------------------
# Centroides en espacio original (de-normalizados) para interpretabilidad
# ---------------------------------------------------------------------------
def centroids_original_space(
    model: KMeans,
    zparams: ZScoreParams,
) -> pd.DataFrame:
    """
    Centroides de KMeans están en z-space. Los llevamos a espacio original
    con centroid_orig = centroid_z * std + mean.

    Devuelve DataFrame: index = letra griega, cols = feature_cols.
    """
    cen_z = model.cluster_centers_
    cen_orig = cen_z * zparams.std + zparams.mean
    letters = MORPHOTYPE_GREEK_LETTERS[: cen_orig.shape[0]]
    return pd.DataFrame(cen_orig, columns=zparams.feature_cols, index=letters)


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def persist_model(
    model: KMeans,
    zparams: ZScoreParams,
    *,
    k_sweep: pd.DataFrame | None = None,
    n_training: int,
    models_dir: Path = MODELS_DIR,
) -> dict[str, Path]:
    """
    Escribe 4 archivos:
      - edo_morphotype_kmeans.pkl        (modelo fitted)
      - edo_morphotype_zscore.json       (mean/std + feature_cols)
      - edo_morphotype_centroids.csv     (centroides en espacio original)
      - edo_morphotype_metadata.json     (K, features, n_training, versión)
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # 1. Pickle del modelo.
    with open(models_dir / KMEANS_PKL.name, "wb") as f:
        pickle.dump(model, f)
    paths["kmeans_pkl"] = models_dir / KMEANS_PKL.name

    # 2. Z-score JSON.
    with open(models_dir / ZSCORE_JSON.name, "w", encoding="utf-8") as f:
        json.dump(zparams.to_dict(), f, indent=2)
    paths["zscore_json"] = models_dir / ZSCORE_JSON.name

    # 3. Centroides en espacio original (interpretables).
    cen = centroids_original_space(model, zparams)
    cen = cen.copy()
    cen.index.name = "morphotype"
    cen.to_csv(models_dir / CENTROIDS_CSV.name)
    paths["centroids_csv"] = models_dir / CENTROIDS_CSV.name

    # 4. Metadata JSON.
    meta = {
        "algorithm_version": ALGORITHM_VERSION_MORPHOTYPES,
        "schema_version": MORPHOTYPES_SCHEMA_VERSION,
        "k": int(model.n_clusters),
        "feature_cols": list(zparams.feature_cols),
        "n_training": int(n_training),
        "random_state": int(MORPHOTYPE_RANDOM_STATE),
        "greek_letters": MORPHOTYPE_GREEK_LETTERS[: int(model.n_clusters)],
        "training_mask": dict(MORPHOTYPE_TRAINING_MASK),
        "inertia_final": float(model.inertia_),
    }
    if k_sweep is not None:
        meta["k_sweep"] = k_sweep.to_dict(orient="records")
    with open(models_dir / METADATA_JSON.name, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    paths["metadata_json"] = models_dir / METADATA_JSON.name

    return paths


def load_model(models_dir: Path = MODELS_DIR) -> tuple[KMeans, ZScoreParams, dict]:
    """Carga modelo + z-score params + metadata desde disco."""
    with open(models_dir / KMEANS_PKL.name, "rb") as f:
        model = pickle.load(f)
    with open(models_dir / ZSCORE_JSON.name, "r", encoding="utf-8") as f:
        zparams = ZScoreParams.from_dict(json.load(f))
    with open(models_dir / METADATA_JSON.name, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return model, zparams, meta


# ---------------------------------------------------------------------------
# K selection heuristic (elbow + silhouette combined score)
# ---------------------------------------------------------------------------
def choose_k(k_sweep: pd.DataFrame) -> int:
    """
    Heurística de selección final: maximiza silhouette - 0.5 * normalized_DB.

    Roberto puede override esta decisión inspeccionando el reporte y pasando
    K manualmente a fit_kmeans. Este helper es sugerencia, no contrato.
    """
    df = k_sweep.copy()
    sil = df["silhouette"].astype(float).to_numpy()
    db = df["davies_bouldin"].astype(float).to_numpy()
    # Normaliza DB a [0,1] dentro del sweep (más alto = peor; invertimos).
    if np.nanmax(db) > np.nanmin(db):
        db_norm = (db - np.nanmin(db)) / (np.nanmax(db) - np.nanmin(db))
    else:
        db_norm = np.zeros_like(db)
    score = sil - 0.5 * db_norm
    best_idx = int(np.nanargmax(score))
    return int(df["k"].iloc[best_idx])
