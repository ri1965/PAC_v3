"""
Etapa 5 paso 6 — Build gold/patients.parquet.

Tabla a nivel paciente: 1 fila × paciente, ~71 cols. En el corpus
actual son 12 pacientes (escalable a ~50). Por la cardinalidad baja,
esta tabla NO se usa para inferencia estadística — es una vista
descriptiva para entender el corpus.

Estructura (~71 cols):

  - Identidad (2): user_id, model_version.
  - Demografía (de patients/clinical.csv, 7): sexo, peso_kg, talla_cm,
    apnea_prev, diabetes, hta, marcapasos. (PII excluido — el
    patient_registry queda local).
  - Conteos de noches (5): n_nights_total, n_nights_quality,
    n_nights_strict, n_nights_high_tst, n_nights_flag_for_review.
  - Agregados de índices clave (30 = 10 × 3): mean/median/sd sobre las
    noches in_quality del paciente, para 10 métricas (ahi_3, t90_frac,
    odi_3, tst_s, sleep_efficiency, mean_spo2, min_spo2, mean_hr,
    n_edos_total, mean_drop_pct).
  - Distribución agregada de morfotipos (4): frac_morpho_α/β/γ/δ
    PONDERADA por cantidad de EDOs (no promedio de fracciones de
    noches — pondera mejor noches con más EDOs).
  - Distribución agregada de PAC states (20): frac_state_{s,m,l}_*
    ponderada por ventanas totales del paciente.
  - Estabilidad fenotípica (3): cv_ahi_3_intra_patient,
    cv_t90_frac_intra_patient, cv_odi_3_intra_patient (sd/mean,
    NaN si mean=0 o solo 1 noche quality).

Decisión: TODOS los agregados se computan sobre noches in_quality
del paciente (consistente con cómo se computan las cross-night en
nights_gold).

Output: gold/patients.parquet — 12 filas × ~71 cols.

Uso:
  python scripts/build_patients_gold.py            # full build
  python scripts/build_patients_gold.py --dry-run  # no escribe disk
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

from pac.schemas import validate_patients_gold  # noqa: E402

GOLD_DIR = REPO_ROOT / "gold"
MANIFEST_PATH = REPO_ROOT / "models" / "MANIFEST.json"
CLINICAL_CSV = REPO_ROOT / "patients" / "clinical.csv"

NIGHTS_GOLD = GOLD_DIR / "nights.parquet"
EVENTS_GOLD = GOLD_DIR / "events.parquet"
STATES_GOLD = GOLD_DIR / "states.parquet"
OUT_PATH = GOLD_DIR / "patients.parquet"

# Métricas clínicas para agregar (deben existir en nights_gold)
KEY_METRICS = [
    "ahi_3",
    "t90_frac",
    "odi_3",
    "tst_s",
    "sleep_efficiency",
    "mean_spo2",
    "min_spo2",
    "mean_hr",
    "n_edos_total",
    "mean_drop_pct",
]

# Métricas para CV intra-paciente (estabilidad fenotípica)
STABILITY_METRICS = ["ahi_3", "t90_frac", "odi_3"]

# Labels canónicos por escala
STATE_LABELS = {
    "s": [f"S{i}" for i in range(6)],
    "m": [f"M{i}" for i in range(8)],
    "l": [f"L{i}" for i in range(6)],
}

MORPHO_LABELS = ["α", "β", "γ", "δ"]


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _load_model_version() -> str:
    with open(MANIFEST_PATH) as f:
        return json.load(f)["model_version"]


def _load_clinical() -> pd.DataFrame:
    """Lee clinical.csv y lo prepara para join sobre user_id."""
    df = pd.read_csv(CLINICAL_CSV, sep=";")
    df["user_id"] = df["patient_id"].astype(str)
    df = df.drop(columns=["patient_id"])
    return df


def _counts_per_patient(nights: pd.DataFrame) -> pd.DataFrame:
    """Counts de noches por paciente y por cohorte."""
    rows = []
    for uid, sub in nights.groupby("user_id"):
        rows.append(
            {
                "user_id": uid,
                "n_nights_total": int(len(sub)),
                "n_nights_quality": int(sub["in_quality"].sum()),
                "n_nights_strict": int(sub["in_strict"].sum()),
                "n_nights_high_tst": int(sub["in_high_tst"].sum()),
                "n_nights_flag_for_review": int(sub["flag_for_review"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _aggregate_metrics(nights: pd.DataFrame) -> pd.DataFrame:
    """mean/median/sd de KEY_METRICS sobre in_quality del paciente."""
    qual = nights.loc[nights["in_quality"]].copy()
    rows = []
    for uid, sub in qual.groupby("user_id"):
        row = {"user_id": uid}
        for m in KEY_METRICS:
            if m not in sub.columns:
                row[f"mean_{m}"] = np.nan
                row[f"median_{m}"] = np.nan
                row[f"sd_{m}"] = np.nan
                continue
            vals = sub[m].dropna()
            if len(vals) == 0:
                row[f"mean_{m}"] = np.nan
                row[f"median_{m}"] = np.nan
                row[f"sd_{m}"] = np.nan
            else:
                row[f"mean_{m}"] = float(vals.mean())
                row[f"median_{m}"] = float(vals.median())
                row[f"sd_{m}"] = float(vals.std(ddof=1)) if len(vals) > 1 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _morpho_distribution_weighted(events_gold: pd.DataFrame) -> pd.DataFrame:
    """
    Distribución de morfotipos ponderada por EDOs (no promedio de
    fracciones por noche). Solo EDOs en noches in_quality.
    """
    qual_edos = events_gold.loc[events_gold["in_quality"]]
    grouped = (
        qual_edos.groupby(["user_id", "morphotype"]).size().unstack(fill_value=0)
    )
    for m in MORPHO_LABELS:
        if m not in grouped.columns:
            grouped[m] = 0
    grouped = grouped[MORPHO_LABELS]
    totals = grouped.sum(axis=1)
    fracs = grouped.div(totals.where(totals > 0, 1), axis=0)
    fracs.columns = [f"frac_morpho_{m}" for m in MORPHO_LABELS]
    return fracs.reset_index()


def _state_distribution_weighted(states_gold: pd.DataFrame) -> pd.DataFrame:
    """
    Distribución de PAC states ponderada por ventanas, por escala. Solo
    ventanas en noches in_quality y con cluster_int >= 0.
    """
    valid = states_gold.loc[
        states_gold["in_quality"] & (states_gold["cluster_int"] >= 0)
    ]
    parts = []
    for scale, labels in STATE_LABELS.items():
        sub = valid.loc[valid["scale"] == scale]
        grouped = (
            sub.groupby(["user_id", "state_label"]).size().unstack(fill_value=0)
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


def _stability_cv(nights: pd.DataFrame) -> pd.DataFrame:
    """
    CV (sd/mean) intra-paciente sobre noches in_quality, para cada
    métrica en STABILITY_METRICS. NaN si mean=0 o sólo 1 noche quality.
    """
    qual = nights.loc[nights["in_quality"]].copy()
    rows = []
    for uid, sub in qual.groupby("user_id"):
        row = {"user_id": uid}
        for m in STABILITY_METRICS:
            if m not in sub.columns:
                row[f"cv_{m}_intra_patient"] = np.nan
                continue
            vals = sub[m].dropna()
            if len(vals) <= 1:
                row[f"cv_{m}_intra_patient"] = np.nan
                continue
            mean = float(vals.mean())
            if mean == 0:
                row[f"cv_{m}_intra_patient"] = np.nan
                continue
            sd = float(vals.std(ddof=1))
            row[f"cv_{m}_intra_patient"] = sd / mean
        rows.append(row)
    return pd.DataFrame(rows)


# --------------------------------------------------------------------- #
# Main builder
# --------------------------------------------------------------------- #


def build_patients_gold(verbose: bool = True) -> pd.DataFrame:
    """Construye y devuelve el DataFrame patients_gold (sin escribir disk)."""
    if not NIGHTS_GOLD.exists():
        raise FileNotFoundError(
            f"Falta {NIGHTS_GOLD}. Correr build_nights_gold.py antes."
        )
    if not EVENTS_GOLD.exists():
        raise FileNotFoundError(f"Falta {EVENTS_GOLD}.")
    if not STATES_GOLD.exists():
        raise FileNotFoundError(f"Falta {STATES_GOLD}.")

    model_version = _load_model_version()

    if verbose:
        print("[patients_gold] cargando gold/nights.parquet...")
    nights = pd.read_parquet(NIGHTS_GOLD)

    # 1. Counts
    counts = _counts_per_patient(nights)
    if verbose:
        print(f"  → counts: {len(counts)} pacientes")

    # 2. Agregados de índices
    aggs = _aggregate_metrics(nights)
    if verbose:
        print(f"  → aggs: {len(aggs)} pacientes × {len(aggs.columns) - 1} agregados")

    # 3. Estabilidad
    stab = _stability_cv(nights)
    if verbose:
        print(f"  → stability: {len(stab)} pacientes × {len(stab.columns) - 1} CV cols")

    # 4. Distribución morfotipos (ponderada)
    if verbose:
        print("[patients_gold] cargando gold/events.parquet para morfotipos...")
    events_gold = pd.read_parquet(
        EVENTS_GOLD, columns=["user_id", "morphotype", "in_quality"]
    )
    morpho = _morpho_distribution_weighted(events_gold)
    if verbose:
        print(f"  → morpho_dist: {len(morpho)} pacientes × 4 cols")

    # 5. Distribución PAC states (ponderada)
    if verbose:
        print("[patients_gold] cargando gold/states.parquet para PAC states...")
    states_gold = pd.read_parquet(
        STATES_GOLD,
        columns=["user_id", "scale", "state_label", "cluster_int", "in_quality"],
    )
    states_dist = _state_distribution_weighted(states_gold)
    if verbose:
        print(f"  → state_dist: {len(states_dist)} pacientes × 20 cols")

    # 6. Demografía
    clinical = _load_clinical()
    if verbose:
        print(f"  → clinical: {len(clinical)} pacientes")

    # 7. Merge
    out = counts.merge(clinical, on="user_id", how="left")
    out = out.merge(aggs, on="user_id", how="left")
    out = out.merge(morpho, on="user_id", how="left")
    out = out.merge(states_dist, on="user_id", how="left")
    out = out.merge(stab, on="user_id", how="left")

    # 8. Identidad / trazabilidad
    out["model_version"] = model_version

    # Reordenar: identidad primero, después demografía, después counts, después agregados
    cols_order = ["user_id", "model_version"]
    cols_order += [c for c in clinical.columns if c != "user_id"]
    cols_order += [c for c in counts.columns if c not in cols_order]
    cols_order += [c for c in aggs.columns if c not in cols_order]
    cols_order += [c for c in morpho.columns if c not in cols_order]
    cols_order += [c for c in states_dist.columns if c not in cols_order]
    cols_order += [c for c in stab.columns if c not in cols_order]
    # Verificar que no falta nada
    missing_in_order = set(out.columns) - set(cols_order)
    cols_order += sorted(missing_in_order)
    out = out[cols_order]

    # 9. Validación final (skeleton, allow_extras=True)
    validate_patients_gold(out, source="<build_patients_gold>", strict=True)

    if verbose:
        print(f"[patients_gold] OK — {len(out)} filas × {len(out.columns)} cols")
        print(f"  pacientes: {out['user_id'].nunique()}")
        print(f"  con clínica completa: {out['sexo'].notna().sum()}")
        print(f"  rango n_nights_quality: {out['n_nights_quality'].min()}-{out['n_nights_quality'].max()}")
        print(f"  mean_ahi_3 range: {out['mean_ahi_3'].min():.1f}-{out['mean_ahi_3'].max():.1f}")
        print(f"  model_version: {model_version}")

    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    df = build_patients_gold(verbose=not args.quiet)

    if args.dry_run:
        if not args.quiet:
            print(f"[patients_gold] --dry-run: NO escribo {OUT_PATH.relative_to(REPO_ROOT)}")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_kb = OUT_PATH.stat().st_size / 1024
    if not args.quiet:
        print(f"[patients_gold] escrito {OUT_PATH.relative_to(REPO_ROOT)} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
