"""
PAC_v2 — Etapa 4 paso 5: entrenamiento de estados PAC (KMeans por escala).

Dos modos:
  --mode sweep   : corre el sweep K=2..10 por escala, persiste métricas en
                   reports/pac_states_sweep.json. NO persiste modelos.
                   (Inspeccionar dashboard del paso 6 y elegir K por escala.)

  --mode final   : fit final con K dado, persiste 4 archivos por escala
                   en models/ + reports/pac_states_training_report.json
                   + reports/pac_states_batch_gate.json.

Pipeline (común a ambos modos):
  1. Iterar 560 silver/{NR}.parquet + events/{NR}_edos.parquet.
  2. Por escala s/m/l, llamar windows.build_windows_for_night → pool.
  3. Aplicar states.build_training_mask (frac_wake ≤ 0.5 AND coverage ≥ 0.5).
  4. Sort pool (reproducibilidad byte-idéntica).
  5. Build feature matrix → fit_zscore → apply_zscore.
  6. Sweep K (siempre en sweep; opcional en final).
  7. Sólo en final: fit_kmeans con K elegido + persist_model.

Corre:
  PYTHONPATH=src python scripts/train_pac_states.py --mode sweep --limit 20
  PYTHONPATH=src python scripts/train_pac_states.py --mode sweep
  PYTHONPATH=src python scripts/train_pac_states.py --mode final --k-s 7 --k-m 6 --k-l 4
"""
from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pac import states as st
from pac import windows as wn
from pac.config import (
    ALGORITHM_VERSION_PAC_STATES,
    EVENTS_DIR,
    MODELS_DIR,
    PAC_STATE_SCALES,
    PAC_STATES_HISTORICAL_K,
    PAC_STATES_K_RANGE,
    PAC_STATES_RANDOM_STATE,
    PAC_STATES_SCHEMA_VERSION,
    PAC_STATES_TRAINING_MASK,
    PAC_WINDOW_FEATURES,
    REPORTS_DIR,
    SILVER_DIR,
)


