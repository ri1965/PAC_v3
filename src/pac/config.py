"""
PAC_v2 — configuración global (constantes planas, módulo).

Centraliza paths, nombres de columnas canónicas, parámetros de parseo.
Nada de lógica aquí: sólo constantes.
"""
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths base
# ---------------------------------------------------------------------------
# Raíz del proyecto = dos niveles arriba de este archivo (src/pac/config.py)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

RAW_DIR:     Path = PROJECT_ROOT / "raw"
BRONZE_DIR:  Path = PROJECT_ROOT / "bronze"
SILVER_DIR:  Path = PROJECT_ROOT / "silver"
EVENTS_DIR:  Path = PROJECT_ROOT / "events"
GOLD_DIR:    Path = PROJECT_ROOT / "gold"
PATIENTS_DIR: Path = PROJECT_ROOT / "patients"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"
MODELS_DIR:  Path = PROJECT_ROOT / "models"

# ---------------------------------------------------------------------------
# Archivos de identidad (2-file model)
# ---------------------------------------------------------------------------
# Nota: el mapping source_exam_id -> patient_id está IMPLÍCITO en el xlsx
# (bloque 1 trae user_id) y se persiste en la metadata KV de cada parquet.
# No se necesita archivo de identidad adicional.
PATIENT_REGISTRY_CSV: Path = PATIENTS_DIR / "patient_registry.csv"
CLINICAL_CSV:         Path = PATIENTS_DIR / "clinical.csv"

# Separador único para los archivos de identidad.
CSV_SEP: str = ";"

# Columnas canónicas (contrato).
REGISTRY_COLS = ["patient_id", "nombre", "apellido", "fecha_nacimiento"]

CLINICAL_COLS = [
    "patient_id",
    "sexo",
    "peso_kg",
    "talla_cm",
    "apnea_prev",
    "diabetes",
    "hta",
    "marcapasos",
]

# ---------------------------------------------------------------------------
# Señales canónicas (bronze) — sólo estas se conservan de los .xlsx
# ---------------------------------------------------------------------------
# sleep_stage se agrega en Etapa 1 como 5ta columna canónica (decisión PAC_v2).
# Su uso efectivo queda abierto hasta Etapa 3/4; en Bronze sólo se persiste.
SIGNAL_COLS = ["timestamp", "spo2", "hr", "mov", "sleep_stage"]

# ---------------------------------------------------------------------------
# Columnas del xlsx de origen (mapeo canónico)
# ---------------------------------------------------------------------------
# Bloque 3 del xlsx (desde la fila 7): una fila por segundo.
# Se conservan sólo 5 columnas → renombradas a SIGNAL_COLS.
XLSX_SIGNAL_MAP = {
    # xlsx column       ->  columna canónica
    "time":                 "_time_str",            # se parsea por separado → timestamp
    "spo2":                 "spo2",
    "bpm":                  "hr",
    "acceleration_module":  "mov",
    "sleep_stage":          "sleep_stage",
}

# Frecuencia de muestreo nominal (Hz). Los xlsx son 1 Hz fijo.
SAMPLING_HZ_NOMINAL: int = 1

# ---------------------------------------------------------------------------
# Parseo de fechas
# ---------------------------------------------------------------------------
# Regla: año 2 dígitos yy ≤ YEAR_PIVOT → 20yy, si no → 19yy
YEAR_PIVOT: int = 25

# ---------------------------------------------------------------------------
# NightRecordID
# ---------------------------------------------------------------------------
NIGHT_ID_PREFIX: str = "NR_"
NIGHT_ID_HASH_LEN: int = 10
# El salt NO se commitea; se lee de entorno en etapas posteriores.
NIGHT_ID_SALT_ENV_VAR: str = "PAC_NIGHT_ID_SALT"

# ---------------------------------------------------------------------------
# Etapa 2 — Silver QC (umbrales fijos, cerrados con Roberto Q1–Q8)
# ---------------------------------------------------------------------------
# SpO2: valores < 55 % se marcan inválidos (incluye 0 = sensor desconectado).
#   Decisión Q1, opción 1c: rango simple + flag + clean col.
SPO2_MIN_VALID: int = 55

