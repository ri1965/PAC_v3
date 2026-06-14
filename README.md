# PAC_v2

> Pipeline de procesamiento y análisis de registros polisomnográficos
> simplificados (señales SpO₂, HR, movimiento) para caracterización
> dinámica de la apnea del sueño. Maestría en Data Science, Universidad
> Austral. Autor: Roberto Inza.

**Estado**: v1.2-tesis. 560 noches quality (12 pacientes) · 540 noches cohorte strict (8 pacientes) ·
85,277 EDOs quality · 11 parquets Gold · NB01–NB08 completos · app Streamlit operativa.

## ¿Qué es PAC_v2?

Un pipeline que toma un registro nocturno crudo (`.xlsx` exportado del
device) y lo convierte en una **caracterización rica del sueño**:

- **Eventos** (EDOs) detectados con su geometría completa y morfotipo
  asignado (α/β/γ/δ).
- **Estados PAC** multi-escala (s=30s, m=5min, l=30min) que capturan la
  dinámica temporal del sueño.
- **Índices clásicos** (AHI, ODI, T90, hypoxic burden, etc.) en gemelo
  con los reportados por el device.
- **Tabla integrada por noche** con 146 columnas listas para análisis
  estadístico, modelado o visualización.

La narrativa central de la tesis: construir un "gemelo digital nocturno"
con señales pobres (sin EEG/EMG/EOG) que vaya más allá de los índices
agregados clásicos, usando estados PAC como contexto dinámico de los
EDOs.

## Estructura del proyecto

```
PAC_v2/
├── raw/              .xlsx de origen (no versionados)
├── bronze/           parquet con señales canonizadas (gitignored)
├── silver/           parquet con QC y signals limpias (gitignored)
├── events/           EDOs + curvas + indices por noche (gitignored)
├── states/           PAC states por ventana × escala (gitignored)
├── gold/             5 tablas consolidadas (gitignored) + 2 sidecars (versionados)
├── models/           centroides + metadata + MANIFEST (versionados)
├── patients/         clinical.csv (versionado), patient_registry.csv (PII, local)
├── reports/          QC summaries + dashboards
├── src/pac/          módulos: bronze, silver, events, morphotypes, states,
│                     windows, indices, schemas, cohorts, orchestrator
├── scripts/          CLI runners + builders + orquestador
└── tests/            350 tests
```

## Documentos

| Documento | Para qué |
|---|---|
| `README.md` (este) | Punto de entrada — qué es y cómo arrancar |
| `PAC_v2_ETAPAS.md` | **Lo construido** — qué se hizo paso a paso, decisiones de implementación |
| `PAC_v2_HANDOFF.md` | **Estado del traspaso** — handoff entre sesiones |
| `PAC_v2_ANALISIS.md` | **Lo que se va a analizar** — plan analítico, hipótesis, base de la tesis |
| `CHANGELOG.md` | Historia de cambios por etapa |
| `gold/MANIFEST.json` | Trazabilidad de la entrega Gold (sha256 + counts) |
| `gold/nights_columns.json` | Diccionario de las 146 columnas de nights_gold |
| `PAC_v2_PipelineDAG.html` | DAG interactivo del pipeline (abrir en browser) |
| `docs/PAC_v2_Maestro_01_Pipeline.docx` | Arquitectura del pipeline de datos |
| `docs/PAC_v2_Maestro_02_Analisis.docx` | Notebooks NB01–NB08: diseño, resultados, Gold |
| `docs/PAC_v2_Maestro_03_App.docx` | App Streamlit: pipeline de inferencia, tabs, IA |
| `informes_nb/` | Informes clínicos por notebook + Marco de Publicaciones |

## Cómo arrancar (entorno limpio)

### 1. Setup

```bash
git clone <repo>
cd PAC_v2
conda activate apnea
pip install -r requirements.txt
```

**Registrar el kernel de Jupyter** (una vez por entorno):

```bash
python -m ipykernel install --user --name apnea --display-name "Python (apnea)"
```

Después de esto, en Jupyter seleccioná el kernel **Python (apnea)** antes de correr cualquier notebook.

### 2. Front door único: `run.py`

Todo el pipeline se maneja desde `run.py` en la raíz. Inyecta
`PYTHONPATH=src` automáticamente y unifica los flujos típicos:

```bash
python run.py            # AUTO: ingest si hay xlsx nuevos + orquestador interactivo
python run.py status     # inventario (bronze coverage + estado del orquestador)
python run.py plan       # plan sin ejecutar
python run.py ingest     # solo raw → bronze
python run.py update     # solo silver/events/states/gold (sin bronze)
python run.py all --yes  # todo end-to-end sin prompts
python run.py validate   # sanity check del scaffold (dirs + identity)
python run.py --help     # ayuda completa
```

### 3. Casos típicos

**Verificar que el repo está al día:**

```bash
python run.py status
```

Si dice "✓ Todo up-to-date" — listo. Si hay etapas stale, te dice qué
correr.

