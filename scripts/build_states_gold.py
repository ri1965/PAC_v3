"""
Etapa 5 paso 4 — Build gold/states.parquet.

Stackea los 560 states/{NR}.parquet en una sola tabla long-format.
Mismo patrón que build_events_gold:
  - 15 cols base (STATES_SCHEMA: identidad + temporal + cluster + contexto)
  - + user_id (lookup silver_qc)
  - + model_version (del MANIFEST)
  - + 5 flags de cohorte B (in_quality, in_strict, in_high_tst,
    flag_for_review, b2_fail)

Total: 22 cols (GOLD_STATES_SCHEMA).

Esta tabla habilita el join temporal `events_gold × states_gold` que
quedó deferido en Q4 (state-context-at-event reconstruible).

Output:
  gold/states.parquet  — ~600k filas × 22 cols.

Uso:
  python scripts/build_states_gold.py            # full build
  python scripts/build_states_gold.py --dry-run  # no escribe disk
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
    GOLD_STATES_SCHEMA,
    validate_states,
    validate_states_gold,
)

STATES_DIR = REPO_ROOT / "states"
GOLD_DIR = REPO_ROOT / "gold"
SILVER_QC = REPO_ROOT / "reports" / "silver_qc_summary.csv"
MANIFEST_PATH = REPO_ROOT / "models" / "MANIFEST.json"

OUT_PATH = GOLD_DIR / "states.parquet"


def _load_user_map() -> dict:
    df = pd.read_csv(SILVER_QC, usecols=["night_record_id", "user_id"])
    df["user_id"] = df["user_id"].astype(str)
    return dict(zip(df["night_record_id"], df["user_id"]))


def _load_model_version() -> str:
    with open(MANIFEST_PATH) as f:
        return json.load(f)["model_version"]


def build_states_gold(verbose: bool = True) -> pd.DataFrame:
    """Construye y devuelve el DataFrame de states_gold (sin escribir disk)."""
    state_files = sorted(STATES_DIR.glob("NR_*.parquet"))
    if not state_files:
        raise RuntimeError(f"No se encontraron states/NR_*.parquet en {STATES_DIR}")

    user_map = _load_user_map()
    model_version = _load_model_version()

    nrs_quality = get_cohort_quality()
    nrs_strict = get_cohort_strict()
    nrs_high_tst = get_cohort_high_tst(min_tst_h=4.0)
    nrs_b2 = set(_b2_fail_excluded_nrs())
    nrs_flag = set(_flag_for_review_nrs())

    if verbose:
        print(f"[states_gold] leyendo {len(state_files)} archivos states/...")

    parts = []
    n_validated = 0
    for fp in state_files:
        df = pd.read_parquet(fp)
        validate_states(df, source=str(fp.relative_to(REPO_ROOT)), strict=True)
        n_validated += 1
        parts.append(df)

    if verbose:
        print(f"[states_gold] validadas {n_validated} fuentes contra STATES_SCHEMA")

    out = pd.concat(parts, ignore_index=True)

    out["user_id"] = out["night_record_id"].map(user_map)
    out["model_version"] = model_version
    out["in_quality"] = out["night_record_id"].isin(nrs_quality)
    out["in_strict"] = out["night_record_id"].isin(nrs_strict)
    out["in_high_tst"] = out["night_record_id"].isin(nrs_high_tst)
    out["flag_for_review"] = out["night_record_id"].isin(nrs_flag)
    out["b2_fail"] = out["night_record_id"].isin(nrs_b2)

    out = out[list(GOLD_STATES_SCHEMA.keys())]

    validate_states_gold(out, source="<build_states_gold>", strict=True)

    if verbose:
        n_missing_user = out["user_id"].isna().sum()
        print(f"[states_gold] OK — {len(out):,} filas × {len(out.columns)} cols")
        print(f"  noches únicas:   {out['night_record_id'].nunique()}")
        print(f"  user_ids únicos: {out['user_id'].nunique()}")
        if n_missing_user:
            print(f"  WARN: {n_missing_user} filas sin user_id (NRs no en silver_qc)")
        # Distribución por escala
        scale_counts = out["scale"].value_counts().to_dict()
        print(f"  por escala:      {scale_counts}")
        # Distribución de cohorte
        print(f"  in_quality:      {int(out['in_quality'].sum()):,} filas")
        print(f"  in_strict:       {int(out['in_strict'].sum()):,} filas")
        print(f"  in_high_tst:     {int(out['in_high_tst'].sum()):,} filas")
        print(f"  flag_for_review: {int(out['flag_for_review'].sum()):,} filas")
        print(f"  b2_fail:         {int(out['b2_fail'].sum()):,} filas")
        print(f"  model_version:   {model_version}")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    df = build_states_gold(verbose=not args.quiet)

    if args.dry_run:
        if not args.quiet:
            print(f"[states_gold] --dry-run: NO escribo {OUT_PATH.relative_to(REPO_ROOT)}")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    if not args.quiet:
        print(f"[states_gold] escrito {OUT_PATH.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