# HR: rango fisiológico ampliado. Inválidos incluyen 0 y outliers groseros.
#   Decisión Q2, opción 2b: rango fijo; coherencia multi-señal difiere a Etapa 3.
HR_MIN_VALID: int = 30
HR_MAX_VALID: int = 200

# Cobertura temporal (gaps).
#   Decisión Q3, opción 3c: coverage ratio + max_contiguous_gap en vez de n_gaps.
QC_COVERAGE_MIN: float = 0.90
QC_MAX_GAP_S:   int   = 1800  # 30 min

# Duración de la noche (dual flag: aborted < 1h ⊂ short < 3h).
#   Decisión Q4, opción 4a.
QC_DURATION_ABORTED_S: int = 3600    # < 1 h → aborted
QC_DURATION_MIN_S:     int = 10800   # < 3 h → short (PSG estándar mínimo)

# Versión del schema silver (KV metadata de cada parquet).
SILVER_SCHEMA_VERSION: str = "1"

# ---------------------------------------------------------------------------
# Etapa 3 — Events (EDOs + IRD + índices nocturnos)
# Decisiones cerradas con Roberto (R1–R5 + Q1–Q15). Ver PAC_v2_ETAPAS.md.
# ---------------------------------------------------------------------------

# --- Detección de EDOs (Evento de Desaturación de Oxígeno) ---------------
# Baseline móvil: mediana de los N s previos al inicio del drop.
#   Decisión R3, AASM 2012 Rule 10.
EDO_BASELINE_WINDOW_S: int = 120

# Recuperación: el EDO termina cuando SpO2 ≥ EDO_RECOVERY_PCT × baseline.
#   Decisión R1.
EDO_RECOVERY_PCT: float = 0.90

# Duración mínima para considerar un EDO candidato.
#   Decisión R2 + Q9: detección permisiva; la separación "real vs ruido"
#   se hace por clustering en Etapa 4.
EDO_MIN_DURATION_S: int = 10

# Umbrales de drop % evaluados para cada EDO (vs baseline previo).
#   Decisión Q2: cada EDO lleva 4 booleanos meets_Npct; ODI nocturno se
#   calcula para los 4 umbrales.
EDO_DROP_THRESHOLDS_PCT = [2, 3, 4, 5]

# Resampleo de la curva morfológica del EDO (sidecar {NR}_edo_curves).
#   Decisión Q15c: N puntos fijos para clustering morfológico en Etapa 4.
EDO_RESAMPLE_N_POINTS: int = 30

# --- IRD (Índice de Respuesta a la Desaturación) ------------------------
# Pesos fijos iniciales; la función acepta pesos como parámetro para que
# la recalibración futura (RN u otra) no requiera re-detectar EDOs.
#   Decisión R4 + Q13a.
IRD_WEIGHTS = {"spo2": 0.5, "hr": 0.3, "mov": 0.2}

# Normalización de las 3 componentes del IRD: relativa al baseline propio
# de cada señal dentro del evento (Q14c).
#   ird_spo2_comp = drop_pct     / baseline_spo2
#   ird_hr_comp   = delta_hr_bpm / baseline_hr_bpm
#   ird_mov_comp  = peak_mov     / baseline_mov
# (constante documental; la lógica vive en pac.events)

# --- Flags de calidad sobre eventos ------------------------------------
# Un EDO se marca near_gap si está a <NEAR_GAP_WINDOW_S del borde de
# cualquier gap ≥30 s de la señal original.
#   Decisión Q4 4c: las 560 noches se procesan; el filtering final por
#   noches con fallo de QC se pospone a Gold.
NEAR_GAP_WINDOW_S: int = 300  # 5 min

# --- Umbrales fisiológicos para índices nocturnos derivados ------------
# T<N y CT<N: % de tiempo y tiempo cumulativo bajo cada umbral de SpO2.
T_UNDER_THRESHOLDS_PCT = [90, 88, 85]

