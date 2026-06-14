"""
Etapa 5 paso 5 — Build gold/nights.parquet.

Tabla principal del producto: 1 fila × noche, con TODA la información
caracterizada (filosofía data-lake: el modelo de KMeans es UNA segmentación
arbitraria, no la fuente de verdad — la noche se describe con sus
parámetros explícitos, índices clásicos, distribuciones de morfotipo y
PAC state, métricas de transición/entropía, y comparativas vs corpus
y vs baseline del propio paciente).

Estructura (~146 cols):

  - Identidad (3): night_record_id, user_id, model_version.
  - Flags cohorte B (5): in_quality, in_strict, in_high_tst,
    flag_for_review, b2_fail.
  - Índices clásicos (~104): de events/{NR}_indices.parquet
    (TST, WASO, sleep_efficiency, T90/88/85, AHI/ODI 2/3/4/5%,
     hypoxic burden, comparaciones pac_v2 vs device, etc.).
  - Distribución de morfotipos (4): frac_morpho_α/β/γ/δ.
  - Distribución de PAC states por escala (20):
    frac_state_s_S0..S5 (6), frac_state_m_M0..M7 (8), frac_state_l_L0..L5 (6).
  - Métricas de transición y entropía (6):
    n_transitions_state_{s,m,l}, entropy_state_{s,m,l}.
  - Cross-night cohort-relative (3, calculadas SOBRE in_quality=True
    como referencia): ahi_3_pct_corpus, t90_frac_pct_corpus,
    odi_3_pct_corpus.
  - Cross-night patient-relative (3, solo pacientes con ≥3 noches
    quality): delta_ahi_3_vs_baseline_patient,
    delta_t90_frac_vs_baseline_patient, delta_odi_3_vs_baseline_patient.

El sidecar `gold/nights_columns.json` (paso 7) documentará qué
columnas son single_night vs cross_night_corpus vs cross_night_patient.

Output: gold/nights.parquet — 560 filas × ~146 cols.

Uso:
  python scripts/build_nights_gold.py            # full build
  python scripts/build_nights_gold.py --dry-run  # no escribe disk
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
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
from pac.schemas import validate_nights_gold  # noqa: E402

EVENTS_DIR = REPO_ROOT / "events"
GOLD_DIR = REPO_ROOT / "gold"
MANIFEST_PATH = REPO_ROOT / "models" / "MANIFEST.json"

EVENTS_GOLD = GOLD_DIR / "events.parquet"
STATES_GOLD = GOLD_DIR / "states.parquet"
OUT_PATH = GOLD_DIR / "nights.parquet"

# Labels canónicos por escala (consistente con los modelos K=6/8/6).
STATE_LABELS = {
    "s": [f"S{i}" for i in range(6)],
    "m": [f"M{i}" for i in range(8)],
    "l": [f"L{i}" for i in range(6)],
}

MORPHO_LABELS = ["α", "β", "γ", "δ"]

# Métricas para cross-night (deben existir en _indices.parquet).
CROSS_NIGHT_METRICS = ["ahi_3", "t90_frac", "odi_3"]
# Min noches para calcular baseline-patient
MIN_NIGHTS_FOR_BASELINE = 3


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _load_model_version() -> str:
    with open(MANIFEST_PATH) as f:
        return json.load(f)["model_version"]


def _load_indices_pooled(verbose: bool = True) -> pd.DataFrame:
    """Concat de los 560 events/{NR}_indices.parquet (1 fila/noche)."""
    files = sorted(EVENTS_DIR.glob("NR_*_indices.parquet"))
    if not files:
        raise RuntimeError(f"No hay events/NR_*_indices.parquet en {EVENTS_DIR}")
    if verbose:
        print(f"[nights_gold] leyendo {len(files)} archivos _indices.parquet...")
    parts = [pd.read_parquet(fp) for fp in files]
    df = pd.concat(parts, ignore_index=True)
    if verbose:
        print(f"  → indices_pooled: {len(df):,} filas × {len(df.columns)} cols")
    return df


def _morphotype_distribution(events_gold: pd.DataFrame) -> pd.DataFrame:
    """Para cada noche: fracción de EDOs de cada morfotipo (α/β/γ/δ).

    Si una noche no tiene EDOs, las fracciones son 0 (no NaN).
    """
    grouped = events_gold.groupby(["night_record_id", "morphotype"]).size().unstack(
        fill_value=0
    )
    # Asegurar las 4 cols (orden canónico)
    for m in MORPHO_LABELS:
        if m not in grouped.columns:
            grouped[m] = 0
    grouped = grouped[MORPHO_LABELS]
    totals = grouped.sum(axis=1)
    fracs = grouped.div(totals.where(totals > 0, 1), axis=0)
    fracs.columns = [f"frac_morpho_{m}" for m in MORPHO_LABELS]
    return fracs.reset_index()


def _state_distribution(states_gold: pd.DataFrame) -> pd.DataFrame:
    """Para cada noche × escala: fracción de ventanas en cada state_label.

    Excluye ventanas con cluster_int=-1 (NaN-drop). Devuelve un wide
    DataFrame con 20 cols (6 + 8 + 6).
    """
    valid = states_gold.loc[states_gold["cluster_int"] >= 0]
    parts = []
    for scale, labels in STATE_LABELS.items():
        sub = valid.loc[valid["scale"] == scale]
        grouped = (
            sub.groupby(["night_record_id", "state_label"])
            .size()
            .unstack(fill_value=0)
        )
        for lab in labels:
            if lab not in grouped.columns:
                grouped[lab] = 0
        grouped = grouped[labels]
        totals = grouped.sum(axis=1)
        fracs = grouped.div(totals.where(totals > 0, 1), axis=0)
        fracs.columns = [f"frac_state_{scale}_{lab}" for lab in labels]
        parts.append(fracs)

    out = pd.concat(parts, axis=1).fillna(0.0)
    return out.reset_index()


def _shannon_entropy(probs: np.ndarray) -> float:
    """Shannon entropy en bits. Ignora p=0."""
    p = probs[probs > 0]
    if len(p) == 0:
        return 0.0
    return float(-(p * np.log2(p)).sum())


def _transitions_and_entropy(states_gold: pd.DataFrame) -> pd.DataFrame:
    """Para cada noche × escala: n_transitions y entropía de la secuencia.

    n_transitions = número de cambios de state_label entre ventanas
    consecutivas (ordenadas por window_idx).
    entropy = Shannon entropy en bits de la distribución de fracciones.
    """
    valid = states_gold.loc[states_gold["cluster_int"] >= 0].copy()
    valid = valid.sort_values(["night_record_id", "scale", "window_idx"])

    rows = []
    for (nr, sc), sub in valid.groupby(["night_record_id", "scale"]):
        labels = sub["state_label"].to_numpy()
        n_trans = int((labels[1:] != labels[:-1]).sum()) if len(labels) > 1 else 0
        # entropía
        counts = pd.Series(labels).value_counts(normalize=True).to_numpy()
        ent = _shannon_entropy(counts)
        rows.append(
            {
                "night_record_id": nr,
                "scale": sc,
                "n_transitions": n_trans,
                "entropy": ent,
            }
        )
    long = pd.DataFrame(rows)

    # Pivotear a wide: 6 cols (n_transitions_state_{s,m,l}, entropy_state_{s,m,l})
    pivot_n = (
        long.pivot(index="night_record_id", columns="scale", values="n_transitions")
        .fillna(0)
        .astype(int)
    )
    pivot_n.columns = [f"n_transitions_state_{c}" for c in pivot_n.columns]
    pivot_e = long.pivot(index="night_record_id", columns="scale", values="entropy").fillna(
        0.0
    )
    pivot_e.columns = [f"entropy_state_{c}" for c in pivot_e.columns]

    return pd.concat([pivot_n, pivot_e], axis=1).reset_index()


def _cross_night_features(df: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Agrega cross-night cohort-relative (_pct_corpus) y patient-relative
    (_vs_baseline_patient) sobre las CROSS_NIGHT_METRICS.

    Política:
    - cohort-relative: percentile-rank computado SOBRE in_quality=True
      (553 noches), aplicado a TODAS las filas (incl. b2_fail). Esto
      previene contaminación de los percentiles por noches sin calidad.
    - patient-relative: delta vs mean del paciente sobre sus OTRAS noches
      quality (excluyendo la propia para no auto-referencia). Solo
      pacientes con ≥3 noches quality. NaN para los demás.
    """
    out = df.copy()
    quality_mask = out["in_quality"].astype(bool)
    quality = out.loc[quality_mask].copy()

    # ---- cohort-relative (_pct_corpus) ----
    for m in CROSS_NIGHT_METRICS:
        if m not in out.columns:
            if verbose:
                print(f"  WARN: métrica '{m}' no está en _indices, salteo cross-night")
            continue
        # Reference distribution: solo quality, sin NaN
        ref = quality[m].dropna().to_numpy()
        if len(ref) == 0:
            out[f"{m}_pct_corpus"] = np.nan
            continue
        # Para cada valor en out[m], percentile-rank vs ref
        # Implementación: searchsorted + ajuste por ties
        sorted_ref = np.sort(ref)

        def _pct(v):
            if pd.isna(v):
                return np.nan
            # rank fraccional con ties promedio (cumdist style)
            l = np.searchsorted(sorted_ref, v, side="left")
            r = np.searchsorted(sorted_ref, v, side="right")
            return float((l + r) / 2.0 / len(sorted_ref))

        out[f"{m}_pct_corpus"] = out[m].apply(_pct)

    # ---- patient-relative (_vs_baseline_patient) ----
    # Para cada paciente con ≥MIN_NIGHTS_FOR_BASELINE noches quality,
    # baseline = mean del paciente sobre las otras noches quality.
    user_n_quality = quality.groupby("user_id").size()
    eligible_users = set(
        user_n_quality.loc[user_n_quality >= MIN_NIGHTS_FOR_BASELINE].index
    )
    if verbose:
        print(
            f"  pacientes elegibles para baseline (≥{MIN_NIGHTS_FOR_BASELINE} "
            f"noches quality): {len(eligible_users)}"
        )

    for m in CROSS_NIGHT_METRICS:
        if m not in out.columns:
            continue
        col_out = f"delta_{m}_vs_baseline_patient"
        out[col_out] = np.nan
        for uid in eligible_users:
            mask_user = (out["user_id"] == uid) & quality_mask
            mask_user_q = (quality["user_id"] == uid)
            if mask_user_q.sum() < MIN_NIGHTS_FOR_BASELINE:
                continue
            user_quality = quality.loc[mask_user_q]
            for idx, row in out.loc[mask_user].iterrows():
                # Baseline: mean del paciente excluyendo esta noche
                others = user_quality.loc[
                    user_quality["night_record_id"] != row["night_record_id"], m
                ].dropna()
                if len(others) == 0:
                    continue
                baseline = float(others.mean())
                if pd.isna(row[m]):
                    continue
                out.at[idx, col_out] = float(row[m]) - baseline

    return out


