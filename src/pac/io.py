"""
PAC_v2 — helpers de I/O.

Objetivos:
  - Lectura/escritura de parquet (bronze/silver) con pyarrow.
  - Lectura/escritura de los 3 CSV de identidad (sep=";").
  - Parseo robusto de fechas dd/mm/yy con regla YEAR_PIVOT.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

from pac.config import (
    CLINICAL_COLS,
    CLINICAL_CSV,
    CSV_SEP,
    PATIENT_REGISTRY_CSV,
    REGISTRY_COLS,
    YEAR_PIVOT,
)


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------
def parse_birthdate(raw: str, year_pivot: int = YEAR_PIVOT) -> Tuple[Optional[date], int]:
    """
    Parsea una fecha 'd/m/yy' o 'dd/mm/yy' o 'dd/mm/yyyy' y la devuelve como
    date ISO (YYYY-MM-DD), junto con un flag de auditoría.

    Reglas:
      - Si el año tiene 2 dígitos: yy <= year_pivot → 20yy, si no → 19yy.
      - flag_audit = 1 cuando el año resuelto es >= 2000 (caso potencialmente ambiguo).
      - Si el año viene con 4 dígitos, flag_audit = 0 siempre.

    Retorna (fecha, flag_audit). Si no se puede parsear → (None, 0).
    """
    if raw is None:
        return None, 0
    s = str(raw).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None, 0

    parts = s.split("/")
    if len(parts) != 3:
        return None, 0

    try:
        d = int(parts[0])
        m = int(parts[1])
        y_raw = parts[2].strip()
        y_int = int(y_raw)
    except ValueError:
        return None, 0

    if len(y_raw) <= 2:
        # 2 dígitos: aplicar pivot
        if y_int <= year_pivot:
            year = 2000 + y_int
        else:
            year = 1900 + y_int
        flag = 1 if year >= 2000 else 0
    else:
        year = y_int
        flag = 0

    try:
        return date(year, m, d), flag
    except ValueError:
        return None, 0


# ---------------------------------------------------------------------------
# CSVs de identidad
# ---------------------------------------------------------------------------
def _read_identity_csv(path: Path, cols: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, sep=CSV_SEP, dtype=str, keep_default_na=False)
    # reordenar según contrato; columnas faltantes → vacías
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols]


def read_patient_registry() -> pd.DataFrame:
    return _read_identity_csv(PATIENT_REGISTRY_CSV, REGISTRY_COLS)


def read_clinical() -> pd.DataFrame:
    return _read_identity_csv(CLINICAL_CSV, CLINICAL_COLS)


def write_identity_csv(df: pd.DataFrame, path: Path, cols: list[str]) -> None:
    """Escribe un CSV de identidad con el contrato de columnas y sep=';'."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = ""
    out = out[cols]
    out.to_csv(path, sep=CSV_SEP, index=False)


# ---------------------------------------------------------------------------
# Parquet (para uso futuro — bronze/silver)
# ---------------------------------------------------------------------------
def read_parquet(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
