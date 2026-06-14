# PAC_v2 — Handoff de contexto

> Documento de continuidad del proyecto de tesis de Roberto Inza (Master en Data Science, Universidad Austral). Sube este archivo al **Project de Claude AI** llamado "PAC v2" para que cualquier chat nuevo arranque con todo el contexto.

---

## 1. Qué es PAC_v2

Rediseño desde cero de la tesis: consolidación de dos pipelines viejos (**APNEA** para detección de eventos, **PAC** para estados dinámicos continuos) en **un solo pipeline unificado**.

Objetivos explícitos:

1. Eliminar redundancias del código viejo (crosswalks, dobles agregaciones, timelines symmetric-redundant).
2. Simplificar ingest incremental de nuevas noches (`.xlsx` → pipeline).
3. Minimizar archivos de salida (la tesis evalúa ML, no ingeniería Python).
4. Un único Gold unificado APNEA + PAC.

---

## 2. Arquitectura decidida

**Medallion con 4 zonas:**

```
raw/       .xlsx originales de cada noche (no versionado, local)
bronze/    .parquet por noche con señales canónicas
silver/    .parquet por noche con eventos / ventanas / estados
gold/      .csv consolidados (nights / events / patients)
```

**Señales canónicas** (únicas que se conservan del .xlsx): `timestamp`, `spo2`, `hr`, `mov`. Todo lo demás del xlsx se descarta.

**NightRecordID** = `NR_` + MD5(source_sha256 | ts_start | salt)[:10]. El salt se lee de env var `PAC_NIGHT_ID_SALT`, no se commitea.

**Identidad pseudonimizada — modelo de 2 archivos** (actualizado en Etapa 1):

| archivo | contenido | git |
|---|---|---|
| `patients/patient_registry.csv` | `patient_id;nombre;apellido;fecha_nacimiento` | ❌ local (PII) |
| `patients/clinical.csv` | `patient_id;sexo;peso_kg;talla_cm;apnea_prev;diabetes;hta;marcapasos` | ✅ |

Separador único: `;`

El mapping `source_exam_id → patient_id` está implícito en los xlsx (campo `user_id` del bloque 1) y se persiste como metadata KV de cada parquet bronze. El archivo `source_exam_map.csv` fue deprecado por redundante.

**Regla de parseo de fechas** (dd/mm/yy): `yy ≤ 25 → 20yy`, si no `19yy`. Bootstrap imprime WARNING a consola si resuelve un año ≥ 2000 (no se persiste flag en archivo).

---

## 3. Roadmap — 7 etapas

Workflow: para cada etapa, primero se define scope + se aprueba, después se escribe código.

- **Etapa 0** — Scaffold + config + identidad + hygiene. ✅ **CERRADA**
- **Etapa 1** — Bronze: ingest `.xlsx` → parquet + generación de NightRecordID.
- **Etapa 2** — QC por noche (validaciones, gaps, outliers).
- **Etapa 3** — Events: EDOs + IRD + índices clásicos (T90, ODI, etc.).
- **Etapa 4** — Windows multiescala (short/medium/long) + estados (KMeans: S0–S6, M0–M5, L0–L3).
- **Etapa 5** — Gold: nights_gold, events_gold, patients_gold (unificado APNEA+PAC).
- **Etapa 6** — Orchestrator incremental (staleness por mtime).
- **Etapa 7** — Validación final + release.

---

## 4. Estado actual — Etapa 0 CERRADA

### Estructura creada

```
PAC_v2/
├── raw/ bronze/ silver/ gold/ reports/   (vacíos, placeholders con .gitkeep)
├── patients/
│   ├── patient_registry.csv              (12 pacientes, PII, local)
│   └── clinical.csv                      (12 filas, datos clínicos)
├── src/pac/
│   ├── __init__.py
│   ├── config.py                         (paths + contrato de columnas)
│   └── io.py                             (helpers: parse_birthdate, parquet, identity CSVs)
├── scripts/
│   ├── bootstrap_patient_files.py        (one-shot: CSV de origen → 3 archivos)
│   └── git_init_etapa_0.sh               (inicializador de git para correr en Mac)
├── tests/
│   ├── __init__.py
│   └── test_parse_birthdate.py           (12 casos, todos OK)
├── run.py                                (stub: valida scaffold)
├── requirements.txt                      (pandas, numpy, pyarrow, openpyxl, scikit-learn)
├── README.md
└── .gitignore
```

### Cohorte de 12 pacientes (auditada)

| patient_id | nombre | apellido | nacimiento | sexo | peso | talla | apnea | db | hta | mp |
|---|---|---|---|---|---|---|---|---|---|---|
| 175 | Diego | Sanchez | 1942-07-10 | M | 105 | 168 | 1 | 0 | 1 | 0 |
| 240 | Marcos | Ugarte | 1975-04-01 | M | 88 | 170 | 1 | 0 | 1 | 0 |
| 309 | Ricardo | De Udaeta | 1957-04-07 | M | 76 | 173 | 1 | 0 | 1 | 0 |
| 314 | Alex | Adi | 1968-07-27 | M | 99 | 175 | 0 | 0 | 1 | 0 |
| 321 | Sebastian | Arcucci | 1974-08-23 | M | 90 | 175 | 1 | 0 | 1 | 0 |
| 336 | Domingo Nicolas | Catena | 1939-11-12 | M | 62 | 170 | 1 | 0 | 0 | 0 |
| 622 | Andred | Ocampo | 1978-03-28 | M | 78 | 182 | 1 | 0 | 0 | 0 |
| 656 | Diego | Delia | 1974-06-01 | M | 93 | 172 | 0 | 0 | 0 | 0 |
| 683 | Josef | Broich | 1967-08-02 | M | 79 | 184 | 0 | 0 | 0 | 0 |
| 687 | Salvador | Martinez | 2009-07-28 | M | 70 | 180 | 0 | 0 | 0 | 0 |
| 688 | Roberto | Inza | 1965-07-08 | M | 80 | 172 | 0 | 0 | 0 | 0 |
| 689 | Alejandra | Ferrigno | 1964-04-12 | F | 65 | 160 | 0 | 0 | 0 | 0 |

**Notas de auditoría (todas resueltas):**

- Salvador Martinez (687) nacido en 2009 → confirmado manualmente. No es error.
- Andred Ocampo (622) → identidad confirmada manualmente (nombre correcto).
- Columna `edad` del CSV de origen estaba vacía y se descarta: en el pipeline se calcula dinámicamente a partir de `fecha_nacimiento` + timestamp de la noche.

### Decisiones aplicadas en Etapa 0

1. Columna `fumador` removida de `clinical.csv` (no había datos en origen).
2. Columna `fecha_nacimiento_flag_audit` removida del contrato (over-engineering; WARNING a consola es suficiente).
3. Terminología: **"CSV de origen"** = `datos_paciente.csv` (input one-shot del bootstrap; no se usa después de Etapa 0).

### Cierre — verificaciones ejecutadas

- **Idempotencia del bootstrap**: dos pasadas independientes producen el mismo hash SHA256 (registry y clinical). ✅
- **Tests unitarios `parse_birthdate`**: 12/12 casos OK (pivot 25/26, cohorte real, 4 dígitos, inválidos). ✅
- **`run.py`**: PASSED — 12 pacientes consistentes entre registry y clinical. ✅
- **git init + baseline commit**: ✅ `31a2c50` — `Initial: Etapa 0 CERRADA + Etapa 1 WIP`.
- **Path actual del proyecto**: `/Users/ri1965/Proyectos/PAC_v2` (movido fuera de `~/Documents/` para evitar bloqueos de TCC en macOS).

---

## 4bis. Estado actual — Etapa 1 CERRADA

Código escrito, batch completo ejecutado, outputs validados. Decisiones de scope aprobadas por Roberto antes del código.

### Artefactos nuevos

- `src/pac/ingest.py` — helpers atómicos:
  - `compute_sha256(path)` — streaming 1 MiB chunks.
  - `compute_night_record_id(sha, ts_start_iso)` → `NR_ + MD5(sha|ts_start)[:10]`, **sin salt**.
  - `load_xlsx_night(path)` → `(meta, classical, signals_raw)` — segmenta los 3 bloques del xlsx por filas vacías; robusto a xlsx "unsized".
  - `_parse_ampm_time(s)` — tolera `\u202f` (narrow NBSP) y lowercase.
  - `reconstruct_timestamps(time_strs, ts_start)` — cruce medianoche vectorial: `(diff < 0).cumsum()` como day offset.
  - `normalize_signals(...)` → DataFrame canónico 5-col + diagnostics.
  - `write_signals_parquet` / `write_classical_sidecar` — pyarrow con KV metadata al nivel de schema.
- `src/pac/bronze.py` — orquestador + CLI: `python -m pac.bronze [--limit N]`.
- `scripts/run_bronze.py` — launcher sin PYTHONPATH (evita bug `<frozen getpath>` en Python 3.12 + macOS + conda).
- `scripts/unlock_perms.sh` — helper xattr (legado post-mudanza; ya no necesario).
- `tests/test_ingest.py` — 15 tests: AM/PM (`\u202f`), cruce medianoche, gaps, determinismo NightRecordID, SHA256.

### Decisiones cerradas Etapa 1

1. `patient_id` sale del xlsx (campo `user_id` del bloque 1 de metadata).
2. Re-ingest: **sobreescritura silenciosa** (idempotente si el xlsx no cambió).
3. Sampling: **1 Hz fijo**; se guarda `sampling_hz_median` en metadata como sanity.
4. Índices clásicos pre-computados por el dispositivo → **sidecar parquet** `{NightRecordID}_classical.parquet` (21 columnas: ahi_3/4, odi_3/4, hypoxic_burden_3/4, tst, efficiency, waso, etc.). Material para validación vs recálculo en Etapa 3.
5. `sleep_stage` como **5ta columna canónica** en `SIGNAL_COLS` (uso efectivo queda abierto hasta Etapa 3/4).
6. **NightRecordID sin salt** — determinismo puro.

