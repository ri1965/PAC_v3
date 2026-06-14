"""
PAC_v2 — Etapa 1 Bronze: orquestador.

Itera sobre raw/*.xlsx, llama a ingest_one() por archivo con isolation por
try/except (ningún fallo corta el batch), y escribe:
  - reports/bronze_log.csv   (1 fila por xlsx procesado)
  - reports/bronze_gate.json (resumen agregado del batch)

Los parquets de salida los escribe ingest_one() en BRONZE_DIR:
  - {NightRecordID}.parquet             señales canónicas 5-col
  - {NightRecordID}_classical.parquet   sidecar con ~21 índices pre-computados

Criterios Etapa 1 (cerrados con Roberto):
  1. patient_id sale del xlsx (user_id del bloque 1).
  2. Re-ingest: sobreescritura silenciosa (idempotente si el xlsx no cambió).
  3. Sampling 1 Hz fijo; se guarda sampling_hz_median como sanity.
  4. Índices clásicos en sidecar parquet (recalculables en Etapa 3).
  5. sleep_stage persistido como 5ta columna canónica.
  6. Sin salt (NightRecordID determinístico por SHA + ts_start).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from pac.config import (
    RAW_DIR,
    REPORTS_DIR,
    ensure_dirs,
)
from pac.ingest import (
    ingest_one,
    register_stubs_for_unknown_ids,
    scan_xlsx_user_ids,
)
from pac.io import read_patient_registry


BRONZE_LOG_CSV = REPORTS_DIR / "bronze_log.csv"
BRONZE_GATE_JSON = REPORTS_DIR / "bronze_gate.json"

LOG_COLS = [
    "xlsx",
    "xlsx_bytes",
    "status",
    "error",
    "source_exam_id",
    "user_id",
    "ts_start",
    "ts_end",
    "night_record_id",
    "n_samples",
    "sampling_hz_median",
    "n_gaps",
    "duration_s",
    "source_sha256",
]


def _load_known_patient_ids() -> set[str]:
    reg = read_patient_registry()
    return set(str(x).strip() for x in reg["patient_id"].tolist() if str(x).strip())


def run_bronze(
    raw_dir: Path = RAW_DIR,
    limit: int | None = None,
    verbose: bool = True,
    autoreg: bool = True,
) -> pd.DataFrame:
    """
    Ejecuta el pipeline Bronze sobre todos los xlsx en raw_dir.

    Args:
        raw_dir: carpeta con los .xlsx.
        limit: si se pasa, sólo procesa los primeros N archivos (para smoke tests).
        verbose: imprime por consola el progreso.
        autoreg: si True, antes del loop de ingest se escanean todos los xlsx
                 para detectar user_ids nuevos y se crean filas stub en
                 patient_registry.csv y clinical.csv. Default=True.

    Returns:
        DataFrame con el log por archivo (mismo contenido que bronze_log.csv).
    """
    ensure_dirs()

    xlsx_files = sorted(raw_dir.glob("*.xlsx"))
    if limit is not None:
        xlsx_files = xlsx_files[:limit]
    if verbose:
        print(f"[bronze] .xlsx a procesar: {len(xlsx_files)}")

    # --- Pre-pass: auto-registro de pacientes nuevos (opcional) -------------
    autoreg_result: dict[str, list[str]] = {}
    if autoreg and xlsx_files:
        if verbose:
            print(f"[bronze] autoreg: escaneando user_id de {len(xlsx_files)} xlsx...")
        user_id_map = scan_xlsx_user_ids(xlsx_files)
        autoreg_result = register_stubs_for_unknown_ids(user_id_map, verbose=verbose)

    # Re-leer registry DESPUÉS del autoreg para que ingest_one vea los nuevos.
    known = _load_known_patient_ids()
    if verbose:
        print(f"[bronze] known patient_ids en registry: {len(known)}")

    t0 = time.time()
    rows = []
    for i, xlsx in enumerate(xlsx_files, start=1):
        row = ingest_one(xlsx, known)
        rows.append(row)
        if verbose:
            msg = f"[{i:>4}/{len(xlsx_files)}] {xlsx.name} → {row['status']}"
            if row["status"] == "OK":
                msg += f"  nrid={row['night_record_id']}  n={row['n_samples']}  gaps={row['n_gaps']}"
            elif row["status"] == "FAIL":
                msg += f"  ERROR: {row['error']}"
            elif row["status"] == "SKIP_COHORT":
                msg += f"  user_id={row['user_id']} (fuera del cohort)"
            print(msg)

    elapsed = time.time() - t0

    # --- Escribir log csv ----------------------------------------------------
    df = pd.DataFrame(rows, columns=LOG_COLS)
    BRONZE_LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(BRONZE_LOG_CSV, index=False)

    # --- Gate JSON -----------------------------------------------------------
    ok = int((df["status"] == "OK").sum())
    fail = int((df["status"] == "FAIL").sum())
    skip = int((df["status"] == "SKIP_COHORT").sum())

    # Conteos por paciente (sólo OK)
    by_patient = (
        df[df["status"] == "OK"]
        .groupby("user_id", dropna=False)
        .size()
        .to_dict()
    )

    gate = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "raw_dir": str(raw_dir),
        "n_xlsx": int(len(df)),
        "n_ok": ok,
        "n_fail": fail,
        "n_skip_cohort": skip,
        "n_bronze_parquets": ok,  # 1 signals + 1 classical por OK, pero contamos noches
        "elapsed_s": round(elapsed, 2),
        "nights_per_patient": {str(k): int(v) for k, v in sorted(by_patient.items())},
        "autoreg": {
            "enabled": bool(autoreg),
            "n_new_patients": len(autoreg_result),
            "new_patient_ids": sorted(autoreg_result.keys()),
        },
    }
    with open(BRONZE_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2, ensure_ascii=False)

    if verbose:
        print("")
        print("=" * 60)
        print(f"[bronze] DONE en {elapsed:.1f}s — OK={ok}  FAIL={fail}  SKIP={skip}")
        print(f"[bronze] log:  {BRONZE_LOG_CSV}")
        print(f"[bronze] gate: {BRONZE_GATE_JSON}")

    return df


def main() -> int:
    # CLI mínima: --limit N para smoke tests, --no-autoreg para desactivar autoreg
    limit = None
    autoreg = True
    args = sys.argv[1:]
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("uso: python -m pac.bronze [--limit N] [--no-autoreg]")
            return 2
    if "--no-autoreg" in args:
        autoreg = False
    df = run_bronze(limit=limit, autoreg=autoreg)
    # Exit code = 0 si hubo al menos una noche OK, 1 si ninguna.
    return 0 if (df["status"] == "OK").any() else 1


if __name__ == "__main__":
    sys.exit(main())
