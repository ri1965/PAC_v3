"""
PAC_v2 — Etapa 3b paso 4: entrenamiento del modelo de morphotyping.

Pipeline:
  1. Consolida el pool de EDOs (~78k desde events/*_edos.parquet).
  2. Aplica máscara de training (in_sleep & ~near_gap & meets_3pct).
  3. Build feature matrix (10 cols, Q1=B: morfología + IRD).
  4. Fit z-score sobre training subset.
  5. Sweep K=2..10 con inertia + silhouette + Davies-Bouldin.
  6. Elige K con choose_k() (override manual vía CLI --k).
  7. Fit KMeans final.
  8. Persist: models/edo_morphotype_{kmeans.pkl, zscore.json, centroids.csv,
     metadata.json}.
  9. Escribe reports/morphotypes_training_report.json + interpretability.md.

Corre:  PYTHONPATH=src python scripts/train_morphotypes.py
        PYTHONPATH=src python scripts/train_morphotypes.py --k 4
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import pandas as pd

from pac import morphotypes as mt
from pac.config import (
    ALGORITHM_VERSION_MORPHOTYPES,
    EVENTS_DIR,
    MODELS_DIR,
    MORPHOTYPE_FEATURES,
    MORPHOTYPE_K_RANGE,
    MORPHOTYPE_RANDOM_STATE,
    MORPHOTYPE_TRAINING_MASK,
    REPORTS_DIR,
)


TRAINING_REPORT_JSON = REPORTS_DIR / "morphotypes_training_report.json"
INTERPRETABILITY_MD  = REPORTS_DIR / "morphotypes_interpretability.md"


def _interpretability_md(
    centroids: pd.DataFrame,
    cluster_sizes: pd.Series,
    meets_composition: pd.DataFrame,
    k_chosen: int,
    sweep: pd.DataFrame,
) -> str:
    """Genera un markdown de interpretabilidad a partir de los centroides."""
    lines = []
    lines.append("# Etapa 3b — Morphotype interpretability\n")
    lines.append(
        f"_Generado {datetime.now().isoformat(timespec='seconds')} · "
        f"K={k_chosen} · algorithm={ALGORITHM_VERSION_MORPHOTYPES}_\n"
    )
    lines.append("## Centroides en espacio original\n")
    lines.append(
        "Cada fila es el valor promedio de la feature en el centro del cluster "
        "(de-normalizado desde z-space).\n"
    )
    lines.append(centroids.round(3).to_markdown())
    lines.append("\n\n## Tamaño de cada cluster (EDOs de training)\n")
    sizes_df = cluster_sizes.to_frame("n_training")
    sizes_df["pct"] = (sizes_df["n_training"] / sizes_df["n_training"].sum() * 100).round(2)
    lines.append(sizes_df.to_markdown())
    lines.append("\n\n## Composición por `meets_Npct` (fracción de EDOs de training)\n")
    lines.append(meets_composition.round(3).to_markdown())
    lines.append("\n\n## K-sweep\n")
    lines.append(sweep.round(4).to_markdown(index=False))
    lines.append("\n\n## Descripción post-hoc (rellenar manualmente tras inspeccionar centroides)\n")
    for letter in centroids.index:
        lines.append(f"- **{letter}**: _descripción_\n")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train EDO morphotypes (Etapa 3b)")
    parser.add_argument(
        "--k", type=int, default=None,
        help="K manual. Si se omite, usa choose_k() sobre el sweep."
    )
    parser.add_argument(
        "--k-range", type=int, nargs="+", default=None,
        help=f"Override del k_range default {list(MORPHOTYPE_K_RANGE)}."
    )
    args = parser.parse_args()
    k_range = args.k_range or list(MORPHOTYPE_K_RANGE)

    print("[train] consolidando pool de EDOs …")
    pool = mt.load_edo_pool(EVENTS_DIR)
    print(f"         pool: {len(pool)} EDOs desde {pool['night_record_id'].nunique()} noches")

    # 1. Training mask.
    mask = mt.build_training_mask(pool, MORPHOTYPE_TRAINING_MASK)
    train_df = pool.loc[mask].reset_index(drop=True)
    print(f"         training universe (canónicos): {len(train_df)} EDOs "
          f"({100.0 * len(train_df)/len(pool):.1f}% del pool)")
    if len(train_df) < 100:
        raise RuntimeError(f"Training set demasiado chico ({len(train_df)} EDOs)")

    # 2. Feature matrix + z-score.
    X, kept_idx = mt.build_feature_matrix(train_df, list(MORPHOTYPE_FEATURES))
    print(f"         feature matrix: {X.shape} (tras drop de NaN)")
    zparams = mt.fit_zscore(X, list(MORPHOTYPE_FEATURES))
    Xz = mt.apply_zscore(X, zparams)

    # 3. Sweep K.
    print(f"[train] sweep K en {k_range} …")
    sweep = mt.sweep_k(Xz, k_range=k_range, random_state=MORPHOTYPE_RANDOM_STATE)
    print(sweep.to_string(index=False))

    # 4. Elegir K (manual o heurístico).
    if args.k is not None:
        k_final = int(args.k)
        print(f"[train] K manual → K={k_final}")
    else:
        k_final = mt.choose_k(sweep)
        print(f"[train] K elegido por heurística (silhouette - 0.5*DB_norm) → K={k_final}")

    # 5. Fit final.
    model = mt.fit_kmeans(Xz, k=k_final, random_state=MORPHOTYPE_RANDOM_STATE)
    labels_int = model.predict(Xz)
    labels_greek = mt.int_to_greek(labels_int)

    # 6. Interpretabilidad: centroides, sizes, composición meets_Npct.
    centroids = mt.centroids_original_space(model, zparams)

    labeled_train = train_df.iloc[kept_idx].reset_index(drop=True).copy()
    labeled_train["morphotype"] = labels_greek

    cluster_sizes = labeled_train.groupby("morphotype").size().rename("n").sort_index()

    meets_cols = [c for c in ("meets_2pct", "meets_3pct", "meets_4pct", "meets_5pct")
                  if c in labeled_train.columns]
    meets_comp = labeled_train.groupby("morphotype")[meets_cols].mean()

    # 7. Persist artefactos del modelo.
    print(f"[train] persistiendo modelo en {MODELS_DIR} …")
    paths = mt.persist_model(
        model, zparams,
        k_sweep=sweep,
        n_training=int(X.shape[0]),
        models_dir=MODELS_DIR,
    )
    for k, v in paths.items():
        print(f"         {k}: {v.name}")

    # 8. Reports.
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "algorithm_version": ALGORITHM_VERSION_MORPHOTYPES,
        "training_mask": dict(MORPHOTYPE_TRAINING_MASK),
        "pool_size": int(len(pool)),
        "training_size": int(X.shape[0]),
        "feature_cols": list(MORPHOTYPE_FEATURES),
        "k_range": list(k_range),
        "k_chosen": int(k_final),
        "k_sweep": sweep.to_dict(orient="records"),
        "centroids_original_space": centroids.round(6).to_dict(orient="index"),
        "cluster_sizes_training": cluster_sizes.to_dict(),
        "meets_composition_training": meets_comp.round(6).to_dict(orient="index"),
        "random_state": int(MORPHOTYPE_RANDOM_STATE),
    }
    with open(TRAINING_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"         JSON report: {TRAINING_REPORT_JSON.name}")

    md = _interpretability_md(
        centroids=centroids,
        cluster_sizes=cluster_sizes,
        meets_composition=meets_comp,
        k_chosen=k_final,
        sweep=sweep,
    )
    with open(INTERPRETABILITY_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"         MD interpretability: {INTERPRETABILITY_MD.name}")

    print()
    print(f"[train] DONE — K={k_final} · silhouette="
          f"{sweep.loc[sweep['k']==k_final, 'silhouette'].iloc[0]} · "
          f"DB={sweep.loc[sweep['k']==k_final, 'davies_bouldin'].iloc[0]}")


if __name__ == "__main__":
    main()