SWEEP_REPORT_JSON = REPORTS_DIR / "pac_states_sweep.json"
TRAINING_REPORT_JSON = REPORTS_DIR / "pac_states_training_report.json"
BATCH_GATE_JSON = REPORTS_DIR / "pac_states_batch_gate.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Etapa 4 paso 5 — trainer de estados PAC",
    )
    p.add_argument(
        "--mode",
        choices=["sweep", "final"],
        required=True,
        help="sweep = sólo métricas; final = fit + persist modelo.",
    )
    p.add_argument(
        "--limit", type=int, default=None,
        help="Smoke test: procesar sólo las primeras N noches.",
    )
    p.add_argument(
        "--scales", type=str, default="s,m,l",
        help="Escalas a entrenar (coma-separadas). Default: s,m,l.",
    )
    p.add_argument("--k-s", type=int, default=PAC_STATES_HISTORICAL_K["s"])
    p.add_argument("--k-m", type=int, default=PAC_STATES_HISTORICAL_K["m"])
    p.add_argument("--k-l", type=int, default=PAC_STATES_HISTORICAL_K["l"])
    p.add_argument(
        "--no-sweep", action="store_true",
        help="En modo final, skippear sweep (acelera).",
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Pool de ventanas (memoria)
# ---------------------------------------------------------------------------
def build_pool(
    silver_paths: list[Path],
    scales: list[str],
    verbose: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Itera sobre silver/*.parquet, construye ventanas por escala y concatena.

    Returns
    -------
    dict {scale: DataFrame con 31 cols + night_record_id}
    """
    buckets: dict[str, list[pd.DataFrame]] = defaultdict(list)
    n_skipped = 0
    for i, sp in enumerate(silver_paths, start=1):
        nr = sp.stem
        ep = EVENTS_DIR / f"{nr}_edos.parquet"
        try:
            silver_df = pd.read_parquet(sp)
            edos_df = pd.read_parquet(ep) if ep.exists() else pd.DataFrame(
                columns=["ts_start", "morphotype", "ird_event"]
            )
        except Exception as e:
            n_skipped += 1
            if verbose:
                print(f"  [SKIP {i}/{len(silver_paths)}] {nr}: {e}")
            continue

        for scale in scales:
            w = wn.build_windows_for_night(silver_df, edos_df, scale)
            if len(w) == 0:
                continue
            w = w.copy()
            w.insert(0, "night_record_id", nr)
            buckets[scale].append(w)

        if verbose or i % 50 == 0 or i == len(silver_paths):
            print(f"  [{i:4d}/{len(silver_paths)}] {nr}: windows "
                  f"s={len(buckets['s'][-1]) if buckets['s'] else 0} · "
                  f"m={len(buckets['m'][-1]) if buckets['m'] else 0} · "
                  f"l={len(buckets['l'][-1]) if buckets['l'] else 0}")

    pool: dict[str, pd.DataFrame] = {}
    for scale in scales:
        if not buckets[scale]:
            pool[scale] = pd.DataFrame()
        else:
            pool[scale] = pd.concat(buckets[scale], ignore_index=True)

    if n_skipped:
        print(f"[train] {n_skipped} noches skippeadas por error de lectura.")
    return pool


# ---------------------------------------------------------------------------
# Sweep / final por escala
# ---------------------------------------------------------------------------
def train_scale(
    scale: str,
    pool_scale: pd.DataFrame,
    *,
    mode: str,
    k_final: int,
    do_sweep: bool,
) -> dict:
    """
    Entrena una escala. Persiste modelo si mode='final'.

    Returns
    -------
    dict con resumen (n_pool, n_training, k_sweep records, k_chosen, ...).
    """
    result: dict = {
        "scale": scale,
        "n_pool": int(len(pool_scale)),
    }

    if len(pool_scale) == 0:
        raise RuntimeError(f"Pool vacío para escala {scale!r}")

    # 1. Training mask + sort (byte-reproducibilidad).
    mask = st.build_training_mask(pool_scale)
    train_df = pool_scale.loc[mask].copy()
    train_df = st.sort_pool_for_training(train_df)
    result["n_training"] = int(len(train_df))
    result["frac_training_from_pool"] = round(len(train_df) / len(pool_scale), 4)

    if len(train_df) < 50:
        raise RuntimeError(
            f"Training set chico para escala {scale!r}: {len(train_df)} ventanas"
        )

    # 2. Feature matrix + z-score.
    X, kept_idx = st.build_feature_matrix(train_df, list(PAC_WINDOW_FEATURES))
    result["n_training_after_nan_drop"] = int(X.shape[0])
    zparams = st.fit_zscore(X, list(PAC_WINDOW_FEATURES))
    Xz = st.apply_zscore(X, zparams)

    # 3. Sweep K (siempre en sweep, opcional en final).
    sweep_df = None
    if do_sweep:
        print(f"  [{scale}] sweep K en {PAC_STATES_K_RANGE} sobre {X.shape[0]} ventanas …")
        sweep_df = st.sweep_k(
            Xz, k_range=PAC_STATES_K_RANGE, random_state=PAC_STATES_RANDOM_STATE,
        )
        print(sweep_df.to_string(index=False))
        result["k_sweep"] = sweep_df.to_dict(orient="records")

    # 4. Fit final sólo en modo 'final'.
    if mode == "final":
        print(f"  [{scale}] fit final K={k_final} (ancla histórica={PAC_STATES_HISTORICAL_K[scale]})")
        model = st.fit_kmeans(Xz, k=k_final, random_state=PAC_STATES_RANDOM_STATE)
        result["k_chosen"] = int(k_final)
        result["inertia_final"] = float(model.inertia_)

        # Distribución de labels en training.
        labels_int = model.predict(Xz)
        label_names = st.int_to_state_label(labels_int, scale=scale)
        unique, counts = np.unique(label_names, return_counts=True)
        result["cluster_sizes_training"] = {
            str(u): int(c) for u, c in zip(unique, counts)
        }

        # Persist (4 archivos).
        paths = st.persist_model(
            model, zparams, scale=scale,
            n_training=int(X.shape[0]),
            k_sweep=sweep_df,
            models_dir=MODELS_DIR,
        )
        result["persisted"] = {k: str(v.name) for k, v in paths.items()}

        # Centroides interpretables (en espacio original).
        cen = st.centroids_original_space(model, zparams, scale=scale)
        result["centroids_original_space"] = cen.round(4).to_dict(orient="index")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    scales = [s.strip() for s in args.scales.split(",") if s.strip()]
    unknown = [s for s in scales if s not in PAC_STATE_SCALES]
    if unknown:
        raise ValueError(f"Escalas desconocidas: {unknown}")

    k_per_scale = {"s": args.k_s, "m": args.k_m, "l": args.k_l}

    print(f"[train-pac] mode={args.mode} · scales={scales}")
    if args.mode == "final":
        chosen = {s: k_per_scale[s] for s in scales}
        print(f"[train-pac] K por escala (final): {chosen}")

    # 1. Listar silver (excluyendo _qc).
    silver_paths = sorted(
        p for p in SILVER_DIR.glob("NR_*.parquet")
        if not p.stem.endswith("_qc")
    )
    if args.limit:
        silver_paths = silver_paths[: args.limit]
    print(f"[train-pac] procesando {len(silver_paths)} noches …")

    # 2. Construir pool de ventanas.
    t0 = time.time()
    pool = build_pool(silver_paths, scales, verbose=args.verbose)
    elapsed_pool = time.time() - t0
    for scale in scales:
        print(f"[train-pac] pool[{scale}]: {len(pool[scale])} ventanas")
    print(f"[train-pac] pool built en {elapsed_pool:.1f}s")

    # 3. Entrenar por escala.
    do_sweep = (args.mode == "sweep") or (not args.no_sweep)
    results: dict[str, dict] = {}
    t0 = time.time()
    for scale in scales:
        print()
        print(f"=== Escala {scale!r} ===")
        try:
            r = train_scale(
                scale, pool[scale],
                mode=args.mode,
                k_final=k_per_scale[scale],
                do_sweep=do_sweep,
            )
            results[scale] = r
        except Exception as e:
            print(f"  [{scale}] ERROR: {e}")
            results[scale] = {"scale": scale, "error": str(e)}
    elapsed_train = time.time() - t0

    # 4. Reports.
    timestamp = datetime.now().isoformat(timespec="seconds")

    if args.mode == "sweep":
        report = {
            "timestamp": timestamp,
            "mode": "sweep",
            "n_nights": len(silver_paths),
            "scales": scales,
            "random_state": PAC_STATES_RANDOM_STATE,
            "k_range": PAC_STATES_K_RANGE,
            "training_mask": dict(PAC_STATES_TRAINING_MASK),
            "historical_k": PAC_STATES_HISTORICAL_K,
            "elapsed_pool_s": round(elapsed_pool, 1),
            "elapsed_train_s": round(elapsed_train, 1),
            "by_scale": results,
        }
        with open(SWEEP_REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[train-pac] sweep report: {SWEEP_REPORT_JSON.name}")

    else:  # mode == final
        all_ok = all("error" not in r for r in results.values())
        report = {
            "timestamp": timestamp,
            "mode": "final",
            "algorithm_version": ALGORITHM_VERSION_PAC_STATES,
            "schema_version": PAC_STATES_SCHEMA_VERSION,
            "n_nights": len(silver_paths),
            "scales": scales,
            "k_chosen": {s: k_per_scale[s] for s in scales},
            "random_state": PAC_STATES_RANDOM_STATE,
            "training_mask": dict(PAC_STATES_TRAINING_MASK),
            "elapsed_pool_s": round(elapsed_pool, 1),
            "elapsed_train_s": round(elapsed_train, 1),
            "by_scale": results,
        }
        with open(TRAINING_REPORT_JSON, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n[train-pac] training report: {TRAINING_REPORT_JSON.name}")

        gate = {
            "timestamp": timestamp,
            "mode": "final",
            "n_nights_processed": len(silver_paths),
            "scales_trained": [s for s in scales if "error" not in results[s]],
            "scales_failed":  [s for s in scales if "error" in results[s]],
            "all_ok": bool(all_ok),
        }
        with open(BATCH_GATE_JSON, "w", encoding="utf-8") as f:
            json.dump(gate, f, indent=2, ensure_ascii=False)
        print(f"[train-pac] batch gate: {BATCH_GATE_JSON.name} · all_ok={all_ok}")

    print(f"\n[train-pac] DONE en {elapsed_pool + elapsed_train:.1f}s")


if __name__ == "__main__":
    main()
