# Deuda técnica y hoja de ruta a producción — Proyecto PAC

> **Qué es este archivo.** Registro único de lo que queda por hacer una vez cerrada la tesis:
> bugs conocidos, deuda técnica del Gold y del repo, y los pasos que exigiría llevar el
> Proyecto PAC de prototipo de investigación a uso real.
>
> **Relación con otros archivos del proyecto.** No reemplaza a ninguno, los consolida:
> - `CLAUDE.md` §20–25 — cifras canónicas y bugs detectados durante la verificación.
> - `HANDOFF_repro_y_didactica.md` §3 — tareas de reproducibilidad del repo (jury-ready).
> - Tesis §9.8 (limitaciones integradas) y §10.4 (ocho líneas de trabajo futuro) — la agenda
>   científica, que acá se referencia pero no se duplica.
>
> **Última actualización:** Agosto 2026 — agregado §2.6 (vector de ventana / morfotipos escalares), detectado al preparar el guion de defensa. Antes: Julio 2026, cierre de la sesión de edición v133 → v136.

---

## 0. Principios que no se reabren

1. **El Gold (`gold/*.parquet`) es la única fuente de verdad.** Cualquier discrepancia entre
   texto y Gold se resuelve a favor del Gold.
2. **No re-fitear los modelos.** `models/*.pkl` es canon congelado: cargar y aplicar, nunca
   `.fit()`. Re-fitear arriesga permutación de etiquetas (C4 pasando a llamarse C2) y drift por
   versión de librería. Detalle completo en `HANDOFF_repro_y_didactica.md` §0.
3. **El estimulador del SOMNI 6000 es hipótesis operacional.** Ninguna comunicación del proyecto
   debe afirmar eficacia terapéutica: la tesis establece factibilidad analítica, no efecto clínico.

---

## 1. Registro de cambios de la sesión v133 → v136 (Julio 2026)

### v134 — edición manual (autor)

| Cambio | Alcance |
|---|---|
| Estandarización de MOV | Canónico "movimiento de dedo (MOV)", definido una sola vez en §1.1; eliminadas redefiniciones en §2.2 y §3.2; corregido "movimiento corporal" en §4.3 |
| Estandarización de FC | Colapsada la redefinición de la sigla en §2.2 |
| Capas del pipeline | Bronze / Silver / Events / Gold unificadas a redonda (estaban ~50 % en itálica) |
| Eliminación de SHAP | Retirado de §1.2, §2.4, §3.8, §10.2, Tabla 1.1 del Anexo, glosario y la referencia Lundberg & Lee (2017). Se declaraba pero nunca se reportaba; lo que se usa es importancia Gini, ganancia y coeficientes |
| LOPO-CV | Definición única en §1.1; colapsados los despliegues de §1.2, §2.4 y §3.8 |
| §3.3.3 ARI | Ecuación (4) corregida a `P(x) = rank(x)/N`; N definido fuera de la ecuación; pesos 0,6/0,4 explicitados como criterio de diseño; agregado el caveat de que el índice es relativo a la cohorte; eliminada la cita circular a T1 |
| Referencias | Retiradas las cuatro entradas "Inza et al. (en preparación)", que quedaban sin cita en el cuerpo |
| §2.1 | Agregada la definición de carga hipóxica en su primera mención |
| §1.3 | Párrafo de anexos reescrito (punto y coma, sin guiones largos, sin duplicar la descripción de las Tablas 1.2 y 1.3) |
| Léxico | "en trenes" → "agrupados en el tiempo" (calco de *event trains*); "curva normalizable" → "normalizada y morfotipo asignado" |

### v135 — anclaje de figuras

Catorce referencias de figuras y tablas que aparecían solo en los callouts ▸ y nunca en la prosa
quedaron ancladas: Tablas 1.2 y 1.3, Fig. 4.4, 6.3, 7.4 a 7.10, 8.1, 8.5 y 8.6. También se
corrigió "normalizable" en la tabla de universos de eventos del Anexo.

### v136 — realineación de la Fig. 5.4

Se detectó que la figura ilustraba un clustering distinto del que describía el texto. Detalle en
§2.1 de este documento.

---

## 2. Bugs y deuda de datos (Gold / notebooks)

### 2.1 Fig. 5.4 — dos clusterings confundidos *(diagnosticado, corregido en el texto)*

`04_pca_clusters_multiescala.png` (NB04 celda 14) proyecta las **560 noches** coloreadas por
`pac_multiscale_cluster`, un agrupamiento exploratorio de tamaños **211 / 112 / 237**. Los
fenotipos con nombre de §5.3 y del Cap. 6 (Estable-Protector 138, Carga Intermedia 368, CHA 7)
vienen de `night_traj_cluster`, definido sobre **513 noches**. No son la misma partición: las 7
noches CHA se reparten 1 / 6 / 0 entre los tres clusters de la figura.

