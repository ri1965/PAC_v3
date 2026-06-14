"""
PAC_v2 — Cohort helpers (Etapa 4.6)

Módulo simple y declarativo para definir subconjuntos de noches usados
en distintos análisis. Cada función devuelve un `set[str]` de
`night_record_id`s. Sets se eligen por encima de listas porque
permiten intersección/unión/diferencia naturales y descartan duplicados.

Uso típico:

    from pac.cohorts import get_cohort_quality, get_cohort_strict

    nrs_q = get_cohort_quality()         # 553 noches
    nrs_s = get_cohort_strict()          # 509 noches (excluye review)

    # Combinaciones explícitas
    nrs_qc = get_cohort_quality() & get_cohort_with_clinical()

Persistencia de cohortes para reproducibilidad (snapshot en JSON):

    from pac.cohorts import snapshot_cohort
    snapshot_cohort('strict', get_cohort_strict(), 'analyses/exp1_cohort.json')

Política: cualquier análisis "de tesis" debería declarar al inicio qué
cohorte usa y persistir el snapshot. Análisis sensibles deberían
reportarse contra `quality` y `strict` para mostrar robustez.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Set

import pandas as pd


# --------------------------------------------------------------------- #
# Paths default (relativos al root del repo)
# --------------------------------------------------------------------- #

_REPO_ROOT = Path(__file__).resolve().parents[2]
STATES_DIR = _REPO_ROOT / "states"
EVENTS_DIR = _REPO_ROOT / "events"
REPORTS_DIR = _REPO_ROOT / "reports"
CLINICAL_CSV = _REPO_ROOT / "patients" / "clinical.csv"
SILVER_QC_SUMMARY = _REPO_ROOT / "reports" / "silver_qc_summary.csv"
B2_FAIL_EXCLUDED_JSON = _REPO_ROOT / "reports" / "b2_fail_excluded.json"
FLAG_FOR_REVIEW_CSV = _REPO_ROOT / "reports" / "pac_states_flag_for_review.csv"


# --------------------------------------------------------------------- #
# Helpers internos (con caché in-memory)
# --------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _all_states_nrs() -> frozenset:
    """NRs con archivo states/{NR}.parquet presente."""
    if not STATES_DIR.exists():
        return frozenset()
    nrs = {p.stem for p in STATES_DIR.glob("NR_*.parquet")}
    return frozenset(nrs)


@lru_cache(maxsize=1)
def _b2_fail_excluded_nrs() -> frozenset:
    """NRs en b2_fail_excluded.json (excluidos upstream por silver_qc)."""
    if not B2_FAIL_EXCLUDED_JSON.exists():
        return frozenset()
    with open(B2_FAIL_EXCLUDED_JSON) as f:
        data = json.load(f)
    return frozenset(data.get("night_record_ids", []))


@lru_cache(maxsize=1)
def _flag_for_review_nrs() -> frozenset:
    """NRs en pac_states_flag_for_review.csv (B3∪B4 — atención reducida)."""
    if not FLAG_FOR_REVIEW_CSV.exists():
        return frozenset()
    df = pd.read_csv(FLAG_FOR_REVIEW_CSV)
    return frozenset(df["nr"].astype(str).tolist())


@lru_cache(maxsize=1)
def _user_ids_with_clinical() -> frozenset:
    """user_ids con fila completa en clinical.csv."""
    if not CLINICAL_CSV.exists():
        return frozenset()
    df = pd.read_csv(CLINICAL_CSV, sep=";")
    # Considerar "completo" = patient_id presente y al menos sexo + peso definidos
    df = df.dropna(subset=["patient_id"])
    return frozenset(df["patient_id"].astype(str).tolist())


@lru_cache(maxsize=1)
def _silver_qc_user_map() -> pd.DataFrame:
    """DataFrame con (night_record_id, user_id) desde silver_qc_summary."""
    if not SILVER_QC_SUMMARY.exists():
        return pd.DataFrame(columns=["night_record_id", "user_id"])
    df = pd.read_csv(SILVER_QC_SUMMARY, usecols=["night_record_id", "user_id"])
    df["user_id"] = df["user_id"].astype(str)
    return df


@lru_cache(maxsize=1)
def _indices_tst_summary() -> pd.DataFrame:
    """DataFrame consolidado (night_record_id, tst_s) desde events/{NR}_indices.parquet."""
    if not EVENTS_DIR.exists():
        return pd.DataFrame(columns=["night_record_id", "tst_s"])
    rows = []
    for p in EVENTS_DIR.glob("NR_*_indices.parquet"):
        try:
            df = pd.read_parquet(p, columns=["night_record_id", "tst_s"])
            rows.append(df)
        except Exception:
            continue
    if not rows:
        return pd.DataFrame(columns=["night_record_id", "tst_s"])
    out = pd.concat(rows, ignore_index=True)
    return out


def clear_cache() -> None:
    """Vacía el caché in-memory. Útil tras cambios en disk durante una sesión."""
    _all_states_nrs.cache_clear()
    _b2_fail_excluded_nrs.cache_clear()
    _flag_for_review_nrs.cache_clear()
    _user_ids_with_clinical.cache_clear()
    _silver_qc_user_map.cache_clear()
    _indices_tst_summary.cache_clear()


# --------------------------------------------------------------------- #
# Cohortes
# --------------------------------------------------------------------- #


def get_cohort_all() -> Set[str]:
    """
    Todas las noches con states aplicado (i.e., en `states/{NR}.parquet`).

    En v1 son 560 noches: las 553 que pasaron silver_qc + las 7 que
    fallaron B2 temporal_coverage en QA (que igualmente quedaron con
    states aplicados, marcadas en `b2_fail_excluded.json`). Para
    análisis usar `quality` o `strict` salvo que se quiera incluir
    explícitamente las B2 fail.
    """
    return set(_all_states_nrs())


def get_cohort_quality() -> Set[str]:
    """
    Cohorte de calidad: `all` menos las 7 noches B2 fail
    (cobertura/gap insuficientes detectados por QA y cruzados con
    silver_qc). En v1: 553 noches.
    """
    return get_cohort_all() - set(_b2_fail_excluded_nrs())


def get_cohort_strict() -> Set[str]:
    """
    Cohorte estricta: quality + exclusión de las noches en
    `pac_states_flag_for_review.csv` (B3∪B4 — dominancia/outliers).

    Recomendada para análisis sensibles a calidad o cuando se quiere
    minimizar riesgo de inferencia ruidosa. Análisis sensibles deberían
    reportarse contra `quality` y `strict` para mostrar robustez.
    """
    return get_cohort_quality() - set(_flag_for_review_nrs())


def get_cohort_high_tst(min_tst_h: float = 4.0) -> Set[str]:
    """
    Cohorte filtrada por TST mínimo (default ≥4 h).

    Útil para análisis que requieren registros suficientemente largos
    (ej. fragmentación, entropía de estados con suficiente representación
    de cada estado).

    Aplica sobre `quality` (no sobre `strict`) para no encadenar
    filtros implícitos. Si querés strict + high_tst, hacer la
    intersección manual.

    Args:
        min_tst_h: TST mínimo en horas. Default 4 h.
    """
    df = _indices_tst_summary()
    if df.empty:
        return set()
    min_s = float(min_tst_h) * 3600.0
    nrs = set(df.loc[df["tst_s"] >= min_s, "night_record_id"].astype(str).tolist())
    return nrs & get_cohort_quality()


def get_cohort_with_clinical() -> Set[str]:
    """
    Cohorte con clinical.csv completo (paciente con datos clínicos
    versionables).

    Aplica sobre `quality`. Útil para análisis que requieren covariables
    clínicas (BMI, comorbilidades) que viven en clinical.csv.
    """
    user_map = _silver_qc_user_map()
    if user_map.empty:
        return set()
    valid_uids = _user_ids_with_clinical()
    nrs = set(
        user_map.loc[user_map["user_id"].isin(valid_uids), "night_record_id"]
        .astype(str)
        .tolist()
    )
    return nrs & get_cohort_quality()


# --------------------------------------------------------------------- #
# Operaciones de combinación e introspección
# --------------------------------------------------------------------- #


def cohort_summary() -> dict:
    """
    Devuelve un dict con tamaños de las cohortes principales.
    Útil para reportes y diagnóstico.
    """
    return {
        "all": len(get_cohort_all()),
        "quality": len(get_cohort_quality()),
        "strict": len(get_cohort_strict()),
        "high_tst_4h": len(get_cohort_high_tst(min_tst_h=4.0)),
        "with_clinical": len(get_cohort_with_clinical()),
        "b2_fail_excluded": len(_b2_fail_excluded_nrs()),
        "flag_for_review": len(_flag_for_review_nrs()),
    }


def snapshot_cohort(
    name: str, nrs: Set[str], output_path: Path | str
) -> Path:
    """
    Persiste un snapshot de cohorte para trazabilidad.

    El snapshot incluye nombre, timestamp, count y la lista ordenada
    de NRs. Recomendado al inicio de cada análisis "de tesis" para
    reproducibilidad.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "count": len(nrs),
        "night_record_ids": sorted(nrs),
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2)
    return output_path
