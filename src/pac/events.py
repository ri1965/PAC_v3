"""
PAC_v2 — Etapa 3 Events: detectores puros.

Sin I/O. Cada función toma arrays / Series / DataFrames y devuelve
arrays / dicts. Diseño: funciones idempotentes, testeables aisladas,
sin dependencia de config salvo cuando el caller pasa constantes
explícitas (los defaults se usan en tests unitarios).

Unidades conceptuales (ver PAC_v2_ETAPAS.md):
  - EDO (Evento de Desaturación de Oxígeno): objeto morfológico con
    baseline, nadir, slopes, AUC, duración + 3 componentes IRD.
  - IRD por-EDO: combinación ponderada de tres componentes normalizadas
    al baseline propio de cada señal (R4, Q13a, Q14c).

Decisiones cerradas:
  - Baseline móvil = median(spo2 previo 120 s). AASM 2012 Rule 10 (R3).
  - Fin del EDO = recovery a ≥ 90% × baseline_at_start (R1).
  - Duración mínima 10 s (detección permisiva; clustering real/ruido
    se hace en Etapa 4 — R2 + Q12b).
  - Umbrales de drop evaluados: 2/3/4/5% (Q2).
  - Curvas morfológicas resampleadas a 30 puntos para sidecar (Q15c).
  - Componentes IRD normalizadas al baseline propio de cada señal (Q14c).
  - Pesos IRD default 0.5 / 0.3 / 0.2, swappable por parámetro (R4, Q13a).
"""
from __future__ import annotations

from typing import Iterable, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Baseline móvil
# ---------------------------------------------------------------------------
def compute_baseline_moving(
    spo2: pd.Series,
    window_s: int = 120,
    sampling_hz: float = 1.0,
    min_periods_frac: float = 0.25,
) -> pd.Series:
    """
    Baseline móvil por mediana de una ventana rolling previa.

    AASM 2012 Rule 10: baseline = median(SpO2 en los `window_s` segundos
    anteriores al punto actual). Con 1 Hz fijo, window_s == N samples.

    Args:
        spo2: serie de SpO2 (puede contener NaN; median skipna).
        window_s: tamaño de la ventana en segundos.
        sampling_hz: frecuencia de muestreo (1.0 para PAC_v2).
        min_periods_frac: fracción mínima de la ventana necesaria para
            calcular baseline. Default 0.25 → 30 s a 1 Hz. Los primeros
            samples con historia insuficiente tienen baseline = NaN.

    Returns:
        Serie de la misma longitud e índice que `spo2`.
    """
    window_samples = max(1, int(round(window_s * sampling_hz)))
    min_periods = max(1, int(round(window_samples * min_periods_frac)))
    return spo2.rolling(window=window_samples, min_periods=min_periods).median()