### Contrato de outputs por noche

Dos parquets en `bronze/`, con metadata KV replicada al schema:

| archivo | filas | columnas | metadata KV |
|---|---|---|---|
| `{NR}.parquet` | N samples | `timestamp, spo2, hr, mov, sleep_stage` | night_record_id, source_file, source_sha256, source_exam_id, user_id, ts_start, ts_end, n_samples, sampling_hz_nominal/median, n_gaps, duration_s, pipeline_stage, pipeline_version |
| `{NR}_classical.parquet` | 1 | 21 índices + `algorithm_version` | (mismo set) |

### Verificaciones ya ejecutadas

- ✅ 1 xlsx end-to-end: `exam_12514.xlsx` (user 309) → `NR_73104dce74`, 24704 samples, 312 gaps, medianoche correcta.
- ✅ Idempotencia: 2 pases → content hash idéntico (signals + classical).
- ✅ Smoke batch 20 xlsx: 20/20 OK.
- ✅ `tests/test_ingest.py`: 15/15 OK.
- ✅ **Batch completo 561 xlsx** (elapsed 46:29, re-run limpio post-dedup):
  - **560 OK, 1 FAIL, 0 SKIP cohort**.
  - FAIL: `exam_11943.xlsx` — `ValueError: xlsx con estructura inesperada: 2 bloques (se esperaban 3)`. Archivo truncado en origen; se acepta descarte.
  - **Dedup en `raw/`**: los 2 pares byte-idénticos detectados en el batch previo (`exam_13067 2.xlsx` y `exam_13128 2.xlsx`, sufijo ` 2.xlsx` de macOS = copias dobles de bajada) se **eliminaron físicamente** de `raw/` antes de este re-run. Principio: no acumular errores históricos en los logs; reiniciar desde raw limpio cuando se está iterando el pipeline (pre-Etapa 2).
  - **560 noches únicas** (1120 parquets: 560 signals + 560 classical).
  - **Idempotencia verificada**: los 560 NR_ids post-reset coinciden byte-a-byte con los del batch previo (diff limpio sobre filenames ordenados).
- ✅ Cobertura cohort (12/12 pacientes, dedup por NR):

  | user_id | nights | user_id | nights |
  |:--:|:--:|:--:|:--:|
  | 175 | 29 | 336 | 117 |
  | 240 | 28 | 622 | 2 |
  | 309 | 65 | 656 | 106 |
  | 314 | 11 | 683 | 75 |
  | 321 | 109 | 687 | 9 |
  | 688 | 6 | 689 | 3 |

  Total: **560 noches**. Fuerte desbalance (336: 117 vs 622: 2) — dato para tesis.
- ✅ Duración por noche (h): min=0.22, p25=6.16, median=7.23, p75=8.40, max=10.10. Total señal ≈ 3960 h (~165 días).
- ✅ Gaps por noche: median=416, p95=829, max=1168 (1 Hz nominal sobre ~7 h ≈ 25 k samples → <4% gaps típicos).
- ✅ Spot-check 3 parquets: schema 5-col ✓, metadata KV 15-fields ✓, cruce medianoche ✓, classical sidecar 1×21 ✓.

---

## 5. Convenciones de código

- Python 3.10+, pandas, numpy, pyarrow (parquet), openpyxl (xlsx), scikit-learn.
- Constantes planas en `src/pac/config.py` (no clases de config).
- Un helper por responsabilidad (sin god-modules).
- Los módulos de pipeline (bronze, silver, gold) viven en `src/pac/` — NO notebooks.
- Notebooks sólo para exploración; el pipeline es `.py`.
- Tests en `tests/`, ejecutables con `python -m tests.<modulo>` o `pytest`.

---

## 6. Limitación importante del Project en Claude AI

Claude AI (web/mobile) **NO tiene acceso al filesystem local** de Roberto. En el Project se puede:

- Discutir arquitectura, decisiones, trade-offs.
- Revisar código que Roberto pegue o suba.
- Proponer cambios / planificar etapas.

Pero **no** se puede:

- Ejecutar el pipeline.
- Leer/escribir archivos en `PAC_v2/`.
- Acceder a los `.xlsx` de noches.

Para ejecución real, Roberto sigue trabajando en **Cowork mode** (Claude desktop app) donde sí hay filesystem.

---

## 4ter. Etapa 1.1 — auto-registro de pacientes nuevos

Extensión menor de Etapa 1: cuando un xlsx en `raw/` trae un `user_id` que no
está en `patient_registry.csv`, el pipeline crea automáticamente una fila stub
(con `patient_id` lleno y los otros campos vacíos) en **los dos** CSVs de
identidad. Roberto completa los datos clínicos a mano después.

### Artefactos nuevos
- `src/pac/ingest.py`:
  - `peek_user_id(xlsx)` — abre sólo el Bloque 1 en read_only, ~10-50 ms/xlsx.
  - `scan_xlsx_user_ids(paths)` → `{user_id: [xlsx_filename, ...]}`.
  - `register_stubs_for_unknown_ids(xlsx_user_ids, verbose=True)` → crea filas
    stub en `patient_registry.csv` y `clinical.csv`, idempotente.
- `src/pac/bronze.py`:
  - `run_bronze(..., autoreg=True)` — pre-pass antes del loop de ingest.
  - CLI: `--no-autoreg` para desactivar.
  - `gate.json` incluye sección `autoreg: {enabled, n_new_patients, new_patient_ids}`.
- `tests/test_autoreg.py` — 3 tests: creación, idempotencia, no-mutación de filas existentes.

### Flujo para paciente nuevo (post-Etapa 1.1)
1. Roberto tira el/los `exam_NNNNN.xlsx` nuevos en `raw/`.
2. Corre `python scripts/run_bronze.py`.
3. El pre-pass autoreg detecta el `user_id` nuevo, agrega fila stub a
   `patient_registry.csv` y `clinical.csv`, y loggea WARNING con los IDs
   creados.
4. El pipeline procesa los xlsx normalmente (ya no los skip-ea).
5. Roberto edita los 2 CSVs a mano y completa nombre/apellido/fecha_nac +
   datos clínicos.
6. Los datos quedan disponibles desde Etapa 3 en adelante (gold + análisis).

### Verificaciones ejecutadas
- ✅ `tests/test_autoreg.py`: 3/3 OK.
- ✅ Regresión: `tests/test_ingest.py` 15/15 OK, `tests/test_parse_birthdate.py` 12/12 OK.
- ✅ Smoke sobre raw/ (3 xlsx): "sin pacientes nuevos — 12 ya en registry,
  0 stubs creados". Registry y clinical intactos.
- ✅ `bronze_gate.json` incluye la nueva sección `autoreg`.

### Safety notes
- **Typo del dispositivo** crea paciente fantasma. Mitigación: WARNING visible
  en el batch + review del gate.json.
- **Rollback**: borrar la fila stub falsa de ambos CSVs y mover/borrar el xlsx
  ofensor de `raw/`.
- **Desactivar**: `--no-autoreg` o `autoreg=False` → comportamiento original
  (xlsx con user_id desconocido quedan como `SKIP_COHORT`).

---

## 4quater. Etapa 2 CERRADA — Silver (QC por noche)

QC básico sobre las señales de bronze, sin análisis multi-señal (eso vive en Etapa 3 Events). Decisiones cerradas Q1–Q8 con Roberto.

### Alcance
- **Range QC** por señal: valores no-fisiológicos → NaN + flag. Preserva la columna original + agrega 2 cols nuevas (`{col}_invalid` bool, `{col}_clean` float64 con NaN).
- **Cobertura temporal**: coverage ratio + max_contiguous_gap (no n_gaps).
- **Duración**: dual-flag `aborted` ⊂ `short`.
- Silver **NO** lee `clinical.csv` ni `patient_registry.csv`.
- Multi-señal coherence (HR vs SpO2, eventos) difiere a Etapa 3.

### Umbrales (pac/config.py)

| Constante | Valor | Decisión |
|---|---|---|
| `SPO2_MIN_VALID` | 55 | Q1 — 1c |
| `HR_MIN_VALID` | 30 | Q2 — 2b |
| `HR_MAX_VALID` | 200 | Q2 — 2b |
| `QC_COVERAGE_MIN` | 0.90 | Q3 — 3c |
| `QC_MAX_GAP_S` | 1800 (30 min) | Q3 — 3c |
| `QC_DURATION_ABORTED_S` | 3600 (1 h) | Q4 — 4a |
| `QC_DURATION_MIN_S` | 10800 (3 h) | Q4 — 4a |

### Artefactos

**Código:**
- `src/pac/qc.py` — helpers puros: `apply_range_qc`, `compute_gap_metrics`, `compute_duration_flags`, `compute_coverage_flags`.
- `src/pac/silver.py` — `process_one(nr_path)` + `run_silver(limit=None)` con isolation por try/except; CLI `python -m pac.silver [--limit N]`.
- `tests/test_qc.py` — 20 tests unitarios (range QC edge cases, gap metrics, duration flags, integración sintética).

**Output por noche (2 parquets, pattern Q6 6b):**
- `silver/{NR}.parquet` — 9 cols: `timestamp, spo2, spo2_invalid, spo2_clean, hr, hr_invalid, hr_clean, mov, sleep_stage`.
- `silver/{NR}_qc.parquet` — 1 fila × 16 cols con métricas QC (coverage, max_contiguous_gap_s, n/frac_*_invalid, flags).
- Metadata KV heredada de bronze + agrega `pipeline_stage=silver`, `silver_schema_version=1`, `silver_processed_at`, los umbrales aplicados.

**Reports (Q7 7b + log-B):**
- `reports/silver_gate.json` — resumen + flags counts + distribuciones (median/p5/p95/min/max) de coverage, max_gap, duration, frac_invalids.
- `reports/silver_qc_summary.csv` — snapshot legible 1 fila × noche.

