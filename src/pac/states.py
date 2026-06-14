"""
PAC_v2 — Etapa 4: clustering no-supervisado de estados PAC (KMeans por escala).

Este módulo expone funciones puras para:

1. Aplicar la máscara de training híbrida (Q6=C) a un pool de ventanas:
   frac_wake ≤ max, coverage ≥ min.
2. Construir la matriz de features (24 cols, Q3=A: z-score sobre las 24).
3. Ajustar z-score pooled por escala (fit sobre training, apply a inferencia).
4. Sweep K ∈ [2..10] con inertia + silhouette + Davies-Bouldin (Q5=C).
5. Fit KMeans final con K elegido, random_state=42 (Q4=A, reproducibilidad).
6. Predict → map int → label "S{i}" / "M{i}" / "L{i}" según escala.
7. Centroides de-normalizados en espacio original (interpretabilidad).
8. Persistir + cargar (pkl + zscore json + centroides csv + metadata json).

Decisiones cerradas (Roberto, paso 3 de Etapa 4):
  Q1=3 modelos: un KMeans independiente por escala → los archivos tienen
     sufijo {s,m,l}.
  Q2=sí: se ordena el pool por (night_record_id, window_idx) antes de fit
     para que el entrenamiento sea byte-reproducible.
  Q3=A: z-score sobre las 24 features, incluidas frac_wake/light/deep
     (peso comparable en distancia euclidiana).
  Q4=dash: choose_k vive en el dashboard (paso 6), no acá.
  Q5=A: filas con NaN en cualquier feature se descartan. Suficiente data.

Sin I/O excepto `persist_model` + `load_model` (borde con disco).
Los scripts `train_pac_states.py` (paso 5) y `apply_pac_states.py` (paso 7)
orquestan.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import davies_bouldin_score, silhouette_score

from pac.config import (
    ALGORITHM_VERSION_PAC_STATES,
    MODELS_DIR,
    PAC_STATE_PREFIXES,
    PAC_STATES_K_RANGE,
    PAC_STATES_RANDOM_STATE,
    PAC_STATES_SCHEMA_VERSION,
    PAC_STATES_TRAINING_MASK,
    PAC_WINDOW_FEATURES,
)


# ---------------------------------------------------------------------------
# Naming convention (archivos por escala)
# ---------------------------------------------------------------------------
def _paths_for_scale(scale: str, models_dir: Path = MODELS_DIR) -> dict[str, Path]:
    """Mapea scale → paths de los 4 archivos persistentes."""
    if scale not in PAC_STATE_PREFIXES:
        raise ValueError(
            f"Scale desconocida {scale!r}; esperado uno de "
            f"{tuple(PAC_STATE_PREFIXES.keys())}"
        )
    stem = f"pac_states_{scale}"
    return {
        "kmeans_pkl":    models_dir / f"{stem}_kmeans.pkl",
        "zscore_json":   models_dir / f"{stem}_zscore.json",
        "centroids_csv": models_dir / f"{stem}_centroids.csv",
        "metadata_json": models_dir / f"{stem}_metadata.json",
    }


# ---------------------------------------------------------------------------
# Training mask — Q6=C (híbrida)
# ---------------------------------------------------------------------------
def build_training_mask(
    pool: pd.DataFrame,
    mask_spec: dict | None = None,
) -> pd.Series:
    """
    Máscara booleana de training híbrida (Q6=C).

    Regla: `frac_wake ≤ frac_wake_max` AND `coverage ≥ coverage_min`.
    Ventanas con NaN en estos campos se interpretan como fuera del mask.

    Parameters
    ----------
    pool : DataFrame
        Pool de ventanas (debe tener cols frac_wake, coverage).
    mask_spec : dict | None
        Override del default. Keys esperadas: frac_wake_max, coverage_min.
    """
    if mask_spec is None:
        mask_spec = PAC_STATES_TRAINING_MASK

    missing = [c for c in ("frac_wake", "coverage") if c not in pool.columns]
    if missing:
        raise KeyError(f"cols faltantes en pool para training mask: {missing}")

    fw = pd.to_numeric(pool["frac_wake"], errors="coerce")
    cov = pd.to_numeric(pool["coverage"], errors="coerce")
    mask = (fw <= mask_spec["frac_wake_max"]) & (cov >= mask_spec["coverage_min"])
    mask = mask.fillna(False)
    return mask.astype(bool)


# ---------------------------------------------------------------------------
# Feature matrix + z-score
# ---------------------------------------------------------------------------
def build_feature_matrix(
    df: pd.DataFrame,
    feature_cols: list[str] | None = None,
) -> tuple[np.ndarray, pd.Index]:
    """
    Extrae X (n_rows × n_features) de df, descarta filas con NaN (Q5=A),
    devuelve (X, row_index_preservado).

    Raises KeyError si falta alguna feature (contrato estricto).
    """
    if feature_cols is None:
        feature_cols = list(PAC_WINDOW_FEATURES)
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise KeyError(f"features faltantes en df: {missing}")
    sub = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    keep = sub.notna().all(axis=1)
    sub = sub.loc[keep]
    return sub.to_numpy(dtype=float), sub.index


@dataclass
class ZScoreParams:
    """Parámetros de normalización z-score (fit sobre training, apply a cualquier X)."""
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
    """Calcula mean/std por columna. std≈0 se fuerza a 1 para evitar /0."""
    mean = X.mean(axis=0)
    std = X.std(axis=0, ddof=0)
    std = np.where(std < 1e-12, 1.0, std)
    return ZScoreParams(mean=mean, std=std, feature_cols=list(feature_cols))


def apply_zscore(X: np.ndarray, params: ZScoreParams) -> np.ndarray:
    """Aplica (X - mean) / std."""
    return (X - params.mean) / params.std


# ---------------------------------------------------------------------------
# Sort pool (Q2 — reproducibilidad byte-idéntica)
# ---------------------------------------------------------------------------
def sort_pool_for_training(pool: pd.DataFrame) -> pd.DataFrame:
    """
    Ordena el pool por (night_record_id, window_idx) ascendente.

    Indispensable para que fit_kmeans sea byte-reproducible aún si el orden
    de ingesta del pool cambia (caller distinto, paralelismo, etc).
    Si night_record_id no existe, ordena sólo por window_idx.
    """
    sort_cols = []
    if "night_record_id" in pool.columns:
        sort_cols.append("night_record_id")
    if "window_idx" in pool.columns:
        sort_cols.append("window_idx")
    if not sort_cols:
        return pool.reset_index(drop=True)
    return pool.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)


# ---------------------------------------------------------------------------
# K-sweep + fit
# ---------------------------------------------------------------------------
def sweep_k(
    Xz: np.ndarray,
    k_range: list[int] | None = None,
    random_state: int = PAC_STATES_RANDOM_STATE,
    silhouette_sample: int = 5000,
) -> pd.DataFrame:
    """
    Para cada K en k_range, fit KMeans y devuelve métricas (inertia,
    silhouette, davies_bouldin). Output: DataFrame con 1 fila por K.

    `silhouette_sample` subsamplea para acelerar el cálculo; KMeans usa todo.
    """
    if k_range is None:
        k_range = list(PAC_STATES_K_RANGE)
    rng = np.random.default_rng(random_state)

    n = Xz.shape[0]
    if n > silhouette_sample:
        sub_idx = rng.choice(n, size=silhouette_sample, replace=False)
    else:
        sub_idx = np.arange(n)

    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(Xz)
        sil = (
            float(silhouette_score(Xz[sub_idx], labels[sub_idx]))
            if len(np.unique(labels[sub_idx])) > 1
            else float("nan")
        )
        db = (
            float(davies_bouldin_score(Xz, labels))
            if len(np.unique(labels)) > 1
            else float("nan")
        )
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
    random_state: int = PAC_STATES_RANDOM_STATE,
) -> KMeans:
    """Fit KMeans final con K elegido. n_init=10 para estabilidad."""
    km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    km.fit(Xz)
    return km


# ---------------------------------------------------------------------------
# Predict + label mapping int → S{i} / M{i} / L{i}
# ---------------------------------------------------------------------------
def predict_states(model: KMeans, Xz: np.ndarray) -> np.ndarray:
    """Devuelve array de ints (cluster labels)."""
    return model.predict(Xz)


def int_to_state_label(labels_int: np.ndarray | pd.Series, scale: str) -> np.ndarray:
    """Mapea 0,1,2,… → S0,S1,S2,… (o M/L según escala).

    NaN → None (consistente con morphotypes.int_to_greek).
    """
    if scale not in PAC_STATE_PREFIXES:
        raise ValueError(f"Scale desconocida {scale!r}")
    prefix = PAC_STATE_PREFIXES[scale]
    arr = np.asarray(labels_int)
    if arr.size == 0:
        return np.array([], dtype=object)
    out = np.empty(arr.shape, dtype=object)
    for i, v in enumerate(arr):
        if pd.isna(v):
            out[i] = None
        else:
            out[i] = f"{prefix}{int(v)}"
    return out


# ---------------------------------------------------------------------------
# Centroides en espacio original (de-normalizados) para interpretabilidad
# ---------------------------------------------------------------------------
def centroids_original_space(
    model: KMeans,
    zparams: ZScoreParams,
    scale: str,
) -> pd.DataFrame:
    """
    Centroides KMeans (z-space) → espacio original: centroid_z * std + mean.

    Devuelve DataFrame: index = label "S0..Sk-1" (o M/L), cols = feature_cols.
    """
    if scale not in PAC_STATE_PREFIXES:
        raise ValueError(f"Scale desconocida {scale!r}")
    prefix = PAC_STATE_PREFIXES[scale]
    cen_z = model.cluster_centers_
    cen_orig = cen_z * zparams.std + zparams.mean
    labels = [f"{prefix}{i}" for i in range(cen_orig.shape[0])]
    return pd.DataFrame(cen_orig, columns=zparams.feature_cols, index=labels)


# ---------------------------------------------------------------------------
# Persistencia — 4 archivos por escala
# ---------------------------------------------------------------------------
def persist_model(
    model: KMeans,
    zparams: ZScoreParams,
    scale: str,
    *,
    n_training: int,
    k_sweep: pd.DataFrame | None = None,
    models_dir: Path = MODELS_DIR,
) -> dict[str, Path]:
    """
    Escribe los 4 archivos del modelo de una escala:
      - pac_states_{scale}_kmeans.pkl
      - pac_states_{scale}_zscore.json
      - pac_states_{scale}_centroids.csv
      - pac_states_{scale}_metadata.json
    """
    paths = _paths_for_scale(scale, models_dir=models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. Pickle del modelo.
    with open(paths["kmeans_pkl"], "wb") as f:
        pickle.dump(model, f)

    # 2. Z-score JSON.
    with open(paths["zscore_json"], "w", encoding="utf-8") as f:
        json.dump(zparams.to_dict(), f, indent=2)

    # 3. Centroides en espacio original.
    cen = centroids_original_space(model, zparams, scale)
    cen = cen.copy()
    cen.index.name = "state"
    cen.to_csv(paths["centroids_csv"])

    # 4. Metadata JSON.
    meta = {
        "algorithm_version": ALGORITHM_VERSION_PAC_STATES,
        "schema_version": PAC_STATES_SCHEMA_VERSION,
        "scale": scale,
        "k": int(model.n_clusters),
        "feature_cols": list(zparams.feature_cols),
        "n_training": int(n_training),
        "random_state": int(PAC_STATES_RANDOM_STATE),
        "state_labels": [f"{PAC_STATE_PREFIXES[scale]}{i}" for i in range(model.n_clusters)],
        "training_mask": dict(PAC_STATES_TRAINING_MASK),
        "inertia_final": float(model.inertia_),
    }
    if k_sweep is not None:
        meta["k_sweep"] = k_sweep.to_dict(orient="records")
    with open(paths["metadata_json"], "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return paths


def load_model(
    scale: str,
    models_dir: Path = MODELS_DIR,
) -> tuple[KMeans, ZScoreParams, dict]:
    """Carga (model, zparams, metadata) para una escala."""
    paths = _paths_for_scale(scale, models_dir=models_dir)
    with open(paths["kmeans_pkl"], "rb") as f:
        model = pickle.load(f)
    with open(paths["zscore_json"], "r", encoding="utf-8") as f:
        zparams = ZScoreParams.from_dict(json.load(f))
    with open(paths["metadata_json"], "r", encoding="utf-8") as f:
        meta = json.load(f)
    return model, zparams, meta