- **Resuelto en v136** por vía textual: caption, callout, nota y prosa ahora describen la figura
  como lo que es.
- **Pendiente opcional:** regenerar la figura coloreando por `night_traj_cluster` para que
  ilustre efectivamente los fenotipos nombrados. Sería la solución de fondo.

### 2.2 `night_traj_cluster_x` — columna huérfana *(pendiente)*

`gold/night_multiscale_features.parquet` arrastra tres columnas de clustering:

| Columna | Cobertura | Tamaños | Estado |
|---|---|---|---|
| `pac_multiscale_cluster` | 560 | 211 / 112 / 237 | En uso (Fig. 5.4) |
| `night_traj_cluster_x` | 560 | 257 / 276 / 27 | **Huérfana** — no la usa nadie |
| `night_traj_cluster` (=`_y`) | 513 | 138 / 368 / 7 | Canónica (fenotipos nombrados) |

Los sufijos `_x`/`_y` delatan un merge que duplicó la columna. Eliminar `night_traj_cluster_x`
antes de que alguien la tome por la buena.

### 2.3 `y_Hmin` desalineado en `window_risk_predictions.parquet` *(pendiente, preexistente)*

Las columnas `y_2min/y_5min/y_10min/y_15min` están desalineadas respecto de `user_id`: la
prevalencia por paciente sale uniforme (~8 %, ratio 1,7×) cuando la real, recomputada desde
`events.parquet` y coincidente con NB08 c8, es 1,6–32,4 % (ratio 20×). **No afecta a la tesis**,
que usa los valores in-session de NB08, pero el parquet exportado está mal. Re-exportar alineado.

### 2.4 Markdown y salidas viejas en los notebooks *(pendiente, de `HANDOFF` §3)*

Etiquetas obsoletas a barrer: `553 → 560` noches, `84.248 → 85.277`, C4 `4.377 → 4.301`,
C5 `800 → 821`, `84.193`, V de Cramér vieja, `S=6/M=8/L=6` preliminar, Risk Score
`25,6/31,6`. Requiere re-correr NB01–NB08 **cargando los modelos**, sin re-fitear.

### 2.5 Notebooks exploratorios sin marcar *(pendiente)*

NB09 (optimización de trigger), NB10 (clasificador temprano) y NB11 (predicción mejorada) son
paralelos y no forman parte de la tesis. Mover a `/exploratory` o rotularlos explícitamente
para que no contradigan al canon.

---

## 3. Privacidad y cumplimiento — bloqueante antes de publicar el repo

**Este es el punto crítico si el repositorio se hace público.**

El repo contiene datos fisiológicos a nivel paciente (`bronze/`, `raw/`, `silver/`, `states/`,
`events/`) y datos demográficos y clínicos en `patients.parquet` (sexo, peso, talla, apnea previa,
diabetes, hipertensión, marcapasos). Eso constituye **dato de salud identificable**.

Antes de cualquier push público:

1. `.gitignore` para todas las capas de datos crudos e intermedios; publicar solo código, o a lo
   sumo Gold agregado y de-identificado.
2. Verificar que los outputs guardados en los notebooks no impriman series ni identificadores de
   pacientes.
3. Confirmar que el consentimiento obtenido (aceptación de términos de la app del dispositivo,
   protocolo CLP-275001) cubre la publicación de datos derivados, aunque sean agregados.
4. Mantener `patient_registry.csv` fuera de git (ya está previsto en el modelo de dos archivos).

---

## 4. Deuda metodológica — condiciona cualquier uso real

Estas son las críticas de fondo, ya asumidas en la tesis (§9.8) y desarrolladas en §10.4. Se
listan acá porque son las que gobiernan qué se puede y qué no se puede prometer.

**Circularidad del clustering PAC.** Los clusters (morfotipos y estados) se entrenaron sobre la
cohorte completa y después se usaron como dimensiones dentro del LOPO-CV. Hay contaminación entre
entrenamiento y evaluación. La corrección rigurosa es reconstruir los clusters *within-fold*, o
validar sobre cohorte externa.

**Tamaño muestral.** n = 8 pacientes en cohorte estricta, reclutados en práctica privada
especializada, con sobrerrepresentación del rango moderado-severo. Todo resultado supervisado
descansa sobre 8 unidades independientes.

**Probabilidades no calibradas.** LightGBM con pesos de clase uniformes sobreestima ~4×. El
umbral de Youden absorbe el offset, pero el output es un *ranking*, no una probabilidad. Para uso
clínico hace falta Platt scaling o calibración isotónica por fold.