### Batch completo (560 noches, post-reset de Bronze)

- **560/560 OK, 0 FAIL** en **42.8 s** (vs 46:29 min de Bronze).
- Coverage: median 0.983, p5=0.969, min=0.476, max=1.0.
- Max gap: median 1 s, p95=11 s, max=9656 s (2.7 h).
- Duration: median 7.23 h, p5=4.27 h, min=13 min.
- frac_spo2_invalid: median 0.04%, p95=0.43%, max=25.0%.
- frac_hr_invalid: median 0.46%, p95=1.1%, max=13.1%.

### QC flags agregados

| flag | n true | % | interpretación |
|---|---|---|---|
| `qc_coverage_ok` | 547 | 97.7% | 13 noches con gaps grandes que bajan coverage <0.90 |
| `qc_max_gap_ok` | 545 | 97.3% | 15 noches con al menos 1 gap >30 min |
| `qc_duration_aborted` | 4 | 0.7% | estudios abortados <1h |
| `qc_duration_short` | 17 | 3.0% | noches <3h (incluye las 4 aborted) |

Las 13 noches que fallan coverage son subset de las 15 que fallan max_gap (correlación esperada: un gap grande baja coverage). Las 4 aborted tienen `frac_hr_invalid` entre 4–13% (sensor sin estabilizar).

### Idempotencia

- **Contenido**: 5/5 verificado — re-procesar produce DataFrames idénticos.
- **Archivos**: NO byte-idénticos entre corridas por `silver_processed_at` (ISO timestamp) en KV metadata. Decisión intencional: trazabilidad > hash estable.

### Verificaciones ejecutadas
- ✅ `tests/test_qc.py`: 20/20 OK.
- ✅ Smoke `--limit 10`: 10/10 OK en 0.7 s, schema validado, metadata KV correcta.
- ✅ Batch completo 560 noches: 560/560 OK, 0 FAIL, 42.8 s.
- ✅ Spot-check parquet silver: schema 9-col ✓, dtype por col ✓, flags coherentes ✓, clean col con NaN donde invalid ✓.
- ✅ Idempotencia de contenido (5 noches): DataFrames idénticos.
- ✅ Tests previos sin regresión: `test_ingest.py`, `test_autoreg.py`, `test_parse_birthdate.py`.

---

## 4quinquies. Etapa 3 CERRADA — Events (EDOs, IRD e índices nocturnos)

Primera etapa analítica de PAC_v2: sobre las 560 noches silver, detectar objetos morfológicos (EDOs), calcular un índice multisignal de respuesta (IRD) y consolidar los índices clásicos de APNEA (ODI/AHI/T90/CT90/hypoxic burden) + métricas de sueño + variantes HR/mov. Validación por quintete vs sidecar classical del dispositivo. Decisiones R1–R5 y Q1–Q15 cerradas con Roberto.

### Alcance
- **EDO = Evento de Desaturación de Oxígeno** (objeto morfológico, no clasificador binario). Detección permisiva sin restringir a respiratorio: drop ≥ 2% sostenido ≥ 10s vs baseline móvil AASM 2012 (mediana 120s previo). Clustering real/noise difiere a Etapa 4.
- **IRD = Índice de Respuesta a la Desaturación** multisignal (SpO2 + HR + mov) por evento, con pesos 0.5 / 0.3 / 0.2. Normalizado 0–1.
- **Índices nocturnos clásicos** (quintete vs device): ODI_3/4, AHI_3/4, T90/CT90, hypoxic_burden_3/4, TST_s, sleep_efficiency, WASO_s.
- Silver filtering: se **incluyen** todas las 560 noches (no exclusión por QC). Las flags QC viajan al pool de validación para cross-tab.
- **Safety net**: pre-check de `clinical.csv` (no-blocking) antes de arrancar el batch.

### Umbrales cerrados (pac/config.py)

| Constante | Valor | Decisión |
|---|---|---|
| `EDO_BASELINE_WINDOW_S` | 120 | R1 — AASM 2012 Rule 10 |
| `EDO_RECOVERY_PCT` | 0.90 | R2 — recupera a ≥90% de baseline_at_start |
| `EDO_MIN_DURATION_S` | 10 | R3 — permisivo |
| `EDO_DROP_THRESHOLDS_PCT` | [2, 3, 4, 5] | Q1 — familia ODI/AHI |
| `EDO_RESAMPLE_N_POINTS` | 30 | Q2 — morfología sidecar-compatible |
| `NEAR_GAP_WINDOW_S` | 300 | Q3 — ventana ±5 min para flag `near_gap` |
| `HR_BRADY_THRESHOLD_BPM` | 50 | Q7 |
| `HR_TACHY_THRESHOLD_BPM` | 100 | Q7 |
| `DIFF_REL_FLAG_THRESHOLD` | 0.20 | Q12 — flag quintete si \|diff_rel\|>20% |
| `IRD_WEIGHTS` | {spo2:0.5, hr:0.3, mov:0.2} | Q5 |
| `VALIDATED_INDICES` | 11 índices | Q11 — subset con contrapartida device |

### Artefactos

**Código:**
- `src/pac/events.py` — helpers puros: `baseline_moving`, `detect_edo_candidates`, `characterize_edo`, `compute_ird_event` + componentes SpO2/HR/mov, `resample_curve`, `mark_in_sleep`, `near_gap`.
- `src/pac/indices.py` — 5 familias: SpO2 (ODI/T<N/CT<N/hypoxic_burden/spo2_stats), HR (stats + brady/tachy), mov, sueño (TST/WASO/SE con fallback), event-based (IRD_night, AHI_N, morfología).
- `src/pac/events_pipeline.py` — `process_one_events`, `run_events`, `_read_classical_sidecar`, `clinical_precheck`, CLI `python -m pac.events_pipeline [--limit N]`.
- `scripts/validate_vs_device.py` — consolidación del pool de 560 noches + stats por índice + cross-tab diff_flag × QC.
- `tests/test_events.py` — 23 tests unitarios (baseline, detección, morfología, IRD, edge cases).
- `tests/test_indices.py` — 31 tests unitarios (las 5 familias + cálculo diff quintete).

**Output por noche (3 parquets, 1 row para indices):**

| archivo | contenido |
|---|---|
| `events/{NR}_edos.parquet` | 1 fila × EDO con morfología (baseline, nadir, slopes, AUC), flags (`near_gap`, `in_sleep`, `meets_Npct`), IRD y componentes. |
| `events/{NR}_edo_curves.parquet` | morfología resampleada a 30 puntos (para sidecar-compatibility). |
| `events/{NR}_indices.parquet` | 1 fila × ~104 cols: todos los índices + quintete {pac_v2, device, diff_abs, diff_rel, diff_flag} para los 11 validados. |

Metadata KV heredada de silver + `pipeline_stage=events`, `events_schema_version=1`, `events_processed_at`, `algorithm_version=pac_v2_events_1.0.0`, umbrales aplicados.

**Reports:**
- `reports/events_clinical_precheck.json` — safety net (pacientes con clinical vacío, no-blocking).
- `reports/events_gate.json` — resumen batch + umbrales + distribuciones (median/p5/p95/min/max) de n_edos, ODI_3/4, AHI_3/4, T90, CT90, IRD_night, hypoxic_burden.
- `reports/events_summary.csv` — 1 fila × noche (índices nocturnos).
- `reports/events_indices_pooled.parquet` — consolidado 560 noches × 104 cols (bronze para Gold).
- `reports/events_validation_by_index.csv` — 1 fila × índice validado: pearson, spearman, slope OLS, diff_rel percentiles.
- `reports/events_validation_report.json` — timestamp + umbrales + per-index stats + cross-tabs.

### Batch completo (560 noches)

- **560/560 OK, 0 FAIL** en **272.7 s** (~0.49 s/noche).
- Output total: **65.0 MB** (~116 KB/noche entre los 3 parquets).
- n_edos por noche: median **140.5**, p5=49, p95=286, min=5, max=434.
- ODI_3: median **14.63**, p95=40.2, max=98.5 (paciente severo).
- ODI_4: median **9.25**.
- AHI_3: median **11.98**, p95=35.9.
- IRD_night: median ~0.42, p5=0.31, p95=0.58 (distribución acotada, no-degenerada).
- Hypoxic burden_3: median 3.75 %·h, p95=18.1.

### Validación vs device (560 noches, 11 índices)

| índice | N | % flag | pac_v2 med | device med | pearson | slope OLS |
|---|---|---|---|---|---|---|
| tst_s | 560 | 0.0% | 21615 | 21613 | 1.0000 | 1.00 |
| waso_s | 560 | 0.0% | 3273 | 3274 | 1.0000 | 1.00 |
| sleep_efficiency | 560 | 1.6% | 0.834 | 0.868 | 0.8282 | 0.93 |
| odi_3 | 560 | 50.5% | 14.63 | 14.93 | 0.7461 | 0.89 |
| odi_4 | 560 | 48.0% | 9.25 | 9.70 | 0.7630 | 0.84 |
| ahi_3 | 560 | 52.5% | 11.98 | 13.61 | 0.7657 | 0.59 |
| ahi_4 | 560 | 49.1% | 7.83 | 9.12 | 0.7580 | 0.61 |
| hypoxic_burden_3 | 560 | 92.9% | 3.75 | 9.00 | 0.6450 | 0.71 |
| hypoxic_burden_4 | 560 | 91.4% | 2.18 | 5.71 | 0.6281 | 0.68 |

**3 hallazgos clave para la tesis:**
1. **TST / WASO / sleep_efficiency reproducen el device casi perfecto** (pearson ≈ 1.0, slope ≈ 1.0): la pipeline interpreta correctamente el staging del dispositivo.
2. **ODI / AHI: pac_v2 es sistemáticamente más sensible** (~50% diff_flag, pearson ≈ 0.75, spearman ≈ 0.85–0.89). Los rankings se preservan → útil para ML pese al bias en magnitud. Hipótesis: detección permisiva (sin restringir a respiratorio) captura más eventos que el device.
3. **Hypoxic burden: pac_v2 ≈ 2.5× device** (92.9% diff_flag). Hipótesis: device usa umbral relativo-a-baseline, pac_v2 usa absoluto 90%. Flagged para discusión en Etapa 5.

