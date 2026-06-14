#!/usr/bin/env python3
"""
scripts/bootstrap_patient_files.py
----------------------------------
Bootstrap one-shot de Etapa 0.

Toma el CSV legacy `datos_paciente.csv` (sep=';') y lo parte en los 2 archivos
del modelo de identidad:

  - patients/patient_registry.csv  (PII, local)
  - patients/clinical.csv          (datos clínicos)

Se ejecuta UNA sola vez al inicio del proyecto. Luego los CSVs se mantienen
a mano o con utilitarios específicos.

Uso:
    python scripts/bootstrap_patient_files.py [--source PATH_AL_CSV_LEGACY]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

# Permitir correr el script desde la raíz del proyecto
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.config import (  # noqa: E402
    CLINICAL_COLS,
    CLINICAL_CSV,
    CSV_SEP,
    PATIENT_REGISTRY_CSV,
    REGISTRY_COLS,
    ensure_dirs,
)
from pac.io import parse_birthdate, write_identity_csv  # noqa: E402


DEFAULT_LEGACY = Path("/sessions/cool-serene-albattani/mnt/uploads/datos_paciente.csv")


SEX_MAP = {
    "masculino": "M",
    "femenino": "F",
    "m": "M",
    "f": "F",
}


def _norm_sex(v: str) -> str:
    if v is None:
        return ""
    key = str(v).strip().lower()
    return SEX_MAP.get(key, "")


def _to_int_str(v) -> str:
    """Devuelve el entero como string; '' si no parsea."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none"}:
        return ""
    try:
        return str(int(float(s)))
    except ValueError:
        return ""


def load_legacy(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No existe el CSV legacy: {path}")
    df = pd.read_csv(path, sep=CSV_SEP, dtype=str, keep_default_na=False)
    # columnas esperadas
    expected = {
        "id_paciente", "nombre", "apellido", "sexo", "fecha_nacimiento",
        "peso", "talla", "apnea", "diabetes", "hta", "marcapasos",
    }
    missing = sorted(expected - set(df.columns))
    if missing:
        raise ValueError(f"Columnas faltantes en {path}: {missing}")
    return df


def build_registry(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["patient_id"] = df["id_paciente"].astype(str).str.strip()
    out["nombre"] = df["nombre"].astype(str).str.strip()
    out["apellido"] = df["apellido"].astype(str).str.strip()

    parsed = df["fecha_nacimiento"].apply(parse_birthdate)
    out["fecha_nacimiento"] = [
        (d.isoformat() if d is not None else "") for d, _ in parsed
    ]
    out["_flag_audit"] = [flag for _, flag in parsed]
    return out


def build_clinical(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["patient_id"] = df["id_paciente"].astype(str).str.strip()
    out["sexo"] = df["sexo"].apply(_norm_sex)
    out["peso_kg"] = df["peso"].apply(_to_int_str)
    out["talla_cm"] = df["talla"].apply(_to_int_str)
    out["apnea_prev"] = df["apnea"].apply(_to_int_str)
    out["diabetes"] = df["diabetes"].apply(_to_int_str)
    out["hta"] = df["hta"].apply(_to_int_str)
    out["marcapasos"] = df["marcapasos"].apply(_to_int_str)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap de patients/*.csv desde CSV legacy.")
    ap.add_argument("--source", type=Path, default=DEFAULT_LEGACY,
                    help=f"CSV legacy (default: {DEFAULT_LEGACY})")
    ap.add_argument("--force", action="store_true",
                    help="Sobrescribir si ya existen patient_registry.csv o clinical.csv.")
    args = ap.parse_args()

    ensure_dirs()

    # Chequeo anti-pisada
    for p in (PATIENT_REGISTRY_CSV, CLINICAL_CSV):
        if p.exists() and not args.force:
            print(f"[ABORT] Ya existe {p}. Usar --force para sobrescribir.", file=sys.stderr)
            return 2

    df = load_legacy(args.source)
    print(f"[OK] Legacy cargado: {args.source} — {len(df)} filas")

    registry_full = build_registry(df)
    registry_out = registry_full[REGISTRY_COLS]

    clinical_out = build_clinical(df)
    clinical_out = clinical_out[CLINICAL_COLS]

    # WARNING (no persistido): casos de fecha con año resuelto >= 2000 → revisión humana sugerida
    ambiguous = registry_full.loc[registry_full["_flag_audit"] == 1,
                                  ["patient_id", "nombre", "apellido", "fecha_nacimiento"]]
    if len(ambiguous):
        print(f"[WARN] {len(ambiguous)} paciente(s) con año de nacimiento >= 2000 — revisar manualmente:")
        for _, r in ambiguous.iterrows():
            print(f"         · id={r['patient_id']:>4}  {r['nombre']} {r['apellido']} → {r['fecha_nacimiento']}")

    # Escribir registry + clinical
    write_identity_csv(registry_out, PATIENT_REGISTRY_CSV, REGISTRY_COLS)
    print(f"[OK] Escrito {PATIENT_REGISTRY_CSV}  ({len(registry_out)} filas)")

    write_identity_csv(clinical_out, CLINICAL_CSV, CLINICAL_COLS)
    print(f"[OK] Escrito {CLINICAL_CSV}  ({len(clinical_out)} filas)")

    print("[DONE] Bootstrap completado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
