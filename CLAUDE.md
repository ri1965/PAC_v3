# CLAUDE.md — Contexto de escritura de tesis · Proyecto PAC

> **Instrucciones para el asistente**: Este archivo define el contexto permanente de la tesis. Léelo completo antes de comenzar cualquier tarea de escritura. Para retomar un capítulo, cargá también el .docx del capítulo anterior terminado (no es necesario cargar todos los capítulos anteriores).

---

## 1. Datos del trabajo

| Campo | Valor |
|---|---|
| **Autor** | Roberto Inza |
| **Institución** | Universidad Austral |
| **Programa** | Maestría en Explotación de Datos y Gestión del Conocimiento |
| **Título tentativo** | Proyecto PAC: caracterización fenotípica y dinámica del síndrome de apneas obstructivas del sueño mediante oximetría domiciliaria portátil |
| **Nota de nomenclatura** | El nombre completo oficial es **Proyecto de Procesamiento Autonómico Continuo (Proyecto PAC)**. No usar "Proyecto APNEA". El pipeline se llama PAC_v3. En la primera mención de cada capítulo usar la forma completa; el resto del capítulo puede usar "Proyecto PAC". |
| **Carpeta de capítulos** | `~/Proyectos/PAC_v2/tesis_cap/` |

---

## 2. Constraints globales de escritura (no negociables)

### Tono de potencialidad
Nunca afirmaciones taxativas sobre resultados o capacidades del sistema. Siempre condicional:
- ✅ "podría mejorar", "busca cuantificar", "se evalúa como", "los resultados sugieren"
- ❌ "mejora", "cuantifica", "es", "demuestra"

### Estilo y formato
- **Idioma**: Español (es-AR), sin anglicismos innecesarios. Los términos técnicos en inglés se italiciza la primera vez y se explican.
- **Audiencia**: Científicos de datos / data scientists. **No** especialistas en medicina del sueño. Explicar clínica cuando sea relevante; no asumir conocimiento médico.
- **APA 7ª edición**: Todas las citas. Formato (Apellido et al., año) en el cuerpo; bibliografía al final del capítulo.
- **Formato visual**: Aptos, BLUE = `#1E3A5F`, A4, margen izquierdo 1800 (twips). Texto corrido: 12pt, interlineado 1,5. Mismo estilo que Cap01–Cap05.
- **Sin resultados propios en Cap02/03**: El Marco Teórico y Materiales y Métodos no mencionan resultados específicos del proyecto (eso va en Cap04 y Cap05).

### Cover heading (formato uniforme Cap01–Cap09+)
- **"CAPÍTULO N"**: Aptos 10pt, bold, gris `#6B7280`
- **Subtítulo**: Aptos 18pt, bold, azul `#1E3A5F`
- **"Versión N  ·  Mayo/Junio 2026"**: Aptos 9pt, sin itálica, gris `#6B7280`
- **Header**: "Proyecto APNEA · Tesis de Maestría" (izq, gris) | "Capítulo N — Título  (vN)" (der, gris, itálica); borde inferior `#D0D8E4`
- **Footer**: "Roberto Inza · Universidad Austral · 2026" + número de página; alineado a la derecha; borde superior `#D0D8E4`

### Gestión de redundancia entre capítulos
- Cada capítulo asume que el lector leyó los anteriores. No repetir argumentos, sí profundizar.
- Si un capítulo anterior menciona brevemente un concepto, el siguiente puede desarrollarlo con referencias.
- Si un capítulo ya argumenta extensamente un punto, el siguiente lo referencia y avanza.

---

## 3. Conceptos técnicos clave del proyecto

### Dispositivo y datos
- **SOMNI 6000**: Dispositivo portátil aprobado por ANMAT. Integra pulsioxímetro + estimulador eléctrico transcutáneo en un único sensor de dedo no invasivo. Registra SpO₂ y FC a 1 Hz. Transmisión Bluetooth LE a dispositivo móvil.
- **Cohorte**: 12 pacientes, 560 noches (todas in_quality, con ≥1 EDO), 85.277 EDOs · ⚠ el viejo "553 quality" quedó re-baseado a 560 (Gold actual; ver §20)
- **Protocolo**: CLP-275001 v1.2, abril 2025, estándares ICH GCP, regulaciones FDA y ANMAT, diseño cruzado aleatorizado doble ciego.
- **Señal**: SpO₂ + FC + MOV a 1 Hz, noches consecutivas en condiciones domiciliarias habituales.

### Pipeline PAC_v3 — Arquitectura Medallion
> ⚠ La carpeta en disco se llama `PAC_v2/` pero el pipeline documentado en los capítulos es **PAC_v3** (reanálisis con cohorte estricta final, NB04). No confundir con configuraciones preliminares.

```
Bronze  →  Silver  →  Events  →  Gold
```
- **Bronze**: señales canónicas por noche (timestamp, spo2, hr, mov, sleep_stage). NightRecordID = MD5(SHA256 archivo | ts_start).
- **Silver**: control de calidad de señal (rango fisiológico, cobertura ≥90%, duración mínima). Flags QC, spo2_clean y hr_clean. No excluye noches; marca y delega a Gold.
- **Events**: 85.277 EDOs detectados (umbral permisivo ≥2pp, duración ≥10s, baseline móvil 120s). Caracterización geométrica 25+ features por evento. ARI multimodal por evento. Índices nocturnos + quinteto de validación vs. dispositivo.
- **Gold**: 5 tablas analíticas — events.parquet (85.277 filas), events_curves.parquet (30 puntos SpO₂/evento), states.parquet (~519K ventanas), nights.parquet (560 filas × 146 features), patients.parquet (12 filas).

### Índices y métricas
- **EDO (Evento de Desaturación de Oxígeno)**: caída de SpO₂ ≥ 2pp (umbral permisivo del pipeline), duración ≥ 10s, recuperación al 90% del baseline local (mediana deslizante 120s). El ODI3 clínico usa umbral ≥ 3pp.
  - **Por qué ≥ 2pp y no ≥ 3pp**: el umbral clínico del ODI3 es una convención diagnóstica, no una frontera fisiológica. El Proyecto PAC no busca diagnosticar sino caracterizar morfológicamente los eventos. Un evento de 2,5pp tiene morfología, duración y respuesta autonómica igualmente informativas que uno de 3,2pp; excluirlo implicaría perder información estructural sin justificación fisiopatológica. El umbral permisivo maximiza el corpus analítico y captura eventos borderline relevantes, especialmente en pacientes con hipoxemia basal crónica donde caídas menores a 3pp pueden ser fisiológicamente significativas. El ODI3 se calcula como subconjunto del corpus para preservar la compatibilidad con el estándar clínico.