**Heterogeneidad inter-paciente.** La prevalencia de eventos severos varía 20× entre pacientes
(1,6 % a 32,1 % a H = 5 min). Un umbral global sirve al centro de la distribución y es subóptimo
para el resto: la calibración individual no es un refinamiento, es un requisito.

**Sin validación externa.** Ninguna cohorte independiente, ningún centro distinto, ninguna PSG
simultánea que ancle morfotipos y estados contra el estándar de referencia.

---

## 5. Camino a producción

Ordenado por dependencia: cada bloque supone el anterior resuelto.

### 5.1 Consolidación del artefacto de investigación

- Re-correr NB01–NB08 contra el Gold final, cargando `models/*.pkl`.
- README de trazabilidad: tabla "cifra de la tesis → notebook/celda que la produce".
- Pinear versiones exactas de librerías; documentar el mapeo etiqueta→nombre de
  `models/*_metadata.json`.
- README principal: propósito, cohorte, pipeline, orden de ejecución y disclaimer de que el
  estimulador es hipótesis operacional.

### 5.2 Robustez estadística

- Reconstrucción de clusters within-fold (elimina la circularidad).
- Calibración de probabilidades (Platt / isotónica) sobre el conjunto de validación de cada fold.
- Cohorte externa con PSG simultánea, 30–50 pacientes: valida morfotipos y estados, cuantifica
  concordancia con estadios AASM y cierra la circularidad.

### 5.3 Ingeniería de la PAC App

- **Normalizador del Risk Score:** hoy es `p_severe_mean / 0,7431` (p99 del corpus). Es una
  constante derivada de esta cohorte; con datos nuevos hay que recalcularla o reemplazarla por
  una calibración explícita.
- **Extrapolación fuera de dominio:** los modelos se calibraron sobre 8 pacientes. Aplicarlos a
  un paciente nuevo es extrapolación sin garantía; la app debe explicitarlo en su interfaz.
- **Portabilidad de la ingesta:** el pipeline de entrada es específico al formato Excel del
  SOMNI 6000 bajo el protocolo CLP-275001 v1.2. Cualquier otro dispositivo o versión de firmware
  exige un adaptador.
- **Transferibilidad de los estados patológicos:** su definición está fijada sobre el corpus
  PAC_v3 y puede no valer en poblaciones con fisiología distinta.
- **Backends LLM:** el módulo de Informe IA corre sobre LM Studio local o Claude API. Para uso
  real hay que decidir residencia de datos, trazabilidad de las salidas y validación clínica del
  texto generado.

### 5.4 Traslación clínica

- Calibración individualizada del umbral: 7–14 noches de rodaje sin estimulación por paciente
  para estimar su prevalencia y ajustar el umbral de Youden.
- Ensayo controlado: 30–50 pacientes con SAOS moderado-severo y PSG basal, asignación aleatoria
  a estimulación activa vs. placebo durante 4–8 semanas, con ODI3, T90 y carga hipóxica como
  desenlaces primarios.
- Marco regulatorio: cualquier uso asistencial cae bajo DECIDE-AI y exige validación externa
  previa (Collins et al., 2015).

### 5.5 Extensiones de investigación

Señales adicionales (temperatura periférica, impedancia transtorácica, HRV de alta resolución);
modelos secuenciales nativos para NB08 (LSTM, TCN, Transformers) apuntando a horizontes cortos;
extensión a piernas inquietas, apnea central en insuficiencia cardíaca y narcolepsia.

---

## 6. Pendientes del documento de tesis

- **Actualizar campos en Word (F9).** El Índice de Figuras, el de Tablas y el TOC son campos
  automáticos: la Fig. 5.4 muestra el título viejo hasta que Word los refresque.
- **Verificar §7.4 contra las capturas reales.** Las descripciones de las Fig. 7.4 a 7.10 que se
  anclaron en v135 se derivaron de los rótulos del callout, no de mirar cada imagen.
- **Fig. 4.5 es un campo de referencia cruzada.** Por eso la Fig. 4.4 se agregó como oración
  aparte en §4.3 en lugar de fundirse en el paréntesis existente. Si se quiere unificar, hay que
  hacerlo desde Word.
- **Reconciliar la cohorte de la Fig. 4.6 en NB03** (el código usa ≥5 noches = 10 pacientes; la
  tesis usa strict-8). Es higiene de notebook, el docx ya está bien.

---

## 7. Orden de prioridad sugerido

