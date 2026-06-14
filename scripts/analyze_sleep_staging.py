"""
PAC_v2 — Validación del sleep staging del device (mini-etapa pre-Etapa 4).

El device emite sleep_stage ∈ {0, 1, 2, 3} inferido internamente desde
HR + movimiento. Sin ground-truth PSG, hacemos 5 checks de plausibilidad
fisiológica contra rangos de literatura:

  1. Estructura por ciclos REM-NREM (esperado: 4-6 ciclos, 90-110 min).
  2. Distribución temporal por quintiles (N3 al inicio, REM al final).
  3. Arquitectura por grupo clínico (apnea_prev, tercil ODI_3).
  4. Estabilidad de bloques (runs no fragmentados).
  5. Coherencia con morfotipos de EDOs.

Hipótesis de codificación a validar: 0=Wake, 1=REM, 2=Light, 3=Deep.

Outputs:
  reports/sleep_staging_validation.json
  reports/sleep_staging_validation.md
  reports/sleep_staging_validation.html

Corre:  PYTHONPATH=src python scripts/analyze_sleep_staging.py
        PYTHONPATH=src python scripts/analyze_sleep_staging.py --limit 20
"""
from __future__ import annotations

import argparse
import io
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import seaborn as sns

from pac.config import (
    CLINICAL_CSV,
    CSV_SEP,
    EVENTS_DIR,
    REPORTS_DIR,
    SILVER_DIR,
)

sns.set_theme(style="whitegrid", context="notebook")

# --- Hipótesis de codificación (a validar con estos checks) ----------------
STAGE_NAMES = {0: "wake", 1: "rem", 2: "light", 3: "deep"}
STAGE_COLORS = {"wake": "#d62728", "rem": "#2ca02c", "light": "#1f77b4", "deep": "#9467bd"}

# --- Rangos esperados de literatura ----------------------------------------
EXPECTED = {
    "n_cycles": (4, 6),
    "cycle_duration_min": (70, 120),  # mediana esperada
    "rem_pct": (0.15, 0.25),           # fracción del TST
    "deep_pct": (0.10, 0.25),
    "wake_pct_max": 0.30,              # WASO > 30% es anormal
    "short_run_pct_max": 0.40,          # % runs ≤30s
    "median_n3_run_min": (10, 25),
    "median_rem_run_min": (10, 30),
}

OUTPUT_JSON = REPORTS_DIR / "sleep_staging_validation.json"
OUTPUT_MD = REPORTS_DIR / "sleep_staging_validation.md"
OUTPUT_HTML = REPORTS_DIR / "sleep_staging_validation.html"


# ===========================================================================
# Helpers
# ===========================================================================

def run_length_encoding(seq: np.ndarray) -> list[tuple[int, int]]:
    """Returns list of (value, length) tuples. Treats NaN as its own value."""
    if len(seq) == 0:
        return []
    # Treat NaN as sentinel
    seq = np.where(pd.isna(seq), -1, seq).astype(int)
    changes = np.concatenate([[0], np.where(np.diff(seq) != 0)[0] + 1, [len(seq)]])
    return [(int(seq[changes[i]]), int(changes[i+1] - changes[i])) for i in range(len(changes)-1)]


def count_cycles(stages: np.ndarray) -> tuple[int, float]:
    """
    Detecta ciclos de sueño via transiciones a REM (stage=1).
    Un "ciclo" = entrada a REM precedida por al menos 5 min de NREM.

    Returns: (n_cycles, median_cycle_duration_min).
    """
    # runs después de filtrar wake al inicio/final
    if len(stages) == 0:
        return 0, float("nan")

    rle = run_length_encoding(stages)
    # Tiempos acumulativos (cada run en segundos: asumimos 1Hz).
    rem_entry_times = []
    t = 0
    prev_was_nrem = False
    nrem_accum = 0

    for stage, length in rle:
        if stage == 1:  # REM
            # Aceptamos entrada a REM si tuvimos ≥300s de NREM (Light+Deep) previos.
            if nrem_accum >= 300:
                rem_entry_times.append(t)
            nrem_accum = 0
        elif stage in (2, 3):
            nrem_accum += length
        else:  # wake or unknown
            nrem_accum = 0
        t += length

    n_cycles = len(rem_entry_times)
    if n_cycles >= 2:
        diffs_min = np.diff(rem_entry_times) / 60.0
        median_cycle_min = float(np.median(diffs_min))
    else:
        median_cycle_min = float("nan")

    return n_cycles, median_cycle_min