# Brady/tachycardia: episodios sostenidos ≥ N segundos.
HR_BRADY_THRESHOLD_BPM: int = 50
HR_TACHY_THRESHOLD_BPM: int = 100
HR_EXTREME_MIN_DURATION_S: int = 10

# --- Validación contra sidecar classical del dispositivo --------------
# diff_flag = True cuando |pac_v2 - device| / device > este threshold.
#   Decisión Q6: divergencia >20% sobre los mismos datos físicos = flag.
DIFF_REL_FLAG_THRESHOLD: float = 0.20

# Índices con gemelo en sidecar classical. Para cada uno se persiste el
# quinteto {metric}_pac_v2 / _device / _diff_abs / _diff_rel / _diff_flag.
VALIDATED_INDICES = [
    "odi_3", "odi_4",
    "ahi_3", "ahi_4",
    "t90_frac",
    "hypoxic_burden_3", "hypoxic_burden_4",
    "tst_s",
    "sleep_efficiency",
    "waso_s",
]

# --- Versionado ---------------------------------------------------------
EVENTS_SCHEMA_VERSION: str = "1"
ALGORITHM_VERSION_PAC_V2: str = "pac_v2_events_1.0.0"

# ---------------------------------------------------------------------------
# Etapa 3b — EDO Morphotyping (clustering no-supervisado de EDOs)
# Decisiones cerradas con Roberto (Q1=B, Q2=B, Q3=B, Q4=A). Ver PAC_v2_ETAPAS.md.
# ---------------------------------------------------------------------------

# 10 features escalares por EDO: 6 morfología + 4 IRD (Q1=B).
#   Los nombres coinciden con columnas de events/{NR}_edos.parquet.
MORPHOTYPE_FEATURES = [
    # Morfología (6)
    "duration_s",
    "drop_pct",
    "nadir_spo2",
    "slope_desat_pct_s",
    "slope_recov_pct_s",
    "auc_spo2_pct_s",
    # IRD + componentes (4)
    "ird_event",
    "ird_spo2_comp",
    "ird_hr_comp",
    "ird_mov_comp",
]

# Máscara del universo de training (EDOs "canónicos"):
#   in_sleep=True & near_gap=False & meets_3pct=True (Q3=B).
# Los EDOs marginales (meets_2pct only) se labelan con el modelo entrenado
# sobre los canónicos, pero no participan del fit.
MORPHOTYPE_TRAINING_MASK = {
    "in_sleep":    True,
    "near_gap":    False,
    "meets_3pct":  True,
}

# Sweep K para selección del número de clusters (Q2=B).
#   Criterios: inertia (elbow), silhouette, Davies-Bouldin.
MORPHOTYPE_K_RANGE = list(range(2, 11))  # 2, 3, ..., 10
MORPHOTYPE_RANDOM_STATE: int = 42

# Nomenclatura: letras griegas minúsculas para cluster labels (Q4=A).
MORPHOTYPE_GREEK_LETTERS = [
    "α", "β", "γ", "δ", "ε", "ζ", "η", "θ", "ι", "κ",
]

# Versionado del subpipeline.
MORPHOTYPES_SCHEMA_VERSION: str = "1"
ALGORITHM_VERSION_MORPHOTYPES: str = "pac_v2_morphotypes_1.0.0"

# ---------------------------------------------------------------------------
# Etapa 4 — Windows multiescala + estados PAC
# Decisiones cerradas con Roberto (Q1=A, Q2=A, Q3=C, Q4=A, Q5=C, Q6=C).
# Ver PAC_v2_ETAPAS.md sección "Etapa 4".
# ---------------------------------------------------------------------------

# Directorio de outputs de Etapa 4 (un parquet por noche).
STATES_DIR: Path = PROJECT_ROOT / "states"

# --- Escalas temporales (Q1=A) ----------------------------------------------
# 3 escalas canónicas del PAC histórico: short / medium / long.
PAC_STATE_SCALES = ("s", "m", "l")

