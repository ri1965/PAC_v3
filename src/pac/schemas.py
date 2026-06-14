"""
PAC_v2 — Validación de schemas en bordes (Etapa 4.6)

Validadores explícitos para cada capa del medallion: bronze, silver,
events (edos + curves), states. Diseñados para correr al cruzar
bordes entre capas y cortar en seco con un mensaje claro si llega un
DataFrame con esquema inesperado.

Uso típico (strict, raise on error):

    from pac.schemas import validate_silver, SchemaError
    df = pd.read_parquet('silver/NR_xxx.parquet')
    validate_silver(df, source='silver/NR_xxx.parquet')

Uso permisivo (solo warning):

    validate_silver(df, source='...', strict=False)

Política de extras: columnas extra son WARNING, no error (los modelos
pueden agregar columnas derivadas sin invalidar la capa). Columnas
faltantes son siempre error. Dtypes incompatibles son error en strict.

Tolerancia de dtypes: int8/int16/int32/int64 se consideran equivalentes
a "int"; float32/float64 a "float"; ts con cualquier resolución a "ts".
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Dict, List, Set

import numpy as np
import pandas as pd


# --------------------------------------------------------------------- #
# Excepción dedicada
# --------------------------------------------------------------------- #


class SchemaError(ValueError):
    """Schema mismatch detectado en una capa del pipeline."""

    pass


# --------------------------------------------------------------------- #
# Tipos canónicos abreviados (tolerantes a sub-tipos)
# --------------------------------------------------------------------- #
# - "int": cualquier int (Int8..Int64, int8..int64)
# - "float": cualquier float (float32, float64)
# - "bool": booleano
# - "str": object o string (pandas no estandariza esto, ambos OK)
# - "ts": datetime64 con cualquier unidad
# - "list": object con elementos lista (no se inspecciona profundidad)


def _canonical_kind(series: pd.Series) -> str:
    """Devuelve el kind canónico de una Series."""
    dtype = series.dtype
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return "ts"
    if pd.api.types.is_string_dtype(dtype) or dtype == object:
        # object puede ser str o list; chequear primer no-null
        non_null = series.dropna()
        if len(non_null) == 0:
            return "str"
        first = non_null.iloc[0]
        if isinstance(first, (list, tuple, np.ndarray)):
            return "list"
        return "str"
    return str(dtype)


# --------------------------------------------------------------------- #
# Definiciones de schema por capa
# --------------------------------------------------------------------- #

BRONZE_SCHEMA: Dict[str, str] = {
    "timestamp": "ts",
    "spo2": "int",
    "hr": "int",
    "mov": "int",
    "sleep_stage": "int",
}

SILVER_SCHEMA: Dict[str, str] = {
    "timestamp": "ts",
    "spo2": "int",
    "spo2_invalid": "bool",
    "spo2_clean": "float",
    "hr": "int",
    "hr_invalid": "bool",
    "hr_clean": "float",
    "mov": "int",
    "sleep_stage": "int",
}

EVENTS_EDOS_SCHEMA: Dict[str, str] = {
    "night_record_id": "str",
    "ts_start": "ts",
    "ts_end": "ts",
    "duration_s": "float",
    "baseline_spo2": "float",
    "nadir_spo2": "float",
    "drop_pct": "float",
    "slope_desat_pct_s": "float",
    "slope_recov_pct_s": "float",
    "auc_spo2_pct_s": "float",
    "delta_hr_bpm": "float",
    "baseline_hr_bpm": "float",
    "peak_mov": "float",
    "baseline_mov": "float",
    "ird_spo2_comp": "float",
    "ird_hr_comp": "float",
    "ird_mov_comp": "float",
    "ird_event": "float",
    "near_gap": "bool",
    "in_sleep": "bool",
    "meets_2pct": "bool",
    "meets_3pct": "bool",
    "meets_4pct": "bool",
    "meets_5pct": "bool",
    "morphotype": "str",
    "morphotype_curve": "str",   # shape-based k=5: C1=subcrítico → C5=severo progresivo
}

EVENTS_CURVES_SCHEMA: Dict[str, str] = {
    "night_record_id": "str",
    "ts_start": "ts",
    "spo2_curve": "list",
    "hr_curve": "list",
    "mov_curve": "list",
}

STATES_SCHEMA: Dict[str, str] = {
    "night_record_id": "str",
    "scale": "str",
    "window_idx": "int",
    "t_start": "ts",
    "t_end": "ts",
    "t_start_s": "float",
    "t_end_s": "float",
    "state_label": "str",
    "cluster_int": "int",
    "dist_to_centroid": "float",
    "coverage": "float",
    "frac_wake": "float",
    "frac_light_sleep": "float",
    "frac_deep_sleep": "float",
    "training_eligible": "bool",
}


# --------------------------------------------------------------------- #
# Schemas Gold (Etapa 5)
# --------------------------------------------------------------------- #
# Convención: las tablas Gold extienden las tablas events/states con
# tres bloques transversales:
#   1. Identidad de paciente (user_id) para join con patients_gold/clinical
#   2. Flags de cohorte (in_quality, in_strict, in_high_tst,
#      flag_for_review, b2_fail) — cohorte B: todas las noches con flags
#   3. Trazabilidad de modelo (model_version) — leído del MANIFEST.json
#
# events_curves_gold NO tiene esos bloques (siempre se usa joineado a
# events_gold por (night_record_id, ts_start) — duplicar es ruido).
# states_gold sí los tiene porque puede usarse independiente.

# Bloques reutilizables (DRY)
_COHORT_FLAGS: Dict[str, str] = {
    "in_quality": "bool",
    "in_strict": "bool",
    "in_high_tst": "bool",
    "flag_for_review": "bool",
    "b2_fail": "bool",
}

_TRACE_BLOCK: Dict[str, str] = {
    "user_id": "str",
    "model_version": "str",
}


GOLD_EVENTS_SCHEMA: Dict[str, str] = {
    **EVENTS_EDOS_SCHEMA,
    **_TRACE_BLOCK,
    **_COHORT_FLAGS,
}


GOLD_EVENTS_CURVES_SCHEMA: Dict[str, str] = {
    **EVENTS_CURVES_SCHEMA,
}


GOLD_STATES_SCHEMA: Dict[str, str] = {
    **STATES_SCHEMA,
    **_TRACE_BLOCK,
    **_COHORT_FLAGS,
}


# nights_gold y patients_gold: skeletons mínimos en paso 1.
# Se completan en pasos 5 y 6 con todas las cols (índices clásicos,
# distribuciones de morfotipo y PAC state, cross-night marcadas con
# sufijo _pct_corpus / _vs_baseline_patient, etc.).
GOLD_NIGHTS_SCHEMA: Dict[str, str] = {
    "night_record_id": "str",
    **_TRACE_BLOCK,
    **_COHORT_FLAGS,
    # ... el resto se agrega en paso 5 (build_nights_gold.py)
}


GOLD_PATIENTS_SCHEMA: Dict[str, str] = {
    "user_id": "str",
    "model_version": "str",
    "n_nights_total": "int",
    # ... el resto se agrega en paso 6 (build_patients_gold.py)
}


# --------------------------------------------------------------------- #
# Núcleo del validador
# --------------------------------------------------------------------- #


@dataclass
class ValidationResult:
    """Resultado de una validación de schema."""

    ok: bool
    layer: str
    source: str
    missing: List[str]
    wrong_dtype: List[tuple]  # (col, expected, got)
    extras: List[str]
    n_rows: int

    def __str__(self) -> str:
        msg = f"[schema:{self.layer}] {self.source} — n_rows={self.n_rows}"
        if self.missing:
            msg += f"\n  MISSING ({len(self.missing)}): {self.missing}"
        if self.wrong_dtype:
            msg += "\n  WRONG_DTYPE:"
            for col, exp, got in self.wrong_dtype:
                msg += f"\n    - {col}: expected={exp}, got={got}"
        if self.extras:
            msg += f"\n  EXTRAS ({len(self.extras)}): {self.extras}"
        return msg


def _validate(
    df: pd.DataFrame,
    schema: Dict[str, str],
    layer: str,
    source: str = "<unknown>",
    strict: bool = True,
    allow_extras: bool = True,
) -> ValidationResult:
    """Núcleo del validador. Devuelve ValidationResult; raise si strict y !ok."""
    missing: List[str] = []
    wrong_dtype: List[tuple] = []

    df_cols: Set[str] = set(df.columns)
    schema_cols: Set[str] = set(schema.keys())

    for col, expected_kind in schema.items():
        if col not in df_cols:
            missing.append(col)
            continue
        got_kind = _canonical_kind(df[col])
        if got_kind != expected_kind:
            wrong_dtype.append((col, expected_kind, got_kind))

    extras = sorted(df_cols - schema_cols)

    ok = (len(missing) == 0) and (len(wrong_dtype) == 0)

    result = ValidationResult(
        ok=ok,
        layer=layer,
        source=source,
        missing=missing,
        wrong_dtype=wrong_dtype,
        extras=extras,
        n_rows=len(df),
    )

    if extras and not allow_extras:
        ok = False
        result.ok = False

    if not ok:
        if strict:
            raise SchemaError(str(result))
        else:
            warnings.warn(str(result), UserWarning, stacklevel=2)

    return result


# --------------------------------------------------------------------- #
# Validadores públicos por capa
# --------------------------------------------------------------------- #


def validate_bronze(
    df: pd.DataFrame, source: str = "<bronze>", strict: bool = True
) -> ValidationResult:
    """Valida schema de bronze (señales raw canonizadas)."""
    return _validate(df, BRONZE_SCHEMA, layer="bronze", source=source, strict=strict)


def validate_silver(
    df: pd.DataFrame, source: str = "<silver>", strict: bool = True
) -> ValidationResult:
    """Valida schema de silver (señales con clean + invalid flags)."""
    return _validate(df, SILVER_SCHEMA, layer="silver", source=source, strict=strict)


def validate_events_edos(
    df: pd.DataFrame, source: str = "<events_edos>", strict: bool = True
) -> ValidationResult:
    """Valida schema de events EDOs (1 fila por EDO con morfología + IRD + morphotype)."""
    return _validate(
        df, EVENTS_EDOS_SCHEMA, layer="events_edos", source=source, strict=strict
    )


def validate_events_curves(
    df: pd.DataFrame, source: str = "<events_curves>", strict: bool = True
) -> ValidationResult:
    """Valida schema de events curves (curvas resampleadas por EDO)."""
    return _validate(
        df, EVENTS_CURVES_SCHEMA, layer="events_curves", source=source, strict=strict
    )


def validate_states(
    df: pd.DataFrame, source: str = "<states>", strict: bool = True
) -> ValidationResult:
    """Valida schema de states (PAC States multi-escala s/m/l)."""
    return _validate(df, STATES_SCHEMA, layer="states", source=source, strict=strict)


# --------------------------------------------------------------------- #
# Validadores Gold (Etapa 5)
# --------------------------------------------------------------------- #


def validate_events_gold(
    df: pd.DataFrame, source: str = "<events_gold>", strict: bool = True
) -> ValidationResult:
    """Valida schema de events_gold (events + user_id + flags + model_version)."""
    return _validate(
        df, GOLD_EVENTS_SCHEMA, layer="events_gold", source=source, strict=strict
    )


def validate_events_curves_gold(
    df: pd.DataFrame, source: str = "<events_curves_gold>", strict: bool = True
) -> ValidationResult:
    """Valida schema de events_curves_gold (igual que events_curves: 5 cols list-typed)."""
    return _validate(
        df,
        GOLD_EVENTS_CURVES_SCHEMA,
        layer="events_curves_gold",
        source=source,
        strict=strict,
    )


def validate_states_gold(
    df: pd.DataFrame, source: str = "<states_gold>", strict: bool = True
) -> ValidationResult:
    """Valida schema de states_gold (states + user_id + flags + model_version)."""
    return _validate(
        df, GOLD_STATES_SCHEMA, layer="states_gold", source=source, strict=strict
    )


def validate_nights_gold(
    df: pd.DataFrame, source: str = "<nights_gold>", strict: bool = True
) -> ValidationResult:
    """Valida schema de nights_gold. NOTA: en paso 1 valida solo el skeleton
    mínimo; el schema completo (~150 cols) se materializa en paso 5."""
    return _validate(
        df,
        GOLD_NIGHTS_SCHEMA,
        layer="nights_gold",
        source=source,
        strict=strict,
        allow_extras=True,  # explícito: el skeleton sólo exige las cols base
    )


def validate_patients_gold(
    df: pd.DataFrame, source: str = "<patients_gold>", strict: bool = True
) -> ValidationResult:
    """Valida schema de patients_gold. NOTA: en paso 1 valida solo el skeleton
    mínimo; el schema completo se materializa en paso 6."""
    return _validate(
        df,
        GOLD_PATIENTS_SCHEMA,
        layer="patients_gold",
        source=source,
        strict=strict,
        allow_extras=True,
    )


# --------------------------------------------------------------------- #
# Helpers para uso externo (app, retrain check)
# --------------------------------------------------------------------- #


def list_layers() -> List[str]:
    """Lista los layers conocidos por el validador."""
    return [
        "bronze",
        "silver",
        "events_edos",
        "events_curves",
        "states",
        "events_gold",
        "events_curves_gold",
        "states_gold",
        "nights_gold",
        "patients_gold",
    ]


def get_schema(layer: str) -> Dict[str, str]:
    """Devuelve la definición de schema canónica para un layer."""
    schemas = {
        "bronze": BRONZE_SCHEMA,
        "silver": SILVER_SCHEMA,
        "events_edos": EVENTS_EDOS_SCHEMA,
        "events_curves": EVENTS_CURVES_SCHEMA,
        "states": STATES_SCHEMA,
        "events_gold": GOLD_EVENTS_SCHEMA,
        "events_curves_gold": GOLD_EVENTS_CURVES_SCHEMA,
        "states_gold": GOLD_STATES_SCHEMA,
        "nights_gold": GOLD_NIGHTS_SCHEMA,
        "patients_gold": GOLD_PATIENTS_SCHEMA,
    }
    if layer not in schemas:
        raise KeyError(f"Layer desconocido: {layer}. Conocidos: {list(schemas.keys())}")
    return dict(schemas[layer])
