"""
Etapa 5 paso 7b — Build gold/nights_columns.json (diccionario de datos
de nights_gold).

Híbrido: clasificación AUTOMÁTICA por sufijo + descripciones HUMANAS
opcionales overrideables desde gold/nights_columns_descriptions.csv.

Para cada columna de gold/nights.parquet, registra:
  {
    "name": "ahi_3_pct_corpus",
    "kind": "cross_night_corpus",
    "dtype": "float",
    "description": "Percentile-rank de ahi_3 en el corpus quality (553 noches)."
  }

Categorías (kind):
  - "identity"           : night_record_id, user_id, model_version
  - "flag"               : in_quality, in_strict, in_high_tst,
                           flag_for_review, b2_fail
  - "single_night"       : calculable mirando UNA noche aislada — la app
                           podrá emitirlo. Incluye índices clásicos,
                           distribuciones de morfotipo y PAC state,
                           transición/entropía.
  - "cross_night_corpus" : *_pct_corpus — requiere conocer el corpus.
  - "cross_night_patient": delta_*_vs_baseline_patient — requiere otras
                           noches del mismo paciente.

Override de descripciones:
  Si existe gold/nights_columns_descriptions.csv con headers
  `column_name,description`, las descripciones manuales sobrescriben
  las auto-generadas. Útil para enriquecer con texto técnico/clínico
  sin tocar este script.

Uso:
  python scripts/build_nights_columns_doc.py            # genera/regenera
  python scripts/build_nights_columns_doc.py --dry-run  # imprime, no escribe
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = REPO_ROOT / "gold"
NIGHTS_GOLD = GOLD_DIR / "nights.parquet"
DESCRIPTIONS_OVERRIDE = GOLD_DIR / "nights_columns_descriptions.csv"
OUT_PATH = GOLD_DIR / "nights_columns.json"


# Cols fijas
IDENTITY_COLS = {"night_record_id", "user_id", "model_version"}
FLAG_COLS = {"in_quality", "in_strict", "in_high_tst", "flag_for_review", "b2_fail"}


# Descripciones default (auto) para las cols más comunes en _indices.parquet.
# Lo que no esté acá cae en placeholder genérico — el sidecar manual
# (CSV) puede sobrescribir cualquiera de estas.
DEFAULT_DESCRIPTIONS: Dict[str, str] = {
    # Identidad
    "night_record_id": "Identificador único de la noche (NR_ + hash).",
    "user_id": "Identificador pseudonimizado del paciente.",
    "model_version": "Versión del modelo aplicado (de models/MANIFEST.json).",
    # Flags
    "in_quality": "True si la noche pasó silver_qc y no está en b2_fail.",
    "in_strict": "True si in_quality y NO está en flag_for_review (B3∪B4).",
    "in_high_tst": "True si in_quality y tst_s ≥ 4 horas.",
    "flag_for_review": "True si está en pac_states_flag_for_review (B3 dominance ∪ B4 outliers).",
    "b2_fail": "True si está en b2_fail_excluded (silver_qc fail confirmado).",
    # Identidad/temporal de la noche
    "ts_start": "Timestamp de inicio del registro.",
    "ts_end": "Timestamp de fin del registro.",
    "duration_s": "Duración total del registro (segundos).",
    # Sleep architecture
    "tst_s": "Total Sleep Time (segundos).",
    "waso_s": "Wake After Sleep Onset (segundos).",
    "sleep_efficiency": "Eficiencia del sueño (TST / tiempo en cama).",
    "sleep_latency_s": "Latencia al sueño (segundos).",
    "n_stage_shifts": "Número de cambios de estadio del sueño.",
    # SpO2
    "mean_spo2": "Media de SpO₂ (%).",
    "median_spo2": "Mediana de SpO₂ (%).",
    "min_spo2": "Mínimo de SpO₂ (%).",
    "std_spo2": "Desvío estándar de SpO₂ (%).",
    "t90_frac": "Fracción de tiempo bajo SpO₂ 90%.",
    "t88_frac": "Fracción de tiempo bajo SpO₂ 88%.",
    "t85_frac": "Fracción de tiempo bajo SpO₂ 85%.",
    "ct90_min": "Tiempo total bajo SpO₂ 90% (minutos).",
    "ct88_min": "Tiempo total bajo SpO₂ 88% (minutos).",
    "ct85_min": "Tiempo total bajo SpO₂ 85% (minutos).",
    "hypoxic_burden_90": "Hypoxic burden bajo el umbral 90 (área bajo la curva).",
    "hypoxic_burden_88": "Hypoxic burden bajo el umbral 88.",
    # HR
    "mean_hr": "Media de HR (bpm).",
    "median_hr": "Mediana de HR (bpm).",
    "min_hr": "Mínimo de HR (bpm).",
    "max_hr": "Máximo de HR (bpm).",
    "std_hr": "Desvío estándar de HR (bpm).",
    "n_brady_episodes": "Número de episodios de bradicardia.",
    "n_tachy_episodes": "Número de episodios de taquicardia.",
    "mean_delta_hr_per_edo": "Δ HR promedio por EDO (bpm).",
    "p90_delta_hr_per_edo": "Δ HR p90 por EDO (bpm).",
    # Movement
    "mean_mov": "Media de la señal de movimiento.",
    "movement_index_per_h": "Índice de movimientos por hora.",
    # EDOs
    "n_edos_total": "Número total de EDOs detectados.",
    "mean_drop_pct": "Drop SpO₂ promedio por EDO (%).",
    "mean_duration_s_per_edo": "Duración promedio por EDO (segundos).",
    "max_duration_s_per_edo": "Duración máxima por EDO (segundos).",
    # IRD
    "ird_night": "Index of Respiratory Distress agregado de la noche.",
    "mean_ird_event": "IRD promedio por evento.",
    "p90_ird_event": "IRD p90 por evento.",
    # ODI/AHI por umbral (2/3/4/5)
    **{
        f"odi_{k}": f"Oxygen Desaturation Index con drop ≥{k}% (por hora de TST)."
        for k in [2, 3, 4, 5]
    },
    **{
        f"ahi_{k}": f"Apnea-Hypopnea Index con drop ≥{k}% (por hora de TST)."
        for k in [2, 3, 4, 5]
    },
    **{
        f"n_edos_{k}pct": f"Número de EDOs con drop ≥{k}%."
        for k in [2, 3, 4, 5]
    },
    # Comparación pac_v2 vs device
    # (estructura repetitiva: <metric>_pac_v2/_device/_diff_abs/_diff_rel/_diff_flag)
    # — descripciones generadas dinámicamente abajo.
    "algorithm_version": "Versión del algoritmo de events que generó el _indices original.",
    "events_schema_version": "Versión del schema de events que generó el _indices original.",
}


# Mapeos para descripciones dinámicas de cols comparativas device vs pac_v2
_COMPARISON_BASE = {
    "ahi_3": "AHI 3%",
    "ahi_4": "AHI 4%",
    "odi_3": "ODI 3%",
    "odi_4": "ODI 4%",
    "t90_frac": "T90 frac",
    "hypoxic_burden_3": "Hypoxic burden 3%",
    "hypoxic_burden_4": "Hypoxic burden 4%",
    "tst_s": "TST (s)",
    "sleep_efficiency": "Sleep efficiency",
    "waso_s": "WASO (s)",
}


def _generate_dynamic_default(col: str) -> Optional[str]:
    """Para cols comparativas device vs pac_v2."""
    for base, label in _COMPARISON_BASE.items():
        for suffix, descr in [
            ("_pac_v2", f"{label} computado por pac_v2."),
            ("_device", f"{label} reportado por el device."),
            ("_diff_abs", f"Diferencia absoluta {label} (pac_v2 − device)."),
            ("_diff_rel", f"Diferencia relativa {label} (pac_v2/device − 1)."),
            ("_diff_flag", f"Flag de divergencia significativa {label} (|diff_rel|>umbral)."),
        ]:
            if col == base + suffix:
                return descr
    return None


def _generate_morpho_state_default(col: str) -> Optional[str]:
    """Distribuciones de morfotipos y PAC states."""
    if col.startswith("frac_morpho_"):
        m = col.removeprefix("frac_morpho_")
        return f"Fracción de EDOs de morfotipo {m} (sobre el total de EDOs de la noche)."
    if col.startswith("frac_state_"):
        # frac_state_<scale>_<label>
        rest = col.removeprefix("frac_state_")
        scale, label = rest.split("_", 1)
        return f"Fracción de ventanas en PAC state {label} (escala {scale}, sobre el total de ventanas válidas)."
    if col.startswith("n_transitions_state_"):
        scale = col.removeprefix("n_transitions_state_")
        return f"Número de transiciones de state entre ventanas consecutivas (escala {scale})."
    if col.startswith("entropy_state_"):
        scale = col.removeprefix("entropy_state_")
        return f"Shannon entropy (en bits) de la distribución de PAC states (escala {scale})."
    return None


def _generate_cross_night_default(col: str, kind: str) -> Optional[str]:
    if kind == "cross_night_corpus" and col.endswith("_pct_corpus"):
        base = col.removesuffix("_pct_corpus")
        return f"Percentile-rank de {base} en el corpus quality (553 noches) — referencia poblacional."
    if (
        kind == "cross_night_patient"
        and col.startswith("delta_")
        and col.endswith("_vs_baseline_patient")
    ):
        base = col.removeprefix("delta_").removesuffix("_vs_baseline_patient")
        return (
            f"Δ {base} de esta noche vs baseline del paciente "
            f"(mean leave-one-out sobre sus otras noches quality, ≥3 noches)."
        )
    return None


def _classify(col: str) -> str:
    if col in IDENTITY_COLS:
        return "identity"
    if col in FLAG_COLS:
        return "flag"
    if col.endswith("_pct_corpus"):
        return "cross_night_corpus"
    if col.startswith("delta_") and col.endswith("_vs_baseline_patient"):
        return "cross_night_patient"
    return "single_night"


def _description(col: str, kind: str) -> str:
    # Prioridad: hardcoded > comparativa dinámica > distribución/transición/entropía
    # > cross-night dinámica > placeholder.
    if col in DEFAULT_DESCRIPTIONS:
        return DEFAULT_DESCRIPTIONS[col]
    d = _generate_dynamic_default(col)
    if d:
        return d
    d = _generate_morpho_state_default(col)
    if d:
        return d
    d = _generate_cross_night_default(col, kind)
    if d:
        return d
    return "(sin descripción — agregar a gold/nights_columns_descriptions.csv)"


def _load_overrides() -> Dict[str, str]:
    """Lee el CSV opcional de descripciones manuales."""
    if not DESCRIPTIONS_OVERRIDE.exists():
        return {}
    df = pd.read_csv(DESCRIPTIONS_OVERRIDE)
    if "column_name" not in df.columns or "description" not in df.columns:
        raise ValueError(
            f"{DESCRIPTIONS_OVERRIDE} debe tener cols column_name,description"
        )
    return dict(zip(df["column_name"], df["description"].fillna("")))


def _canonical_dtype(parquet_dtype: str) -> str:
    """Mapea pyarrow types a kinds simples."""
    s = str(parquet_dtype).lower()
    if "bool" in s:
        return "bool"
    if "int" in s:
        return "int"
    if "float" in s or "double" in s:
        return "float"
    if "timestamp" in s or "datetime" in s:
        return "ts"
    if "string" in s or "binary" in s:
        return "str"
    return s


def build_doc(verbose: bool = True) -> dict:
    if not NIGHTS_GOLD.exists():
        raise FileNotFoundError(
            f"Falta {NIGHTS_GOLD}. Correr build_nights_gold.py antes."
        )

    pq_meta = pq.read_metadata(NIGHTS_GOLD)
    schema = pq.read_schema(NIGHTS_GOLD)
    overrides = _load_overrides()
    if verbose and overrides:
        print(f"[nights_columns] {len(overrides)} overrides desde CSV manual.")

    columns: List[dict] = []
    summary = {
        "identity": 0,
        "flag": 0,
        "single_night": 0,
        "cross_night_corpus": 0,
        "cross_night_patient": 0,
    }

    for field in schema:
        name = field.name
        kind = _classify(name)
        summary[kind] = summary.get(kind, 0) + 1
        descr = overrides.get(name) or _description(name, kind)
        columns.append(
            {
                "name": name,
                "kind": kind,
                "dtype": _canonical_dtype(field.type),
                "description": descr,
            }
        )

    out = {
        "manifest_version": "1.0",
        "source": str(NIGHTS_GOLD.relative_to(REPO_ROOT)),
        "n_columns": len(columns),
        "summary_by_kind": summary,
        "kind_legend": {
            "identity": "Identificador o trazabilidad (siempre presente).",
            "flag": "Flag booleano de pertenencia a cohorte.",
            "single_night": (
                "Calculable mirando UNA noche aislada. La app la podrá "
                "emitir desde un xlsx ingestado sin necesidad del corpus."
            ),
            "cross_night_corpus": (
                "Requiere conocer el corpus para computarse "
                "(percentile-rank vs corpus quality)."
            ),
            "cross_night_patient": (
                "Requiere otras noches del mismo paciente (delta vs "
                "baseline leave-one-out, ≥3 noches quality)."
            ),
        },
        "override_file": str(DESCRIPTIONS_OVERRIDE.relative_to(REPO_ROOT)),
        "n_overrides_applied": len(set(overrides) & {c["name"] for c in columns}),
        "columns": columns,
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    doc = build_doc(verbose=True)

    if args.dry_run:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        print("\n--dry-run: NO escribo gold/nights_columns.json")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)

    print(f"OK — {OUT_PATH.relative_to(REPO_ROOT)} generado")
    print(f"  total cols: {doc['n_columns']}")
    for kind, n in doc["summary_by_kind"].items():
        print(f"    - {kind:25s}: {n}")
    if doc["n_overrides_applied"]:
        print(f"  overrides aplicados: {doc['n_overrides_applied']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