- **ODI3**: Oxygen Desaturation Index (umbral 3%), índice de frecuencia nocturna.
- **AHI**: Apnea-Hypopnea Index (requiere PSG; no disponible en esta cohorte).
- **T90**: porcentaje del tiempo de sueño con SpO₂ < 90%.
- **Hypoxic burden / carga hipóxica**: área bajo la curva de SpO₂ durante eventos respiratorios. Predice mortalidad cardiovascular independientemente del AHI (Azarbarzin et al., 2019).
- **ARI (Índice de Reactividad Autonómica)**: índice adimensional que mide la ganancia autonómica de cada evento — cuánta respuesta fisiológica cardíaca y motora genera el organismo por unidad de estímulo hipóxico. **No existe IRD; el único índice de respuesta es el ARI.**

  **Fórmula exacta** (publicada en T1):
  ```
  ARIᵢ = 0.6 · P(hr_gainᵢ)  +  0.4 · P(mov_gainᵢ)

  hr_gainᵢ   = Δhr_bpm_i / drop_pct_i
               (incremento de FC en lpm dividido por profundidad de caída de SpO₂ en pp)
  mov_gainᵢ  = (peak_mov_i − baseline_mov_i) / drop_pct_i
               (incremento de MOV relativo a la caída de SpO₂)
  P(·)       = rango percentil dentro del corpus completo
               (rankdata / N, con N = 85.277 EDOs quality)
  ```
  Los pesos 0.6 / 0.4 reflejan la mayor confiabilidad de la señal cardíaca (PPG) frente al sensor de movimiento. **Ortogonalidad: ρ(ARI, drop_pct) = 0,035** (Spearman, n = 85.277 EDOs; severidad del evento; fuente canónica: Cap04 §4.3.1). [⚠ El antiguo "ρ(ARI, ODI3)=0,034" era el valor de drop_pct mal etiquetado; ρ vs ODI3 real = −0,066 evento / −0,245 noche.] ICC(1,1) noche-nivel = 0,69 (cohorte completa) / 0,74 (cohorte estricta) — rasgo moderadamente estable del paciente.

  **Gradiente autonómico inverso (Cap04 §4.3.3)**: C5 presenta el ARI más bajo del corpus (0,423 ± 0,104). Los morfotipos severos tienen mayor carga hipóxica pero menor reactividad autonómica, no mayor.

### Representaciones derivadas
- **Morfotipos C1–C5**: 5 fenotipos de curvas SpO₂ individuales, obtenidos por K-means (K=5) sobre PCA de 30 puntos de curva normalizados (85.277 EDOs con morfotipo asignado). C4+C5 = severos (5.122 eventos, 6,0% del corpus de 85.277).
- **Morfotipos escalares α–δ**: clustering K=4 sobre vector de 10 features morfológicas (no curva). Complementa C1–C5.
- **PAC States (PAC_v3)**: sistema de estados dinámicos a 3 escalas temporales:
  - **Escala S** (30 s): K=7, estados S0–S6. S1+S2 ≈ 60% del tiempo. S6 excluido de feature matrix nocturna por baja frecuencia (~1%). Mejor predictor de frecuencia: S4 (ρ ODI3 = +0,690).
  - **Escala M** (5 min): K=5, estados M0–M4. Mejor predictor de carga hipóxica: M1 (ρ T90 = +0,744).
  - **Escala L** (30 min): K=4, estados L0–L3. Polos: L0 hipoxemia sostenida (ρ T90 = +0,705), L3 baja carga (ρ ARI = +0,357).
  - ⚠ Versiones preliminares del proyecto usaron S=6/M=8/L=6 — esos valores son incorrectos para PAC_v3.
  - **States patológicos** (tasa C4+C5 > mediana): S2, S4, S6 / M1, M3 / L0, L1
  - **V de Cramér** acoplamiento morfotipo–estado: S=0,356 / M=0,231 / L=0,196 (NB04, 560 noches)

### Validación estadística
- **LOPO-CV (Leave-One-Patient-Out Cross-Validation)**: validación cruzada donde cada fold excluye todas las noches de un paciente. El **n efectivo = 8 pacientes** (cohorte estricta para modelos supervisados), no 540 noches.
- **Cohortes de análisis**: 12 pac. in_strict = 560 noches (análisis descriptivos); 8 pac. = 540 noches (modelos supervisados NB06/NB07/NB08); 494 noches (NB07 Bloque C, tras dropna); 76.053 eventos (NB07 Bloque B, excluyendo primeros 5 por noche); **452.955 ventanas × 4 horizontes** (NB08, cohorte estricta 8 pac.).
- **Variabilidad intraindividual**: las noches de un mismo paciente pueden mostrar perfiles fisiológicos marcadamente distintos (postural, consumo de alcohol, fatiga). Esta variabilidad es información, no ruido.
- **Nota sobre p-valores**: con n grande (85.277 EDOs), cualquier diferencia produce p significativo. El énfasis interpretativo va en tamaños de efecto (ρ, AUC, ICC, AP) y consistencia entre folds LOPO-CV (Wasserstein & Lazar, 2016).

---

## 4. Estructura de la tesis

| Capítulo | Título | Estado | Versión extensa | Versión resumida |
|---|---|---|---|---|
| Cap01 | Introducción | ✅ Terminado | v11 | **resumido v7** |
| Cap02 | Marco Teórico | ✅ Terminado | v10 | resumido v3 |
| Cap03 | Materiales y Métodos | ✅ Terminado | v7 | **resumido v8** |
| Cap04 | Fenotipado Morfológico y Reactividad Autonómica | ✅ Terminado | v12 | **resumido v20** |
| Cap05 | PAC States y Caracterización Multiescala | ✅ Terminado | v12 | **resumido v21** |
| Cap06 | Modelado predictivo basado en PAC | ✅ Terminado | v14 | **resumido v33** |
| Cap07 | App clínica interactiva | ✅ Terminado | v15 | **resumido v12** |
| Cap08 | Predicción prospectiva con margen temporal (NB08) | ✅ Terminado | v8 | **resumido v18** |
| Cap09 | Discusión / revisión de literatura | ✅ Terminado | v15 | **resumido v21** |
| Cap10 | Conclusiones | ✅ Terminado | v5 | **resumido v9** |

> ⚠ **Anexos (versiones finales)**: Anexo A Referencias **v4** · Anexo B Glosario **v11** · Anexo Suplementario **v18**. Ver §20 para el detalle de correcciones de Junio 2026.

**Nota**: Las secciones de "Contribuciones principales" y "Trabajos presentados" van al **Cap10 (Conclusiones)**, no en la Introducción.