# --------------------------------------------------------------------- #
# Main builder
# --------------------------------------------------------------------- #


def build_nights_gold(verbose: bool = True) -> pd.DataFrame:
    """Construye y devuelve el DataFrame nights_gold (sin escribir disk)."""
    if not EVENTS_GOLD.exists() or not STATES_GOLD.exists():
        raise FileNotFoundError(
            f"Faltan {EVENTS_GOLD} o {STATES_GOLD}. Correr build_events_gold.py "
            "y build_states_gold.py antes."
        )

    model_version = _load_model_version()
    nrs_quality = get_cohort_quality()
    nrs_strict = get_cohort_strict()
    nrs_high_tst = get_cohort_high_tst(min_tst_h=4.0)
    nrs_b2 = set(_b2_fail_excluded_nrs())
    nrs_flag = set(_flag_for_review_nrs())

    # 1. Indices clásicos (núcleo)
    indices = _load_indices_pooled(verbose=verbose)

    # 2. Distribución de morfotipos
    if verbose:
        print("[nights_gold] cargando gold/events.parquet para distribución morfotipos...")
    events_gold = pd.read_parquet(EVENTS_GOLD, columns=["night_record_id", "morphotype"])
    morpho_dist = _morphotype_distribution(events_gold)
    if verbose:
        print(f"  → morpho_dist: {len(morpho_dist):,} noches × 4 cols")

    # 3. Distribución de PAC states
    if verbose:
        print("[nights_gold] cargando gold/states.parquet para distribución states...")
    states_gold = pd.read_parquet(
        STATES_GOLD,
        columns=["night_record_id", "scale", "state_label", "cluster_int", "window_idx"],
    )
    state_dist = _state_distribution(states_gold)
    if verbose:
        print(f"  → state_dist: {len(state_dist):,} noches × 20 cols")

    # 4. Transiciones y entropía
    trans_ent = _transitions_and_entropy(states_gold)
    if verbose:
        print(f"  → trans_ent: {len(trans_ent):,} noches × 6 cols")

    # 5. Merge incremental (left-join sobre indices, que es la fuente
    #    canónica de noches: 560 filas).
    out = indices.copy()
    out = out.merge(morpho_dist, on="night_record_id", how="left")
    out = out.merge(state_dist, on="night_record_id", how="left")
    out = out.merge(trans_ent, on="night_record_id", how="left")

    # Las cols _morpho_* y frac_state_* deben ser 0 (no NaN) cuando faltan
    # (noches sin EDOs o sin ventanas válidas, raro).
    morpho_cols = [c for c in out.columns if c.startswith("frac_morpho_")]
    state_cols = [c for c in out.columns if c.startswith("frac_state_")]
    trans_cols = [c for c in out.columns if c.startswith("n_transitions_state_")]
    ent_cols = [c for c in out.columns if c.startswith("entropy_state_")]
    out[morpho_cols] = out[morpho_cols].fillna(0.0)
    out[state_cols] = out[state_cols].fillna(0.0)
    out[trans_cols] = out[trans_cols].fillna(0).astype(int)
    out[ent_cols] = out[ent_cols].fillna(0.0)

    # 6. Bloques transversales
    out["model_version"] = model_version
    out["in_quality"] = out["night_record_id"].isin(nrs_quality)
    out["in_strict"] = out["night_record_id"].isin(nrs_strict)
    out["in_high_tst"] = out["night_record_id"].isin(nrs_high_tst)
    out["flag_for_review"] = out["night_record_id"].isin(nrs_flag)
    out["b2_fail"] = out["night_record_id"].isin(nrs_b2)

    # 7. Cross-night (después de tener flags de cohorte)
    if verbose:
        print("[nights_gold] calculando cross-night cohort + patient-relative...")
    out = _cross_night_features(out, verbose=verbose)

    # 8. Validación final (skeleton, allow_extras=True)
    validate_nights_gold(out, source="<build_nights_gold>", strict=True)

    if verbose:
        print(f"[nights_gold] OK — {len(out):,} filas × {len(out.columns)} cols")
        print(f"  noches únicas:   {out['night_record_id'].nunique()}")
        print(f"  user_ids únicos: {out['user_id'].nunique()}")
        print(f"  in_quality:      {int(out['in_quality'].sum())} filas")
        print(f"  in_strict:       {int(out['in_strict'].sum())} filas")
        print(f"  in_high_tst:     {int(out['in_high_tst'].sum())} filas")
        print(f"  flag_for_review: {int(out['flag_for_review'].sum())} filas")
        print(f"  b2_fail:         {int(out['b2_fail'].sum())} filas")
        # Sanity: cuántas noches tienen baseline-patient
        n_with_baseline = (
            out["delta_ahi_3_vs_baseline_patient"].notna().sum()
            if "delta_ahi_3_vs_baseline_patient" in out.columns
            else 0
        )
        print(
            f"  con baseline patient: {n_with_baseline} noches "
            f"(de {int(out['in_quality'].sum())} quality)"
        )

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    df = build_nights_gold(verbose=not args.quiet)

    if args.dry_run:
        if not args.quiet:
            print(f"[nights_gold] --dry-run: NO escribo {OUT_PATH.relative_to(REPO_ROOT)}")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    if not args.quiet:
        print(f"[nights_gold] escrito {OUT_PATH.relative_to(REPO_ROOT)} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