def quintile_composition(stages: np.ndarray) -> np.ndarray:
    """
    Divide la noche en 5 quintiles temporales y devuelve matriz 5×4
    de fracciones (quintil × stage).
    """
    result = np.zeros((5, 4))
    if len(stages) == 0:
        return result
    chunks = np.array_split(stages, 5)
    for i, chunk in enumerate(chunks):
        for s in (0, 1, 2, 3):
            result[i, s] = float((chunk == s).mean()) if len(chunk) > 0 else 0.0
    return result


def run_length_stats(stages: np.ndarray) -> dict:
    """
    Para cada stage, devuelve:
      median_run_s: mediana de duración de runs (en segundos)
      n_runs: total de runs
      pct_short: fracción de runs ≤30s
    """
    rle = run_length_encoding(stages)
    out: dict = {}
    for s in (0, 1, 2, 3):
        runs = [length for stage, length in rle if stage == s]
        if runs:
            out[STAGE_NAMES[s]] = {
                "median_run_s": float(np.median(runs)),
                "n_runs": len(runs),
                "pct_short": float(sum(1 for r in runs if r <= 30) / len(runs)),
            }
        else:
            out[STAGE_NAMES[s]] = {"median_run_s": float("nan"), "n_runs": 0, "pct_short": 0.0}
    return out


def stage_fractions(stages: np.ndarray) -> dict:
    """Fracción global de cada stage sobre TODAS las muestras de la noche."""
    if len(stages) == 0:
        return {STAGE_NAMES[s]: 0.0 for s in (0, 1, 2, 3)}
    return {STAGE_NAMES[s]: float((stages == s).mean()) for s in (0, 1, 2, 3)}


# ===========================================================================
# Procesamiento por noche
# ===========================================================================

def analyze_one_night(
    silver_path: Path,
    edo_path: Path | None,
) -> dict:
    """Computes all 5 check metrics for one night."""
    tbl = pq.read_table(silver_path, columns=["timestamp", "sleep_stage"])
    df = tbl.to_pandas()
    stages = df["sleep_stage"].to_numpy()
    ts_start = pd.Timestamp(df["timestamp"].iloc[0]) if len(df) else None

    n_cycles, cycle_med = count_cycles(stages)
    quint = quintile_composition(stages)
    rls = run_length_stats(stages)
    frac = stage_fractions(stages)

    # Check 5 — Coherencia morfotipos × stages.
    # Para cada EDO, vemos el stage en t_start. Si el archivo existe.
    morphotype_xtab = {}
    if edo_path is not None and edo_path.exists():
        edos = pq.read_table(edo_path, columns=["ts_start", "morphotype"]).to_pandas()
        if len(edos) > 0 and ts_start is not None:
            # Index sleep_stage por timestamp para lookup rápido.
            df_idx = df.set_index("timestamp")["sleep_stage"]
            stage_at_event = []
            for ts in edos["ts_start"]:
                ts_p = pd.Timestamp(ts)
                if ts_p in df_idx.index:
                    stage_at_event.append(int(df_idx.loc[ts_p]))
                else:
                    # Nearest sample
                    try:
                        nearest = df_idx.index.get_indexer([ts_p], method="nearest")[0]
                        stage_at_event.append(int(df_idx.iloc[nearest]))
                    except Exception:
                        stage_at_event.append(-1)
            edos["sleep_stage"] = stage_at_event
            valid = edos[(edos["sleep_stage"] >= 0) & edos["morphotype"].notna()]
            for m in ("α", "β", "γ", "δ"):
                sub = valid[valid["morphotype"] == m]
                for s in (0, 1, 2, 3):
                    key = f"{m}_{STAGE_NAMES[s]}"
                    morphotype_xtab[key] = int((sub["sleep_stage"] == s).sum())

    return {
        "night_record_id": silver_path.stem,
        "n_samples": int(len(stages)),
        "duration_s": int(len(stages)),  # 1 Hz
        "n_cycles": int(n_cycles),
        "cycle_median_min": cycle_med,
        "quintile_composition": quint.tolist(),  # 5x4
        "stage_fractions": frac,
        "run_length_stats": rls,
        "morphotype_xtab": morphotype_xtab,
    }


# ===========================================================================
# Agregación pool
# ===========================================================================