PAC_WINDOW_DURATIONS_S = {
    "s": 30,     # short:  30 s
    "m": 300,    # medium:  5 min
    "l": 1800,   # long:   30 min
}

# Q2=A: ventanas disjuntas (sin overlap). Step == window duration.
PAC_WINDOW_OVERLAP: float = 0.0

# --- Features por ventana (Q3=C) --------------------------------------------
# Stats sobre señales (6 stats × 2 señales + 3 para mov = 15).
# Los stats se calculan sobre las cols *_clean (ignorando samples inválidos).
PAC_SIGNAL_STATS_SPO2 = ("mean", "std", "min", "max", "p10", "p90")
PAC_SIGNAL_STATS_HR   = ("mean", "std", "min", "max", "p10", "p90")
PAC_SIGNAL_STATS_MOV  = ("mean", "std", "max")

# Densidades de morfotipos (6): n_edos por letra griega + IRD local.
# n_α / n_β / n_γ / n_δ cuentan EDOs cuyo t_start cae dentro de la ventana.
PAC_MORPHOTYPE_DENSITY_FEATURES = (
    "n_edos_total",
    "n_alpha",      # morphotype == α
    "n_beta",       # morphotype == β
    "n_gamma",      # morphotype == γ
    "n_delta",      # morphotype == δ
    "ird_mean_local",  # mean de ird_event sobre los EDOs de la ventana (0 si none)
)

# Composición de sleep_stage por ventana (3 fracciones que suman ≤1).
#
# El aparato emite sleep_stage ∈ {0, 1, 2, 3} inferido internamente desde
# HR + movimiento (no PSG). La validación de plausibilidad fisiológica
# (reports/sleep_staging_validation.{md,html,json}, 560 noches, 5 checks)
# mostró que las 4 categorías crudas NO son confiables a nivel intra-sueño:
#   ✗ ciclos REM-NREM: mediana 10/noche (esperado 4-6), 28.5 min c/u
#   ✗ stage 3 no decrece Q1→Q5 y ocupa 33% del sueño (literatura 13-23%)
#   ✗ morfotipos no discriminan por stage
#   ✓ discrimina bien wake vs sleep
#   ✓ discrimina bien severidad apneica (tercil ODI)
#
# DECISIÓN (Roberto, post-análisis): Mapeo B — colapsar a 3 categorías:
#   raw 0                → wake
#   raw 1, raw 2         → light_sleep
#   raw 3                → deep_sleep  (nombre convencional, NO N3 clínico)
#
# CAVEAT: "deep_sleep" es el label del stage 3 del aparato. NO es N3 AASM.
# Se conserva como feature porque tiene valor discriminativo empírico en
# modelos no-supervisados (clustering PAC), NO debe leerse clínicamente.
# Si a futuro se cambia el mapeo o aparecen más stages, editar este dict
# y re-entrenar toda la pipeline aguas abajo (ver PAC_v2_ETAPAS.md).
PAC_SLEEP_STAGE_RAW = {
    0: "wake",
    1: "stage_1_raw",   # device-labeled (posible REM o N1, sin validar)
    2: "stage_2_raw",   # device-labeled (posible N2/Light)
    3: "stage_3_raw",   # device-labeled (no N3 clínico; ver caveat)
}

# Mapeo raw → categoría colapsada. Este es el ÚNICO lugar donde se decide
# cómo se reduce la granularidad del aparato a features de composición.
PAC_SLEEP_STAGE_COLLAPSE_MAP = {
    0: "wake",
    1: "light_sleep",
    2: "light_sleep",
    3: "deep_sleep",
}

# Categorías finales (orden canónico para el feature vector).
PAC_SLEEP_CATEGORIES = ("wake", "light_sleep", "deep_sleep")

PAC_SLEEP_COMPOSITION_FEATURES = (
    "frac_wake",
    "frac_light_sleep",
    "frac_deep_sleep",
)