Cross-tab `diff_flag × silver QC` muestra que las noches con `qc_coverage_ok=False` o `qc_max_gap_ok=False` concentran 60–100% de diff_flag (vs 50% global) — consistente con QC degradando la comparabilidad.

### Verificaciones ejecutadas
- ✅ `tests/test_events.py`: 23/23 OK.
- ✅ `tests/test_indices.py`: 31/31 OK.
- ✅ Regresión completa `pytest tests/`: 104/104 OK (incluye test_qc, test_ingest, test_autoreg, test_parse_birthdate).
- ✅ Smoke synthetic 28800s con 10 notches: ODI_3=1.25/h, T90=0.01042, CT90=5 min, HB≈3.125 — verificados manualmente.
- ✅ Clinical pre-check: 560/560 pacientes con clinical completo.
- ✅ Batch completo 560 noches: 560/560 OK, 0 FAIL, 272.7 s.
- ✅ Pool consolidado 560 × 104 cols persistido en `events_indices_pooled.parquet`.
- ✅ Validación cross-dataset: pearson/spearman/OLS slope-intercept por los 11 índices validados.

### Idempotencia
- **Contenido**: determinístico — re-procesar produce DataFrames idénticos (tests unitarios lo cubren).
- **Archivos**: NO byte-idénticos por `events_processed_at` (ISO timestamp) en KV metadata. Intencional: trazabilidad > hash estable.

---

## 4sexies. Etapa 3b CERRADA — EDO Morphotyping (KMeans unsupervised)

Entre Etapa 3 (Events) y Etapa 4 (Windows PAC) se inserta una etapa analítica no-planeada originalmente pero clínicamente valiosa: **clusterizar los EDOs antes de construir estados nocturnos**. La motivación fue de Roberto: "tener EDO leve / moderado / severo se podría hacer antes de entrar con PAC". El resultado es un morfotipo griego por EDO (α / β / γ / δ) que viaja como columna extra en `events/{NR}_edos.parquet` y queda disponible como feature tanto para el modelo PAC nocturno de Etapa 4 como para reporting descriptivo en Etapa 5.

### Alcance
- **Morfotipo = cluster KMeans no-supervisado sobre 10 features escalares del EDO**, normalizadas por z-score pooled. Sin labels clínicos de entrada; la interpretación (severo / sostenido / respuesta motora / leve) es post-hoc sobre centroides.
- **Nomenclatura griega** (α, β, γ, δ) en lugar de adjetivos clínicos ("leve / moderado / severo") — más honesta con respecto al origen unsupervised y extensible hasta K=10.
- **Universo de labeling**: TODOS los 85 286 EDOs del pool (560 noches), incluidos los marginales `meets_2pct` que quedaron fuera del training subset. Cada EDO recibe un morfotipo si sus 10 features están completas.
- **Universo de training**: subset canónico `in_sleep=True & ~near_gap & meets_3pct=True` → **42 819 EDOs (50.2 % del pool)**. Los marginales no contaminan los centroides pero sí reciben label en inferencia.

### Umbrales y decisiones cerradas (Q1–Q4)

| # | Decisión | Valor | Motivación |
|---|---|---|---|
| Q1 | Features | **B** — 6 morfología (`duration_s`, `drop_pct`, `nadir_spo2`, `slope_desat_pct_s`, `slope_recov_pct_s`, `auc_spo2_pct_s`) + 4 IRD (`ird_event`, `ird_spo2_comp`, `ird_hr_comp`, `ird_mov_comp`) | Incluir IRD desde training (no solo shape SpO2) para que los morfotipos reflejen la respuesta autonómica, no sólo la desaturación. |
| Q2 | Selección K | **B** — sweep K=2..10 con silhouette + Davies-Bouldin + elbow, decisión humana sobre plateau | Heurística automática tiende a K=2 (binario) o K=10 (DB decreciente monotónicamente). Plateau K=3–6 en silhouette ~0.30 permite elegir por valor clínico. |
| Q3 | Training mask | **B** — excluir marginales `meets_2pct-only` del training (quedan en inferencia) | Centroides basados en EDOs claramente significativos (≥ 3 %); marginales igual reciben label por consistencia del pipeline. |
| Q4 | Nomenclatura | **A** — letras griegas α, β, γ, δ | No pre-judge severidad; deja la interpretación clínica al capítulo de discusión. |

### K elegido: **K=4** (decisión humana post-dashboard)

Inicialmente K=3 se consideraba el extremo parsimonioso del plateau silhouette. Roberto pidió comparar K=3 vs K=4 vía dashboard visual antes de decidir. K=4 ganó porque divide los β "leves" de K=3 en dos fenotipos clínicamente distintos: los **α sostenidos** (drop moderado ~7 % pero duración 38 s y AUC alta — fenotipo novedoso) y los **δ leves verdaderos** (drop 4 %, duración 19 s). Esto vale la pérdida de parsimonia.

**Sweep K=2..10:**

| K | inertia | silhouette | DB |
|---|---|---|---|
| 2 | 311 118 | 0.467 | 1.33 |
| 3 | 263 699 | 0.348 | 1.40 |
| **4** | **239 156** | **0.296** | **1.44** |
| 5 | 215 849 | 0.298 | 1.31 |
| 6 | 200 919 | 0.299 | 1.32 |
| 7 | 187 374 | 0.262 | 1.29 |
| 8 | 174 522 | 0.257 | 1.29 |
| 9 | 163 807 | 0.262 | 1.24 |
| 10 | 154 766 | 0.257 | 1.22 |

Silhouette max en K=2 es la dicotomía severos/resto. K=3–6 forman plateau estable ~0.30. K≥7 degrada. K=4 es el primer K dentro del plateau que separa "sostenidos" de "leves".

### Centroides (espacio original, K=4)

| morfotipo | n_train | % | duration_s | drop_pct | nadir_spo2 | slope_desat | slope_recov | AUC | IRD_event | ird_mov |
|---|---|---|---|---|---|---|---|---|---|---|
| **α** (sostenidos) | 7 379 | 17.2 % | **38.2** | 7.1 | 87.1 | 0.51 | 0.85 | 128.6 | 2.6 | 12.6 |
| **β** (resp. motora) | 7 986 | 18.7 % | 20.8 | 8.1 | 86.5 | 1.40 | 1.11 | 75.8 | 13.5 | **67.2** |
| **γ** (severos) | 2 448 | 5.7 % | 24.3 | **20.8** | **73.9** | **4.20** | **3.22** | **206.0** | 10.1 | 49.9 |
| **δ** (leves) | 25 006 | 58.4 % | 18.5 | **4.2** | 90.0 | 0.79 | 0.60 | 38.9 | **1.2** | 6.0 |

**Interpretación post-hoc:**
- **α — sostenidos**: drop moderado pero duración 2× el resto; el EDO baja poco y se queda ahí. Slopes planas. Fenotipo clínicamente novedoso vs taxonomía AASM clásica.
- **β — respuesta motora**: drop leve-moderado pero `ird_mov_comp=67` (vs 6–50 en el resto). EDOs con despertar motor pronunciado (arousal cortical con componente movimiento).
- **γ — severos**: drop 21 %, nadir 74, slopes abruptas, AUC alta, IRD SpO2 alto. La cola severa clásica.
- **δ — leves**: drop 4 %, corto, IRD casi-cero. Mayoritario (58 % del training, 72 % del pool).

### Artefactos

**Código:**
- `src/pac/morphotypes.py` (276 líneas) — funciones puras: `load_edo_pool`, `build_training_mask`, `build_feature_matrix`, `ZScoreParams` dataclass, `fit_zscore`/`apply_zscore`, `sweep_k`, `fit_kmeans`, `predict_morphotype`, `int_to_greek`, `centroids_original_space`, `persist_model`, `load_model`, `choose_k`.
- `scripts/train_morphotypes.py` — CLI con `--k` / `--k-range`. Entrena sobre training subset, escribe modelo + reports.
- `scripts/apply_morphotypes.py` — CLI batch labeling sobre 560 noches. Idempotente; agrega columna `morphotype` in-place.
- `scripts/dashboard_morphotypes.py` — CLI `--k` para re-fit on-the-fly y generar dashboard HTML standalone con 6 secciones (sweep, centroides, boxplots por feature, composición meets_Npct, PCA 2D, curvas morfología media ±IQR).
- `tests/test_morphotypes.py` — 20 tests unitarios (mask, feature matrix, z-score, sweep_k, fit_kmeans determinismo + separación, int_to_greek, centroids, persist/load roundtrip, choose_k).

**Modelo persistido (`models/`):**

| archivo | contenido |
|---|---|
| `edo_morphotype_kmeans.pkl` | KMeans fitted (sklearn 1.7.2, n_clusters=4, random_state=42, n_init=10). |
| `edo_morphotype_zscore.json` | `ZScoreParams` (feature_cols + mean + std) para transformación reproducible. |
| `edo_morphotype_centroids.csv` | Centroides en espacio original (de-normalizados), index=letra griega. |
| `edo_morphotype_metadata.json` | K, algorithm_version, training_mask, n_training, random_state, k_sweep completo. |

**Column extra en parquets (560 ficheros):**

- `events/{NR}_edos.parquet` ahora incluye columna `morphotype` (dtype=object, valores ∈ {α, β, γ, δ, None}). KV metadata agregada: `morphotyping_applied_at`, `morphotype_algorithm_version=pac_v2_morphotypes_1.0.0`, `morphotypes_schema_version=1`.

**Reports:**

