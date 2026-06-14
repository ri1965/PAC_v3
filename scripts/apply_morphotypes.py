"""
PAC_v2 — Etapa 3b paso 5: batch labeling de morphotypes sobre todos los EDOs.

Carga el modelo persistido (models/edo_morphotype_kmeans.pkl) + z-score
(edo_morphotype_zscore.json), aplica el label a las 560 × {NR}_edos.parquet
(añade columna `morphotype` ∈ {α,β,γ,δ,…}) y escribe:

  reports/morphotypes_summary.csv     (1 fila × noche: n_edos por morfotipo)
  reports/morphotypes_batch_gate.json (resumen batch)

Idempotente: re-correr produce el mismo label. Si la columna `morphotype` ya
existe en el parquet, se sobrescribe. La metadata KV agrega
`morphotyping_applied_at` y `morphotype_algorithm_version`.

Universo de labeling: TODOS los EDOs del pool (incluye marginales meets_2pct
que no participaron del training) — consistente con decisión R2 del scope.

Corre:  PYTHONPATH=src python scripts/apply_morphotypes.py
        PYTHONPATH=src python scripts/apply_morphotypes.py --limit 10
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pac import morphotypes as mt
from pac.config import (
    ALGORITHM_VERSION_MORPHOTYPES,
    EVENTS_DIR,
    MODELS_DIR,
    MORPHOTYPE_FEATURES,
    MORPHOTYPES_SCHEMA_VERSION,
    REPORTS_DIR,
)


SUMMARY_CSV = REPORTS_DIR / "morphotypes_summary.csv"
BATCH_GATE_JSON = REPORTS_DIR / "morphotypes_batch_gate.json"


def _label_one(
    nr_path: Path,
    model,
    zparams,
    feature_cols: list[str],
) -> dict:
    """
    Añade columna `morphotype` al parquet de una noche (sobre-escribe).

    Labeling robusto:
      - EDOs con NaN en alguna feature → morphotype = None.
      - EDOs con features completas → label griega según KMeans.

    Idempotente vía sobrescritura del parquet (preserva schema).
    """
    tbl = pq.read_table(nr_path)
    df = tbl.to_pandas()
    if len(df) == 0:
        return {
            "night_record_id": nr_path.stem.replace("_edos", ""),
            "n_edos": 0, "n_labeled": 0, "n_null": 0,
        }

    # Matriz de features sobre TODOS los EDOs del parquet.
    sub = df[feature_cols].apply(pd.to_numeric, errors="coerce")
    complete = sub.notna().all(axis=1).to_numpy()
    Xz = mt.apply_zscore(sub.to_numpy(dtype=float), zparams)
    # Sólo predecir sobre las filas completas.
    labels_int = np.full(len(df), -1, dtype=int)
    if complete.any():
        labels_int[complete] = model.predict(Xz[complete])

    # Mapear a letra griega (None para los -1).
    out_labels = np.empty(len(df), dtype=object)
    for i, li in enumerate(labels_int):
        out_labels[i] = (
            mt.MORPHOTYPE_GREEK_LETTERS[int(li)] if li >= 0 else None
        )
    df["morphotype"] = out_labels

    # Reescribir parquet preservando KV metadata + agregando campos propios.
    new_tbl = pa.Table.from_pandas(df, preserve_index=False)
    existing_kv = dict((tbl.schema.metadata or {}))
    existing_kv = {
        (k.decode() if isinstance(k, bytes) else k):
        (v.decode() if isinstance(v, bytes) else v)
        for k, v in existing_kv.items()
    }
    existing_kv["morphotyping_applied_at"] = datetime.now().isoformat(
        timespec="seconds"
    )
    existing_kv["morphotype_algorithm_version"] = ALGORITHM_VERSION_MORPHOTYPES
    existing_kv["morphotypes_schema_version"] = MORPHOTYPES_SCHEMA_VERSION
    new_schema = new_tbl.schema.with_metadata(existing_kv)
    new_tbl = new_tbl.replace_schema_metadata(existing_kv)

    pq.write_table(new_tbl, nr_path)

    return {
        "night_record_id": nr_path.stem.replace("_edos", ""),
        "n_edos": int(len(df)),
        "n_labeled": int((pd.Series(out_labels).notna()).sum()),
        "n_null": int((pd.Series(out_labels).isna()).sum()),
        **{
            f"n_{letter}": int((pd.Series(out_labels) == letter).sum())
            for letter in mt.MORPHOTYPE_GREEK_LETTERS[: model.n_clusters]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aplica morphotype label a todos los EDOs (Etapa 3b paso 5)"
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Si se pasa, procesa sólo las primeras N noches.")
    parser.add_argument("--verbose", action="store_true",
                        help="Log por noche.")
    args = parser.parse_args()

    print("[apply] cargando modelo persistido …")
    model, zparams, meta = mt.load_model(MODELS_DIR)
    k = model.n_clusters
    letters_used = mt.MORPHOTYPE_GREEK_LETTERS[:k]
    print(f"        K = {k} · letras = {letters_used} · features = {len(zparams.feature_cols)}")

    paths = sorted(EVENTS_DIR.glob("NR_*_edos.parquet"))
    if args.limit:
        paths = paths[: args.limit]
    print(f"[apply] procesando {len(paths)} noches …")

    rows = []
    t0 = time.time()
    for i, p in enumerate(paths, start=1):
        try:
            r = _label_one(p, model, zparams, list(MORPHOTYPE_FEATURES))
            rows.append({**r, "status": "ok"})
            if args.verbose or i % 50 == 0 or i == len(paths):
                print(f"  [{i:4d}/{len(paths)}] {r['night_record_id']}: "
                      f"n={r['n_edos']} labeled={r['n_labeled']} null={r['n_null']}")
        except Exception as e:
            rows.append({
                "night_record_id": p.stem.replace("_edos", ""),
                "n_edos": 0, "n_labeled": 0, "n_null": 0,
                "status": f"fail: {type(e).__name__}: {e}",
            })
            print(f"  [{i:4d}/{len(paths)}] FAIL {p.stem}: {e}")
    elapsed = time.time() - t0

    summary = pd.DataFrame(rows)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_CSV, index=False)
    print(f"[apply] summary CSV: {SUMMARY_CSV.name}")

    # Batch gate JSON.
    ok_mask = summary["status"] == "ok"
    n_ok = int(ok_mask.sum())
    n_fail = int((~ok_mask).sum())
    label_totals = {
        letter: int(summary.get(f"n_{letter}", pd.Series(dtype=int)).sum())
        for letter in letters_used
    }
    total_edos = int(summary["n_edos"].sum())
    total_labeled = int(summary["n_labeled"].sum())
    total_null = int(summary["n_null"].sum())

    gate = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "events_dir": str(EVENTS_DIR),
        "models_dir": str(MODELS_DIR),
        "k": int(k),
        "letters_used": letters_used,
        "algorithm_version": ALGORITHM_VERSION_MORPHOTYPES,
        "n_nights_input": int(len(paths)),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "elapsed_s": round(elapsed, 2),
        "total_edos": total_edos,
        "total_labeled": total_labeled,
        "total_null": total_null,
        "label_totals": label_totals,
        "label_fractions": {
            letter: round(label_totals[letter] / total_labeled, 4)
            if total_labeled > 0 else 0.0
            for letter in letters_used
        },
    }
    with open(BATCH_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2, ensure_ascii=False)
    print(f"[apply] gate JSON: {BATCH_GATE_JSON.name}")

    print()
    print(f"[apply] DONE — {n_ok}/{len(paths)} OK · {n_fail} FAIL · "
          f"{elapsed:.1f} s · {total_labeled:,} EDOs labeled · "
          f"{total_null:,} null.")
    print("[apply] distribución global:")
    for letter, n in label_totals.items():
        pct = 100.0 * n / total_labeled if total_labeled > 0 else 0.0
        print(f"          {letter}: {n:>7,} ({pct:5.2f}%)")


if __name__ == "__main__":
    main()
