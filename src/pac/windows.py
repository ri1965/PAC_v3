"""
PAC_v2 — Etapa 4 · ventaneo multiescala (helpers puros).

Particiona cada noche en ventanas disjuntas de duración fija por escala
(short=30s, medium=5min, long=30min) y produce el feature vector canónico
de 24 dimensiones listo para el KMeans de estados PAC.

Contrato de entrada:
  - silver_df: DataFrame de `silver/{NR}.parquet` (9 cols, 1 Hz, timestamps
    datetime64[ns], señales *_clean con NaN donde inválido, sleep_stage Int64
    con valores {0,1,2,3}).
  - edos_df: DataFrame de `events/{NR}_edos.parquet` (con ts_start,
    morphotype ∈ {α,β,γ,δ,None}, ird_event).

Contrato de salida (DataFrame por noche+escala):
  Metadata  (7 cols): scale, window_idx, t_start, t_end, n_samples_raw,
                      coverage, is_tail.
  Features (24 cols): las 24 dimensiones canónicas declaradas en
                      PAC_WINDOW_FEATURES (15 signal + 6 morfo + 3 sleep).

Decisiones de diseño (Q1..Q6, aprobadas por Roberto):
  Q1=B: la última ventana parcial (is_tail) se incluye sólo si
        coverage ≥ tail_coverage_min (default 0.5).
  Q2=A: coverage = frac_no_nan(spo2_clean) sobre duración NOMINAL
        (no sobre n_samples_raw). Así la tail no "infla" su coverage.
  Q3=A: stats con nanmean/nanstd/nanpercentile sobre *_clean.
        Si todos los samples son NaN → feature = NaN.
  Q4=A: orquestadora por escala (build_windows_for_night(..., scale));
        el trainer llama 3 veces.
  Q5=A: EDO pertenece a ventana si ts_start ∈ [t_start, t_end).
        Regla explícita, sin doble-conteo.
  Q6=A: output con 24 features + metadata (training mask aguas abajo).

Sin I/O: toda persistencia queda en scripts/train_pac_states.py y
scripts/apply_pac_states.py.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from pac.config import (
    PAC_MORPHOTYPE_DENSITY_FEATURES,
    PAC_SIGNAL_STATS_HR,
    PAC_SIGNAL_STATS_MOV,
    PAC_SIGNAL_STATS_SPO2,
    PAC_SLEEP_CATEGORIES,
    PAC_SLEEP_STAGE_COLLAPSE_MAP,
    PAC_WINDOW_DURATIONS_S,
    PAC_WINDOW_FEATURES,
)

# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------
# Mapeo nombre de stat → función (todos nan-aware).
_STAT_FNS = {
    "mean": np.nanmean,
    "std":  np.nanstd,
    "min":  np.nanmin,
    "max":  np.nanmax,
    "p10":  lambda x: float(np.nanpercentile(x, 10)),
    "p90":  lambda x: float(np.nanpercentile(x, 90)),
}

# Mapeo morfotipo (letra griega raw en events/) → nombre de feature canónico.
# Orden consistente con PAC_MORPHOTYPE_DENSITY_FEATURES.
_MORPHO_FEATURE_MAP = {
    "α": "n_alpha",
    "β": "n_beta",
    "γ": "n_gamma",
    "δ": "n_delta",
}

# Columnas de metadata que produce partition_windows (antes de features).
WINDOW_META_COLS = (
    "scale",
    "window_idx",
    "t_start",
    "t_end",
    "n_samples_raw",
    "coverage",
    "is_tail",
)

# Columnas internas (prefijo _) que no se exponen en el output final.
_INTERNAL_COLS = ("_row_start", "_row_end")


# ---------------------------------------------------------------------------
# 1) partition_windows
# ---------------------------------------------------------------------------
def partition_windows(
    silver_df: pd.DataFrame,
    scale: str,
    tail_coverage_min: float = 0.5,
) -> pd.DataFrame:
    """
    Particiona una noche en ventanas disjuntas de duración fija.

    Ventaneo por ÍNDICE DE FILA (chunks de `duration` samples consecutivos a
    1 Hz), no por timestamp. Esto tolera gaps interiores pequeños (Etapa 2
    garantiza coverage ≥ 90 %). La última ventana es `is_tail=True` si
    n_samples_raw < duration; se descarta si `coverage < tail_coverage_min`.

    Parameters
    ----------
    silver_df : DataFrame
        Contrato silver ({timestamp, spo2, spo2_invalid, spo2_clean, hr,
        hr_invalid, hr_clean, mov, sleep_stage}).
    scale : {"s","m","l"}
    tail_coverage_min : float, default 0.5
        Umbral de cobertura para conservar la última ventana parcial.

    Returns
    -------
    DataFrame con columnas:
        window_idx (int), t_start (Timestamp), t_end (Timestamp),
        n_samples_raw (int), coverage (float ∈ [0,1]), is_tail (bool),
        _row_start (int), _row_end (int)

    Notas
    -----
    * `t_end` es NOMINAL (t_start + duration), no el timestamp del último
      sample. Esto garantiza particionamiento exacto y uso consistente
      para el EDO matching (ts_start ∈ [t_start, t_end)).
    * `coverage` se computa SOBRE LA DURACIÓN NOMINAL, no sobre n_samples_raw.
    """
    if scale not in PAC_WINDOW_DURATIONS_S:
        raise ValueError(
            f"Scale desconocida {scale!r}; esperado uno de "
            f"{tuple(PAC_WINDOW_DURATIONS_S.keys())}"
        )

    duration = PAC_WINDOW_DURATIONS_S[scale]
    n = len(silver_df)
    cols = list(WINDOW_META_COLS) + list(_INTERNAL_COLS)
    if n == 0:
        return pd.DataFrame(columns=cols)

    spo2_clean = silver_df["spo2_clean"].to_numpy()
    timestamps = silver_df["timestamp"].to_numpy()

    rows: list[dict] = []
    for idx, start in enumerate(range(0, n, duration)):
        end = min(start + duration, n)
        n_raw = end - start
        is_tail = n_raw < duration

        # Coverage sobre duración NOMINAL (no n_raw). Decisión Q2=A.
        chunk_clean = spo2_clean[start:end]
        n_valid = int(np.sum(~pd.isna(chunk_clean)))
        cov = n_valid / float(duration)

        if is_tail and cov < tail_coverage_min:
            continue

        t_start = pd.Timestamp(timestamps[start])
        t_end_nominal = t_start + pd.Timedelta(seconds=duration)

        rows.append({
            "scale": scale,
            "window_idx": idx,
            "t_start": t_start,
            "t_end": t_end_nominal,
            "n_samples_raw": n_raw,
            "coverage": float(cov),
            "is_tail": bool(is_tail),
            "_row_start": int(start),
            "_row_end": int(end),
        })

    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# 2) aggregate_signal_stats
# ---------------------------------------------------------------------------
def aggregate_signal_stats(
    chunk: pd.DataFrame,
    clean_col: str,
    stats: Iterable[str],
    prefix: str,
) -> dict:
    """
    Calcula stats nan-aware sobre una columna clean.

    Parameters
    ----------
    chunk : DataFrame
        Slice de silver para la ventana.
    clean_col : str
        Nombre de la columna sobre la que se computan los stats.
        Para `mov` pasar "mov" (no tiene clean).
    stats : iterable de str
        Subset de {"mean","std","min","max","p10","p90"}.
    prefix : str
        Prefijo del nombre del feature (p.ej. "spo2" → "spo2_mean").

    Returns
    -------
    dict {f"{prefix}_{stat}": float o NaN}
    """
    vals = chunk[clean_col].to_numpy(dtype=float)
    out: dict = {}
    all_nan = (len(vals) == 0) or bool(np.isnan(vals).all())
    for s in stats:
        fname = f"{prefix}_{s}"
        if s not in _STAT_FNS:
            raise ValueError(f"Stat no soportado: {s!r}")
        if all_nan:
            out[fname] = np.nan
        else:
            out[fname] = float(_STAT_FNS[s](vals))
    return out


# ---------------------------------------------------------------------------
# 3) count_morphotype_densities
# ---------------------------------------------------------------------------
def count_morphotype_densities(
    edos_df: pd.DataFrame,
    t_start: pd.Timestamp,
    t_end: pd.Timestamp,
) -> dict:
    """
    Cuenta EDOs cuyo `ts_start ∈ [t_start, t_end)` y calcula IRD local.

    Parameters
    ----------
    edos_df : DataFrame
        events/{NR}_edos.parquet (25 cols).
    t_start, t_end : Timestamp

    Returns
    -------
    dict con 6 keys según PAC_MORPHOTYPE_DENSITY_FEATURES:
        n_edos_total, n_alpha, n_beta, n_gamma, n_delta, ird_mean_local.

    Notas
    -----
    * ird_mean_local = 0.0 cuando no hay EDOs en la ventana (convención
      PAC: la ausencia de eventos se codifica como 0, no NaN, para que
      la ventana participe del clustering).
    """
    out = {f: 0 for f in PAC_MORPHOTYPE_DENSITY_FEATURES}
    out["ird_mean_local"] = 0.0  # override float

    if len(edos_df) == 0:
        return out

    ts_start = edos_df["ts_start"]
    mask = (ts_start >= t_start) & (ts_start < t_end)
    in_win = edos_df.loc[mask]

    out["n_edos_total"] = int(len(in_win))
    for letter, fname in _MORPHO_FEATURE_MAP.items():
        out[fname] = int((in_win["morphotype"] == letter).sum())

    if len(in_win) > 0 and "ird_event" in in_win.columns:
        ird_vals = in_win["ird_event"].dropna()
        out["ird_mean_local"] = float(ird_vals.mean()) if len(ird_vals) else 0.0

    return out


# ---------------------------------------------------------------------------
# 4) compute_sleep_composition
# ---------------------------------------------------------------------------
def compute_sleep_composition(sleep_series: pd.Series) -> dict:
    """
    Aplica PAC_SLEEP_STAGE_COLLAPSE_MAP y devuelve fracciones.

    Parameters
    ----------
    sleep_series : Series
        Columna sleep_stage (Int64 con valores {0,1,2,3}) para la ventana.

    Returns
    -------
    dict con 3 keys: frac_wake, frac_light_sleep, frac_deep_sleep.

    Notas
    -----
    * El denominador es len(sleep_series), NO el conteo de no-null.
      Samples null o fuera del mapping contribuyen 0 a todas las fracs
      (se consideran "unknown").
    * Como consecuencia, sum(fracs) ≤ 1.0 (puede haber "unknown" implícito).
    """
    out = {f"frac_{cat}": 0.0 for cat in PAC_SLEEP_CATEGORIES}
    n_total = len(sleep_series)
    if n_total == 0:
        return out

    # .map con dict sobre Int64 retorna objects; .dropna limpia null y unmapped.
    mapped = sleep_series.map(PAC_SLEEP_STAGE_COLLAPSE_MAP).dropna()
    for cat in PAC_SLEEP_CATEGORIES:
        out[f"frac_{cat}"] = float((mapped == cat).sum()) / float(n_total)
    return out


# ---------------------------------------------------------------------------
# 5) build_windows_for_night — orquestadora
# ---------------------------------------------------------------------------
def build_windows_for_night(
    silver_df: pd.DataFrame,
    edos_df: pd.DataFrame,
    scale: str,
    tail_coverage_min: float = 0.5,
) -> pd.DataFrame:
    """
    Orquestadora: ventaneo + features → DataFrame listo para persistir.

    Output schema (31 cols = 7 metadata + 24 features):
        scale, window_idx, t_start, t_end, n_samples_raw, coverage, is_tail,
        spo2_mean, spo2_std, spo2_min, spo2_max, spo2_p10, spo2_p90,
        hr_mean,   hr_std,   hr_min,   hr_max,   hr_p10,   hr_p90,
        mov_mean,  mov_std,  mov_max,
        n_edos_total, n_alpha, n_beta, n_gamma, n_delta, ird_mean_local,
        frac_wake, frac_light_sleep, frac_deep_sleep

    Returns
    -------
    DataFrame con 31 columnas, una fila por ventana.
    Empty DataFrame (mismas columnas) si silver_df está vacío.
    """
    bases = partition_windows(silver_df, scale, tail_coverage_min=tail_coverage_min)
    out_cols = list(WINDOW_META_COLS) + list(PAC_WINDOW_FEATURES)

    if len(bases) == 0:
        return pd.DataFrame(columns=out_cols)

    rows: list[dict] = []
    for _, w in bases.iterrows():
        start = int(w["_row_start"])
        end = int(w["_row_end"])
        chunk = silver_df.iloc[start:end]

        row: dict = {
            "scale": scale,
            "window_idx": int(w["window_idx"]),
            "t_start": w["t_start"],
            "t_end": w["t_end"],
            "n_samples_raw": int(w["n_samples_raw"]),
            "coverage": float(w["coverage"]),
            "is_tail": bool(w["is_tail"]),
        }

        # Signal stats — 15 features (6 + 6 + 3).
        row.update(aggregate_signal_stats(
            chunk, "spo2_clean", PAC_SIGNAL_STATS_SPO2, "spo2"
        ))
        row.update(aggregate_signal_stats(
            chunk, "hr_clean", PAC_SIGNAL_STATS_HR, "hr"
        ))
        row.update(aggregate_signal_stats(
            chunk, "mov", PAC_SIGNAL_STATS_MOV, "mov"
        ))

        # Morphotype densities — 6 features.
        row.update(count_morphotype_densities(edos_df, w["t_start"], w["t_end"]))

        # Sleep composition — 3 features.
        row.update(compute_sleep_composition(chunk["sleep_stage"]))

        rows.append(row)

    return pd.DataFrame(rows, columns=out_cols)