- `reports/morphotypes_training_report.json` — timestamp, training_mask, pool_size, training_size, k_range, k_chosen, k_sweep completo, centroids_original_space, cluster_sizes_training, meets_composition_training.
- `reports/morphotypes_interpretability.md` — tabla de centroides + sizes + composición meets_Npct + sweep, con placeholders para descripción clínica manual.
- `reports/morphotypes_summary.csv` — 1 fila × noche × morfotipo (n_edos, n_labeled, n_null, n_α/β/γ/δ).
- `reports/morphotypes_batch_gate.json` — batch gate: 560/560 OK, 85 286 EDOs labeled, 0 null, distribución global.
- `reports/morphotypes_dashboard_k3.html` + `morphotypes_dashboard_k4.html` — dashboards standalone (~1.4 MB cada uno, SVG inline).

### Batch completo (560 noches)

- **560/560 OK, 0 FAIL** en **25.1 s** (~45 ms/noche).
- **85 286 EDOs labeled, 0 null** — todos los EDOs del pool tienen features completas.
- Idempotencia: re-correr `apply_morphotypes.py` produce labels idénticos (KMeans.predict es determinístico sobre mismo modelo + mismo input).

### Distribución global de morfotipos (pool completo, 85 286 EDOs)

| morfotipo | n_EDOs | fracción |
|---|---|---|
| α sostenidos | 10 598 | 12.43 % |
| β respuesta motora | 9 930 | 11.64 % |
| γ severos | 3 005 | 3.52 % |
| δ leves | 61 753 | 72.41 % |

Fracción δ mayor en el pool global (72 %) que en el training subset (58 %) porque los marginales `meets_2pct-only` — excluidos del training — son mayoritariamente leves de poca intensidad.

### Composición por `meets_Npct` (training subset)

| morfotipo | meets_2pct | meets_3pct | meets_4pct | meets_5pct |
|---|---|---|---|---|
| α | 100 % | 100 % | 91.5 % | 78.9 % |
| β | 100 % | 100 % | 94.7 % | 85.0 % |
| γ | 100 % | 100 % | 100 % | 99.9 % |
| δ | 100 % | 100 % | 48.6 % | 24.0 % |

γ satura los 4 thresholds (son los severos). δ dropea fuerte por encima de 3 % (leves verdaderos). α y β tienen sensibilidad alta hasta 5 %.

### Verificaciones ejecutadas
- ✅ `tests/test_morphotypes.py`: 20/20 OK.
- ✅ Regresión completa `pytest tests/`: **124/124 OK** (104 previos + 20 nuevos, sin regresión en events/indices/qc/ingest/autoreg/parse_birthdate).
- ✅ Smoke `apply_morphotypes --limit 10`: 10/10 OK, schema validado, columna `morphotype` presente, KV metadata aumentada.
- ✅ Batch completo 560 noches: 560/560 OK, 0 FAIL, 25.1 s.
- ✅ Idempotencia verificada: segunda corrida de `apply_morphotypes` sobre el mismo pool produce labels byte-compatibles (mismo cluster por EDO).
- ✅ Dashboards K=3 y K=4 generados y comparados antes de fijar K=4.

### Idempotencia
- **Contenido**: determinístico — con modelo fijo, labels reproducibles al 100 %.
- **Archivos**: NO byte-idénticos por `morphotyping_applied_at` (ISO timestamp) en KV metadata. Consistente con decisión de trazabilidad de Etapas 2 y 3.

---

## 7. Etapa 4 — scope cerrado, paso 1 hecho

**Estado:** scope decisional aprobado (Q1–Q6), paso 1 (constantes en `config.py`) completado.

### Decisiones Q1–Q6 cerradas (pre-código)

- **Q1 = A** — ventanas fijas, 3 escalas `s=30s / m=5min / l=30min` (ancla PAC histórico).
- **Q2 = A** — ventanas disjuntas, sin overlap (`PAC_WINDOW_OVERLAP = 0.0`).
- **Q3 = C** — features por ventana: 15 signal stats (spo2 × 6 + hr × 6 + mov × 3) + 6 densidades morfotípicas (n_α/β/γ/δ + n_total + IRD local) + 3 de composición de sueño = **24 features** por ventana.
- **Q4 = A** — KMeans unificado sobre las 560 noches (no per-paciente), z-score pooled.
- **Q5 = C** — sweep K ∈ [2..10] por escala, con anclas históricas marcadas en dashboard (S=7, M=6, L=4) para decisión humana informada.
- **Q6 = C** — máscara de training híbrida: entrena sobre ventanas con `frac_wake ≤ 0.5` y `coverage ≥ 0.5`; inferencia sobre TODAS las ventanas.

### Decisión pre-Etapa-4 · Validación del sleep staging del device

**Contexto.** El aparato emite `sleep_stage ∈ {0,1,2,3}` inferido internamente desde HR + movimiento (no PSG). Antes de comprometernos con una codificación semántica, corrimos validación de plausibilidad sobre las 560 noches (script `scripts/analyze_sleep_staging.py`, 5 checks fisiológicos).

**Resultado:** veredicto `REPENSAR` (2/5 señales OK).

| Check | Resultado | ¿Cierra? |
|---|---|---|
| Ciclos REM-NREM: 4–6 por noche, 70–120 min | mediana 10/noche, 28.5 min | ✗ |
| Stage 3 decrece Q1→Q5 (N3 front-loaded) | 0.305 → 0.348 (sube) | ✗ |
| Morfotipos × stage coherentes (γ ↑ en REM) | distribución homogénea | ✗ |
| Arquitectura vs. severidad (tercil ODI) | low: 12% wake, 37% "deep"; high: 22% wake, 29% "deep" | ✓ |
| Estabilidad run-length (<40% runs ≤30s) | 0% short runs en todos los stages | ✓ |

**Lectura.** Las 4 categorías crudas NO son confiables a nivel intra-sueño (ciclos muy fragmentados, N3 no front-loaded, morfotipos no discriminan). El aparato SÍ discrimina bien `sleep vs wake` y correlaciona con severidad apneica.

**Decisión (Roberto, tras proponer 3 mapeos):** **Mapeo B** — colapsar 4 → 3 categorías:

| raw device | categoría colapsada |
|---|---|
| 0 | `wake` |
| 1 | `light_sleep` |
| 2 | `light_sleep` |
| 3 | `deep_sleep` |

**Caveat explícito en `config.py`:** `deep_sleep` es el label del stage 3 del aparato, **NO es N3 clínico AASM**. Se conserva como feature discriminativo empírico para clustering no-supervisado, pero no debe leerse clínicamente. Si el mapeo cambia o aparecen más stages, editar `PAC_SLEEP_STAGE_COLLAPSE_MAP` en `config.py` y re-entrenar toda la pipeline aguas abajo.

**Artefactos versionados:**
- `scripts/analyze_sleep_staging.py` — script idempotente con `--limit N` para re-ejecutar el análisis cuando cambie la cohorte o el criterio.
- `reports/sleep_staging_validation.json` — per-night + pool agregado (560 noches).
- `reports/sleep_staging_validation.md` — reporte con las 5 checks y el veredicto.
- `reports/sleep_staging_validation.html` — dashboard con 4 plots SVG.

### Insumos ya disponibles para Etapa 4

- 560 silver/{NR}.parquet (señales QC-aware, 9 cols).
- 560 events/{NR}_edos.parquet (con `morphotype` ∈ {α, β, γ, δ, None}) + {NR}_edo_curves + {NR}_indices.
- reports/events_indices_pooled.parquet (560 × 104 cols).
- models/edo_morphotype_* — modelo KMeans para morfotipos α/β/γ/δ.
- `src/pac/config.py` — 24 features canónicas, mapping sleep colapsado, umbrales training híbridos.

### Pasos Etapa 4 — TODOS CERRADOS

1. ✅ **Paso 1** — constantes en `config.py` (Q1–Q6 + mapeo sleep).
2. ✅ **Paso 2** — `src/pac/windows.py` helpers puros (ventaneo multiescala s/m/l, signal stats, densidades morfotípicas, composición sleep).
3. ✅ **Paso 3** — `src/pac/states.py` helpers puros (z-score pooled, fit KMeans, predict, sweep K).
4. ✅ **Paso 4** — tests unit (`test_windows.py` + `test_states.py`).
5. ✅ **Paso 5** — `scripts/train_pac_states.py` (trainer + sweep K=2..10) + `scripts/validate_pac_states.py` (post-fit C1-C5 checks).
6. ✅ **Paso 6** — `scripts/dashboard_pac_states.py` (elbow/silhouette + anclas para decisión K).
7. ✅ **Paso 7** — `scripts/apply_pac_states.py` (batch labeling 560 noches).
8. ✅ **Paso 8** — `scripts/qa_pac_states_batch.py` (5 checks B1-B5 + cross-check con silver_qc).
9. ✅ **Paso 8.5** — `scripts/build_stratigraphy_dashboard.py` (5 dashboards Plotly multi-escala + EDOs).

---

## 7bis. Etapa 4 CERRADA — PAC States multi-escala (s/m/l)

**Estado:** 9 pasos cerrados. K final por escala: **s=6, m=8, l=6**. 560/560 noches labeled. Gate apply-QA: `proceed=True` (con 7 noches B2-FAIL conocidas en silver_qc, excluidas del cohorte gold). 189/189 tests verde.

### Pasos 5+6 — Training + decisión de K

- **Sweep K=2..10** por escala sobre 560 noches con máscara training híbrida (`frac_wake≤0.5 AND coverage≥0.5`). KMeans unificado (no per-paciente), `n_init=10`, `random_state=42`, z-score pooled.
- **Decisión de K**: Roberto eligió s=6, m=8, l=6 desde el dashboard `dashboard_pac_states.html` (elbow + silhouette + interpretabilidad clínica). Las anclas históricas (S=7, M=6, L=4) NO se respetaron porque silhouette/elbow apuntaban distinto; el dashboard documenta la decisión.
- **Modelos persistidos** (gitignored los `.pkl`, versionados los `*_centroids.csv`/`*_metadata.json`/`*_zscore.json`): `models/pac_states_{s,m,l}_*.{pkl,csv,json}`.
- **Validación post-fit (`scripts/validate_pac_states.py`)**: 5 checks (C1 escalonado, C3 doble criterio, C4 sleep coherence sin wake, C5 epsilon physiological, otros). Resultado: **PROCEED con 3 WARN** (C1: clusters S5=0.61%, M5=0.35%, L3=0.56% son outliers clínicamente válidos, no artefactos).