**Nota Cap07**: Cap08 continúa narrativamente desde Cap06, no desde Cap07. Cap07 (App clínica) es paralelo. Si Cap07 no estuviera listo para defensa, eliminar su mención de Cap01 §1.7 y de Cap06 §6.14.

---

## 5. Estructura de Cap01 (referencia rápida)

- **1.1** Contexto y motivación clínica del SAOS
- **1.2** El dispositivo SOMNI 6000 y el entorno de adquisición (incluye mención ANMAT)
- **1.3** Pipeline PAC_v3: descripción de alto nivel
- **1.4** Preguntas de investigación
- **1.5** Objetivos generales y específicos
- **1.6** Alcance y limitaciones
- **1.7** Organización del documento

---

## 6. Estructura de Cap02 (referencia rápida)

Cuatro pilares conceptuales articulados progresivamente. Versión final: v10.

- **Párrafo introductorio**: anuncia los 4 dominios (clínica del SAOS → instrumento → series temporales fisiológicas → ML en señales biomédicas)
- **2.1** Fisiopatología del SAOS; AHI/ODI como índices de frecuencia y T90 como métrica temporal; hypoxic burden; variabilidad noche a noche; fenotipado clínico
- **2.2** Monitoreo domiciliario vs. PSG (complementario, no reemplazante); roles analíticos de SpO₂ (primaria), FC (secundaria) y movimiento (auxiliar); variabilidad intraindividual como información; caveat de no-independencia estadística para LOPO-CV
- **2.3** Tres niveles analíticos: evento (morfología EDO + respuesta autonómica FC) → noche (multiescala, estados dinámicos) → paciente (fenotipo longitudinal). Incluye cita Berry 2012 para criterios AASM y base conceptual del ARI.
- **2.4** PCA, K-means, modelos supervisados (LightGBM), LOPO-CV, SHAP. Cierra con disclaimer de causalidad: el ML identifica asociaciones, no establece causalidad clínica sin validación prospectiva.
- **Párrafo de cierre**: define PAC como representación intermedia (entre índice escalar y señal cruda), continua, multiescala y longitudinal, operando en los tres niveles evento/noche/paciente.

**26 referencias** · APA 7ª edición

---

## 7. Estructura de Cap03 (referencia rápida)

Ocho secciones que operacionalizan el marco teórico del Cap02. Versión final: v7.

- **Párrafo introductorio**: anuncia las 8 secciones y el eje narrativo (pipeline Bronze→Gold)
- **3.1** Diseño observacional retrospectivo; protocolo CLP-275001 v1.2; ICH GCP, FDA, ANMAT; consentimiento y anonimización
- **3.2** Cohorte (12 pac., 560 noches, sesgo clínico); SOMNI 6000 (descripción técnica, 3 señales a 1 Hz); protocolo domiciliario vs. PSG
- **3.3** Pipeline PAC_v3 completo: Bronze → Silver (QC) → Events (detección ≥2pp, 25+ features, ARI, quinteto validación) → Gold (5 tablas)
- **3.4** Nivel 1 — Evento: PCA sobre 85.277 curvas normalizadas; K-means K=5; morfotipos C1–C5; ARI (fórmula exacta, ortogonalidad a ODI3)
- **3.5** Nivel 2 — Noche: escalas S(K=7)/M(K=5)/L(K=4); vector 24 features; 26 features nocturnas; Markov + trayectorias K=3
- **3.6** Nivel 3 — Paciente: nights.parquet como matriz de diseño; LightGBM vs. LR; clasificación 4 categorías AASM + binaria; ablación por bloque; NB07; score 0–100
- **3.7** NB08: 452.955 ventanas de 30s; horizontes H∈{2,5,10,15} min; H=5min óptimo; métricas AP + AUC + PPV
- **3.8** Validación: LOPO-CV (n efectivo=8 pac. cohorte estricta); ICC(1,1); Bland-Altman; bootstrap MAE; SHAP; nota sobre p-valores

**11 referencias nuevas** · APA 7ª edición (se suman a las 26 de Cap02)

---

## 8. Estructura de Cap04 (referencia rápida)

Análisis de nivel evento: morfotipos y ARI. Versión final: v12.

- **4.1** Corpus de eventos (560 noches, 85.286 EDOs total / 85.277 quality / 85.277 con morfotipo)
- **4.2** Fenotipado morfológico (NB01): PCA (PC1=62,9% / PC2=14,0% / PC3=7,0%); K=5 (Silhouette=0,386); morfotipos C1–C5; distribución (C4+C5=6,0%; C4=4.301/5,0%, C5=821/1,0%); IEI mediano=82s; correspondencia con α–δ; ICC inter-noche
- **4.3** Diagnóstico IRD → definición ARI (NB02): bug de escala en IRD; ρ(ARI, drop_pct)=0,034; gradiente inverso C5 ARI más bajo (0,423); análisis within-stratum; ICC(1,1)=0,69/0,74
- **4.4** Síntesis features nocturnas (NB03): matriz 50 features, 560 noches (re-baseado desde 553)
- **4.5** Validación reproducibilidad multi-noche: ODI3 necesita ~7 noches; ARI estable desde noche 1

---

## 9. Estructura de Cap05 (referencia rápida)

PAC States multiescala. Versión final: v12.

- **5.1** Fundamentos (NB03): validación ARI como feature estable (ICC=0,69; ρ ODI3=0,041); construcción espacio de estados; Tabla 5.2 parámetros por escala; V de Cramér como métrica de asociación
- **5.2** Escala S — microdinámica (NB04): K=7, S0–S6; S1+S2≈60%; S4 mejor predictor AHI (ρ=+0,691); S5 reactividad máxima (ρ ARI=+0,637); S6 más raro (~1%)
- **5.3** Escala M — regulación intermedia (NB04): K=5, M0–M4; M1 mejor predictor T90 (ρ=+0,744); M0/M2 protectores; arquetipos A/B/C (50%/35%/15%)
- **5.4** Escala L — arquitectura global (NB04): K=4, L0–L3; L0 hipoxemia sostenida (ρ T90=+0,705); L3 baja carga (ρ ARI=+0,357)
- **5.5** Features nocturnas multiescala: 15 fracciones (frac_s_S0–S5 excluye S6 + frac_m_M0–M4 + frac_l_L0–L3) + 3 entropías + 3 transiciones = 21 features PAC; **PCA PC1=36,7%** (verificado sobre Gold; el viejo 29,2% era incorrecto)
- **5.6** Especialización funcional (hallazgo central): S4→frecuencia (AHI); M1→carga hipóxica (T90); S5→reactividad autonómica (ARI); L0→arquitectura global
- **5.7** Síntesis y limitaciones; bridge al Cap06

