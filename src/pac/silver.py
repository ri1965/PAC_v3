"""
PAC_v2 — Etapa 2 Silver: orquestador.

Lee bronze/{NR}.parquet (5 cols canónicas, 1 Hz), aplica QC:
  - Range QC sobre spo2 y hr (SpO2<55 → inválido; HR ∉ [30,200] → inválido).
  - Cobertura temporal (coverage ratio + max_contiguous_gap).
  - Duración de noche (dual-flag aborted<1h / short<3h).

Escribe 2 parquets por noche:
  - silver/{NR}.parquet        → 9 cols (5 señales + spo2_invalid/_clean + hr_invalid/_clean)
  - silver/{NR}_qc.parquet     → 1 fila × ~15 cols con métricas QC

Y al cerrar el batch:
  - reports/silver_gate.json       → resumen agregado + distribuciones (p5/median/p95)
  - reports/silver_qc_summary.csv  → snapshot legible: 1 fila por noche con todas las QC cols

Criterios Etapa 2 (cerrados con Roberto Q1–Q8):
  1. SpO2 rango simple (Q1 1c).
  2. HR rango simple; coherencia multi-señal difiere a Etapa 3 (Q2 2b).
  3. Gaps con coverage + max_contiguous_gap, no n_gaps (Q3 3c).
  4. Duración dual-flag aborted ⊂ short (Q4 4a).
  5. Silver NO lee clinical.csv ni patient_registry.csv (Q5).
  6. 2 parquets por noche: signals 9-col + qc 1-row (Q6 6b).
  7. Gate minimal + distribuciones; CSV snapshot al final (Q7 7b + log-B).
  8. Dedup en raw/ ya cerrado; Silver procesa sobre bronze limpio (Q8 8a).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pac.config import (
    BRONZE_DIR,
    HR_MAX_VALID,
    HR_MIN_VALID,
    QC_COVERAGE_MIN,
    QC_DURATION_ABORTED_S,
    QC_DURATION_MIN_S,
    QC_MAX_GAP_S,
    REPORTS_DIR,
    SAMPLING_HZ_NOMINAL,
    SILVER_DIR,
    SILVER_SCHEMA_VERSION,
    SPO2_MIN_VALID,
    ensure_dirs,
)
from pac.qc import (
    apply_range_qc,
    compute_coverage_flags,
    compute_duration_flags,
    compute_gap_metrics,
)


SILVER_GATE_JSON = REPORTS_DIR / "silver_gate.json"
SILVER_QC_SUMMARY_CSV = REPORTS_DIR / "silver_qc_summary.csv"

# Columnas finales del silver signals parquet.
SILVER_SIGNAL_COLS = [
    "timestamp",
    "spo2", "spo2_invalid", "spo2_clean",
    "hr", "hr_invalid", "hr_clean",
    "mov",
    "sleep_stage",
]

# Columnas del _qc.parquet (1 fila).
SILVER_QC_COLS = [
    "night_record_id", "user_id",
    "ts_start", "ts_end",
    "n_samples", "duration_s",
    "coverage", "max_contiguous_gap_s",
    "qc_coverage_ok", "qc_max_gap_ok",
    "qc_duration_aborted", "qc_duration_short",
    "n_spo2_invalid", "n_hr_invalid",
    "frac_spo2_invalid", "frac_hr_invalid",
]


# ---------------------------------------------------------------------------
# I/O helpers — lectura de bronze + escritura parquet con metadata KV.
# ---------------------------------------------------------------------------
def _read_bronze_signals(nr_path: Path) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Lee un bronze parquet y devuelve (df, kv_metadata)."""
    table = pq.read_table(nr_path)
    df = table.to_pandas()
    md_raw = table.schema.metadata or {}
    # Filtrar las keys de pandas (que empiezan con b'pandas') y decodear.
    kv = {
        k.decode("utf-8"): v.decode("utf-8")
        for k, v in md_raw.items()
        if not k.startswith(b"pandas")
    }
    return df, kv