# ---------------------------------------------------------------------------
# Detección de EDOs candidatos
# ---------------------------------------------------------------------------
def detect_edo_candidates(
    spo2_clean: pd.Series,
    ts: pd.Series,
    baseline: pd.Series,
    min_duration_s: int = 10,
    recovery_pct: float = 0.90,
    min_drop_pct: float = 2.0,
) -> list[dict]:
    """
    Detecta EDOs candidatos sobre la señal de SpO2 QC-aware.

    Algoritmo:
      1. trigger: spo2_clean < baseline (permisivo, cualquier caída).
      2. agrupar puntos contiguos bajo baseline como segmentos.
      3. extender `end` del segmento hasta que spo2 ≥ baseline_at_start * recovery_pct.
      4. nadir = min(spo2_clean) dentro del segmento extendido.
      5. filtrar por duration ≥ min_duration_s Y drop_pct ≥ min_drop_pct.

    NaN en spo2_clean o baseline no contribuyen al trigger (se ignoran).

    Args:
        spo2_clean: columna de Silver con NaN donde invalid.
        ts: timestamps (datetime64).
        baseline: output de compute_baseline_moving.
        min_duration_s: duración mínima del EDO (s).
        recovery_pct: fracción del baseline para considerar recovery.
        min_drop_pct: drop mínimo en % (permisivo: 2.0).

    Returns:
        Lista de dicts, uno por EDO candidato:
            start_idx, end_idx, nadir_idx (int),
            baseline_spo2, nadir_spo2, drop_pct, duration_s (float),
            ts_start, ts_end (Timestamp).
    """
    spo2_arr = spo2_clean.to_numpy(dtype=float)
    baseline_arr = baseline.to_numpy(dtype=float)
    ts_arr = ts.to_numpy()
    n = len(spo2_arr)

    # Máscara de "bajo baseline" — NaN se trata como no-drop.
    below = (
        (spo2_arr < baseline_arr)
        & ~np.isnan(spo2_arr)
        & ~np.isnan(baseline_arr)
    )
    if not below.any():
        return []

    # Bordes de segmentos contiguos via diff.
    below_int = below.astype(np.int8)
    diffs = np.diff(below_int, prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0] - 1  # inclusive

    results: list[dict] = []
    for s_idx, e_idx in zip(starts, ends):
        b0 = baseline_arr[s_idx]
        if np.isnan(b0) or b0 <= 0:
            continue

        # Extender end hasta recovery ≥ baseline_at_start * recovery_pct.
        recovery_thr = b0 * recovery_pct
        extend_end = e_idx
        for k in range(e_idx + 1, n):
            v = spo2_arr[k]
            if np.isnan(v):
                # NaN no extiende ni corta; seguimos si quedan puntos.
                continue
            if v >= recovery_thr:
                extend_end = k
                break
            extend_end = k
        # Si no encontramos recovery, dejamos extend_end como último punto
        # que quedó — el evento está truncado por fin de noche o gap.

        window = spo2_arr[s_idx : extend_end + 1]
        if np.all(np.isnan(window)):
            continue
        local_nadir_offset = int(np.nanargmin(window))
        nadir_idx = s_idx + local_nadir_offset
        nadir_spo2 = float(spo2_arr[nadir_idx])

        drop_pct = (b0 - nadir_spo2) / b0 * 100.0
        if drop_pct < min_drop_pct:
            continue

        ts_start = ts_arr[s_idx]
        ts_end = ts_arr[extend_end]
        duration_s = float((ts_end - ts_start) / np.timedelta64(1, "s"))
        if duration_s < min_duration_s:
            continue

        results.append(
            {
                "start_idx": int(s_idx),
                "end_idx": int(extend_end),
                "nadir_idx": int(nadir_idx),
                "baseline_spo2": float(b0),
                "nadir_spo2": nadir_spo2,
                "drop_pct": float(drop_pct),
                "duration_s": duration_s,
                "ts_start": pd.Timestamp(ts_start),
                "ts_end": pd.Timestamp(ts_end),
            }
        )

    # Resolver solapamientos entre EDOs: cuando un segmento cae dentro
    # de la ventana extendida del anterior, se descarta.
    if not results:
        return []
    filtered = [results[0]]
    for edo in results[1:]:
        if edo["start_idx"] <= filtered[-1]["end_idx"]:
            continue
        filtered.append(edo)
    return filtered