---

## 10. Estructura de Cap06 (referencia rápida)

Modelado predictivo basado en PAC. Versión final: v7.

- **6.1–6.2** Introducción y corpus (NB05: 12 pac./80.353 ev./560 noches; NB06/07: 8 pac.)
- **6.3** Acoplamiento morfotipo–estado (NB05 §2): V de Cramér S=0,354/M=0,230/L=0,196; estados patológicos S2/S4/S6, M1/M3, L0/L1; RR: S6×4,9 / M1×3,3 / L0×2,0
- **6.4** Coupling index nocturno: ci_s vs ci_m prácticamente independientes (r=0,056); ci_m/ci_l moderado (r=0,364)
- **6.5** Resiliencia post-evento severo: S=43,3% / M=12,3% / L=1,3% — inercia creciente con la escala
- **6.6** Dinámica Markoviana: 462.519 trans. S / 45.900 M / 7.196 L; atractores S1/M0/L3
- **6.7** Fenotipos de trayectoria nocturna (K=3, NB05 §6): Estable-Protector / Carga Intermedia / Carga Hipóxica Alta; hallazgo clave: fenotipo CHA aparece en subgrupo SAOS Moderado
- **6.8** Ablación LOPO-CV (NB06): PAC States dominan (44,75%); morfotipos 20,2%; dinámica 14,7%; ARI solo 3,4% / balanced acc.=0,281
- **6.9–6.10** Predicción evento severo (NB07 Bloque B): LightGBM AUC=0,878 / LR=0,743; AP=0,240 vs baseline=5,56%; 76.053 eventos, 8 pac.
- **6.11–6.12** Clasificación riesgo nocturno (NB07 Bloque C): LR AUC=0,905 / RF=0,783; AP=0,834 vs baseline=0,348; fracciones M dominantes; 494 noches
- **6.13** Risk Score PAC (0–100): 0,40×p_ev_norm + 0,60×p_high_risk_night (heurístico); lead time ≈5 min = ventana causal NB07, NO predicción prospectiva (eso es Cap08)
- **6.14–6.16** Relación con capítulos previos / Limitaciones / Conclusión; bridge a Cap07

**Nota NB08**: el contenido de NB08 (predicción prospectiva con horizonte temporal H∈{2,5,10,15} min, 452.955 ventanas, habilitación del estimulador) pertenece al **Cap08**, no al Cap06.

---

## 11. Estructura de Cap08 (referencia rápida)

Predicción prospectiva con horizonte temporal — módulo NB08. Versión extensa: v8. Versión resumida (tesis): **resumido v14** · Calificación jurado: 9.5/10.

**Corpus**: 452.955 ventanas de 30 s × 4 horizontes · 8 pacientes · 540 noches · LOPO-CV estricto

**Resultado central**: AUC = 0,821 ± 0,022 para H = 5 min (horizonte óptimo), Sens = 76 %, Spec = 74 %, PPV = 20 %

- **Intro**: bridge desde Cap06 §6.16; inercia Markoviana como base fisiológica de la predicción prospectiva; output del modelo = ranking de riesgo, no probabilidad calibrada
- **8.1** Formulación: NB07 (clasificación condicional, evento en curso) vs. NB08 (predicción prospectiva, sin evento); Tabla 8.1 comparativa; motivación clínica SOMNI 6000 — estimulador como **hipótesis operacional** pendiente de ensayo clínico controlado
- **8.2** Diseño: 8.2.1 corpus ventanas 30 s sin solapamiento; 8.2.2 features backward-looking en 5 grupos (estado PAC, posición temporal, historial reciente, morfología reciente, historial acumulado); 8.2.3 LR baseline + LightGBM 300 est., LOPO-CV, **pesos clase uniformes** (sin scale_pos_weight) — decisión que explica brecha de calibración; Niculescu-Mizil & Caruana (2005)
- **8.3** Prevalencia: 3,74 % (H=2min) → 18,89 % (H=15min); heterogeneidad 20× (Pac314=1,6 % vs Pac175=32,1 %); Tabla 8.3 por paciente
- **8.4** Rendimiento: pendiente moderada AUC 0,838→0,763; LightGBM supera LR en 3–5 pts (mayor ventaja horizontes cortos); delta 8 pts NB07 vs NB08 interpretado fisiológicamente; feature importance: window_position > ci_sofar > state_m_enc (H=2min); paradoja Pac314 — menor prevalencia → mayor AUC (discriminación ⊥ prevalencia); Figura 8.4 heatmap AUC × paciente
- **8.5** Operacional: umbral Youden H=5min (Sens=76%, Spec=74%, PPV=20%); H=2min descartado (PPV=10%, 9/10 activaciones falsas); W_block=5min → ~200 ventanas-alarma → ~20 episodios noche (**estimación de primer orden, no simulación validada**); ~5 reales / ~20 falsos = ratio 1:4 efectivo
- **8.6** Estimulador: 8.6.1 cadena de decisión (actualizacion 30s, umbral individual, lead time >>90s ramp-up — Clifton et al. 2015); 8.6.2 heterogeneidad como barrera principal (calibración individual requerida); 8.6.3 qué establece vs. qué queda pendiente
- **8.7** Limitaciones: muestra n=8; heterogeneidad no modelada; **circularidad PAC** — clusters entrenados sobre cohorte completa, validación rigurosa requeriría recluster within-fold o cohorte externa; calibración ~4× sobreestimación (Platt scaling / isotónica como solución); morph_mean_5min ausente 28,7% ventanas; sin validación externa; referencia Saito & Rehmsmeier (2015) para AP en datasets desbalanceados
- **8.8** Conclusión: "NB08 no demuestra eficacia terapéutica, pero define la condición algorítmica mínima para que una intervención adaptativa sea plausible"; bridge al Cap09

**9 referencias** (Azarbarzin 2019, Berry 2012, Clifton 2015, Inza T1/T4, Ke 2017, Lévy 2015, Niculescu-Mizil & Caruana 2005, Saito & Rehmsmeier 2015) · APA 7ª edición

**Figuras NB08** (en `notebooks/figuras/nb08/`): fig_00_cell8.png (Fig 8.1 dataset), fig_01_cell13.png (Fig 8.2 AUC vs lead time), fig_02_cell14.png (Fig 8.3 feature importance), fig_03_cell16.png (Fig 8.5 umbral operacional), fig_04_cell17.png (Fig 8.4 heatmap AUC paciente), fig_05_cell19.png (Fig 8.6 calibración + perfil riesgo)