### Paso 7 — Apply (`scripts/apply_pac_states.py`)

- **Output schema (15 cols, long-format con 3 escalas stackeadas, 1 parquet por NR)**:
  ```
  night_record_id, scale, window_idx, t_start, t_end, t_start_s, t_end_s,
  state_label, cluster_int, dist_to_centroid, coverage,
  frac_wake, frac_light_sleep, frac_deep_sleep, training_eligible
  ```
- **Decisiones Q1-Q7=A** (Roberto): training_eligible flag persistido, 1 parquet por noche, NaN-drop con cluster=-1, dist_to_centroid persistido, gate check pre-apply, `--force` para re-procesar, sort por (scale, window_idx) para byte-reproducibilidad.
- **CLI**: `--mode {smoke,batch}`, `--limit`, `--force`, `--skip-gate-check`.
- **KV metadata por parquet**: `night_record_id`, `applied_at`, `algorithm_version`, `schema_version`, `k_per_scale`, `source_silver_mtime`, `source_events_mtime`.
- **Run completo**: 560/560 OK · 0 FAIL · 927s wall-clock · `reports/pac_states_apply_report.json`.
- **Drift L1 vs training**: s=5.41%, m=10.75%, l=3.11% → distribuciones estables.
- **Tests**: `tests/test_apply_pac_states.py` 6/6 verde (schema, prefijos, idempotencia, NaN-drop, training_eligible, parquet roundtrip).

### Paso 8 — QA del labeling (`scripts/qa_pac_states_batch.py`)

- **5 checks (B1-B5)**:
  - **B1 schema_lock**: 100% PASS — 560 parquets con OUTPUT_COLS + dtypes correctos.
  - **B2 temporal_coverage**: 7 FAIL · 5 WARN · 548 PASS. Las 7 FAIL son **redundantes con `silver_qc`** (todas tienen `qc_coverage_ok=False` Y `qc_max_gap_ok=False`) → cross-check confirmado, gate downgraded FAIL→WARN.
  - **B3 per_night_cluster_dominance**: 15 noches WARN (>95% un cluster) — noches cortas o muy uniformes.
  - **B4 dist_to_centroid_outliers**: 36 noches WARN (>20% en top-5% global de dist por escala) — candidatas a inspección clínica.
  - **B5 cross_scale_consistency**: PASS — coherencia mean l-vs-m=0.618, l-vs-s=0.544 (régimen *moderado* deseado: las 3 escalas se relacionan pero no son redundantes).
- **Decisiones Q1-Q5=A** (Roberto): B5 incluido, B4 por-escala, CSV per-night persistido, tests sobre check fns, script independiente.
- **Cross-check Q1=A** (post-resultados): si TODAS las B2-FAIL son known-bad en silver_qc, gate baja a PROCEED. Persiste `reports/b2_fail_excluded.json` (7 NRs) para exclusión obligatoria en Etapa 5.
- **Lista B3∪B4 Q2=A**: 44 noches en `reports/pac_states_flag_for_review.csv` para inspección y atención en gold (peso reducido o cohorte separado).
- **Outputs**: `reports/pac_states_apply_qa.{md,json,csv}`, `reports/pac_states_batch_gate.json` con `apply_qa_proceed=true`.
- **Tests**: `tests/test_qa_pac_states_batch.py` 9/9 verde (B1 pass+missing, B2 perfecta+gap, B3 sin/con dominio, B4 frac, B5 homogéneo+diverso).

### Paso 8.5 — Stratigraphy dashboard (`scripts/build_stratigraphy_dashboard.py`)

- **Objetivo (Roberto)**: "ver superpuesto una noche con sus diferentes estados multiescala y los EDOs … inferencias acerca de lo que pasa antes, durante y después de los EDOs."
- **5 noches representativas** (Q4=A, criterios reproducibles con seed=42):

| Tag | NR_id | Criterio |
|---|---|---|
| saos_severo | NR_55d1add2ff | argmax(ahi_3)=60.13, 264 EDOs |
| control | NR_7fe8bdf7e4 | argmin(ahi_3)=2.02 con tst≥5h, 40 EDOs |
| cluster_L3 | NR_75caca4a4e | 4 ventanas L3 (rare cluster outlier) |
| flag_b3_dominance | NR_29462faf4f | dominio l=100% |
| flag_b4_outliers | NR_5fd35bfdca | 19.4% s en top-5% dist |

- **Layout HTML+Plotly (8 filas con `shared_xaxes=True`)**: SpO₂, HR, hipnograma, EDO markers ±2min ctx (Q5=C), state stripes l/m/s coloreadas, morfotipos por EDO (α/β/γ/δ) con tooltips.
- **Decisiones Q1-Q7** (Roberto): Q1=A Plotly interactivo, Q2=B 5 archivos separados, Q3=B tracks completos, Q5=C ±2min context shading, Q6=A `reports/stratigraphy/`, Q7=A persistir `stratigraphy_nights_selected.json` para reproducibilidad.
- **Outputs**: 5 HTML standalones (~5.7 MB total, gitignored, regenerables) + `reports/stratigraphy_nights_selected.json` (versionado).

### Verificaciones ejecutadas

- ✅ `pytest`: **189/189 OK** (15 nuevos: 6 apply + 9 QA, sin regresión).
- ✅ Smoke `apply_pac_states --mode smoke --limit 10` y `qa --limit 10`: ambos OK antes de batch.
- ✅ Batch `apply` 560 noches: 560/560 OK, 0 FAIL, 927s.
- ✅ Batch `QA`: 49.6s, gate PROCEED tras cross-check con silver_qc.
- ✅ Idempotencia: re-correr `apply` con `--force` produce DataFrames byte-idénticos por sort (scale, window_idx).
- ✅ Gates encadenados: `validation_proceed=true` → `apply_qa_proceed=true`.

### Idempotencia y regenerabilidad

- **States parquets**: contenido determinístico con modelo fijo. Archivos NO byte-idénticos por `applied_at` ISO timestamp en KV metadata (consistente con Etapas 2-3).
- **Stratigraphy HTMLs**: regenerables al 100% desde `seed=42` + selection JSON + las fuentes (silver/events/states).

### Outputs estructurales (ubicaciones canónicas)

- `states/<NR>.parquet` — 560 archivos, ~26 MB total (gitignored, regenerables).
- `models/pac_states_{s,m,l}_*.{pkl,csv,json}` — 3 modelos, centroides, z-params.
- `reports/pac_states_*.{md,json,csv}` — sweep, training, validation, apply, apply_qa, batch_gate, b2_fail_excluded, flag_for_review (versionados como excepciones).
- `reports/stratigraphy/<NR>__<tag>.html` — 5 dashboards (gitignored).
- `reports/stratigraphy_nights_selected.json` — selección reproducible (versionado).

### Insumos disponibles para Etapa 5 (Gold)

- 560 silver + 560 events + 560 states + reports/events_indices_pooled (560 × 112 cols) + 3 modelos PAC.
- **Lista de exclusión obligatoria**: `reports/b2_fail_excluded.json` (7 NRs).
- **Lista de atención** (peso reducido o cohorte separado): `reports/pac_states_flag_for_review.csv` (44 NRs).
- **Cohorte efectivo recomendado para gold**: 560 - 7 = **553 noches**.

---

## 7ter. Etapa 4.6 CERRADA — Pre-Gold hardening (lock + schemas + cohortes + manifest + retrain gateway)

**Estado:** 6 piezas cerradas. Suite de tests **214/214 OK** (25 nuevos en 4.6, sin regresión sobre Etapa 4). `models/MANIFEST.json` v1 generado y versionado (git_sha=`e318cfa76165`, n_state_files=560, n_patients=12).

### Pieza A — Lock de dependencias

- `requirements.txt` reorganizado en secciones (Core / Data IO / Plotting / Tests) con rangos `>=,<` (numpy, pandas, scikit-learn, plotly, matplotlib, seaborn, pytest).
- `scripts/freeze_lock.sh` (executable): `pip freeze | sort -f` con header (timestamp ISO, Python ver, venv path) → `requirements.lock.txt`. Sanity-check de `VIRTUAL_ENV`.

### Pieza B — Schema validation (`src/pac/schemas.py`)

- `SchemaError`, `_canonical_kind` (tolera int8/16/32/64→"int", float32/64→"float").
- 5 schemas declarativos: `BRONZE_SCHEMA` (5 cols), `SILVER_SCHEMA` (9), `EVENTS_EDOS_SCHEMA` (25), `EVENTS_CURVES_SCHEMA` (5 list-typed), `STATES_SCHEMA` (15).
- 5 validadores: `validate_bronze`, `validate_silver`, `validate_events_edos`, `validate_events_curves`, `validate_states`. Firma común `(df, source, strict=True, allow_extras=True) → ValidationResult`.
- `strict=True` raise; `strict=False` emite `UserWarning` y devuelve `ok=False`.
- Helpers públicos: `list_layers()`, `get_schema(layer)`.
- Smoke contra archivos reales: 5/5 OK.

### Pieza C — Cohort helpers (`src/pac/cohorts.py`)

5 cohortes públicas (sets, no listas):

| cohorte | n |
|---|---|
| `get_cohort_all()` | 560 |
| `get_cohort_quality()` | 553 |
| `get_cohort_strict()` | 511 |
| `get_cohort_high_tst(min_tst_h=4.0)` | 499 |
| `get_cohort_with_clinical()` | 553 |

