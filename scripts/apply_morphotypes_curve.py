"""
PAC_v2 — Apply morphotype_curve labels a todos los EDOs.

Carga el modelo persistido (models/edo_morphotype_curve_kmeans.pkl),
lee cada par {NR}_edos.parquet + {NR}_edo_curves.parquet,
asigna la columna `morphotype_curve` ∈ {"C1","C2","C3","C4","C5"}
y reescribe {NR}_edos.parquet (idempotente).

Idéntico en estructura a apply_morphotypes.py (que asigna α/β/γ/δ).

Uso:
  PYTHONPATH=src python scripts/apply_morphotypes_curve.py
  PYTHONPATH=src python scripts/apply_morphotypes_curve.py --limit 10
  PYTHONPATH=src python scripts/apply_morphotypes_curve.py --verbose
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
import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pac import morphotypes_curve as mc  # noqa: E402
from pac.config import EVENTS_DIR, MODELS_DIR, REPORTS_DIR  # noqa: E402


BATCH_GATE_JSON = REPORTS_DIR / "morphotypes_curve_batch_gate.json"
SUMMARY_CSV     = REPORTS_DIR / "morphotypes_curve_summary.csv"


def _label_one_night(
    nr_id: str,
    model,
    events_dir: Path,
) -> dict:
    """
    Asigna `morphotype_curve` a todos los EDOs de UNA noche.

    Estrategia de robustez:
      - EDOs sin curva correspondiente → morphotype_curve = None
      - EDOs con NaN en la curva → morphotype_curve = None
      - EDOs con duration > 180s → morphotype_curve = None (fuera del training)
      - Resto → C1..C5 por distancia euclidiana al centroide

    Idempotente: sobrescribe morphotype_curve si ya existe.
    """
    edos_path   = events_dir / f"{nr_id}_edos.parquet"
    curves_path = events_dir / f"{nr_id}_edo_curves.parquet"

    if not edos_path.exists():
        return {"night_record_id": nr_id, "status": "no_edos_file",
                "n_edos": 0, "n_labeled": 0, "n_null": 0}

    # Leer EDOs
    tbl_edos = pq.read_table(edos_path)
    df_edos  = tbl_edos.to_pandas()
    n_edos   = len(df_edos)

    # Inicializar columna de salida con None
    df_edos["morphotype_curve"] = None

    if n_edos == 0 or not curves_path.exists():
        _write_back(df_edos, tbl_edos, edos_path, nr_id)
        return {"night_record_id": nr_id, "status": "ok",
                "n_edos": n_edos, "n_labeled": 0, "n_null": n_edos,
                **{f"n_{lbl}": 0 for lbl in mc.CURVE_LABELS}}

    # Leer curvas
    df_curves = pq.read_table(
        curves_path, columns=["night_record_id", "ts_start", "spo2_curve"]
    ).to_pandas()

    # Join por (night_record_id, ts_start)
    merged = df_edos[["night_record_id", "ts_start", "baseline_spo2", "duration_s"]].merge(
        df_curves,
        on=["night_record_id", "ts_start"],
        how="left",
    )

    # Máscara de filas etiquetables
    has_curve  = merged["spo2_curve"].notna()
    valid_dur  = merged["duration_s"] <= mc.CURVE_TRAINING_FILTER["duration_s_max"]
    etiquetable = has_curve & valid_dur

    labels_out = np.full(n_edos, None, dtype=object)

    if etiquetable.any():
        idx_valid = np.where(etiquetable)[0]
        # Construir ΔSpO2
        curves_valid   = np.stack(merged.loc[etiquetable, "spo2_curve"].values)
        baseline_valid = merged.loc[etiquetable, "baseline_spo2"].values.reshape(-1, 1)
        X = curves_valid - baseline_valid

        # Filtrar NaN dentro de las curvas etiquetables
        nan_mask = np.isnan(X).any(axis=1)
        X_clean  = X[~nan_mask]
        idx_clean = idx_valid[~nan_mask]

        if len(X_clean) > 0:
            preds = mc.predict_curve_cluster(model, X_clean)
            for i, lbl in zip(idx_clean, preds):
                labels_out[i] = lbl

    df_edos["morphotype_curve"] = labels_out
    _write_back(df_edos, tbl_edos, edos_path, nr_id)

    n_labeled = int(pd.Series(labels_out).notna().sum())
    n_null    = int(n_edos - n_labeled)
    label_counts = {
        f"n_{lbl}": int((pd.Series(labels_out) == lbl).sum())
        for lbl in mc.CURVE_LABELS
    }
    return {"night_record_id": nr_id, "status": "ok",
            "n_edos": n_edos, "n_labeled": n_labeled, "n_null": n_null,
            **label_counts}


def _write_back(df: pd.DataFrame, orig_tbl, path: Path, nr_id: str) -> None:
    """Reescribe el parquet preservando KV metadata."""
    new_tbl = pa.Table.from_pandas(df, preserve_index=False)
    existing_kv = {
        (k.decode() if isinstance(k, bytes) else k):
        (v.decode() if isinstance(v, bytes) else v)
        for k, v in (orig_tbl.schema.metadata or {}).items()
    }
    existing_kv["morphotype_curve_applied_at"] = datetime.now().isoformat(timespec="seconds")
    existing_kv["morphotype_curve_version"] = mc.CURVE_ALGORITHM_VERSION
    new_tbl = new_tbl.replace_schema_metadata(existing_kv)
    pq.write_table(new_tbl, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aplica morphotype_curve a todos los EDOs (Etapa 3c paso 2)"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Procesar solo las primeras N noches.")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print("[apply_curve] cargando modelo...")
    model, meta = mc.load_curve_model(MODELS_DIR)
    print(f"  k={model.n_clusters}  version={meta['algorithm_version']}")

    edos_paths  = sorted(EVENTS_DIR.glob("NR_*_edos.parquet"))
    if args.limit:
        edos_paths = edos_paths[: args.limit]
    print(f"[apply_curve] procesando {len(edos_paths)} noches...\n")

    rows = []
    t0   = time.time()
    for i, ep in enumerate(edos_paths, start=1):
        nr_id = ep.stem.replace("_edos", "")
        try:
            r = _label_one_night(nr_id, model, EVENTS_DIR)
            rows.append(r)
            if args.verbose or i % 50 == 0 or i == len(edos_paths):
                print(f"  [{i:4d}/{len(edos_paths)}] {nr_id}: "
                      f"labeled={r['n_labeled']} null={r['n_null']}")
        except Exception as e:
            rows.append({"night_record_id": nr_id, "status": f"fail: {e}",
                         "n_edos": 0, "n_labeled": 0, "n_null": 0})
            print(f"  [{i:4d}/{len(edos_paths)}] FAIL {nr_id}: {e}")

    elapsed = time.time() - t0
    summary = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_CSV, index=False)

    ok_mask       = summary["status"] == "ok"
    total_labeled = int(summary["n_labeled"].sum())
    label_totals  = {lbl: int(summary.get(f"n_{lbl}", pd.Series(0)).sum())
                     for lbl in mc.CURVE_LABELS}

    gate = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "algorithm_version": mc.CURVE_ALGORITHM_VERSION,
        "n_nights_input": len(edos_paths),
        "n_ok": int(ok_mask.sum()),
        "n_fail": int((~ok_mask).sum()),
        "total_edos": int(summary["n_edos"].sum()),
        "total_labeled": total_labeled,
        "total_null": int(summary["n_null"].sum()),
        "elapsed_s": round(elapsed, 2),
        "label_totals": label_totals,
        "label_fractions": {
            lbl: round(label_totals[lbl] / total_labeled, 4)
            if total_labeled > 0 else 0.0
            for lbl in mc.CURVE_LABELS
        },
    }
    with open(BATCH_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2, ensure_ascii=False)

    print(f"\n[apply_curve] DONE — {gate['n_ok']}/{len(edos_paths)} OK · "
          f"{elapsed:.1f}s · {total_labeled:,} EDOs labeled")
    print("[apply_curve] distribución:")
    for lbl, n in label_totals.items():
        pct = 100 * n / total_labeled if total_labeled > 0 else 0
        print(f"  {lbl}: {n:>7,} ({pct:5.2f}%)")
    print(f"\n  Summary CSV: {SUMMARY_CSV.name}")
    print(f"  Gate JSON:   {BATCH_GATE_JSON.name}")
    print("\nPróximo paso: rebuild gold/events.parquet")
    print("  python scripts/build_events_gold.py")


if __name__ == "__main__":
    main()