**Build**: script `build_cap08_v2.js` (outputs temporales Cowork) · Output: `tesis_cap/Cap08_prediccion_prospectiva_v6.docx`

---

## 12. Estrategia de sesiones de escritura

### Cómo retomar un capítulo nuevo
1. Abrir chat nuevo
2. Cargar este `CLAUDE.md` desde `~/Proyectos/PAC_v2/CLAUDE.md`
3. Cargar el .docx del **capítulo anterior terminado** (solo el inmediato anterior es suficiente; no hace falta cargar todos)
4. Indicar el capítulo objetivo y las secciones a trabajar en la sesión

### Nota de continuidad de capítulos
- **Cap08 continúa desde Cap06** (§6.16), no desde Cap07. Cap07 (App clínica) es paralelo y no precede narrativamente a Cap08.
- Para Cap09 (Discusión): cargar Cap08 resumido v14 como capítulo anterior inmediato.

### Por qué no cargar todos los capítulos anteriores
- El capítulo anterior da la transición narrativa necesaria (qué se dijo, qué se prometió desarrollar)
- Los capítulos más viejos solo añaden peso de contexto sin beneficio práctico
- Si hay una referencia cruzada necesaria, se puede pedir explícitamente

### Build de .docx
- El sistema usa **Node.js + librería `docx`** para generar los archivos Word
- Script de build: generado ad hoc por sesión en la carpeta temporal de trabajo de Cowork
- Output final en: `~/Proyectos/PAC_v2/tesis_cap/`
- Nomenclatura: `Cap0X_NombreCapitulo_vNN.docx`
- Borradores previos en: `~/Proyectos/PAC_v2/tesis_cap/Borradores de capitulos/`
- **Versioning**: cada ronda de correcciones genera una nueva versión (v1, v2, … vN)

---

## 13. Publicaciones asociadas

- **T1** (enviado): Fenotipado morfológico y ARI — cubre NB01–NB02. Contiene datos definitivos de cohorte, descripción del SOMNI 6000 y **fórmula canónica del ARI**.
- **T2**: PAC States multiescala — cubre NB03–NB04. En preparación.
- **T3**: Asociación estados PAC × severidad EDO, modelos predictivos — NB05–NB07. En preparación.
- **T4**: Predicción prospectiva con lead time clínico — NB08. En preparación.

---

*Última actualización: Junio 2026 — Cap01–Cap10 terminados · todos los anexos corregidos · corpus completo y consistente · LISTO PARA DEFENSA*

**Correcciones post-evaluación de jurado (Junio 2026) — versiones finales definitivas:**
- **Cap04 v14→v16**: Tabla 4.2 y 4.6 corregidas (C4: 4.377→4.301 / 5,2%→5,0%; C5: 800→821 / 0,9%→1,0%). Citas Prabhakar, 2016 → Prabhakar, 2016a (ambas instancias).
- **Cap06 v24→v27**: AUC Bloque C corregido (LR 0,874→0,905; RF 0,815→0,777; AP LR 0,764→0,834; RF 0,649→0,633; baseline 0,320→0,348 + nota NaN folds). Resiliencia §6.4 corregida ("permanecer patológico" → "retornar a estado protector"; nota completada con valores colapsado). §6.2 nota corpus NB05 (83.892 ev.) vs. NB04 (85.277 ev.) + nota Fig 6.3 unificada (0,231→0,229).
- **Cap07 v6→v7**: §7.1 obj.(3) "Gemma vía LM Studio" → dual backend (LM Studio + Claude API). §7.2 mención backends LLM. §7.3 párrafo alertas de discordancia (CI_M/CI_L umbrales, referencia Cap04 §4.3.3). §7.4 especificación hardware (Apple M2, 16 GB RAM).
- **Cap08 v15→v16**: §8.7 circularidad PAC comprimida, referencia a Cap06 §6.10 + matiz prospectivo específico de NB08.
- **Cap09 v16→v18**: §9.2.1 "6,1 %"→"6,0 %". §9.2.2 ρ=0,034 especificado como vs. ODI3 + conexión explícita con ρ=0,035 vs. drop_pct (Cap04 §4.3.1). §9.9 "84.248"→"85.277" + parentético de Segunda contribución con ambos ρ. Cita Prabhakar, 2016 → Prabhakar, 2016b.
- **Cap10 v4→v5**: Tabla 10.1 "84.248"→"85.277"; "C4+C5 = 6,1 %"→"6,0 %".
- **Anexo B Glosario v8→v9**: Cover "ANEXO C"→"ANEXO B" / "Versión 1"→"Versión 9". Morfotipos: 84.248→85.277; C4 5,2%→5,0%; C5 0,9%→1,0%; 6,1%→6,0%. Carga hipóxica: 6,1%→6,0%. Risk Score medianas: 29,2/29,4/72,9/81,0→25,6/31,6/72,2/80,8. Trayectorias: ~50/35/15%→~28/71/1%.
- **Anexo Suplementario v15→v16**: Cover "Versión 9"→"Versión 16". Fig 6.3 nota: V Cramér M 0,231→0,229. Fig 6.12 nota: "permanecer patológico"→"retornar a estado protector" + valores colapsado. Fig 6.15 nota: LR 0,874/0,764→0,905/0,834; RF 0,815/0,649→0,777/0,633; baseline 0,320→0,348. Fig 6.9 nota: medianas 29,2/29,4/72,9/81,0→25,6/31,6/72,2/80,8; Moderadas 77,6%→74,3%; Leves 9,4%→11,7%.
- **CLAUDE.md**: morfotipos 84.248→85.277; C4+C5 5.177→5.122 (6,1%→6,0%); todas las versiones resumidas actualizadas.

---

## 14. Notas de sesión — Cap06 v14

### Concepto clave incorporado en v14
- **Risk Score PAC = índice de caracterización dinámica retrospectiva**, no sistema de monitoreo en tiempo real. Se calcula sobre la noche ya procesada (al día siguiente). Su valor clínico: fenotipado post-diagnóstico, seguimiento longitudinal, detección de noches con riesgo oculto.
- La predicción en tiempo real con lead time explícito y habilitación del estimulador es **Cap08**.

### Acoplamiento — definición canónica
A la relación entre el estado fisiológico activo y la morfología del evento que ocurre en él se la denomina **acoplamiento**. Por construcción, todo EDO ocurre dentro de algún estado PAC activo; la pregunta no es si se superponen, sino si esa superposición tiene estructura: si ciertos estados concentran morfotipos severos de manera no aleatoria.