def aggregate_pool(per_night: list[dict], clinical_df: pd.DataFrame, indices_df: pd.DataFrame) -> dict:
    """Agrega métricas al nivel pool (560 noches)."""
    df = pd.DataFrame([
        {
            "night_record_id": r["night_record_id"],
            "n_cycles": r["n_cycles"],
            "cycle_median_min": r["cycle_median_min"],
            **{f"frac_{s}": r["stage_fractions"][s] for s in ("wake", "rem", "light", "deep")},
            **{f"median_run_s_{s}": r["run_length_stats"][s]["median_run_s"] for s in ("wake", "rem", "light", "deep")},
            **{f"pct_short_{s}": r["run_length_stats"][s]["pct_short"] for s in ("wake", "rem", "light", "deep")},
        }
        for r in per_night
    ])

    # --- Check 1: ciclos ---
    check1 = {
        "n_nights_with_cycle_data": int(df["cycle_median_min"].notna().sum()),
        "n_cycles_median": float(df["n_cycles"].median()),
        "n_cycles_p25_p75": [float(df["n_cycles"].quantile(0.25)), float(df["n_cycles"].quantile(0.75))],
        "n_cycles_in_range_pct": float(((df["n_cycles"] >= EXPECTED["n_cycles"][0]) & (df["n_cycles"] <= EXPECTED["n_cycles"][1])).mean()),
        "cycle_duration_median_min": float(df["cycle_median_min"].median(skipna=True)),
        "cycle_duration_in_range_pct": float(((df["cycle_median_min"] >= EXPECTED["cycle_duration_min"][0]) & (df["cycle_median_min"] <= EXPECTED["cycle_duration_min"][1])).mean()),
    }

    # --- Check 2: distribución por quintiles (promedio pool) ---
    quint_stack = np.stack([np.array(r["quintile_composition"]) for r in per_night])  # (N, 5, 4)
    mean_quint = quint_stack.mean(axis=0)  # 5x4
    check2 = {
        "mean_quintile_composition": mean_quint.tolist(),
        "n3_Q1_pct": float(mean_quint[0, 3]),
        "n3_Q5_pct": float(mean_quint[4, 3]),
        "rem_Q1_pct": float(mean_quint[0, 1]),
        "rem_Q5_pct": float(mean_quint[4, 1]),
        "n3_decreasing": bool(mean_quint[0, 3] > mean_quint[4, 3]),
        "rem_increasing": bool(mean_quint[0, 1] < mean_quint[4, 1]),
    }

    # --- Check 3: arquitectura por grupo clínico ---
    # (a) Por apnea_prev (si tenemos clinical.csv).
    # Necesitamos mapping NR → patient_id → clinical.
    # Los KV metadata de silver tienen user_id; indices_df también.
    pool = df.merge(indices_df[["night_record_id", "user_id", "odi_3", "sleep_efficiency", "tst_s"]], on="night_record_id", how="left")
    pool["user_id"] = pool["user_id"].astype(str)
    clinical_df = clinical_df.copy()
    clinical_df["patient_id"] = clinical_df["patient_id"].astype(str)
    pool = pool.merge(clinical_df[["patient_id", "apnea_prev"]], left_on="user_id", right_on="patient_id", how="left")

    n_clinical = int(pool["apnea_prev"].notna().sum())
    apnea_arch = None
    if n_clinical > 0:
        apnea_arch = pool.groupby("apnea_prev")[[f"frac_{s}" for s in ("wake", "rem", "light", "deep")] + ["sleep_efficiency"]].mean().round(4).to_dict(orient="index")

    # (b) Por tercil ODI_3.
    pool["odi_tercile"] = pd.qcut(pool["odi_3"], q=3, labels=["low", "mid", "high"], duplicates="drop")
    odi_arch = pool.groupby("odi_tercile", observed=True)[[f"frac_{s}" for s in ("wake", "rem", "light", "deep")] + ["sleep_efficiency", "odi_3"]].mean().round(4).to_dict(orient="index")

    check3 = {
        "n_nights_with_clinical": n_clinical,
        "by_apnea_prev": apnea_arch,
        "by_odi_tercile": odi_arch,
        "pool_mean_stage_fractions": {s: float(pool[f"frac_{s}"].mean()) for s in ("wake", "rem", "light", "deep")},
        "rem_pct_in_literature_range_pct": float(((pool["frac_rem"] >= EXPECTED["rem_pct"][0]) & (pool["frac_rem"] <= EXPECTED["rem_pct"][1])).mean()),
        "deep_pct_in_literature_range_pct": float(((pool["frac_deep"] >= EXPECTED["deep_pct"][0]) & (pool["frac_deep"] <= EXPECTED["deep_pct"][1])).mean()),
    }

    # --- Check 4: run-length ---
    check4 = {}
    for s in ("wake", "rem", "light", "deep"):
        check4[s] = {
            "median_run_s_median": float(df[f"median_run_s_{s}"].median(skipna=True)),
            "median_run_min_median": float(df[f"median_run_s_{s}"].median(skipna=True) / 60.0),
            "pct_short_median": float(df[f"pct_short_{s}"].median(skipna=True)),
            "pct_nights_above_40pct_short": float((df[f"pct_short_{s}"] > 0.40).mean()),
        }

    # --- Check 5: morfotipos × stages ---
    all_xtab = Counter()
    for r in per_night:
        for k, v in r["morphotype_xtab"].items():
            all_xtab[k] += v
    # Reshape: dict[morphotype] -> dict[stage] -> count
    xtab_matrix = {m: {s: int(all_xtab.get(f"{m}_{s}", 0)) for s in ("wake", "rem", "light", "deep")} for m in ("α", "β", "γ", "δ")}
    # Fracciones por morphotype (normalizadas por fila).
    xtab_pct = {}
    for m, d in xtab_matrix.items():
        total = sum(d.values())
        xtab_pct[m] = {s: (v / total if total > 0 else 0.0) for s, v in d.items()}

    check5 = {
        "counts": xtab_matrix,
        "row_normalized_fractions": xtab_pct,
        "gamma_in_sleep_pct": (xtab_pct["γ"]["rem"] + xtab_pct["γ"]["light"] + xtab_pct["γ"]["deep"]) if xtab_matrix["γ"] else 0.0,
    }

    return {
        "pool_stats": {
            "n_nights": len(df),
            "n_with_clinical": n_clinical,
        },
        "check1_cycles": check1,
        "check2_quintiles": check2,
        "check3_architecture": check3,
        "check4_runlength": check4,
        "check5_morphotype_xtab": check5,
        "pool_df_summary": df.describe().round(4).to_dict(),
    }