| # | Tarea | Motivo |
|---|---|---|
| 1 | Privacidad del repo (§3) | Bloqueante y de riesgo legal |
| 2 | Actualizar campos del docx (§6) | Trivial, visible para el jurado |
| 3 | `y_Hmin` y columna huérfana (§2.2, §2.3) | Bugs concretos, arreglo acotado |
| 4 | Re-correr notebooks + trazabilidad (§5.1) | Lo que un jurado de datos va a mirar |
| 5 | Clusters within-fold + calibración (§5.2) | Deuda metodológica de fondo |
| 6 | Cohorte externa con PSG (§5.2) | Habilita todo lo demás |
| 7 | Ingeniería de la app (§5.3) | Solo tiene sentido tras 5 y 6 |
| 8 | Ensayo clínico (§5.4) | Horizonte largo |

### 2.6 Vector de ventana: morfotipos escalares α–δ *(pendiente, preexistente)*

**Qué pasa.** `PAC_WINDOW_FEATURES` cuenta eventos por morfotipo escalar con cuatro variables —`n_alpha`, `n_beta`, `n_gamma`, `n_delta`— pero el modelo de producción `edo_morphotype_kmeans.pkl` entrena con **K = 10** (α a κ). Quedan sin contar η (7.286 eventos), κ (6.739) y ζ (3.698), todos más frecuentes que α (4.675); y se cuenta δ, que tiene **151 eventos en todo el corpus**, con lo cual `n_delta` es casi siempre cero. Alrededor del 24 % de los eventos no contribuyen a ninguna densidad por morfotipo.

**Por qué no se corrige ahora.** Cambiar el vector obliga a re-fitear los tres clusterings de Estados PAC, lo que viola §0.2 (modelos congelados) y renumeraría S/M/L, invalidando las cifras de los Cap. 5 a 8. **No es un bug de resultados: los estados existentes son válidos como están definidos.** Es deuda de diseño.

**Qué hacer al re-entrenar.** Decidir explícitamente entre (a) contar los diez morfotipos, (b) contar los k más frecuentes que cubran un porcentaje declarado del corpus, o (c) colapsar los raros en una categoría «otros». Documentar la elección en `config.py`, que hoy no la justifica.

**Documentación asociada a corregir en la misma pasada.** El Cap. 5 de la tesis describe estas densidades como «conteo de EDOs por tipo C1–C5» —son α–δ— y menciona «contexto temporal» entre las variables de la ventana, cuando no hay ninguna variable de posición temporal en el vector. `CLAUDE.md` §3 decía K = 4; corregido en §44.

**Detectado**: Agosto 2026, preparando el guion de defensa. Detalle completo en `CLAUDE.md` §44.

### 2.7 El IRD sobrevive en el vector de ventana *(pendiente, preexistente)*

**Qué pasa.** La erradicación del IRD y sus derivadas quedó incompleta. Sobrevive en dos lugares, y los dos alimentan a los Estados PAC:

- **Directo**: `PAC_WINDOW_FEATURES` incluye `ird_mean_local`, que `config.py` define como *«mean de `ird_event` sobre los EDOs de la ventana»*. No es el ARI.
- **Indirecto**: el modelo de morfotipos escalares (§2.6) se entrena sobre 10 variables, de las cuales **cuatro son IRD** — `ird_event`, `ird_spo2_comp`, `ird_hr_comp`, `ird_mov_comp`. Sus recuentos entran al vector de ventana.

**Cómo se detecta sin abrir el código.** El ARI está acotado entre 0 y 1 por construcción (promedio ponderado de rangos percentiles). `ird_event` va de −0,21 a 25,41, y su componente de movimiento llega a 125,87. Cualquier valor mayor que 1 en una variable rotulada «ARI» delata la sustitución.

**Por qué no se corrige ahora.** Mismo motivo que §2.6: obliga a re-fitear los tres clusterings de estados, lo que viola §0.2 y renumeraría S/M/L. **No es un bug de resultados**; los estados son válidos como están definidos.

**Qué hacer al re-entrenar.** Reemplazar `ird_mean_local` por el ARI —que ya está calculado y es la versión corregida del mismo concepto— y reconstruir los morfotipos escalares sobre las seis variables morfológicas más los componentes percentilizados, sin el IRD crudo. Verificar después si los estados resultantes conservan la especialización funcional reportada en el Cap. 5; si no la conservan, es un hallazgo por derecho propio.

**Impacto en la interpretación, no en las cifras.** Donde el Cap. 5 atribuye «reactividad autonómica» a un estado, la variable que lo definió está dominada por movimiento crudo. En la escala S el estado de mayor `ird_mean_local` (5,09) es también el de mayor `mov_mean` (21,54).

**Documentación a corregir en la misma pasada.** Cap. 5: «ARI medio en la ventana» → respuesta autonómica media. Diapositiva d12 del mazo de defensa: ídem.

**Detectado**: Agosto 2026, preparando el guion de defensa. Detalle completo en `CLAUDE.md` §44.b.