### Figuras conceptuales generadas (PNGs en `notebooks/figuras/`)
`cap06_concepto_acoplamiento.png` · `cap06_concepto_coupling_index.png` · `cap06_concepto_resiliencia.png` · `cap06_concepto_markov.png` · `cap06_concepto_trayectorias.png` · `cap06_concepto_ablacion.png` · `cap06_concepto_modelo_evento.png` · `cap06_concepto_modelo_nocturno.png` · `cap06_concepto_risk_score.png` · `cap06_concepto_escalera.png`

### Build
- Script: `/sessions/.../cap06/build.js` (Node.js + librería `docx`)
- Output: `tesis_cap/Cap06_modelado_predictivo_v14.docx`

---

## 15. Notas de sesión — Cap08 v6

### Decisiones de diseño incorporadas en el proceso
- **Cap08 continúa desde Cap06 §6.16**, no desde Cap07. El bridge de entrada lo explicita: "Cap06 establece que esas representaciones contienen la información necesaria; Cap08 la convierte en acción."
- **Mecanismo estimulador = hipótesis operacional**: en todas las menciones del SOMNI 6000, el efecto autonómico del estímulo está calificado como hipótesis pendiente de ensayo clínico controlado. No usar indicativo sin calificador.
- **Output del modelo = ranking, no probabilidad**: LightGBM sobreestima ~4× con pesos uniformes. El umbral de Youden absorbe el offset. Platt scaling / isotónica requeridos para uso clínico en términos absolutos.
- **W_block = estimación de primer orden**: ~200 ventanas-alarma → ~20 episodios por noche es una aproximación analítica, no una simulación sobre series de probabilidades predichas por paciente.
- **Paradoja Pac314**: AUC más alto del corpus (0,87) en el paciente de menor prevalencia (1,6%). Discriminación y prevalencia son ortogonales — el sistema PAC puede anticipar eventos en pacientes con pocos eventos severos siempre que su estado fisiológico sea suficientemente distinto del habitual.

### Consideraciones editoriales resueltas (historial de versiones)
- **v1**: borrador completo, sin figuras
- **v2**: 6 figuras NB08 incorporadas
- **v3**: densidad narrativa (inercia Markoviana en intro + ranking vs probabilidad); §8.1 hipótesis operacional; §8.4 delta AUC fisiológico; §8.5 W_block desarrollado
- **v4**: §8.5 nota "estimación primer orden"; §8.7.3 circularidad PAC + validación ideal especificada; §8.8 frase clínica final
- **v5**: referencia Wasserstein → Saito & Rehmsmeier (2015) para AP; figuras uniformadas; §8.6.1 condicional estimulador
- **v6**: §8.2.3 scale_pos_weight explicitado + cita Niculescu-Mizil & Caruana (2005); §8.7.4 calibración anclada; bibliografía 6→9 referencias (+Clifton 2015, +Niculescu-Mizil & Caruana 2005); §8.6.1 Clifton para lead time clínico

### Build
- Script: `build_cap08_v2.js` (acumulativo, en carpeta temporal de Cowork)
- Output: `tesis_cap/Cap08_prediccion_prospectiva_v6.docx`

---

## 16. Notas de sesión — Cap08 resumido v14 (Junio 2026)

### Correcciones técnicas verificadas contra NB08
- **Lookback del historial reciente**: 5 min (eventos) y 10 min (fracción severos). El texto anterior decía "5 y 15 min" — corregido.
- **Imputación morph_mean_5min**: mediana del **corpus** (global), no del paciente. El texto anterior decía "mediana del paciente" — corregido.
- **Exclusión de ventanas con evento activo**: no es una exclusión explícita en el código; el escenario prospectivo se define porque el target y_H referencia únicamente eventos futuros al cierre de la ventana.

### Figuras incorporadas al cuerpo del resumido
- **Fig. 8.2** (AUC vs lead time): en §8.5, actualizada sin panel de tabla embebida (regenerada desde NB08).
- **Fig. 8.3** (feature importance por horizonte): en §8.4, después del párrafo de features.
- **Fig. 8.4** (heatmap AUC × paciente): en §8.4, después del párrafo del Paciente 314.
- **Tablas 8.2 y 8.3** (prevalencia): movidas del Anexo al cuerpo de §8.3.

### Decisiones de estilo aplicadas al resumido
- **Sin rayas largas** en el cuerpo del texto — reemplazar por paréntesis o punto y coma.
- **Sin referencias NB07/NB08** en títulos de tablas y figuras — usar descripciones sustantivas.
- **Tono de potencialidad**: "confirma" → "sugiere"; "puede predecir" en pregunta retórica es aceptable; "es posible" → "resulta factible en la medida en que".
- **"modelo predictivo"** → "módulo de predicción prospectiva" en contextos donde se describe el módulo NB08.

### Estructura del resumido v14 (8 secciones)
- **8.1** Formulación: Tabla 8.1 comparativa clasificación condicional vs. predicción prospectiva
- **8.2** Diseño: corpus, 5 bloques de features, LOPO-CV
- **8.3** Prevalencia: Tabla 8.2 (por horizonte) + Tabla 8.3 (por paciente) + párrafo sobre heterogeneidad y decisión de umbral Youden global
- **8.4** Rendimiento: Tabla 8.4 + Fig. 8.3 (features) + Fig. 8.4 (heatmap AUC paciente) + frase de cierre sobre estrategia estable
- **8.5** Operacional: intro con 3 preguntas + Fig. 8.2 + Tabla 8.6 + estimación 20 alarmas/noche + nota epistemológica sobre ranking vs. probabilidad + frase de cierre
- **8.6** Implicancias: cadena decisión → actuación → hipótesis estimulador
- **8.7** Limitaciones: lista en orden de impacto
- **8.8** Conclusión: narrativa sin números, cierre con agenda para Cap09

### Glosario (Anexo B)
- **ramp-up** agregado al Anexo B: período de latencia entre activación del estímulo y efecto fisiológico (~90 s para estimulación transcutánea, Clifton et al. 2015).

### Evaluación como jurado
- **Calificación: 9.5/10** — estructura sólida, rigor honesto, tono correcto. El 0.5 restante es estructural (n=8) no editorial.

---

## 17. Referencias pendientes de incorporar (buscadas en Open Evidence)

Referencias identificadas como relevantes para Cap09, pendientes de incorporar cuando corresponda:

