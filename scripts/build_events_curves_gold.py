"""
Etapa 5 paso 3 — Build gold/events_curves.parquet.

Consolida los 560 events/{NR}_edo_curves.parquet en una sola tabla
list-typed (5 cols). Schema = GOLD_EVENTS_CURVES_SCHEMA = igual al
schema de events_curves (sin agregar flags ni user_id: esos viven en
events_gold y se acceden por join sobre (night_record_id, ts_start)).

Output:
  gold/events_curves.parquet  — 5 cols × ~85k filas, list-typed.

Uso:
  python scripts/build_events_curves_gold.py            # full build
  python scripts/build_events_curves_gold.py --dry-run  # no escribe disk
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pac.schemas import (  # noqa: E402
    GOLD_EVENTS_CURVES_SCHEMA,
    validate_events_curves,
    validate_events_curves_gold,
)

EVENTS_DIR = REPO_ROOT / "events"
GOLD_DIR = REPO_ROOT / "gold"
OUT_PATH = GOLD_DIR / "events_curves.parquet"


def build_events_curves_gold(verbose: bool = True) -> pd.DataFrame:
    """Construye y devuelve el DataFrame de events_curves_gold."""
    curve_files = sorted(EVENTS_DIR.glob("NR_*_edo_curves.parquet"))
    if not curve_files:
        raise RuntimeError(
            f"No se encontraron events/NR_*_edo_curves.parquet en {EVENTS_DIR}"
        )

    if verbose:
        print(f"[events_curves_gold] leyendo {len(curve_files)} archivos...")

    parts = []
    for fp in curve_files:
        df = pd.read_parquet(fp)
        validate_events_curves(df, source=str(fp.relative_to(REPO_ROOT)), strict=True)
        parts.append(df)

    out = pd.concat(parts, ignore_index=True)
    # Reordenar al orden canónico (defensa contra surprises)
    out = out[list(GOLD_EVENTS_CURVES_SCHEMA.keys())]

    validate_events_curves_gold(
        out, source="<build_events_curves_gold>", strict=True
    )

    if verbose:
        print(f"[events_curves_gold] OK — {len(out):,} filas × {len(out.columns)} cols")
        print(f"  noches únicas: {out['night_record_id'].nunique()}")
        # sanity: longitud de las curvas
        sample_spo2 = out["spo2_curve"].iloc[0]
        sample_hr = out["hr_curve"].iloc[0]
        sample_mov = out["mov_curve"].iloc[0]
        print(
            f"  longitudes (primer EDO): "
            f"spo2={len(sample_spo2)}, hr={len(sample_hr)}, mov={len(sample_mov)}"
        )

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    df = build_events_curves_gold(verbose=not args.quiet)

    if args.dry_run:
        if not args.quiet:
            print(f"[events_curves_gold] --dry-run: NO escribo {OUT_PATH.relative_to(REPO_ROOT)}")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    if not args.quiet:
        print(
            f"[events_curves_gold] escrito {OUT_PATH.relative_to(REPO_ROOT)} ({size_mb:.1f} MB)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
