"""
PAC_v2 — Etapa 4 paso 7: batch labeling de estados PAC sobre las 560 noches.

Carga los 3 modelos persistidos (s/m/l), itera sobre silver/*.parquet,
construye ventanas con `windows.build_windows_for_night`, aplica z-score,
predice cluster, computa `dist_to_centroid`, mapea a state_label, y persiste
en `states/<NR>.parquet` (long-format, 3 escalas apiladas).

Decisiones cerradas (Q1..Q7=A, Roberto):
  Q1=A: etiqueta TODAS las ventanas (incluso wake-heavy). Marca
        `training_eligible` (bool) según Q6=C training mask
        (frac_wake≤0.5 AND coverage≥0.5).
  Q2=A: 1 parquet por NR_id, 3 escalas apiladas en col `scale`.
        Mismo pattern que events/<NR>_edos.parquet.
  Q3=A: filas con NaN en cualquier feature → no entran al predict
        (cluster_int=-1, state_label=None, dist_to_centroid=NaN).
  Q4=A: persiste `dist_to_centroid` (euclídea en z-space) — útil para
        flagging downstream y weighted averages en gold.
  Q5=A: tests en tests/test_apply_pac_states.py (paso siguiente).
  Q6=A: gate-check al inicio: exige `validation_proceed=True` en
        `reports/pac_states_batch_gate.json`. Si no, abort.
  Q7=A: skip NR_ids ya labelados (states/<NR>.parquet existente);
        flag `--force` para re-procesar todos.

Schema states/<NR>.parquet (14 cols, long-format, ordenado por
(scale, window_idx) para byte-reproducibilidad):

  night_record_id   str          NR_yyyymmdd_<hash>
  scale             str          "s" / "m" / "l"
  window_idx        int          0..N-1 por escala
  t_start           datetime64   absoluto (timestamp del primer sample)
  t_end             datetime64   absoluto (nominal: t_start + duration)
  t_start_s         float        segundos desde silver.timestamp[0]
  t_end_s           float        segundos desde silver.timestamp[0]
  state_label       object|None  "S3" / "M0" / "L2" o None si NaN-dropped
  cluster_int       int          0..K-1 o -1 si NaN-dropped
  dist_to_centroid  float        euclídea en z-space; NaN si NaN-dropped
  coverage          float        [0,1] (Q2=A en windows.py)
  frac_wake         float        [0,1]
  frac_light_sleep  float        [0,1]
  frac_deep_sleep   float        [0,1]
  training_eligible bool         True si frac_wake≤0.5 AND coverage≥0.5

KV metadata (parquet schema):
  night_record_id, applied_at, algorithm_version, schema_version,
  k_per_scale (json), source_silver_mtime, source_events_mtime.

Reporte: reports/pac_states_apply_report.json
  - per-NR_id: n_windows × scale, n_predicted, n_dropped_nan,
               n_training_eligible
  - global: distribución de clusters por escala (apply vs training,
            para detectar drift)
  - elapsed, n_ok, n_fail.

Corre:
  PYTHONPATH=src python scripts/apply_pac_states.py --mode smoke --limit 10
  PYTHONPATH=src python scripts/apply_pac_states.py --mode batch
  PYTHONPATH=src python scripts/apply_pac_states.py --mode batch --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pac import states as st
from pac import windows as wn
from pac.config import (
    ALGORITHM_VERSION_PAC_STATES,
    EVENTS_DIR,
    MODELS_DIR,
    PAC_STATES_SCHEMA_VERSION,
    PAC_STATES_TRAINING_MASK,
    PAC_STATE_PREFIXES,
    PAC_STATE_SCALES,
    PAC_WINDOW_FEATURES,
    REPORTS_DIR,
    SILVER_DIR,
    STATES_DIR,
)


APPLY_REPORT_JSON = REPORTS_DIR / "pac_states_apply_report.json"
BATCH_GATE_JSON = REPORTS_DIR / "pac_states_batch_gate.json"

# Schema canónico de output (orden de columnas + dtype hint).
OUTPUT_COLS = [
    "night_record_id",
    "scale",
    "window_idx",
    "t_start",
    "t_end",
    "t_start_s",
    "t_end_s",
    "state_label",
    "cluster_int",
    "dist_to_centroid",
    "coverage",
    "frac_wake",
    "frac_light_sleep",
    "frac_deep_sleep",
    "training_eligible",
]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Etapa 4 paso 7: batch labeling de estados PAC."
    )
    p.add_argument("--mode", choices=("smoke", "batch"), default="batch",
                   help="smoke = procesa --limit primeras noches; batch = todas.")
    p.add_argument("--limit", type=int, default=10,
                   help="N noches en --mode smoke (default 10).")
    p.add_argument("--force", action="store_true",
                   help="Re-procesa NR_ids con states/<NR>.parquet existente.")
    p.add_argument("--skip-gate-check", action="store_true",
                   help="Omite chequeo de validation_proceed (uso interno/tests).")
    p.add_argument("--silver-dir", type=Path, default=SILVER_DIR)
    p.add_argument("--events-dir", type=Path, default=EVENTS_DIR)
    p.add_argument("--states-dir", type=Path, default=STATES_DIR)
    p.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    p.add_argument("--verbose", action="store_true",
                   help="Log detallado por noche.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Gate check (Q6=A)
# ---------------------------------------------------------------------------
def gate_check(skip: bool = False) -> dict:
    """Lee batch_gate.json y exige validation_proceed=True."""
    if skip:
        print("[apply] gate check OMITIDO (--skip-gate-check).")
        return {"skipped": True}

    if not BATCH_GATE_JSON.exists():
        print(f"[apply] ERROR: {BATCH_GATE_JSON.name} no existe. "
              "Correr scripts/validate_pac_states.py antes.")
        sys.exit(2)

    with open(BATCH_GATE_JSON, encoding="utf-8") as f:
        bg = json.load(f)

    if not bg.get("validation_proceed", False):
        print(f"[apply] ERROR: validation_proceed=False en {BATCH_GATE_JSON.name}. "
              "Hay FAIL bloqueante en post-fit validation. Abort.")
        print(f"        failed_checks: {bg.get('validation_failed_checks', [])}")
        sys.exit(2)

    print(f"[apply] gate check OK · validation_proceed=True · "
          f"WARN={len(bg.get('validation_warned_checks', []))}")
    return bg


# ---------------------------------------------------------------------------
# Carga de los 3 modelos
# ---------------------------------------------------------------------------
def load_all_models(models_dir: Path) -> dict:
    """Carga (model, zparams, meta) para cada escala. Cachea centroides z-space."""
    out = {}
    for scale in PAC_STATE_SCALES:
        paths = st._paths_for_scale(scale, models_dir=models_dir)
        if not paths["kmeans_pkl"].exists():
            print(f"[apply] ERROR: modelo no encontrado para escala {scale!r}: "
                  f"{paths['kmeans_pkl']}")
            sys.exit(3)
        model, zparams, meta = st.load_model(scale, models_dir=models_dir)
        out[scale] = {
            "model": model,
            "zparams": zparams,
            "meta": meta,
            "centroids_z": np.asarray(model.cluster_centers_, dtype=float),
            "k": int(model.n_clusters),
            "prefix": PAC_STATE_PREFIXES[scale],
        }
        print(f"[apply] modelo {scale!r}: K={out[scale]['k']} · "
              f"features={len(zparams.feature_cols)}")
    return out


# ---------------------------------------------------------------------------
# Núcleo: labelar UNA noche
# ---------------------------------------------------------------------------
def label_night(
    silver_path: Path,
    events_path: Path | None,
    models: dict,
) -> tuple[pd.DataFrame, dict]:
    """
    Etiqueta una noche en las 3 escalas. Devuelve (df_long, stats_dict).

    df_long: DataFrame con OUTPUT_COLS, 3 escalas apiladas.
    stats_dict: counts per scale para el reporte.
    """
    nr = silver_path.stem
    silver_df = pd.read_parquet(silver_path)
    if events_path is not None and events_path.exists():
        edos_df = pd.read_parquet(events_path)
    else:
        edos_df = pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])

    # Tiempo cero de la noche para t_start_s relativo.
    if len(silver_df) == 0 or "timestamp" not in silver_df.columns:
        # Edge case: silver vacío → output vacío para esta noche.
        empty = pd.DataFrame(columns=OUTPUT_COLS)
        return empty, {"empty_silver": True}

    t0 = pd.Timestamp(silver_df["timestamp"].iloc[0])

    feature_cols = list(PAC_WINDOW_FEATURES)
    chunks: list[pd.DataFrame] = []
    stats: dict = {"by_scale": {}}

    for scale in PAC_STATE_SCALES:
        m = models[scale]
        model = m["model"]
        zparams = m["zparams"]
        centroids_z = m["centroids_z"]
        prefix = m["prefix"]

        # 1. Ventaneo + features (24 cols + metadata).
        wdf = wn.build_windows_for_night(silver_df, edos_df, scale)
        if len(wdf) == 0:
            stats["by_scale"][scale] = {
                "n_windows": 0, "n_predicted": 0,
                "n_dropped_nan": 0, "n_training_eligible": 0,
                "cluster_dist": {},
            }
            continue

        # 2. Matriz de features alineada al orden canónico.
        feat = wdf[feature_cols].apply(pd.to_numeric, errors="coerce")
        complete_mask = feat.notna().all(axis=1).to_numpy()

        # 3. Predict sólo sobre filas completas.
        n_total = len(wdf)
        cluster_int = np.full(n_total, -1, dtype=int)
        dist_to_cen = np.full(n_total, np.nan, dtype=float)
        if complete_mask.any():
            X = feat.to_numpy(dtype=float)[complete_mask]
            Xz = st.apply_zscore(X, zparams)
            preds = model.predict(Xz)
            cluster_int[complete_mask] = preds
            # Distancia euclídea al centroide asignado (z-space).
            assigned_centroids = centroids_z[preds]
            dist_to_cen[complete_mask] = np.linalg.norm(
                Xz - assigned_centroids, axis=1
            )

        # 4. State label (None para -1).
        state_label = np.empty(n_total, dtype=object)
        for i, ci in enumerate(cluster_int):
            state_label[i] = f"{prefix}{int(ci)}" if ci >= 0 else None

        # 5. training_eligible (mismo predicado que Q6=C en train).
        cov = pd.to_numeric(wdf["coverage"], errors="coerce")
        fw = pd.to_numeric(wdf["frac_wake"], errors="coerce")
        training_elig = (
            (fw <= PAC_STATES_TRAINING_MASK["frac_wake_max"])
            & (cov >= PAC_STATES_TRAINING_MASK["coverage_min"])
        ).fillna(False).astype(bool).to_numpy()

        # 6. t_start_s / t_end_s relativos a t0 de la noche.
        t_start_s = (
            (pd.to_datetime(wdf["t_start"]) - t0).dt.total_seconds()
            .to_numpy(dtype=float)
        )
        t_end_s = (
            (pd.to_datetime(wdf["t_end"]) - t0).dt.total_seconds()
            .to_numpy(dtype=float)
        )

        # 7. Ensamblar long-format.
        out = pd.DataFrame({
            "night_record_id":  nr,
            "scale":            scale,
            "window_idx":       wdf["window_idx"].astype(int).to_numpy(),
            "t_start":          pd.to_datetime(wdf["t_start"]).to_numpy(),
            "t_end":            pd.to_datetime(wdf["t_end"]).to_numpy(),
            "t_start_s":        t_start_s,
            "t_end_s":          t_end_s,
            "state_label":      state_label,
            "cluster_int":      cluster_int,
            "dist_to_centroid": dist_to_cen,
            "coverage":         cov.to_numpy(dtype=float),
            "frac_wake":        fw.to_numpy(dtype=float),
            "frac_light_sleep": pd.to_numeric(
                wdf["frac_light_sleep"], errors="coerce"
            ).to_numpy(dtype=float),
            "frac_deep_sleep":  pd.to_numeric(
                wdf["frac_deep_sleep"], errors="coerce"
            ).to_numpy(dtype=float),
            "training_eligible": training_elig,
        }, columns=OUTPUT_COLS)
        chunks.append(out)

        # Stats per-scale.
        cluster_dist = {
            f"{prefix}{i}": int((cluster_int == i).sum())
            for i in range(m["k"])
        }
        stats["by_scale"][scale] = {
            "n_windows": int(n_total),
            "n_predicted": int(complete_mask.sum()),
            "n_dropped_nan": int((~complete_mask).sum()),
            "n_training_eligible": int(training_elig.sum()),
            "cluster_dist": cluster_dist,
        }

    if not chunks:
        return pd.DataFrame(columns=OUTPUT_COLS), stats

    df_long = pd.concat(chunks, ignore_index=True)
    # Sort por (scale, window_idx) para byte-reproducibilidad
    # (scale es categorical-ish, sort es estable por orden alfabético: l<m<s).
    df_long = df_long.sort_values(
        ["scale", "window_idx"], kind="mergesort"
    ).reset_index(drop=True)
    return df_long, stats


# ---------------------------------------------------------------------------
# SHA256 de los modelos (Etapa 6.1: idempotencia honesta)
# ---------------------------------------------------------------------------
def compute_models_sha256(models_dir: Path) -> str:
    """SHA256 corto (16 chars) de los 3 archivos pac_states_{s,m,l}_centroids.csv
    concatenados.

    Sirve como huella digital del estado del modelo PAC States. Cuando el SHA
    cambia (porque se reentrenó), los `states/<NR>.parquet` con SHA viejo
    están realmente stale y requieren re-procesamiento.

    Cuando el SHA no cambia, los states están vigentes incluso si el mtime
    de events/* es más nuevo (porque apply_morphotypes solo agregó la columna
    morphotype, que apply_pac_states no usa).
    """
    h = hashlib.sha256()
    for scale in PAC_STATE_SCALES:
        path = models_dir / f"pac_states_{scale}_centroids.csv"
        if not path.exists():
            raise FileNotFoundError(f"Falta {path} para computar SHA del modelo.")
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def read_states_models_sha256(parquet_path: Path) -> str | None:
    """Lee model_centroids_sha256 del KV metadata de un states/*.parquet.

    Devuelve None si el archivo no existe, no tiene KV metadata, o no tiene
    la clave (states pre-Etapa 6.1).
    """
    if not parquet_path.exists():
        return None
    try:
        meta = pq.read_metadata(parquet_path)
        if not meta.metadata:
            return None
        kv = {k.decode(): v.decode() for k, v in meta.metadata.items()
              if not k.startswith(b"ARROW:")}
        return kv.get("model_centroids_sha256")
    except Exception:
        return None


def rehydrate_states_sha(parquet_path: Path, models_sha256: str) -> bool:
    """Agrega model_centroids_sha256 al KV de un states/*.parquet pre-Etapa 6.1.

    NO regenera el contenido del parquet — solo lee la tabla en memoria y
    la reescribe con el KV ampliado. Es ~10× más rápido que regenerar via
    label_night (no recomputa windows ni aplica el modelo).

    Devuelve True si rehidrató, False si no (archivo no existe).
    """
    if not parquet_path.exists():
        return False
    try:
        tbl = pq.read_table(parquet_path)
        existing_kv = {}
        if tbl.schema.metadata:
            existing_kv = {
                k.decode(): v.decode()
                for k, v in tbl.schema.metadata.items()
                if not k.startswith(b"ARROW:")
            }
        existing_kv["model_centroids_sha256"] = models_sha256
        tbl = tbl.replace_schema_metadata(existing_kv)
        pq.write_table(tbl, parquet_path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Persistencia con KV metadata
# ---------------------------------------------------------------------------
def write_states_parquet(
    df: pd.DataFrame,
    out_path: Path,
    nr: str,
    silver_path: Path,
    events_path: Path | None,
    models: dict,
    models_sha256: str,
) -> None:
    """Escribe states/<NR>.parquet con KV metadata canónico."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(df, preserve_index=False)

    kv = {
        "night_record_id":         nr,
        "applied_at":              datetime.now().isoformat(timespec="seconds"),
        "algorithm_version":       ALGORITHM_VERSION_PAC_STATES,
        "schema_version":          PAC_STATES_SCHEMA_VERSION,
        "k_per_scale":             json.dumps({s: int(models[s]["k"])
                                               for s in PAC_STATE_SCALES}),
        "source_silver_mtime":     str(silver_path.stat().st_mtime),
        "source_events_mtime":     (str(events_path.stat().st_mtime)
                                    if events_path and events_path.exists()
                                    else "none"),
        # Etapa 6.1: SHA del modelo usado. Permite al orquestador detectar
        # invalidación honesta (sólo cuando el modelo realmente cambió).
        "model_centroids_sha256":  models_sha256,
    }
    tbl = tbl.replace_schema_metadata(kv)
    pq.write_table(tbl, out_path)


# ---------------------------------------------------------------------------
# Reporte global (incluye drift check vs training)
# ---------------------------------------------------------------------------
def build_global_report(
    per_night: list[dict],
    models: dict,
    elapsed: float,
    n_input: int,
) -> dict:
    """Agrega per-night → global; compara distribución apply vs training."""
    total_windows = {s: 0 for s in PAC_STATE_SCALES}
    total_predicted = {s: 0 for s in PAC_STATE_SCALES}
    total_dropped = {s: 0 for s in PAC_STATE_SCALES}
    total_eligible = {s: 0 for s in PAC_STATE_SCALES}
    cluster_totals: dict = {s: {} for s in PAC_STATE_SCALES}

    n_ok = 0
    n_fail = 0
    fails: list[str] = []
    for entry in per_night:
        if entry.get("status") != "ok":
            n_fail += 1
            fails.append(f"{entry.get('nr', '??')}: {entry.get('error', '?')}")
            continue
        n_ok += 1
        # Edge case: silver vacío → stats sin 'by_scale'.
        by_scale = entry.get("stats", {}).get("by_scale", {})
        for scale, sc in by_scale.items():
            total_windows[scale] += sc["n_windows"]
            total_predicted[scale] += sc["n_predicted"]
            total_dropped[scale] += sc["n_dropped_nan"]
            total_eligible[scale] += sc["n_training_eligible"]
            for label, n in sc["cluster_dist"].items():
                cluster_totals[scale][label] = (
                    cluster_totals[scale].get(label, 0) + n
                )

    # Drift check: comparar fracciones apply vs training (cluster_sizes_training
    # del training_report, si existe).
    training_report_path = REPORTS_DIR / "pac_states_training_report.json"
    drift = {}
    if training_report_path.exists():
        with open(training_report_path, encoding="utf-8") as f:
            tr = json.load(f)
        for scale in PAC_STATE_SCALES:
            train_sizes = (
                tr.get("by_scale", {}).get(scale, {})
                  .get("cluster_sizes_training", {})
            )
            train_total = sum(train_sizes.values()) or 1
            apply_total = sum(cluster_totals[scale].values()) or 1
            train_pct = {k: 100.0 * v / train_total
                         for k, v in train_sizes.items()}
            apply_pct = {k: 100.0 * cluster_totals[scale].get(k, 0) / apply_total
                         for k in train_sizes.keys()}
            # Distancia L1 entre fracciones (en %).
            l1 = sum(abs(train_pct[k] - apply_pct.get(k, 0.0))
                     for k in train_sizes.keys())
            drift[scale] = {
                "training_pct": {k: round(v, 3) for k, v in train_pct.items()},
                "apply_pct":    {k: round(v, 3) for k, v in apply_pct.items()},
                "l1_distance_pct": round(l1, 3),
            }

    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "algorithm_version": ALGORITHM_VERSION_PAC_STATES,
        "schema_version": PAC_STATES_SCHEMA_VERSION,
        "n_nights_input": n_input,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "fails": fails[:50],
        "elapsed_s": round(elapsed, 2),
        "k_per_scale": {s: int(models[s]["k"]) for s in PAC_STATE_SCALES},
        "totals": {
            "n_windows":           total_windows,
            "n_predicted":         total_predicted,
            "n_dropped_nan":       total_dropped,
            "n_training_eligible": total_eligible,
        },
        "cluster_totals": cluster_totals,
        "drift_vs_training": drift,
        "per_night": [
            {"nr": e["nr"], "status": e["status"],
             **({"by_scale": {
                 s: {kk: vv for kk, vv in sc.items() if kk != "cluster_dist"}
                 for s, sc in e.get("stats", {}).get("by_scale", {}).items()
             }} if e.get("status") == "ok" else {})}
            for e in per_night
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    args.states_dir.mkdir(parents=True, exist_ok=True)

    # --- Gate check
    bg = gate_check(skip=args.skip_gate_check)

    # --- Carga modelos
    models = load_all_models(args.models_dir)

    # --- SHA del modelo (Etapa 6.1: idempotencia honesta)
    current_models_sha256 = compute_models_sha256(args.models_dir)
    print(f"[apply] model_centroids_sha256: {current_models_sha256}")

    # --- Lista de noches a procesar (excluye sidecars _qc.parquet)
    silver_paths = sorted(
        p for p in args.silver_dir.glob("NR_*.parquet")
        if not p.stem.endswith("_qc")
    )
    if args.mode == "smoke":
        silver_paths = silver_paths[: args.limit]
    if not silver_paths:
        print(f"[apply] ERROR: no se encontraron silver/*.parquet en "
              f"{args.silver_dir}.")
        sys.exit(4)
    print(f"[apply] mode={args.mode!r} · {len(silver_paths)} noches a procesar.")

    # --- Filtrado por idempotencia (Q7=A) + Etapa 6.1: skip-touch honesto
    #     Para cada NR con states/<NR>.parquet existente, 4 casos:
    #       a) SHA persistido == SHA actual → touch + skip (vigente).
    #       b) SHA persistido != SHA actual → re-procesar (modelo cambió).
    #       c) SHA ausente (states pre-Etapa 6.1) → REHIDRATAR: leer/escribir
    #          parquet con SHA agregado al KV. Barato (no recomputa modelo).
    #       d) NR sin states → procesar normalmente.
    if not args.force:
        skipped_touched = 0
        rehydrated = 0
        skipped_stale = 0
        to_process = []
        for sp in silver_paths:
            nr = sp.stem
            out_path = args.states_dir / f"{nr}.parquet"
            if not out_path.exists():
                to_process.append(sp)
                continue
            stored_sha = read_states_models_sha256(out_path)
            if stored_sha == current_models_sha256:
                # Caso (a): vigente → touch + skip
                out_path.touch()
                skipped_touched += 1
            elif stored_sha is None:
                # Caso (c): pre-Etapa 6.1 → rehidratar SHA en KV (barato)
                if rehydrate_states_sha(out_path, current_models_sha256):
                    rehydrated += 1
                else:
                    # Falló el rehydrate → forzar re-procesar
                    to_process.append(sp)
            else:
                # Caso (b): SHA difiere → modelo cambió, re-procesar
                to_process.append(sp)
                skipped_stale += 1
        if skipped_touched:
            print(f"[apply] {skipped_touched} noches con SHA modelo vigente · "
                  f"touch+skip.")
        if rehydrated:
            print(f"[apply] {rehydrated} noches con KV pre-Etapa 6.1 · "
                  f"rehidratadas (SHA agregado al KV, contenido intacto).")
        if skipped_stale:
            print(f"[apply] {skipped_stale} noches con SHA modelo distinto · "
                  f"re-procesar (modelo reentrenado).")
        silver_paths = to_process

    if not silver_paths:
        print("[apply] nada para procesar (todas ya labeladas y vigentes). "
              "Usar --force para re-correr.")
        return

    # --- Loop principal
    per_night: list[dict] = []
    t0 = time.time()
    for i, sp in enumerate(silver_paths, start=1):
        nr = sp.stem
        ep = args.events_dir / f"{nr}_edos.parquet"
        out_path = args.states_dir / f"{nr}.parquet"
        try:
            df_long, stats = label_night(sp, ep, models)
            write_states_parquet(
                df_long, out_path, nr, sp, ep, models, current_models_sha256
            )
            per_night.append({"nr": nr, "status": "ok", "stats": stats})
            if args.verbose or i % 50 == 0 or i == len(silver_paths):
                summary = " · ".join(
                    f"{s}:{stats['by_scale'].get(s, {}).get('n_windows', 0)}"
                    for s in PAC_STATE_SCALES
                )
                print(f"  [{i:4d}/{len(silver_paths)}] {nr}: {summary}")
        except Exception as e:
            per_night.append({
                "nr": nr, "status": "fail",
                "error": f"{type(e).__name__}: {e}",
            })
            print(f"  [{i:4d}/{len(silver_paths)}] FAIL {nr}: {e}")
    elapsed = time.time() - t0

    # --- Reporte global
    report = build_global_report(per_night, models, elapsed, len(silver_paths))
    # Si --force no se usó y hay noches preexistentes, n_input refleja sólo lo
    # procesado en esta corrida; lo aclaramos en el reporte:
    report["force_mode"] = bool(args.force)
    report["mode"] = args.mode

    with open(APPLY_REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[apply] reporte: {APPLY_REPORT_JSON.name}")

    # --- Resumen
    print(f"[apply] DONE — {report['n_ok']}/{len(silver_paths)} OK · "
          f"{report['n_fail']} FAIL · {elapsed:.1f} s")
    for scale in PAC_STATE_SCALES:
        nw = report["totals"]["n_windows"][scale]
        np_ = report["totals"]["n_predicted"][scale]
        ne = report["totals"]["n_training_eligible"][scale]
        print(f"        scale {scale!r}: n_windows={nw:,} · predicted={np_:,} · "
              f"training_eligible={ne:,}")
    if report["drift_vs_training"]:
        for scale, d in report["drift_vs_training"].items():
            print(f"        drift {scale!r}: L1={d['l1_distance_pct']:.2f}% "
                  f"(apply vs training)")


if __name__ == "__main__":
    main()