### Fenotipado morfológico de eventos / clustering de oximetría (§9.2)
- **Zhang, X., Li, F., Fang, Y., et al. (2026).** Novel event-based peripheral oxygen saturation metrics provide complementary information for OSA classification. *IEEE Transactions on Bio-Medical Engineering.* https://pubmed.ncbi.nlm.nih.gov/41701586 — **Muy relevante**: métricas basadas en eventos individuales de SpO₂. Revisar si opera sobre morfología de curva o solo features escalares.
- **Terrill, P. I. (2020).** A review of approaches for analysing obstructive sleep apnoea-related patterns in pulse oximetry data. *Respirology.* https://pubmed.ncbi.nlm.nih.gov/31246376 — **Relevante**: review del panorama de métodos de análisis de oximetría en OSA hasta 2020. Útil para mostrar ausencia del enfoque morfológico.
- **Biedebach, L., Ferreira-Santos, D., Stefanos, M. A., et al. (2025).** Unsupervised machine learning in sleep research: a scoping review. *Sleep.* https://pubmed.ncbi.nlm.nih.gov/40719375 — **Relevante**: scoping review de ML no supervisado en sueño. Citar cuando se afirma que el fenotipado morfológico no supervisado de EDOs no tiene equivalente publicado.

### Fenotipado / ML en OSA (contexto general)
- **Ma, E. Y., Kim, J. W., Lee, Y., et al. (2021).** Combined unsupervised-supervised machine learning for phenotyping complex diseases with its application to obstructive sleep apnea. *Scientific Reports.* https://pubmed.ncbi.nlm.nih.gov/33627761 — ML no supervisado + supervisado para fenotipado de OSA, probablemente a nivel paciente/noche, no evento individual.
- **Vaquerizo-Villar, F., Álvarez, D., Gutiérrez-Tobal, G. C., et al. (2022).** Deep-learning model based on convolutional neural networks to classify apnea-hypopnea events from the oximetry signal. *Advances in Experimental Medicine and Biology.* https://pubmed.ncbi.nlm.nih.gov/36217089 — Clasifica eventos desde oximetría con deep learning, no clustering morfológico.
- **Resta, E., Gnoni, V., Cistulli, P., et al. (2025).** Distinct hypoxemic profiles of obstructive sleep apnea in Southern Italy: The Living With OSA and CPAP Study. *Journal of Clinical Medicine.* https://pubmed.ncbi.nlm.nih.gov/41517455 — Perfiles hipoxémicos de OSA, orientado a índices agregados nocturnos.
- **Álvarez, D., Gutiérrez-Tobal, G. C., Vaquerizo-Villar, F., et al. (2022).** Oximetry indices in the management of sleep apnea: from overnight minimum saturation to the novel hypoxemia measures. *Advances in Experimental Medicine and Biology.* https://pubmed.ncbi.nlm.nih.gov/36217087 — Índices de oximetría agregados, menos relevante para el punto morfológico.

---

## 18. Notas de sesión — Cap09 resumido v16 (Junio 2026)

### Estructura final (9 secciones)
- **Apertura**: cuatro contribuciones articuladas (fenotipado+ARI / PAC States / acoplamiento / predicción prospectiva)
- **9.1** Índices de evento e índices agregados — posiciona en la trayectoria de la literatura (Azarbarzin, Sands), sin re-explicar AHI/ODI3
- **9.2** Fenotipado morfológico: 9.2.1 morfotipos vs literatura (IEI→baseline 120s como validación interna) · 9.2.2 ARI ortogonal (gradiente inverso + ICC vs ODI3)
- **9.3** PAC States: 9.3.1 triple innovación · 9.3.2 especialización funcional + variabilidad intraindividual como información
- **9.4** Acoplamiento morfotipo–estado (V de Cramér + resiliencia + inercia → NB08)
- **9.5** Modelos de predicción vs literatura (Behar, Clifton) + framework 3 fases validación dispositivos médicos
- **9.6** Oximetría vs PSG — 3 oraciones, posiciona resultados, no repite Cap02
- **9.7** Hacia la terapéutica automática: heterogeneidad inter-paciente (paradoja Pac314) · circularidad PAC · diseño ensayo clínico (30–50 pac, anclado en potencia)
- **9.8** Limitaciones integradas (5, ordenadas por impacto)
- **9.9** Síntesis: 4 contribuciones (Primera/Segunda/Tercera/Cuarta) + cierre de posicionamiento en literatura ("fronteras conocidas y diseñables")

### Decisiones de estilo
- Sin sección de Referencias al final (todas están en Anexo A — cotejadas, ninguna faltaba)
- Formato: Aptos 12pt, interlineado 1.5, márgenes A4 igual a Cap02 (top/bottom 1701, header/footer 708)
- Header: borde azul `1E3A5F`; footer: borde gris `D1D5DB`; línea "Versión" en itálica color `666666`
- Cierre §9.9: párrafo de posicionamiento vs literatura (no metafórico — reservado para Cap10)

### Calificación jurado
- **9.5 / 10** — techo editorial alcanzado. 0.5 estructural (n=8, circularidad PAC)

### Build
- Script: `build_cap09_resumido_v16.js` (outputs temporales Cowork)
- Output: `tesis_cap/Cap09_Discusion_resumido_v16.docx`

---

## 19. Notas de sesión — Cap10 resumido v4 (Junio 2026)

### Estructura final (5 secciones)
- **Apertura**: bridge desde Cap09, presenta cadena EDO→Estados→Acople→Fenotipia→Predicción
- **10.1** Tabla 10.1: 6 objetivos de Cap01 con respuesta numérica verificable
- **10.2** Contribuciones en 3 planos: científico (ARI, especialización funcional, variabilidad) · metodológico (Medallion, QC no destructivo, LOPO-CV) · clínico (PAC App + condición algorítmica mínima)
- **10.3** Tabla 10.2: T1–T4 con estado
- **10.4** 8 líneas de trabajo futuro ordenadas: gaps metodológicos (1-3) → ensayo clínico (4-5) → extensiones (6-8)
- **10.5** Reflexión final: pregunta de apertura → respuesta condicional y precisa → estructura fisiológica → naturaleza representacional de la contribución ("El ARI no es un modelo: es una pregunta") → cierre metafórico "punto más oscuro"

### Decisiones de estilo
- §10.2: "no registra equivalente publicado en la literatura revisada" (alineado con Cap09, no "no tiene precedente publicado")
- §10.5: oración de cierre del círculo con Cap01: "La pregunta con la que abrió esta tesis tiene ahora una respuesta parcial y verificable"
- Cierre final (último párrafo de la tesis): "Bajo la lupa del Proyecto PAC, una noche de sueño deja de ser un número: se convierte en una trayectoria con memoria... punto más oscuro"

### Calificación jurado
- **9.5 / 10** — mismo nivel que Cap08 y Cap09. 0.5 estructural (n=8, circularidad PAC)

### Build
- Script: `build_cap10_resumido_v4.js` (outputs temporales Cowork)
- Output: `tesis_cap/Cap10_Conclusiones_resumido_v4.docx`