`cohort_summary() → dict`, `snapshot_cohort(name, nrs, output_path)` para reproducibilidad. Cada I/O helper con `lru_cache(maxsize=1)`. `clear_cache()` para forzar refresh tras cambios en disk.

### Pieza D — Model manifest (`scripts/generate_manifest.py` → `models/MANIFEST.json`)

Fuente única de verdad. Bloques: `morphotypes`, `pac_states_s`, `pac_states_m`, `pac_states_l` con `k`, `n_training`, `feature_cols`, `training_mask`, `labels`, `centroids_path`, `centroids_sha256_short` (16-char), `kmeans_pkl_sha256_short`, etc. Más `corpus_snapshot` (n_state_files, n_patients, cohort_sizes), `exclusion_lists` (b2_fail + flag_for_review con políticas), `retrain_policy` (umbrales 100 noches / 10 pacientes).

CLI: `--bump v2` (post-reentreno), `--force` (regenerar misma versión). v1 actual generada y commiteada.

### Pieza E — Retrain gateway (`scripts/retrain_check.py`)

Compara inventario actual vs `corpus_snapshot` del manifest. Si supera umbrales, prompt `[y/N]` (no asume). CLI: `--threshold-nights`, `--threshold-patients`, `--json` (CI), `--auto-yes`, `--dry-run`. Si user acepta, orquesta 6 pasos vía subprocess con `PYTHONPATH=src` (train_morphotypes → train_pac_states → validate → apply_morphotypes → apply_pac_states batch → qa_pac_states_batch). **NO bumpea manifest** — el user lo hace manual con `generate_manifest.py --bump v2` cuando está conforme con resultados.

### Pieza F — Tests + docs

- `tests/test_schemas.py` (15 tests): happy-path (5) + missing cols (2) + wrong dtype (2) + extras y dtype subtypes (3) + helpers públicos (3).
- `tests/test_cohorts.py` (10 tests): invariantes de inclusión (5: strict⊆quality⊆all, high_tst monotone), `cohort_summary` (3), `snapshot_cohort` (2).
- Suite total: **214/214 OK**.

### Verificaciones ejecutadas

- ✅ `freeze_lock.sh` ejecutado en venv → `requirements.lock.txt` generado.
- ✅ 5 validadores ejecutados sobre archivos reales del corpus → todos OK, 0 extras inesperados.
- ✅ `cohort_summary()` produce {all:560, quality:553, strict:511, high_tst_4h:499, with_clinical:553, b2_fail_excluded:7, flag_for_review:44}.
- ✅ `MANIFEST.json` v1 con SHA256 truncados de cada centroide.
- ✅ `retrain_check.py --json` y modo humano: delta=0 → no sugiere retrain.
- ✅ `pytest`: **214/214 OK**.

### Outputs estructurales (nuevos en 4.6)

- `requirements.txt` reorganizado + `requirements.lock.txt` (gitignored).
- `scripts/freeze_lock.sh` (versionado).
- `src/pac/schemas.py`, `src/pac/cohorts.py` (versionados).
- `scripts/generate_manifest.py`, `scripts/retrain_check.py` (versionados).
- `models/MANIFEST.json` (**versionado** — fuente de verdad de v_actual).
- `tests/test_schemas.py`, `tests/test_cohorts.py` (versionados).

### Para Gold (Etapa 5) — qué cambia

- **Cohorte oficial**: usar `get_cohort_quality()` (553 NRs) como default; reportar también `get_cohort_strict()` (511) en análisis sensibles a calidad.
- **Versión de modelo**: cada noche en gold incluye `model_version="v1"` (leído del manifest) → trazabilidad completa cuando exista v2.
- **Validación en bordes**: cada paso de Gold valida sus inputs/outputs con `validate_<layer>()`.
- **Snapshot de cohorte por análisis**: `snapshot_cohort('thesis_main', get_cohort_quality(), 'analyses/thesis_main_cohort.json')`.

---

## 7quater. Etapa 5 CERRADA — Gold (data lake unificado APNEA + PAC)

**Estado:** 8 pasos cerrados. **5 tablas Gold materializadas + 2 sidecars versionados**. Suite **328/328 OK** (78 nuevos en Etapa 5, sin regresión sobre 4.6). Pipeline orquestado end-to-end vía `scripts/build_gold_all.py`.

### Filosofía consensuada

Roberto: *"una clusterización no es más que una segmentación en el fondo arbitraria... Evento, noche y paciente deben ser exhaustivos en datos bien caracterizados."* Gold es **data lake** — preserva TODO lo medido (forma cruda + labels de modelo + distribuciones + cross-night + flags), no solo el output del clustering.

### Las 5 tablas Gold

| tabla | filas × cols | tamaño | grano |
|---|---|---|---|
| `gold/events.parquet` | 85,286 × 32 | 3.4 MB | 1 fila × EDO |
| `gold/events_curves.parquet` | 85,286 × 5 | 8.6 MB | 1 fila × EDO (3 listas pre/durante/post) |
| `gold/states.parquet` | 518,867 × 22 | 15.1 MB | 1 fila × ventana × escala × noche |
| `gold/nights.parquet` | 560 × 146 | 0.55 MB | 1 fila × noche (tabla principal) |
| `gold/patients.parquet` | 12 × 71 | 49 KB | 1 fila × paciente (descriptiva) |

### Decisiones arquitecturales clave

- **Cohorte B**: todas 560 noches con flags (`in_quality`, `in_strict`, `in_high_tst`, `flag_for_review`, `b2_fail`). Filtrado downstream con `pac.cohorts`.
- **Cross-night `_pct_corpus`** computadas SOBRE `in_quality=True` (553) como referencia, aplicadas a todas las filas — previene contaminación de percentiles.
- **Cross-night `_vs_baseline_patient`**: leave-one-out sobre noches quality del paciente (≥3 noches, 11 de 12 pacientes elegibles).
- **NO state-context en events_gold** — reconstruible vía join `events_gold × states_gold` cuando se necesite.
- **`gold/<tabla>.parquet`** sin sufijo `_gold` (la carpeta ya dice "gold").
- **events_curves SIN flags** — se accede joineada a events_gold (duplicar es ruido).

### Estructura de `nights_gold` (146 cols)

- Identidad (3) + flags (5).
- Índices clásicos (104) de `events/{NR}_indices.parquet`: TST, WASO, T90/88/85, AHI/ODI 2/3/4/5%, hypoxic burden, comparaciones pac_v2 vs device.
- Distribución morfotipos (4): `frac_morpho_α/β/γ/δ`.
- Distribución PAC states (20): `frac_state_s_S0..S5` + `frac_state_m_M0..M7` + `frac_state_l_L0..L5`.
- Transición/entropía (6): `n_transitions_state_{s,m,l}` + `entropy_state_{s,m,l}` (Shannon en bits).
- Cross-night cohort (3): `*_pct_corpus` para ahi_3, t90_frac, odi_3.
- Cross-night patient (3): `delta_*_vs_baseline_patient` para los mismos.

### Estructura de `patients_gold` (71 cols, 12 filas)

Demografía (7) + counts (5) + agregados mean/median/sd de 10 métricas (30) + distribuciones morfotipo y PAC state ponderadas por EDOs/ventanas (24) + estabilidad CV intra-paciente (3) + identidad (2). **Vista descriptiva** — n=12 no permite inferencia.

### Sidecars (versionados en git)

- **`gold/MANIFEST.json`**: model_version, git_sha, sha256 + n_rows + n_cols por tabla, build_order, cohort_policy. Generado por `scripts/build_gold_manifest.py`.
- **`gold/nights_columns.json`**: diccionario de datos de las 146 cols clasificadas en 5 kinds (`identity`/`flag`/`single_night`/`cross_night_corpus`/`cross_night_patient`). 100% cubiertas por descripciones híbridas (auto + override CSV opcional). Generado por `scripts/build_nights_columns_doc.py`.
- **`gold/nights_columns_descriptions.csv`** (opcional): override manual de descripciones por nombre.

### Verificaciones ejecutadas

- ✅ `pytest`: **328/328 OK** (78 nuevos: 14 schemas + 13 events + 7 events_curves + 15 states + 26 nights + 24 patients + 15 sidecars + 1 viejo actualizado).
- ✅ `build_gold_all.py` end-to-end: 5 tablas + 2 sidecars en orden, sin errores.
- ✅ Distribuciones suman 1.0 exacto en TODAS las tablas (morfotipos y cada escala de PAC states, tanto en nights_gold como en patients_gold ponderado).
- ✅ Cross-night invariantes: `ahi_3_pct_corpus` uniforme [0,1] sobre quality (mean=0.500), `delta_ahi_3_vs_baseline_patient` centrado en 0 (mean=-0.000).
- ✅ Coherencia entre tablas: 12 user_ids únicos en patients_gold ⊆ nights_gold ⊆ events_gold.
- ✅ Heterogeneidad clínica clara: AHI3 paciente ∈ [2.7 (sano), 41.0 (severo)], n_nights_quality ∈ [2, 116], CV intra-paciente ∈ [0.11, 0.72].

### Outputs estructurales (ubicaciones canónicas)

- `gold/<tabla>.parquet` × 5 (gitignored, regenerables).
- `gold/MANIFEST.json` + `gold/nights_columns.json` (**versionados**).
- `scripts/build_*_gold.py` × 5 + `scripts/build_gold_manifest.py` + `scripts/build_nights_columns_doc.py` + `scripts/build_gold_all.py` (orquestador).
- `tests/test_gold_*.py` (5 archivos).
- `src/pac/schemas.py` ampliado con 5 GOLD_*_SCHEMA + 5 validators.

### Insumos disponibles para Etapa 6 (orquestador incremental) y futuro análisis

- 5 tablas Gold consolidadas con trazabilidad completa.
- Cohorte oficial `get_cohort_quality()` (553 NRs) declarado en docs.
- `gold/MANIFEST.json` con SHA256 + counts por tabla.
- `gold/nights_columns.json` con clasificación single_night vs cross_night → contrato de salida para la app futura (single_night = lo que la app puede emitir desde un xlsx aislado).
- Validadores `validate_*_gold()` ready-to-use.

