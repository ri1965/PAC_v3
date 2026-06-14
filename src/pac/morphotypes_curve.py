"""
PAC_v2 — Morphotyping basado en forma de curva SpO2 (curve-based).

Complementa morphotypes.py (que usa 10 features escalares → α/β/γ/δ).
Este módulo clasifica EDOs por la FORMA de su curva SpO2 de 30 puntos
normalizados en tiempo [0%..100%] del evento.

Resultado: columna `morphotype_curve` ∈ {"C1","C2","C3","C4","C5"}
  C1 — Subcrítico       (nadir ~−1.7%, mínima respuesta)
  C2 — Leve/Gradual     (nadir ~−3.8%, caída tardía, sin recuperar)
  C3 — Moderado V       (nadir ~−7.9%, V simétrica, nadir precoz, recuperación completa)
  C4 — Severo Agudo     (nadir ~−8.5%, ya desaturado al inicio, sin recuperación)
  C5 — Severo Progresivo (nadir ~−15.2%, profundo, sin recuperar)

Convenciones (idénticas a morphotypes.py):
  - train_morphotypes_curve.py  → ajusta el modelo y persiste
  - apply_morphotypes_curve.py  → añade `morphotype_curve` a {NR}_edos.parquet
  - models/edo_morphotype_curve_*.{pkl,npy,csv,json}

Sin z-score: las curvas están en unidades comparables (ΔSpO2 %)
→ la distancia euclidiana en espacio original es directamente interpretable.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.cluster import KMeans

from pac.config import EVENTS_DIR, MODELS_DIR


# ── Constantes del módulo ──────────────────────────────────────────────────
CURVE_N_POINTS: int = 30
CURVE_K: int = 5
CURVE_LABELS: list[str] = ["C1", "C2", "C3", "C4", "C5"]
CURVE_ALGORITHM_VERSION: str = "pac_v2_morphotypes_curve_1.0.0"
CURVE_SCHEMA_VERSION: str = "1"
CURVE_TRAINING_FILTER: dict = {
    "duration_s_max": 180,
    "in_quality_night": True,
}

# Paths de artefactos en models/
CURVE_KMEANS_PKL     = MODELS_DIR / "edo_morphotype_curve_kmeans.pkl"
CURVE_CENTROIDS_NPY  = MODELS_DIR / "edo_morphotype_curve_centroids.npy"
CURVE_CENTROIDS_CSV  = MODELS_DIR / "edo_morphotype_curve_centroids.csv"
CURVE_METADATA_JSON  = MODELS_DIR / "edo_morphotype_curve_metadata.json"


# ── Extracción de features ────────────────────────────────────────────────
def build_curve_matrix(
    curves_df: pd.DataFrame,
    edos_df: pd.DataFrame,
) -> tuple[np.ndarray, pd.Index]:
    """
    Construye la matriz X de ΔSpO2 (N × 30) uniendo curvas y baseline.

    Parámetros
    ----------
    curves_df : DataFrame con columnas [night_record_id, ts_start, spo2_curve]
    edos_df   : DataFrame con columnas [night_record_id, ts_start, baseline_spo2,
                                        duration_s]

    Retorna
    -------
    X         : ndarray (N, 30) — curvas ΔSpO2 respecto a baseline
    valid_idx : índice pandas de las filas válidas (sin NaN, duración ≤ 180s)
    """
    merged = curves_df[["night_record_id", "ts_start", "spo2_curve"]].merge(
        edos_df[["night_record_id", "ts_start", "baseline_spo2", "duration_s"]],
        on=["night_record_id", "ts_start"],
        how="inner",
    )

    # Filtro de duración
    merged = merged[merged["duration_s"] <= CURVE_TRAINING_FILTER["duration_s_max"]].copy()

    # Convertir listas/arrays a ndarray
    curves = np.stack(merged["spo2_curve"].values)          # (N, 30)
    baseline = merged["baseline_spo2"].values.reshape(-1, 1) # (N, 1)
    X = curves - baseline                                    # ΔSpO2

    # Filas con NaN
    valid_mask = ~np.isnan(X).any(axis=1)
    return X[valid_mask], merged.index[valid_mask]


def build_curve_matrix_from_night(
    nr_id: str,
    events_dir: Path = EVENTS_DIR,
) -> tuple[np.ndarray, pd.DataFrame] | tuple[None, None]:
    """
    Carga curvas y edos de UNA noche y devuelve (X_delta, merged_df).
    Retorna (None, None) si no hay archivos o están vacíos.
    """
    curves_path = events_dir / f"{nr_id}_edo_curves.parquet"
    edos_path   = events_dir / f"{nr_id}_edos.parquet"
    if not curves_path.exists() or not edos_path.exists():
        return None, None

    curves_df = pq.read_table(curves_path).to_pandas()
    edos_df   = pq.read_table(edos_path).to_pandas()
    if curves_df.empty or edos_df.empty:
        return None, None

    merged = curves_df[["night_record_id", "ts_start", "spo2_curve"]].merge(
        edos_df[["night_record_id", "ts_start", "baseline_spo2", "duration_s"]],
        on=["night_record_id", "ts_start"],
        how="inner",
    )
    if merged.empty:
        return None, None

    curves  = np.stack(merged["spo2_curve"].values)
    baseline = merged["baseline_spo2"].values.reshape(-1, 1)
    X = curves - baseline
    return X, merged


# ── Training ──────────────────────────────────────────────────────────────
def fit_curve_kmeans(
    X: np.ndarray,
    k: int = CURVE_K,
    random_state: int = 42,
    n_init: int = 20,
) -> KMeans:
    """
    Ajusta KMeans sobre X (N × 30).

    Los centroides se reordenan post-fit de menos severo (C1) a más severo (C5)
    según el nadir (valor mínimo) de la curva centroide.
    """
    km = KMeans(n_clusters=k, random_state=random_state, n_init=n_init)
    labels_raw = km.fit_predict(X)

    # Reordenar: menor nadir (menos negativo) = C1 → mayor nadir (más negativo) = C5
    centers = km.cluster_centers_
    depth   = [c.min() for c in centers]
    order   = np.argsort(depth)[::-1]   # descending de profundidad
    remap   = {old: new for new, old in enumerate(order)}
    labels_sorted = np.array([remap[l] for l in labels_raw])

    km.cluster_centers_ = centers[order]
    km.labels_          = labels_sorted
    return km


# ── Predicción ────────────────────────────────────────────────────────────
def predict_curve_cluster(
    model: KMeans,
    X: np.ndarray,
) -> np.ndarray:
    """
    Asigna cada fila de X al cluster más cercano (distancia euclidiana).
    Retorna array de strings "C1".."C5".
    """
    labels_int = model.predict(X)
    return np.array([CURVE_LABELS[i] for i in labels_int], dtype=object)


# ── Persistencia ──────────────────────────────────────────────────────────
def persist_curve_model(
    model: KMeans,
    n_training: int,
    models_dir: Path = MODELS_DIR,
) -> dict[str, Path]:
    """
    Escribe 4 artefactos en models/:
      - edo_morphotype_curve_kmeans.pkl
      - edo_morphotype_curve_centroids.npy   (k × 30)
      - edo_morphotype_curve_centroids.csv   (legible)
      - edo_morphotype_curve_metadata.json
    """
    models_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # 1. Pickle
    with open(models_dir / CURVE_KMEANS_PKL.name, "wb") as f:
        pickle.dump(model, f)
    paths["kmeans_pkl"] = models_dir / CURVE_KMEANS_PKL.name

    # 2. Centroides npy
    np.save(models_dir / CURVE_CENTROIDS_NPY.name, model.cluster_centers_)
    paths["centroids_npy"] = models_dir / CURVE_CENTROIDS_NPY.name

    # 3. Centroides csv
    t = np.linspace(0, 100, CURVE_N_POINTS)
    cent_df = pd.DataFrame(
        model.cluster_centers_,
        index=CURVE_LABELS[: model.n_clusters],
        columns=[f"pt_{i:02d}" for i in range(CURVE_N_POINTS)],
    )
    cent_df.index.name = "cluster"
    cent_df.to_csv(models_dir / CURVE_CENTROIDS_CSV.name)
    paths["centroids_csv"] = models_dir / CURVE_CENTROIDS_CSV.name

    # 4. Metadata
    centers = model.cluster_centers_
    meta = {
        "algorithm_version": CURVE_ALGORITHM_VERSION,
        "schema_version": CURVE_SCHEMA_VERSION,
        "k": int(model.n_clusters),
        "cluster_labels": CURVE_LABELS[: model.n_clusters],
        "feature_space": "spo2_delta_curve_30pt",
        "feature_description": (
            "Delta SpO2 vs baseline del evento, interpolado a 30 puntos "
            "de tiempo normalizado [0%..100%] del evento."
        ),
        "normalization": "none",
        "ordering": "C1=menos severo → C5=más severo (por nadir de centroide)",
        "n_training": int(n_training),
        "training_filter": CURVE_TRAINING_FILTER,
        "random_state": 42,
        "inertia_final": float(model.inertia_),
        "cluster_stats": [
            {
                "label": CURVE_LABELS[ci],
                "nadir_spo2_delta": round(float(centers[ci].min()), 3),
                "nadir_position_pct": round(float(t[np.argmin(centers[ci])]), 1),
            }
            for ci in range(model.n_clusters)
        ],
    }
    with open(models_dir / CURVE_METADATA_JSON.name, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    paths["metadata_json"] = models_dir / CURVE_METADATA_JSON.name

    return paths


def load_curve_model(
    models_dir: Path = MODELS_DIR,
) -> tuple[KMeans, dict]:
    """Carga modelo + metadata desde disco."""
    with open(models_dir / CURVE_KMEANS_PKL.name, "rb") as f:
        model = pickle.load(f)
    with open(models_dir / CURVE_METADATA_JSON.name, "r", encoding="utf-8") as f:
        meta = json.load(f)
    return model, meta