# ---------------------------------------------------------------------------
# Flags de contexto del EDO
# ---------------------------------------------------------------------------
def compute_gaps(
    ts: pd.Series,
    min_gap_s: float = 30.0,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Lista de gaps (pares ts_before, ts_after) con diff ≥ min_gap_s.
    """
    dt = ts.diff().dt.total_seconds()
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for i, d in enumerate(dt):
        if pd.notna(d) and d >= min_gap_s:
            gaps.append((ts.iloc[i - 1], ts.iloc[i]))
    return gaps


def mark_near_gap(
    edo_ts_start: pd.Timestamp,
    edo_ts_end: pd.Timestamp,
    gaps: Iterable[tuple[pd.Timestamp, pd.Timestamp]],
    window_s: int = 300,
) -> bool:
    """
    True si el EDO cae dentro de [gap_start - window_s, gap_end + window_s]
    para algún gap.
    """
    w = pd.Timedelta(seconds=window_s)
    for g_start, g_end in gaps:
        influence_start = g_start - w
        influence_end = g_end + w
        if edo_ts_start <= influence_end and edo_ts_end >= influence_start:
            return True
    return False


def mark_in_sleep(
    start_idx: int,
    end_idx: int,
    sleep_stage: pd.Series,
    wake_values: Optional[set] = None,
) -> bool:
    """
    True si > 50% de los samples del EDO están fuera de wake.

    `wake_values` = conjunto de códigos que representan "despierto".
    Default conservador: {0} (convención más común).
    """
    if wake_values is None:
        wake_values = {0}
    stages = sleep_stage.iloc[start_idx : end_idx + 1]
    if len(stages) == 0:
        return False
    non_wake_frac = (~stages.isin(wake_values)).mean()
    return bool(non_wake_frac > 0.5)


# ---------------------------------------------------------------------------
# Resampling de curva morfológica
# ---------------------------------------------------------------------------
def resample_curve(values: np.ndarray, n_points: int = 30) -> np.ndarray:
    """
    Resamplea una curva 1D a N puntos fijos por interpolación lineal.

    Usa ffill/bfill para rellenar NaN antes de interpolar (no-op si la
    curva está limpia). Si todo es NaN → array de NaN.
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return np.full(n_points, np.nan, dtype=float)
    if np.all(np.isnan(arr)):
        return np.full(n_points, np.nan, dtype=float)
    filled = pd.Series(arr).ffill().bfill().to_numpy(dtype=float)
    if filled.size == n_points:
        return filled.copy()
    original_x = np.linspace(0.0, 1.0, filled.size)
    target_x = np.linspace(0.0, 1.0, n_points)
    return np.interp(target_x, original_x, filled)


# ---------------------------------------------------------------------------
# IRD — Índice de Respuesta a la Desaturación
# ---------------------------------------------------------------------------
_DEFAULT_IRD_WEIGHTS = {"spo2": 0.5, "hr": 0.3, "mov": 0.2}


def compute_ird_components(
    drop_pct: float,
    baseline_spo2: float,
    delta_hr_bpm: float,
    baseline_hr_bpm: float,
    peak_mov: float,
    baseline_mov: float,
) -> dict:
    """
    Tres componentes del IRD normalizadas al baseline propio de cada señal.
    Decisión Q14c.

    - spo2_comp = drop_pct / baseline_spo2
        Proporción de la caída respecto al baseline (sin unidad).
    - hr_comp   = delta_hr_bpm / baseline_hr_bpm
        Incremento relativo de HR respecto al baseline.
    - mov_comp  = (peak_mov - baseline_mov) / (baseline_mov + 0.01)
        Incremento proporcional de mov; el +0.01 evita explosión cuando
        el paciente estaba quieto (baseline_mov ≈ 0).

    NaN en los inputs → 0 en el componente correspondiente (no se propaga
    a las otras componentes del IRD).
    """
    eps = 1e-6

    def _safe_div(num: float, den: float, den_offset: float = 0.0) -> float:
        if num is None or den is None:
            return 0.0
        if np.isnan(num) or np.isnan(den):
            return 0.0
        denom = den + den_offset
        if abs(denom) < eps:
            return 0.0
        return float(num / denom)

    spo2_comp = _safe_div(drop_pct, baseline_spo2)
    hr_comp = _safe_div(delta_hr_bpm, baseline_hr_bpm)
    mov_comp = _safe_div(peak_mov - baseline_mov, baseline_mov, den_offset=0.01)

    return {
        "ird_spo2_comp": spo2_comp,
        "ird_hr_comp": hr_comp,
        "ird_mov_comp": mov_comp,
    }


def compute_ird_event(
    components: dict,
    weights: Optional[dict] = None,
) -> float:
    """
    Combina las 3 componentes con pesos.

    Default: 0.5 SpO2 + 0.3 HR + 0.2 mov (R4 + Q13a). Pesos swappable
    por parámetro para que la recalibración futura (RN u otra) no
    requiera re-detectar EDOs.
    """
    if weights is None:
        weights = _DEFAULT_IRD_WEIGHTS
    return float(
        weights["spo2"] * components["ird_spo2_comp"]
        + weights["hr"] * components["ird_hr_comp"]
        + weights["mov"] * components["ird_mov_comp"]
    )


# ---------------------------------------------------------------------------
# Caracterización morfológica completa del EDO
# ---------------------------------------------------------------------------
def characterize_edo(
    edo: dict,
    df: pd.DataFrame,
    drop_thresholds_pct: Optional[list[int]] = None,
    n_resample_points: int = 30,
    context_window_s: int = 60,
    ird_weights: Optional[dict] = None,
) -> dict:
    """
    Expande un EDO candidato a su caracterización morfológica completa.

    Args:
        edo: dict de `detect_edo_candidates`.
        df: DataFrame silver con cols `timestamp, spo2_clean, hr_clean, mov`.
        drop_thresholds_pct: umbrales evaluados. Default [2,3,4,5] (Q2).
        n_resample_points: puntos de las curvas resampleadas. Default 30.
        context_window_s: ventana previa para baseline de HR y mov (s).
        ird_weights: pesos del IRD; default de módulo.

    Returns:
        Dict con:
          - ts_start, ts_end, duration_s
          - baseline_spo2, nadir_spo2, drop_pct
          - slope_desat_pct_s, slope_recov_pct_s, auc_spo2_pct_s
          - meets_2pct, meets_3pct, meets_4pct, meets_5pct
          - delta_hr_bpm, baseline_hr_bpm
          - peak_mov, baseline_mov
          - ird_spo2_comp, ird_hr_comp, ird_mov_comp, ird_event
          - _spo2_curve, _hr_curve, _mov_curve (arrays np, para sidecar)
    """
    if drop_thresholds_pct is None:
        drop_thresholds_pct = [2, 3, 4, 5]

    s = edo["start_idx"]
    e = edo["end_idx"]
    nadir = edo["nadir_idx"]

    window = df.iloc[s : e + 1]
    ts_start = edo["ts_start"]
    ts_end = edo["ts_end"]
    ts_nadir = df["timestamp"].iloc[nadir]

    # Slopes (%/s). Manejo de duraciones cero.
    desat_dur_s = max((ts_nadir - ts_start).total_seconds(), 0.0)
    recov_dur_s = max((ts_end - ts_nadir).total_seconds(), 0.0)

    drop_magnitude = edo["baseline_spo2"] - edo["nadir_spo2"]
    last_valid_spo2 = window["spo2_clean"].dropna()
    last_spo2 = (
        float(last_valid_spo2.iloc[-1])
        if len(last_valid_spo2) > 0
        else float(edo["nadir_spo2"])
    )
    recov_magnitude = last_spo2 - edo["nadir_spo2"]

    slope_desat = drop_magnitude / desat_dur_s if desat_dur_s > 0 else 0.0
    slope_recov = recov_magnitude / recov_dur_s if recov_dur_s > 0 else 0.0

    # AUC del déficit respecto al baseline, con dx=1s (1 Hz).
    # NaN → rellenar con baseline (no contribuye al déficit).
    spo2_vals = window["spo2_clean"].to_numpy(dtype=float)
    spo2_filled = np.where(np.isnan(spo2_vals), edo["baseline_spo2"], spo2_vals)
    deficit = np.clip(edo["baseline_spo2"] - spo2_filled, a_min=0.0, a_max=None)
    # np.trapezoid (NumPy ≥2) con fallback a np.trapz (NumPy <2).
    _trapz = getattr(np, "trapezoid", getattr(np, "trapz", None))
    auc = float(_trapz(deficit, dx=1.0))

    # Flags meets_Npct.
    meets = {
        f"meets_{int(pct)}pct": bool(edo["drop_pct"] >= pct)
        for pct in drop_thresholds_pct
    }

    # Ventana de contexto previa para HR y mov.
    ctx_start = max(0, s - int(context_window_s))
    context = df.iloc[ctx_start:s]

    hr_ctx = context["hr_clean"] if len(context) > 0 else pd.Series(dtype=float)
    mov_ctx = context["mov"] if len(context) > 0 else pd.Series(dtype=float)
    baseline_hr = float(hr_ctx.median()) if len(hr_ctx.dropna()) > 0 else np.nan
    baseline_mov = float(mov_ctx.median()) if len(mov_ctx.dropna()) > 0 else 0.0

    hr_in_edo = window["hr_clean"].to_numpy(dtype=float)
    mov_in_edo = window["mov"].to_numpy(dtype=float)

    if np.all(np.isnan(hr_in_edo)):
        max_hr = np.nan
    else:
        max_hr = float(np.nanmax(hr_in_edo))
    delta_hr = (
        float(max_hr - baseline_hr)
        if not (np.isnan(max_hr) or np.isnan(baseline_hr))
        else 0.0
    )
    peak_mov = (
        float(np.nanmax(mov_in_edo))
        if not np.all(np.isnan(mov_in_edo))
        else 0.0
    )

    # Componentes IRD + scalar.
    ird_comps = compute_ird_components(
        drop_pct=edo["drop_pct"],
        baseline_spo2=edo["baseline_spo2"],
        delta_hr_bpm=delta_hr,
        baseline_hr_bpm=baseline_hr if not np.isnan(baseline_hr) else 0.0,
        peak_mov=peak_mov,
        baseline_mov=baseline_mov,
    )
    ird_event = compute_ird_event(ird_comps, weights=ird_weights)

    # Curvas resampleadas (sidecar).
    spo2_curve = resample_curve(spo2_vals, n_resample_points)
    hr_curve = resample_curve(hr_in_edo, n_resample_points)
    mov_curve = resample_curve(mov_in_edo, n_resample_points)

    result = {
        "ts_start": ts_start,
        "ts_end": ts_end,
        "duration_s": edo["duration_s"],
        "baseline_spo2": edo["baseline_spo2"],
        "nadir_spo2": edo["nadir_spo2"],
        "drop_pct": edo["drop_pct"],
        "slope_desat_pct_s": float(slope_desat),
        "slope_recov_pct_s": float(slope_recov),
        "auc_spo2_pct_s": auc,
        "delta_hr_bpm": float(delta_hr),
        "baseline_hr_bpm": (
            float(baseline_hr) if not np.isnan(baseline_hr) else np.nan
        ),
        "peak_mov": float(peak_mov),
        "baseline_mov": float(baseline_mov),
        "ird_spo2_comp": ird_comps["ird_spo2_comp"],
        "ird_hr_comp": ird_comps["ird_hr_comp"],
        "ird_mov_comp": ird_comps["ird_mov_comp"],
        "ird_event": ird_event,
        "_spo2_curve": spo2_curve,
        "_hr_curve": hr_curve,
        "_mov_curve": mov_curve,
        **meets,
    }
    return result