**Procesar todo desde cero (raw/ con xlsx, resto vacío):**

```bash
python run.py all --yes
```

Tiempo esperado para 560 noches: ~30-60 min según hardware.

**Ingest de noches nuevas (tirar xlsx en `raw/`):**

```bash
python run.py            # detecta los xlsx nuevos y propone ingest + orquestador
```

**Re-procesar tras modificar un script del pipeline (sin tocar bronze):**

```bash
python run.py update
```

### 4. Reentrenar (cuando el corpus crece)

`run.py` no envuelve el reentrenamiento todavía — sigue siendo manual:

```bash
PYTHONPATH=src python3 scripts/retrain_check.py        # detecta drift, pregunta
PYTHONPATH=src python3 scripts/generate_manifest.py --bump v2
python run.py update                                   # regenera todo downstream
```

### 5. App interactiva (Streamlit)

La app carga un `.xlsx` nocturno y devuelve análisis completo en 5 tabs interactivos
con Risk Score, morfotipos, estados PAC, historia nocturna e informe IA.

```bash
conda activate apnea
cd /Users/ri1965/Proyectos/PAC_v2   # ← importante: lanzar desde el root del proyecto
streamlit run app/app.py
```

Se abre en **http://localhost:8501**. Si Streamlit no está instalado en el entorno:

```bash
pip install streamlit>=1.30 anthropic>=0.25 openai>=1.0
```

**App de diagnóstico** (debug paso a paso del pipeline, puerto separado):

```bash
streamlit run app/diag_streamlit.py --server.port 8502
```

> El informe IA del Tab 5 usa **LM Studio** por defecto (modelo local, puerto 1234).
> Asegurate de tener LM Studio corriendo con un modelo cargado antes de generarlo.
> Claude API es la alternativa si configurás `ANTHROPIC_API_KEY` en el entorno.

### 6. Scripts originales (uso avanzado)

`run.py` es un wrapper fino: los scripts subyacentes
(`scripts/run_bronze.py`, `scripts/orchestrate.py`,
`scripts/build_gold_all.py`) siguen funcionando igual y soportan flags
adicionales no expuestos en `run.py`. Si necesitás algo exótico,
invocalos directo con `PYTHONPATH=src python3 scripts/<nombre>.py`.

## Cómo usar Gold para análisis

Gold tiene 11 parquets: 5 core pipeline + 6 analíticos (generados por NB01–NB08).

```python
import pandas as pd

# ── Core pipeline ──────────────────────────────────────────────────────────
events    = pd.read_parquet('gold/events.parquet')           # 85286 × 33
curves    = pd.read_parquet('gold/events_curves.parquet')    # 85286 × 5
states    = pd.read_parquet('gold/states.parquet')           # 518867 × 22
nights    = pd.read_parquet('gold/nights.parquet')           # 560 × 146
patients  = pd.read_parquet('gold/patients.parquet')         # 12 × 71

# ── Analíticos (NB01–NB08) ────────────────────────────────────────────────
ev_analysis   = pd.read_parquet('gold/events_analysis.parquet')          # 85286 × 9   (NB01)
ev_states_ms  = pd.read_parquet('gold/event_states_multiscale.parquet')  # 85258 × 48  (NB04)
night_feats   = pd.read_parquet('gold/night_features.parquet')           # 560 × 36    (NB03)
night_ms      = pd.read_parquet('gold/night_multiscale_features.parquet')# 560 × 53    (NB04)
transitions   = pd.read_parquet('gold/transition_matrices.parquet')      # 90 × 5      (NB05)
window_risk   = pd.read_parquet('gold/window_risk_predictions.parquet')  # 452955 × 16 (NB08)

# Filtrar por cohorte oficial (8 pacientes strict)
nights_q = nights[nights['in_quality']]    # 560 noches (todas con ≥1 EDO)

# Top 10 noches con más severidad
nights_q.nlargest(10, 'ahi_3')[['night_record_id', 'user_id', 'ahi_3']]
```

Ver más recetas en `PAC_v2_ETAPAS.md` → "Guía didáctica de Gold" →
"Recetas rápidas".

## Modelo de identidad (2 archivos)

| archivo | contenido | git |
|---|---|---|
| `patient_registry.csv` | `patient_id;nombre;apellido;fecha_nacimiento` | ❌ local (PII) |
| `clinical.csv` | `patient_id;sexo;peso_kg;talla_cm;apnea_prev;diabetes;hta;marcapasos` | ✅ |

Separador único: `;`. El mapping `source_exam_id → patient_id` está
implícito en los xlsx (campo `user_id`) y se persiste como metadata KV
de cada parquet bronze.

## Tests

```bash
PYTHONPATH=src python3 -m pytest                # 350 tests, ~25s
PYTHONPATH=src python3 -m pytest tests/test_orchestrator.py -v
```

## Política sobre PII

- `patients/patient_registry.csv` (nombres, fechas de nacimiento) **NO se
  versiona**. Está en `.gitignore`.
