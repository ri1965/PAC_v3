"""
Etapa 5 paso 2 — Build gold/events.parquet.

Consolida los 560 events/{NR}_edos.parquet en una sola tabla wide-todo
siguiendo la filosofía data-lake (Roberto): preservar TODO lo medido a
nivel evento + agregar bloques transversales para análisis directo sin
joins:

  1. Identidad de paciente: `user_id` (lookup en silver_qc_summary).
  2. Flags de cohorte (cohorte B): in_quality, in_strict, in_high_tst,
     flag_for_review, b2_fail. Calculados a partir de pac.cohorts.
  3. Trazabilidad de modelo: model_version (leído de models/MANIFEST.json).

Output:
  gold/events.parquet  — schema GOLD_EVENTS_SCHEMA (32 cols).

Uso:
  python scripts/build_events_gold.py            # full build
  python scripts/build_events_gold.py --dry-run  # no escribe disk
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pac.cohorts import (  # noqa: E402
    get_cohort_high_tst,
    get_cohort_quality,
    get_cohort_strict,
    _b2_fail_excluded_nrs,
    _flag_for_review_nrs,
)
from pac.schemas import (  # noqa: E402
    GOLD_EVENTS_SCHEMA,
    validate_events_edos,
    validate_events_gold,
)

EVENTS_DIR = REPO_ROOT / "events"
GOLD_DIR = REPO_ROOT / "gold"
SILVER_QC = REPO_ROOT / "reports" / "silver_qc_summary.csv"
MANIFEST_PATH = REPO_ROOT / "models" / "MANIFEST.json"

OUT_PATH = GOLD_DIR / "events.parquet"


def _load_user_map() -> dict:
    """night_record_id → user_id desde silver_qc_summary."""
    if not SILVER_QC.exists():
        raise FileNotFoundError(f"No existe {SILVER_QC}")
    df = pd.read_csv(SILVER_QC, usecols=["night_record_id", "user_id"])
    df["user_id"] = df["user_id"].astype(str)
    return dict(zip(df["night_record_id"], df["user_id"]))


def _load_model_version() -> str:
    """Lee model_version del manifest activo."""
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No existe {MANIFEST_PATH}. Generar con scripts/generate_manifest.py"
        )
    with open(MANIFEST_PATH) as f:
        return json.load(f)["model_version"]


def build_events_gold(verbose: bool = True) -> pd.DataFrame:
    """Construye y devuelve el DataFrame de events_gold (sin escribir disk)."""
    edos_files = sorted(EVENTS_DIR.glob("NR_*_edos.parquet"))
    if not edos_files:
        raise RuntimeError(f"No se encontraron events/NR_*_edos.parquet en {EVENTS_DIR}")

    user_map = _load_user_map()
    model_version = _load_model_version()

    # Cohortes (sets). Materializar una vez para join O(1) por NR.
    nrs_quality = get_cohort_quality()
    nrs_strict = get_cohort_strict()
    nrs_high_tst = get_cohort_high_tst(min_tst_h=4.0)
    nrs_b2 = set(_b2_fail_excluded_nrs())
    nrs_flag = set(_flag_for_review_nrs())

    if verbose:
        print(f"[events_gold] leyendo {len(edos_files)} archivos events/_edos.parquet...")

    parts = []
    n_validated = 0
    for fp in edos_files:
        df = pd.read_parquet(fp)
        # Validación dura: cada archivo fuente debe respetar EVENTS_EDOS_SCHEMA
        validate_events_edos(df, source=str(fp.relative_to(REPO_ROOT)), strict=True)
        n_validated += 1
        parts.append(df)

    if verbose:
        print(f"[events_gold] validadas {n_validated} fuentes contra EVENTS_EDOS_SCHEMA")

    out = pd.concat(parts, ignore_index=True)

    # Bloque trazabilidad
    out["user_id"] = out["night_record_id"].map(user_map)
    out["model_version"] = model_version

    # Bloque flags de cohorte (vectorizado)
    out["in_quality"] = out["night_record_id"].isin(nrs_quality)
    out["in_strict"] = out["night_record_id"].isin(nrs_strict)
    out["in_high_tst"] = out["night_record_id"].isin(nrs_high_tst)
    out["flag_for_review"] = out["night_record_id"].isin(nrs_flag)
    out["b2_fail"] = out["night_record_id"].isin(nrs_b2)

    # Reordenar columnas en orden canónico del schema
    out = out[list(GOLD_EVENTS_SCHEMA.keys())]

    # Validación final del output
    validate_events_gold(out, source="<build_events_gold>", strict=True)

    if verbose:
        n_missing_user = out["user_id"].isna().sum()
        print(f"[events_gold] OK — {len(out):,} filas × {len(out.columns)} cols")
        print(f"  noches únicas: {out['night_record_id'].nunique()}")
        print(f"  user_ids únicos: {out['user_id'].nunique()}")
        if n_missing_user:
            print(f"  WARN: {n_missing_user} filas sin user_id (NRs no en silver_qc)")
        print(f"  in_quality:      {int(out['in_quality'].sum()):,} filas")
        print(f"  in_strict:       {int(out['in_strict'].sum()):,} filas")
        print(f"  in_high_tst:     {int(out['in_high_tst'].sum()):,} filas")
        print(f"  flag_for_review: {int(out['flag_for_review'].sum()):,} filas")
        print(f"  b2_fail:         {int(out['b2_fail'].sum()):,} filas")
        print(f"  model_version:   {model_version}")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Construye y valida pero no escribe gold/events.parquet.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Silencia output (solo errores).",
    )
    args = parser.parse_args()

    df = build_events_gold(verbose=not args.quiet)

    if args.dry_run:
        if not args.quiet:
            print(f"[events_gold] --dry-run: NO escribo {OUT_PATH.relative_to(REPO_ROOT)}")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    if not args.quiet:
        print(f"[events_gold] escrito {OUT_PATH.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