# ===========================================================================
# Reportes (MD + HTML)
# ===========================================================================

def _verdict(value: float, expected_range: tuple, comp: str = "in") -> str:
    """Emite un veredicto textual ✓/✗/~"""
    if pd.isna(value):
        return "?"
    if comp == "in":
        lo, hi = expected_range
        if lo <= value <= hi:
            return "✓"
        elif lo * 0.8 <= value <= hi * 1.2:
            return "~"
        return "✗"
    elif comp == "max":
        if value <= expected_range:
            return "✓"
        elif value <= expected_range * 1.3:
            return "~"
        return "✗"
    return "?"


def generate_md_report(pool: dict, timestamp: str, n_input_nights: int) -> str:
    c1 = pool["check1_cycles"]
    c2 = pool["check2_quintiles"]
    c3 = pool["check3_architecture"]
    c4 = pool["check4_runlength"]
    c5 = pool["check5_morphotype_xtab"]
    ps = pool["pool_stats"]

    lines = []
    lines.append("# Validación del sleep staging del device — 560 noches\n")
    lines.append(f"_Generado {timestamp} · {n_input_nights} noches analizadas_\n")
    lines.append("El dispositivo emite `sleep_stage` ∈ {0,1,2,3} inferido internamente "
                 "desde HR + mov. Sin PSG ground-truth, hacemos 5 checks de "
                 "plausibilidad fisiológica.\n")
    lines.append("**Hipótesis de codificación a validar**: `0=Wake, 1=REM, 2=Light, 3=Deep`.\n")

    # ---------------- Check 1 ----------------
    lines.append("## Check 1 — Estructura por ciclos REM-NREM\n")
    lines.append(f"Rango esperado (literatura): {EXPECTED['n_cycles'][0]}–{EXPECTED['n_cycles'][1]} ciclos por noche, "
                 f"duración {EXPECTED['cycle_duration_min'][0]}–{EXPECTED['cycle_duration_min'][1]} min.\n")
    lines.append(f"- Ciclos/noche — mediana: **{c1['n_cycles_median']:.1f}** (IQR {c1['n_cycles_p25_p75'][0]:.1f}–{c1['n_cycles_p25_p75'][1]:.1f}) — {_verdict(c1['n_cycles_median'], EXPECTED['n_cycles'])}")
    lines.append(f"- % noches con # ciclos en rango: **{100*c1['n_cycles_in_range_pct']:.1f}%**")
    lines.append(f"- Duración mediana de ciclo: **{c1['cycle_duration_median_min']:.1f} min** — {_verdict(c1['cycle_duration_median_min'], EXPECTED['cycle_duration_min'])}")
    lines.append(f"- % noches con duración de ciclo en rango: **{100*c1['cycle_duration_in_range_pct']:.1f}%**\n")

    # ---------------- Check 2 ----------------
    lines.append("## Check 2 — Distribución temporal por quintiles\n")
    lines.append("Esperado: N3 (Deep) concentrado al inicio de la noche (Q1 > Q5), REM al final (Q1 < Q5).\n")
    mean_q = np.array(c2["mean_quintile_composition"])
    lines.append("| Quintil | Wake | REM | Light | Deep |")
    lines.append("|---|---|---|---|---|")
    for i in range(5):
        lines.append(f"| Q{i+1} | {mean_q[i,0]:.3f} | {mean_q[i,1]:.3f} | {mean_q[i,2]:.3f} | {mean_q[i,3]:.3f} |")
    lines.append("")
    n3_dec = "✓" if c2["n3_decreasing"] else "✗"
    rem_inc = "✓" if c2["rem_increasing"] else "✗"
    lines.append(f"- Deep (N3) decreciente Q1→Q5: {c2['n3_Q1_pct']:.3f} → {c2['n3_Q5_pct']:.3f} — {n3_dec}")
    lines.append(f"- REM creciente Q1→Q5: {c2['rem_Q1_pct']:.3f} → {c2['rem_Q5_pct']:.3f} — {rem_inc}\n")

    # ---------------- Check 3 ----------------
    lines.append("## Check 3 — Arquitectura por grupo clínico\n")
    lines.append(f"Noches con clinical.csv disponible: **{c3['n_nights_with_clinical']}** / {ps['n_nights']}.\n")
    pm = c3["pool_mean_stage_fractions"]
    lines.append(f"Arquitectura promedio pool: Wake={pm['wake']:.3f} · REM={pm['rem']:.3f} · "
                 f"Light={pm['light']:.3f} · Deep={pm['deep']:.3f}.\n")
    lines.append(f"- % noches con REM en rango literatura ({EXPECTED['rem_pct'][0]:.2f}–{EXPECTED['rem_pct'][1]:.2f}): "
                 f"**{100*c3['rem_pct_in_literature_range_pct']:.1f}%**")
    lines.append(f"- % noches con Deep en rango literatura ({EXPECTED['deep_pct'][0]:.2f}–{EXPECTED['deep_pct'][1]:.2f}): "
                 f"**{100*c3['deep_pct_in_literature_range_pct']:.1f}%**\n")

    if c3["by_apnea_prev"]:
        lines.append("### Por `apnea_prev`\n")
        lines.append("| apnea_prev | frac_wake | frac_rem | frac_light | frac_deep | SE |")
        lines.append("|---|---|---|---|---|---|")
        for group, stats in c3["by_apnea_prev"].items():
            lines.append(f"| {group} | {stats['frac_wake']:.3f} | {stats['frac_rem']:.3f} | "
                         f"{stats['frac_light']:.3f} | {stats['frac_deep']:.3f} | {stats['sleep_efficiency']:.3f} |")
        lines.append("")

    if c3["by_odi_tercile"]:
        lines.append("### Por tercil de ODI_3 (severidad)\n")
        lines.append("| tercil | frac_wake | frac_rem | frac_light | frac_deep | SE | ODI_3 |")
        lines.append("|---|---|---|---|---|---|---|")
        for group, stats in c3["by_odi_tercile"].items():
            lines.append(f"| {group} | {stats['frac_wake']:.3f} | {stats['frac_rem']:.3f} | "
                         f"{stats['frac_light']:.3f} | {stats['frac_deep']:.3f} | "
                         f"{stats['sleep_efficiency']:.3f} | {stats['odi_3']:.2f} |")
        lines.append("")

    # ---------------- Check 4 ----------------
    lines.append("## Check 4 — Estabilidad de bloques (run-length)\n")
    lines.append(f"Esperado: runs de N3 ~{EXPECTED['median_n3_run_min'][0]}–{EXPECTED['median_n3_run_min'][1]} min, "
                 f"runs REM ~{EXPECTED['median_rem_run_min'][0]}–{EXPECTED['median_rem_run_min'][1]} min. "
                 f"**{int(EXPECTED['short_run_pct_max']*100)}%+** de runs ≤30s = sobre-fragmentado.\n")
    lines.append("| stage | median run (min) | % runs ≤30s | % noches > 40% short |")
    lines.append("|---|---|---|---|")
    for s in ("wake", "rem", "light", "deep"):
        st = c4[s]
        lines.append(f"| {s} | {st['median_run_min_median']:.1f} | "
                     f"{100*st['pct_short_median']:.1f}% | {100*st['pct_nights_above_40pct_short']:.1f}% |")
    lines.append("")

    # ---------------- Check 5 ----------------
    lines.append("## Check 5 — Coherencia morfotipos × sleep_stage\n")
    lines.append("Esperado fisiológico (hipótesis): γ (severos) sobre-representados en REM "
                 "(atonía muscular). β (respuesta motora) en Light.\n")
    counts = c5["counts"]
    lines.append("**Conteos brutos:**")
    lines.append("| morphotype | wake | rem | light | deep | total |")
    lines.append("|---|---|---|---|---|---|")
    for m in ("α", "β", "γ", "δ"):
        d = counts[m]
        total = sum(d.values())
        lines.append(f"| {m} | {d['wake']} | {d['rem']} | {d['light']} | {d['deep']} | {total} |")
    lines.append("")
    lines.append("**Fracciones (normalizadas por fila):**")
    lines.append("| morphotype | wake | rem | light | deep |")
    lines.append("|---|---|---|---|---|")
    pct = c5["row_normalized_fractions"]
    for m in ("α", "β", "γ", "δ"):
        d = pct[m]
        lines.append(f"| {m} | {d['wake']:.3f} | {d['rem']:.3f} | {d['light']:.3f} | {d['deep']:.3f} |")
    lines.append("")

    # ---------------- Veredicto ----------------
    lines.append("## Veredicto\n")
    # Criterios de decisión:
    signals_ok = 0
    signals_fail = 0
    reasons = []

    # Ciclo count en rango
    if c1["n_cycles_in_range_pct"] >= 0.5:
        signals_ok += 1; reasons.append("✓ #ciclos típicos")
    else:
        signals_fail += 1; reasons.append(f"✗ #ciclos fuera de rango en {100*(1-c1['n_cycles_in_range_pct']):.0f}% de noches")
    # Duración ciclo
    if EXPECTED["cycle_duration_min"][0] <= c1["cycle_duration_median_min"] <= EXPECTED["cycle_duration_min"][1]:
        signals_ok += 1; reasons.append("✓ duración ciclo en rango")
    else:
        signals_fail += 1; reasons.append(f"✗ duración ciclo mediana = {c1['cycle_duration_median_min']:.1f} min")
    # N3 decreciente
    if c2["n3_decreasing"]:
        signals_ok += 1; reasons.append("✓ N3 decreciente Q1→Q5")
    else:
        signals_fail += 1; reasons.append("✗ N3 no decrece a lo largo de la noche")
    # REM creciente
    if c2["rem_increasing"]:
        signals_ok += 1; reasons.append("✓ REM creciente Q1→Q5")
    else:
        signals_fail += 1; reasons.append("✗ REM no crece a lo largo de la noche")
    # Fragmentación
    light_short = c4["light"]["pct_short_median"]
    if light_short <= 0.5:
        signals_ok += 1; reasons.append(f"✓ Light no sobre-fragmentado ({100*light_short:.0f}% short)")
    else:
        signals_fail += 1; reasons.append(f"✗ Light sobre-fragmentado ({100*light_short:.0f}% short)")

    total_signals = signals_ok + signals_fail
    pct_ok = signals_ok / total_signals if total_signals > 0 else 0.0

    if pct_ok >= 0.8:
        recomendacion = "**USAR TAL CUAL**"
        txt = "El staging del device es fisiológicamente plausible. Proceder con Etapa 4 usándolo como feature."
    elif pct_ok >= 0.5:
        recomendacion = "**USAR CON CAVEATS**"
        txt = "El staging pasa algunos checks pero falla otros. Usar en Etapa 4 documentando las limitaciones en la discusión de tesis."
    else:
        recomendacion = "**REPENSAR**"
        txt = "Varios checks críticos fallan. Considerar implementar staging propio (Escenario B/C) antes de Etapa 4."

    lines.append(f"**Señales OK**: {signals_ok}/{total_signals} ({100*pct_ok:.0f}%)\n")
    for r in reasons:
        lines.append(f"- {r}")
    lines.append("")
    lines.append(f"### Recomendación: {recomendacion}\n")
    lines.append(txt)
    lines.append("")
    lines.append("_Nota: esta es una validación indirecta sin PSG ground-truth. "
                 "Las discordancias sugieren pero no prueban error del device._")
    return "\n".join(lines)