- `patients/clinical.csv` (datos clínicos pseudonimizados por
  `patient_id`) sí se versiona.
- Los archivos `bronze/`/`silver/`/`events/`/`states/`/`gold/*.parquet`
  son regenerables desde raw/. No contienen PII (solo `user_id`).

## Roadmap

- ✅ Etapa 0 — Scaffold + identidad
- ✅ Etapa 1 — Bronze (ingest .xlsx)
- ✅ Etapa 1.1 — Auto-registro de pacientes nuevos
- ✅ Etapa 2 — Silver QC
- ✅ Etapa 3 — Events (EDOs + IRD + índices)
- ✅ Etapa 3b — EDO Morphotyping (KMeans K=5: morfotipos C1–C5)
- ✅ Etapa 4 — PAC States multi-escala (S: K=7 · M: K=5 · L: K=4)
- ✅ Etapa 4.6 — Pre-Gold hardening (lock + schemas + cohorts + manifest + retrain gateway)
- ✅ Etapa 5 — Gold (data lake unificado APNEA+PAC)
- ✅ Etapa 6 — Orquestador incremental
- ✅ Etapa 7 — Validación final + release v1.0-tesis
- ✅ Post-tesis: app interactiva Streamlit (xlsx → 5 tabs + informe IA)
- ✅ Post-tesis: NB01–NB08 completos (morfología → severidad → lead time)
- ✅ Post-tesis: Gold 11 parquets (5 core + 6 analíticos)
- ⏳ Próximo: Tab 6 (Riesgo & Lead Time) — integrar NB07 + NB08 en app

## Notebooks — Orden de ejecución (NB01–NB08)

Los notebooks en `notebooks/` deben correrse **en orden**, cargando los modelos
guardados en `models/` — **sin re-fitear** (ver aviso abajo).

| Notebook | Contenido | Gold producido |
|---|---|---|
| NB01 | Fenotipado morfológico de EDOs — PCA + KMeans K=5 (C1–C5) | `events_analysis.parquet` |
| NB02 | Índice de Reactividad Autonómica (ARI) — hr\_gain + mov\_gain | (en memory, informa NB03) |
| NB03 | Features por noche — índices clásicos + ARI nocturno | `night_features.parquet` |
| NB04 | PAC States multiescala — S(K=7) / M(K=5) / L(K=4) + acoplamiento | `event_states_multiscale.parquet`, `night_multiscale_features.parquet` |
| NB05 | Acoplamiento morfotipo × estado, Markov, fenotipos de trayectoria | `transition_matrices.parquet` |
| NB06 | Ablación LOPO-CV por bloque de features | (modelo `nb06_event_lgbm.pkl`, `nb06_night_lr.pkl`) |
| NB07 | Predicción de evento severo y clasificación de riesgo nocturno | (Risk Score en `nights.parquet`) |
| NB08 | Predicción prospectiva con horizonte temporal H∈{2,5,10,15} min | `window_risk_predictions.parquet` |

Los notebooks `NB09`–`NB11` son exploratorios; ver `notebooks/exploratory/README.md`.

### ⚠ Aviso: modelos congelados — no re-fitear

`models/` contiene los modelos entrenados que son **canon congelado**, al igual que el Gold:

```
models/
  edo_morphotype_curve_kmeans.pkl   ← morfotipos C1–C5
  pac_states_s/m/l_kmeans.pkl       ← estados PAC por escala
  nb05_traj_kmeans.pkl              ← fenotipos de trayectoria
  nb06_event_lgbm.pkl               ← predictor de evento severo
  nb06_night_lr.pkl                 ← clasificador de riesgo nocturno
  *_metadata.json                   ← mapeo etiqueta → nombre semántico
  *_zscore.json                     ← parámetros de estandarización
  ari_*_sorted.npy                  ← arrays percentiles ARI
```

Al re-correr los notebooks, **cargar y aplicar** (`load` + `predict`/`transform`),
**nunca** volver a `.fit()`. Re-fitear introduce riesgo de permutación de etiquetas
(p. ej. C4 pasa a llamarse C2) y drift por versión de librería, invalidando las
tablas y referencias de la tesis.

## ⚠ Disclaimer sobre el estimulador del SOMNI 6000

El dispositivo SOMNI 6000 integra un pulsioxímetro y un **estimulador eléctrico
transcutáneo**. Este trabajo **no evalúa ni demuestra eficacia terapéutica** del
estimulador. Su mención en el contexto de la predicción prospectiva (NB08) es una
**hipótesis operacional**: el módulo establece la condición algorítmica mínima para
que una intervención adaptativa sea técnicamente plausible; la eficacia requiere
un ensayo clínico controlado separado.

El diseño del estudio es **observacional retrospectivo**. Las conclusiones son
de caracterización, no de causalidad clínica.

## Licencia

Trabajo de tesis. Uso académico. Datos del corpus son confidenciales y no
se distribuyen.