### Comandos de regeneración (PYTHONPATH=src en todos)

```
# Pipeline completo (recomendado):
python scripts/build_gold_all.py
# Pasos individuales:
python scripts/build_events_gold.py
python scripts/build_events_curves_gold.py
python scripts/build_states_gold.py
python scripts/build_nights_gold.py
python scripts/build_patients_gold.py
python scripts/build_gold_manifest.py
python scripts/build_nights_columns_doc.py
# Tests:
python -m pytest
```

---

## 7quinquies. Etapa 6 CERRADA — Orquestador incremental (staleness por mtime)

**Estado:** 3 pasos cerrados. **Suite 350/350 OK** (22 nuevos en Etapa 6, sin regresión). Orquestador detecta staleness y ejecuta pipeline mínimo automáticamente.

### El problema que resuelve

Antes había que recordar el orden y disparar manualmente: `silver → events_pipeline → apply_morphotypes → apply_pac_states → build_gold_all`. Si reentrenabas un modelo, manualmente acordarte de regenerar todo downstream. Riesgo de error humano alto.

### Decisiones consensuadas

- **P1 — mtime puro** (no SHA256): rápido, suficiente porque "los archivos llegan tal como vienen".
- **P2 — A** auto-invalidación por modelo: el reentrenamiento toca `models/*` mtimes → detecta automáticamente.
- **P3 — Híbrido** (incluido en docs): un script con sub-comandos `status`/`plan`/`run` + default sensato sin sub-comando = `run` interactivo.
- **P4 — Triple criterio para gold**: data + scripts + MANIFEST.
- **P5 — No ingiere xlsx nuevos**: correr `run_bronze.py` antes.

### Componentes

- **`src/pac/orchestrator.py`** (~340 líneas): biblioteca pura sin side-effects. Define etapas, detecta staleness por mtime, arma plan con propagación downstream. Filtrado estricto de NRs (regex `^NR_[0-9a-f]{10}\.parquet$`) para no contar `_qc.parquet`/`_edos.parquet` como NRs.
- **`scripts/orchestrate.py`** (CLI híbrido): `status`/`plan`/`run` + default = `run` interactivo. `--yes` para CI, `--dry-run`, `--quiet`.

### CLI híbrido — cheatsheet

```
orchestrate                   # default = run interactivo (lee plan, pregunta y/N)
orchestrate status            # solo inventario, exit 1 si stale
orchestrate status -v         # con detalle de NRs stale
orchestrate plan              # status + plan, no ejecuta
orchestrate run               # ejecuta tras prompt
orchestrate run --yes         # auto-confirm (CI)
orchestrate run --dry-run     # alias de plan
```

### Pipeline modelado (4 etapas, 5 comandos)

| etapa | comando(s) |
|---|---|
| silver | `python -m pac.silver` |
| events | `python -m pac.events_pipeline` + `python scripts/apply_morphotypes.py` |
| states | `python scripts/apply_pac_states.py --mode batch` |
| gold | `python scripts/build_gold_all.py --quiet` |

events tiene 2 sub-pasos: el pipeline genera EDOs sin morfotipo, apply_morphotypes agrega la columna después.

### Reglas de detección

| etapa stale si... |
|---|
| **silver** | bronze más nuevo que silver, o silver missing |
| **events** | silver más nuevo que events, o `models/edo_morphotype_*` mtime > events |
| **states** | events más nuevo que states, o `models/pac_states_*` mtime > states |
| **gold** | falta tabla, o (events ∪ states ∪ build_*_gold.py ∪ MANIFEST) mtime > tabla más vieja |

**Propagación**: si silver stale → plan incluye silver+events+states+gold (re-correr upstream invalida todos los mtimes downstream).

### Limitación conocida

`silver` y `events_pipeline` son **batch-full** (procesan 560 NRs siempre, no aceptan filtro per-NR). El orquestador detecta stale por NR (útil para diagnóstico) pero al ejecutar corre el script entero. Mejora futura: agregar `--only-stale NR1,NR2` a esos scripts para ejecución quirúrgica.

### Tests

`tests/test_orchestrator.py` (22 tests): 100% determinísticos sobre `tmp_path` con monkeypatch. Cobertura: filtrado estricto de NRs (4), pipeline limpio (2), detección por etapa (9), propagación de plan (3), render (4).

### Verificaciones

- ✅ `pytest`: **350/350 OK**.
- ✅ Smoke `orchestrate status` sobre corpus real: detecta stale correctamente tras runs accidentales.
- ✅ Filtrado de NRs: silver/ con 1120 archivos cuenta correctamente 560 NRs.
- ✅ Propagación: silver stale → plan de 5 pasos.

### Comandos típicos

```
# ¿Está todo al día?
python scripts/orchestrate.py status

# ¿Qué harías?
python scripts/orchestrate.py plan

# Hacelo (interactivo):
python scripts/orchestrate.py

# Hacelo (CI):
python scripts/orchestrate.py run --yes
```

---

## 7sexies. Etapa 7 CERRADA — Validación final + release v1.0-tesis

**Estado:** 6 piezas cerradas. **Suite 350/350 OK**. Tag `v1.0-tesis` creado. Release de defensa de tesis completo.

### Decisiones (Roberto)

- Q1 (alcance): A — solo defensa, no GitHub público. C posible después.
- Q2 (opcionales): 7 (lint) y 8 (lock) SÍ. 9 (reporte ejecutivo) y 10 (stub app) no en v1.0.
- Q3 (tag): `v1.0-tesis`.
- Q4 (README): español.
- Q5 (e2e): Claude la primera, Roberto confirma comandos en su entorno.

### Piezas

- **A** Full e2e + audit: gold pipeline 27.8s, 350/350 tests OK distribuidos en 21 archivos sobre 15 módulos.
- **B** Revisión de `PAC_v2_ANALISIS.md` (692 → 1124 líneas): grafo Mermaid del pipeline + joins + cohortes (§0 nueva), refactor de §2.1/§3.1/§3.2/§4.1 con tablas "presente HOY vs derivar", §5.1 aclarada (cruce via join temporal), §7.5 nueva (uso correcto cross-night), §8 marcada post-tesis, bitácora con 4 entradas nuevas.
- **C** `README.md` (reescrito en español, reemplaza el de Etapa 0) + `CHANGELOG.md` (one-liner por etapa, agrupados por release).
- **D** Lint: ruff aplicó 66 fixes auto, 41 residuales cosméticos aceptados. Lock: `scripts/freeze_lock.sh` con sanity-check `VIRTUAL_ENV` (Roberto regenera desde su venv).
- **E** Audit: 0 TODOs reales en src/scripts. `*.html` y `.Rhistory` agregados a `.gitignore`.
- **F** Cierre: docs ETAPAS+HANDOFF + commit + tag.

### Cómo retomar post-tesis

```
git log --oneline v1.0-tesis | head -20    # commits hasta el release
python scripts/orchestrate.py status       # ¿al día?
cat README.md                              # punto de entrada
cat PAC_v2_ANALISIS.md                     # plan analítico (base de la tesis)
```

### Limitaciones conocidas (documentadas para post-tesis)

1. silver/events_pipeline son batch-full — el orquestador detecta stale por NR pero ejecuta full. Mejora: agregar `--only-stale` a esos scripts.
2. App diferida — contrato técnico en `gold/nights_columns.json` (cols `single_night` vs `cross_night`).
3. Features extendidas del EDO (asymmetry, lag_autonomic) NO en Gold v1 — derivar on-the-fly cuando se necesiten.
4. Edad no en `patients_gold` — requiere PII (registry local).

**Estado de defensa de tesis: ✅ LISTO**

---

## 7septies. Etapa 6.1 CERRADA — Hardening del orquestador (SHA modelo)

**Estado:** 3 piezas cerradas. **Suite 354/354 OK** (4 nuevos tests). Tag `v1.1-tesis`. Resuelve el falso positivo "states STALE" que aparecía después de cada lote nuevo de noches.

### Problema

La heurística mtime original era conservadora: cuando `apply_morphotypes` reescribía `events/*.parquet` solo para agregar la columna `morphotype`, todos los `states/*.parquet` quedaban con mtime viejo y el orquestador los marcaba stale, aunque eran funcionalmente válidos (apply_pac_states usa las 24 features de geometría/IRD, NO morphotype).

### Decisión Roberto

Q1=B (touch + SHA modelo), Q2=no extender a events, Q3=etapa 6.1 + tag v1.1-tesis.

### Cambios

- **`apply_pac_states.py`**: SHA256 de los 3 centroides PAC persistido en KV de cada `states/*.parquet`. Skip-if-exists ampliado a 4 casos: SHA igual → touch+skip; SHA difiere → re-procesar; SHA ausente (pre-6.1) → REHIDRATAR (lectura/escritura barata, segundos para 560 noches); NR sin states → procesar.
- **`orchestrator.py:detect_states_stale()`**: SHA-aware. Compara SHA persistido vs actual; si igual → vigente (ignora mtime); si difiere → stale por modelo; si ausente o falta modelo → fallback mtime.
- **Tests**: 1 viejo adaptado + 4 nuevos (`TestStatesStaleByShaModel`).

### Smoke en sandbox

- `apply_pac_states --mode batch`: rehidrató 560 noches en segundos.
- `orchestrate status`: states pasó de STALE (560/560) a OK (560).
- `orchestrate run --yes`: solo regeneró gold (26.4s). Final: ✓ Todo up-to-date.

### Beneficio

Cada lote nuevo a futuro: el orquestador queda "honesto" — solo marca stale lo que realmente cambió. Si reentrenás, el SHA del modelo cambia automáticamente y todos los states viejos quedan stale legítimamente.

**Tag**: `v1.1-tesis` (compatible con v1.0-tesis para análisis).
