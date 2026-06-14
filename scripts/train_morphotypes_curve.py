"""
PAC_v2 — Train morphotype_curve model (shape-based, k=5).

Ajusta KMeans sobre las curvas SpO2 de 30 puntos (ΔSpO2 vs baseline),
reordena clusters de C1=leve a C5=crítico y persiste en models/.

Diferencias vs train_morphotypes.py:
  - Features: curva SpO2 de 30 puntos (no features escalares)
  - Sin z-score (unidades ya comparables: ΔSpO2 %)
  - k=5 (óptimo por silhouette sobre curvas de forma)
  - Output: `morphotype_curve` ∈ {"C1","C2","C3","C4","C5"}

Uso:
  PYTHONPATH=src python scripts/train_morphotypes_curve.py
  PYTHONPATH=src python scripts/train_morphotypes_curve.py --k 5 --n-init 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pac import morphotypes_curve as mc  # noqa: E402
from pac.config import EVENTS_DIR, MODELS_DIR, REPORTS_DIR  # noqa: E402


TRAINING_REPORT_JSON = REPORTS_DIR / "morphotypes_curve_training_report.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train curve-based morphotype model (Etapa 3c)"
    )
    parser.add_argument("--k", type=int, default=mc.CURVE_K,
                        help=f"Número de clusters (default: {mc.CURVE_K})")
    parser.add_argument("--n-init", type=int, default=20,
                        help="n_init para KMeans (default: 20)")
    parser.add_argument("--quality-only", action="store_true", default=True,
                        help="Usar solo noches de calidad (default: True)")
    args = parser.parse_args()

    print("=" * 60)
    print("PAC_v2 — train_morphotypes_curve")
    print(f"k={args.k}  n_init={args.n_init}")
    print("=" * 60)

    # ── 1. Cargar pool de curvas ──────────────────────────────────────────
    print("\n[1] Cargando pool de curvas...")
    t0 = time.time()

    curve_paths = sorted(EVENTS_DIR.glob("NR_*_edo_curves.parquet"))
    edos_paths  = {p.stem.replace("_edos", ""): p
                   for p in sorted(EVENTS_DIR.glob("NR_*_edos.parquet"))}

    all_curves, all_baselines, all_durations = [], [], []
    n_nights_ok, n_nights_fail = 0, 0

    for cp in curve_paths:
        nr_id = cp.stem.replace("_edo_curves", "")
        ep = edos_paths.get(nr_id)
        if ep is None:
            n_nights_fail += 1
            continue
        try:
            curves_df = pd.read_parquet(cp)[["night_record_id","ts_start","spo2_curve"]]
            edos_df   = pd.read_parquet(ep)[["night_record_id","ts_start",
                                              "baseline_spo2","duration_s"]]
            merged = curves_df.merge(edos_df, on=["night_record_id","ts_start"])
            if merged.empty:
                continue
            stacked = np.stack(merged["spo2_curve"].values)
            all_curves.append(stacked)
            all_baselines.append(merged["baseline_spo2"].values)
            all_durations.append(merged["duration_s"].values)
            n_nights_ok += 1
        except Exception as e:
            print(f"  WARN {nr_id}: {e}")
            n_nights_fail += 1

    if not all_curves:
        print("ERROR: no se pudieron cargar curvas.")
        sys.exit(1)

    curves_all   = np.vstack(all_curves)
    baseline_all = np.concatenate(all_baselines).reshape(-1, 1)
    duration_all = np.concatenate(all_durations)

    print(f"  Noches OK: {n_nights_ok}  |  FAIL: {n_nights_fail}")
    print(f"  EDOs totales: {len(curves_all):,}")

    # ── 2. Construir X (ΔSpO2) y aplicar filtros ─────────────────────────
    print("\n[2] Construyendo X (ΔSpO2) y filtrando...")
    X_all = curves_all - baseline_all
    dur_mask  = duration_all <= mc.CURVE_TRAINING_FILTER["duration_s_max"]
    nan_mask  = ~np.isnan(X_all).any(axis=1)
    train_mask = dur_mask & nan_mask
    X = X_all[train_mask]
    print(f"  X training: {X.shape}  "
          f"(excluidos {(~train_mask).sum():,} por duration>180s o NaN)")

    # ── 3. Sweep silhouette (rápido, subsample) ───────────────────────────
    print("\n[3] Sweep k=2..7 (subsample 6000)...")
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.metrics import silhouette_score, davies_bouldin_score
    rng = np.random.default_rng(42)
    idx_sub = rng.choice(len(X), min(6000, len(X)), replace=False)
    X_sub = X[idx_sub]

    sweep_rows = []
    for k in range(2, 8):
        km_tmp = MiniBatchKMeans(n_clusters=k, random_state=42, n_init=5, batch_size=2000)
        labs = km_tmp.fit_predict(X_sub)
        sil = silhouette_score(X_sub, labs, sample_size=3000, random_state=42)
        db  = davies_bouldin_score(X_sub, labs)
        sweep_rows.append({"k": k, "silhouette": round(sil, 4), "davies_bouldin": round(db, 4)})
        print(f"  k={k}: silhouette={sil:.4f}  DB={db:.4f}")
    sweep_df = pd.DataFrame(sweep_rows)

    # ── 4. Fit KMeans final ───────────────────────────────────────────────
    print(f"\n[4] Ajustando KMeans final k={args.k}, n_init={args.n_init}...")
    model = mc.fit_curve_kmeans(X, k=args.k,
                                 random_state=42, n_init=args.n_init)
    print(f"  Inertia: {model.inertia_:.1f}  |  n_iter: {model.n_iter_}")

    centers = model.cluster_centers_
    t_pct = np.linspace(0, 100, mc.CURVE_N_POINTS)
    print("\n  Clusters (C1=leve → C5=crítico):")
    for ci in range(args.k):
        mn = centers[ci]
        n  = int((model.labels_ == ci).sum())
        print(f"    C{ci+1}: nadir={mn.min():.2f}%  "
              f"pos={t_pct[np.argmin(mn)]:.0f}%  n={n:,}")

    # ── 5. Persistir ──────────────────────────────────────────────────────
    print(f"\n[5] Persistiendo en {MODELS_DIR}...")
    paths = mc.persist_curve_model(model, n_training=int(len(X)), models_dir=MODELS_DIR)
    for name, path in paths.items():
        print(f"  {name}: {path.name}")

    # ── 6. Training report ────────────────────────────────────────────────
    elapsed = time.time() - t0
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "algorithm_version": mc.CURVE_ALGORITHM_VERSION,
        "k_chosen": args.k,
        "n_init": args.n_init,
        "n_training": int(len(X)),
        "n_nights_ok": n_nights_ok,
        "inertia_final": float(model.inertia_),
        "elapsed_s": round(elapsed, 2),
        "k_sweep": sweep_df.to_dict(orient="records"),
        "cluster_stats": [
            {
                "label": mc.CURVE_LABELS[ci],
                "n": int((model.labels_ == ci).sum()),
                "pct": round(100 * (model.labels_ == ci).mean(), 2),
                "nadir_spo2_delta": round(float(centers[ci].min()), 3),
                "nadir_position_pct": round(float(t_pct[np.argmin(centers[ci])]), 1),
            }
            for ci in range(args.k)
        ],
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(TRAINING_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n  Training report: {TRAINING_REPORT_JSON.name}")
    print(f"\n[DONE] {elapsed:.1f}s — modelo listo para apply_morphotypes_curve.py")


if __name__ == "__main__":
    main()
