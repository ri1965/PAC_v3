"""
Etapa 5 paso 8 — Orquestador de Gold.

Corre el pipeline completo de Gold en orden canónico, con gate entre
pasos: si uno falla, abortar (no contamina los siguientes).

Pipeline:
  1. build_events_gold.py            → gold/events.parquet
  2. build_events_curves_gold.py     → gold/events_curves.parquet
  3. build_states_gold.py            → gold/states.parquet
  4. build_nights_gold.py            → gold/nights.parquet (depende de 1+3)
  5. build_patients_gold.py          → gold/patients.parquet (depende de 1+3+4)
  6. build_gold_manifest.py          → gold/MANIFEST.json
  7. build_nights_columns_doc.py     → gold/nights_columns.json

Política: pre-requisitos chequeados antes de arrancar (events/, states/,
silver_qc, models/MANIFEST.json). Cada paso corre como subprocess con
PYTHONPATH=src y cwd=REPO_ROOT — los scripts ya validan sus inputs
internamente vía pac.schemas.

Uso:
  python scripts/build_gold_all.py            # full pipeline
  python scripts/build_gold_all.py --dry-run  # plan, no ejecuta
  python scripts/build_gold_all.py --quiet    # output mínimo
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PIPELINE = [
    ("Events EDOs",    ["python", "scripts/build_events_gold.py"]),
    ("Events Curves",  ["python", "scripts/build_events_curves_gold.py"]),
    ("States",         ["python", "scripts/build_states_gold.py"]),
    ("Nights",         ["python", "scripts/build_nights_gold.py"]),
    ("Patients",       ["python", "scripts/build_patients_gold.py"]),
    ("Gold Manifest",  ["python", "scripts/build_gold_manifest.py"]),
    ("Nights Columns", ["python", "scripts/build_nights_columns_doc.py"]),
]


def _check_prerequisites() -> list:
    """Devuelve lista de pre-requisitos faltantes (vacía si todo OK)."""
    missing = []
    if not list((REPO_ROOT / "events").glob("NR_*_edos.parquet")):
        missing.append("events/NR_*_edos.parquet (correr Etapa 3 primero)")
    if not list((REPO_ROOT / "states").glob("NR_*.parquet")):
        missing.append("states/NR_*.parquet (correr Etapa 4 paso 7 primero)")
    if not (REPO_ROOT / "reports" / "silver_qc_summary.csv").exists():
        missing.append("reports/silver_qc_summary.csv (Etapa 2)")
    if not (REPO_ROOT / "models" / "MANIFEST.json").exists():
        missing.append("models/MANIFEST.json (correr scripts/generate_manifest.py)")
    if not (REPO_ROOT / "patients" / "clinical.csv").exists():
        missing.append("patients/clinical.csv (datos clínicos)")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Muestra el plan, no ejecuta.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suprime el banner y output detallado.")
    args = parser.parse_args()

    if not args.quiet:
        print("=" * 70)
        print("PAC_v2 — Pipeline Gold (Etapa 5)")
        print("=" * 70)

    missing = _check_prerequisites()
    if missing:
        print("ERROR — pre-requisitos faltantes:")
        for m in missing:
            print(f"  ✗ {m}")
        return 1

    if not args.quiet:
        print("✓ Pre-requisitos OK")
        print()
        print("Pipeline:")
        for i, (label, cmd) in enumerate(PIPELINE, 1):
            print(f"  {i}. {label:18s} $ {' '.join(cmd)}")
        print()

    if args.dry_run:
        if not args.quiet:
            print("--dry-run: NO se ejecuta ningún paso.")
        return 0

    env = {**os.environ, "PYTHONPATH": "src"}
    t0 = time.time()
    for i, (label, cmd) in enumerate(PIPELINE, 1):
        if not args.quiet:
            print(f"[{i}/{len(PIPELINE)}] {label}")
            print(f"  $ {' '.join(cmd)}")
        ts = time.time()
        try:
            res = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        except Exception as e:
            print(f"  ✗ paso {i} excepción: {e}")
            return 1
        if res.returncode != 0:
            print(f"  ✗ paso {i} falló (returncode={res.returncode}). Abortando.")
            return res.returncode
        if not args.quiet:
            print(f"  ✓ paso {i} OK ({time.time() - ts:.1f}s)")
            print()

    elapsed = time.time() - t0
    if not args.quiet:
        print("=" * 70)
        print(f"✓ Pipeline Gold completo — {elapsed:.1f}s")
        print("=" * 70)
        print()
        print("Outputs en gold/:")
        for f in sorted((REPO_ROOT / "gold").iterdir()):
            if f.name.startswith("."):
                continue
            size_kb = f.stat().st_size / 1024
            print(f"  {f.name:35s} ({size_kb:>10,.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
