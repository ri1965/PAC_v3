"""
PAC_v2 — Etapa 2 Silver: helpers de QC (funciones puras).

Sin I/O. Sin dependencias de config excepto las constantes de umbrales
cuando el caller las pasa explícitas. Diseño: cada función toma un DataFrame
(o un escalar) + config, devuelve un DataFrame enriquecido o un dict.

Las funciones son idempotentes: llamarlas dos veces con el mismo input
produce el mismo output.

Decisiones de diseño (cerradas con Roberto Q1–Q8):
  - Range QC crea 2 columnas nuevas ({col}_invalid, {col}_clean) sin tocar
    la original. Razón: preservar la señal cruda + hacer explícito qué se
    marcó como inválido.
  - Gaps se mide como coverage ratio + max_contiguous_gap_s (no como
    conteo). Más robusto que n_gaps porque un gap de 30 min es muy distinto
    de 30 gaps de 1s.
  - Duración usa dual-flag (aborted ⊂ short) para distinguir estudios
    abortados (<1h) de estudios cortos-pero-válidos (1-3h).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Range QC — aplica límites fisiológicos sobre una columna de señal.
# ---------------------------------------------------------------------------
def apply_range_qc(
    df: pd.DataFrame,
    col: str,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
) -> pd.DataFrame:
    """
    Agrega dos columnas al DataFrame:
      - `{col}_invalid` (bool): True donde el valor está fuera de [vmin, vmax].
      - `{col}_clean` (float64): copia de `col` con NaN donde invalid.

    Args:
        df: DataFrame con la columna `col` (numérica).
        col: nombre de la columna a evaluar.
        vmin: límite inferior inclusivo. Si None → sin límite inferior.
        vmax: límite superior inclusivo. Si None → sin límite superior.

    Returns:
        Copia del DataFrame con las 2 columnas nuevas.

    Notas:
      - NaNs pre-existentes en `col` se consideran inválidos (propagación
        natural del predicado). Tanto `{col}_invalid=True` como
        `{col}_clean=NaN`.
      - `{col}_clean` es float64 aunque `col` fuera int, porque int no
        soporta NaN. Esto es estándar en pandas.
      - La columna original `col` no se modifica.
    """
    if col not in df.columns:
        raise KeyError(f"columna '{col}' no está en el DataFrame")
    if vmin is None and vmax is None:
        raise ValueError("al menos uno de vmin/vmax debe estar definido")

    out = df.copy()
    series = out[col]

    # Construir máscara de inválidos. NaN se considera inválido.
    invalid = series.isna()
    if vmin is not None:
        invalid = invalid | (series < vmin)
    if vmax is not None:
        invalid = invalid | (series > vmax)

    out[f"{col}_invalid"] = invalid.astype(bool)

    # Clean column: series con NaN donde invalid. Force float64 para NaN-safe.
    clean = series.astype("float64").copy()
    clean[invalid] = np.nan
    out[f"{col}_clean"] = clean

    return out


# ---------------------------------------------------------------------------
# Gaps — mide cobertura temporal y mayor hueco contiguo.
# ---------------------------------------------------------------------------
def compute_gap_metrics(
    df: pd.DataFrame,
    ts_col: str = "timestamp",
    sampling_hz: float = 1.0,
) -> dict:
    """
    Calcula métricas de cobertura temporal sobre una serie timestampeada.

    Asume que `df[ts_col]` es un datetime64 ordenado y que el sampling
    nominal es `sampling_hz` (Hz). El intervalo nominal entre muestras
    consecutivas es `1/sampling_hz` segundos.

    Returns:
        {
          "n_samples":           int,   # len(df)
          "duration_s":          float, # (ts_max - ts_min).total_seconds()
          "n_expected":          int,   # duration_s * sampling_hz + 1
          "coverage":            float, # n_samples / n_expected (∈ [0,1])
          "n_gaps":              int,   # cantidad de huecos (diff > nominal)
          "max_contiguous_gap_s": int,  # max duración de un solo hueco (s)
        }

    Edge cases:
      - Si `df` está vacío → todos los campos = 0 / 0.0.
      - Si tiene 1 sola fila → duration_s=0, coverage=1.0, n_gaps=0.
      - Si no hay gaps → max_contiguous_gap_s=0.
    """
    n_samples = int(len(df))
    if n_samples == 0:
        return {
            "n_samples": 0,
            "duration_s": 0.0,
            "n_expected": 0,
            "coverage": 0.0,
            "n_gaps": 0,
            "max_contiguous_gap_s": 0,
        }

    ts = df[ts_col]
    duration_s = float((ts.iloc[-1] - ts.iloc[0]).total_seconds())

    if n_samples == 1 or duration_s == 0.0:
        return {
            "n_samples": n_samples,
            "duration_s": duration_s,
            "n_expected": n_samples,
            "coverage": 1.0,
            "n_gaps": 0,
            "max_contiguous_gap_s": 0,
        }

    nominal_dt = 1.0 / sampling_hz
    n_expected = int(round(duration_s * sampling_hz)) + 1
    coverage = float(n_samples) / float(n_expected) if n_expected > 0 else 0.0

    # Diffs en segundos entre muestras consecutivas.
    dt_s = ts.diff().dt.total_seconds().iloc[1:]

    # Gap = diff mayor que el nominal (con pequeña tolerancia).
    # Un gap de N segundos (N > nominal) implica que se perdieron
    # (N/nominal - 1) muestras. La "duración del hueco" en segundos
    # es N - nominal.
    tol = 1e-6
    gap_mask = dt_s > (nominal_dt + tol)
    n_gaps = int(gap_mask.sum())

    if n_gaps > 0:
        max_gap_s = int(round(float((dt_s[gap_mask] - nominal_dt).max())))
    else:
        max_gap_s = 0

    return {
        "n_samples": n_samples,
        "duration_s": duration_s,
        "n_expected": n_expected,
        "coverage": coverage,
        "n_gaps": n_gaps,
        "max_contiguous_gap_s": max_gap_s,
    }


# ---------------------------------------------------------------------------
# Duración — dual-flag aborted/short.
# ---------------------------------------------------------------------------
def compute_duration_flags(
    duration_s: float,
    aborted_s: int,
    min_s: int,
) -> dict:
    """
    Dual-flag de duración de noche:

      - qc_duration_aborted: True si duration_s < aborted_s.
      - qc_duration_short:   True si duration_s < min_s (incluye aborted).

    Tal como acordado (Q4, opción 4a):
      < aborted_s            → aborted=True,  short=True
      aborted_s ≤ d < min_s  → aborted=False, short=True
      d ≥ min_s              → aborted=False, short=False

    Args:
        duration_s: duración de la noche en segundos.
        aborted_s:  umbral para marcar como aborted (típico 3600 = 1h).
        min_s:      umbral para marcar como short (típico 10800 = 3h).

    Returns:
        {"qc_duration_aborted": bool, "qc_duration_short": bool}
    """
    if aborted_s > min_s:
        raise ValueError(
            f"aborted_s ({aborted_s}) debe ser ≤ min_s ({min_s})"
        )
    aborted = duration_s < aborted_s
    short = duration_s < min_s
    return {
        "qc_duration_aborted": bool(aborted),
        "qc_duration_short": bool(short),
    }


# ---------------------------------------------------------------------------
# Coverage flags — combinador de gap_metrics + umbrales → flags de gate.
# ---------------------------------------------------------------------------
def compute_coverage_flags(
    gap_metrics: dict,
    coverage_min: float,
    max_gap_s: int,
) -> dict:
    """
    Dado el dict de `compute_gap_metrics`, decide los flags de paso/falla
    contra los umbrales de configuración.

    Returns:
        {"qc_coverage_ok": bool, "qc_max_gap_ok": bool}
    """
    return {
        "qc_coverage_ok": bool(gap_metrics["coverage"] >= coverage_min),
        "qc_max_gap_ok":  bool(gap_metrics["max_contiguous_gap_s"] <= max_gap_s),
    }
