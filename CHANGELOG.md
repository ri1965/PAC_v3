# Changelog — PAC_v2

Resumen one-liner por etapa cerrada. Para detalle técnico de cada
etapa, ver `PAC_v2_ETAPAS.md`.

## v1.2 — 2026-05-17

Capa de análisis sobre Gold: features derivadas de los notebooks.

- **`gold/events_analysis.parquet`**: nueva tabla generada por NB01.
  Contiene columnas clave de identidad de `events.parquet` más features
  analíticas que requieren juicio interpretativo y no pertenecen al
  pipeline determinístico.
- **`morphotype_severity`**: feature derivada binaria (`low`/`high`)
  basada en la agrupación de clusters data-driven. `low` = C1+C2
  (~89% eventos, desaturación mínima); `high` = C3+C4+C5 (~11%,
  desaturación significativa). Ver `PAC_v2_ETAPAS.md` → "Capa de
  análisis" para rationale completo.
- **Notebooks reorganizados**: carpeta `notebooks/` con NB01–NB08
  (pipeline analítico) + `varios/` (exploración ad-hoc). Figuras
  originales preservadas en `notebooks/figuras_backup/`; figuras
  regeneradas con código reproducible en `notebooks/figuras/`.
- **`requirements.txt`**: agregado `ipykernel>=6.0` para registro
  del kernel Jupyter en el entorno conda `apnea`.
- **README.md**: instrucción de registro de kernel Jupyter agregada
  al setup inicial.

## v1.1 — 2026-05-17

Reorganización del proyecto y correcciones al orquestador.

- **Proyecto limpio**: PAC_v2 reconstruido desde cero a partir de Backup_PAC_v2.
  Solo código fuente, tests, app, docs y datos de entrada. Outputs regenerados
  corriendo el pipeline completo.
- **Orquestador completo**: se agregaron los pasos faltantes en `compute_plan`:
  `train_morphotypes`, `train_morphotypes_curve`, `validate_pac_states`,
  `generate_manifest`. El orquestador ahora corre el pipeline de punta a punta
  sin intervención manual, incluyendo bootstrap de modelos desde cero.
- **Prompt de re-entrenamiento**: el orquestador pregunta si re-entrenar
  morfotipos y PAC states cuando hay datos nuevos y los modelos ya existen.
- **K PAC states escala m**: cambiado de 6 a 5 en `PAC_STATES_HISTORICAL_K`
  (K=6 generaba cluster degenerado M4 con 0.27% — por debajo del umbral C1
  del validador con esta cohorte).
- **Dependencia tabulate**: agregada a `requirements.txt` (requerida por
  `train_morphotypes.py` para el reporte de interpretabilidad en markdown).

## v1.0-tesis — 2026-04-26

Release de defensa de tesis. Pipeline completo, 5 tablas Gold + 2
sidecars, 350 tests OK.

### Etapa 7 — Validación final + release

- Full end-to-end run verificado (gold pipeline 27.8s).
- Audit de tests: 350/350 OK distribuidos en 21 archivos.
- README.md y CHANGELOG.md creados.
- Lint con ruff aplicado.
- `PAC_v2_ANALISIS.md` revisado y alineado con Gold v1 (incluye grafo
  Mermaid del pipeline + joins + cohortes).
- Tag git `v1.0-tesis`.

### Etapa 6 — Orquestador incremental

- `src/pac/orchestrator.py` (módulo puro testeable) + `scripts/orchestrate.py`
  (CLI híbrido con sub-comandos `status`/`plan`/`run`).
- Detección de staleness por mtime de archivos. Auto-invalidación por
  reentrenamiento (mtime de `models/*` cambia).
- 22 tests determinísticos con tmp_path + monkeypatch.

### Etapa 5 — Gold (data lake unificado APNEA+PAC)

- 5 tablas: `events.parquet` (85k filas × 32 cols), `events_curves.parquet`
  (85k × 5), `states.parquet` (519k × 22), `nights.parquet` (560 × 146),
  `patients.parquet` (12 × 71).
- 2 sidecars versionados: `gold/MANIFEST.json` (sha256 + counts) y
  `gold/nights_columns.json` (diccionario de las 146 cols clasificadas
  en single_night/cross_night_corpus/cross_night_patient).
- Filosofía data-lake: preserva TODO lo medido + bloques transversales
  (user_id + flags de cohorte + model_version) en cada tabla.
- Cross-night `_pct_corpus` calculadas SOBRE quality (553) como
  referencia. Cross-night `_vs_baseline_patient` con leave-one-out.
- Orquestador `scripts/build_gold_all.py` con pre-requisitos validados.
- 78 tests nuevos (5 archivos).

### Etapa 4.6 — Pre-Gold hardening

- Lock de dependencias (`requirements.txt` con rangos + `freeze_lock.sh`).
- Schema validation (`src/pac/schemas.py` con 10 schemas + 10 validators).
- Cohort helpers (`src/pac/cohorts.py`: 5 cohortes públicas con
  `lru_cache`).
- Model manifest (`models/MANIFEST.json` con sha256 + corpus_snapshot
  + retrain_policy).
- Retrain gateway (`scripts/retrain_check.py` con prompt y/N).

### Etapa 4 — PAC States multi-escala (K=6/8/6)

- Ventaneo multiescala s/m/l (30s/5min/30min) en `src/pac/windows.py`.
- KMeans pooled con z-score por escala. Decisión K via sweep + dashboard.
- Apply batch a 560 noches (`scripts/apply_pac_states.py`) con metadata
  KV de versión.
- QA del labeling (5 checks B1-B5). Cross-check con silver_qc redujo
  7 noches B2-fail a "exclusión obligatoria".
- Stratigraphy dashboard interactivo (5 noches representativas) con
  Plotly.

### Etapa 3b — EDO Morphotyping (KMeans K=4)

- Clustering no supervisado de la geometría de EDOs sobre 24 features.
- 4 morfotipos (α/β/γ/δ) caracterizados por geometría dominante.
- Validación con sweep + análisis clínico de centroides.
- Apply batch sobre 85k EDOs con persistencia en `events/{NR}_edos.parquet`.

### Etapa 3 — Events (EDOs + IRD + índices nocturnos)

- Detección de EDOs con criterios temporales y de profundidad.
- Cálculo de IRD compuesto (SpO₂/HR/MOV con pesos).
- 104 índices nocturnos clásicos (AHI/ODI/T90/HB) en gemelo con device.
- 3 archivos por noche: `_edos.parquet`, `_edo_curves.parquet`,
  `_indices.parquet`.

### Etapa 2 — Silver QC

- Validación de cobertura, gaps, valores fuera de rango.
- Limpieza con flags `*_invalid` y versiones `*_clean`.
- Reporte agregado `reports/silver_qc_summary.csv`.

### Etapa 1.1 — Auto-registro de pacientes nuevos

- Detección de `user_id` no registrados al ingest.
- Append automático a `patient_registry.csv` con WARNING.

### Etapa 1 — Bronze (ingest .xlsx → parquet)

- Parser de xlsx con dialect del device.
- Generación de `night_record_id` (NR) por hash determinístico de
  contenido.
- Persistencia en parquet con metadata KV (source_sha256, ts_start,
  user_id, etc.).

### Etapa 0 — Scaffold + identidad

- Estructura de directorios medallion (raw → bronze → silver → events
  → states → gold).
- Modelo de identidad de 2 archivos (registry local PII + clinical
  versionable).
- Bootstrap de pacientes desde CSV de origen.
- Setup de tests con pytest.