# Lista completa de features por ventana (26 total).
# El orden es determinístico y canónico — todos los stats y densidades
# aparecen siempre en este orden en el feature vector.
def _pac_feature_names() -> list[str]:
    names: list[str] = []
    for stat in PAC_SIGNAL_STATS_SPO2:
        names.append(f"spo2_{stat}")
    for stat in PAC_SIGNAL_STATS_HR:
        names.append(f"hr_{stat}")
    for stat in PAC_SIGNAL_STATS_MOV:
        names.append(f"mov_{stat}")
    names.extend(PAC_MORPHOTYPE_DENSITY_FEATURES)
    names.extend(PAC_SLEEP_COMPOSITION_FEATURES)
    return names

PAC_WINDOW_FEATURES = tuple(_pac_feature_names())  # 24 features (15 + 6 + 3)

# --- Training (Q4=A, Q6=C) --------------------------------------------------
# Q4=A: KMeans unificado sobre el pool de las 560 noches (no per-patient).
# Q6=C (hybrid): training mask filtra ventanas donde frac_wake < threshold
#                (~in_sleep dominante). Inferencia se aplica a todas las
#                ventanas (incluidas las dominadas por wake).
PAC_STATES_TRAINING_MASK = {
    "frac_wake_max": 0.5,   # ventana entra a training si <50% wake
    "coverage_min":  0.5,   # y tiene ≥50% de samples válidos (spo2_clean no-NaN)
}

# --- Sweep K por escala (Q5=C) ----------------------------------------------
# Ancla histórica del PAC viejo. El sweep se corre 2..10 y en el dashboard
# se marca dónde cae el K histórico para decisión humana informada.
PAC_STATES_K_RANGE = list(range(2, 11))    # 2..10 por escala
PAC_STATES_HISTORICAL_K = {
    "s": 7,   # S0..S6
    "m": 5,   # M0..M4 (K=6 generaba cluster degenerado M4 <0.3% con esta cohorte)
    "l": 4,   # L0..L3
}

PAC_STATES_RANDOM_STATE: int = 42

# Nomenclatura: estados se nombran "S{i}", "M{i}", "L{i}" (scale prefix + int).
# A diferencia de morfotipos, acá la escala actúa como disambiguador y no
# usamos letras griegas (serían ambiguas entre las 3 escalas).
PAC_STATE_PREFIXES = {"s": "S", "m": "M", "l": "L"}

# --- Versionado -------------------------------------------------------------
PAC_STATES_SCHEMA_VERSION: str = "1"
ALGORITHM_VERSION_PAC_STATES: str = "pac_v2_states_1.0.0"

# ---------------------------------------------------------------------------
# Helpers mínimos de directorios
# ---------------------------------------------------------------------------
def ensure_dirs() -> None:
    """Crea todos los directorios del scaffold si no existen."""
    for d in (
        RAW_DIR, BRONZE_DIR, SILVER_DIR, EVENTS_DIR, GOLD_DIR,
        PATIENTS_DIR, REPORTS_DIR, MODELS_DIR, STATES_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def as_dict() -> dict:
    """Dump de configuración (útil para logs / gates)."""
    return {
        "project_root": str(PROJECT_ROOT),
        "raw_dir": str(RAW_DIR),
        "bronze_dir": str(BRONZE_DIR),
        "silver_dir": str(SILVER_DIR),
        "events_dir": str(EVENTS_DIR),
        "gold_dir": str(GOLD_DIR),
        "states_dir": str(STATES_DIR),
        "models_dir": str(MODELS_DIR),
        "patients_dir": str(PATIENTS_DIR),
        "reports_dir": str(REPORTS_DIR),
        "csv_sep": CSV_SEP,
        "signal_cols": SIGNAL_COLS,
        "year_pivot": YEAR_PIVOT,
        "pac_scales": PAC_STATE_SCALES,
        "pac_window_durations_s": PAC_WINDOW_DURATIONS_S,
        "pac_window_features": list(PAC_WINDOW_FEATURES),
        "pac_states_historical_k": PAC_STATES_HISTORICAL_K,
        "pac_sleep_stage_collapse_map": PAC_SLEEP_STAGE_COLLAPSE_MAP,
        "pac_sleep_categories": list(PAC_SLEEP_CATEGORIES),
    }