def _write_parquet_with_kv(
    df: pd.DataFrame,
    path: Path,
    kv_metadata: Dict[str, str],
) -> None:
    """Escribe un parquet con metadata KV al nivel de schema (pattern de ingest.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    merged = dict(existing)
    merged.update(
        {k.encode("utf-8"): str(v).encode("utf-8") for k, v in kv_metadata.items()}
    )
    table = table.replace_schema_metadata(merged)
    pq.write_table(table, path, compression="snappy")


# ---------------------------------------------------------------------------
# process_one — pipeline silver por noche.
# ---------------------------------------------------------------------------
def process_one(
    nr_path: Path,
    silver_dir: Path = SILVER_DIR,
) -> dict:
    """
    Procesa un bronze/{NR}.parquet → escribe silver/{NR}.parquet +
    silver/{NR}_qc.parquet. Devuelve el dict de la fila QC (mismo shape que
    el _qc.parquet de esa noche).

    Raises:
        Si falla lectura o escritura de parquets, propaga la excepción
        al caller (run_silver la captura como FAIL).
    """
    # --- Read bronze -------------------------------------------------------
    df, kv = _read_bronze_signals(nr_path)

    # Asegurar orden temporal (defensivo; bronze ya lo garantiza).
    if not df["timestamp"].is_monotonic_increasing:
        df = df.sort_values("timestamp").reset_index(drop=True)

    # --- Range QC ----------------------------------------------------------
    df = apply_range_qc(df, "spo2", vmin=SPO2_MIN_VALID)
    df = apply_range_qc(df, "hr", vmin=HR_MIN_VALID, vmax=HR_MAX_VALID)

    # Reordenar columnas al contrato.
    df = df[SILVER_SIGNAL_COLS]

    # --- Gap metrics -------------------------------------------------------
    gm = compute_gap_metrics(df, ts_col="timestamp", sampling_hz=float(SAMPLING_HZ_NOMINAL))

    # --- Duration flags ----------------------------------------------------
    dur_flags = compute_duration_flags(
        duration_s=gm["duration_s"],
        aborted_s=QC_DURATION_ABORTED_S,
        min_s=QC_DURATION_MIN_S,
    )

    # --- Coverage flags ----------------------------------------------------
    cov_flags = compute_coverage_flags(
        gm,
        coverage_min=QC_COVERAGE_MIN,
        max_gap_s=QC_MAX_GAP_S,
    )

    # --- Invalid counts ----------------------------------------------------
    n_spo2_invalid = int(df["spo2_invalid"].sum())
    n_hr_invalid = int(df["hr_invalid"].sum())
    n_samples = int(len(df))
    frac_spo2 = float(n_spo2_invalid / n_samples) if n_samples else 0.0
    frac_hr = float(n_hr_invalid / n_samples) if n_samples else 0.0

    # --- Armar fila QC -----------------------------------------------------
    nr_id = kv.get("night_record_id", nr_path.stem)
    user_id = kv.get("user_id", "")
    ts_start = kv.get("ts_start", "")
    ts_end = kv.get("ts_end", "")

    qc_row = {
        "night_record_id": nr_id,
        "user_id": user_id,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "n_samples": n_samples,
        "duration_s": float(gm["duration_s"]),
        "coverage": float(gm["coverage"]),
        "max_contiguous_gap_s": int(gm["max_contiguous_gap_s"]),
        "qc_coverage_ok": cov_flags["qc_coverage_ok"],
        "qc_max_gap_ok": cov_flags["qc_max_gap_ok"],
        "qc_duration_aborted": dur_flags["qc_duration_aborted"],
        "qc_duration_short": dur_flags["qc_duration_short"],
        "n_spo2_invalid": n_spo2_invalid,
        "n_hr_invalid": n_hr_invalid,
        "frac_spo2_invalid": frac_spo2,
        "frac_hr_invalid": frac_hr,
    }

    # --- Metadata KV para los parquets silver ------------------------------
    # Hereda campos relevantes de bronze + agrega los de silver.
    silver_kv = dict(kv)  # copia
    silver_kv.update(
        {
            "pipeline_stage": "silver",
            "silver_schema_version": SILVER_SCHEMA_VERSION,
            "silver_processed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "spo2_min_valid": str(SPO2_MIN_VALID),
            "hr_min_valid": str(HR_MIN_VALID),
            "hr_max_valid": str(HR_MAX_VALID),
            "qc_coverage_min": str(QC_COVERAGE_MIN),
            "qc_max_gap_s": str(QC_MAX_GAP_S),
        }
    )

    # --- Escribir silver/{NR}.parquet --------------------------------------
    signals_path = silver_dir / f"{nr_id}.parquet"
    _write_parquet_with_kv(df, signals_path, silver_kv)

    # --- Escribir silver/{NR}_qc.parquet (1 fila) --------------------------
    qc_path = silver_dir / f"{nr_id}_qc.parquet"
    qc_df = pd.DataFrame([qc_row], columns=SILVER_QC_COLS)
    _write_parquet_with_kv(qc_df, qc_path, silver_kv)

    return qc_row


# ---------------------------------------------------------------------------
# run_silver — orquestador.
# ---------------------------------------------------------------------------
def run_silver(
    bronze_dir: Path = BRONZE_DIR,
    silver_dir: Path = SILVER_DIR,
    limit: Optional[int] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Itera sobre bronze/NR_*.parquet (excluye *_classical.parquet), llama a
    process_one() con isolation por try/except. Escribe:
      - reports/silver_gate.json       (resumen + distribuciones)
      - reports/silver_qc_summary.csv  (1 fila por noche OK)

    Returns:
        DataFrame con 1 fila por noche procesada. Columnas extra:
        `status` ('OK'/'FAIL'), `error` (mensaje si FAIL).
    """
    ensure_dirs()

    # Listar bronze signals parquets (excluir sidecars classical).
    candidates = sorted(bronze_dir.glob("NR_*.parquet"))
    candidates = [p for p in candidates if not p.name.endswith("_classical.parquet")]
    if limit is not None:
        candidates = candidates[:limit]
    if verbose:
        print(f"[silver] bronze parquets a procesar: {len(candidates)}")

    t0 = time.time()
    rows = []
    for i, nr_path in enumerate(candidates, start=1):
        try:
            qc_row = process_one(nr_path, silver_dir=silver_dir)
            qc_row["status"] = "OK"
            qc_row["error"] = ""
            msg_tail = (
                f"cov={qc_row['coverage']:.3f}  maxgap={qc_row['max_contiguous_gap_s']}s  "
                f"spo2_inv={qc_row['frac_spo2_invalid']:.1%}  hr_inv={qc_row['frac_hr_invalid']:.1%}"
            )
        except Exception as e:  # noqa: BLE001
            qc_row = {c: "" for c in SILVER_QC_COLS}
            qc_row["night_record_id"] = nr_path.stem
            qc_row["status"] = "FAIL"
            qc_row["error"] = f"{type(e).__name__}: {e}"
            msg_tail = f"ERROR: {qc_row['error']}"

        rows.append(qc_row)
        if verbose:
            print(f"[{i:>4}/{len(candidates)}] {nr_path.name} → {qc_row['status']}  {msg_tail}")

    elapsed = time.time() - t0

    # --- Summary CSV -------------------------------------------------------
    summary_cols = SILVER_QC_COLS + ["status", "error"]
    df_summary = pd.DataFrame(rows, columns=summary_cols)
    SILVER_QC_SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_summary.to_csv(SILVER_QC_SUMMARY_CSV, index=False)

    # --- Gate JSON ---------------------------------------------------------
    n_ok = int((df_summary["status"] == "OK").sum())
    n_fail = int((df_summary["status"] == "FAIL").sum())

    ok_mask = df_summary["status"] == "OK"
    ok_df = df_summary[ok_mask]

    def _dist(col: str) -> dict:
        if ok_df.empty:
            return {"median": None, "p5": None, "p95": None, "min": None, "max": None}
        s = pd.to_numeric(ok_df[col], errors="coerce").dropna()
        if s.empty:
            return {"median": None, "p5": None, "p95": None, "min": None, "max": None}
        return {
            "median": float(np.median(s)),
            "p5":     float(np.percentile(s, 5)),
            "p95":    float(np.percentile(s, 95)),
            "min":    float(s.min()),
            "max":    float(s.max()),
        }

    def _count_true(col: str) -> int:
        if ok_df.empty or col not in ok_df.columns:
            return 0
        return int(ok_df[col].astype(bool).sum())

    gate = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "bronze_dir": str(bronze_dir),
        "silver_dir": str(silver_dir),
        "n_bronze_input": int(len(df_summary)),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "elapsed_s": round(elapsed, 2),
        "thresholds": {
            "spo2_min_valid": SPO2_MIN_VALID,
            "hr_min_valid": HR_MIN_VALID,
            "hr_max_valid": HR_MAX_VALID,
            "qc_coverage_min": QC_COVERAGE_MIN,
            "qc_max_gap_s": QC_MAX_GAP_S,
            "qc_duration_aborted_s": QC_DURATION_ABORTED_S,
            "qc_duration_min_s": QC_DURATION_MIN_S,
        },
        "qc_flags_counts": {
            "qc_coverage_ok_true":      _count_true("qc_coverage_ok"),
            "qc_max_gap_ok_true":       _count_true("qc_max_gap_ok"),
            "qc_duration_aborted_true": _count_true("qc_duration_aborted"),
            "qc_duration_short_true":   _count_true("qc_duration_short"),
        },
        "metrics_distribution": {
            "coverage":             _dist("coverage"),
            "max_contiguous_gap_s": _dist("max_contiguous_gap_s"),
            "duration_s":           _dist("duration_s"),
            "frac_spo2_invalid":    _dist("frac_spo2_invalid"),
            "frac_hr_invalid":      _dist("frac_hr_invalid"),
        },
    }
    with open(SILVER_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2, ensure_ascii=False)

    if verbose:
        print("")
        print("=" * 60)
        print(f"[silver] DONE en {elapsed:.1f}s — OK={n_ok}  FAIL={n_fail}")
        print(f"[silver] summary: {SILVER_QC_SUMMARY_CSV}")
        print(f"[silver] gate:    {SILVER_GATE_JSON}")

    return df_summary


def main() -> int:
    """CLI mínima: --limit N para smoke tests."""
    limit = None
    args = sys.argv[1:]
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("uso: python -m pac.silver [--limit N]")
            return 2
    df = run_silver(limit=limit)
    return 0 if (df["status"] == "OK").any() else 1


if __name__ == "__main__":
    sys.exit(main())