---

## 20. Sesión de correcciones post-checklist (Junio 2026) — ESTADO ACTUAL DEFINITIVO

> Esta sección **prevalece** sobre cualquier número/versión mencionado más arriba en caso de conflicto. Surge de aplicar el `Checklist_Correcciones_Tesis_PAC.docx` (C1–C4, I1–I3, M1–M13) más una verificación conjunta de coherencia. **Cada corrección se verificó a nivel pipeline/notebook (Gold parquet + NB01–NB08), no contra el texto previo.**

### Principio rector
**El Gold (`gold/*.parquet`) es la única fuente de verdad.** Donde el texto, el CLAUDE.md o el output guardado de un notebook discrepaban del Gold, se re-baseó al Gold. Excepción explícita: el **Risk Score** (ver abajo).

### Manifiesto de versiones finales (resumido)
| Documento | Versión final |
|---|---|
| Cap01 Introducción | resumido v11 |
| Cap02 Marco Teórico | resumido v4 |
| Cap03 Materiales y Métodos | resumido v11 |
| Cap04 Fenotipado + ARI | resumido v20 |
| Cap05 PAC States | resumido v21 |
| Cap06 Modelado predictivo | resumido v36 |
| Cap07 App clínica | resumido v12 |
| Cap08 Predicción prospectiva | resumido v18 |
| Cap09 Discusión | resumido v22 |
| Cap10 Conclusiones | resumido v10 |
| Anexo A Referencias | v5 |
| Anexo B Glosario | v16 |
| Anexo Suplementario | v21 |

> ⚠ **Manifiesto actualizado en la sesión de verificación independiente (Jun 2026, §21).** Cap06/Anexo B/Cap01 corregidos re-aplicando sobre las versiones paralelas v35/v15/v9. Quedan en `tesis_cap/` versiones intermedias superables (Cap01 v8, Cap06 v34, Anexo B v12) que pueden borrarse.

### Cifras canónicas (verificadas contra Gold)
- **Universos de eventos** (ver Tabla 3.2 nueva en Cap03 §3.3.4): 85.286 detectados → 85.277 quality+morfotipo → 83.892 con estado PAC → 80.345 con morfotipo+3 escalas (universo del RR) → 78.908 estrictos con contexto → 76.053 Bloque B. El **84.193 era un error de suma** (ya no existe).
- **Noches**: 560 in_quality (todas con ≥1 EDO) · 540 estrictas · 494 Bloque C (NB07) · **513 noches / 12 pacientes** en el clustering de fenotipos de trayectoria (era "511/8 pac", incorrecto).
- **Morfotipos (Tabla 4.2 y 4.6)**: C1 55.175 (64,7 %) · C2 21.318 (25,0 %) · C3 3.662 (4,3 %) · C4 4.301 (5,0 %) · C5 821 (1,0 %). C4+C5 = 6,0 %.
- **ARI**: fórmula canónica = 2 componentes `0,6·P(hr_gain)+0,4·P(mov_gain)` sobre `drop_pct` (NO 3 componentes; la Tabla 4.5 es la combinación naïve **descartada** por escala — MOV crudo absorbe ~98,5 %). ARI C5 = **0,423 ± 0,104**. **Titular de ortogonalidad = ρ(ARI,drop_pct)=0,035** (severidad del evento). ⚠ ρ(ARI,ODI3) NO es 0,034: verificado contra Gold = **−0,066 (evento) / −0,245 (noche)**; el 0,034 era el valor de drop_pct mal etiquetado (corregido Jun 2026 en Cap09/Cap10/glosario; H1 Opción B). ICC=0,69/0,74.
- **Carga hipóxica C4+C5 = 23,8 %** del total (vs 6,0 % de prevalencia); C5 solo = 7,0 %.
- **RR evento severo (NB05, marginal 5,73 %)**: S6 = **4,9×**, M1 = 3,3×, L0 = 2,0× (el "4,70×/5,97 %" era viejo).
- **V de Cramér** morfotipo–estado (Gold): 0,356/0,231/0,196. La tesis usa 0,355/0,229/0,194 (diferencia ≤0,002, internamente consistente — se dejó así).
- **AUC**: noche 0,905 (LR, **valor agrupado/pooled sobre 494 noches; AUC por paciente solo definido en 5/8 folds**, media 0,856) · evento 0,878 (LightGBM) · prospectivo H=5min 0,821. RF noche 0,777; AP noche 0,834.
- **PCA features nocturnas (21)**: **PC1 = 36,7 %** (el 29,2 % era incorrecto).
- **Especialización funcional**: S4→ODI3 (+0,691); M1→T90 (+0,744); S5→ARI (+0,637); L0→T90 (+0,705).

### Risk Score (re-basado al Gold, Jun 2026 — H2 Opción A)
- **Risk Score PAC**: medianas **29,2 / 29,4 / 72,9 / 81,0** (Normal/Leve/Moderado/Severo) — valores del Gold (`risk_score`), que reproducen **exactamente** la fórmula NB07 (`p_ev_norm = p_ev / p_ev.max()`, verificado al decimal). Las medianas previas 25,6/31,6/72,2/80,8 eran un artefacto **no reproducible** desde el Gold y se descartaron. Capturas @60: 100 % Severas · **77,6 % Moderadas · 9,0 % Leves** (n=494). La mediana de Leve (29,4) cae en el rango **Bajo (<30)**, junto con Normal (29,2) — con esto la corrección M12 queda obsoleta (ningún valor >30 mal etiquetado).

### Publicaciones (estado unificado)
- **T1 = "Enviado (junio 2026)"** / "Manuscrito enviado para publicación" (Anexo A cita `Inza et al., 2026`). T2–T4 = "En preparación". (Antes había "en preparación"/"publicada"/"mayo 2025" mezclados.)

### Citas corregidas
- Descomposición del SAOS en 4 rasgos = **Eckert et al. (2013)** (no Sands). Sands et al. = **2018** (no 2021), para cuantificación del umbral de arousal desde PSG. Prabhakar en glosario = **2016a**.

### Referencias cruzadas corregidas
- Objetivos de Cap01 = **§1.2** (no §1.6). Gradiente inverso del C5 = Cap04 **§4.3.2** (no §4.3.3).

### Pendiente opcional (no afecta la tesis)
- Markdown de NB01/NB03 todavía dice "553 noches" (etiqueta de fuente; el cómputo da 560). No tocado.

### Estado
**Checklist completo (C1–C4, I1–I3, M1–M13) + verificación conjunta cerrados. Cifras de titular consistentes entre los 13 documentos y coincidentes con el Gold.** Listo para evaluación estricta independiente.
