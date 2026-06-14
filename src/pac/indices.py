"""
PAC_v2 — Etapa 3 Events: cálculo de índices nocturnos.

Sin I/O. Cada función es pura y devuelve escalar o dict. El orquestador
de `pac.events_pipeline` las compone sobre los datos de una noche.

Familias de índices (~35 campos al final, algunos son stats derivadas
baratas del mismo cálculo):

  SpO2:      ODI_N (N en 2/3/4/5), T<N (90/88/85), CT<N, stats, HB.
  HR:        stats, delta_HR per-EDO agregados, brady/tachy events.
  Movimiento: stats + movement_index_per_h.
  Sueño:     TST, WASO, sleep_efficiency, sleep_latency, n_stage_shifts.
  Event-based: AHI_N (con in_sleep filter), IRD nocturno + estadísticos.

Convención:
  - Los tiempos en segundos salvo donde se indique "_min" (minutos) o "_h".
  - Los NaN de las señales (spo2_clean, hr_clean) no contribuyen a las
    estadísticas (se usa .dropna() o funciones np.nan* explícitas).
  - AHI sin señal de flow se define como "ODI_N restringido a in_sleep".
    Se documenta en el schema: no es AASM-AHI estricto.
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Utilidades base
# ---------------------------------------------------------------------------
def _duration_s(ts: pd.Series) -> float:
    """Duración total de la serie de timestamps en segundos."""
    if len(ts) < 2:
        return 0.0
    return float((ts.iloc[-1] - ts.iloc[0]).total_seconds())


# ---------------------------------------------------------------------------
# SpO2 — ODI (genérico para cualquier umbral)
# ---------------------------------------------------------------------------
def compute_odi(n_events: int, tst_s: float) -> float:
    """
    Oxygen Desaturation Index = eventos / hora de sueño.

    Si tst_s ≤ 0, devuelve 0.0 (noche sin sueño medible).
    """
    if tst_s <= 0:
        return 0.0
    return float(n_events) * 3600.0 / float(tst_s)


def compute_ahi(n_events_in_sleep: int, tst_s: float) -> float:
    """
    AHI sin flow = ODI restringido a eventos con in_sleep=True.
    Documentado en schema: no es AASM-AHI estricto.
    """
    return compute_odi(n_events_in_sleep, tst_s)


# ---------------------------------------------------------------------------
# SpO2 — T<N y CT<N
# ---------------------------------------------------------------------------
def compute_t_under(
    spo2: pd.Series,
    threshold_pct: float,
) -> float:
    """
    Fracción de tiempo (samples) con SpO2 < threshold_pct.

    NaN no se cuentan ni en numerador ni en denominador.
    Returns: ∈ [0.0, 1.0].
    """
    valid = spo2.dropna()
    if len(valid) == 0:
        return 0.0
    return float((valid < threshold_pct).mean())


def compute_ct_under(
    spo2: pd.Series,
    threshold_pct: float,
    sampling_hz: float = 1.0,
) -> float:
    """
    Cumulative time bajo threshold_pct en minutos.
    Cada sample válido cuenta 1/sampling_hz segundos.
    """
    valid = spo2.dropna()
    if len(valid) == 0:
        return 0.0
    n_under = int((valid < threshold_pct).sum())
    return float(n_under / sampling_hz / 60.0)


# ---------------------------------------------------------------------------
# SpO2 — estadísticas básicas
# ---------------------------------------------------------------------------
def compute_spo2_stats(spo2: pd.Series) -> dict:
    """
    Retorna mean, median, min, std de SpO2 (dropna).
    Si está vacío/todo NaN → todos los campos NaN.
    """
    valid = spo2.dropna()
    if len(valid) == 0:
        return {
            "mean_spo2": float("nan"),
            "median_spo2": float("nan"),
            "min_spo2": float("nan"),
            "std_spo2": float("nan"),
        }
    return {
        "mean_spo2": float(valid.mean()),
        "median_spo2": float(valid.median()),
        "min_spo2": float(valid.min()),
        "std_spo2": float(valid.std(ddof=0)),
    }


# ---------------------------------------------------------------------------
# SpO2 — Hypoxic Burden (Azarbarzin 2019)
# ---------------------------------------------------------------------------
def compute_hypoxic_burden(
    spo2: pd.Series,
    ts: pd.Series,
    threshold_pct: float = 90.0,
    sampling_hz: float = 1.0,
) -> float:
    """
    Hypoxic Burden canónico: área del déficit bajo `threshold_pct`.

    HB = ∫ max(threshold - spo2(t), 0) dt      (en %·s)

    Se devuelve en **%·min por hora de grabación** (normalizado a rate),
    que es la presentación más común en literatura. Si la noche no tiene
    duración medible, retorna 0.0.

    NaN se tratan como "sin déficit" (conservador: no sobre-estimamos HB
    en ausencia de señal).
    """
    dur_s = _duration_s(ts)
    if dur_s <= 0:
        return 0.0
    vals = spo2.to_numpy(dtype=float)
    filled = np.where(np.isnan(vals), threshold_pct, vals)
    deficit = np.clip(threshold_pct - filled, a_min=0.0, a_max=None)
    dt = 1.0 / sampling_hz
    # np.trapezoid (NumPy ≥2) con fallback a np.trapz (NumPy <2).
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    auc_pct_s = float(_trapz(deficit, dx=dt))
    # normalizar a %·min/h
    auc_pct_min = auc_pct_s / 60.0
    return auc_pct_min * 3600.0 / dur_s


# ---------------------------------------------------------------------------
# HR — estadísticas básicas
# ---------------------------------------------------------------------------
def compute_hr_stats(hr: pd.Series) -> dict:
    """
    Retorna mean, median, min, max, std de HR (dropna).
    """
    valid = hr.dropna()
    if len(valid) == 0:
        return {k: float("nan") for k in (
            "mean_hr", "median_hr", "min_hr", "max_hr", "std_hr"
        )}
    return {
        "mean_hr": float(valid.mean()),
        "median_hr": float(valid.median()),
        "min_hr": float(valid.min()),
        "max_hr": float(valid.max()),
        "std_hr": float(valid.std(ddof=0)),
    }


# ---------------------------------------------------------------------------
# HR — brady/tachy sostenidos
# ---------------------------------------------------------------------------
def count_sustained_extremes(
    signal: pd.Series,
    threshold: float,
    comparator: str,
    min_duration_s: int = 10,
    sampling_hz: float = 1.0,
) -> int:
    """
    Cuenta episodios donde `signal <comparator> threshold` sostenidamente
    por ≥ min_duration_s.

    Args:
        signal: serie a evaluar (NaN no cuenta como evento).
        threshold: umbral a comparar.
        comparator: '<' o '>'.
        min_duration_s: duración mínima del episodio en segundos.
        sampling_hz: frecuencia de muestreo.

    Returns:
        Número de episodios.
    """
    vals = signal.to_numpy(dtype=float)
    if comparator == "<":
        mask = (vals < threshold) & ~np.isnan(vals)
    elif comparator == ">":
        mask = (vals > threshold) & ~np.isnan(vals)
    else:
        raise ValueError(f"comparator debe ser '<' o '>', no {comparator!r}")
    if not mask.any():
        return 0

    # Segmentos contiguos
    mask_int = mask.astype(np.int8)
    diffs = np.diff(mask_int, prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0] - 1

    min_samples = int(round(min_duration_s * sampling_hz))
    count = 0
    for s, e in zip(starts, ends):
        if (e - s + 1) >= min_samples:
            count += 1
    return count


# ---------------------------------------------------------------------------
# HR — agregados del delta_hr_per_edo (extraído del DataFrame de events)
# ---------------------------------------------------------------------------
def compute_delta_hr_stats(events_df: pd.DataFrame) -> dict:
    """
    Estadísticos del delta_hr_bpm a lo largo de los EDOs de la noche.
    Retorna NaN si no hay eventos.
    """
    if len(events_df) == 0 or "delta_hr_bpm" not in events_df.columns:
        return {
            "mean_delta_hr_per_edo": float("nan"),
            "p90_delta_hr_per_edo": float("nan"),
        }
    series = events_df["delta_hr_bpm"].dropna()
    if len(series) == 0:
        return {
            "mean_delta_hr_per_edo": float("nan"),
            "p90_delta_hr_per_edo": float("nan"),
        }
    return {
        "mean_delta_hr_per_edo": float(series.mean()),
        "p90_delta_hr_per_edo": float(series.quantile(0.90)),
    }


# ---------------------------------------------------------------------------
# Movimiento
# ---------------------------------------------------------------------------
def compute_mov_stats(
    mov: pd.Series,
    ts: pd.Series,
    threshold_factor: float = 3.0,
    sampling_hz: float = 1.0,
) -> dict:
    """
    mean_mov + movement_index_per_h.

    movement_index_per_h = eventos de mov. sostenidos por hora, donde
    "evento" = segmento ≥ 2 s con mov > threshold_factor × median(mov).

    Si median(mov) ≈ 0 (paciente muy quieto), threshold = threshold_factor.
    """
    valid = mov.dropna()
    if len(valid) == 0:
        return {"mean_mov": float("nan"), "movement_index_per_h": 0.0}
    mean_mov = float(valid.mean())
    median_mov = float(valid.median())
    threshold = max(median_mov * threshold_factor, 0.01 * threshold_factor)
    n_events = count_sustained_extremes(
        mov, threshold=threshold, comparator=">",
        min_duration_s=2, sampling_hz=sampling_hz,
    )
    dur_s = _duration_s(ts)
    rate_per_h = n_events * 3600.0 / dur_s if dur_s > 0 else 0.0
    return {
        "mean_mov": mean_mov,
        "movement_index_per_h": float(rate_per_h),
    }


# ---------------------------------------------------------------------------
# Sueño
# ---------------------------------------------------------------------------
def compute_sleep_stats(
    sleep_stage: pd.Series,
    ts: pd.Series,
    wake_values: Optional[set] = None,
    sampling_hz: float = 1.0,
) -> dict:
    """
    Retorna tst_s, waso_s, sleep_efficiency, sleep_latency_s, n_stage_shifts.

    Definiciones:
      - TST: total samples con stage ∈ not wake, convertidos a segundos.
      - sleep_latency_s: tiempo desde inicio de la grabación hasta el
        primer sample de sueño (stage not wake). Si nunca duerme, =
        duración total.
      - WASO: tiempo en wake DESPUÉS del sleep_onset.
      - sleep_efficiency: TST / duration_s.
      - n_stage_shifts: número de transiciones stage[t] ≠ stage[t-1].

    Si sleep_stage está vacío o todo NaN → TST = duration_s (fallback:
    asumimos toda la grabación como "sueño" si no hay staging).
    """
    if wake_values is None:
        wake_values = {0}

    dur_s = _duration_s(ts)
    sample_s = 1.0 / sampling_hz
    n_total = len(sleep_stage)

    # Fallback sin sleep staging
    if n_total == 0 or sleep_stage.isna().all():
        return {
            "tst_s": float(dur_s),
            "waso_s": 0.0,
            "sleep_efficiency": 1.0 if dur_s > 0 else 0.0,
            "sleep_latency_s": 0.0,
            "n_stage_shifts": 0,
        }

    is_sleep = ~sleep_stage.isin(wake_values) & sleep_stage.notna()
    n_sleep = int(is_sleep.sum())
    tst_s = float(n_sleep * sample_s)

    # Sleep onset = primer índice en sueño
    sleep_indices = np.where(is_sleep.to_numpy())[0]
    if len(sleep_indices) == 0:
        sleep_latency_s = float(dur_s)
        waso_s = 0.0
    else:
        onset_idx = int(sleep_indices[0])
        sleep_latency_s = float(onset_idx * sample_s)
        # WASO = samples post-onset en wake
        post_onset = sleep_stage.iloc[onset_idx:]
        waso_samples = int(
            (post_onset.isin(wake_values) & post_onset.notna()).sum()
        )
        waso_s = float(waso_samples * sample_s)

    sleep_efficiency = float(tst_s / dur_s) if dur_s > 0 else 0.0

    # Stage shifts
    arr = sleep_stage.to_numpy()
    non_nan = ~pd.isna(arr)
    if non_nan.sum() < 2:
        n_stage_shifts = 0
    else:
        clean = arr[non_nan]
        n_stage_shifts = int((clean[1:] != clean[:-1]).sum())

    return {
        "tst_s": tst_s,
        "waso_s": waso_s,
        "sleep_efficiency": sleep_efficiency,
        "sleep_latency_s": sleep_latency_s,
        "n_stage_shifts": n_stage_shifts,
    }


# ---------------------------------------------------------------------------
# Event-based — IRD nocturno + stats de EDOs
# ---------------------------------------------------------------------------
def compute_ird_night(events_df: pd.DataFrame, tst_s: float) -> float:
    """
    IRD nocturno = Σ(ird_event × duration_s) / TST.

    Densidad de severidad por hora de sueño (proporcional a TST).
    Si TST ≤ 0 o sin eventos, retorna 0.0.
    """
    if tst_s <= 0 or len(events_df) == 0:
        return 0.0
    if "ird_event" not in events_df.columns or "duration_s" not in events_df.columns:
        return 0.0
    weighted = (events_df["ird_event"].fillna(0.0) * events_df["duration_s"]).sum()
    return float(weighted / tst_s)


def compute_ird_event_stats(events_df: pd.DataFrame) -> dict:
    """
    Estadísticos del ird_event sobre todos los EDOs de la noche.
    """
    if len(events_df) == 0 or "ird_event" not in events_df.columns:
        return {
            "mean_ird_event": float("nan"),
            "p90_ird_event": float("nan"),
        }
    s = events_df["ird_event"].dropna()
    if len(s) == 0:
        return {
            "mean_ird_event": float("nan"),
            "p90_ird_event": float("nan"),
        }
    return {
        "mean_ird_event": float(s.mean()),
        "p90_ird_event": float(s.quantile(0.90)),
    }


def compute_edo_morphology_stats(events_df: pd.DataFrame) -> dict:
    """
    Estadísticos de morfología agregados (mean_drop_pct, mean_duration_s).
    """
    if len(events_df) == 0:
        return {
            "n_edos_total": 0,
            "mean_drop_pct": float("nan"),
            "mean_duration_s": float("nan"),
            "max_duration_s": float("nan"),
        }
    return {
        "n_edos_total": int(len(events_df)),
        "mean_drop_pct": float(events_df["drop_pct"].mean()),
        "mean_duration_s": float(events_df["duration_s"].mean()),
        "max_duration_s": float(events_df["duration_s"].max()),
    }


# ---------------------------------------------------------------------------
# ODI / AHI a partir del DataFrame de events
# ---------------------------------------------------------------------------
def compute_odi_ahi_family(
    events_df: pd.DataFrame,
    tst_s: float,
    thresholds: Iterable[int] = (2, 3, 4, 5),
) -> dict:
    """
    Calcula ODI_N y AHI_N para cada threshold en `thresholds`.
    ODI = total eventos que cumplen meets_Npct por hora de sueño.
    AHI = restringido a eventos con in_sleep=True.

    Retorna dict con claves odi_2..5, ahi_2..5 + n_edos_Npct (conteos).
    """
    out: dict = {}
    if len(events_df) == 0:
        for pct in thresholds:
            out[f"odi_{int(pct)}"] = 0.0
            out[f"ahi_{int(pct)}"] = 0.0
            out[f"n_edos_{int(pct)}pct"] = 0
        return out

    for pct in thresholds:
        col = f"meets_{int(pct)}pct"
        if col not in events_df.columns:
            n_meet = 0
            n_meet_in_sleep = 0
        else:
            meets = events_df[col].fillna(False)
            n_meet = int(meets.sum())
            if "in_sleep" in events_df.columns:
                n_meet_in_sleep = int((meets & events_df["in_sleep"].fillna(False)).sum())
            else:
                n_meet_in_sleep = n_meet  # sin sleep_stage, AHI = ODI
        out[f"odi_{int(pct)}"] = compute_odi(n_meet, tst_s)
        out[f"ahi_{int(pct)}"] = compute_ahi(n_meet_in_sleep, tst_s)
        out[f"n_edos_{int(pct)}pct"] = n_meet
    return out


# ---------------------------------------------------------------------------
# Validación contra sidecar classical
# ---------------------------------------------------------------------------
def compute_diff_vs_device(
    pac_v2_value: float,
    device_value: Optional[float],
    flag_threshold: float = 0.20,
) -> dict:
    """
    Calcula el quinteto {_pac_v2, _device, _diff_abs, _diff_rel, _diff_flag}
    para un índice con gemelo en el sidecar.

    Si device_value es None/NaN → diff_abs y diff_rel = NaN,
    diff_flag = False (no se puede comparar).
    """
    result = {
        "pac_v2": float(pac_v2_value) if pac_v2_value is not None else float("nan"),
        "device": float(device_value) if device_value is not None else float("nan"),
        "diff_abs": float("nan"),
        "diff_rel": float("nan"),
        "diff_flag": False,
    }
    if device_value is None or (isinstance(device_value, float) and np.isnan(device_value)):
        return result
    if pac_v2_value is None or (isinstance(pac_v2_value, float) and np.isnan(pac_v2_value)):
        return result
    diff_abs = abs(pac_v2_value - device_value)
    result["diff_abs"] = float(diff_abs)
    if abs(device_value) < 1e-9:
        # device = 0: diff_rel indefinido. Usamos diff_abs como proxy.
        result["diff_rel"] = float("inf") if diff_abs > 0 else 0.0
    else:
        result["diff_rel"] = float((pac_v2_value - device_value) / device_value)
    result["diff_flag"] = bool(
        np.isfinite(result["diff_rel"]) and abs(result["diff_rel"]) > flag_threshold
    )
    return result
