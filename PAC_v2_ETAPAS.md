# PAC_v2 — Bitácora descriptiva por etapa

> Documento vivo. Se **agrega** (no se re-escribe) al cerrar cada etapa del pipeline.
> Complementa a `README.md` (setup/uso) y `PAC_v2_HANDOFF.md` (tracker operativo por sesión).
> Propósito: permitir evaluación a fondo de cada etapa cuando ya haya pasado tiempo desde su cierre —
> incluye inputs, procesos, objetivos, decisiones, outputs, resultados, verificaciones y apéndices
> útiles para la tesis.

**Autor:** Roberto Inza — Maestría en Data Science, Universidad Austral
**Proyecto:** PAC_v2 (consolidación APNEA + PAC en un solo pipeline)
**Última actualización:** 2026-04-22 (cierre de Etapa 2)

---

## Índice

- [Preámbulo — Contexto del proyecto](#preámbulo--contexto-del-proyecto)
- [Etapa 0 — Scaffold, configuración, identidad](#etapa-0--scaffold-configuración-identidad)
- [Etapa 1 — Bronze (ingest `.xlsx` → parquet)](#etapa-1--bronze-ingest-xlsx--parquet)
- [Etapa 1.1 — Auto-registro de pacientes nuevos](#etapa-11--auto-registro-de-pacientes-nuevos)
- [Etapa 2 — Silver (QC por noche)](#etapa-2--silver-qc-por-noche)
- [Apéndice general — Convenciones transversales](#apéndice-general--convenciones-transversales)
- [Etapa 3 — Events (EDOs, IRD e índices nocturnos)](#etapa-3--events-edos-ird-e-índices-nocturnos)
- [Etapa 3b — EDO Morphotyping (KMeans unsupervised)](#etapa-3b--edo-morphotyping-kmeans-unsupervised)

---

## Preámbulo — Contexto del proyecto

### 1. Introducción

PAC_v2 es el **rediseño desde cero** del pipeline de tesis de Roberto Inza.
Consolida dos pipelines viejos que convivían en paralelo:

- **APNEA** — detección de eventos respiratorios (apneas, desaturaciones, movimientos).
- **PAC** — estados dinámicos continuos (ventanas multiescala, clustering de estados).

Ambos trabajaban sobre la misma materia prima (polisomnografía nocturna de 1 Hz) pero
generaban sus propios ingests, sus propios agregados y sus propios archivos de salida.
La consolidación busca: un solo ingest, un solo gold, una sola historia reproducible.

Esta bitácora existe para que, cuando Roberto vuelva a leer el proyecto meses o años
después (o cualquier revisor de tesis), pueda reconstruir **por qué se tomó cada
decisión, con qué evidencia y qué se descartó en el camino**.

### 2. Objetivos pautados (proyecto global)

1. **Eliminar redundancias** del código viejo: crosswalks, dobles agregaciones,
   timelines symmetric-redundant, mappings paralelos de identidad.
2. **Simplificar ingest incremental**: agregar una noche nueva (`.xlsx`) debe requerir
   un solo comando, sin re-procesar todo.
3. **Minimizar archivos de salida**: la tesis evalúa ML y conclusiones clínicas,
   no ingeniería de software. Menos archivos = menos deuda conceptual.
4. **Gold unificado APNEA + PAC**: un único conjunto de tablas `nights_gold`,
   `events_gold`, `patients_gold` que cubra ambas aproximaciones.
5. **Trazabilidad plena**: cada parquet lleva metadata KV (source file, sha256,
   timestamps, versiones de pipeline).

### 3. Cohorte

12 pacientes, 560 noches únicas post-deduplicación (rango 2 a 117 noches por
paciente). Desbalance muy marcado (paciente 336 concentra 117 noches; pacientes
622 y 689 tienen 2 y 3 respectivamente). Este desbalance es un dato para la tesis:
el análisis debe estratificar o ponderar por paciente.

Distribución de noches por paciente al cierre de Etapa 1:

| user_id | nights | user_id | nights |
|:--:|:--:|:--:|:--:|
| 175 | 29 | 336 | 117 |
| 240 | 28 | 622 | 2 |
| 309 | 65 | 656 | 106 |
| 314 | 11 | 683 | 75 |
| 321 | 109 | 687 | 9 |
| 688 | 6 | 689 | 3 |

Total: **560 noches** (~3960 h de señal ≈ 165 días).

### 4. Arquitectura (medallion con 4 zonas)

```
raw/       .xlsx originales de cada noche (no versionado, local)
bronze/    .parquet por noche con señales canónicas + metadata KV
silver/    .parquet por noche con QC-aware signals + métricas QC
gold/      .csv consolidados (nights / events / patients) — Etapa 5
```

**Señales canónicas** (únicas que se conservan del xlsx): `timestamp`, `spo2`, `hr`,
`mov`, `sleep_stage`. Todo lo demás del xlsx se descarta explícitamente.

### 5. Stack técnico

- Python 3.10+
- pandas, numpy
- pyarrow (parquet + metadata KV a nivel de schema)
- openpyxl (xlsx read)
- scikit-learn (clustering en Etapa 4)
- pytest (suite de tests unitarios y de integración)

### 6. Roadmap — 7 etapas

| Etapa | Nombre | Estado |
|---|---|---|
| 0 | Scaffold + config + identidad + hygiene | ✅ CERRADA |
| 1 | Bronze (ingest `.xlsx` → parquet + NightRecordID) | ✅ CERRADA |
| 1.1 | Auto-registro de pacientes nuevos | ✅ CERRADA |
| 2 | Silver (QC por noche) | ✅ CERRADA |
| 3 | Events (EDOs, IRD, índices clásicos) | pendiente |
| 4 | Windows multiescala + estados (KMeans) | pendiente |
| 5 | Gold unificado (nights, events, patients) | pendiente |
| 6 | Orchestrator incremental (staleness por mtime) | pendiente |
| 7 | Validación final + release | pendiente |

**Regla transversal del workflow:** para cada etapa, primero se define scope y se
aprueba explícitamente con Roberto, recién después se escribe código.

---

## Etapa 0 — Scaffold, configuración, identidad

### 1. Introducción

Etapa fundacional. Crea el esqueleto del repo, las convenciones de
configuración y el modelo de identidad pseudonimizada de pacientes.
No procesa ninguna señal todavía, pero establece todos los contratos
(columnas, nombres de archivos, convenciones de git) que las etapas
posteriores deben respetar.

### 2. Objetivos pautados

- Dejar listo el scaffold de directorios y módulos.
- Definir el **contrato de columnas** para los 3 artefactos de identidad.
- Cargar una cohorte inicial auditada de 12 pacientes desde un CSV de origen
  one-shot.
- Implementar helpers de parseo de fechas (dd/mm/yy con pivot) y de I/O
  de parquet con metadata KV.
- Dejar git inicializado con un commit baseline.

### 3. Inputs

- **CSV de origen** (`datos_paciente.csv`, one-shot): dump del sistema del
  laboratorio con nombre, apellido, fecha de nacimiento en dd/mm/yy,
  datos clínicos. **No se conserva en el repo**: se usa sólo para el
  bootstrap y después se descarta.
- Decisión de cohorte inicial: 12 pacientes con al menos una noche disponible
  en raw/.

### 4. Procesos

1. Crear scaffold de directorios (`raw/`, `bronze/`, `silver/`, `gold/`,
   `patients/`, `reports/`, `src/pac/`, `scripts/`, `tests/`).
2. Escribir `config.py` con paths absolutos derivados de `PROJECT_ROOT`,
   nombres de columnas canónicas y constantes de parseo (`YEAR_PIVOT=25`,
   `CSV_SEP=";"`).
3. Implementar `io.py` con:
   - `parse_birthdate(s)` — dd/mm/yy con pivot; WARNING a consola si el año
     resuelto es ≥ 2000 (auditoría humana).
   - Helpers de lectura/escritura de parquet con metadata KV.
   - Lectura/escritura de los dos CSVs de identidad con separador `;`.
4. Bootstrap one-shot (`scripts/bootstrap_patient_files.py`): parsea el
   CSV de origen, genera `patient_registry.csv` (con PII) y `clinical.csv`
   (sin PII).
5. Escribir `run.py` — stub que valida la consistencia entre registry y
   clinical (misma cantidad de filas, mismos `patient_id`).
6. Inicializar git y hacer commit baseline.

### 5. Decisiones de diseño

**D0.1 — Modelo de identidad con 2 archivos, no 3.**
Se evaluó un tercer archivo `source_exam_map.csv` (mapping
`source_exam_id → patient_id`) y se descartó: esa información vive
implícita en los xlsx (campo `user_id` del bloque 1 de metadata) y
se persiste luego como KV en cada parquet bronze. El tercer archivo
sería un cache redundante con riesgo de desincronización.

**D0.2 — Separador `;` uniforme.**
Los nombres en la cohorte tienen comas (apellidos compuestos). Usar `;`
evita cualquier ambigüedad de parseo sin necesidad de quoting.

**D0.3 — `patient_registry.csv` local, `clinical.csv` versionado.**
El registry tiene PII (nombre, apellido, fecha de nacimiento) y queda
gitignored. El clinical sólo tiene campos estructurados sin identificación
personal y se versiona. Consecuencia: cualquier clone fresco del repo
necesita el registry localmente, pero el clinical viaja con el código.

**D0.4 — Fechas con pivot `yy ≤ 25 → 20yy`.**
El CSV de origen viene con formato dd/mm/yy ambiguo. Roberto validó que
todos los nacimientos reales son previos a 1960 excepto uno (paciente 687,
nacido 2009). El pivot en 25 cubre la cohorte actual y próximas décadas.
Se imprime WARNING a consola para cualquier año resuelto ≥ 2000: auditoría
humana garantizada sin persistir flags en archivo (over-engineering).

**D0.5 — Columnas descartadas en bootstrap.**
- `edad`: vacía en origen; se re-computa dinámicamente por noche
  (fecha de nacimiento + timestamp de la noche).
- `fumador`: sin datos en origen; se elimina del contrato.
- `fecha_nacimiento_flag_audit`: flag que se propuso persistir en
  archivo → rechazado como over-engineering (WARNING a consola alcanza).

**D0.6 — Constantes planas en `config.py`, no clases.**
No se instancia ningún `Config()` object. `config.py` es un módulo con
constantes y dos helpers (`ensure_dirs`, `as_dict`). Simplicidad > patrones.

### 6. Outputs

```
PAC_v2/
├── raw/ bronze/ silver/ gold/ reports/   (vacíos, .gitkeep)
├── patients/
│   ├── patient_registry.csv              (12 filas, PII, gitignored)
│   └── clinical.csv                      (12 filas, 8 cols, versionado)
├── src/pac/
│   ├── __init__.py
│   ├── config.py                         (paths + contrato + constantes)
│   └── io.py                             (parse_birthdate, parquet, CSVs)
├── scripts/
│   ├── bootstrap_patient_files.py        (one-shot)
│   └── git_init_etapa_0.sh
├── tests/
│   ├── __init__.py
│   └── test_parse_birthdate.py           (12 casos)
├── run.py                                (stub de validación)
├── requirements.txt
├── README.md
└── .gitignore
```

**Contrato `patient_registry.csv`:**
`patient_id;nombre;apellido;fecha_nacimiento`

**Contrato `clinical.csv`:**
`patient_id;sexo;peso_kg;talla_cm;apnea_prev;diabetes;hta;marcapasos`

### 7. Resultados obtenidos

Cohorte inicial (auditada manualmente por Roberto):

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

Notas auditadas:
- Salvador Martinez (687), nacido 2009 → confirmado manualmente. No es error.
- Andred Ocampo (622) → nombre no habitual, pero confirmado contra el sistema
  del laboratorio.
- Cohorte fuertemente masculina (11/12) y con edad concentrada en 60+ salvo
  el caso 687. Dato para sesgo demográfico de la tesis.

### 8. Verificaciones

- ✅ **Idempotencia del bootstrap**: dos corridas independientes producen
  el mismo SHA256 para registry y clinical.
- ✅ **Tests `parse_birthdate`**: 12/12 casos (pivot 25/26, cohorte real,
  4 dígitos, inválidos).
- ✅ **`run.py`**: PASSED. 12 pacientes consistentes entre registry y clinical
  (mismos IDs, mismo count).
- ✅ **Git baseline**: commit `31a2c50` — "Initial: Etapa 0 CERRADA + Etapa 1 WIP".

### 9. Conclusión

La Etapa 0 dejó el proyecto con un contrato de identidad cerrado y
auditado y con un scaffold que no se ha vuelto a tocar en las etapas
siguientes. La decisión de ir con **2 archivos en vez de 3** (descartar
`source_exam_map.csv`) se validó en la Etapa 1: el `user_id` del bloque 1
del xlsx es estable y suficiente para enlazar ingesta con identidad,
sin introducir un archivo de mapeo adicional.

Queda abierto: la integración Pacientes↔Silver/Gold no necesita identidad
(Silver no lee clinical.csv, ver Etapa 2). Clinical se leerá recién en Etapa 3
(Events) y en Etapa 5 (Gold).

### 10. Apéndices

**Reglas de `.gitignore`:**
- `raw/*.xlsx`, `bronze/*.parquet`, `silver/*.parquet`, `gold/*.csv`
  — artefactos derivados no viajan.
- `patients/patient_registry.csv` — PII local.
- `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`.

**Path actual del proyecto:**
`/Users/ri1965/Proyectos/PAC_v2` (movido fuera de `~/Documents/` para evitar
bloqueos de TCC en macOS).

---

## Etapa 1 — Bronze (ingest `.xlsx` → parquet)

### 1. Introducción

Primera etapa que toca datos de noches. Convierte cada archivo `.xlsx`
de `raw/` en dos parquets en `bronze/`: uno con las señales canónicas
(timestamp + 4 canales) y un sidecar con los 21 índices clásicos
pre-computados por el dispositivo.

La etapa es **lossy intencional**: de cada xlsx se conservan
sólo las 5 columnas canónicas y un subset fijo de metadata. Todo lo demás
se descarta. La razón: los xlsx son fotografía del dispositivo; bronze
es el esquema estable del proyecto.

### 2. Objetivos pautados

- Convertir todos los xlsx de `raw/` a parquet canónico.
- Generar un `NightRecordID` determinístico por noche.
- Extraer `user_id` del propio xlsx y usarlo para enlazar con
  `patient_registry.csv`.
- Resolver el cruce de medianoche de forma vectorial y robusta.
- Persistir los 21 índices clásicos del dispositivo como sidecar
  (material para la Etapa 3: comparación contra re-cálculo propio).
- Dejar el pipeline **idempotente** a nivel contenido (misma entrada →
  mismo parquet).

### 3. Inputs

- `raw/exam_NNNNN.xlsx` — un archivo por noche, estructura de 3 bloques
  separados por filas vacías:
  1. **Bloque 1** — metadata KV: `user_id`, `exam_id`, fecha de estudio, etc.
  2. **Bloque 2** — 21 índices clásicos pre-computados (ahi_3/4, odi_3/4,
     hypoxic_burden_3/4, tst, sleep_efficiency, waso, etc.).
  3. **Bloque 3** — señal: una fila por segundo (1 Hz fijo), columnas
     `time`, `spo2`, `bpm`, `acceleration_module`, `sleep_stage`.
- `patients/patient_registry.csv` — para validar pertenencia a la cohorte.

Supuestos:
- Sampling 1 Hz **fijo** (se valida por `sampling_hz_median`).
- `time` viene como string AM/PM con posibles caracteres `\u202f`
  (narrow non-breaking space) que openpyxl introduce.
- El estudio puede cruzar medianoche (pocas horas antes de 00:00 seguidas
  de horas después). Hay que detectarlo sin depender de la fecha de
  comienzo.

### 4. Procesos

1. **Escaneo de raw/**: lista de xlsx, orden estable (filename).
2. Por cada xlsx:
   1. `compute_sha256(path)` — streaming en chunks de 1 MiB (archivos ~20 MB).
   2. `load_xlsx_night(path)` — segmenta los 3 bloques por filas vacías.
      Falla explícita si no encuentra 3 bloques (e.g. archivo truncado).
   3. Parseo de metadata (Bloque 1) → dict.
   4. Parseo de índices clásicos (Bloque 2) → DataFrame 1×21.
   5. `_parse_ampm_time(s)` por cada fila del Bloque 3 → tiempo en segundos
      desde medianoche, tolerante a `\u202f` y lowercase.
   6. `reconstruct_timestamps(time_strs, ts_start)` — cruce de medianoche
      vectorial: `(diff < 0).cumsum()` genera un offset de días que se suma
      a la fecha base.
   7. `normalize_signals(...)` → DataFrame canónico de 5 columnas
      (`timestamp, spo2, hr, mov, sleep_stage`) + diagnósticos (n_samples,
      n_gaps, duration_s, sampling_hz_median).
   8. `compute_night_record_id(sha, ts_start_iso)` →
      `NR_ + MD5(sha|ts_start)[:10]` — **sin salt** en esta versión.
   9. `write_signals_parquet({NR}.parquet, metadata_kv)` — parquet con KV
      a nivel de schema.
   10. `write_classical_sidecar({NR}_classical.parquet, metadata_kv)` —
       sidecar 1×21 con el mismo set de KV + `algorithm_version` del
       dispositivo.
3. Consolidar `reports/bronze_gate.json` con summary del batch.
4. Consolidar `reports/bronze_log.csv` con una fila por xlsx (OK/FAIL/SKIP).

### 5. Decisiones de diseño

**D1.1 — `patient_id` sale del xlsx.**
Se evaluó mantener el mapping en un archivo externo (`source_exam_map.csv`)
y se descartó. El campo `user_id` del Bloque 1 es autoritativo; replicarlo
en un CSV era pura redundancia. Si el laboratorio cambia el mapping,
lo cambia en el siguiente dump de xlsx.

**D1.2 — Re-ingest con sobreescritura silenciosa.**
Si el pipeline encuentra un `{NR}.parquet` que ya existe, lo sobreescribe
sin preguntar. Es seguro porque el NightRecordID es determinista: si el xlsx
no cambió, el NR es el mismo y el contenido también. Si el xlsx cambió,
queremos el nuevo contenido.

**D1.3 — Sampling 1 Hz fijo.**
Los xlsx son 1 Hz por diseño del dispositivo. Se guarda `sampling_hz_median`
en metadata como sanity check: si alguna noche sale con median ≠ 1.0,
es un flag para revisar.

**D1.4 — Índices clásicos como sidecar, no como columnas.**
Los 21 índices clásicos vienen pre-computados por el dispositivo. Se
persisten en `{NR}_classical.parquet` (1 fila × 21 columnas). Razón:
- Permite comparar contra nuestro propio cálculo en Etapa 3 (validación).
- Mantiene el parquet principal acotado a señales crudas.
- El sidecar es opt-in: etapas posteriores lo leen si lo necesitan.

**D1.5 — `sleep_stage` como 5ta columna canónica.**
Decisión de PAC_v2 (no estaba en PAC/APNEA viejos). Se conserva en bronze
aunque su uso efectivo queda abierto hasta Etapa 3/4. Razón: es barato
persistir y cara volver a procesar 560 xlsx para agregarlo después.

**D1.6 — NightRecordID sin salt.**
Se evaluó usar salt leído de `PAC_NIGHT_ID_SALT` para obfuscar el hash
ante un atacante con acceso a otro dataset con los mismos archivos.
Se descartó para esta etapa: el proyecto es local, el salt complicaba
reproducibilidad del NR entre entornos (Roberto laptop ↔ Cowork sandbox
↔ colaboradores futuros). La opción queda documentada en `config.py`
(`NIGHT_ID_SALT_ENV_VAR`) por si se reactiva en Etapa 7.

**D1.7 — Metadata KV al nivel de schema, no al nivel de file.**
pyarrow admite ambos; se eligió schema para que cualquier reader que
abre el parquet vea los KV como parte del schema sin hacer llamadas
extra a FileMetadata.

**D1.8 — Bloque 3 robusto a xlsx "unsized".**
Algunos xlsx declaran dimensiones incorrectas en el zip. `openpyxl` en
modo `read_only=True` + detección de filas vacías por generator maneja
esto sin fallar.

### 6. Outputs

Por cada noche OK, 2 archivos en `bronze/`:

| archivo | filas | columnas | metadata KV (schema) |
|---|---|---|---|
| `{NR}.parquet` | N samples | `timestamp, spo2, hr, mov, sleep_stage` | night_record_id, source_file, source_sha256, source_exam_id, user_id, ts_start, ts_end, n_samples, sampling_hz_nominal, sampling_hz_median, n_gaps, duration_s, pipeline_stage, pipeline_version |
| `{NR}_classical.parquet` | 1 | 21 índices + `algorithm_version` | (mismo set KV) |

Reports globales (`reports/`):
- `bronze_gate.json` — snapshot del batch (counts, elapsed, errors).
- `bronze_log.csv` — 1 fila por xlsx (status, NR, n_samples, duration, error).

### 7. Resultados obtenidos

**Batch final** (post-deduplicación, re-run limpio):

- 561 xlsx en `raw/` → **560 OK, 1 FAIL, 0 SKIP cohort**.
- Elapsed: **46:29 min**.
- 1 FAIL: `exam_11943.xlsx` — archivo truncado en origen
  (`ValueError: xlsx con estructura inesperada: 2 bloques (se esperaban 3)`).
  Se acepta el descarte; no amerita recuperar a mano.
- 560 noches únicas (1120 parquets: 560 signals + 560 classical).

**Duración por noche** (horas):
- min = 0.22, p25 = 6.16, median = 7.23, p75 = 8.40, max = 10.10.
- Total señal ≈ **3960 h ≈ 165 días**.

**Gaps por noche** (1 Hz nominal, ~7 h de estudio ≈ 25 k muestras):
- median = 416, p95 = 829, max = 1168.
- <4% de gaps típico — consistente con pérdidas menores de paquete.

**Cohorte de 12 pacientes**: todos presentes; ninguno quedó en
`SKIP_COHORT`. Desbalance marcado (336: 117 noches vs 622: 2).

### 8. Verificaciones

- ✅ **1 xlsx end-to-end**: `exam_12514.xlsx` (user 309) → `NR_73104dce74`,
  24704 samples, 312 gaps, cruce de medianoche correcto.
- ✅ **Idempotencia**: 2 pases del mismo xlsx → content hash del parquet
  idéntico (signals + classical).
- ✅ **Smoke batch 20 xlsx**: 20/20 OK (antes del batch completo).
- ✅ **Tests `test_ingest.py`**: 15/15 (AM/PM con `\u202f`, cruce de medianoche,
  gaps, determinismo NightRecordID, SHA256 streaming).
- ✅ **Spot-check 3 parquets post-batch**: schema 5 cols ✓, metadata KV
  15 campos ✓, cruce medianoche ✓, classical sidecar 1×21 ✓.
- ✅ **Idempotencia cross-batch**: los 560 NR_ids del batch final coinciden
  byte-a-byte con los del batch previo — confirma determinismo del pipeline.

### 9. Conclusión

Bronze dejó 560 noches con un contrato estable que las etapas siguientes
pueden consumir sin pensar en `.xlsx`. La robustez del parser de tiempo
(AM/PM con `\u202f`, cruce medianoche vectorial) y la idempotencia se
validaron con dos batches completos cuyos artefactos resultaron
byte-idénticos en filenames y content-idénticos en payload.

Aprendizajes para tesis:
- El campo `user_id` del xlsx es más limpio de lo esperado: 0
  inconsistencias en 561 archivos.
- El único FAIL (truncado en origen) es 0.18% del batch — robustez aceptable.
- Los 21 índices clásicos pre-computados son **material de validación**:
  la Etapa 3 va a recomputar varios de ellos (ahi, odi, t90) y
  comparar. Divergencia sistemática = diferencia de definición;
  divergencia puntual = bug.

### 10. Apéndices

**CLI:**
```bash
# Corrida completa (lee todo raw/):
python scripts/run_bronze.py

# Corrida acotada (smoke):
PYTHONPATH=src python -m pac.bronze --limit 20
```

**Decisión operativa — deduplicación en `raw/`.**
En el batch previo se detectaron 2 pares de xlsx byte-idénticos
(`exam_13067 2.xlsx`, `exam_13128 2.xlsx`) con el sufijo ` 2.xlsx` que
macOS agrega cuando se baja dos veces el mismo archivo. Se eliminaron
físicamente de `raw/` antes del re-run final. Principio aplicado:
**no acumular errores históricos en los logs; reiniciar desde raw limpio
cuando se está iterando el pipeline pre-cierre de etapa**.

**Launcher sin PYTHONPATH.**
`scripts/run_bronze.py` existe para esquivar un bug `<frozen getpath>`
de Python 3.12 + macOS + conda cuando `PYTHONPATH=src` se setea vía
variable de entorno antes del import. El launcher inyecta el path por
`sys.path.insert(0, ...)` al inicio, lo que siempre funciona.

---

## Etapa 1.1 — Auto-registro de pacientes nuevos

### 1. Introducción

Extensión menor de Etapa 1. Resuelve una fricción operativa: cuando
aparece un xlsx con un `user_id` nuevo (no en `patient_registry.csv`),
la Etapa 1 original lo marcaba `SKIP_COHORT` y había que editar los CSVs
a mano antes de re-correr. Esto rompía el flujo incremental.

Etapa 1.1 agrega un **pre-pass** que escanea los xlsx antes de ingestar,
detecta `user_id` nuevos y crea **filas stub** (con `patient_id` lleno y
el resto de campos vacíos) en los dos CSVs de identidad. El usuario
completa los datos después.

### 2. Objetivos pautados

- Permitir que tirar un xlsx nuevo en `raw/` no requiera intervención manual
  antes de correr bronze.
- Mantener idempotencia: si el user_id ya existe, no tocar nada.
- Hacer visible el auto-registro: WARNING a consola + campo en
  `bronze_gate.json`.
- No romper el comportamiento anterior: flag `--no-autoreg` restablece
  el SKIP original.

### 3. Inputs

- Mismos que Etapa 1 (xlsx en raw/) + `patient_registry.csv` y
  `clinical.csv` actuales.

### 4. Procesos

1. `scan_xlsx_user_ids(paths)` — itera todos los xlsx, abre **sólo el
   Bloque 1** en modo read-only (~10-50 ms/xlsx). Retorna
   `{user_id: [xlsx_filename, ...]}`.
2. Diff contra `patient_registry.csv`. Los IDs desconocidos son candidatos.
3. `register_stubs_for_unknown_ids(new_ids)`:
   - Agrega fila a `patient_registry.csv`: `patient_id` lleno, resto vacío.
   - Agrega fila a `clinical.csv`: `patient_id` lleno, resto vacío.
   - WARNING a consola con el ID creado y el xlsx que lo detonó.
4. `run_bronze(..., autoreg=True)` llama a este pre-pass antes del loop
   principal.
5. `bronze_gate.json` incluye sección `autoreg: {enabled, n_new_patients,
   new_patient_ids}`.

### 5. Decisiones de diseño

**D1.1.1 — Pre-pass, no en medio del loop.**
Podría haberse manejado al vuelo (al primer xlsx de un user nuevo, crear
la fila y seguir). Se eligió pre-pass porque:
- Un WARNING upfront al usuario es más legible que uno enterrado en un log
  de 500 líneas.
- Permite contar "cuántos pacientes nuevos hay" antes de procesar.
- Simplifica el test: se puede testear el autoreg sin ingestar nada.

**D1.1.2 — Filas stub, no filas completas.**
El xlsx sólo trae `user_id`, no nombre, apellido, fecha de nacimiento ni
datos clínicos. El stub es lo honesto. El usuario sabe que tiene que
completarlo; el pipeline no se inventa datos.

**D1.1.3 — Idempotencia fuerte.**
Segunda corrida sin xlsx nuevos = 0 mutaciones. Segunda corrida con el
mismo xlsx nuevo (ya registrado) = 0 mutaciones. Verificado por test.

**D1.1.4 — Flag `--no-autoreg` para regresión.**
Desactiva el pre-pass; los xlsx con user desconocido se marcan como
`SKIP_COHORT` igual que antes. Permite reproducir batches históricos.

### 6. Outputs

- Filas agregadas (cuando hay new patients) en `patients/patient_registry.csv`
  y `patients/clinical.csv`.
- WARNING a consola durante la corrida.
- Sección nueva en `reports/bronze_gate.json`:
  ```json
  "autoreg": {
    "enabled": true,
    "n_new_patients": 0,
    "new_patient_ids": []
  }
  ```

### 7. Resultados obtenidos

- Smoke sobre `raw/` (3 xlsx): "sin pacientes nuevos — 12 ya en registry,
  0 stubs creados". Registry y clinical intactos post-corrida.
- En el batch completo de 561 xlsx: `n_new_patients = 0`. La cohorte de
  Etapa 0 cubrió exactamente los xlsx disponibles al momento del batch.

### 8. Verificaciones

- ✅ `tests/test_autoreg.py`: 3/3 (creación, idempotencia,
  no-mutación de filas existentes).
- ✅ Regresión: `test_ingest.py` 15/15, `test_parse_birthdate.py` 12/12 —
  sin efectos colaterales.
- ✅ `bronze_gate.json` incluye la sección `autoreg` en todas las corridas.

### 9. Conclusión

Feature de bajo costo (pre-pass de ~20 s sobre 561 xlsx) que elimina la
fricción operativa principal del flujo incremental. La decisión de usar
filas stub (no auto-completar) protege la integridad del registry:
el usuario sabe exactamente qué campos vienen del laboratorio y cuáles
tiene que llenar manualmente.

Queda abierto: si el dispositivo devuelve un `user_id` **por typo**
(e.g. 3336 en vez de 336), Etapa 1.1 crearía un paciente fantasma.
Mitigación actual: WARNING visible + review humano del `gate.json`.
Rollback: borrar fila stub + mover el xlsx ofensor fuera de `raw/`.

### 10. Apéndices

**Flujo para paciente nuevo (post-Etapa 1.1):**
1. Roberto tira el/los `exam_NNNNN.xlsx` nuevos en `raw/`.
2. Corre `python scripts/run_bronze.py`.
3. Pre-pass detecta `user_id` nuevo → WARNING + filas stub creadas.
4. Pipeline ingesta los xlsx normalmente (ya no los skippa).
5. Roberto edita los 2 CSVs a mano y completa nombre/apellido/fecha_nac +
   datos clínicos.
6. Los datos quedan disponibles desde Etapa 3 en adelante (Gold + análisis).

**CLI:**
```bash
# Default (autoreg activo):
python scripts/run_bronze.py

# Regresión al comportamiento original:
python -m pac.bronze --no-autoreg
```

---

## Etapa 2 — Silver (QC por noche)

### 1. Introducción

Silver es la primera capa **analítica** del pipeline: aplica controles
de calidad (QC) sobre las señales de Bronze, marca valores no
fisiológicos, mide cobertura temporal y dicta si una noche es
estructuralmente utilizable.

**Silver NO es análisis multi-señal.** La coherencia entre HR y SpO2,
la detección de artefactos de movimiento combinada, la validación
cruzada con `sleep_stage` — todo eso vive en Etapa 3 (Events). Silver
es QC por columna + QC temporal por noche.

Silver tampoco lee `clinical.csv` ni `patient_registry.csv`: los controles
son estrictamente sobre la señal, independientes del paciente.

### 2. Objetivos pautados

- **Range QC** por señal: valores no-fisiológicos → NaN + flag. Preservar
  la columna original + agregar dos columnas nuevas
  (`{col}_invalid` bool, `{col}_clean` float64 con NaN donde invalid).
- **Cobertura temporal**: medir coverage ratio (samples observados /
  samples esperados al sampling nominal) y `max_contiguous_gap_s`
  (mayor hueco contiguo en segundos).
- **Duración**: dual-flag `aborted` (<1 h) ⊂ `short` (<3 h).
- Output por noche: un parquet con las señales QC-aware + un sidecar
  con las métricas QC agregadas.
- Reports globales con distribuciones de las métricas y conteo de flags.
- Pipeline **idempotente a nivel contenido** (los files difieren sólo
  por timestamp de procesamiento).

### 3. Inputs

Por cada noche en `bronze/`:
- `bronze/{NR}.parquet` — señales canónicas (5 cols):
  `timestamp, spo2, hr, mov, sleep_stage`.
- `bronze/{NR}_classical.parquet` — **NO se lee en Silver**. Se reserva
  para Etapa 3.
- Metadata KV del schema del parquet (15 campos).

Silver **NO lee**:
- `patients/patient_registry.csv`
- `patients/clinical.csv`

Umbrales (fijos, de `config.py`):

| Constante | Valor | Interpretación |
|---|---|---|
| `SPO2_MIN_VALID` | 55 | Por debajo → sensor desconectado o artefacto |
| `HR_MIN_VALID` | 30 | Por debajo → artefacto |
| `HR_MAX_VALID` | 200 | Por encima → artefacto (incluye taquicardia extrema) |
| `QC_COVERAGE_MIN` | 0.90 | Mínimo de samples/esperados para qc_coverage_ok |
| `QC_MAX_GAP_S` | 1800 (30 min) | Máximo gap contiguo tolerado |
| `QC_DURATION_ABORTED_S` | 3600 (1 h) | Por debajo → aborted |
| `QC_DURATION_MIN_S` | 10800 (3 h) | Por debajo → short |

### 4. Procesos

**Por noche (`process_one`):**

1. `_read_bronze_signals(nr_path)` — lee parquet + decodifica metadata
   KV (excluye claves pandas internas).
2. **Range QC — SpO2**: `apply_range_qc(df, "spo2", vmin=SPO2_MIN_VALID)`.
   Agrega `spo2_invalid` (bool) y `spo2_clean` (float64, NaN donde invalid).
3. **Range QC — HR**: `apply_range_qc(df, "hr", vmin=HR_MIN_VALID,
   vmax=HR_MAX_VALID)`. Ídem.
4. **Gap metrics**: `compute_gap_metrics(df, ts_col="timestamp",
   sampling_hz=1.0)` → dict con `n_samples`, `duration_s`, `n_expected`,
   `coverage`, `n_gaps`, `max_contiguous_gap_s`.
5. **Coverage flags**: `compute_coverage_flags(gap_metrics,
   coverage_min=0.90, max_gap_s=1800)` → `qc_coverage_ok`, `qc_max_gap_ok`.
6. **Duration flags**: `compute_duration_flags(duration_s,
   aborted_s=3600, min_s=10800)` → `qc_duration_aborted`, `qc_duration_short`.
7. **Invalid counts/fracs**: por cada señal, count y fracción de
   `{col}_invalid == True`.
8. Escribir `silver/{NR}.parquet` — 9 columnas
   (`timestamp, spo2, spo2_invalid, spo2_clean, hr, hr_invalid, hr_clean,
   mov, sleep_stage`) con metadata KV heredada de bronze + `pipeline_stage=
   silver` + `silver_schema_version` + `silver_processed_at` + umbrales
   aplicados.
9. Escribir `silver/{NR}_qc.parquet` — 1 fila × 16 columnas con métricas
   agregadas.

**Batch (`run_silver`):**

1. Listar `bronze/NR_*.parquet` (excluye sidecars `_classical`).
2. Loop con try/except por noche: una noche que falla no tira el batch.
3. Escribir `reports/silver_gate.json` — summary + distribuciones
   (median/p5/p95/min/max) de coverage, max_gap, duration,
   frac_spo2_invalid, frac_hr_invalid + conteo de flags.
4. Escribir `reports/silver_qc_summary.csv` — 1 fila × noche, legible
   de cabeza.

### 5. Decisiones de diseño

Todas cerradas en sesión con Roberto (Q1–Q8).

**Q1 — SpO2 QC pattern.** Opción elegida: **1c — rango simple + flag +
clean col** (vmin = 55, sin vmax).
Alternativas descartadas:
- 1a — Sólo NaN sobre la col original: pierde la señal cruda.
- 1b — Reemplazo in-place con forward-fill: introduce artefactos.
- 1d — Modelo de drift con banda adaptativa: over-engineering para Silver.

**Q2 — HR QC pattern.** Opción elegida: **2b — rango fijo [30, 200]**.
Alternativas descartadas:
- 2a — Rango por edad/sexo: requeriría leer clinical.csv (rompe
  la independencia de Silver).
- 2c — Coherencia con SpO2: análisis multi-señal → difiere a Etapa 3.

**Q3 — Gap metric.** Opción elegida: **3c — coverage ratio +
max_contiguous_gap_s**.
Alternativa descartada:
- 3a — `n_gaps` como única métrica: un gap de 30 min es muy distinto
  de 30 gaps de 1 s, pero `n_gaps` los trata igual.

**Q4 — Duración short.** Opción elegida: **4a — dual flag
aborted (<1h) ⊂ short (<3h)**.
Semántica:
- `< aborted_s` → `aborted=True, short=True`
- `aborted_s ≤ d < min_s` → `aborted=False, short=True`
- `d ≥ min_s` → `aborted=False, short=False`

**Q5 — Ubicación de las cols QC en el parquet.** Se colocan adyacentes
a la columna original (`spo2, spo2_invalid, spo2_clean, hr, hr_invalid,
hr_clean, mov, sleep_stage`). Facilita leer la señal QC-aware sin tener
que hacer reorder.

**Q6 — Estructura de output.** Opción elegida: **6b — dos parquets por
noche** (`{NR}.parquet` con señales, `{NR}_qc.parquet` con métricas
agregadas 1 fila × 16 cols).
Alternativa descartada:
- 6a — Un solo parquet con métricas duplicadas en cada fila: infla el
  tamaño, tiene redundancia.

**Q7 — Reports.** Opción elegida: **7b — gate.json estructurado +
summary.csv legible** + log-B (logging por noche para debug).

**Q8 — Schema versioning.** Se persiste `silver_schema_version="1"` en
cada KV. Cualquier cambio retrocompatible bumpea minor; cualquier cambio
breaking bumpea major. Permite a Etapa 3 saber con qué schema fue
producido el parquet que está leyendo.

**Otras decisiones transversales:**

- **Idempotencia por contenido, no por archivo**. Re-procesar produce
  DataFrames idénticos pero archivos distintos (por `silver_processed_at`
  en KV). Trazabilidad > hash estable. Documentado explícitamente.
- **Funciones puras en `qc.py`**, orquestación en `silver.py`. Los
  helpers de QC no saben nada de I/O, se testean con DataFrames sintéticos.
- **Isolation por try/except** en el batch: una noche que falla
  se loggea y sigue. No hay all-or-nothing.

### 6. Outputs

**Por noche (2 parquets):**

| archivo | filas | columnas | KV agregado |
|---|---|---|---|
| `silver/{NR}.parquet` | N | 9: `timestamp, spo2, spo2_invalid, spo2_clean, hr, hr_invalid, hr_clean, mov, sleep_stage` | `pipeline_stage=silver`, `silver_schema_version=1`, `silver_processed_at`, `spo2_min_valid`, `hr_min_valid`, `hr_max_valid` |
| `silver/{NR}_qc.parquet` | 1 | 16: `night_record_id, user_id, ts_start, ts_end, n_samples, duration_s, coverage, max_contiguous_gap_s, qc_coverage_ok, qc_max_gap_ok, qc_duration_aborted, qc_duration_short, n_spo2_invalid, frac_spo2_invalid, n_hr_invalid, frac_hr_invalid` | (ídem) |

**Reports globales (`reports/`):**
- `silver_gate.json` — summary + distribuciones + flags counts.
- `silver_qc_summary.csv` — 1 fila × noche, snapshot legible para
  revisión rápida en Excel/Numbers.

### 7. Resultados obtenidos

**Batch completo (560 noches, post-reset de Bronze):**

- **560/560 OK, 0 FAIL** en **42.8 s** (vs 46:29 min de Bronze; Silver
  es ~65× más rápido porque opera sobre parquet en vez de xlsx).

**Distribuciones:**

| métrica | median | p5 | p95 | min | max |
|---|---|---|---|---|---|
| `coverage` | 0.983 | — | — | 0.476 | 1.0 |
| `max_contiguous_gap_s` | 1 s | — | 11 s | — | 9656 s (2.7 h) |
| `duration_s` (h) | 7.23 | 4.27 | — | 0.22 | — |
| `frac_spo2_invalid` | 0.04% | — | 0.43% | — | 25.0% |
| `frac_hr_invalid` | 0.46% | — | 1.1% | — | 13.1% |

**QC flags agregados:**

| flag | n true | % | interpretación |
|---|---|---|---|
| `qc_coverage_ok` | 547 | 97.7% | 13 noches con gaps grandes que bajan coverage <0.90 |
| `qc_max_gap_ok` | 545 | 97.3% | 15 noches con al menos 1 gap >30 min |
| `qc_duration_aborted` | 4 | 0.7% | estudios abortados <1 h |
| `qc_duration_short` | 17 | 3.0% | noches <3 h (incluye las 4 aborted) |

**Observaciones cualitativas:**

- Las 13 noches que fallan `qc_coverage_ok` son **subset** de las 15
  que fallan `qc_max_gap_ok`. Correlación esperada: un gap grande baja
  coverage automáticamente.
- Las 4 noches aborted tienen `frac_hr_invalid` entre 4–13% (sensor
  sin estabilizar todavía: los primeros minutos de un estudio
  típicamente tienen HR errático).
- Concentración de fallos por paciente: el paciente 336 concentra 6 de
  las 13 coverage failures (y tiene 117 noches, 21% del batch; ratio
  6/117 ≈ 5% versus ratio 13/560 ≈ 2.3% global → 2× más que el promedio).
  El 656 tiene 3 y el 683 tiene 2. Dato para la tesis: ¿es problema de
  sensor/adherencia específico del paciente?
- `frac_spo2_invalid` de 25% en la peor noche — un estudio esencialmente
  inutilizable para SpO2. No tira el batch porque el flag lo marca.

### 8. Verificaciones

- ✅ `tests/test_qc.py`: **20/20** OK.
  - Range QC: vmin only, vmin+vmax, boundaries inclusive, pre-existing NaN,
    no mutación del input, raises en columna faltante, raises sin bounds.
  - Gap metrics: empty df, single row, contiguous no gaps, multiple gaps,
    max is max not sum.
  - Duration flags: aborted, short not aborted, full night, exact boundary,
    config inválida.
  - Coverage flags: fail, pass.
  - Integración: noche sintética de 96 samples con outliers + 1 gap.
- ✅ Smoke `--limit 10`: 10/10 en 0.7 s, schema validado, metadata KV
  correcta.
- ✅ Batch completo 560 noches: 560/560 OK en 42.8 s.
- ✅ Spot-check parquet silver: schema 9-col ✓, dtype por col ✓,
  flags coherentes ✓, `{col}_clean` con NaN donde `{col}_invalid == True` ✓.
- ✅ **Idempotencia de contenido** (5 noches aleatorias): DataFrames
  idénticos entre corridas. Archivos NO byte-idénticos por
  `silver_processed_at` (intencional).
- ✅ Tests previos sin regresión: `test_ingest.py` 15/15,
  `test_autoreg.py` 3/3, `test_parse_birthdate.py` 12/12.

### 9. Conclusión

Silver deja 560 noches con QC aplicado y 4 flags booleanos por noche
que las etapas posteriores pueden usar como gate de inclusión. La tasa
de fallos es baja (2.3% coverage, 2.7% max_gap, 3.0% short) y
concentrada en pacientes específicos — lo que sugiere que el QC es
razonable (no descarta masivamente) y apunta a problemas reales
(adherencia del paciente al sensor) en vez de a ruido del pipeline.

Decisiones clave validadas:
- `{col}_invalid + {col}_clean` en vez de reemplazo in-place: permitió
  spot-checks rápidos (puedes comparar visualmente crudo vs clean).
- `coverage + max_contiguous_gap_s` en vez de `n_gaps`: detectó noches
  con 1 gap enorme (>30 min) que `n_gaps` habría minimizado.
- Dual-flag aborted ⊂ short: 4 estudios abortados <1h distinguidos
  nítidamente de 13 estudios cortos (1–3h) pero potencialmente
  usables.
- Silver sin lectura de clinical.csv: mantiene los QC como controles
  estructurales de señal, no como filtros clínicos. Los filtros
  clínicos (e.g. excluir apneicos severos) viven en Etapa 3/5.

Queda abierto para Etapa 3:
- ¿Las noches con `qc_coverage_ok=False` o `qc_max_gap_ok=False` se
  **excluyen** del análisis de eventos, o se **incluyen con imputación
  del gap**?
- Safety net prometido: validar que no haya pacientes con clinical
  vacío antes de que corra Events (clinical es input del filtering
  clínico y de la normalización por edad/sexo).

### 10. Apéndices

**CLI:**
```bash
# Smoke con limit:
PYTHONPATH=src python -m pac.silver --limit 10

# Batch completo:
PYTHONPATH=src python -m pac.silver
```

**Funciones puras de `qc.py` (contrato):**

- `apply_range_qc(df, col, vmin=None, vmax=None) -> DataFrame`
  - Agrega `{col}_invalid` (bool) y `{col}_clean` (float64 NaN donde invalid).
  - NaNs pre-existentes se consideran inválidos (propagación natural).
  - No muta el input (copia).
  - Raises `KeyError` si `col` no existe, `ValueError` si ambos bounds son None.

- `compute_gap_metrics(df, ts_col="timestamp", sampling_hz=1.0) -> dict`
  - Retorna `{n_samples, duration_s, n_expected, coverage, n_gaps,
    max_contiguous_gap_s}`.
  - Edge cases: df vacío → todos en cero; 1 sola fila → coverage=1.0.

- `compute_duration_flags(duration_s, aborted_s, min_s) -> dict`
  - Retorna `{qc_duration_aborted, qc_duration_short}`.
  - Raises `ValueError` si `aborted_s > min_s`.

- `compute_coverage_flags(gap_metrics, coverage_min, max_gap_s) -> dict`
  - Retorna `{qc_coverage_ok, qc_max_gap_ok}`.

**Umbrales por qué 0.90/1800/3600/10800:**

- `coverage_min = 0.90`: por debajo de 90% de samples esperados, la noche
  tiene pérdida estructural suficiente para afectar índices continuos
  (T90, ODI). No se pone más estricto porque la cohorte tiene gaps
  típicos del 4% que son perfectamente usables.
- `max_gap_s = 1800`: 30 minutos. Un gap de 30 min contiene ~15 ciclos
  de sueño REM/NREM: pierde eventos suficientes para sesgar estadísticos
  agregados. Por debajo, interpolación es tolerable.
- `aborted_s = 3600`: 1 hora. Por debajo, no hay ni siquiera 1 ciclo
  completo de sueño.
- `min_s = 10800`: 3 horas. Mínimo reconocido de PSG estándar para
  considerar el estudio diagnóstico.

---

## Apéndice general — Convenciones transversales

### Nombres y paths

- Constantes planas en `src/pac/config.py` (no clases Config).
- Paths absolutos derivados de `PROJECT_ROOT = Path(__file__).resolve().parents[2]`.
- Naming: `{NR}.parquet` para señales, `{NR}_{tag}.parquet` para sidecars.

### Metadata KV en parquet

Al nivel de **schema** (no de file), con keys en snake_case ASCII. Se
replican las KV de la etapa anterior y se agregan las propias. Keys
con prefijo de etapa para disambiguación (`bronze_*`, `silver_*`,
`gold_*`).

### Contrato de idempotencia

- **Contenido**: re-correr cualquier etapa produce DataFrames idénticos.
- **Archivos**: pueden diferir por timestamps de procesamiento en KV.
  Esto es intencional: trazabilidad de cuándo se produjo cada artefacto.

### Reports por etapa

- Un `{etapa}_gate.json` con summary estructurado (counts, elapsed,
  distribuciones, flags).
- Un `{etapa}_log.csv` o `{etapa}_qc_summary.csv` con 1 fila por
  unidad procesada (noche).
- Ambos en `reports/`. Se **sobrescriben** en cada corrida — se asume
  que la corrida actual es la de interés.

### Principio operativo — no acumular errores

Cuando se está iterando un pipeline **antes del cierre final** de una
etapa y se detectan errores (duplicados en raw, outputs inconsistentes,
metadata corrupta), la política es **resetear desde la etapa más
cercana al origen del problema** en vez de parchear en capas posteriores.
Principio: "no quiero que se acumulen registros de errores ocurridos
sino resolverlos".

Post-cierre de etapa, este principio se afloja: una vez firmada una
etapa, se prefiere correcciones en capas siguientes para no invalidar
artefactos ya validados.

### Tests

- `tests/test_{modulo}.py` ejecutables con `pytest` o
  `python -m tests.{modulo}`.
- Cada etapa agrega tests propios y mantiene los previos verdes como
  regresión.
- Tests de integración sintética cuando es razonable (Silver: noche
  de 96 samples con outliers).

### Git

- Un commit por cierre de etapa, mensaje formato
  `"Etapa N CERRADA: <resumen 5-8 palabras>"`.
- `raw/`, `bronze/`, `silver/`, `gold/`, `reports/` gitignored
  (artefactos derivados).
- `patients/patient_registry.csv` gitignored (PII).
- `patients/clinical.csv` versionado (sin PII directa).

### Workflow por etapa

1. Scope + preguntas de fork (`Q1..Qn`) en la conversación.
2. Aprobación explícita de Roberto para cada Q.
3. Implementación.
4. Tests unitarios + smoke end-to-end.
5. Batch completo.
6. Spot-checks + idempotencia.
7. Update de `PAC_v2_HANDOFF.md` (tracker operativo).
8. Update de este documento `PAC_v2_ETAPAS.md` (sección descriptiva).
9. Commit.

---

---

## Etapa 3 — Events (EDOs, IRD e índices nocturnos)

### 1. Introducción

Events es la primera capa del pipeline donde aparecen **objetos
clínicamente interpretables**: EDOs (Eventos de Desaturación de Oxígeno)
con morfología caracterizada e índices nocturnos agregados. Es también
la primera capa que produce un contrato medible contra el **device**:
cada índice con gemelo en el sidecar classical se persiste como quinteto
`{pac_v2, device, diff_abs, diff_rel, diff_flag}`, permitiendo inspección
directa del acuerdo entre la implementación de la tesis y la del
dispositivo.

La etapa recoge el concepto original de APNEA (EDOs como unidades
morfológicas: slope de desaturación, nadir, slope de recuperación, AUC)
y lo extiende con una métrica nueva: el **IRD (Índice de Respuesta a la
Desaturación)** — combinación ponderada de tres componentes (SpO2, HR,
movimiento) normalizadas al baseline propio de cada señal, que vive a
nivel evento y se agrega como métrica nocturna proporcional a TST.

La detección es **permisiva por diseño**: drop ≥ 2% y duración ≥ 10 s.
La separación entre EDOs reales y ruido morfológico se delega a Etapa 4
(clustering). Esto preserva toda la información morfológica para análisis
posterior y evita pérdida prematura por thresholding.

### 2. Objetivos pautados

- Detectar EDOs candidatos sobre `silver/{NR}.parquet` con detección
  permisiva (drop ≥ 2%, duración ≥ 10 s), usando baseline móvil AASM
  2012 Rule 10 (mediana móvil de los 120 s previos) y recovery al 90 %
  del baseline al inicio.
- Caracterizar cada EDO con morfología completa: baseline, nadir, drop %,
  slope desat/recov (%/s), AUC (%·s), flags `meets_Npct` para
  N ∈ {2,3,4,5}, componentes IRD y scalar `ird_event`.
- Persistir **curvas resampleadas** a 30 puntos por señal (SpO2, HR, mov)
  por EDO, como sidecar dedicado, para clustering morfológico en Etapa 4.
- Marcar flags de contexto por EDO: `near_gap` (a ≤5 min de cualquier
  gap ≥30 s) y `in_sleep` (>50 % de samples con sleep_stage ≠ 0).
- Calcular ~35 índices nocturnos en 5 familias: SpO2 (ODI_N, AHI_N,
  T<N/CT<N, HB, stats), HR (stats, brady/tachy, delta_hr per-EDO), mov
  (stats + movement_index_per_h), sueño (TST, WASO, sleep_efficiency,
  sleep_latency, n_stage_shifts), event-based (IRD_night, IRD stats,
  morfología agregada).
- Persistir para cada índice con gemelo device el quinteto
  `{_pac_v2, _device, _diff_abs, _diff_rel, _diff_flag}` con threshold de
  flag |diff_rel| > 20 %.
- Procesar **todas** las 560 noches (no filtrar por QC silver); el
  filtrado clínico por calidad o por clinical.csv se aplica en Etapa 5.
- Pre-check de clinical.csv al inicio del batch (safety net): no bloquea,
  sólo registra cobertura clínica y usuarios missing.

### 3. Inputs

Por cada noche en `silver/`:
- `silver/{NR}.parquet` — 9 cols:
  `timestamp, spo2, spo2_invalid, spo2_clean, hr, hr_invalid, hr_clean,
  mov, sleep_stage`.
- `bronze/{NR}_classical.parquet` — sidecar del device con 21 cols
  (`sqi, efficiency, tst, ahi_3, ahi_4, odi_3, odi_4, hypoxic_burden_3/4,
  apnea_duration_3/4, latency, duration, waso, fragmentation, periodicity,
  spo2_basal, spo2_basal_alt1, spo2_basal_alt2, algorithm_version,
  wake_transitions`). Values vienen como strings con espacios; se
  parsean a float con `.strip()` + `float()`.

Pre-check (safety net, `clinical_precheck`):
- `patients/clinical.csv` con sep `;` y cols canónicas `CLINICAL_COLS`.
- `reports/silver_qc_summary.csv` para extraer user_ids de silver OK.

Constantes cerradas en `src/pac/config.py` (R1–R5 + Q1–Q15):

| Constante | Valor | Decisión |
|---|---|---|
| `EDO_BASELINE_WINDOW_S` | 120 | R3 — AASM 2012 Rule 10 |
| `EDO_RECOVERY_PCT` | 0.90 | R1 |
| `EDO_MIN_DURATION_S` | 10 | R2 + Q12b (permisivo; clustering en Etapa 4) |
| `EDO_DROP_THRESHOLDS_PCT` | [2, 3, 4, 5] | Q2 (cada EDO lleva 4 flags meets_Npct) |
| `EDO_RESAMPLE_N_POINTS` | 30 | Q15c (sidecar morfológico) |
| `IRD_WEIGHTS` | {spo2: 0.5, hr: 0.3, mov: 0.2} | R4 + Q13a (swappables por parámetro) |
| `NEAR_GAP_WINDOW_S` | 300 (5 min) | Q4 (near_gap flag) |
| `T_UNDER_THRESHOLDS_PCT` | [90, 88, 85] | Q7 |
| `HR_BRADY_THRESHOLD_BPM` | 50 | Q7 |
| `HR_TACHY_THRESHOLD_BPM` | 100 | Q7 |
| `HR_EXTREME_MIN_DURATION_S` | 10 | Q7 |
| `DIFF_REL_FLAG_THRESHOLD` | 0.20 | Q6 |
| `VALIDATED_INDICES` | ODI_3/4, AHI_3/4, T90, HB_3/4, TST, eff, WASO | Q6 |

### 4. Procesos

**Pre-check batch (`clinical_precheck`):**

1. Leer `clinical.csv` + extraer set de `patient_id`.
2. Leer `silver_qc_summary.csv` + extraer set de `user_id` (sólo status=OK).
3. Cross-tab: cobertura, pct_nights_covered, missing_user_ids_sample,
   partially_filled_user_ids.
4. Persistir `reports/events_clinical_precheck.json`. No bloquea.

**Por noche (`process_one_events`):**

1. Leer `silver/{NR}.parquet` con `_read_parquet_with_kv`.
2. Calcular baseline móvil:
   `compute_baseline_moving(spo2_clean, window_s=120)`.
3. Detectar EDOs candidatos:
   `detect_edo_candidates(spo2_clean, ts, baseline, min_duration_s=10,
   recovery_pct=0.90, min_drop_pct=2.0)`.
   - Trigger: `spo2_clean < baseline`.
   - Agrupar segmentos contiguos `below=True`.
   - Extender `end` hasta `spo2 ≥ baseline_at_start × 0.90`.
   - Filtrar por `duration ≥ 10 s` Y `drop_pct ≥ 2.0`.
   - Resolver solapamientos: si un EDO cae dentro del anterior, descarta.
4. Computar gaps con `compute_gaps(ts, min_gap_s=30)`.
5. Por cada EDO candidato:
   - `characterize_edo(edo, df, drop_thresholds_pct=[2,3,4,5],
     n_resample_points=30, context_window_s=60)` → morfología completa
     + componentes IRD + scalar ird_event + 3 curvas resampleadas.
   - Flags contexto: `mark_near_gap` + `mark_in_sleep`.
6. Computar índices nocturnos (orden: sleep → SpO2 → HR → mov → event):
   - `compute_sleep_stats` (TST, WASO, efficiency, latency, stage_shifts).
   - `compute_spo2_stats`, `compute_t_under` × 3, `compute_ct_under` × 3,
     `compute_hypoxic_burden` a 90 y 88 %.
   - `compute_hr_stats`, `count_sustained_extremes` (brady, tachy),
     `compute_delta_hr_stats`.
   - `compute_mov_stats`.
   - `compute_odi_ahi_family` × 4 thresholds (con in_sleep filter para AHI),
     `compute_ird_night`, `compute_ird_event_stats`,
     `compute_edo_morphology_stats`.
7. Leer sidecar classical:
   `_read_classical_sidecar(bronze_dir, nr_id)` → parseo float de strings.
8. Para cada índice en `VALIDATED_INDICES`:
   `compute_diff_vs_device(pac_v2_value, device_value)` → quinteto.
9. Escribir 3 parquets:
   - `events/{NR}_edos.parquet` (N filas × 24 cols, 1 por EDO sin curvas).
   - `events/{NR}_edo_curves.parquet` (N filas × 5 cols con 3 arrays
     de 30 pts cada uno).
   - `events/{NR}_indices.parquet` (1 fila × 104 cols con todos los
     índices + quintetos).
10. Retornar fila summary para events_summary.csv.

**Batch (`run_events`):**

1. `ensure_dirs()` + `clinical_precheck(verbose=True)`.
2. Listar `silver/NR_*.parquet` (excluye `_qc.parquet`).
3. Loop con try/except por noche. Status: OK | FAIL + error message.
4. Persistir:
   - `reports/events_summary.csv` (1 fila × noche con indices principales
     + diff_flags + has_classical_sidecar).
   - `reports/events_gate.json` (summary + distribuciones + diff_flag
     counts + thresholds).

**Análisis post-batch (`scripts/validate_vs_device.py`):**

1. Consolidar 560 `events/{NR}_indices.parquet` → pool (560×104).
2. Joinear con `silver_qc_summary.csv` → pool+QC (560×112).
3. Persistir pool como `reports/events_indices_pooled.parquet`.
4. Por cada índice validado: calcular pearson_r, spearman_r, slope_ols,
   intercept_ols, stats del diff_rel (median, p5, p95).
5. Cross-tab diff_flag × QC flags de silver (aborted, short,
   coverage_fail, max_gap_fail) para cada índice clave.
6. Persistir `reports/events_validation_by_index.csv` (1 fila × índice
   con stats) y `reports/events_validation_report.json` (todo + crosstabs).

### 5. Decisiones de diseño

Todas cerradas en sesión con Roberto (R1–R5 + Q1–Q15). Quince decisiones,
de las cuales estas son las de mayor impacto.

**R1 — Recovery del EDO.** `spo2 ≥ baseline_at_start × 0.90`, igual que
AASM y que el PAC_v1. Alternativa descartada: recovery proporcional al
drop (más agresivo).

**R2 + Q12b — Detección permisiva + clustering delegado.** Duración
mínima 10 s y drop mínimo 2 % capturan todo. La separación "EDO real vs
ruido morfológico" se hace en Etapa 4 por clustering sobre las curvas
resampleadas. Esto preserva información para análisis posteriores y
separa deterministic-detection de learned-classification.

**R3 — Baseline AASM 2012 Rule 10.** Mediana móvil de los 120 s previos
al punto actual. `min_periods=30` para que los primeros 30 s no produzcan
baseline; NaN en ese rango excluye el trigger.

**R4 + Q13a — IRD con pesos fijos swappables.** Defaults 0.5 / 0.3 / 0.2
(SpO2 > HR > mov). La función `compute_ird_event` recibe `weights` como
parámetro, por lo que una recalibración futura (RN u otra) no requiere
re-detectar EDOs — sólo re-calcular el scalar.

**Q14c — Normalización de componentes IRD al baseline propio.**
- `ird_spo2_comp = drop_pct / baseline_spo2`
- `ird_hr_comp = delta_hr_bpm / baseline_hr_bpm`
- `ird_mov_comp = (peak_mov - baseline_mov) / (baseline_mov + 0.01)`
  (el +0.01 evita explosión cuando el paciente estaba quieto). Se deja
  explícita en código la observación de que `mov_comp` puede alcanzar
  ~50 en casos con `baseline_mov ≈ 0`, a revisar en la fase de validación
  (posible mitigación: `tanh` compression).

**Q15c — Curvas resampleadas a 30 puntos.** Sidecar `_edo_curves.parquet`
con 3 arrays (spo2_curve, hr_curve, mov_curve). Se interpolan linealmente
con ffill/bfill para NaN. Permite matching morfológico y clustering
indistinto de la duración original del EDO.

**Q6 — Validación vs sidecar classical.** Para cada índice con gemelo se
persiste el quinteto `{_pac_v2, _device, _diff_abs, _diff_rel, _diff_flag}`
con threshold de flag `|diff_rel| > 0.20`. Manejo de edge cases:
`device=NaN` → quinteto con NaN; `device=0` → `diff_rel=inf`, `flag=False`
(no comparable).

**Q4d + Q4c — Procesar todas las noches, flags en Gold.** Etapa 3
procesa 560 noches sin filtrar por silver QC. Los flags `near_gap`,
`in_sleep`, `diff_flag` viajan con los datos. El filtrado operativo
(descartar noches aborted/short de análisis final) se difiere a Etapa 5.

**Q5 — Schema de outputs.** Tres parquets por noche. Alternativa
descartada: un sólo parquet con curvas como columnas (inflaría tamaño
del parquet de eventos y mezclaría dos granularidades lógicamente
distintas).

**Otras decisiones transversales:**

- **Funciones puras en `events.py` e `indices.py`**, orquestación en
  `events_pipeline.py`. Sin I/O en detectores; sólo `process_one_events`
  y `run_events` hacen read/write. Permite testing con DataFrames sintéticos.
- **Safety net clinical explícito pero no bloqueante**. `clinical_precheck`
  corre al inicio del batch, persiste JSON, emite warning si cobertura
  < 80 %, pero no aborta. Decisión Q4d+4c ya lo cubría.
- **Metadata KV heredada + extendida por cada parquet events**:
  `pipeline_stage=events`, `events_schema_version=1`,
  `events_processed_at`, `algorithm_version=pac_v2_events_1.0.0`,
  `edo_*` thresholds, `ird_weights` serializado.
- **`np.trapz` → `np.trapezoid`** con fallback para compatibilidad
  NumPy < 2 (`getattr(np, 'trapezoid', np.trapz)`).

### 6. Outputs

**Por noche (3 parquets):**

| archivo | filas | columnas | contenido |
|---|---|---|---|
| `events/{NR}_edos.parquet` | N | 24 | 1 fila por EDO: morfología + flags contexto + componentes IRD + meets_Npct |
| `events/{NR}_edo_curves.parquet` | N | 5 | sidecar morfológico: 3 arrays de 30 pts cada uno |
| `events/{NR}_indices.parquet` | 1 | 104 | índices nocturnos + quintetos device + metadata |

**Reports globales (`reports/`):**
- `events_gate.json` — summary batch (n_ok/fail, distribuciones,
  diff_flag counts, thresholds, has_classical_sidecar_count).
- `events_summary.csv` — 1 fila × noche con indices principales.
- `events_clinical_precheck.json` — snapshot del safety net pre-batch.
- `events_indices_pooled.parquet` — pool de todos los indices + cols
  de silver QC (560 × 112, base para Gold y análisis de validación).
- `events_validation_by_index.csv` — 1 fila × índice (10 filas) con
  stats pac_v2 vs device (pearson, spearman, slope_ols, diff_rel stats).
- `events_validation_report.json` — report completo + cross-tabs
  diff_flag × QC.

### 7. Resultados obtenidos

**Batch completo 560 noches, `run_events`:**
- **560/560 OK, 0 FAIL** en **272.7 s** (~4m33s).
- **560/560 con sidecar classical** disponible (clinical_precheck: 12/12
  user_ids con clinical completo → cobertura 100 %).
- **65.0 MB** total en `events/` (3 parquets × 560 noches).

**Distribuciones nocturnas (p5 / median / p95):**

| métrica | p5 | median | p95 |
|---|---|---|---|
| `n_edos_total` | 49 | 140 | 286 |
| `odi_3` | 4.9 | 14.6 | 40.2 |
| `odi_4` | 3.0 | 9.2 | 31.8 |
| `ahi_3` | 4.5 | 12.0 | 28.9 |
| `ahi_4` | 2.5 | 7.6 | 21.8 |
| `ird_night` | 0.14 | 0.40 | 1.42 |
| `tst_s` | 11491 | 21615 | 27778 |
| `sleep_efficiency` | 0.65 | 0.83 | 0.92 |
| `t90_frac` | 0.003 | 0.018 | 0.170 |
| `hypoxic_burden_90` | 0.48 | 3.75 | 37.54 |

**Validación vs sidecar classical (560 noches, 10 índices):**

| índice | N_comp | % flag | pac_v2 median | device median | pearson | slope |
|---|---|---|---|---|---|---|
| `odi_3` | 560 | 50.5 % | 14.63 | 14.93 | 0.7461 | 0.89 |
| `odi_4` | 560 | 50.2 % | 9.25 | 9.33 | 0.7296 | 0.80 |
| `ahi_3` | 560 | 52.5 % | 11.98 | 13.61 | 0.7657 | 0.59 |
| `ahi_4` | 560 | 50.5 % | 7.65 | 8.39 | 0.7653 | 0.55 |
| `t90_frac` | 0 | — | — | — (no en sidecar) | — | — |
| `hypoxic_burden_3` | 560 | 92.9 % | 3.75 | 9.00 | 0.6450 | 0.71 |
| `hypoxic_burden_4` | 560 | 95.7 % | 1.62 | 5.59 | 0.6475 | 0.64 |
| `tst_s` | 560 | 0.0 % | 21615 | 21613 | 1.0000 | 1.00 |
| `sleep_efficiency` | 560 | 1.6 % | 0.834 | 0.868 | 0.8282 | 0.93 |
| `waso_s` | 560 | 0.0 % | 3273 | 3274 | 1.0000 | 1.00 |

**Lectura analítica:**

1. **TST / WASO / sleep_efficiency** — agreement casi perfecto
   (pearson ≈ 1.00 en TST/WASO, slope ≈ 1). Nuestras métricas de sueño
   basadas en `sleep_stage` reproducen exactamente las del device.
2. **ODI_N / AHI_N** — los medians coinciden dentro de ~1–2 eventos/h,
   pero hay **50 % de noches con diff_flag** (|diff_rel|>20 %). Las
   ordenaciones por severidad se conservan (spearman 0.84–0.89). El
   slope_ols 0.55–0.89 con intercept ~+3 a +4 indica que PAC_v2 tiene
   baseline superior: más sensible en el rango bajo, acercándose al
   device en el rango alto.
3. **Hypoxic burden** — PAC_v2 ~2.5× superior al device con 93–96 % de
   diff_flag. Probable causa metodológica: nuestro HB usa threshold
   absoluto 90 %; el device parece usar threshold relativo al basal
   del paciente. Queda como discusión abierta para el capítulo de
   validación de la tesis.
4. **t90_frac** — sin gemelo en el sidecar (el device no lo expone).
   Métrica única de PAC_v2.
5. **Cross-tab diff_flag × QC fail**: las noches con QC silver
   comprometida (aborted, short, coverage_fail, max_gap_fail) concentran
   más diff_flags (40–100 % vs 50 % global), como se esperaba: menos
   datos válidos → más ruido en cocientes pac_v2/device.

### 8. Verificaciones ejecutadas

- ✅ `tests/test_events.py` (23 tests nuevos): baseline, detect, gaps,
  near_gap, in_sleep, resample, IRD components + event, caracterización
  end-to-end. **23/23 OK.**
- ✅ `tests/test_indices.py` (31 tests nuevos): 10 familias + quintetos +
  edge cases (NaN, vacío, tst=0, device=0/NaN). **31/31 OK.**
- ✅ Regression completa post-implementación: **104/104 tests OK**
  (50 previos + 54 nuevos de Etapa 3).
- ✅ Smoke `--limit 10`: 10/10 OK en 4.0 s. Los 3 parquets por noche
  generados con schema y metadata KV correctas. Quintetos coherentes
  con el sidecar (TST diff_rel=0.0000 en la noche spot-checked).
- ✅ Batch completo 560 noches: 560/560 OK, 0 FAIL, 272.7 s.
- ✅ Spot-check `{NR}_indices.parquet`: 104 cols presentes, quintetos
  completos para los 10 índices de `VALIDATED_INDICES`.
- ✅ Spot-check `{NR}_edo_curves.parquet`: 3 arrays de 30 pts por EDO,
  interpoladas correctamente sobre muesca sintética.
- ✅ `clinical_precheck` pre-batch: 12/12 user_ids cubiertos por
  `clinical.csv` → 560/560 noches con clinical completo.
- ✅ Análisis post-batch de validación vs device: stats por índice y
  cross-tab con QC silver persistidos.

### 9. Conclusión

Etapa 3 cierra el bucle que el proyecto venía buscando: cada noche ahora
tiene una caracterización morfológica de sus desaturaciones, una métrica
multi-señal (IRD) que integra la respuesta fisiológica al evento, un
conjunto completo de índices nocturnos clínicamente interpretables, y un
contrato de validación directo contra los valores del device para 10
índices con gemelo.

**Tres hallazgos centrales emergen del batch completo**, que perfilan el
capítulo de validación de la tesis:

1. **Las métricas de sueño (TST, WASO, eficiencia) son reproducibles con
   precisión decimal contra el device** — nuestra implementación basada
   en `sleep_stage` no es una aproximación, es una réplica.
2. **La detección de EDOs es sistemáticamente más sensible que la del
   device** — 50 % de noches con diff_flag >20 %, pero correlaciones
   mantenidas (pearson ~0.75, spearman ~0.85) y ordenaciones preservadas.
   Esto abre la puerta al análisis de sub-eventos que el device ignora.
3. **Hypoxic burden requiere reconciliación metodológica** — la
   divergencia sistemática (~2.5×) sugiere que los dos pipelines usan
   thresholds diferentes (absoluto vs relativo al basal). Revisar en
   Etapa 5 / validación final.

El diseño permisivo + clustering diferido a Etapa 4 ya mostró valor
operativo: no perdimos información en el thresholding, y todos los
candidatos viajan al siguiente paso con su morfología completa y 30-pt
curves disponibles para clasificación.

**Etapa 3 está cerrada y sellada**; cualquier cambio en detección,
pesos IRD o thresholds de validación se registraría como bump de
`ALGORITHM_VERSION_PAC_V2 = pac_v2_events_1.0.0`.

### 10. Apéndices y notas sueltas

**Apéndice A — por qué 30 puntos en las curvas.**
Compromiso entre resolución morfológica y costo de almacenamiento. Con
560 noches × ~140 EDOs mediana × 3 señales × 30 pts × 8 bytes ≈ 57 MB;
con 50 pts saltaría a ~95 MB. 30 puntos capturan la forma de drop +
nadir + recovery con margen (EDOs de 10 s a 120 s van bien).

**Apéndice B — Observación sobre `mov_comp`.**
La normalización `(peak_mov - baseline_mov) / (baseline_mov + 0.01)`
puede dar valores grandes (~50) cuando el paciente estaba quieto
(`baseline_mov ≈ 0`). En el batch de 560 noches se observó que la
distribución de `ird_night` no se disparó (p95 = 1.42), sugiriendo
que esos casos extremos son pocos; pero la ird_event individual puede
estar dominada por mov en ciertos EDOs. Documentado para revisión en
Etapa 5 (posible mitigación: `tanh(mov_comp / k)` o clipping).

**Apéndice C — Sidecar classical: strings con espacios.**
Los valores del `bronze/{NR}_classical.parquet` vienen persistidos como
strings del estilo `' 0.9324069268154579'` (con leading space). El
parser `_read_classical_sidecar` aplica `float(str(v).strip())` con
try/except → NaN en caso de error. No se modifica el bronze, se parsea
on-read.

**Apéndice D — `VALIDATED_INDICES` y el mapeo a columnas del sidecar.**
La constante `VALIDATED_INDICES` define el orden canónico; el mapa
`CLASSICAL_COL_MAP` en `events_pipeline.py` traduce cada índice a la
columna del sidecar (o `None` para los que no tienen gemelo como
`t90_frac`). Añadir o quitar índices validados requiere actualizar
ambas constantes.

**Apéndice E — Idempotencia.**
Los parquets events reusan el contrato de Etapa 2: idempotencia por
contenido (mismos inputs → mismos DataFrames) pero no por archivo (el
KV `events_processed_at` lleva timestamp ISO). Trazabilidad > hash
estable. Válido durante el desarrollo; post-cierre, los 560 parquets
no se regeneran salvo cambio de versión algorítmica.

---

## Etapa 3b — EDO Morphotyping (KMeans unsupervised)

### 1. Introducción

Etapa 3b es una **etapa analítica insertada entre Etapa 3 (Events) y
Etapa 4 (Windows PAC)**, no planeada originalmente en la arquitectura
v2. Surge de una observación de Roberto durante el cierre de Etapa 3:
"Antes de construir estados nocturnos PAC, ¿no convendría clusterizar
los EDOs mismos? Así cada EDO tiene un tipo morfológico y las ventanas
PAC pueden consumir densidades locales por morfotipo en lugar de solo
stats crudos de SpO2/HR/mov".

La idea es ortogonal a PAC: los morfotipos viven a nivel **evento**
(sub-minuto), PAC a nivel **estado nocturno** (ventanas 30 s / 5 min /
30 min). Ambos son unsupervised y ambos producen labels que alimentan
Gold. La diferencia clave: morfotipos son un **objeto interpretable
directamente** (un EDO es un fenómeno fisiológico discreto), mientras
que los estados PAC son más abstractos (combinación de tendencias).

El resultado de Etapa 3b es una **columna extra `morphotype` en cada
`events/{NR}_edos.parquet`**, con valores en {α, β, γ, δ, None}. Esta
columna estará disponible como feature para Etapa 4 (PAC) y como
material descriptivo para Etapa 5 (Gold + reporting).

**Por qué griegos y no "leve/moderado/severo"**: KMeans es unsupervised
y el orden de los clusters por número es arbitrario. Asignar nombres
clínicos pre-análisis contamina la interpretación. Las letras griegas
son neutras y permiten describir cada morfotipo por sus centroides en
la sección de resultados, sin pre-judice.

### 2. Objetivos pautados

- Entrenar un modelo KMeans unsupervised sobre un subset canónico de
  EDOs (in_sleep, sin near_gap, drop ≥ 3 %) usando 10 features
  escalares (6 morfología + 4 IRD), normalizadas por z-score pooled.
- Hacer sweep K=2..10 con inertia + silhouette + Davies-Bouldin, y
  elegir K con intervención humana sobre el plateau silhouette
  (rechazar decisión automática: lleva a K=2 binario o K=10 por DB).
- Entrenar el modelo final con K elegido y persistirlo en `models/`
  (pkl + zscore JSON + centroides CSV + metadata JSON).
- Aplicar batch labeling sobre los 560 × {NR}_edos.parquet, añadiendo
  columna `morphotype`. Todos los EDOs del pool reciben label si
  tienen features completas, incluidos los marginales `meets_2pct-only`
  que quedaron fuera del training.
- Producir reports interpretables: training_report.json (sweep +
  centroides + composición meets_Npct), interpretability.md (tabla
  de centroides), batch_gate.json (560/560 OK), summary.csv (1 fila ×
  noche), y un dashboard HTML standalone por cada K evaluado para
  visualizar boxplots, PCA 2D y curvas morfológicas medias.
- Mantener idempotencia de contenido: con modelo fijo, los labels son
  reproducibles al 100 % (KMeans.predict determinístico).
- No romper Etapa 3: la columna `morphotype` es additive-only; las 560
  noches siguen teniendo todas las otras columnas intactas y el KV
  metadata original se preserva (sólo se agregan 3 claves nuevas).

### 3. Inputs

Por cada noche en `events/`:
- `events/{NR}_edos.parquet` — 1 fila × EDO con las 10 features
  requeridas + flags (`in_sleep`, `near_gap`, `meets_Npct`) necesarios
  para construir la máscara de training.

Consolidación al pool:
- `load_edo_pool(EVENTS_DIR)` itera sobre las 560 noches y concatena
  en un `pd.DataFrame` con columna extra `night_record_id` para
  trazabilidad. Total: 85 286 EDOs × ~40 cols.

Constantes cerradas en `src/pac/config.py` (Q1–Q4):

| Constante | Valor | Decisión |
|---|---|---|
| `MORPHOTYPE_FEATURES` | 10 features (6 morfología + 4 IRD) | Q1=B |
| `MORPHOTYPE_TRAINING_MASK` | `{in_sleep: True, near_gap: False, meets_3pct: True}` | Q3=B |
| `MORPHOTYPE_K_RANGE` | `list(range(2, 11))` | Q2=B |
| `MORPHOTYPE_RANDOM_STATE` | 42 | Reproducibilidad |
| `MORPHOTYPE_GREEK_LETTERS` | `['α', 'β', 'γ', 'δ', 'ε', 'ζ', 'η', 'θ', 'ι', 'κ']` | Q4=A |
| `MORPHOTYPES_SCHEMA_VERSION` | `'1'` | Contrato de schema |
| `ALGORITHM_VERSION_MORPHOTYPES` | `'pac_v2_morphotypes_1.0.0'` | Versionado algorítmico |

### 4. Procesos

**Training pipeline (`scripts/train_morphotypes.py`):**

1. **Consolidación del pool**: `mt.load_edo_pool(EVENTS_DIR)` →
   DataFrame 85 286 × N cols con columna `night_record_id`.
2. **Training mask**: `mt.build_training_mask(pool, MORPHOTYPE_TRAINING_MASK)`
   → pd.Series booleana. Reglas: cada flag del spec debe cumplirse
   exactamente; NaN o columna faltante → False para esa fila.
3. **Feature matrix**: `mt.build_feature_matrix(train_df, features)`
   → np.ndarray (n, 10) dtype float + `kept_idx` con índices de filas
   preservadas (las que tienen todas las 10 features no-NaN).
4. **Z-score pooled**: `mt.fit_zscore(X, features)` →
   `ZScoreParams(feature_cols, mean, std)`. std=0 → se fuerza a 1
   para evitar divisiones por cero en columnas constantes.
   Luego `mt.apply_zscore(X, z)` → Xz con mean 0 y std 1 por columna.
5. **Sweep K=2..10**: `mt.sweep_k(Xz, k_range=[2..10], random_state=42)`
   → DataFrame con cols `k, inertia, silhouette, davies_bouldin`.
   Cada K: fit KMeans(n_init=10), `sklearn.metrics.silhouette_score`
   (sample_size=5000 si n > 5000 para eficiencia), `davies_bouldin_score`.
6. **Selección de K**: heurística automática `mt.choose_k(sweep)` usa
   `silhouette - 0.5*DB_norm` pero tiende a extremos en este dataset.
   Se permite override manual vía CLI `--k`. En la práctica K=4 fue
   elegido post-dashboard comparando K=3 vs K=4 con boxplots + PCA.
7. **Fit final**: `mt.fit_kmeans(Xz, k=k_final, random_state=42)` →
   KMeans fitted (n_init=10, max_iter=300, tolerance=1e-4).
8. **Centroides en espacio original**:
   `mt.centroids_original_space(model, zparams)` → DataFrame
   (k × len(features)), index=letra griega, valores
   de-normalizados a la escala física original de cada feature.
9. **Persist**: `mt.persist_model(model, zparams, k_sweep, n_training,
   models_dir)` escribe 4 artefactos en `models/`:
   `edo_morphotype_kmeans.pkl` (pickle del KMeans),
   `edo_morphotype_zscore.json` (params z-score),
   `edo_morphotype_centroids.csv` (centroides legibles),
   `edo_morphotype_metadata.json` (k, schema_version, training_mask,
   n_training, random_state, k_sweep completo).
10. **Reports**: `reports/morphotypes_training_report.json` +
    `reports/morphotypes_interpretability.md` (auto-generado).

**Inference pipeline (`scripts/apply_morphotypes.py`):**

Por cada noche:
1. `pq.read_table({NR}_edos.parquet)` preservando KV metadata.
2. Construir matriz de features `sub = df[feature_cols].apply(pd.to_numeric, errors='coerce')`.
3. Identificar filas completas: `complete = sub.notna().all(axis=1)`.
4. `Xz = mt.apply_zscore(sub.to_numpy(), zparams)`.
5. `labels_int[complete] = model.predict(Xz[complete])`;
   `labels_int[~complete] = -1` (sentinel).
6. Mapeo a letra griega: `label_greek = MORPHOTYPE_GREEK_LETTERS[li]`
   si `li >= 0`, else None.
7. `df['morphotype'] = label_greek` (sobre-escribe si ya existe).
8. Preservar KV metadata existente (decodificando bytes→str) y
   agregar 3 claves nuevas: `morphotyping_applied_at` (ISO
   timestamp), `morphotype_algorithm_version`,
   `morphotypes_schema_version`.
9. `pq.write_table(new_tbl, {NR}_edos.parquet)` in-place.

Acumula stats por noche: `n_edos, n_labeled, n_null, n_α, n_β, n_γ,
n_δ`. Al final, escribe `reports/morphotypes_summary.csv` + un
`reports/morphotypes_batch_gate.json` con los totales.

**Dashboard pipeline (`scripts/dashboard_morphotypes.py`):**

CLI con `--k` recibe el K a explorar. Entrena on-the-fly (NO
persiste modelo), genera un HTML standalone con 6 secciones:
1. Sweep K (scatter inertia/silhouette/DB).
2. Tabla de centroides en espacio original + leyenda dinámica
   ordenada por `drop_pct` descendente.
3. Boxplots por feature en grid 2×5, coloreados por morfotipo.
4. Composición `meets_Npct` por morfotipo.
5. PCA 2D scatter (sample 8 000 pts para no saturar SVG) con los
   2 primeros componentes principales.
6. Curvas morfológicas medias ±IQR por morfotipo (sample 500 por
   cluster desde `{NR}_edo_curves.parquet`).

Todos los plots embebidos como SVG inline → HTML único ~1.4 MB
abrible en browser sin dependencias.

### 5. Decisiones de diseño

**Q1=B — Incluir IRD en las features de training.**
Opciones evaluadas:
- A: sólo morfología SpO2 (6 features). Ventaja: interpretación
  puramente morfológica. Desventaja: ignora respuesta autonómica.
- **B: 6 morfología + 4 IRD (10 features). Ventaja: captura la
  dimensión "respuesta motora" que resultó ser un morfotipo real (β).
  Desventaja: IRD es una métrica derivada, añade dependencia de
  weights R4 (0.5/0.3/0.2).** Ganó porque el objetivo es tener
  morfotipos clínicamente útiles para PAC, no sólo descriptores SpO2.

**Q2=B — Sweep K=2..10 con silhouette + DB + plateau analysis.**
Opciones evaluadas:
- A: K fijo (ej. K=3 por analogía leve/mod/sev). Desventaja:
  pre-commits a una interpretación antes de ver la estructura.
- **B: sweep + decisión humana sobre plateau.** En este dataset el
  plateau es K=3–6 en silhouette ~0.30, con K=2 dominando por ser
  dicotomía severos/resto. La elección K=4 se tomó comparando
  dashboards K=3 vs K=4 visualmente.

**Q3=B — Excluir marginales del training, labelar en inferencia.**
Opciones evaluadas:
- A: incluir todos los EDOs en training. Desventaja: los marginales
  `meets_2pct-only` contaminan los centroides con ruido.
- **B: training sobre subset canónico (`meets_3pct=True`), inferencia
  sobre todos.** Los marginales reciben label por consistencia del
  pipeline pero no afectan los centroides. Training subset: 42 819
  EDOs (50.2 % del pool).

**Q4=A — Nomenclatura griega (α, β, γ, δ) en lugar de clínica.**
Opciones evaluadas:
- **A: letras griegas, neutras.** Elegida.
- B: "leve / moderado / severo / sostenido". Desventaja: pre-judge la
  interpretación antes de inspeccionar centroides. Además, en este
  dataset el morfotipo β ("respuesta motora") no encaja bien en esa
  escala lineal de severidad.

**Decisión K=4 post-dashboard.**
K=3 agrupa todos los EDOs no-severos en un solo cluster ("leves"). K=4
divide ese grupo en dos: α sostenidos (duración larga pero drop
moderado) y δ leves verdaderos (duración corta, drop mínimo). Este
split tiene valor clínico: los α son un fenotipo no trivial (apneas
sostenidas sin gran desaturación, posiblemente respiraciones lentas y
profundas sub-umbral), distinto de los δ. La pérdida de parsimonia vs
K=3 se compensa con la ganancia interpretativa.

**n_init=10 y random_state=42.**
KMeans es sensible a inicialización. n_init=10 ejecuta 10
k-means++ con diferentes seeds y se queda con el de menor inertia.
random_state=42 fija el seed global → reproducibilidad total (tests
lo verifican).

**Z-score pooled (no per-patient).**
KMeans es escala-sensible (usa distancia euclidiana). Normalizamos
sobre el training set completo (42 819 EDOs), no por paciente. El
rationale: queremos que "EDO severo del paciente X" y "EDO severo del
paciente Y" caigan en el mismo cluster, aunque el paciente X tenga
baseline más alto. Si normalizamos per-patient, perdemos esa
comparabilidad.

**Columna `morphotype` como object (no category).**
Para permitir None en EDOs con features incompletas. Categorical con
NaN funcionaría pero complica el ingest en reports downstream.

**Idempotencia por contenido, no por archivo.**
Consistente con Etapas 2 y 3: `morphotyping_applied_at` lleva ISO
timestamp en KV metadata → re-corridas producen archivos no
byte-idénticos pero con DataFrames idénticos. Trazabilidad > hash.

### 6. Outputs

**Por noche (columna extra):**

| parquet | cambio |
|---|---|
| `events/{NR}_edos.parquet` | Agrega columna `morphotype` (dtype=object, ∈ {α, β, γ, δ, None}). KV metadata aumentada. Otras columnas y KV existente intactos. |

**Modelo persistido (`models/`):**

| archivo | contenido |
|---|---|
| `edo_morphotype_kmeans.pkl` | KMeans fitted (sklearn). |
| `edo_morphotype_zscore.json` | `{feature_cols, mean[], std[]}`. |
| `edo_morphotype_centroids.csv` | Centroides en espacio original. |
| `edo_morphotype_metadata.json` | K, versiones, sweep completo, training_mask. |

**Reports:**

- `reports/morphotypes_training_report.json` — sweep + centroides +
  cluster_sizes + composición meets_Npct.
- `reports/morphotypes_interpretability.md` — markdown con tablas +
  placeholders para descripción clínica manual.
- `reports/morphotypes_summary.csv` — 1 fila × noche × morfotipo.
- `reports/morphotypes_batch_gate.json` — batch gate.
- `reports/morphotypes_dashboard_k{3,4}.html` — dashboards
  standalone.

### 7. Resultados obtenidos

**Consolidación del pool:**
- 560 noches × 85 286 EDOs totales.
- Training subset canónico: 42 819 EDOs (50.2 % del pool).
- Tasa de NaN en features: 0 % (todos los EDOs del pool tienen
  features completas — la detección en Etapa 3 ya garantiza esto).

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

Observaciones:
- Silhouette max en K=2 (0.467): dicotomía severos/resto.
- Plateau K=3–6 en silhouette ~0.30 (variación < 0.005 entre K=4/5/6).
- K≥7 degrada silhouette (cae a 0.25–0.26).
- DB decrece monotónicamente con K → no útil como señal pura.
- Inertia decrece suavemente sin codo claro.

**K=4 elegido. Centroides en espacio original:**

| morfotipo | n_train | % | duration | drop_pct | nadir | slope_desat | slope_recov | AUC | IRD | ird_mov |
|---|---|---|---|---|---|---|---|---|---|---|
| α | 7 379 | 17.2 % | 38.2 s | 7.1 % | 87.1 | 0.51 | 0.85 | 128.6 | 2.6 | 12.6 |
| β | 7 986 | 18.7 % | 20.8 s | 8.1 % | 86.5 | 1.40 | 1.11 | 75.8 | 13.5 | **67.2** |
| γ | 2 448 | 5.7 % | 24.3 s | **20.8 %** | **73.9** | **4.20** | **3.22** | **206.0** | 10.1 | 49.9 |
| δ | 25 006 | 58.4 % | 18.5 s | **4.2 %** | 90.0 | 0.79 | 0.60 | 38.9 | **1.2** | 6.0 |

**Interpretación post-hoc:**
- **α — sostenidos**: drop moderado (7 %), duración larga (38 s, 2×
  el resto), slopes planas. Fenotipo novedoso: EDO prolongado sin
  desaturación severa. Hipótesis: respiraciones lentas y profundas
  sub-umbral, o apneas compensadas parcialmente.
- **β — respuesta motora**: drop leve-moderado (8 %) pero
  `ird_mov_comp = 67` (vs 6–50 en el resto). EDOs con fuerte arousal
  motor. Hipótesis: despertares corticales con componente
  movimiento pronunciado.
- **γ — severos**: drop 21 %, nadir 74 %, slopes abruptas, AUC alta,
  IRD SpO2 alto. La cola severa clásica. Minoría (5.7 % del training).
- **δ — leves**: drop 4 %, corto, IRD casi-cero. Mayoritario (58 %
  training, 72 % pool). La categoría residual.

**Distribución global (pool completo, 85 286 EDOs):**

| morfotipo | n_EDOs | fracción |
|---|---|---|
| α | 10 598 | 12.43 % |
| β | 9 930 | 11.64 % |
| γ | 3 005 | 3.52 % |
| δ | 61 753 | 72.41 % |

Fracción δ mayor en el pool global (72 %) que en el training subset
(58 %): los marginales `meets_2pct-only` excluidos del training son
mayoritariamente leves.

**Composición por `meets_Npct` (training subset):**

| morfotipo | meets_2pct | meets_3pct | meets_4pct | meets_5pct |
|---|---|---|---|---|
| α | 100 % | 100 % | 91.5 % | 78.9 % |
| β | 100 % | 100 % | 94.7 % | 85.0 % |
| γ | 100 % | 100 % | 100 % | 99.9 % |
| δ | 100 % | 100 % | 48.6 % | 24.0 % |

γ satura los 4 thresholds (son los severos puros). δ dropea fuerte
por encima de 3 % (leves verdaderos). α y β tienen sensibilidad alta
hasta 5 %.

**Batch labeling (560 noches):**
- 560/560 OK, 0 FAIL en 25.1 s (~45 ms/noche).
- 85 286 EDOs labeled, 0 null.
- Idempotencia verificada: 2 corridas consecutivas producen labels
  idénticos al 100 %.

### 8. Verificaciones ejecutadas

- ✅ `tests/test_morphotypes.py`: 20/20 OK. Cubre:
  - `build_training_mask`: default, missing column, NaN como False,
    override spec.
  - `build_feature_matrix`: shape, drop NaN rows, raise on missing col.
  - `fit_zscore` + `apply_zscore`: roundtrip mean 0 std 1, std=0 safe,
    dict roundtrip.
  - `sweep_k`: estructura de columnas, K reales, inertia decreciente.
  - `fit_kmeans`: determinismo con random_state, separación de
    clusters sintéticos (silhouette > 0.5).
  - `int_to_greek`: mapping básico, empty, raise si K > 10.
  - `centroids_original_space`: shape + index griegos + valores
    cerca de clusters sintéticos.
  - `persist_model` + `load_model`: roundtrip con tmp_path.
  - `choose_k`: retorna K válido del range.
- ✅ Regresión completa `pytest tests/`: **124/124 OK** (104 previos +
  20 nuevos, sin regresión en events/indices/qc/ingest/autoreg/
  parse_birthdate).
- ✅ Smoke `apply_morphotypes --limit 10`: 10/10 OK, schema validado,
  columna `morphotype` presente, KV metadata aumentada con 3 claves
  nuevas.
- ✅ Batch completo 560 noches: 560/560 OK, 0 FAIL, 25.1 s.
- ✅ Idempotencia (2 corridas): labels byte-compatibles.
- ✅ Dashboards K=3 y K=4 generados, visualizados y comparados antes
  de fijar K=4.
- ✅ Integridad de parquets post-labeling: re-lectura de las 560 noches
  confirma que todas las columnas previas siguen presentes, el KV
  metadata original se preserva, y la columna `morphotype` está
  correctamente tipada.

### 9. Conclusión

Etapa 3b produce un artefacto que no estaba en la arquitectura
original: un modelo KMeans persistido (K=4) que asigna cada EDO a
uno de 4 morfotipos griegos. Los 85 286 EDOs del pool tienen
morphotype asignado, sin NaNs. La distribución es desbalanceada (δ
dominan con 72 %, γ raros con 3.5 %) pero esto refleja la
distribución fisiológica real de los eventos de desaturación: la
mayoría son leves y cortos, la minoría son severos. El fenotipo
inesperado es el α — sostenidos con drop moderado — que podría
corresponder a apneas mixtas o hipopneas prolongadas y es un
hallazgo que vale documentar en la tesis.

La etapa es **reversible**: si en Etapa 4 o 5 se decide que K=3 o K=5
encaja mejor, se puede re-entrenar con `scripts/train_morphotypes.py
--k <N>` y re-aplicar con `apply_morphotypes.py`. El modelo es un
artefacto intercambiable, no una decisión terminal.

Para Etapa 4, los morfotipos proveen un nuevo conjunto de features
por ventana temporal: densidades locales (n_α_local, n_β_local,
n_γ_local, n_δ_local) que enriquecen el vector usado para clustering
de estados PAC.

### 10. Apéndices y notas sueltas

**Apéndice A — ¿Por qué no DBSCAN o GMM?**
DBSCAN requiere eps como hiperparámetro y en espacios de alta
dimensión (10D) es difícil calibrar. GMM asume densidades
gaussianas que los centroides no parecen tener (γ y β son colas
pesadas). KMeans simple con z-score es la baseline interpretable;
si en Etapa 5 se ve que los clusters no captan bien la estructura,
se puede probar HDBSCAN o GMM como ablation.

**Apéndice B — n_init=10 es conservador.**
sklearn default es n_init=10 desde 1.2 (antes era 10 explícito o 1
en versiones muy viejas). Con random_state=42 + n_init=10, la
inertia final es estable entre corridas (<0.1 % variación).

**Apéndice C — ¿Por qué no PCA antes de KMeans?**
Evaluado mentalmente; descartado por interpretabilidad. Los 10
features originales son nombrables (duration, drop, slope...); los
10 primeros PCs no lo son. El dashboard sí usa PCA 2D para
visualización, pero el modelo clusterea en el espacio de features
originales (post z-score).

**Apéndice D — Heurística `choose_k` y su inadecuación.**
La heurística `silhouette - 0.5*DB_norm` en este dataset elige K=10
porque DB decrece con K. Se dejó en el código como utilidad pero no
se usa para decisiones de tesis. Para que fuera útil habría que
añadir penalty por K (ej. `silhouette - 0.05*K`) o usar elbow
explícito sobre inertia; pero con 10 niveles de K, la decisión
humana sobre el plateau es más honesta.

**Apéndice E — Morphotype None y downstream.**
En el batch completo 0 EDOs quedaron con `morphotype = None`.
Técnicamente el pipeline soporta features incompletas (label →
None), pero en la práctica Etapa 3 garantiza features completas
vía `characterize_edo`. Si en el futuro se incorporan noches con
features degradadas (ej. sensor fail parcial), downstream debería
filtrar `morphotype.notna()` antes de agregar densidades.

**Apéndice F — Tamaño del modelo persistido.**
`edo_morphotype_kmeans.pkl` pesa ~5 KB (KMeans es minúsculo). El
zscore JSON ~1 KB. El metadata JSON ~3 KB. Total del modelo < 10
KB, cómodo de versionar en git si se decide.

**Apéndice G — Idempotencia.**
Los parquets reusan el contrato de Etapas 2 y 3: idempotencia por
contenido (mismo modelo + mismo input → mismos labels), pero no por
archivo (KV lleva `morphotyping_applied_at` ISO timestamp).
Trazabilidad > hash estable. El modelo sí es byte-idéntico entre
corridas con mismo random_state, pero su JSON metadata lleva
timestamp de persistencia.

---

## Apéndice pre-Etapa 4 — Validación del sleep staging del device

Este apéndice documenta un análisis hecho **entre el cierre de Etapa 3b y el
paso 1 de Etapa 4**, a pedido de Roberto tras consultar al diseñador del
aparato. No es una etapa formal del pipeline: es una decisión de diseño
tomada con evidencia empírica antes de incorporar `sleep_stage` como
feature en las ventanas multiescala.

### Contexto

El aparato emite `sleep_stage ∈ {0, 1, 2, 3}` como 5ª columna canónica en
Bronze. Consulta al diseñador: **el valor lo estima un algoritmo interno a
partir de frecuencia cardíaca y movimiento, sin referencia PSG.** La
literatura sobre staging basado en HR+mov reporta accuracies 4-stage de
~70-78% contra PSG (Redmond, Fonseca, Willemen).

Sin PSG ground-truth disponible, se diseñó una **validación indirecta por
plausibilidad fisiológica**: 5 checks que si cierran sugieren que el
staging del device replica rasgos macroscópicos del sueño normal, y si no
cierran indican que el staging no es utilizable tal cual.

### Procesos

Script `scripts/analyze_sleep_staging.py`, idempotente, con `--limit N`
para ejecutar sobre subconjunto.

Para cada noche:
- Se leen `silver/{NR}.parquet` (incluye `sleep_stage` por segundo) y
  `events/{NR}_edos.parquet` (para el check 5 de morfotipos × stage).
- Se computan 5 estadísticos fisiológicos (ver apartado "Checks" abajo).

A nivel pool:
- Se agregan las 560 noches y se evalúan 5 señales binarias de cierre.
- Veredicto: ≥80% señales OK → `USAR TAL CUAL`; 50-79% → `USAR CON
  CAVEATS`; <50% → `REPENSAR`.

Salidas: `reports/sleep_staging_validation.{json,md,html}`.

### Los 5 checks

**Check 1 — Estructura por ciclos REM-NREM.** Conteo de ciclos usando
REM-entry con prefijo ≥300s de NREM. Esperado: 4–6 ciclos/noche, 70–120
min por ciclo.

**Check 2 — Distribución temporal por quintiles.** Se divide cada noche en
5 quintiles temporales y se calcula fracción de cada stage por quintil.
Esperado: N3 (stage 3) concentrado en Q1-Q2 (front-loaded), REM creciente
hacia Q5.

**Check 3 — Arquitectura por grupo clínico.** Fracciones promedio de cada
stage por tercil de ODI_3. Esperado: pacientes con más eventos tienen más
wake y menos sueño consolidado.

**Check 4 — Estabilidad de bloques (run-length).** Distribución de
duraciones de runs consecutivos del mismo stage. Esperado: runs N3 ~10-25
min, runs REM ~10-30 min; <40% de runs ≤30s.

**Check 5 — Coherencia morfotipos × sleep_stage.** Cross-tab entre
morfotipo del EDO y stage vigente en t_start. Esperado: morfotipo γ
(severo) sobre-representado en REM por atonía muscular.

### Resultados (560 noches)

**Veredicto: `REPENSAR` · 2/5 señales OK.**

| Check | Resultado empírico | Esperado | Cierra |
|---|---|---|---|
| 1 — Ciclos #/noche | mediana 10 (IQR 7-12) | 4-6 | ✗ |
| 1 — Duración ciclo | 28.5 min mediana | 70-120 min | ✗ |
| 2 — N3 decrece Q1→Q5 | 0.305 → 0.348 (sube) | decrece | ✗ |
| 2 — REM crece Q1→Q5 | 0.154 → 0.170 | crece | ✓ |
| 3 — Severidad discrimina | low: 12% wake / 37% "deep"; high: 22% wake / 29% "deep" | sí | ✓ |
| 3 — REM en rango literatura | 60.5% de noches | >50% | ✓ parcial |
| 3 — Deep en rango literatura | 19.6% de noches (3-34%) | >50% | ✗ |
| 4 — Run-length | <5% short runs | <40% short | ✓ |
| 5 — γ sobre-rep en REM | homogéneo (15% REM, 33% Light, 33% "Deep") | γ↑ REM | ✗ |

**Conteo de Check 5 (morfotipos × stage, pool 560 noches):**

| morphotype | wake | rem | light | deep | total |
|---|---|---|---|---|---|
| α | 2994 | 1739 | 3286 | 2579 | 10598 |
| β | 1791 | 1684 | 3296 | 3159 | 9930 |
| γ | 548 | 455 | 1004 | 998 | 3005 |
| δ | 11439 | 10144 | 20710 | 19460 | 61753 |

### Decisión de diseño

Roberto evaluó 3 mapeos propuestos:

- **A (binario):** wake vs sleep — pierde toda granularidad intra-sueño.
- **B (3 cats mantiene "deep"):** `wake = 0, light_sleep = 1+2, deep_sleep = 3`.
- **C (3 cats "deep = 2+3"):** `wake = 0, light_sleep = 1, deep_sleep = 2+3`.

**Decisión final: Mapeo B.**

Fundamentos:
- El aparato discrimina wake vs sleep con fidelidad suficiente (check 3).
- Colapsar 1+2 como `light_sleep` reduce el ruido de la sub-clasificación
  intra-NREM, que es donde la validación falla.
- Mantener stage 3 como `deep_sleep` conserva un feature potencialmente
  discriminativo (aunque no sea N3 clínico), para que el clustering
  PAC de Etapa 4 lo pondere empíricamente.
- El nombre `deep_sleep` se mantiene con **caveat explícito** en
  `config.py`: no es N3 AASM, es el label del stage 3 del device.

### Outputs persistidos

- `scripts/analyze_sleep_staging.py` — análisis idempotente re-ejecutable.
- `reports/sleep_staging_validation.json` — per-night stats + pool.
- `reports/sleep_staging_validation.md` — reporte narrativo con veredicto.
- `reports/sleep_staging_validation.html` — dashboard con 4 plots SVG.
- `src/pac/config.py` — `PAC_SLEEP_STAGE_COLLAPSE_MAP`, `PAC_SLEEP_CATEGORIES`,
  `PAC_SLEEP_COMPOSITION_FEATURES` con caveat documentado.

### Implicancias para Etapa 4

La ventana multiescala tendrá 3 features de composición de sueño
(`frac_wake`, `frac_light_sleep`, `frac_deep_sleep`) en lugar de las 5
originalmente planeadas (`frac_wake/n1/n2/n3/rem`). El total de features
por ventana pasa de 26 a **24** (15 signal + 6 morfotipo + 3 sleep).

La máscara de training híbrido (`frac_wake_max ≤ 0.5`) queda intacta — el
umbral opera sobre la nueva categoría `frac_wake`, que equivale al stage 0
raw del aparato (igual definición, sólo renombre).

### Conclusión

La validación evitó incorporar 5 features de composición de sueño con
semántica falsa (n1/n2/n3/rem). El colapso a 3 categorías es
defensivo-pragmático: usa la señal que el aparato sí captura
confiablemente (sleep vs wake), mantiene un feature extra para
granularidad empírica sin comprometerse con lectura clínica. El análisis
es re-ejecutable si a futuro se obtiene PSG ground-truth o si cambia el
firmware del aparato.

---

## Etapa 4 — PAC States (multi-escala s/m/l)

### 1. Objetivo

Asignar a cada noche un **stratum temporal multi-escala** de estados
clínicos derivados de clustering no-supervisado sobre ventanas
contiguas. La idea: producir un "estratigrafía" de la noche que pueda
analizarse junto con los EDOs de Etapa 3 para inferir patrones
**antes/durante/después** de los eventos. Tres escalas — `s=30s`,
`m=5min`, `l=30min` — cubren respectivamente respuesta inmediata
fisiológica, dinámica fisiopatológica de eventos, y estados PAC
históricos (sleep cycles).

### 2. Decisiones de diseño (Q1–Q6, pre-código)

- **Q1 = A** — ventanas fijas, 3 escalas `s/m/l`, anclas PAC históricas.
- **Q2 = A** — ventanas disjuntas (overlap=0). Permite suma directa de
  features y evita doble-conteo de morfotipos.
- **Q3 = C** — 24 features por ventana: 15 signal stats (spo2 × 6 +
  hr × 6 + mov × 3) + 6 densidades morfotípicas (n_α/β/γ/δ + n_total +
  IRD local) + 3 composición de sueño (`frac_wake`,
  `frac_light_sleep`, `frac_deep_sleep`).
- **Q4 = A** — KMeans **unificado** sobre las 560 noches (no
  per-paciente), z-score pooled. Razón: tamaño de cohorte
  insuficiente para personalización, y el objetivo es construir un
  vocabulario compartido de estados.
- **Q5 = C** — sweep K ∈ [2..10] por escala con anclas históricas
  marcadas en dashboard, decisión humana informada (no auto-pick por
  silhouette).
- **Q6 = C** — máscara de training **híbrida**: entrena sólo sobre
  ventanas con `frac_wake ≤ 0.5` AND `coverage ≥ 0.5`. Inferencia se
  hace sobre TODAS las ventanas (incluido wake), pero se persiste
  `training_eligible` para auditoría.

### 3. Pasos 1-4 — Constantes, helpers y tests

- **Paso 1 (`src/pac/config.py`)**: 24 features canónicas declaradas en
  `PAC_WINDOW_FEATURES`, mapeo sleep colapsado en
  `PAC_SLEEP_STAGE_COLLAPSE_MAP`, umbrales de máscara training en
  `PAC_STATES_TRAINING_MASK`, durations en `PAC_WINDOW_DURATIONS_S`.
- **Paso 2 (`src/pac/windows.py`)**: `partition_windows(silver, scale)`
  + `aggregate_signal_stats` + `densify_morphotypes(edos, …)` + helpers
  puros. Tests `tests/test_windows.py`.
- **Paso 3 (`src/pac/states.py`)**: `fit_zscore`, `apply_zscore`,
  `fit_kmeans`, `predict`, `dist_to_centroid_z`, `sweep_k`. Tests
  `tests/test_states.py`.
- **Paso 4**: `tests/test_windows.py` + `tests/test_states.py` cubren
  partition, agregación, z-score idempotencia, KMeans determinismo.

### 4. Paso 5 — Training + sweep

`scripts/train_pac_states.py` corre el sweep K=2..10 por escala sobre
las 560 noches con la máscara training híbrida. Para cada K computa
inertia, silhouette, davies-bouldin y entrena el modelo final con K
seleccionado. Output:

- `models/pac_states_{s,m,l}.pkl` — KMeans persistido (gitignored).
- `models/pac_states_{s,m,l}_centroids.csv` — centroides en espacio z
  (versionado).
- `models/pac_states_{s,m,l}_metadata.json` — features, K elegido,
  random_state, n_init, fit_at, n_train, mean_silhouette (versionado).
- `models/pac_states_{s,m,l}_zscore.json` — mean/std por feature
  (versionado).
- `reports/pac_states_sweep.json` — métricas por K.
- `reports/pac_states_training_report.json` — resumen de fit.
- `reports/pac_states_batch_gate.json` — gate `validation_proceed=true`
  tras post-fit.

### 5. Decisión de K — Roberto eligió s=6, m=8, l=6

Decisión informada desde `dashboard_pac_states.html` (paso 6) que
muestra elbow + silhouette por K + composición de cada cluster
candidato + anclas históricas (S=7, M=6, L=4). Las anclas históricas
**no se respetaron**:

- **s=6** (no 7): silhouette pico en 6, séptimo cluster fragmentaba
  un estado fisiológico ya presente.
- **m=8** (no 6): inflexión clara de elbow en 8; los 2 clusters
  extras capturan dinámicas valiosas (variabilidad alta wake-like vs
  transiciones REM-NREM).
- **l=6** (no 4): silhouette pico en 6; 4 era too-coarse y mezclaba
  estados clínicamente distintos.

### 6. Validación post-fit (`scripts/validate_pac_states.py`)

5 checks por escala:

- **C1 cluster_sizes** (escalonado FAIL/WARN/PASS): FAIL si <0.3%, WARN
  si <2.0%, PASS si ≥2.0%. Resultado: 3 WARN (S5=0.61%, M5=0.35%,
  L3=0.56%) — outliers clínicamente válidos.
- **C2 silhouette per-cluster**: ningún cluster con silhouette < 0.0.
- **C3 morphotype_coherence** (doble criterio Q-aprobado): PASS si
  diversity ≥ 0.5 OR n_edos_total range ≥ 1.0.
- **C4 sleep_coherence** (rediseñado sin wake-required): la training
  mask excluye wake, así que el check sólo mira light/deep balance.
- **C5 physiological_ranges** (con epsilon=1e-3 para tolerar -0.0
  roundoff): ningún feature signal fuera de su rango fisiológico
  esperado.

**Veredicto:** PROCEED con 3 WARN · 0 FAIL. Gate
`validation_proceed=true`.

### 7. Paso 7 — Apply (labeling batch)

`scripts/apply_pac_states.py` recorre las 560 silver, ventanea por
escala, aplica los 3 modelos (z-score → KMeans.predict →
dist_to_centroid), y persiste **1 parquet por noche** en `states/`
con schema long-format de 15 columnas:

```
night_record_id, scale, window_idx, t_start, t_end, t_start_s, t_end_s,
state_label, cluster_int, dist_to_centroid, coverage,
frac_wake, frac_light_sleep, frac_deep_sleep, training_eligible
```

Las 3 escalas se stackean en un único DataFrame por noche, ordenado por
`(scale, window_idx)` para idempotencia byte-compatible. Ventanas con
NaN en features se persisten con `cluster_int=-1`, `state_label=None`,
`dist_to_centroid=NaN` (no se pierden).

KV metadata por parquet: `night_record_id`, `applied_at`,
`algorithm_version`, `schema_version`, `k_per_scale`,
`source_silver_mtime`, `source_events_mtime`. Permite trazabilidad y
detección de necesidad de re-labeling si cambia silver o events.

**CLI**: `--mode {smoke,batch}`, `--limit N`, `--force`,
`--skip-gate-check`. La gate de pre-apply lee
`pac_states_batch_gate.json:validation_proceed` y aborta si es `false`
salvo `--skip-gate-check`.

**Resultado batch**: 560/560 OK · 0 FAIL · 927s wall-clock. Drift L1
vs training: s=5.41%, m=10.75%, l=3.11% — distribuciones estables
entre training y full-cohort apply.

**Tests**: `tests/test_apply_pac_states.py` 6/6 verde.

### 8. Paso 8 — QA del labeling

`scripts/qa_pac_states_batch.py` corre 5 checks B1–B5 sobre los 560
parquets en `states/`:

- **B1 schema_lock_per_night**: verifica `OUTPUT_COLS` + dtypes en cada
  parquet. **Resultado: 100% PASS.**
- **B2 temporal_coverage**: ratio `sum(window_seconds) / max(t_end_s)`
  por escala. FAIL <0.85, WARN <0.95, PASS ≥0.95. **Resultado: 7
  FAIL · 5 WARN · 548 PASS.** Las 7 FAIL son **redundantes con
  silver_qc** (todas tienen `qc_coverage_ok=False` Y
  `qc_max_gap_ok=False` por gaps de 1-2.7h).
- **B3 per_night_cluster_dominance**: WARN si algún cluster acapara
  >95% de las ventanas en alguna escala. **15 noches WARN** (2.7%) —
  noches cortas o muy uniformes.
- **B4 dist_to_centroid_outliers**: per-escala, p95 global como
  threshold; flagea noches con >20% de ventanas en top-5%. **36
  noches WARN** (6.4%) — candidatas a inspección clínica.
- **B5 cross_scale_consistency**: índice de coherencia
  `1 - entropy(labels)/log2(K)` para m-states y s-states dentro de
  cada l-window. WARN si mean < 0.3. **Resultado: PASS** —
  l-vs-m=0.618, l-vs-s=0.544 → régimen *moderado* deseado (escalas
  relacionadas pero no redundantes).

**Cross-check con silver_qc** (Q1=A post-resultados, Roberto): si
TODAS las B2-FAIL están marcadas como `qc_coverage_ok=False` en
silver_qc, el gate baja a PROCEED (la detección es redundante con QC
anterior). Las 7 noches efectivamente lo cumplen → gate
`apply_qa_proceed=true`.

**Listas auxiliares persistidas**:

- `reports/b2_fail_excluded.json` (7 NRs) — exclusión OBLIGATORIA en
  Etapa 5 (gold).
- `reports/pac_states_flag_for_review.csv` (44 noches B3∪B4) — atención
  en gold (peso reducido o cohorte separado).

**Tests**: `tests/test_qa_pac_states_batch.py` 9/9 verde.

### 9. Paso 8.5 — Stratigraphy dashboard

`scripts/build_stratigraphy_dashboard.py` produce 5 HTML interactivos
(Plotly) que materializan el objetivo original de Roberto:

> "ver superpuesto una noche con sus diferentes estados multi-escala
> y los EDOs … inferencias acerca de lo que pasa antes, durante y
> después de los EDOs."

**Selección de noches** (seed=42, reproducible vía
`reports/stratigraphy_nights_selected.json`):

| Tag | NR_id | Criterio |
|---|---|---|
| saos_severo | NR_55d1add2ff | argmax(ahi_3)=60.13, 264 EDOs |
| control | NR_7fe8bdf7e4 | argmin(ahi_3)=2.02 con tst≥5h, 40 EDOs |
| cluster_L3 | NR_75caca4a4e | 4 ventanas L3 (rare cluster outlier) |
| flag_b3_dominance | NR_29462faf4f | dominio l=100% |
| flag_b4_outliers | NR_5fd35bfdca | 19.4% s en top-5% dist |

**Layout (8 filas con shared_xaxes para zoom/pan sincronizado)**:

1. SpO₂ line (75-100%).
2. HR line (40-110 bpm).
3. Hipnograma escalonado (wake/light/deep).
4. EDOs: span rojo + ±2 min context shading amarillo + marker rombo
   con tooltip (duración, nadir, drop%, ΔHR, morfotipo,
   meets-3%/4%).
5. Stripe states escala l (30 min) coloreada.
6. Stripe states escala m (5 min) coloreada.
7. Stripe states escala s (30 s) coloreada con tooltips per-window
   (state, coverage, frac_wake, dist).
8. Morfotipos por EDO (α/β/γ/δ con colores).

Outputs en `reports/stratigraphy/<NR>__<tag>.html` (~5.7 MB total,
gitignored, regenerables al 100% desde el seed + selection JSON).

### 10. Cierre y handoff a Etapa 5

**Tests al cierre**: 189/189 OK (15 nuevos: 6 apply + 9 QA, sin
regresión sobre 174 previos).

**Insumos para Etapa 5 (Gold)**:

- 560 silver + 560 events + 560 states + reports/events_indices_pooled
  (560 × 112 cols) + 3 modelos PAC + 4 morfotipos.
- **Cohorte efectivo recomendado**: 560 − 7 = **553 noches** (excluir
  los NRs en `b2_fail_excluded.json`).
- **44 noches con flag_for_review** a tratar con cuidado en gold (peso
  reducido o cohorte secundario).
- Estructura de datos lista para join `silver × events × states` sobre
  `(night_record_id, t_start_s/t_end_s)`, que es la base del análisis
  pre/durante/post EDO que motivó el diseño multi-escala.

**Comandos de regeneración** (PYTHONPATH=src en todos):

```
# Training (paso 5):
python scripts/train_pac_states.py
# Validación post-fit (paso 5-val):
python scripts/validate_pac_states.py
# Apply batch (paso 7):
python scripts/apply_pac_states.py --mode batch
# QA batch (paso 8):
python scripts/qa_pac_states_batch.py
# Stratigraphy dashboard (paso 8.5):
python scripts/build_stratigraphy_dashboard.py
# Tests:
python -m pytest
```

---

## Etapa 4.6 — Pre-Gold hardening (lock + schemas + cohortes + manifest + retrain gateway)

**Objetivo.** Antes de saltar a Gold (Etapa 5), endurecer la base con cinco piezas que la tesis va a usar repetidamente: (1) lock de dependencias para reproducibilidad, (2) validación de schema en los bordes de cada layer, (3) helpers de cohorte declarativos para análisis, (4) manifest único de modelos congelados, (5) gateway controlado para reentrenar cuando entren noches/pacientes nuevos. La etapa **no toca el corpus ni los modelos** — solo agrega la infraestructura de trazabilidad.

### Pieza A — Lock de dependencias

- `requirements.txt` reorganizado con secciones (Core, Data IO, Plotting, Tests) y rangos `>=,<` (ej. `numpy>=1.26,<3.0`, `pandas>=2.2,<3.0`, `scikit-learn>=1.5,<2.0`).
- Nuevos: `plotly>=5.20,<7.0`, `matplotlib>=3.8,<4.0`, `seaborn>=0.13,<1.0`, `pytest>=8.0,<10.0` (antes implícitos).
- `scripts/freeze_lock.sh` ejecutable: corre `pip freeze | sort -f` con header (timestamp ISO, Python version, ruta del venv) y escribe `requirements.lock.txt`. Sanity-check de `VIRTUAL_ENV` para no congelar el sistema base.

**Política**: `requirements.txt` define el contrato (rangos), `requirements.lock.txt` reproduce el ambiente exacto de la defensa.

### Pieza B — Schema validation en bordes (`src/pac/schemas.py`)

- `SchemaError(ValueError)` para fallos en modo strict.
- `_canonical_kind(series) → "int"|"float"|"bool"|"str"|"ts"|"list"`. Tolerancia de subtipos: int8/16/32/64 → "int", float32/64 → "float". Esto es importante: un parquet roundtripeado puede degradar `int64→int32`, no debe romper validación.
- 5 schemas declarativos (`dict[col → kind]`):
  - `BRONZE_SCHEMA` (5 cols)
  - `SILVER_SCHEMA` (9 cols, agrega `*_invalid`/`*_clean`)
  - `EVENTS_EDOS_SCHEMA` (25 cols: identidad, geometría SpO2, hemodinamia, mov, IRD, gates, morfotipo)
  - `EVENTS_CURVES_SCHEMA` (5 cols, list-typed)
  - `STATES_SCHEMA` (15 cols: 4 identidad + 4 temporal + cluster + 5 contexto)
- `ValidationResult` (dataclass): `ok, layer, source, missing, wrong_dtype, extras, n_rows`.
- 5 validadores públicos: `validate_bronze`, `validate_silver`, `validate_events_edos`, `validate_events_curves`, `validate_states`. Firmas idénticas: `(df, source, strict=True, allow_extras=True) → ValidationResult`.
- Modo `strict=True` raise; `strict=False` emite `UserWarning` y devuelve `ok=False`.
- Helpers: `list_layers()`, `get_schema(layer)` (devuelve copia para evitar mutación accidental).

**Smoke test contra archivos reales del corpus**: 5/5 validadores OK, 0 extras inesperados.

### Pieza C — Cohort helpers (`src/pac/cohorts.py`)

Módulo declarativo para definir subconjuntos de noches usados en análisis. Cada función devuelve `set[str]` (sets se eligen por sobre listas para permitir intersección/unión natural).

**Cohortes públicas** (sobre el corpus actual):

| cohorte | n | def |
|---|---|---|
| `get_cohort_all()` | 560 | `states/NR_*.parquet` presentes |
| `get_cohort_quality()` | 553 | `all − b2_fail_excluded` (7 noches B2 fail) |
| `get_cohort_strict()` | 511 | `quality − flag_for_review` (44 noches B3∪B4) |
| `get_cohort_high_tst(min_tst_h=4.0)` | 499 | `quality ∩ {tst_s ≥ 4h}` |
| `get_cohort_with_clinical()` | 553 | `quality ∩ {user_id con clinical.csv válido}` |

**Helpers**:
- `cohort_summary() → dict` con tamaños de las 5 cohortes + counts de exclusiones.
- `snapshot_cohort(name, nrs, output_path) → Path` persiste JSON con `{name, timestamp, count, night_record_ids: sorted}` para reproducibilidad.
- `clear_cache()` vacía el `lru_cache(maxsize=1)` de cada I/O helper.

**Política**: cualquier análisis "de tesis" declara al inicio qué cohorte usa y persiste el snapshot. Análisis sensibles a calidad reportan contra `quality` y `strict` para mostrar robustez.

### Pieza D — Model manifest (`models/MANIFEST.json`)

Fuente única de verdad sobre qué modelos están activos, sobre qué corpus fueron entrenados, con qué parámetros. Generado por `scripts/generate_manifest.py`.

**Estructura**:
```json
{
  "manifest_version": "1.0",
  "model_version": "v1",
  "generated_at": "...",
  "git_sha": "...",
  "corpus_snapshot": {"n_state_files": 560, "n_patients": 12, "cohort_sizes": {...}},
  "models": {
    "morphotypes": {label, type, k=4, n_training, feature_cols, training_mask, labels=[α,β,γ,δ], centroids_path, centroids_sha256_short, ...},
    "pac_states_s": {... k=6 ...},
    "pac_states_m": {... k=8 ...},
    "pac_states_l": {... k=6 ...}
  },
  "k_per_scale_pac_states": {"s": 6, "m": 8, "l": 6},
  "exclusion_lists": {"b2_fail_excluded": {...}, "flag_for_review": {...}},
  "retrain_policy": {"trigger_threshold_new_nights": 100, "trigger_threshold_new_patients": 10, ...}
}
```

CLI: `--bump v2` (nueva versión post-reentreno), `--force` (regenerar misma versión).

**Lo lee**: `retrain_check.py`, `apply_pac_states.py` (para metadata KV), la app (para inferencia frozen), Gold (para versión por noche).

### Pieza E — Retrain gateway (`scripts/retrain_check.py`)

Compara inventario actual del corpus contra `corpus_snapshot` del manifest. Si supera umbrales (default: 100 noches nuevas o 10 pacientes nuevos), **sugiere** retrain con prompt `[y/N]`. **Nunca reentrena sin confirmación explícita** (excepto `--auto-yes` para CI).

CLI: `--threshold-nights N`, `--threshold-patients M`, `--json` (no interactivo), `--auto-yes`, `--dry-run` (muestra plan, no ejecuta).

Si el usuario acepta, orquesta 6 pasos vía `subprocess` con `PYTHONPATH=src`:
1. `train_morphotypes.py`
2. `train_pac_states.py`
3. `validate_pac_states.py`
4. `apply_morphotypes.py`
5. `apply_pac_states.py --mode batch`
6. `qa_pac_states_batch.py`

**No bumpea manifest automáticamente** — el usuario lo hace manual con `generate_manifest.py --bump v2` una vez conforme con resultados (revisión de sweep, validación, QA). Esto preserva el principio "modelos frozen v1 salvo decisión explícita".

### Pieza F — Tests + docs

- `tests/test_schemas.py` (15 tests): 5 happy-path + 2 missing cols + 2 wrong dtype + 3 extras (int subtypes, float subtypes, custom col) + 3 helpers públicos.
- `tests/test_cohorts.py` (10 tests): 5 invariantes (subset relations, monotonía de high_tst), 3 cohort_summary (keys, types, consistencia), 2 snapshot (JSON válido, crea dirs).
- Suite total: **214/214 OK**, sin regresión sobre Etapa 4.

### Verificaciones ejecutadas

- ✅ `freeze_lock.sh` ejecutado en venv → `requirements.lock.txt` generado.
- ✅ Smoke `validate_*` contra archivos reales: 5/5 OK, 0 extras inesperados.
- ✅ `cohort_summary()` produce las cifras esperadas (560/553/511/499/553).
- ✅ `generate_manifest.py` genera `MANIFEST.json` v1 con git_sha y SHA256 de cada centroide.
- ✅ `retrain_check.py --json` y modo humano: delta=0 → no sugiere retrain (corpus coincide con snapshot).
- ✅ `pytest`: **214/214 OK** (25 nuevos en 4.6, 189 previos sin tocar).

### Outputs estructurales (nuevos en 4.6)

- `requirements.txt` reorganizado + `requirements.lock.txt` (gitignored, regenerable).
- `scripts/freeze_lock.sh` (versionado).
- `src/pac/schemas.py` (~280 líneas, versionado).
- `src/pac/cohorts.py` (~210 líneas, versionado).
- `scripts/generate_manifest.py` (versionado).
- `scripts/retrain_check.py` (versionado).
- `models/MANIFEST.json` (**versionado** — fuente de verdad de la versión activa).
- `tests/test_schemas.py` + `tests/test_cohorts.py` (versionados).

### Insumos disponibles para Etapa 5 (Gold) — ahora con trazabilidad

- Todo lo de Etapa 4 (560 silver/events/states + 3 modelos PAC + morfotipos).
- **Cohorte oficial declarado**: `get_cohort_quality()` (553 NRs) — `get_cohort_strict()` (511) para análisis de robustez.
- **Manifest activo**: `models/MANIFEST.json` v1 con SHA256 de cada centroide → Gold puede incluir `model_version="v1"` en la metadata por noche.
- **Validadores ready-to-use**: cualquier nuevo paso de Gold valida sus inputs/outputs con `validate_<layer>()`.
- **Snapshot de cohorte por análisis**: `snapshot_cohort('thesis_main', get_cohort_quality(), 'analyses/thesis_main_cohort.json')` para reproducibilidad documental.

**Comandos de regeneración** (PYTHONPATH=src en todos):

```
# Lock del ambiente:
bash scripts/freeze_lock.sh
# Manifest (v1 ya existe; bumpear sólo post-reentreno):
python scripts/generate_manifest.py --force
# Retrain gateway (chequeo periódico):
python scripts/retrain_check.py
# Tests:
python -m pytest
```

---

## Etapa 5 — Gold (data lake unificado APNEA + PAC)

**Objetivo.** Consolidar todo lo que la tesis necesita para análisis en
una capa coherente, persistente y trazable. Filosofía explícita
(Roberto): *"una clusterización no es más que una segmentación en el
fondo arbitraria... Evento, noche y paciente deben ser exhaustivos en
datos bien caracterizados."* Gold es **data lake** — preserva TODO lo
medido, no solo el output del clustering.

### Decisiones arquitecturales (cerradas pre-implementación)

- **5 tablas** (1 fila × grano de cada nivel):
  `events`, `events_curves`, `states`, `nights`, `patients`.
- **Cohorte B** (todas 560 noches con flags `in_quality`, `in_strict`,
  `in_high_tst`, `flag_for_review`, `b2_fail`). El filtrado se hace
  downstream con `pac.cohorts`.
- **Cross-night**: `nights_gold` incluye absolutas + relativas. Las
  relativas marcadas con sufijos (`_pct_corpus`, `_vs_baseline_patient`)
  y documentadas en `gold/nights_columns.json`.
- **Cross-night cohort-relative computadas SOBRE `in_quality=True`**
  (553 noches) como referencia, aplicadas a todas las filas — previene
  contaminación de percentiles por noches sin calidad.
- **NO state context en events_gold** ahora — reconstruible vía join
  `events_gold × states_gold ON (nr, ts_start ∈ [t_start, t_end])`
  cuando se necesite.
- **Trazabilidad de modelo**: `gold/MANIFEST.json` apunta a
  `models/MANIFEST.json` activo + sha256 de cada parquet gold.
- **Naming**: `gold/<tabla>.parquet` (sin sufijo `_gold` redundante —
  la carpeta ya dice "gold").
- **Formato**: parquet (compresión, dtypes, lectura rápida). CSV opcional
  vía script futuro si se necesita para R/Excel.

### Paso 1 — Schemas Gold (`src/pac/schemas.py`)

5 schemas nuevos extendiendo los base:

- `GOLD_EVENTS_SCHEMA` (32 cols) = `EVENTS_EDOS_SCHEMA` (25) + `_TRACE_BLOCK`
  (user_id, model_version) + `_COHORT_FLAGS` (5).
- `GOLD_EVENTS_CURVES_SCHEMA` (5 cols) = `EVENTS_CURVES_SCHEMA` sin cambios
  (se accede joineada a events_gold — duplicar es ruido).
- `GOLD_STATES_SCHEMA` (22 cols) = `STATES_SCHEMA` (15) + `_TRACE_BLOCK` + `_COHORT_FLAGS`.
- `GOLD_NIGHTS_SCHEMA` (skeleton mínimo en paso 1, se completa en paso 5
  con allow_extras=True).
- `GOLD_PATIENTS_SCHEMA` (skeleton mínimo en paso 1, se completa en paso 6
  con allow_extras=True).

5 validators nuevos: `validate_events_gold`, `validate_events_curves_gold`,
`validate_states_gold`, `validate_nights_gold`, `validate_patients_gold`.
`list_layers()` y `get_schema()` ahora cubren los 10 layers (5 base + 5 gold).

### Paso 2 — `build_events_gold.py` → `gold/events.parquet`

Concatena 560 `events/{NR}_edos.parquet` + agrega bloques transversales:

- `user_id` desde `reports/silver_qc_summary.csv`.
- `model_version` desde `models/MANIFEST.json`.
- 5 flags vectorizados desde `pac.cohorts`.

Validación strict en cada fuente (EVENTS_EDOS_SCHEMA) + validación final
del output (GOLD_EVENTS_SCHEMA).

**Output**: 85,286 EDOs × 32 cols × 3.4 MB.

### Paso 3 — `build_events_curves_gold.py` → `gold/events_curves.parquet`

Concatena 560 `events/{NR}_edo_curves.parquet`. Sin agregar flags (se
joinea con events_gold sobre `(night_record_id, ts_start)`).

**Output**: 85,286 filas × 5 cols × 8.6 MB. Curvas list-typed de 30 muestras
por señal (spo2/hr/mov).

### Paso 4 — `build_states_gold.py` → `gold/states.parquet`

Stackea los 560 `states/{NR}.parquet` long-format con bloques transversales
consistentes con events_gold.

**Output**: 518,867 filas × 22 cols × 15.1 MB. Distribución por escala:
s=464,651 (88%), m=46,461 (9%), l=7,755 (3%).

### Paso 5 — `build_nights_gold.py` → `gold/nights.parquet`

Tabla principal del producto. 1 fila × noche. Estructura:

- **Identidad** (3): `night_record_id`, `user_id`, `model_version`.
- **Flags cohorte B** (5).
- **Índices clásicos** (104): de `events/{NR}_indices.parquet` (TST, WASO,
  T90/88/85, AHI/ODI 2/3/4/5%, hypoxic burden, comparaciones pac_v2 vs device).
- **Distribución de morfotipos** (4): `frac_morpho_α/β/γ/δ`.
- **Distribución de PAC states** (20): `frac_state_s_S0..S5` (6) +
  `frac_state_m_M0..M7` (8) + `frac_state_l_L0..L5` (6). Excluye ventanas
  con cluster_int=-1.
- **Métricas de transición y entropía** (6): `n_transitions_state_{s,m,l}`
  + `entropy_state_{s,m,l}` (Shannon en bits).
- **Cross-night cohort-relative** (3): `ahi_3_pct_corpus`, `t90_frac_pct_corpus`,
  `odi_3_pct_corpus`. Percentile-rank computado sobre quality.
- **Cross-night patient-relative** (3): `delta_ahi_3_vs_baseline_patient`,
  `delta_t90_frac_vs_baseline_patient`, `delta_odi_3_vs_baseline_patient`.
  Baseline = mean leave-one-out del paciente sobre sus otras noches quality
  (≥3 noches → 11 de 12 pacientes elegibles, 551 de 553 noches cubiertas).

**Output**: 560 filas × 146 cols × 0.55 MB.

Sanidad verificada: Σ frac_morpho = 1.0 exacto, Σ frac_state_{s,m,l} = 1.0
exacto, `ahi_3_pct_corpus` uniforme [0,1] (mean=0.500), delta vs baseline
centrado en 0 (mean=-0.000), entropy ≤ log2(K) cada escala.

### Paso 6 — `build_patients_gold.py` → `gold/patients.parquet`

1 fila × paciente. 12 pacientes en corpus actual. Por cardinalidad baja,
vista descriptiva — NO se usa para inferencia estadística.

- **Identidad** (2).
- **Demografía** (7) de `patients/clinical.csv`: sexo, peso_kg, talla_cm,
  apnea_prev, diabetes, hta, marcapasos. Join `patient_id ↔ user_id`
  normalizando a str.
- **Conteos de noches** (5): total, quality, strict, high_tst,
  flag_for_review.
- **Agregados** (30 = 10 × {mean, median, sd}): sobre noches in_quality
  del paciente, para 10 métricas clave (ahi_3, t90_frac, odi_3, tst_s,
  sleep_efficiency, mean_spo2, min_spo2, mean_hr, n_edos_total,
  mean_drop_pct). sd = NaN si n_quality ≤ 1.
- **Distribución morfotipos** (4): PONDERADA por cantidad de EDOs
  (no promedio de fracciones por noche).
- **Distribución PAC states** (20): ponderada por ventanas válidas.
- **Estabilidad fenotípica** (3): `cv_*_intra_patient` (sd/mean) sobre
  ahi_3, t90_frac, odi_3.

**Output**: 12 filas × 71 cols × 49 KB.

Heterogeneidad clínica clara: AHI3 ∈ [2.7 (sano), 41.0 (severo)],
n_nights_quality ∈ [2, 116], CV intra-paciente ∈ [0.11, 0.72].

### Paso 7 — Sidecars (versionados en git)

**`gold/MANIFEST.json`** (`scripts/build_gold_manifest.py`):
- Apunta a `models/MANIFEST.json` activo (model_version).
- Para cada tabla: path, n_rows, n_cols, size_mb, sha256_short.
- git_sha del HEAD.
- build_order canónico, cohort_policy explícita.

**`gold/nights_columns.json`** (`scripts/build_nights_columns_doc.py`):
- Diccionario de datos de las 146 cols de nights_gold.
- Hybrid: clasificación AUTOMÁTICA por sufijo + descripciones HUMANAS
  opcionales overrideables desde `gold/nights_columns_descriptions.csv`.
- 5 categorías (kind):
  * `identity` (3), `flag` (5), `single_night` (132),
    `cross_night_corpus` (3), `cross_night_patient` (3).
- Cobertura de descripciones: 100% (0 placeholders).

### Paso 8 — Orquestador `build_gold_all.py`

Pipeline completo en orden canónico con gates: chequea pre-requisitos
(events/, states/, silver_qc, models/MANIFEST.json, clinical.csv) antes
de arrancar. Cada paso corre como subprocess; abort si alguno falla.

CLI: `--dry-run` (plan, no ejecuta), `--quiet`.

### — — — Guía didáctica de Gold — — —

> Esta sub-sección está pensada para que cualquier lector futuro (yo
> dentro de seis meses, un colaborador, un juez de tesis) pueda abrir
> el documento y entender en una pasada qué es Gold, qué archivos lo
> componen, qué hay en cada uno, y cómo se usa para análisis. Se puede
> leer de forma autocontenida sin haber seguido el detalle de los 8
> pasos previos.

#### El mapa mental: la pirámide de granularidad

PAC_v2 estudia la apnea del sueño en **tres niveles anidados de
observación**, de fino a grueso:

```
                     ┌──────────────┐
                     │   PACIENTE   │   12 personas (escalable a ~50)
                     │  (user_id)   │   1 fila → patients_gold
                     └──────┬───────┘
                            │ 1:N
                  ┌─────────┴─────────┐
                  │       NOCHE       │   560 noches grabadas
                  │ (night_record_id) │   1 fila → nights_gold
                  └─────────┬─────────┘
                            │ 1:N (cada noche tiene N EDOs y M ventanas)
              ┌─────────────┴─────────────┐
              │                           │
       ┌──────▼──────┐             ┌──────▼──────┐
       │ EDO (evento │             │  VENTANA    │   3 escalas:
       │  desat./    │             │  s/m/l      │   s=30s, m=5min,
       │  obstructi- │             │             │   l=30min
       │  vo)        │             │  → states_  │
       │  → events_  │             │    gold     │
       │    gold +   │             │             │   ~518k filas
       │  events_    │             │             │
       │  curves_    │             │             │
       │  gold       │             │             │
       └─────────────┘             └─────────────┘
       85,286 EDOs                 (1 fila por
       1 fila c/u                   ventana × escala)
```

Las 5 tablas Gold están organizadas por **grano**: cada una resuelve un
nivel de pregunta distinto. Saber cuál usar depende de qué unidad de
análisis te interesa.

#### Llaves de join (cómo se conectan las tablas)

| desde / hacia | events | events_curves | states | nights | patients |
|---|---|---|---|---|---|
| **events** | — | (nr, ts_start) | (nr, ts_start ∈ [t_start, t_end]) | nr | user_id |
| **events_curves** | (nr, ts_start) | — | — | nr | — |
| **states** | (nr, ts_start ∈ [..]) | — | — | (nr, scale) | user_id |
| **nights** | nr | nr | (nr, scale) | — | user_id |
| **patients** | user_id | — | user_id | user_id | — |

Convenciones: `nr` = `night_record_id`, `(a, b)` = key compuesta.

#### Las 5 tablas, una por una

##### 1. `gold/events.parquet` — el catálogo de EDOs

**Para qué existe.** Una sola tabla con TODOS los eventos detectados
(EDOs = Eventos de Desaturación Oximétrica) del corpus, con todas las
mediciones que los caracterizan, su morfotipo asignado, y bloques
transversales (paciente + flags de cohorte + versión de modelo).

**Qué contiene.** 85,286 EDOs × 32 columnas. Una fila = un evento
detectado en una noche, con:
- Geometría del evento en SpO₂: cuánto bajó, qué tan rápido, área bajo la curva, profundidad mínima.
- Hemodinamia: cambio de HR (Δ HR), HR baseline.
- Movimiento: pico, baseline.
- Índice IRD compuesto: una métrica unificada de severidad respiratoria del evento.
- Flags clínicos: cumple criterio 2%/3%/4%/5% de drop, está en sueño, está cerca de gap.
- Morfotipo asignado: α/β/γ/δ (geometría dominante del evento).
- Identidad: a qué noche y a qué paciente pertenece.
- Trazabilidad: qué versión de modelo lo etiquetó.
- Flags de cohorte: si su noche está en quality, strict, etc.

**Preguntas que responde.**
- "¿Cuántos EDOs morfotipo β tuvo el paciente 175 en sus noches quality?"
- "Distribución de drop_pct por morfotipo en todo el corpus."
- "¿Los EDOs con duración > 60s tienden a tener mayor delta_hr_bpm?"
- "Top 100 EDOs más severos según ird_event."

**Cómo leerlo.**
```python
import pandas as pd
edos = pd.read_parquet('gold/events.parquet')
quality_edos = edos[edos['in_quality']]
quality_edos.groupby('morphotype')['drop_pct'].describe()
```

##### 2. `gold/events_curves.parquet` — la forma física de cada EDO

**Para qué existe.** Para cada EDO, las **curvas pre/durante/post** de
SpO₂, HR y MOV — los datos crudos de la "forma" del evento, que el
clustering de morfotipos ya resumió pero que pueden re-analizarse
arbitrariamente (re-clusterizar, comparar formas, ver shape específicas
sin pasar por la categorización β/α/etc.).

**Qué contiene.** 85,286 filas × 5 columnas. Una fila por EDO (mismo
universo que `events.parquet`). Las 3 columnas centrales son **listas
de 30 valores** cada una (representan ~1 minuto centrado en el evento):
- `spo2_curve`: lista de 30 valores de SpO₂.
- `hr_curve`: lista de 30 valores de HR.
- `mov_curve`: lista de 30 valores de movimiento.

**Para filtrar por cohorte hay que joinearlo a `events.parquet`** (esta
tabla NO tiene flags por diseño — duplicarlos en list-typed parquet es
costoso y redundante).

**Preguntas que responde.**
- "Curva promedio de SpO₂ por morfotipo (overlay de los 4 promedios)."
- "Re-clusterizar las curvas con un algoritmo distinto (DTW, autoencoder)."
- "Ejemplo visual: dame las 5 curvas más representativas de morfotipo δ."
- "¿Hay sub-tipos dentro de β que el clustering K=4 no captó?"

**Cómo leerlo.**
```python
edos = pd.read_parquet('gold/events.parquet')
curves = pd.read_parquet('gold/events_curves.parquet')
joined = edos.merge(curves, on=['night_record_id', 'ts_start'])
beta_curves = joined.loc[joined['morphotype'] == 'β', 'spo2_curve']
# Promedio de las curvas β:
import numpy as np
mean_beta = np.mean([np.array(c) for c in beta_curves], axis=0)
```

##### 3. `gold/states.parquet` — la "estratigrafía" temporal de la noche

**Para qué existe.** Para cada noche, capturar **qué estaba haciendo el
sistema cardio-respiratorio en cada momento**, en tres escalas
temporales: micro (30s), meso (5min), macro (30min). Cada ventana de
cada escala tiene un PAC state asignado (S0..S5, M0..M7, L0..L5).

Esto permite reconstruir cuándo en la noche pasó cada cosa, y eventualmente
joinear con events_gold para responder "qué PAC state estaba activo
durante cada EDO".

**Qué contiene.** 518,867 filas × 22 columnas. Una fila = una ventana
en una escala en una noche. Por noche típica de 8h hay ~960 ventanas
escala s + ~96 escala m + ~16 escala l = ~1.072 filas/noche. Total
3 escalas:

- `scale`: "s" / "m" / "l".
- `window_idx`: 0, 1, 2... orden temporal dentro de la noche.
- `t_start`, `t_end`: timestamps absolutos.
- `t_start_s`, `t_end_s`: segundos desde inicio de registro.
- `state_label`: la asignación del clustering (ej. "S3", "M5", "L1").
- `cluster_int`: int del cluster (-1 si la ventana fue droppeada).
- `dist_to_centroid`: qué tan lejos del centroide está esta ventana
  (medida de "atipicidad").
- `coverage`, `frac_wake`, `frac_light_sleep`, `frac_deep_sleep`:
  calidad y composición de la ventana.
- `training_eligible`: si esta ventana se usó para entrenar el modelo.
- Identidad + flags de cohorte + model_version.

**Preguntas que responde.**
- "¿En qué fracción de la noche el paciente está en state L3?" (junto
  con nights_gold).
- "Reconstruir el hipnograma + estratigrafía PAC para una noche dada."
- "¿Hay transiciones típicas entre states (Markov)?"
- "¿Qué PAC state estaba activo durante el EDO #47 de NR_xxx?" (join
  con events_gold).
- "Ventanas con dist_to_centroid muy alta = candidatos a outliers
  clínicos."

**Cómo leerlo.**
```python
states = pd.read_parquet('gold/states.parquet')
# Distribución de states escala s en una noche:
nr = 'NR_002e0a5021'
night_s = states[(states['night_record_id'] == nr) & (states['scale'] == 's')]
night_s['state_label'].value_counts(normalize=True)

# Reconstruir el "qué PAC state estaba activo durante cada EDO":
edos = pd.read_parquet('gold/events.parquet')
night_edos = edos[edos['night_record_id'] == nr]
night_states_l = states[(states['night_record_id'] == nr) & (states['scale'] == 'l')]
# Join temporal: para cada EDO, ventana l que lo contiene
import pandas as pd
night_edos['pac_state_l_at_event'] = night_edos['ts_start'].apply(
    lambda ts: night_states_l.loc[
        (night_states_l['t_start'] <= ts) & (night_states_l['t_end'] >= ts),
        'state_label'
    ].iloc[0] if any((night_states_l['t_start'] <= ts) & (night_states_l['t_end'] >= ts)) else None
)
```

##### 4. `gold/nights.parquet` — el fenotipo de cada noche (TABLA PRINCIPAL)

**Para qué existe.** Esta es la **tabla principal del producto**. Cada
fila representa **toda la información que se conoce de una noche
grabada**, lista para análisis estadístico, modelado o (a futuro)
salida de la app que ingiera un xlsx.

Es donde se materializa el principio data-lake: **toda noche está
exhaustivamente caracterizada con métricas absolutas, distribuciones,
métricas relativas al corpus, y métricas relativas a su propio paciente**.

**Qué contiene.** 560 filas × 146 columnas, organizadas en bloques:

- **Identidad** (3): `night_record_id`, `user_id`, `model_version`.
- **Flags de cohorte** (5): `in_quality`, `in_strict`, `in_high_tst`,
  `flag_for_review`, `b2_fail`. Permiten filtrar después.
- **Índices clásicos** (104): TST, WASO, sleep_efficiency, T90/88/85,
  AHI/ODI 2/3/4/5%, hypoxic burden, mean/median/min/std de SpO₂ y HR,
  número de EDOs, etc. Más comparaciones contra device (ahi_3_pac_v2 vs
  ahi_3_device, diff_abs, diff_rel, etc.).
- **Distribución de morfotipos** (4): `frac_morpho_α/β/γ/δ`. Suma 1.0.
  Caracterizan el "perfil de eventos" de la noche.
- **Distribución de PAC states por escala** (20): `frac_state_s_S0..S5`
  (6) + `frac_state_m_M0..M7` (8) + `frac_state_l_L0..L5` (6). Cada
  bloque suma 1.0. Caracterizan el "perfil temporal" de la noche.
- **Métricas de transición y entropía** (6): `n_transitions_state_{s,m,l}`
  (cuántos cambios entre ventanas) + `entropy_state_{s,m,l}` (Shannon
  entropy en bits — qué tan diversa es la mezcla de states).
- **Cross-night cohort-relative** (3): `ahi_3_pct_corpus`,
  `t90_frac_pct_corpus`, `odi_3_pct_corpus`. **Percentile-rank** de
  esta noche vs corpus quality (553 noches). 0.5 = mediana del corpus,
  0.95 = top 5% (severo).
- **Cross-night patient-relative** (3): `delta_ahi_3_vs_baseline_patient`,
  etc. Cuánto se desvía esta noche del **promedio de las otras noches
  del mismo paciente** (leave-one-out, requiere ≥3 noches quality).
  0 = típica para ese paciente; positivo = peor que su norma.

**Preguntas que responde.**
- "Top 10 noches con AHI3 más alto."
- "¿Hay correlación entre fracción de morfotipo β y fracción de state L3?"
- "¿Esta noche es atípica para este paciente?" (`delta_ahi_3_vs_baseline_patient` alto).
- "¿Cómo se compara esta noche con el corpus en T90?" (`t90_frac_pct_corpus`).
- "¿Las noches con más entropía de PAC state escala l tienen peor
  fragmentación?" (entropy vs n_transitions vs n_stage_shifts).
- "Diferencias entre el AHI medido por pac_v2 y el reportado por el
  device — ¿hay sesgo sistemático?"

**Cómo leerlo.**
```python
nights = pd.read_parquet('gold/nights.parquet')
quality = nights[nights['in_quality']]

# Correlación morfotipo β ↔ state L3:
quality[['frac_morpho_β', 'frac_state_l_L3']].corr()

# Noches atípicas para su paciente:
quality.loc[
    quality['delta_ahi_3_vs_baseline_patient'].abs() > 10,
    ['night_record_id', 'user_id', 'ahi_3', 'delta_ahi_3_vs_baseline_patient']
].sort_values('delta_ahi_3_vs_baseline_patient', ascending=False).head(20)

# Top severas vs corpus:
quality.loc[quality['ahi_3_pct_corpus'] > 0.95, ['user_id', 'ahi_3']].head(10)
```

##### 5. `gold/patients.parquet` — vista por paciente (descriptiva)

**Para qué existe.** Una fila resumen por paciente, con su demografía
clínica y agregados de sus noches quality. **No se usa para
inferencia** (n=12 es muy chico para tests estadísticos a este nivel),
sino para ver el **perfil del corpus** y detectar pacientes con
fenotipos extremos o atípicos.

**Qué contiene.** 12 filas × 71 columnas:

- **Identidad** (2): `user_id`, `model_version`.
- **Demografía** (7): sexo, peso_kg, talla_cm, apnea_prev, diabetes,
  hta, marcapasos. Joineadas desde `patients/clinical.csv`.
- **Conteos de noches** (5): `n_nights_total`, `n_nights_quality`,
  `n_nights_strict`, `n_nights_high_tst`, `n_nights_flag_for_review`.
- **Agregados de índices clave** (30): para 10 métricas (ahi_3,
  t90_frac, odi_3, tst_s, sleep_efficiency, mean_spo2, min_spo2,
  mean_hr, n_edos_total, mean_drop_pct), las tres estadísticas mean,
  median, sd sobre las noches quality del paciente. `sd` es NaN si el
  paciente tiene ≤1 noche quality.
- **Distribución de morfotipos PONDERADA** (4): la fracción no es
  promedio de fracciones de noches, sino que se calcula sumando todos
  los EDOs del paciente y normalizando. Esto pondera mejor a noches
  con más EDOs (más representativas).
- **Distribución de PAC states PONDERADA** (20): igual idea, pero
  contando ventanas por estado.
- **Estabilidad fenotípica** (3): `cv_ahi_3_intra_patient`,
  `cv_t90_frac_intra_patient`, `cv_odi_3_intra_patient` (CV =
  coeficiente de variación = sd/mean). CV bajo = paciente consistente
  noche a noche; CV alto = paciente muy variable.

**Preguntas que responde.**
- "¿Qué pacientes son los más severos en promedio?"
- "¿Qué paciente es el más variable (CV alto) y cuál el más estable?"
- "¿Hay relación entre BMI (peso/talla²) y AHI promedio?"
- "Distribución demográfica del corpus."
- "¿Los pacientes con muchos EDOs morfotipo α tienen comorbilidades
  específicas (HTA, diabetes)?"

**Cómo leerlo.**
```python
patients = pd.read_parquet('gold/patients.parquet')
# Top severos:
patients[['user_id', 'sexo', 'peso_kg', 'mean_ahi_3', 'cv_ahi_3_intra_patient']
        ].sort_values('mean_ahi_3', ascending=False)
# BMI:
patients['bmi'] = patients['peso_kg'] / (patients['talla_cm'] / 100) ** 2
patients[['bmi', 'mean_ahi_3']].corr()
```

#### Sidecars: la documentación viva

##### `gold/MANIFEST.json` — la "etiqueta" de la entrega

**Para qué existe.** Saber **qué entregó** este snapshot de Gold: qué
versión del modelo se usó, en qué commit del repo se generó, cuántas
filas tiene cada tabla, y la firma SHA256 de cada parquet (para
detectar corrupción o modificaciones inadvertidas).

**Qué contiene.**
- `model_version`: la versión activa de los modelos (v1 hoy).
- `git_sha`: el commit de git en que se generó.
- `tables`: para cada una de las 5 tablas, su path, n_rows, n_cols,
  size_mb, sha256_short.
- `cohort_policy`: política explícita ("B — todas con flags").
- `build_order`: el orden canónico de generación.

**Cuándo lo lees.** Antes de citar un análisis ("se hizo sobre Gold v1
generada en commit XYZ con 553 noches quality"). También después de
cualquier rebuild, para confirmar que las cardinalidades son las
esperadas.

##### `gold/nights_columns.json` — el diccionario de datos

**Para qué existe.** Documentar **qué significa cada una de las 146
columnas** de nights_gold y, crucialmente, **clasificarlas por
naturaleza** (tipo de cómputo que requirieron).

**Qué contiene.** Para cada columna:
- `name`: nombre.
- `kind`: una de 5 categorías:
  - `identity`: identificadores y trazabilidad.
  - `flag`: pertenencia a cohorte.
  - `single_night`: calculable mirando UNA noche aislada — la app
    futura podrá emitirla a partir del xlsx.
  - `cross_night_corpus`: requiere conocer el corpus completo (ej.
    percentile-rank).
  - `cross_night_patient`: requiere otras noches del mismo paciente
    (ej. delta vs baseline).
- `dtype`: tipo de dato.
- `description`: descripción humana.

**Cuándo lo lees.** Cuando estás eligiendo qué columna usar y necesitás
saber si es absoluta (interpretable por sí sola) o relativa (necesita
contexto). Y cuando llegue el día de hacer la app: las columnas
`cross_night_*` no se podrán emitir a partir de una sola noche.

**Override manual.** Si querés enriquecer una descripción (ej. agregar
referencia bibliográfica para "hypoxic_burden_88"), creá
`gold/nights_columns_descriptions.csv` con cols `column_name,description`
y re-correr el script — sobrescribe la auto.

#### Cuándo usar qué tabla — árbol de decisión

```
¿Qué nivel de pregunta?
│
├── Sobre un EVENTO específico (un EDO)
│   ├── Sus métricas / flags / morfotipo:        events.parquet
│   └── Su forma cruda (curvas):                  events_curves.parquet
│                                                   (joineado a events)
│
├── Sobre un MOMENTO de la noche (una ventana)
│   └── PAC state activo en ese momento:          states.parquet
│
├── Sobre una NOCHE entera
│   ├── Índices clásicos (AHI, T90, etc.):        nights.parquet
│   ├── Distribución de morfotipos / PAC states:  nights.parquet
│   ├── Comparación con el corpus:                nights.parquet
│   │                                              (cols *_pct_corpus)
│   └── Comparación con el propio paciente:       nights.parquet
│                                                   (cols delta_*_vs_baseline_patient)
│
├── Sobre un PACIENTE (descripción global)
│   ├── Su demografía clínica:                    patients.parquet
│   ├── Sus agregados sobre noches quality:       patients.parquet
│   ├── Su estabilidad/variabilidad:              patients.parquet
│   │                                              (cv_*_intra_patient)
│   └── Su distribución agregada de morfotipos:   patients.parquet
│                                                   (ponderada por EDOs)
│
└── Cruce de niveles (ej. EDO × PAC state)
    └── Join temporal events × states:            ambos parquets +
                                                   pandas merge
                                                   (ver receta arriba)
```

#### Glosario de conceptos clave

- **EDO** (Evento de Desaturación Oximétrica): un episodio detectado en
  el que la SpO₂ bajó por debajo de un umbral con criterios temporales
  específicos. ≈ "apnea/hypopnea" en el lenguaje clínico.
- **Morfotipo (α/β/γ/δ)**: etiqueta asignada a cada EDO por el
  clustering de Etapa 3b según la geometría conjunta de SpO₂/HR/MOV
  durante el evento. Son K=4 categorías exhaustivas. δ tiende a ser
  "leve/normal", β "desaturación marcada", etc.
- **PAC state**: etiqueta asignada a cada VENTANA temporal por el
  clustering de Etapa 4 sobre 24 features de la ventana. Hay 3
  escalas: s (30s, K=6 estados S0..S5), m (5min, K=8 M0..M7), l (30min,
  K=6 L0..L5). Distinto de "estado del sueño" (wake/N1/N2/N3/REM).
- **Cohorte quality** (553 noches): excluye 7 noches que fallaron
  silver_qc (b2_fail).
- **Cohorte strict** (511 noches): además excluye 44 noches con
  flag_for_review (clusters dominantes o outliers).
- **Single-night feature**: calculable mirando UNA sola noche aislada.
  Lo que la app del producto final podrá emitir.
- **Cross-night feature**: requiere comparar la noche con otras (corpus
  o paciente). No emitible noche a noche sin tener el corpus a mano.
- **Percentile-rank de X en el corpus quality**: el valor P ∈ [0,1] tal
  que P × 553 noches del corpus tienen X menor o igual que la noche
  actual. P=0.5 es la mediana, P=0.95 es top 5%.
- **Leave-one-out baseline**: para calcular el delta de una noche vs el
  paciente, se promedia sobre TODAS LAS OTRAS noches del paciente
  (excluyendo la noche actual). Esto evita auto-referencia y hace que
  el delta no esté forzado a 0.
- **Distribución ponderada vs promedio de fracciones**: para agregar
  morfotipos a nivel paciente, se pueden hacer dos cosas: (a) calcular
  fracción por noche y promediar (cada noche pesa igual), o (b) sumar
  todos los EDOs del paciente y dividir por el total (las noches con
  más EDOs pesan más). En `patients_gold` se usa **(b)** porque refleja
  mejor el "promedio fenotípico" del paciente sin que noches cortas
  distorsionen.
- **CV intra-paciente**: coeficiente de variación = sd/mean. Mide qué
  tan consistente es el paciente noche a noche en cada métrica. Un
  paciente con CV_ahi_3 = 0.1 tiene noches muy parecidas; con CV = 0.7
  tiene noches muy variables.

#### Recetas rápidas — código listo para copiar

```python
# ----------------------------------------------------------------- #
# Setup
# ----------------------------------------------------------------- #
import pandas as pd, numpy as np

events    = pd.read_parquet('gold/events.parquet')
curves    = pd.read_parquet('gold/events_curves.parquet')
states    = pd.read_parquet('gold/states.parquet')
nights    = pd.read_parquet('gold/nights.parquet')
patients  = pd.read_parquet('gold/patients.parquet')

# Filtrar por cohorte quality (recomendado por defecto):
nights_q = nights[nights['in_quality']]

# ----------------------------------------------------------------- #
# Receta 1: top 10 noches más severas del corpus quality
# ----------------------------------------------------------------- #
nights_q.nlargest(10, 'ahi_3')[['night_record_id', 'user_id', 'ahi_3', 't90_frac']]

# ----------------------------------------------------------------- #
# Receta 2: ¿qué pacientes tienen mucho morfotipo α?
# (Posible relevancia: α suele asociarse a EDOs con caída brusca)
# ----------------------------------------------------------------- #
patients[['user_id', 'sexo', 'peso_kg', 'mean_ahi_3', 'frac_morpho_α']
        ].sort_values('frac_morpho_α', ascending=False)

# ----------------------------------------------------------------- #
# Receta 3: noches atípicas para su paciente
# ----------------------------------------------------------------- #
atipicas = nights_q.loc[
    nights_q['delta_ahi_3_vs_baseline_patient'].abs() > 10,
    ['night_record_id', 'user_id', 'ahi_3', 'delta_ahi_3_vs_baseline_patient']
].sort_values('delta_ahi_3_vs_baseline_patient', ascending=False)

# ----------------------------------------------------------------- #
# Receta 4: distribución de PAC state escala l por morfotipo dominante
# ----------------------------------------------------------------- #
def morfotipo_dominante(row):
    cols = ['frac_morpho_α', 'frac_morpho_β', 'frac_morpho_γ', 'frac_morpho_δ']
    return row[cols].idxmax().replace('frac_morpho_', '')
nights_q['dominant_morpho'] = nights_q.apply(morfotipo_dominante, axis=1)
state_l_cols = [c for c in nights_q.columns if c.startswith('frac_state_l_')]
nights_q.groupby('dominant_morpho')[state_l_cols].mean().round(3)

# ----------------------------------------------------------------- #
# Receta 5: para una noche dada, qué PAC state escala l estaba activo
# durante cada uno de sus EDOs (join temporal)
# ----------------------------------------------------------------- #
nr = 'NR_002e0a5021'
night_edos = events[events['night_record_id'] == nr][['ts_start', 'ts_end', 'morphotype']]
night_states_l = states[(states['night_record_id'] == nr) & (states['scale'] == 'l')]

def state_at(ts):
    mask = (night_states_l['t_start'] <= ts) & (night_states_l['t_end'] >= ts)
    matches = night_states_l.loc[mask, 'state_label']
    return matches.iloc[0] if len(matches) else None

night_edos['pac_state_l'] = night_edos['ts_start'].apply(state_at)
# Cross-tabla:
pd.crosstab(night_edos['morphotype'], night_edos['pac_state_l'])

# ----------------------------------------------------------------- #
# Receta 6: BMI vs AHI a nivel paciente (n=12, solo descriptivo)
# ----------------------------------------------------------------- #
patients['bmi'] = patients['peso_kg'] / (patients['talla_cm'] / 100) ** 2
patients[['user_id', 'bmi', 'mean_ahi_3']].corr(numeric_only=True)
```

#### Limitaciones que conviene tener presentes

- **n=12 pacientes** es bajo para inferencia poblacional. La tesis se
  centra en describir el corpus y demostrar que el pipeline reproduce
  hallazgos clásicos, no en concluir patrones epidemiológicos.
- **Las cohortes quality/strict** no son ground truth clínico — son
  filtros operacionales basados en QC del registro y dominancia de
  clusters. Una noche "quality" no implica una noche "clínicamente
  buena".
- **Los morfotipos y PAC states son segmentaciones arbitrarias de un
  espacio continuo** (Roberto dixit). Cualquier umbral entre β y δ es
  convencional. Por eso Gold preserva siempre los parámetros crudos
  alongside los labels.
- **Las cross-night cohort-relative reflejan ESTE corpus** (553
  noches), no la población general. Si el corpus crece, los percentiles
  cambian — por eso versionamos Gold con `model_version` y SHA256.
- **El cross-night patient-relative requiere ≥3 noches quality**. Para
  pacientes con menos noches, esas columnas son NaN. En el corpus
  actual: 11 de 12 pacientes elegibles, 551 de 553 noches cubiertas.

### Verificaciones ejecutadas

- ✅ `pytest`: **328/328 OK** (78 nuevos en Etapa 5: 14 schemas + 13 events
  + 7 events_curves + 15 states + 26 nights + 24 patients + 15 sidecars
  + 1 viejo actualizado por list_layers).
- ✅ `build_gold_all.py` end-to-end: 5 tablas + 2 sidecars en orden, sin
  errores.
- ✅ Sanidad cross-tabla: `n_state_files` y filas en gold/states.parquet
  consistentes con `gold/MANIFEST.json`. user_ids únicos en patients_gold
  ⊆ user_ids en nights_gold ⊆ user_ids en events_gold = 12.
- ✅ Cross-night invariants: percentiles uniformes [0,1] sobre quality;
  delta-vs-baseline centrado en 0 por construcción (leave-one-out).
- ✅ Distribuciones suman 1.0 exacto en todas las tablas.

### Outputs estructurales (ubicaciones canónicas)

| archivo | filas × cols | tamaño | versionado |
|---|---|---|---|
| `gold/events.parquet` | 85,286 × 32 | 3.4 MB | NO (regenerable) |
| `gold/events_curves.parquet` | 85,286 × 5 | 8.6 MB | NO |
| `gold/states.parquet` | 518,867 × 22 | 15.1 MB | NO |
| `gold/nights.parquet` | 560 × 146 | 0.55 MB | NO |
| `gold/patients.parquet` | 12 × 71 | 49 KB | NO |
| `gold/MANIFEST.json` | — | — | **SÍ** |
| `gold/nights_columns.json` | — | — | **SÍ** |
| `gold/nights_columns_descriptions.csv` | — | — | **SÍ** (opcional) |

`.gitignore` actualizado: `gold/**` ignored, con excepciones para los
3 sidecars (fuente de verdad).

### Insumos disponibles para Etapa 6 (orquestador incremental) y futuro análisis

- 5 tablas Gold consolidadas con trazabilidad completa.
- Cohorte oficial declarado: `get_cohort_quality()` (553 NRs).
- Manifest activo `gold/MANIFEST.json` con SHA256 de cada parquet.
- Diccionario de datos `gold/nights_columns.json` con clasificación
  single_night vs cross_night → contrato de salida para la app futura.
- Validadores `validate_*_gold()` listos para usar en cualquier nuevo
  paso o análisis.

**Comandos de regeneración** (PYTHONPATH=src en todos):

```
# Pipeline completo:
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

## Etapa 6 — Orquestador incremental (staleness por mtime)

**Objetivo.** Eliminar el riesgo de error humano al re-correr el
pipeline. Antes había que recordar el orden y qué scripts disparar
cuando llegaban noches nuevas o se reentrenaba un modelo. Ahora un
único comando detecta qué está stale y propone (o ejecuta) el plan
mínimo para volver a estado consistente.

### Decisiones cerradas pre-implementación

- **P1 — mtime puro** (no SHA256 de inputs). Más rápido, suficiente
  porque la promesa es "los archivos llegan tal como vienen, no se
  modifican manualmente".
- **P2 — A** (auto-invalidación por modelo). El reentrenamiento toca
  los mtimes de `models/*` → la detección los ve más nuevos que los
  outputs downstream y los marca stale. Sin necesidad de leer
  `model_version` del KV metadata.
- **P3 — Híbrido** (sub-comandos + default sensato). Un solo
  `scripts/orchestrate.py` con sub-comandos `status`/`plan`/`run`. Sin
  sub-comando, default = `run` interactivo (= ver plan + prompt y/N).
- **P4 — Detección de gold por triple criterio**: mtime de archivos
  upstream (events/, states/) + mtime de `scripts/build_*_gold.py` +
  mtime de `models/MANIFEST.json`. Si alguno es más nuevo que la tabla
  más vieja, gold stale.
- **P5 — Solo procesa lo que ya está en bronze/** (no incluye `raw →
  bronze` porque el naming de raw es arbitrario y NR se calcula del
  contenido). Para xlsx nuevos, correr `scripts/run_bronze.py` antes.

### Limitación conocida y plan de mejora futura

Los scripts `silver` y `events_pipeline` son **batch-full** — procesan
los 560 NRs siempre, no aceptan filtro per-NR. El orquestador detecta
stale por NR (útil para diagnóstico) pero al ejecutar corre el script
entero. Mejora futura: agregar `--only-stale NR1,NR2,...` a esos
scripts para que el orquestador pueda ser quirúrgico. Por ahora,
acepta el costo de re-procesar todo si hay 1 noche stale.

### Paso 1 — `src/pac/orchestrator.py` (módulo puro)

Biblioteca pura sin side-effects: define etapas, detecta staleness,
arma plan. Testeable sin tocar disco real (todos los paths son
constantes overrideables vía monkeypatch).

**Componentes principales:**

- `StageStatus` (dataclass): nombre, n_total, n_stale, lista de NRs
  stale, razones por NR.
- `PipelineStatus`: dict de `StageStatus` por etapa.
- `detect_silver_stale()`, `detect_events_stale()`,
  `detect_states_stale()`, `detect_gold_stale()`: detección
  por etapa.
- `detect_all()`: las 4 etapas en una pasada.
- `compute_plan(status)`: lista ordenada de pasos (con propagación
  downstream — si silver stale, se incluye también events/states/gold).
- `render_status_text()`, `render_plan_text()`: pretty-print.

**Reglas de detección:**

| etapa | regla |
|---|---|
| silver | bronze/<NR>.parquet mtime > silver/<NR>.parquet mtime, o silver missing |
| events | silver mtime > events/<NR>_edos mtime, o `models/edo_morphotype_*` mtime > events mtime |
| states | events/<NR>_edos mtime > states/<NR>.parquet mtime, o `models/pac_states_*` mtime > states mtime |
| gold | falta tabla, o cualquier upstream (events/, states/, build_*_gold.py, MANIFEST.json) más nuevo que la tabla más vieja |

**Filtrado estricto de NRs**: los NRs se identifican por regex
`^NR_[0-9a-f]{10}\.parquet$` para evitar contar `*_qc.parquet`,
`*_edos.parquet` etc. como NRs propios.

### Paso 2 — `scripts/orchestrate.py` (CLI híbrido)

Hybrid CLI con 4 modos de uso:

```
python scripts/orchestrate.py                # = `run` interactivo (default)
python scripts/orchestrate.py status         # solo inventario
python scripts/orchestrate.py status -v      # con detalle de NRs stale
python scripts/orchestrate.py plan           # imprime plan, no ejecuta
python scripts/orchestrate.py run            # ejecuta tras prompt y/N
python scripts/orchestrate.py run --yes      # ejecuta sin prompt (CI)
python scripts/orchestrate.py run --dry-run  # alias de plan
python scripts/orchestrate.py run --quiet    # output mínimo
```

`status` y `plan` devuelven exit code 1 si hay etapas stale (útil para
CI: `orchestrate status || alertar`).

**Plan emitido en orden con propagación**: si `events` está stale, el
plan incluye `events_pipeline` + `apply_morphotypes` + `apply_pac_states` +
`build_gold_all` aunque cada uno individualmente parezca limpio (porque
al re-correr la upstream, los mtimes propagados invalidan los downstream).

**Pipeline modelado** (en orden):

| etapa | comando(s) |
|---|---|
| silver | `python -m pac.silver` |
| events | `python -m pac.events_pipeline` |
| events (cont.) | `python scripts/apply_morphotypes.py` (agrega columna `morphotype`) |
| states | `python scripts/apply_pac_states.py --mode batch` |
| gold | `python scripts/build_gold_all.py --quiet` |

Nota: events tiene **dos comandos** porque `events_pipeline` produce
los EDOs sin la columna morphotype, y `apply_morphotypes` la agrega
después como un paso separado (modelo del clustering de morfotipos).

### Paso 3 — Tests + docs

`tests/test_orchestrator.py` (22 tests), 100% sobre `tmp_path` con
monkeypatch — sin depender del corpus real:

- **TestListNrsIn** (4): regex filtra `_qc`/`_edos`, ignora dirs
  inexistentes/vacíos.
- **TestCleanPipeline** (2): pipeline coherente → nada stale, plan vacío.
- **TestSilverStale** (2): missing output, bronze más nuevo.
- **TestEventsStale** (2): silver más nuevo, modelo morfotipos más
  nuevo (validación de P2).
- **TestStatesStale** (1): modelo PAC más nuevo (validación de P2).
- **TestGoldStale** (4): missing table, upstream data más nuevo, build
  script más nuevo (P4), MANIFEST bumpeado.
- **TestPlanPropagation** (3): silver stale → 5 pasos (incluye 2 de
  events), events stale → 4 pasos, gold-only → 1 paso.
- **TestRender** (4): renders clean/stale, plan vacío/con pasos.

### Verificaciones ejecutadas

- ✅ `pytest`: **350/350 OK** (22 nuevos en Etapa 6, sin regresión sobre
  328 de Etapa 5).
- ✅ Smoke `orchestrate status` sobre el corpus real: detecta
  correctamente stale por mtime tras correr `python -m pac.silver` y
  `python -m pac.events_pipeline` accidentalmente.
- ✅ Filtrado de NRs: silver/ tiene 1120 archivos (560 NR + 560 _qc) y
  el orquestador correctamente cuenta 560.
- ✅ Plan propagation: hacer silver stale produce 5 pasos en el plan
  (silver + 2 de events + states + gold).

### Outputs estructurales

- `src/pac/orchestrator.py` (~340 líneas, módulo puro testeable).
- `scripts/orchestrate.py` (CLI híbrido).
- `tests/test_orchestrator.py` (22 tests determinísticos).

### — — — Guía didáctica del orquestador — — —

> Sub-sección autocontenida pensada para que un lector futuro entienda
> cómo usar el orquestador sin leer todo el doc.

#### Cuándo usarlo

Cualquier momento en que **algo cambió** en el pipeline:

- Agregaste noches nuevas en `bronze/` (después de `run_bronze.py`).
- Reentrenaste un modelo (vía `retrain_check.py` o manual).
- Modificaste el código de algún `build_*_gold.py`.
- Bumpeaste el manifest (`generate_manifest.py --bump v2`).
- Pasaron meses y no recordás si las tablas gold están al día.

#### Cómo usarlo (3 verbos + 1 default)

```
python scripts/orchestrate.py status
```
**¿Qué pregunto?** "¿Está todo al día?" Inventario rápido sin tocar
nada. Devuelve exit 1 si hay stale (útil para crontab / CI: te alerta
si hay drift).

```
python scripts/orchestrate.py plan
```
**¿Qué pregunto?** "Si te dejo trabajar, ¿qué pensás hacer?" Imprime
status + plan detallado. NO ejecuta, NO pregunta.

```
python scripts/orchestrate.py run
```
**¿Qué pregunto?** "Hacelo." Imprime plan, prompt y/N, ejecuta si
confirmás. Para CI: `--yes` salta el prompt.

```
python scripts/orchestrate.py
```
**Sin sub-comando** = `run` interactivo. Para uso humano del día a día.

#### Qué NO hace

- **No ingiere xlsx nuevos**. Para eso correr `scripts/run_bronze.py`
  antes (ese sí puede ser quirúrgico con `--limit`).
- **No reentrena modelos**. Para eso `scripts/retrain_check.py`.
- **No es per-NR**. Si hay 1 noche stale en silver, corre silver para
  las 560. Es el costo de no haber tocado los scripts existentes.

#### Qué SÍ detecta automáticamente

- Noches nuevas (bronze nuevo → silver missing → cascada downstream).
- Reentrenamientos (mtime de modelos cambió).
- Cambios en código (mtime de scripts cambió).
- Bumps de manifest (mtime de MANIFEST.json cambió).
- Tablas gold faltantes.

### Comandos de regeneración

```
# Estado actual (no hace nada):
python scripts/orchestrate.py status

# Ver plan (no hace nada):
python scripts/orchestrate.py plan

# Ejecutar todo:
python scripts/orchestrate.py run --yes

# Tests:
python -m pytest tests/test_orchestrator.py
```

---

## Etapa 7 — Validación final + release (v1.0-tesis)

**Objetivo.** Cierre del proyecto en estado entregable. Verificación
end-to-end, audits, doc de cara al usuario, tag de release.

### Decisiones cerradas pre-implementación

- **Q1 — Alcance del release**: A (solo defensa de tesis, no GitHub
  público). C posible después si se decide publicar.
- **Q2 — Items opcionales**: 7 (lint con ruff) y 8 (verificación de
  lock vigente) SÍ. 9 (reporte ejecutivo) y 10 (stub app) NO en v1.0.
- **Q3 — Tag de git**: `v1.0-tesis`.
- **Q4 — README.md**: español (consistente con resto de docs).
- **Q5 — Full e2e run**: primera corrida hecha por Claude (gold
  pipeline 27.8s OK), Roberto confirma comandos en su entorno.

### Pieza A — Full end-to-end + audit de tests

- ✅ Suite **350/350 OK** distribuida en 21 archivos de test.
- ✅ `build_gold_all.py`: 27.8s para regenerar las 5 tablas + 2
  sidecars desde events/+states/.
- ✅ Cobertura por módulo: 21 archivos test sobre 15 módulos `pac.*`
  (≈140%), todos los módulos del pipeline cubiertos.

### Pieza B — Revisión de PAC_v2_ANALISIS.md

Refactor mayor (692 → 1124 líneas) para alinear el plan analítico
con el estado real entregado en Gold v1:

- §0 nueva: mapa visual del proyecto con grafo Mermaid del pipeline
  completo + grafo de joins entre 5 tablas + grafo de cohortes +
  tabla de docs y rol de cada uno. **Pedido explícito de Roberto**.
- §2.1 / §3.1 / §3.2 / §4.1 refactorizadas con tablas
  "presente HOY en Gold v1" vs "NO está — derivar en análisis".
  Anclar al estado real evita confusión entre lo aspiracional y lo
  entregado.
- Nombres de columnas alineados con `gold/nights_columns.json`
  (`t90_frac` no `t90_pct`, `frac_state_s_S0..S5` no
  `pct_time_state_s_k`, etc.).
- §5.1 aclarada: el cruce PAC × EDO se materializa via join temporal
  (no está en columnas — Q4 deferida en Etapa 5). Snippet de código
  incluido.
- §7.5 nueva: política de uso correcto de cross-night cohort y
  patient (cuándo usar, cuándo no).
- §8 marcada explícitamente como post-tesis.
- Bitácora con 4 entradas nuevas (4.6, 5, 6, esta revisión).

### Pieza C — README.md + CHANGELOG.md (en español)

- `README.md`: punto de entrada para usuario nuevo (qué es PAC_v2,
  estructura, cómo arrancar desde cero, cómo procesar nuevas noches,
  cómo reentrenar, ejemplo de uso de Gold). Reemplaza el README viejo
  (que estaba en Etapa 0).
- `CHANGELOG.md`: one-liner por etapa cerrada (0 → 7), agrupadas por
  tag de release (v1.0-tesis).

### Pieza D — Lint con ruff + verificación de lock

- `ruff check src/ scripts/ tests/`: 107 errores detectados, 66
  auto-fixables aplicados. 41 restantes son cosméticos (E402 imports
  después de sys.path manipulation, E702/E701 multi-statement, F841
  unused vars en scripts) — no rompen tests, aceptados como
  convenciones de scripts.
- Lock: `scripts/freeze_lock.sh` con sanity-check de `VIRTUAL_ENV`.
  El usuario lo regenera desde su venv para tener el lock real
  (en sandbox no hay venv activo).
- Tests post-ruff: **350/350 OK** (sin regresión).

### Pieza E — Audit de archivos huérfanos + TODOs

- TODOs/FIXMEs en `src/`: **0** (limpio).
- TODOs/FIXMEs en `scripts/`: 0 reales (3 matches son la palabra
  "TODOS" en frases en español).
- Archivos huérfanos en disk: `*.html` y `.Rhistory` (artefactos de
  preview MD y R) → agregados al `.gitignore`.

### Pieza F — Cierre Etapa 7

- Actualización `PAC_v2_ETAPAS.md` (esta sección) y
  `PAC_v2_HANDOFF.md`.
- Tag git: `v1.0-tesis` en el commit de cierre.
- Suite final: **350/350 OK**.

### Estado del proyecto al cierre

| componente | estado |
|---|---|
| Pipeline (bronze → silver → events → states → gold) | ✅ funcional, 560 noches procesadas |
| 5 tablas Gold + 2 sidecars | ✅ versionados los sidecars, parquets regenerables |
| Modelos congelados v1 | ✅ morphotypes K=4, PAC states K=6/8/6 |
| Validación de schemas | ✅ 10 schemas + 10 validators en `pac.schemas` |
| Cohortes | ✅ 5 cohortes en `pac.cohorts`, oficial = quality (553) |
| Manifest + retrain gateway | ✅ `models/MANIFEST.json` + `retrain_check.py` |
| Orquestador incremental | ✅ `scripts/orchestrate.py` con CLI híbrido |
| Documentación | ✅ README + CHANGELOG + ETAPAS + HANDOFF + ANALISIS |
| Tests | ✅ 350/350, 21 archivos |
| Lint | ✅ ruff aplicado, residuales cosméticos |

### Limitaciones conocidas (documentadas para post-tesis)

1. **silver/events_pipeline son batch-full** — el orquestador detecta
   stale por NR pero al ejecutar corre el script entero. Mejora
   futura: agregar `--only-stale NR1,NR2` a esos scripts.
2. **App diferida** — el contrato técnico está en
   `gold/nights_columns.json` (cols `single_night` vs `cross_night`).
3. **Features extendidas** del EDO (asymmetry_ratio,
   lag_nadir_to_hr_peak_s, etc.) no están en Gold v1 — derivar
   on-the-fly en notebooks `analyses/` cuando se necesiten.
4. **Edad** no está en `patients_gold` — requiere PII
   (`patient_registry.csv`, gitignored).

### Cómo retomar el proyecto post-tesis

```
# Verificar que todo está al día:
python scripts/orchestrate.py status

# Ver qué versión de modelo está activa:
cat models/MANIFEST.json | python -c "import sys, json; print(json.load(sys.stdin)['model_version'])"

# Lo que se entregó en la tesis:
git log --oneline v1.0-tesis | head -20
git show v1.0-tesis  # commit del cierre
```

---

## Etapa 6.1 — Hardening del orquestador (SHA modelo, no mtime)

**Objetivo.** Eliminar el falso positivo "states STALE" del orquestador
después de cada lote nuevo de noches. La heurística mtime original era
demasiado conservadora: cuando `apply_morphotypes` reescribía los
`events/*.parquet` solo para agregar la columna `morphotype`, todos los
`states/*.parquet` quedaban con mtime viejo y el orquestador los marcaba
stale, aunque eran funcionalmente válidos (apply_pac_states usa las 24
features de geometría/IRD, NO la columna morphotype).

### Decisión Roberto

> "si voy a ir agregando más registros tipo en batch, el STALE va a
> seguir saliendo. ¿No se podría arreglar para que en el futuro no
> aparezca? Me parece que el momento de hacer el esfuerzo computacional
> es ahora."

Q1 = B (touch + verificación SHA del modelo, robusta). Q2 = no
extender a events ahora. Q3 = etapa 6.1 + tag `v1.1-tesis`.

### Pieza A — `apply_pac_states.py`: SHA modelo + skip-touch

- Nuevo helper `compute_models_sha256(models_dir)` → SHA256 (16 chars)
  de los 3 archivos `pac_states_{s,m,l}_centroids.csv` concatenados.
  Es la "huella digital" del estado del modelo PAC.
- `write_states_parquet()` ahora persiste `model_centroids_sha256` en
  KV metadata de cada `states/<NR>.parquet`.
- Lógica de skip-if-exists ampliada a 4 casos por NR:
  - **(a) SHA persistido == SHA actual** → `Path.touch()` (refresca
    mtime) + skip. El states está vigente.
  - **(b) SHA persistido != SHA actual** → re-procesar (modelo
    reentrenado, states obsoleto).
  - **(c) SHA ausente** (states pre-Etapa 6.1) → REHIDRATAR: leer/
    reescribir el parquet con SHA agregado al KV. **Barato**: no
    recomputa windows ni aplica el modelo, solo serializa metadata.
    Tarda segundos para 560 noches.
  - **(d) NR sin states** → procesar normalmente.

### Pieza B — `orchestrator.py`: detección por SHA en lugar de mtime

- Nuevo helper `_compute_pac_models_sha256()` (espejo del de apply,
  por consistencia).
- Nuevo helper `_read_states_models_sha256(parquet_path)` — lee
  el KV.
- `detect_states_stale()` reescrito:
  - Si SHA persistido == SHA actual → vigente (ignora mtime).
  - Si SHA difiere → stale por modelo cambiado.
  - Si SHA ausente o modelo faltante → fallback a mtime (compatibilidad
    con states pre-Etapa 6.1).

### Pieza C — Tests + docs

- `tests/test_apply_pac_states.py`: 1 test adaptado (firma de
  `write_states_parquet` agregó `models_sha256`) + verificación de
  que el KV `model_centroids_sha256` se persiste.
- `tests/test_orchestrator.py`: 1 test viejo adaptado (mensaje de
  reason cambió a incluir "(no SHA)") + nueva clase
  `TestStatesStaleByShaModel` con 4 tests:
  - `test_sha_match_means_not_stale` — SHA igual + events más nuevo
    → NO stale (caso del falso positivo original).
  - `test_sha_mismatch_means_stale` — SHA difiere → stale por modelo.
  - `test_no_sha_falls_back_to_mtime` — KV ausente → fallback mtime.
  - `test_compute_sha_returns_none_when_models_missing`.

### Verificaciones ejecutadas

- ✅ `pytest`: **354/354 OK** (350 + 4 nuevos en 6.1).
- ✅ Smoke en sandbox con corpus real:
  - `apply_pac_states --mode batch`: rehidrató 560 noches en segundos
    (sin recomputar nada).
  - `orchestrate status`: states pasó de STALE (560/560) a OK (560).
  - `orchestrate run --yes`: solo regeneró gold (26.4s), states quedó
    vigente. Status final: ✓ Todo up-to-date.
- ✅ Consistencia entre helpers: `apply_pac_states.compute_models_sha256()`
  y `orchestrator._compute_pac_models_sha256()` devuelven el MISMO
  SHA sobre los mismos centroides (verificado).

### Beneficio operacional para Roberto

Sin Etapa 6.1: cada lote nuevo de pacientes → "states STALE" después
del run, requiere ignorar manualmente o `--force` (15-20 min).

Con Etapa 6.1: cada lote nuevo:
1. Pipeline corre (events + apply_morphotypes + apply_pac_states).
2. apply_pac_states procesa solo noches nuevas; las viejas → touch + skip.
3. orchestrate status → ✓ Todo up-to-date.

Si el modelo cambia (vía `retrain_check.py`): el SHA cambia
automáticamente, todos los states viejos → stale honesto, se
regeneran con `apply_pac_states --force`.

### Outputs estructurales (modificados en 6.1)

- `scripts/apply_pac_states.py` (+SHA helper, +rehydrate, lógica skip
  ampliada).
- `src/pac/orchestrator.py` (+SHA helpers, `detect_states_stale`
  reescrito).
- `tests/test_apply_pac_states.py` (1 test adaptado).
- `tests/test_orchestrator.py` (1 test adaptado + 4 nuevos).
- KV metadata de `states/*.parquet` ahora incluye `model_centroids_sha256`.

### Tag

`v1.1-tesis` — release post-defensa con orquestador honesto. Compatible
con `v1.0-tesis` para análisis (no cambia ningún output, solo metadata
del KV).

---

*Fin del pipeline — proyecto cerrado en v1.1-tesis. Las secciones
siguientes documentan la capa de análisis sobre Gold.*

---

## Capa de análisis — Features derivadas (post-pipeline)

### Diseño: por qué no modificar el pipeline

El pipeline genera Gold de forma determinística a partir de datos
crudos y modelos entrenados. Introducir features que requieren juicio
analítico (interpretación de resultados, decisiones de agrupación
basadas en análisis exploratorio) dentro del pipeline mezcla dos
responsabilidades distintas:

- **Pipeline**: computa, no interpreta. Sus outputs son reproducibles
  mecánicamente desde `raw/` + `models/`.
- **Análisis**: interpreta, agrupa, decide. Sus outputs dependen del
  corpus actual y de decisiones que pueden evolucionar.

Por eso las features derivadas del análisis no van a `events.parquet`
(que regenera el pipeline en cada run) sino a una tabla separada
`gold/events_analysis.parquet`, generada y mantenida por los notebooks.
Si en el futuro una feature madura y se estabiliza, se puede promover
al pipeline con un cambio formal en `scripts/` + tests + CHANGELOG.

### `gold/events_analysis.parquet`

Tabla de análisis derivada de `gold/events.parquet`. Contiene columnas
clave de identidad y las features analíticas adicionales. **No se
genera en el pipeline** — se genera en `notebooks/NB01_morfologia_eventos.ipynb`
y debe regenerarse si se re-entrena el modelo de morfotipos.

Columnas:

| Columna | Origen | Descripción |
|---|---|---|
| `night_record_id` | events | Identificador de noche |
| `ts_start` | events | Timestamp de inicio del evento |
| `user_id` | events | Identificador de paciente |
| `morphotype` | events | Morfotipo rule-based (α…κ, 10 clases) |
| `morphotype_curve` | events | Morfotipo data-driven (C1–C5) |
| `morphotype_severity` | **derivada** | Agrupación binaria de severidad (ver abajo) |
| `in_quality` | events | Flag de cohorte quality |
| `duration_s` | events | Duración del evento en segundos |
| `nadir_spo2_delta` | events | Nadir ΔSpO₂ vs baseline (pp) |

### Feature: `morphotype_severity`

**Definición:**
```
low  → C1 (Subcrítico), C2 (Leve/Gradual)
high → C3 (Severo Agudo), C4 (Moderado-V), C5 (Severo Progresivo)
```

**Rationale:** el análisis de cross-tabulation entre morfotipos
rule-based y data-driven (NB01) reveló un corte natural en la
distribución de eventos:

- **C1+C2 (~89% de eventos):** desaturación mínima o gradual.
  Clínicamente de bajo riesgo de forma aislada. β (87% → C1),
  γ, η, κ mapean consistentemente a este grupo.
- **C3+C4+C5 (~11% de eventos):** desaturación significativa
  (nadir −7.9 pp a −15.3 pp). Alto riesgo clínico. δ (83% → C5),
  ε (68% → C3), ι (48% → C4) mapean consistentemente a este grupo.

**Por qué dos grupos y no cinco:**
La dicotomía low/high es útil para modelos de predicción binaria
(¿este evento importa?) y para resúmenes nocturnos (proporción de
eventos de alto riesgo). No reemplaza a `morphotype_curve` — C3/C4/C5
tienen mecanismos temporales distintos (nadir precoz vs tardío vs
progresivo) que son relevantes para el análisis mecanístico y los
PAC states. Ambas columnas coexisten para usos complementarios.

**Generación:**
```python
SEVERITY_MAP = {'C1': 'low', 'C2': 'low',
                'C3': 'high', 'C4': 'high', 'C5': 'high'}
ev['morphotype_severity'] = ev['morphotype_curve'].map(SEVERITY_MAP)
```
Los eventos sin `morphotype_curve` (duración > 180s, excluidos del
training del modelo de curvas) quedan como `NaN` en esta columna.

**Distribución esperada (cohorte quality, 85,277 eventos):**
- `low`:  ~76,000 eventos (~89%)
- `high`: ~9,000 eventos (~11%)
- `NaN`:  ~9 eventos (duración > 180s, fuera del modelo)

*Sección agregada durante análisis de NB01 — 2026-05-17.*