# ===========================================================================
# HTML dashboard
# ===========================================================================

def _fig_to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def generate_html_dashboard(pool: dict, timestamp: str) -> str:
    c2 = pool["check2_quintiles"]
    c3 = pool["check3_architecture"]
    c4 = pool["check4_runlength"]
    c5 = pool["check5_morphotype_xtab"]

    # Plot 1: Quintiles stacked bar
    fig1, ax1 = plt.subplots(figsize=(8, 4))
    mean_q = np.array(c2["mean_quintile_composition"])
    bottom = np.zeros(5)
    for s_idx, s_name in enumerate(("wake", "rem", "light", "deep")):
        ax1.bar(range(1, 6), mean_q[:, s_idx], bottom=bottom,
                color=STAGE_COLORS[s_name], label=s_name.upper())
        bottom += mean_q[:, s_idx]
    ax1.set_xlabel("Quintil de la noche")
    ax1.set_ylabel("Fracción")
    ax1.set_title("Check 2 — Composición por quintil temporal (promedio pool)")
    ax1.legend(loc="upper right", framealpha=0.9)
    ax1.set_xticks(range(1, 6))
    ax1.set_xticklabels(["Q1\n(inicio)", "Q2", "Q3", "Q4", "Q5\n(final)"])
    svg1 = _fig_to_svg(fig1)

    # Plot 2: run-length por stage
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    stages_list = ["wake", "rem", "light", "deep"]
    median_mins = [c4[s]["median_run_min_median"] for s in stages_list]
    colors = [STAGE_COLORS[s] for s in stages_list]
    bars = ax2.bar(stages_list, median_mins, color=colors)
    # Expected range como líneas horizontales
    ax2.axhspan(EXPECTED["median_n3_run_min"][0], EXPECTED["median_n3_run_min"][1], alpha=0.1, color="green", label="rango literatura N3/REM")
    ax2.set_ylabel("Mediana de duración de run (min)")
    ax2.set_title("Check 4 — Duración mediana de runs por stage (pool)")
    ax2.legend()
    for bar, val in zip(bars, median_mins):
        ax2.text(bar.get_x() + bar.get_width()/2, val, f"{val:.1f}",
                 ha="center", va="bottom")
    svg2 = _fig_to_svg(fig2)

    # Plot 3: morphotype × stage heatmap
    fig3, ax3 = plt.subplots(figsize=(7, 4))
    pct = c5["row_normalized_fractions"]
    morph = ("α", "β", "γ", "δ")
    mat = np.array([[pct[m][s] for s in stages_list] for m in morph])
    sns.heatmap(mat, annot=True, fmt=".3f", cmap="YlOrRd",
                xticklabels=[s.upper() for s in stages_list],
                yticklabels=list(morph), ax=ax3, cbar_kws={"label": "fracción"})
    ax3.set_title("Check 5 — Cross-tab morphotype × sleep_stage (row-normalized)")
    ax3.set_xlabel("sleep_stage")
    ax3.set_ylabel("morphotype")
    svg3 = _fig_to_svg(fig3)

    # Plot 4: arquitectura por tercil ODI
    svg4 = ""
    if c3["by_odi_tercile"]:
        fig4, ax4 = plt.subplots(figsize=(8, 4))
        tercils = list(c3["by_odi_tercile"].keys())
        bottom = np.zeros(len(tercils))
        for s in stages_list:
            vals = np.array([c3["by_odi_tercile"][t][f"frac_{s}"] for t in tercils])
            ax4.bar(tercils, vals, bottom=bottom, color=STAGE_COLORS[s], label=s.upper())
            bottom += vals
        ax4.set_ylabel("Fracción")
        ax4.set_title("Check 3 — Arquitectura del sueño por tercil de ODI_3")
        ax4.legend()
        svg4 = _fig_to_svg(fig4)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Sleep staging validation — PAC_v2</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 20px; color: #222; line-height: 1.5; }}
  h1 {{ color: #1a1a1a; border-bottom: 2px solid #1f77b4; padding-bottom: 8px; }}
  h2 {{ color: #1f77b4; margin-top: 36px; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 24px; }}
  .panel {{ background: #f9f9fa; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px; margin: 16px 0; }}
  .panel svg {{ max-width: 100%; height: auto; }}
  .verdict {{ padding: 12px 16px; border-radius: 6px; font-weight: 500; margin: 8px 0; }}
  .verdict.ok {{ background: #e6f4ea; border-left: 4px solid #2ca02c; }}
  .verdict.warn {{ background: #fff4e0; border-left: 4px solid #ff9800; }}
  .verdict.fail {{ background: #fde8e6; border-left: 4px solid #d62728; }}
  table {{ border-collapse: collapse; margin: 8px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 12px; text-align: right; }}
  th {{ background: #f0f0f0; }}
</style>
</head>
<body>
<h1>Validación del sleep staging del device</h1>
<div class="meta">Generado {timestamp} · Pool: {pool["pool_stats"]["n_nights"]} noches</div>

<p>El dispositivo emite <code>sleep_stage</code> ∈ {{0, 1, 2, 3}} inferido desde HR + movimiento.
Sin PSG de referencia, hacemos 5 checks de plausibilidad fisiológica contra rangos de literatura.</p>

<p><strong>Hipótesis de codificación a validar</strong>: 0=Wake, 1=REM, 2=Light, 3=Deep.</p>

<h2>Check 2 — Distribución temporal</h2>
<div class="panel">{svg1}</div>
<p>Esperado: N3 (Deep) dominante al inicio (Q1), REM creciente hacia el final (Q5).</p>

<h2>Check 3 — Arquitectura por severidad (tercil ODI_3)</h2>
<div class="panel">{svg4}</div>
<p>Esperado: pacientes con ODI alto → menos REM, más Wake, SE más baja.</p>

<h2>Check 4 — Estabilidad de bloques</h2>
<div class="panel">{svg2}</div>
<p>Esperado: runs mediana N3 y REM en 10–30 min. Runs &lt;5 min sugieren sobre-fragmentación artificial.</p>

<h2>Check 5 — Coherencia morfotipos × stages</h2>
<div class="panel">{svg3}</div>
<p>Esperado fisiológico: γ (EDOs severos) sobre-representados en REM (atonía muscular → apneas obstructivas largas).</p>

<hr>
<p style="color: #888; font-size: 0.85em;">Reporte completo en <code>reports/sleep_staging_validation.md</code>.
JSON de métricas por noche en <code>sleep_staging_validation.json</code>.</p>
</body>
</html>"""
    return html


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Valida sleep_stage del device sobre pool de noches")
    parser.add_argument("--limit", type=int, default=None, help="Procesar solo N primeras noches")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print("[validate-sleep] consolidando pool de índices + clinical …")
    clinical_df = pd.read_csv(CLINICAL_CSV, sep=CSV_SEP)
    indices_paths = sorted(EVENTS_DIR.glob("NR_*_indices.parquet"))

    # Consolidar indices pool para obtener user_id + odi_3.
    indices_list = []
    for p in indices_paths:
        try:
            tbl = pq.read_table(p, columns=["night_record_id", "odi_3", "sleep_efficiency", "tst_s"])
            df = tbl.to_pandas()
            # user_id vive en KV metadata.
            kv = dict(tbl.schema.metadata or {})
            uid = kv.get(b"user_id", b"").decode()
            df["user_id"] = uid
            indices_list.append(df)
        except Exception:
            continue
    indices_df = pd.concat(indices_list, ignore_index=True) if indices_list else pd.DataFrame()
    print(f"         pool de indices: {len(indices_df)} noches · {indices_df['user_id'].nunique()} pacientes únicos")
    print(f"         clinical.csv: {len(clinical_df)} pacientes con info")

    silver_paths = sorted(
        p for p in SILVER_DIR.glob("NR_*.parquet")
        if not p.stem.endswith("_qc")
    )
    if args.limit:
        silver_paths = silver_paths[: args.limit]
    print(f"[validate-sleep] analizando {len(silver_paths)} noches …")

    per_night = []
    t0 = time.time()
    for i, sp in enumerate(silver_paths, start=1):
        nr = sp.stem
        ep = EVENTS_DIR / f"{nr}_edos.parquet"
        try:
            r = analyze_one_night(sp, ep)
            per_night.append(r)
            if args.verbose or i % 50 == 0 or i == len(silver_paths):
                print(f"  [{i:4d}/{len(silver_paths)}] {nr}: cycles={r['n_cycles']} "
                      f"frac_rem={r['stage_fractions']['rem']:.2f}")
        except Exception as e:
            print(f"  [{i:4d}/{len(silver_paths)}] FAIL {nr}: {e}")
    elapsed = time.time() - t0

    print(f"[validate-sleep] agregando pool ({len(per_night)} noches procesadas) …")
    pool = aggregate_pool(per_night, clinical_df, indices_df)
    pool["timestamp"] = datetime.now().isoformat(timespec="seconds")
    pool["elapsed_s"] = round(elapsed, 2)
    pool["n_nights_analyzed"] = len(per_night)

    # Persistir JSON (incluye per_night + agregado).
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = {"pool": pool, "per_night": per_night}
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"[validate-sleep] JSON: {OUTPUT_JSON.name}")

    md = generate_md_report(pool, pool["timestamp"], len(per_night))
    with open(OUTPUT_MD, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[validate-sleep] MD: {OUTPUT_MD.name}")

    html = generate_html_dashboard(pool, pool["timestamp"])
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[validate-sleep] HTML: {OUTPUT_HTML.name}")

    # Final summary.
    c1 = pool["check1_cycles"]
    c2 = pool["check2_quintiles"]
    print()
    print(f"[validate-sleep] DONE — {len(per_night)} noches en {elapsed:.1f}s")
    print(f"  #ciclos mediana: {c1['n_cycles_median']:.1f} (esperado 4-6)")
    print(f"  duración ciclo mediana: {c1['cycle_duration_median_min']:.1f} min (esperado 70-120)")
    print(f"  N3 Q1→Q5: {c2['n3_Q1_pct']:.3f} → {c2['n3_Q5_pct']:.3f} (decreciente? {c2['n3_decreasing']})")
    print(f"  REM Q1→Q5: {c2['rem_Q1_pct']:.3f} → {c2['rem_Q5_pct']:.3f} (creciente? {c2['rem_increasing']})")


if __name__ == "__main__":
    main()
