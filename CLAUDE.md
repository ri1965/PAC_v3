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
| **Nota de nomenclatura** | ⚠ **Corregido Ago 2026 (§41).** El nombre es **Proyecto de Perfilamiento y Análisis Continuo (Proyecto PAC)** — así aparece en las 6 menciones del consolidado. El «Procesamiento Autonómico Continuo» que decía esta fila **no existe en la tesis** (0 apariciones): no usarlo y sobre todo no dispararlo como reemplazo global. Tampoco «Proyecto APNEA» (0 apariciones). El pipeline se llama PAC_v3. En la primera mención de cada capítulo usar la forma completa; el resto puede usar «Proyecto PAC». |
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

> ⚠ **Esta subsección describe los .docx por capítulo, no el consolidado.** Verificado sobre la v171: el encabezado real es el título de capítulo y el pie dice «Magíster en Explotación de Datos y Gestión del Conocimiento» + folio. No hay ningún «Proyecto APNEA». Vale como referencia histórica de los capítulos sueltos; para el consolidado mandan §26 y §37.

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

  **Gradiente autonómico inverso (Cap04 §4.3.2)**: C5 presenta el ARI más bajo del corpus (0,423 ± 0,104). Los morfotipos severos tienen mayor carga hipóxica pero menor reactividad autonómica, no mayor.

### Representaciones derivadas
- **Morfotipos C1–C5**: 5 fenotipos de curvas SpO₂ individuales, obtenidos por K-means (K=5) sobre PCA de 30 puntos de curva normalizados (85.277 EDOs con morfotipo asignado). C4+C5 = severos (5.122 eventos, 6,0% del corpus de 85.277).
- **Morfotipos escalares**: clustering sobre vector de 10 features morfológicas por evento (duración, drop_pct, nadir, pendientes de bajada y recuperación, AUC y los cuatro componentes de la respuesta), z-scoreadas. Complementa C1–C5, que sale de la forma de la curva. ⚠ **Corregido Ago 2026 (§44): el modelo de producción es K = 10, no K = 4** — `edo_morphotype_metadata.json` declara `k: 10` con letras α a κ, y el Gold tiene las diez. La ficha anterior decía «α–δ, K=4», que es la nomenclatura de una versión previa. El vector de ventana de los Estados PAC cuenta solo α, β, γ y δ; ver §44.
- **PAC States (PAC_v3)**: sistema de estados dinámicos a 3 escalas temporales:
  - **Escala S** (30 s): K=7, estados S0–S6. S1+S2 ≈ 60% del tiempo. S6 excluido de feature matrix nocturna por baja frecuencia (~1%). Mejor predictor de frecuencia: S4 (ρ ODI3 = +0,690).
  - **Escala M** (5 min): K=5, estados M0–M4. Mejor predictor de carga hipóxica: M1 (ρ T90 = +0,744).
  - **Escala L** (30 min): K=4, estados L0–L3. Polos: L0 hipoxemia sostenida (ρ T90 = +0,683 · corregido en §23), L3 baja carga (ρ ARI = +0,357).
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
- **4.2** Fenotipado morfológico (NB01): PCA (PC1=62,9% / PC2=14,0% / PC3=7,0%); K=5 (Silhouette=0,432; no es máximo, decrece desde K=2 — se elige por interpretabilidad C4/C5); morfotipos C1–C5; distribución (C4+C5=6,0%; C4=4.301/5,0%, C5=821/1,0%); IEI mediano=82s; correspondencia con α–δ; ICC inter-noche
- **4.3** Diagnóstico IRD → definición ARI (NB02): bug de escala en IRD; ρ(ARI, drop_pct)=0,034; gradiente inverso C5 ARI más bajo (0,423); análisis within-stratum; ICC(1,1)=0,69/0,74
- **4.4** Síntesis features nocturnas (NB03): matriz 50 features, 560 noches (re-baseado desde 553)
- **4.5** Validación reproducibilidad multi-noche: ODI3 necesita ~7 noches; ARI estable desde noche 1

---

## 9. Estructura de Cap05 (referencia rápida)

PAC States multiescala. Versión final: v12.

- **5.1** Fundamentos (NB03): validación ARI como feature estable (ICC=0,69; ρ ODI3=0,041); construcción espacio de estados; Tabla 5.2 parámetros por escala; V de Cramér como métrica de asociación
- **5.2** Escala S — microdinámica (NB04): K=7, S0–S6; S1+S2≈60%; S4 mejor predictor AHI (ρ=+0,690 · corregido en §23); S5 reactividad máxima (ρ ARI=+0,637); S6 más raro (~1%)
- **5.3** Escala M — regulación intermedia (NB04): K=5, M0–M4; M1 mejor predictor T90 (ρ=+0,744); M0/M2 protectores; arquetipos A/B/C (50%/35%/15%)
- **5.4** Escala L — arquitectura global (NB04): K=4, L0–L3; L0 hipoxemia sostenida (ρ T90=+0,683 · corregido en §23); L3 baja carga (ρ ARI=+0,357)
- **5.5** Features nocturnas multiescala: 15 fracciones (frac_s_S0–S5 excluye S6 + frac_m_M0–M4 + frac_l_L0–L3) + 3 entropías + 3 transiciones = 21 features PAC; **PCA PC1=36,7%** (verificado sobre Gold; el viejo 29,2% era incorrecto)
- **5.6** Especialización funcional (hallazgo central): S4→frecuencia (AHI); M1→carga hipóxica (T90); S5→reactividad autonómica (ARI); L0→arquitectura global
- **5.7** Síntesis y limitaciones; bridge al Cap06

---

## 10. Estructura de Cap06 (referencia rápida)

Modelado predictivo basado en PAC. Versión final: v7.

- **6.1–6.2** Introducción y corpus (NB05: 12 pac./80.353 ev./560 noches; NB06/07: 8 pac.)
- **6.3** Acoplamiento morfotipo–estado (NB05 §2): V de Cramér S=0,356/M=0,231/L=0,196 (unificado, antes 0,354/0,230/0,194); estados patológicos S2/S4/S6, M1/M3, L0/L1; RR: S6×4,9 / M1×3,3 / L0×2,0
- **6.4** Coupling index nocturno: ci_s vs ci_m prácticamente independientes (r=0,056); ci_m/ci_l moderado (r=0,364)
- **6.5** Resiliencia post-evento severo: S=43,3% / M=12,3% / L=1,3% — inercia creciente con la escala
- **6.6** Dinámica Markoviana: 462.519 trans. S / 45.900 M / 7.196 L; atractores S1/M0/L3
- **6.7** Fenotipos de trayectoria nocturna (K=3, NB05 §6): Estable-Protector / Carga Intermedia / Carga Hipóxica Alta; hallazgo clave: fenotipo CHA aparece en subgrupo SAOS Moderado
- **6.8** Ablación → título "Importancia **discriminante**" (NB06): PAC States 44,8% (Gini 0,4485, 15 vars); morfotipos 20,6% (0,2057); dinámica 14,7% (0,1470); clínicas 10,1%; sueño 6,6%; ARI 3,3% (0,0325). Balanced acc.: PAC-only **0,481** (antes 0,521, stale) / clínicas 0,354 / ARI 0,281
- **6.9–6.10** Predicción evento severo (NB07 Bloque B): LightGBM AUC=**0,882** / LR=0,745; AP=**0,264** vs baseline=**5,57%** (§25, bug PATH_M); 76.053 eventos, 4.238 severos, 8 pac.
- **6.11–6.12** Clasificación riesgo nocturno → título "**Clasificación de riesgo a nivel de noche**" (NB07 Bloque C): LR AUC=0,905 / RF=**0,777**; AP=0,834 vs baseline=0,348; fracciones M dominantes (**77,8%** de la importancia, antes 88,9% stale); 494 noches, 34,8% pos.
- **6.13** Risk Score PAC (0–100): 0,40×p_ev_norm + 0,60×p_high_risk_night (heurístico); bandas **Bajo<30 / Intermedio 30–60 / Alto>60** (banda media renombrada "Intermedio" para no chocar con AASM Moderado); medianas **28,2/29,3/73,1/81,3**; @60 captura 100% Sev / 77,6% Mod / **9,0%** Leves (§25); Moderado AASM abarca RS 23–100; lead time ≈5 min = ventana causal NB07, NO predicción prospectiva (eso es Cap08)
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

*Última actualización: Agosto 2026 — **§44 y §44.b: deuda técnica detectada al preparar la defensa** (morfotipos escalares K=10 y el IRD sobreviviente en el vector de ventana); no afecta cifras publicadas, ver `DEUDA_TECNICA_Y_PRODUCCION.md` §2.6 y §2.7. **§43: cerrados los 5 puntos finales del director + verificación de autenticidad de las 58 citas.** Consolidado vigente `tesis_cap/Tesis_PAC_v189.docx` · 172 páginas · 39/39 · pendiente el F9 en Word. Lo que sigue describe la entrega previa: consolidado `tesis_cap/Tesis_PAC_v175.docx` · 164 páginas · 39/39 controles · los 10 puntos del director cerrados · barrido visual limpio (0 páginas en blanco, 0 pies huérfanos, 0 tablas partidas, índices sin discrepancias) · Reconocimientos y carátula incorporados. La versión de entrega se generó desde la v175 sin sufijo de versión. Ver §42 para la ronda de cierre y §41 para la lectura fina de estilo; §26 fija los criterios editoriales y las cifras canónicas.*

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
- **V de Cramér** morfotipo–estado (Gold): 0,356/0,231/0,196. ⚠ **Superado por §22**: la tesis quedó unificada en 0,356/0,231/0,196.
- **AUC**: noche 0,905 (LR, **valor agrupado/pooled sobre 494 noches; AUC por paciente solo definido en 5/8 folds**, media 0,856) · evento **0,882** (LightGBM, §25) · prospectivo H=5min 0,821. RF noche 0,777; AP noche 0,834.
- **PCA features nocturnas (21)**: **PC1 = 36,7 %** (el 29,2 % era incorrecto).
- **Especialización funcional**: S4→ODI3 (**+0,690**); M1→T90 (+0,744); S5→ARI (+0,637); L0→T90 (**+0,683**). ⚠ Los +0,691 / +0,705 previos fueron corregidos contra el Gold en §23.

### Risk Score (re-basado al Gold, Jun 2026 — H2 Opción A)
- **Risk Score PAC**: ⚠ **superado por §25** (tras el bug PATH_M las medianas son **28,2 / 29,3 / 73,1 / 81,3** y la captura @60 de Leve es 9,0 %). El párrafo siguiente conserva el razonamiento original. Medianas **29,2 / 29,4 / 72,9 / 81,0** (Normal/Leve/Moderado/Severo) — valores del Gold (`risk_score`), que reproducen **exactamente** la fórmula NB07 (`p_ev_norm = p_ev / p_ev.max()`, verificado al decimal). Las medianas previas 25,6/31,6/72,2/80,8 eran un artefacto **no reproducible** desde el Gold y se descartaron. Capturas @60: 100 % Severas · **77,6 % Moderadas · 9,0 % Leves** (n=494). La mediana de Leve (29,4) cae en el rango **Bajo (<30)**, junto con Normal (29,2) — con esto la corrección M12 queda obsoleta (ningún valor >30 mal etiquetado).

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

---

## 21. Sesión recorte conceptual + re-verificación Cap 04 (Junio 2026)

Cap 04 llevado a versión **conceptual-anclada** (mensaje en prosa, números en tablas/figuras) y **re-auditado celda por celda contra el Gold**. Surgieron correcciones de datos que NO eran cosméticas (valores stale de corridas preliminares). **Valores canónicos confirmados/corregidos:**

- **Silhouette morfotipos de curva (NB01)**: K=5 = **0,432** (era 0,386). El Silhouette **decrece** desde K=2 (0,576/0,463/0,462/0,432/0,217/0,199); K=5 **no es máximo** — se elige por interpretabilidad (separa C4/C5) y por ser el último K antes de la caída en K=6. La fig. recalcula sobre muestra de 8000 (0,214); el valor canónico es el del training report.
- **Nadir de curva C5 (Tabla 4.2)**: **−15,3 pp** (era −10,1). drop_pct C5 = 24,4 media / 23,3 mediana.
- **Tabla 4.7 ICC ODI3**: **0,77 / 0,79** (full/strict) (era 0,71/0,72). Fuente canónica = **NB00 `icc_oneway`** (reproduce exacto ARI 0,69/HB 0,41/T90 0,52/SE 0,35). Nota: coexiste `icc11` (NB01, corrección n0) que da ~0,02 más.
- **Tabla 4.8 (estabilización ODI3, strict-8)**: MAE real **4,8 / 2,7 / 1,7 / 1,2** ev/h (1/3/7/14 noches). Se eliminó la columna ICC (el ICC del ODI3 vive solo en Tabla 4.7). Fuente: NB03 celda 67 / `APNEA_validacion`.
- **ρ(ARI, ODI3) noche = −0,245** (NO ≈0). La ortogonalidad ≈0 es **ρ(ARI, drop_pct)=0,035 a nivel evento**. (Mismo error que ya se corrigió en Cap09/10; estaba latente en §4.4.)

**Cambios estructurales Cap 04:** Tabla 4.9 (carga hipóxica acumulada por morfotipo: C4+C5=23,8% con 6,0% eventos; C5=7,0%) agregada al Anexo C + celda reproducible en NB01. Columna "Pos. nadir" eliminada de Tabla 4.2. §4.2.3 (IEI) fusionado en §4.2.2. Figuras regeneradas desde el Gold: **Fig 4.2** (`01_clustering_kmeans.png`) y **Fig 4.6** (`03_odi3_estabilidad_multinoche.png`); backups `_PRE_*`.

**⚠ IEI (82 s / 62,8 %)**: sin fuente reproducible en ningún NB (recompute Gold onset-to-onset = 81 s / 63,5 %). El glosario lo define end-to-start (daría 58 s) — inconsistencia no resuelta en Anexo B.

**Versión vigente del consolidado: `Tesis_PAC_v18.docx`** (v10 fue la base; v11 descartable). Cadena: v13 (Tabla 4.1) → v15 (silhouette+Fig4.2+Pos.nadir) → v16 (Tabla 4.7 ODI3) → v17 (Tabla 4.8+Fig4.6) → v18 (alt-text Fig 4.1).

**Pendiente:** (1) extender recorte conceptual + re-verificación contra Gold a **Cap 05 y Cap 06** (misma procedencia de métricas: silhouette/K, ICC, V de Cramér, AUC, RR — riesgo de errores análogos). (2) Reconciliar cohorte de Fig 4.6 en NB03 (usa ≥5 noches=10 pac; la tesis usa strict-8). (3) Glosario IEI (definición vs valor).

---

## 22. Sesión recorte conceptual + re-verificación Cap 06 (Junio 2026)

Cap 06 llevado a versión **conceptual-anclada** (prosa describe, números viven en tablas/figuras) y **re-auditado contra el Gold/NB06/NB07**. Consolidado vigente: **`Tesis_PAC_v38.docx`** (cadena v28→v38). Las cifras de abajo **prevalecen** sobre cualquier valor anterior de Cap 06.

### Cifras canónicas verificadas (Gold/NB06/NB07)
- **V de Cramér acoplamiento (unificado en todo el doc)**: **0,356 / 0,231 / 0,196** (S/M/L). Se descartó el "0,355/0,229/0,194" que la tesis traía; §20 queda superado en este punto.
- **§6.3 Coupling Index** — correlaciones cruzadas: r(ci_s,ci_m)=**0,056** (antes 0,066 stale); r(ci_m,ci_l)=**0,364** (antes 0,291 stale); r(ci_s,ci_l)=−0,113 (n=513).
- **§6.4 Resiliencia post-evento severo (NB05 §B4)**: resiliente 43,3/12,3/1,3 % (S/M/L); colapsado 40,2/80,4/74,5 %. ⚠ "resiliente" = ventana siguiente **no patológica** (sale del estado patológico), no estrictamente "protectora"; el resto al 100 % = sin ventana siguiente (último evento). Corredor Markoviano M0/M2→M4→M3→M1.
- **§6.5 Fenotipos de trayectoria (Tabla 6.5, NB05 §6, K=3, 513 noches/12 pac.)** — perfil por medianas: Estable-Protector M1=2,8% / ARI=0,522 / entropía M=1,497 / trans=29 / %sev=3,1; Carga Intermedia M1=3,5% / %sev=5,0% / ARI=0,493 / trans=42 / entropía=1,933; CHA M1=78,1% / %sev=**36,1%** (antes 37,9) / ARI=0,284 / trans=6 / entropía=1,122. CHA exclusiva de AASM **Moderado** (cross-tab: 4,4% Moderado, 0% Leve/Normal/Severo).
- **§6.6 Ablación → "Importancia discriminante"** (NB06, RandomForest, 540 noches, night_multiscale_features): Gini PAC States 0,4485 (44,8%, **15 vars** no 20) · Morfotipos 0,2057 (20,6%) · PAC Dynamics 0,1470 (14,7%) · Clínicas 0,1007 (10,1%) · Sueño 0,0656 (6,6%) · ARI 0,0325 (3,3%). Balanced acc.: **PAC-only 0,481** (el 0,521 era markdown stale del NB) / clínicas 0,354 / ARI 0,281.
- **§6.7 Evento (NB07 Bloque B)**: 76.053 ev., 4.238 severos = **5,57%** (baseline AP, antes 5,56); LightGBM AUC 0,878 / AP 0,240 (4,3×); LR 0,743 / 0,164 (2,9×); Youden LGBM Sens 0,87/Spec 0,76; rango AUC fold 0,798–0,964; features event_position>recent_morph_mean>ci_so_far.
- **§6.8 Noche → "Clasificación de riesgo a nivel de noche"** (NB07 Bloque C): 494 noches, 34,8% pos.; LR AUC **0,905**/AP 0,834; RF **0,777**/0,633 (antes 0,783); baseline 0,348; AUC pooled, por-paciente solo en 5/8 folds (media 0,856); fracciones M = **77,8%** de la importancia (el 88,9% venía de run preliminar con M0–M7; el Gold canónico tiene M0–M4).
- **§6.9 Risk Score**: bandas **Bajo<30 / Intermedio 30–60 / Alto>60** (banda media renombrada "Intermedio" para no colisionar con AASM "Moderado"; cambiado en nota Tabla 6.9, caveat y glosario). @60 captura 100% Sev / 77,6% Mod / **9,4%** Leves (≥60, convención inclusiva; el 9,0% usaba >60). Moderado AASM abarca RS 23–100. Spearman RS~ODI3 = 0,79 (discordancia inversa RS-bajo/ODI3-alto rara: 2,4%).

### Decisiones editoriales
- Títulos: §6.6 "predictiva"→"**discriminante**" (es clasificación retrospectiva, no predicción); §6.8 "Modelo predictivo a nivel de noche"→"**Clasificación de riesgo a nivel de noche**".
- Evitar "ablación" (→ "análisis de contribución") y "features" (→ "variables") en §6.6.
- Risk Score §6.9 reescrito didáctico: lectura de un valor concreto (RS<30 tranquila / >60 compromiso sostenido / 30–60 parcial), discordancia forward (riesgo oculto) + reverso.
- **Formato títulos/epígrafes normalizado document-wide**: títulos de figura/tabla = Aptos 10 bold; notas ("Nota.") = Aptos 9 italic (reparó captions que habían quedado sin rPr).

### Pendiente
- Reinsertar índice automático + niveles de esquema al final (se venía difiriendo).

---

## 23. Sesión auditoría Cap 05 (Junio 2026) — CERRADO

Cap 05 re-verificado celda por celda contra el Gold. **Resultado: prácticamente limpio** (a diferencia de Cap 04/06, no tenía valores stale). Consolidado vigente: **`Tesis_PAC_v39.docx`**.

### Verificado exacto contra Gold
- Especialización: M1~T90 **0,744** · M1~HB **0,618** · S5~ARI **0,637** · L0~T90 (t90_frac) **0,683** · L3~ARI **0,357**.
- Fracciones (window-level, states.parquet, 518.867 ventanas ≈ "~519K"): S1+S2 = 60,0 %; **S6 = 0,98 %** (el más raro); M0/M1/M2/M4 = 27/7/19/27; L0/L1/L2/L3 = 13/23/34/30.
- PCA 21 features (560 noches): PC1 36,7 % / PC2 20,2 % / PC3 12,1 % (69,0 % acum, 5 comp. para 80 %).
- Fenotipos trayectoria K=3 (513 noches): Estable-Protector 138 (27 %) / Carga Intermedia 368 (72 %) / CHA **7** (1 %). CHA M1≈78 %, ARI≈0,28.
- Tabla 5.2: V de Cramér 0,356/0,231/0,196; transiciones 462.519/45.900/7.196 (total 515.615); 83.892 eventos.

### Única corrección aplicada
- **S4~ODI3 = 0,690** (Gold 0,6896), antes **0,691**. Corregido en 7 lugares: Cap 05 (§5.2, nota Fig 5.5, Tabla 5.3) + Cap 09 + Cap 10 (texto + Tablas 10.1 y 10.2). Resto del valor (0,744/0,637/0,683) sin cambios.
- Recorte conceptual: no requerido — Cap 05 ya estaba conceptual-anclado (prosa describe, números en tablas).

**Estado: Cap 01–06 cerrados y re-baseados al Gold.** Consolidado = `Tesis_PAC_v40.docx`.

### Cierre de inconsistencias menores (v40)
- **Glosario IEI** reconciliado: definición → *inicio-a-inicio* (onset-to-onset); valor reproducible del Gold = **81 s / 63,5 % < 2 min** (events.parquet `ts_start`, n=84.726). Reemplaza el viejo "82 s / 62,8 %" con definición end-to-start inconsistente.
- **Fig 5.3 alt-text** corregido: "Perfil fisiológico de los cinco estados…" (stale, invisible) → "Fisiología de los eventos según el estado M activo (mediana ± IQR)" (coincide con el caption visible).
- **Fig 4.6**: en el docx ya está strict-8 (caption + figura regenerada). La inconsistencia ≥5 noches=10 pac es solo del código de NB03 (hygiene de notebook, no afecta la tesis).
- **Markdown "553 noches"**: verificado inexistente en NB01/NB03 (ni código ni salida). No hay nada que corregir.

### Único pendiente de Cap 01–06
- **Índice automático + niveles de esquema (outline)**: NO está (0 outlineLvl, 0 campo TOC). Hacerlo **al final de todo**, para no regenerarlo tras ediciones estructurales posteriores.

---

## 24. Sesión revisión Cap 07–10 (Junio 2026) — CERRADO

Consolidado vigente: **`Tesis_PAC_v43.docx`**. **Cap 01–10 revisados completos y re-baseados al Gold; barrido doc-wide de residuos stale = 0.**

- **Cap 07** (App clínica): aprobado como está, sin cambios (decisión del autor).
- **Cap 08** (predicción prospectiva, NB08): verificado exacto contra NB08 — 452.955 ventanas, prevalencia 3,74/8,04/13,88/18,89 %, Tabla 8.4 (AUC LR 0,789/0,774/0,760/0,750; LGBM 0,838/0,821/0,783/0,763; AP 0,203/0,326/0,396/0,449), Tabla 8.6 (Youden, Sens/Spec/PPV), heterogeneidad 20× (Pac175 32,1 % / Pac314 1,6 %, re-derivada desde events.parquet C4/C5). Únicos cambios: §8.5 PPV 5min **20,1→20,3 %** y estimación "~5→~4 reales" (coherencia con PPV 20 %).
- **Cap 09** (Discusión): 2 valores stale corregidos — §9.2.1 IEI **82 s/62,8 %→81 s/63,5 %** (inicio-a-inicio, alineado con glosario); §9.3.2 ARI trayectoria **0,524/0,492→0,522/0,493** (Tabla 6.5). Resto = cross-refs ya verificados.
- **Cap 10** (Conclusiones): limpio; S4→ODI3 ya en +0,690. Tablas 10.1/10.2 verificadas.
- **Residuo final**: nota Fig 6.15 (anexo) "Baseline AP 5,56→**5,57 %**".

### ⚠ Bug de Gold detectado (NO afecta la tesis) — tarea pendiente
- **`gold/window_risk_predictions.parquet`**: columnas `y_2min/y_5min/y_10min/y_15min` **desalineadas del `user_id`** (prevalencia por paciente sale uniforme ~8 %, ratio 1,7×; la verdadera, recomputada desde events.parquet y coincidente con NB08 c8, es 1,6–32,4 %, ratio 20×). Re-exportar alineado en NB08. La tesis usa los valores in-session de NB08 (correctos), así que no está afectada.

### Índice automático — HECHO (v45)
- Consolidado vigente: **`Tesis_PAC_v45.docx`**. Se insertaron niveles de esquema vía `outlineLvl` directo (sin tocar el formato visual): **92 párrafos** (10 capítulos a nivel 1 = subtítulo descriptivo; 66 secciones N.N a nivel 2; 16 subsecciones N.N.N a nivel 3). Campo TOC `TOC \o "1-3" \h \z \u` antes del Capítulo 1 + `updateFields=true` en settings.xml. ⚠ El índice es un placeholder hasta que Word actualice el campo (F9 / clic derecho → Actualizar campos) — Word calcula títulos y números de página al abrir.

> ⚠⚠ **ESTO YA NO ES CIERTO. Verificado en Ago 2026 (§41) sobre v169, v170, v171 y v172: el campo TOC no existe y `updateFields` no está en `settings.xml`.**
>
> En algún punto entre la v45 y la v169 el índice general fue **desvinculado** (*unlink fields*, ⌘⇧F9 en Word): quedó convertido en texto estático. Lo que hay hoy son **155 campos `HYPERLINK \l` + 186 campos `PAGEREF`** sueltos y **cero** instrucciones `TOC \o`. Las tres versiones dan exactamente los mismos conteos, así que no lo rompió ninguna sesión reciente.
>
> Consecuencias prácticas, que cambian el procedimiento de entrega:
>
> | | Antes se creía | Realidad |
> |---|---|---|
> | Word propone actualizar al abrir | sí (`updateFields=true`) | **no**: hay que acordarse del ⌘A + F9 |
> | F9 regenera las entradas del índice general | sí | **no**: solo actualiza los `PAGEREF` |
> | El índice general se repara solo si cambia un título | sí | **no**: es tan manual como los de figuras y tablas (§27) |
>
> **Lo que sigue funcionando:** F9 actualiza los 186 `PAGEREF`, así que **los números de página sí se corrigen**. Por eso no es un bloqueante de entrega.
>
> **Lo que hay que vigilar:** si alguna vez se edita el **texto de un encabezado**, o se agrega o elimina una sección, el índice general **no se entera** y hay que tocarlo a mano. Mientras las ediciones sean dentro de párrafos de cuerpo (como todas las de §41), no hay riesgo.
>
> Detección: `re.findall(r'<w:instrText[^>]*>(.*?)</w:instrText>', document.xml)` — si no aparece ningún `TOC \o`, está desvinculado.

### Pendientes de cierre final (después de todo)
1. **Corregir `y_Hmin`** en `window_risk_predictions.parquet` (hygiene de Gold; tarea #14, no afecta la tesis).

---

## 25. Sesión bug PATH_M + regeneración Gold + verificación app (Junio 2026) — CERRADO

Consolidado vigente: **`Tesis_PAC_v46.docx`**. Surge de verificar la PAC App corriendo sobre nochés-benchmark del Gold.

### Bug real encontrado y corregido (PATH_M en NB07)
- **NB07 usaba `PATH_M = {0,2,5,7}`** (numeración M=8 preliminar) en la feature `frac_path_m_30ev` del modelo de evento, cuando el modelo se entrenó con `{1,3}` (M1,M3 canónico; `generate_app_models.py`) y la app usa `{1,3}`. **Corregido en `NB07_prediccion.ipynb` → `{1,3}`** y re-corrido NB07 (regenera p_severe_mean/p_high_risk_night/risk_score en `night_multiscale_features.parquet`). Backup: `night_multiscale_features_PRE_pathm.parquet`.
- **Efecto (menor):** AUC evento **0,878→0,882**, AP **0,240→0,264**, mejora 4,3×→4,7×, Youden LGBM Sens 0,87→0,89/Spec 0,76→0,75, rango fold 0,798–0,964→0,803–0,960; LR AUC 0,743→0,745/AP 0,164→0,165/2,9×→3,0×. RS medianas 29,2/29,4/72,9/81,0 → **28,2/29,3/73,1/81,3**; captura @60 Leve 9,4%→**9,0%** (Mod 77,6%, Sev 100% igual). **§6.8 (noche) sin cambios** (0,905/0,777). Aplicado a la tesis en v46 (§6.7, §6.9, Tabla 6.9 composición, Fig 6.15, Tabla 8.1, Tablas 10.1/10.2, glosario).

### Aclaración clave (mi diagnóstico inicial fue erróneo)
- El `p_severe_mean` del Gold **NO está roto**: es la predicción **LOPO out-of-fold** (`ev_df['p_severe']=all_probs`, NB07 c15/c19), metodológicamente correcta. La ρ≈0 a nivel noche-promedio es esperable (predicción dominada por contexto), no un bug. La discordancia §6.9 es **real**, no artefacto.
- La divergencia app↔Gold (exam_12038: app RS 34 vs Gold 72) es **in-sample (app, modelo guardado entrenado con los 8 pac.) vs out-of-fold (Gold/tesis, LOPO)** — esperable para pacientes de la cohorte; para un paciente nuevo (producción) la app se comporta out-of-fold. Ninguno está "mal".

### Bug real de la app (corregido aparte)
- `app/pipeline.py`: normalizador del Risk Score era `p_severe_mean / 0.30` (hardcode incorrecto) → inflaba el RS ~25 pts. **Corregido a `/ 0.7431`** (= p99 de p_severe_mean del corpus, NB07). Verificado: exam_11555 RS 98→74, reproduce el batch.

### §7.4 (RESUELTO en v47)
- El ejemplo de §7.4 (antes 87 EDOs, ODI₂ 10,4, ci_m 0,82, "CHA" — no correspondía a noche real) se reescribió con `exam_11555` (NR_4c7feeef42, pac 656, **Carga Intermedia**) verificada con la app: 259 EDOs, ODI₂ 32,3, 18 severos (6,9 %), ci_m 0,944, RS 74 (Alto), valores consistentes con el batch out-of-fold (73,1).

### Consolidado vigente: `Tesis_PAC_v47.docx`

### Pendiente de cierre (no afecta la tesis)
1. **`y_Hmin`** desalineado en `window_risk_predictions.parquet` (tarea #14, hygiene de Gold).

---

## 26. Sesión de cierre editorial (Julio 2026) — v142 → v146

> ⚠ **Esta sección prevalece sobre §20–§25 en todo lo que sea formato, terminología y bibliografía.**
> Las cifras y resultados de §20–§25 siguen vigentes: esta sesión **no tocó ningún número**.

### Consolidado vigente: `tesis_cap/Tesis_PAC_v146.docx`

Cadena: v142 (entrada, con devolución del tutor) → **v143** formato → **v144** bibliografía → **v145** terminología y estilo → **v146** tono de potencialidad.

### Cifras canónicas vigentes (leer esto antes que §9, §10 o §20)

Verificadas contra el Gold y contra el consolidado. **Prevalecen sobre cualquier valor de las secciones anteriores.** La lista completa, en formato ejecutable, está en `scripts/tesis_qa/cifras_canonicas.py`.

| Métrica | Valor | Ojo con |
|---|---|---|
| EDOs quality / detectados | 85.277 / 85.286 | nunca 84.248 ni 84.193 |
| Noches quality / estrictas / Bloque C | 560 / 540 / 494 | nunca 553 |
| Ventanas NB08 | 452.955 | |
| V de Cramér S / M / L | 0,356 / 0,231 / 0,196 | nunca 0,355 / 0,229 / 0,194 |
| AUC evento (LightGBM) · AP | **0,882** · **0,264** | nunca 0,878 / 0,240 (pre-PATH_M) |
| AUC noche LR / RF | 0,905 / 0,777 | nunca 0,874 / 0,815 |
| AUC prospectivo H = 5 min | 0,821 | |
| S4→ODI3 | **+0,690** | nunca +0,691 |
| M1→T90 · S5→ARI | +0,744 · +0,637 | |
| L0→T90 · L3→ARI | **+0,683** · +0,357 | nunca +0,705 |
| PC1 de las 21 variables | 36,7 % | nunca 29,2 % |
| Silhouette K = 5 | 0,432 | nunca 0,386 |
| ρ(ARI, drop_pct) | 0,035 | el 0,034 era drop_pct mal rotulado |
| ARI del morfotipo C5 | 0,423 ± 0,104 | |
| C4+C5 · su carga hipóxica | 6,0 % · 23,8 % | nunca 6,1 % |
| Gini de Estados PAC | 44,8 % (15 variables) | |
| Risk Score PAC (medianas) | **28,2 / 29,3 / 73,1 / 81,3** | nunca 25,6/31,6/72,2/80,8 ni 29,2/29,4/72,9/81,0 |
| IEI (inicio-a-inicio) | 81 s · 63,5 % < 2 min | nunca 82 s / 62,8 % |

### Auditoría automática — correrla SIEMPRE antes de entregar

```bash
python3 scripts/tesis_qa/auditar_tesis.py tesis_cap/Tesis_PAC_v146.docx
```

**33 controles en cinco bloques**, código de salida 0 si pasa todo (v146 pasa los 33):

| Bloque | Qué controla |
|---|---|
| 1–7 | Defectos puntuales, referencias APA, tablas, cursivas, terminología, carátula, estilo |
| 8 | Cruce citas ↔ referencias (huérfanas y citas sin entrada) |
| 9 | Cruce figuras ↔ referencias cruzadas |
| 10–12 | **Cifras canónicas**: presentes, valores superados que reaparecen, coherencia interna |
| 13 | **Tono de potencialidad** (advertencia: lista para revisión, no hace fallar) |

Archivos: `auditar_tesis.py` (lógica), `cifras_canonicas.py` (los datos), `lib_docx.py` (edición quirúrgica de .docx preservando formato), `parse_refs.py` (detecta el tramo en cursiva de cada referencia APA).

⚠ **`cifras_canonicas.py` es la red que evita que un número vuelva atrás.** Cuando el pipeline cambie una cifra, hay que editar ese archivo y **mover el valor viejo a `SUPERADOS`**. Los patrones de `SUPERADOS` evitan a propósito los números ambiguos (0,783 es el AUC de H = 10 min, 0,71 una especificidad, 0,354 una balanced accuracy): no agregar valores que colisionen con otra métrica legítima.

**Corrección detectada al construir la lista**: el consolidado usa **ρ(L0, T90) = +0,683** (8 apariciones, coherente en todo el documento). El **+0,705 de §9 y §20 es un valor viejo** que §23 ya había corregido contra el Gold y que quedó sin actualizar en esas dos secciones.

### Criterios editoriales fijados (no re-litigar sin motivo)

| Tema | Criterio |
|---|---|
| **Cursivas** | **En el cuerpo**: extranjerismo conceptual (*pipeline*, *baseline*, *clustering*, *lead time*, *fold*, *backend*, *ramp-up*, *ad hoc*) en cursiva **solo la primera vez**; nombres propios de método/software, nombres de archivo y nombres de componentes del pipeline (LightGBM, Random Forest, Streamlit, Plotly, LOPO-CV, PAC App, K-means, Silhouette, Medallion, `*.parquet`, Bronze, Silver, Events, Gold, NightRecordID) **siempre en redonda**, y el nombre de archivo entero, extensión incluida: `states.parquet`. **En el aparato** (notas `Nota.` y punteros `▸`): **cursiva íntegra**, sin excepciones adentro (§40). |
| **dimensión vs. variable** | `dimensión` = concepto ("el ARI como dimensión ortogonal"), geometría del espacio y dimensiones de una tabla de contingencia. `variables` = columnas de la matriz de diseño: las que se agrupan, se ordenan por importancia y se ablacionan. `características` **retirado** como sinónimo (queda solo en "características demográficas / del evento"). |
| **Estados PAC** | Mayúscula = el sistema (`Estados PAC`). Minúscula = una instancia concreta (`el estado PAC activo`). |
| **Risk Score** | Siempre `Risk Score PAC`, nunca suelto. |
| **Capítulo vs. Cap.** | `Capítulo N` en prosa corrida; `Cap. N` en referencias cruzadas, entre paréntesis, con `§` y en tablas. |
| **Cohorte** | `cohorte completa` (12 p.) y `cohorte estricta` (8 p.). Nunca `full` / `strict`. |
| **Tablas** | APA: línea superior, línea bajo el encabezado, línea inferior. **Sin verticales ni horizontales interiores.** Encabezado repetido entre páginas y `Nota.` debajo. |
| **Referencias** | APA 7 con sangría francesa (1,27 cm) y cursiva en revista+volumen (artículos) o título (libros y actas, sin el rango de páginas). **Sin `et al.` en la lista.** |
| **Comillas** | Tipográficas “ ”, no rectas. |
| **Notación** | Decimal con coma; porcentaje con espacio (`6,0 %`); espacio angosto (U+202F) entre magnitud y unidad (`30 s`, `5 min`). |

### Carátula

No existe plantilla oficial de la Maestría. Se derivó de seis tesis recientes: logo Austral centrado (4,5 cm), nombre de la maestría, **`Tesis de Maestría`**, fórmula de grado, `Autor:` y **`Director:`** (nunca `Tutor:` — unánime en el corpus), lugar y fecha.

### Bibliografía: 74 → 59 entradas

Cruce completo: 0 huérfanas, 0 citas sin entrada. Se **agregaron 24 citas** para conceptos que se usaban sin atribuir (Shannon→entropías, Jolliffe→PCA, Shrout & Fleiss→ICC, Efron & Tibshirani→bootstrap, Hosmer→regresión logística, Roberts→validación por grupos, Streamlit/Plotly, Brown/Anthropic→informe LLM, Ancoli-Israel, Collop, Bittencourt, Levendowski, Bailly) y **8 clásicos de SAOS** repuestos en Cap. 2 (Young 1993, Peppard 2013, Nieto 2000, Punjabi 2009, Yaggi 2005, Dempsey 2010, Lévy 2015, Malhotra 2021).

⚠ **15 referencias eliminadas — no reponer sin citarlas primero**: Álvarez 2022, Bonsignore 2019, Duran-Cantolla 2010, Goldberger 2002, Landis & Koch 1977, Linz 2018, McKinney 2010, Pedregosa 2011, Penzel 2016, Shamsuzzaman 2003, Stradling 2004, Xie 2016, Ye 2014, Yoon & Choi 2023, Zhang 2026.

⚠ Las tres de §17 pendientes de incorporar quedaron resueltas: Álvarez y Zhang **eliminadas**; Biedebach 2025 **citada** en §9.9 y completada con sus 7 autores (Sleep, 48(11), zsaf189).

### Corrección de fondo en Cap. 2

Dos citas estaban cruzadas en el párrafo de apertura: **Benjafield et al. (2019)** (prevalencia global) sostenía la frase de desenlaces cardiovasculares y **Marin et al. (2005)** (desenlaces cardiovasculares) sostenía la de prevalencia. Intercambiadas.

### Defectos del tipo "hueco de reemplazo global"

El jurado detectó 5; había **7**. Los dos que no vio: `Importancia discriminante (Gini):  44,8 %` (Tabla 1.2 del Anexo) y `evaluación de aportes por bloques (, morfotipos…` (§3.6), ambos sin `Estados PAC`. También apareció `heartbeat interval dimensiones` dentro del título en inglés de de Chazal (2004) y `dimensión matrix` en el glosario, ambos residuos de un reemplazo global `features → dimensiones`. **Moraleja: después de cualquier reemplazo global, correr la auditoría.**

### Tono de potencialidad (v146)

El bloque 13 marcaba 5 verbos taxativos. Tres son legítimos y se dejaron: `la prueba que importa` (sustantivo), `Garantiza idempotencia` y `confirman que la app reproduce el pipeline` (propiedades técnicas verificables, no afirmaciones sobre resultados). **Dos eran violaciones reales y se corrigieron en v146**:

- §6.5 · `La baja entropía de M en CHA confirma el patrón` → `es consistente con ese patrón`
- §6.3 · `(r = 0,056) confirma que el acoplamiento a escala M es un fenómeno distinto` → `sugiere que … sería un fenómeno distinto`

El control queda como advertencia permanente: no hace fallar la auditoría porque los usos legítimos requieren criterio.

### Lo que queda abierto

1. **Reconocimientos está vacío** — el texto lo tiene el autor; se incorpora recién en la versión de entrega.
2. **Actualizar campos en Word antes de exportar el PDF** (⌘A + F9). ⚠ **Corregido Ago 2026 (§41): Word NO lo propone al abrir** — `updateFields` ya no está en `settings.xml` y el campo TOC fue desvinculado (detalle en §24). El F9 hay que acordarse de hacerlo, y actualiza **números de página**, no el texto de las entradas: los tres índices son hoy texto estático con `PAGEREF` vivos. **No exportar el PDF desde LibreOffice.** ⚠ **Corregido Ago 2026 (§42):** llegué a escribir acá que un PDF de LibreOffice servía igual para el barrido visual porque «la paginación coincide». **Es falso**: la v161 daba 180 páginas en LibreOffice y la v175 da 164 en Word, y la diferencia no se explica solo por el contenido. Las métricas de fuente y el guionado difieren, así que **el barrido visual hay que hacerlo sobre el PDF de Word**, que además es el que se entrega.
3. **`y_Hmin`** desalineado en `window_risk_predictions.parquet` (viene de §24; hygiene de Gold, no afecta la tesis).

### ⚠ Nota operativa sobre `tesis_cap/`

Escribir un `.docx` en esa carpeta desde una sesión de Cowork **puede quedar desincronizado**: pasó dos veces en esta sesión (el archivo leído no era el escrito). Después de copiar, **verificar md5 de origen y destino** y, si difieren, volver a copiar. Un `.docx` corrupto o viejo se detecta corriendo la auditoría sobre el archivo **de destino**, no sobre el de trabajo.

---

## 27. Sesión de cierre APA + índices (Julio 2026) — v146 → v147

> Complementa §26; no toca ningún número ni ningún criterio ya fijado.

### Consolidado vigente: `tesis_cap/Tesis_PAC_v147.docx`

Script reproducible: `scripts/tesis_qa/fix_v147.py` (idempotente; se puede re-correr sin efecto).

Cuatro correcciones que la auditoría **no detectaba** (v146 ya pasaba los 33 controles):

1. **APA 7 · mayúscula tras dos puntos en el título — 22 entradas.** APA exige mayúscula en la primera palabra después de dos puntos, también en títulos en español (`Heart rate variability: A review`, `Intraclass correlations: Uses…`, `Claude: Un asistente…`).
2. **APA 7 · descriptor entre corchetes en software y modelos — 3 entradas.** `Collaborative data science [Software]`, `Streamlit: The fastest way… [Software]`, `Claude: Un asistente de IA por Anthropic [Modelo de lenguaje grande]`.
3. **`(Anexo Suplementario)` unificado en los índices — 8 entradas.** Coexistían `. (Anexo Suplementario)` (17), `.(Anexo Suplementario)` sin espacio (7) y `(mediana ± IQR)(Anexo Suplementario).` (1). Forma canónica única: **`<título>. (Anexo Suplementario)`** — 25/25.
4. **Tabla 1.3**: el párrafo de prosa estaba entre el título y la tabla. La prosa pasó por encima del título (APA: el título va inmediatamente sobre la tabla).

### ⚠ Los índices de figuras y tablas NO son campos TOC

A diferencia del índice general, el **Índice de figuras** y el **Índice de tablas** son párrafos escritos a mano con un campo `PAGEREF` al final. F9 les actualiza **solo el número de página**: el texto es permanente y no se regenera desde los pies de figura. Consecuencias:

- Editar un pie de figura **no** actualiza su entrada en el índice. Hay que tocar los dos.
- El marcador `(Anexo Suplementario)` vive **solo** en el índice; los pies de figura del anexo no lo llevan.
- `p.runs` de python-docx **no ve** ese texto: vive dentro de un `w:hyperlink` y `runs` solo devuelve los `w:r` hijos directos. Usar `ParrafoProfundo` de `fix_v147.py` (itera `.//w:r`) para editarlo.

### Carátula

Se verificó: **no queda ningún "Tutor"** en el documento (§26 ya lo había corregido en v143); la carátula dice `Director: Prof. Rodrigo Del Rosso`. Búsqueda web confirmada: **la Universidad Austral no publica plantilla de carátula**; el único documento normativo accesible es el Reglamento General de Maestrías y Especializaciones, que regula el modo de citar pero no la portada. **Confirmar por secretaría académica antes de imprimir.**

### Lo que sigue abierto (heredado de §26)

1. **Reconocimientos vacío** — lo incorpora el autor en la versión de entrega.
2. **⌘A + F9 en Word antes de exportar el PDF**; no exportar desde LibreOffice.
3. **`y_Hmin`** desalineado en `window_risk_predictions.parquet` (hygiene de Gold).
4. **Densidad de tablas** (criterio, no error): T7.1 tiene celdas de 271 caracteres, la 10.1 de 260 y la 1.3 son 30 × 5. La estructura APA es correcta; la densidad quedó a criterio del autor.

---

## 28. Sesión de sincronización de índices (Julio 2026) — v147 → v148

### Consolidado vigente: `tesis_cap/Tesis_PAC_v148.docx`

Script: `scripts/tesis_qa/fix_v148.py` (idempotente). Entrada: la v147 **con las ediciones manuales del autor** en Word (título de la Tabla 10.2 y carátula).

### ⚠ Los índices eran un punto ciego de la auditoría

`auditar_tesis.py` recorría el cuerpo pero no los índices de figuras y tablas. Como esos índices son **texto escrito a mano** (§27), tres reemplazos globales viejos habían sobrevivido ahí:

| Entrada | Decía | Criterio violado |
|---|---|---|
| Tabla 4.7 | `cohortes full (12 p.) y strict (8 p.)` | §26: nunca `full` / `strict` |
| Figura 7.10 | `perfil de dimensiones nocturnas` | §26: `variables`, no `dimensiones` |
| Figura 8.2 | `Importancia de dimensiones LightGBM` | §26: idem |

Más: Tabla 10.2 desincronizada del cuerpo, Tabla 8.3 con espacios normales donde el cuerpo tiene duros, Figura 6.13 sin punto final, y el pie de la Tabla 4.1 en el cuerpo sin punto final. **7 correcciones.**

`fix_v148.py` deja un comparador índice↔cuerpo reutilizable (`mapa_pies` + `informe_divergencias`). Las **25 divergencias restantes son abreviaciones deliberadas**: el pie del cuerpo agrega N, cohorte o panel que el índice omite. No tocarlas sin decisión editorial.

### ⚠ Word poda los bordes `val="none"` al guardar

Al abrir y guardar la v147 en Word, las 32 tablas perdieron los elementos `left/right/insideH/insideV` con `val="none"` de su `tblBorders`. Word los considera redundantes. **Visualmente no cambia nada** (las tablas no tienen `tblStyle` y el estilo `Tablanormal` no define bordes), pero la auditoría los exigía explícitos y marcaba las 32 tablas como defectuosas.

Se corrigieron las dos puntas:

- **`auditar_tesis.py`**: el bloque 3 ahora marca solo el borde **presente con un valor distinto de `none`/`nil`**; un borde ausente sin `tblStyle` con bordes es correcto. Se agregó `_estilo_con_bordes()` para el caso de herencia. Verificado con inyección: sigue detectando tablas con líneas reales.
- **`fix_v148.py`**: repone los 128 bordes `none` explícitos, para que el .docx no dependa del estilo por defecto del renderizador.

**Moraleja: después de cada guardado en Word, correr la auditoría.** Word normaliza el XML y puede disparar falsos positivos.

---

## 29. Sesión Tabla 4.4 (Julio 2026) — v148 → v149

### Consolidado vigente: `tesis_cap/Tesis_PAC_v149.docx`

Script: `scripts/tesis_qa/fix_v149.py` (acepta rutas por argv: `fix_v149.py <origen> <destino>`).

1. **Tabla 4.4 · encabezados partidos a mitad de palabra.** Las columnas 1 y 3 medían 1209 y 1800 twips, unos puntos menos que sus propios encabezados a 12 pt: Word renderizaba **`Morfotip/o`** e **`Interpretació/n`**. Anchos `[1209, 1299, 1800, 4692]` → **`[1450, 1299, 2150, 4101]`** (suma 9000 constante; el sobrante sale de `Observación`, que tenía holgura). `fijar_anchos()` reescribe `tblGrid` **y** el `tcW` de cada celda: tocar solo el grid no alcanza.
2. **Índice de Tablas · entrada de la Tabla 1.1 en 10 pt** (`sz=20`) mientras el resto del índice va en 12 pt. Eliminadas las 16 propiedades `sz`/`szCs`.

### ⚠ Verificar los anchos de columna contra el texto del encabezado

Es un defecto que **ninguno de los 33 controles detecta** y que no se ve en el XML: hay que renderizar. Receta:

```bash
soffice --headless --convert-to pdf tesis_cap/Tesis_PAC_vNNN.docx
pdftoppm -f <pagina> -l <pagina> -r 110 -png tesis.pdf salida   # y mirar el PNG
```

Regla de bolsillo a 12 pt: **~1 twip por cada 0,0072 caracteres**; un encabezado de N caracteres necesita ≈ `N × 145` twips. `Morfotipo` (9) ≈ 1300; `Interpretación` (14) ≈ 2030. Candidatas a revisar: cualquier columna cuyo ancho quede por debajo de eso.

### ⚠ El `.docx` de `tesis_cap/` se vació a 0 bytes

Confirmación dura de la advertencia de §26: durante esta sesión `tesis_cap/Tesis_PAC_v148.docx` **y su copia en uploads** (están enlazadas duro, `nlink=2`) quedaron en **0 bytes**. El trabajo se salvó porque existía una copia intermedia en `/tmp`. Procedimiento obligatorio:

1. Trabajar sobre una copia en `/tmp`, nunca in situ.
2. Copiar al final a `tesis_cap/`.
3. **`md5sum` de origen y destino** — y correr la auditoría **sobre el archivo de destino**.

Si el destino da 0 bytes o md5 distinto, volver a copiar antes de seguir.

---

## 30. Sesión código de campo aplanado (Julio 2026) — v149 → v151

### Consolidado vigente: `tesis_cap/Tesis_PAC_v151.docx` · **34 controles**

Scripts: `fix_v150.py` (limpieza) y `fix_v151.py` (reconstrucción del campo). Ambos aceptan rutas por argv.

### El defecto: `HYPERLINK \l "ancla"` visible como texto

Tres párrafos tenían el **código de campo aplanado dentro de un `w:t`**, en vez de vivir como `instrText` dentro de un campo. Se leía literal en el documento:

| Ubicación | Decía |
|---|---|
| ¶67 · índice general | `4.4  Síntesis de variables nocturnasHYPERLINK \l "_Toc232926391"` |
| ¶333 · **cuerpo**, sección 4.2.1 | `...de los cinco fenotiposHYPERLINK \l "bk232926385"` |
| ¶926 · **cuerpo**, Anexo C | `Cap. 7  App Clínica Interactiva (HYPERLINK \l "bkCap07"PAC App)` |

⚠ **Los dos del cuerpo eran los importantes.** El índice general sí es un campo TOC y F9 lo regenera — pero lo regenera **desde los encabezados del cuerpo**. Corregir solo el índice habría hecho que el próximo F9 volviera a copiar la basura.

### Además, la entrada 4.4 había perdido el campo HYPERLINK entero

No alcanzaba con sacar el texto: la entrada quedaba en negro y sin enlace mientras el resto del índice va en azul. `fix_v151.py` lo reconstruye con la estructura de una entrada sana:

```
fldChar begin | instrText HYPERLINK \l "ancla" | fldChar separate
run del título (rStyle Hipervnculo)
tab | campo PAGEREF | fldChar end        <- cierra el HYPERLINK
```

⚠ **`addprevious` inserta siempre pegado al nodo de referencia**, así que hay que recorrer los tres runs de apertura en **orden natural** (begin, instrText, separate): el último insertado queda más cerca del título. Invertir el orden produce `separate, instrText, begin`, y entonces LibreOffice y Word muestran el código en lugar del título — se ve peor que el defecto original.

### Control nuevo (bloque 1) — la auditoría pasa a 34

```
[OK ] código de campo visible como texto                     0
```

`_codigos_visibles()` recorre los **`w:t`**, no `p.text`: `instrText` dentro de un campo es legítimo y no debe marcarse. Verificado: da 3 sobre la v149 y 0 sobre la v151.

⚠ **Ninguna entrada del índice usa `w:hyperlink`**; todas usan el HYPERLINK como *campo*. No confundir con los índices de figuras y tablas de §27, donde el texto sí vive dentro de un `w:hyperlink`.

---

## 31. Sesión anchos de columna (Julio 2026) — v151 → v153

### Consolidado vigente: `tesis_cap/Tesis_PAC_v153.docx`

Scripts: `fix_v152.py` (Tablas 6.4 y 6.7, a mano) y **`fix_v153.py`** (repartidor genérico) + `anchos_caracter.json`.

### Diez encabezados partidos a mitad de palabra, no uno

La Tabla 4.4 de §29 no era un caso aislado. Renderizando aparecieron **10**: `Sensibilid/ad`, `Especificid/ad`, `Interpretaci/ón`, `Transicion/es`, `Precisio/n`, `Prevalenc/ia`, `Componen/te`, `Entropí/a`, `Ventan/a`, `Umbr/al`, en las Tablas 4.5, 4.6, 5.1, 6.2, 6.3, 6.4, 6.6, 6.7, 6.8 y 8.5.

En la **Tabla 6.4** (7 columnas) ningún reparto alcanzaba: las glosas del encabezado (`(severo)`, `(antesala)`) pasaron a la nota — encabezado corto, aclaración debajo, que es lo que pide APA.

### ⚠ Contar caracteres NO sirve para estimar el ancho

La regla `N × 145` de §29 es demasiado tosca: las letras tienen anchos muy distintos. `Sensibilidad` (12 caracteres) entra en 1560 twips y `Umbral` (6) se parte en 992. Con esa regla se corrigen unas y se rompen otras — me pasó: al achicar columnas para dar lugar, rompí `Umbral` y `Ventanas`, que antes andaban.

**Solución: medir, no estimar.** `anchos_caracter.json` tiene el ancho por carácter derivado por mínimos cuadrados sobre las 7.405 palabras del PDF renderizado a 12 pt (altura de caja 14,0). Error medio **28 twips**, p95 107. Se regenera así:

```bash
soffice --headless --convert-to pdf tesis_cap/Tesis_PAC_vNNN.docx
pdftotext -bbox tesis.pdf bb.html     # <word xMin=… xMax=…>texto</word>
```

Ancho requerido de columna = ancho del fragmento más ancho **+ 216 twips** (margen de celda de Word, 108 + 108).

### Dos reglas del repartidor

1. **Solo ensancha.** Una columna que hoy anda no se toca; lo que falta sale de las columnas con holgura, a prorrata. Achicar es como se rompen las que funcionaban.
2. **El mínimo mira encabezado y datos.** Solo el encabezado no alcanza: al apretar la columna PPV de la Tabla 8.5, `20,3 %` se partió del `%`. `trozos()` corta por espacio normal, guion y barra — donde Word envuelve sin que se note — pero **no** por espacio duro ni angosto.

Queda **una sola tabla sin lugar: la 1.3** (trazabilidad, 30 × 5). Pide 12.129 twips y hay 9.000, por los nombres de archivo `*.parquet` que no pueden partir. Renderiza aceptablemente porque envuelve por la coma; entra en la discusión de densidad, no en la de defectos.

### Detectar cortes: comparar tokens, no líneas

En `pdftotext -layout` los fragmentos de un encabezado partido quedan separados por las **otras columnas**, no por un salto de línea: buscar `prefijo\nsufijo` da 0 falsos negativos aparentes y es inútil. Lo que funciona es tomar cada palabra de encabezado y ver si `prefijo` y `sufijo` aparecen ambos como tokens sueltos. Genera falsos positivos con palabra + `s` (y `s` es token: es la unidad de `30 s`), así que conviene filtrar los sufijos de una o dos letras y revisar el resto a mano.

---

## 32. Sesión ortografía (Julio 2026) — v153 → v154

### Consolidado vigente: `tesis_cap/Tesis_PAC_v154.docx`

Primera pasada de ortografía del proyecto: **no había ningún control de esto en los 34**.

### ⚠ El diccionario importa más que la herramienta

`pyspellchecker` con `language='es'` marcaba **1.852 de 3.599 palabras únicas** — incluidas `aborda`, `abre`, `acompaña`, `acota`. Su diccionario español es inservible.

Lo que funciona, sin necesidad de root (no hay `apt` en el sandbox):

```bash
npm install dictionary-es          # hunspell es: index.aff + index.dic (57.345 entradas)
pip install spylls --break-system-packages   # hunspell puro en Python
```

Con ese diccionario: 468 candidatas sobre 3.599. Filtrado que deja el ruido en nada:

1. **Excluir la bibliografía** (los apellidos son ruido puro): del párrafo `Referencias` hasta `ANEXO B`.
2. **Descartar lo que también valida el diccionario inglés** (`/usr/share/hunspell/en_US`): son los tecnicismos en inglés.
3. **Descartar las capitalizadas**: nombres propios y siglas.
4. **Ordenar por frecuencia y leer la cola.** Las frecuentes son jerga legítima (`morfotipos` 73, `hipóxica` 63); **los typos viven en las 87 de frecuencia 1**.

### Lo encontrado

- **`latella`** → `lead time`. Residuo de un reemplazo global, en §6.10: *"La predicción en tiempo real con latella explícito…"*. Corregido en v154, en redonda (§26: cursiva solo la primera vez, que está más arriba).
- **`arquitecturadas`** → `con mejor arquitectura`. No existe en español. §5.4: *"las noches mejor arquitecturadas (con mayor proporción de L3)"* → *"las noches con mejor arquitectura…"*, que conserva el sentido de la escala L (el capítulo la llama "arquitectura global"). Aplicado en **v155**.
- **`evaluatorio`** → `preparatorio`. §3.4 llamaba al PCA *"paso evaluatorio previo al K-means"*, pero el PCA prepara, no evalúa. Aplicado en **v155**.

**Consolidado tras la pasada de ortografía: `tesis_cap/Tesis_PAC_v155.docx`** (`fix_v155.py`).

El resto de las 87 son tecnicismos correctos (`autotransición`, `colapsabilidad`, `endotipos`, `fotopletismografía`, `euclídeas`, `reclustear`).

⚠ **La bibliografía quedó sin revisar** a propósito: hay que mirarla aparte, ignorando apellidos y revisando solo las palabras de los títulos.

---

## 33. Barrido visual (Julio 2026) — v155 → v156

### Consolidado vigente: `tesis_cap/Tesis_PAC_v156.docx` · 174 páginas

Script: `fix_v156.py`. Tres defectos que **ningún control detectaba**, porque solo se ven paginando.

1. **La línea de lugar y fecha de la carátula caía sola en la página 2**, con encabezado, pie y número. Es lo primero que ve el jurado. Se recuperó espacio achicando dos espaciados posteriores (`Tesis de Maestría` 600 → 360, `Director:` 480 → 300), sin borrar párrafos ni cambiar el diseño.
2. **Tres pies de figura separados de su figura** (6.5, 6.11 y 7.2): el pie al final de una página y la imagen en la siguiente. Se marcó `w:keepNext` en **los 40 pies del cuerpo**, no solo en los tres, para que no vuelva a pasar.
3. **Página en blanco entre el Abstract y Reconocimientos**: un párrafo vacío con salto de página se comía una hoja entera. Eliminado; el salto pasó a `pageBreakBefore` del propio título.

### ⚠ El documento está en Letter, no en A4

`sectPr` = **12240 × 15840 twips (216 × 279 mm)**, o sea Letter, mientras el §2 de este archivo especifica A4 (11906 × 16838). **Decisión del autor (Jul 2026): se deja en Letter.** Si alguna vez se cambia, reflota todo el documento: cambian saltos y números de página, hay que rehacer ⌘A + F9 y repetir este barrido.

Márgenes actuales: izq 2268 (4 cm), der 1134 (2 cm), sup 1554, inf 1387. El §2 menciona 1800 para el izquierdo; el valor real es 2268, más holgado para encuadernación.

### Chequeos del barrido, reutilizables

```bash
soffice --headless --convert-to pdf tesis_cap/Tesis_PAC_vNNN.docx
pdfinfo tesis.pdf                      # tamaño de página y cantidad
pdfimages -list tesis.pdf              # en qué página está cada imagen
```

- **Páginas en blanco**: contar líneas no vacías por página y descontar 3 (encabezado y pie). ≤ 1 es blanco.
- **Pie separado de su figura**: cruzar la página de cada pie contra las páginas con imagen (`pdfimages -list`). ⚠ Hay que **saltear las páginas de los índices** (1–16), o se toman las entradas del índice en lugar de los pies del cuerpo: da 42/42 falsos positivos.

### Lo que queda

- **Reconocimientos sigue vacío** (pág. 5) — lo completa el autor.
- **La bibliografía no pasó por el corrector** (§32): revisar solo las palabras de los títulos, ignorando apellidos.

---

## 34. Tablas cortadas entre páginas (Julio 2026) — v156 → v157

### Consolidado vigente: `tesis_cap/Tesis_PAC_v157.docx` · 175 páginas

Script: `fix_v157.py`. Cierra el **punto 5 del director**: *"revisaría las tablas largas que se parten entre páginas"*.

### Diagnóstico

**10 de 32 tablas se partían**, y en cinco el título quedaba solo al pie de una página con todas las filas en la siguiente (5.1, 6.1, 6.3, 6.4, 7.1). Lo que ya estaba bien y no era el problema: las filas tenían `cantSplit` (ninguna se parte por la mitad) y el encabezado se repetía en la continuación.

Faltaban dos cosas:

1. **`keepNext` en el párrafo de título** de las 32 tablas → el título nunca queda huérfano.
2. **`keepNext` en todas las filas menos la última**, para las tablas de hasta 10 filas de datos → la tabla entera viaja junta a la página siguiente si no entra.

Resultado: **de 10 tablas cortadas a 2**, al costo de una página (174 → 175).

Las 2 que siguen partidas son las que no entran en una página y está bien que se partan:

- **Tabla 10.1** (6 filas, celdas de 260 caracteres) — tiene `keepNext` pero Word la parte igual porque no entra. `keepNext` es una preferencia, no una orden: por eso es seguro aplicarlo.
- **Tabla 1.2** (17 filas) — se dejó partir a propósito, junto con la 1.1 (20) y la 1.3 (29). Para ellas alcanza con el encabezado repetido.

⚠ La última fila **no** lleva `keepNext`: si no, arrastra el párrafo siguiente y la nota se pega a la tabla en la página que no corresponde.

### Detectar tablas cortadas sobre el PDF

Dos trampas, las dos me costaron una corrida:

- **Saltear las páginas de índice**, que se reconocen por tener ≥ 3 líneas con puntos guía (`\.{6,}\s*\d+$`). Si no, el título de la tabla se encuentra primero en el Índice de Tablas y todo el análisis sale mal.
- **No buscar el texto de la primera celda**: las celdas envuelven y `'L (30 min)'` renderiza como `L        (30 30 min`, así que el match falla y da falsos "título huérfano". Buscar el **token más largo (≥ 6 caracteres) de la última fila**, que sobrevive al envoltorio.

---

## 35. Arbitraje externo y sensibilidad del ARI (Julio 2026) — v158 → v159

### Consolidado vigente: `tesis_cap/Tesis_PAC_v159.docx` · 177 páginas

Script: `fix_v159.py`. Surge de un arbitraje simulado con criterios de *The Lancet* que un tercero corrió sobre la tesis.

### Del informe externo, qué era señal y qué era ruido

- **Ruido**: el dictamen etiquetó el trabajo como ECA y lo penalizó por no cumplir CONSORT. Premisa falsa — el §3.1 dice *"análisis observacional retrospectivo"*; el diseño cruzado aleatorizado es el del protocolo **fuente** (CLP-275001), no el de la tesis. También el 72/100 contra "estándar internacional > 80": mide distancia a una revista de ensayos clínicos, no calidad de tesis.
- **Ya declarado**: n = 12 / 8 efectivos, sesgo masculino 11/12, sobreajuste a la cohorte (= circularidad PAC), validación externa. Todo en §8.7 y §9.8.
- **Señal**: dos críticas accionables, las dos incorporadas en v159.

### Análisis de sensibilidad del ARI (nueva Tabla 4.9)

Calculado sobre `events.parquet` (85.277 EDOs), recalculando el índice completo para cada ponderación. **Reproduce el ARI canónico**: ρ = 0,0335 (canónico 0,035) y C5 = 0,422 ± 0,105 (canónico 0,423 ± 0,104), con los cinco N exactos.

| Pesos hr/mov | ρ drop_pct | ARI C5 | ρ canónico | ICC noche |
|---|---|---|---|---|
| 1,0 / 0,0 | −0,14 | 0,26 | 0,82 | 0,56 |
| 0,7 / 0,3 | −0,03 | 0,38 | 0,98 | 0,69 |
| **0,6 / 0,4** | **0,03** | **0,42** | **1,00** | **0,71** |
| 0,5 / 0,5 | 0,11 | 0,46 | 0,97 | 0,70 |
| 0,4 / 0,6 | 0,19 | 0,50 | 0,88 | 0,67 |
| 0,0 / 1,0 | 0,29 | 0,66 | 0,45 | 0,46 |

Tres lecturas:

1. **El gradiente inverso del C5 es robusto** en w_hr ∈ [0,5 · 1,0]; solo se rompe cuando el movimiento pesa más que la señal cardíaca, que es la configuración que el capítulo descarta por confiabilidad del sensor.
2. **Argumento nuevo a favor de 0,6/0,4**: el ICC noche se maximiza ahí (0,71). Es mejor justificación que la cualitativa, porque es medible.
3. ⚠ **La ortogonalidad NO es robusta**: ρ cruza cero alrededor de w_hr ≈ 0,65. El 0,035 es propiedad de la ponderación, no del índice. Se declara en §4.3.1, que es lo que convierte la vulnerabilidad en fortaleza.

⚠ Ojo con `0,034`: está en `SUPERADOS`. Por eso la tabla va a **2 decimales**, que además evita fingir una precisión que el recómputo no comparte con el pipeline.

⚠ `ird_hr_comp` / `ird_mov_comp` del Gold son los componentes **crudos**, no los percentilizados: son el bug de escala de la Tabla 4.5. El ARI hay que recalcularlo con `rankdata/N` sobre `hr_gain` y `mov_gain`.

### Tres bugs de edición, todos del mismo tipo: el XML manda

Clonar un párrafo para reusar su formato es la técnica correcta, pero **hay que limpiar lo que se arrastra**:

1. **`fldChar begin` heredado.** El título de la Tabla 4.5 contiene un campo. Quedarse con "el primer run" copió el `fldChar begin` sin su cierre → campo abierto → **Word y LibreOffice se tragan el título, la tabla y la nota**, aunque estén en el XML. `clonar_parrafo_limpio()` conserva el `rPr` del primer run con texto y descarta runs, hyperlinks, marcadores y `fldSimple`.
2. **`w:jc` agregado al final del `pPr`.** El orden de los hijos de `w:pPr` es fijo en OOXML; agregarlo al final invalida el XML y el contenido desaparece igual que en el caso anterior. Usar `par.alignment = WD_ALIGN_PARAGRAPH.LEFT`, que lo inserta donde corresponde.
3. **Encabezados largos + justificado.** `ρ con el ARI canónico` estirado por la justificación era ilegible. Encabezados cortos (`ρ canónico`) y alineación a la izquierda; el desarrollo va en la nota, como en la Tabla 6.4.

⚠ **LibreOffice puede servir un PDF cacheado**: el tamaño no cambiaba entre corridas y me hizo perseguir un fantasma. Ante la duda, `pkill -f soffice`, perfil nuevo con `-env:UserInstallation` y `--outdir` limpio.

---

## 36. ✅ APLICADO en la v160 — `fix_v160.py`

> **Consolidado vigente: `tesis_cap/Tesis_PAC_v160.docx` · 177 páginas · 34/34.**
> Los cinco cambios A–E se aplicaron en una sola pasada. Se conserva el detalle
> del diagnóstico porque documenta el mecanismo de anclas y la regla de renumeración.
>
> **Resultado verificado**: 9 tablas del Cap. 4 numeradas 4.1–4.9 sin huecos ni
> duplicados, 9 entradas de índice cada una apuntando a su propio `cap_t_4_N`,
> y las tres anclas de la tabla nueva (`cap_t_4_6`, `anx_T4_6`, `ptr_T4_6`) creadas.
>
> ⚠ Al renumerar hubo que pasar la tabla nueva por un **marcador temporal** antes de
> liberar el 4.9: si no, choca con la 4.8 que se convierte en 4.9.

### A · El párrafo de conflictos de interés es redundante

Detectado por el autor. Tres de sus cinco oraciones repiten lo que ya está dos párrafos arriba en el mismo §3.1:

| El párrafo nuevo dice | Ya estaba en |
|---|---|
| "provienen del protocolo CLP-275001, patrocinado por el fabricante" | ¶1: *"bajo el protocolo CLP-275001 v1.2…, patrocinado por el fabricante"* |
| "El autor no participó en el diseño de ese protocolo" | ¶2: *"en cuyo diseño esta investigación no tuvo intervención"* |
| "la fase analítica … es retrospectiva e independiente, sobre registros previamente recolectados y anonimizados" | ¶2, casi textual |

Solo dos oraciones aportan información nueva, y son las que responden la objeción de sesgo de interpretación del arbitraje. **Texto de reemplazo (5 oraciones → 2):**

> **Declaración de conflictos de interés y financiamiento.** El autor no recibió financiamiento del fabricante del SOMNI 6000 ni mantiene con él relación laboral, de consultoría ni de participación accionaria. El fabricante no participó en el diseño del análisis, en la interpretación de los resultados ni en la redacción de esta tesis, y no ejerció derecho de revisión previa sobre su contenido.

### B · La tabla nueva debe ser la 4.6, no la 4.9

Las tablas se numeran por **orden de primera mención en el texto**, y la nueva se menciona en §4.3.1 inmediatamente después de la 4.5:

| Mención | §4.1 | §4.2.1 | §4.2.2 | §4.2.3 | §4.3.1 | **§4.3.1** | §4.3.2 | §4.5 | §4.5 |
|---|---|---|---|---|---|---|---|---|---|
| Hoy | 4.1 | 4.2 | 4.3 | 4.4 | 4.5 | **4.9** | 4.6 | 4.7 | 4.8 |
| Debe ser | 4.1 | 4.2 | 4.3 | 4.4 | 4.5 | **4.6** | 4.7 | 4.8 | 4.9 |

**Alcance medido de la cascada** (4.6 → 4.7 → 4.8 → 4.9): 3 menciones de "Tabla 4.6", 4 de "Tabla 4.7" y 4 de "Tabla 4.8" en el cuerpo, más los 3 títulos, las 3 entradas del Índice de Tablas y los marcadores `cap_t_4_6/7/8`.

⚠ **Renumerar de mayor a menor** (4.8→4.9 primero, después 4.7→4.8, después 4.6→4.7) o los reemplazos se pisan entre sí.

### C · Falta el párrafo "▸ Tabla complementaria"

La convención del documento es **doble**: mención en línea dentro del párrafo **y** un párrafo aparte. Existen para las Tablas 1.1, 1.2, 1.3, 4.3 y 4.5; la nueva solo tiene la mención en línea. Falta agregar en §4.3.1:

> ▸ Tabla complementaria en el Anexo Suplementario: Tabla 4.6 (análisis de sensibilidad de los pesos del ARI).

### D · Falta el andamiaje de enlaces bidireccionales

⚠ Cada tabla del anexo usa **tres anclas**, no una:

| Ancla | Dónde vive | Para qué |
|---|---|---|
| `cap_t_4_5` | título de la tabla en el anexo | destino de la entrada del Índice de Tablas |
| `ptr_T4_5` | marcador en el párrafo "▸" del cuerpo | destino del enlace **de vuelta** (anexo → cuerpo) |
| `anx_T4_5` | marcador en el anexo | destino del enlace **de ida** (cuerpo → anexo) |

El párrafo "▸" lleva un `w:hyperlink anchor="anx_T4_5"`; el título en el anexo lleva un **campo** `HYPERLINK \l "ptr_T4_5"`. La tabla nueva no tiene ninguna de las tres anclas.

### E · Bug: la entrada del índice apunta a la tabla equivocada

Al clonar la entrada de la Tabla 4.5 en el Índice de Tablas solo se cambió el texto visible: el `w:hyperlink anchor` y el `PAGEREF` siguen apuntando a **`cap_t_4_5`**. Hoy, hacer clic en la entrada de la tabla nueva lleva a la Tabla 4.5 y muestra su número de página.

**Al aplicar B, C, D y E hay que rehacer los tres índices en Word (⌘A + F9)** y volver a correr la auditoría sobre el archivo guardado.

---

---

## 37. Márgenes APA y bloque 14 de la auditoría (Julio 2026) — v160 → v161

### Consolidado vigente: `tesis_cap/Tesis_PAC_v161.docx` · 180 páginas · **39 controles**

Script: `fix_v161.py`. Decisiones del autor en esta ronda: carátula y Tabla 1.3 quedan como están, la Tabla 4.6 está aprobada, la higiene del Gold no se toca.

### Márgenes

APA 7 pide 1 pulgada (1440 twips) en los cuatro lados; la excepción habitual es el izquierdo, que muchas universidades piden en 1,5" para encuadernación.

| | v160 | v161 |
|---|---|---|
| izq | 2268 (1,57") | **2268** — encuadernación, se respeta |
| der | 1134 (0,79") ✗ | **1440** (1") |
| sup | 1554 (1,08") | **1554** — ya cumplía |
| inf | 1387 (0,96") ✗ | **1440** (1") |

Ancho de texto: 8838 → **8532 twips**. El documento pasa de 177 a 180 páginas.

### ⚠ 24 tablas ya se salían del bloque de texto, y nadie lo había visto

Medían **9000 twips con un ancho de texto de 8838**: se desbordaban 3 mm desde antes de esta sesión. Al angostar la caja el desborde habría sido visible, así que las 33 tablas se reescalaron proporcionalmente a 8532 y después se revisó que ningún encabezado quedara más angosto que su palabra más larga (§31).

Dos efectos colaterales del ancho nuevo:

- **Tabla 8.5** volvía a partir `Sensibilidad` y `Especificidad`. Se abreviaron los encabezados a `Umbral`, `Sens.` y `Espec.`, que la propia nota ya desarrolla (*"Umbral de Youden: maximiza Sensibilidad + Especificidad − 1"*).
- **`9,6 %` se partía del `%`** en la columna PPV. Se ataron con espacio duro las 114 celdas con `<número> <unidad>` de todo el documento. ⚠ El primer intento falló por un `\b` después de `%`: **`%` no es carácter de palabra, así que ese límite nunca matchea**.

La única tabla que sigue sin entrar es la **1.3** (trazabilidad, 29 filas), que el autor decidió dejar así.

### Bloque 14 · Formato de página — la auditoría pasa de 34 a 39 controles

```
14. Formato de página
  [OK ] márgenes por debajo del mínimo (texto 8532 tw)         0
  [OK ] tablas más anchas que el texto (de 33)                 0
  [OK ] párrafos fuera del interlineado del documento          0
  [OK ] párrafos con sangría de primera línea                  0
  [OK ] secciones sin folio en el pie (de 1)                   0
```

⚠ **Estos controles no verifican APA estricto: verifican el criterio del proyecto.** La tesis se aparta de APA en tres puntos, de forma deliberada, porque son convenciones de tesis encuadernada y no de manuscrito para revista:

| APA 7 | Este documento |
|---|---|
| sangría de primera línea de 0,5" | sin sangría; separación por espaciado |
| folio arriba a la derecha | folio al pie, con el crédito del autor |
| interlineado doble | 1,5 en el cuerpo · 1,0 en el aparato (notas y punteros "▸") |

Lo único que se controla contra APA es el mínimo de márgenes, que es el que un jurado puede medir con una regla. Los otros tres controlan **consistencia interna**: que no haya párrafos sueltos con otro interlineado, ni sangrías intrusas, ni secciones sin folio. El control de ancho de tabla es nuevo y salió de esta sesión.

---

## 38. Puntos 7 y 2 del director (Julio 2026) — v161 → v162

### Consolidado vigente: `tesis_cap/Tesis_PAC_v162.docx` · 39/39

Script: `fix_v162.py`. Cierra los dos únicos puntos del director que seguían abiertos.

### ⚠ El ancho de tabla necesita TRES cosas, no dos

`fix_v161` fijó `tblGrid` y el `tcW` de cada celda, pero dejó el **`tblW`** (ancho preferido de la tabla) en 9000. Al abrir y guardar en Word, **Word le hace caso a `tblW` y reexpande la grilla**: 24 tablas volvieron a 9000 sin que nadie tocara una tabla.

El síntoma es inconfundible: la auditoría marca "tablas más anchas que el texto" después de un guardado que no tocó tablas. `reescalar_tablas()` en `fix_v162.py` corrige las tres.

### Punto 7 · terminología — 4 correcciones

- **`RS` suelto ×3 en §6.9.** Verificado: la abreviatura **no se introduce en ningún lado** del documento, así que además de violar el §26 quedaba opaca. → `Risk Score PAC`. La cuarta aparición, en el glosario, define la fórmula (`RS = 0,40 × …`) y se deja.
- **`dentro de un Estado PAC patológico`** → minúscula: es una instancia concreta, no el sistema.

Las otras 10 apariciones de `Estado PAC` en singular refieren al sistema (`etiquetas de Estado PAC`, `asignación de Estado PAC`) y quedan en mayúscula. `features` y `strict`, que el control de terminología no marca, aparecen una vez cada uno y **son legítimos**: viven dentro del título en inglés de de Chazal (2004) y del Abstract.

### Punto 2 · APA en referencias — cerrado

De los cinco ítems del director, cuatro ya estaban: sangría francesa (59/59), cursiva en revista y volumen, cero `et al.` en la lista, y mayúscula tras dos puntos (§27, 22 entradas).

- **DOI uniformes**: 51 de 59 usan `https://doi.org/`, sin puntos finales ni espacios. Siete no tienen DOI **con razón** (libros, actas de congreso, software). La única inconsistencia real era **Terrill (2020)**, un artículo de revista citado con URL de PubMed y sin volumen ni páginas. Corregido a `Respirology, 25(5), 475–485. https://doi.org/10.1111/resp.13635`.
  ⚠ La cursiva cubre revista **y volumen**, pero no el número entre paréntesis ni las páginas: `*Respirology, 25*(5), 475–485`.
- **Ortografía de los títulos**: corrida con el diccionario hunspell. **Cero typos.** Las 30 palabras que marca son grafías británicas (`apnoea`, `analysing`, `hypopnoea`), tecnicismos (`oximetry`, `polysomnography`, `chemoreflex`, `intraclass`) y fragmentos de DOI (`jcsm`, `zsaf`, `eurheartj`). No tocar.

### Estado de los 10 puntos del director

| # | Punto | Estado |
|---|---|---|
| 1 | Carátula | esperando secretaría académica |
| 2 | APA en referencias | ✅ cerrado en v162 |
| 3 | Cruce citas ↔ referencias | ✅ 59 · 0 huérfanas · 0 sin entrada |
| 4 | Cursivas | ✅ |
| 5 | Tablas | ✅ 30 de 32 ya no se parten; la 1.3 y la 10.1 no entran por tamaño |
| 6 | Los 5 defectos puntuales | ✅ los cinco dan 0 |
| 7 | Terminología | ✅ cerrado en v162 |
| 8 | Anexo C | ✅ 42 pies · 42 notas · 42 referenciadas |
| 9 | Publicaciones | ✅ |
| 10 | Última lectura de estilo | ✅ primera pasada cerrada en v171–v173 (§41): 46 candidatos relevados, 18 aplicados. Los 28 abiertos son redundancia y tono, ninguno un error |

---

## 39. Cursivas de la edición manual (Julio 2026) — v163 → v165

### Consolidado vigente: `tesis_cap/Tesis_PAC_v165.docx` · 39/39

Scripts: `fix_v164.py` (regresión + concordancia) y `fix_v165.py` (capas del pipeline).

### ⚠ Editar en Word reintroduce cursivas: el texto nuevo hereda el run vecino

La v162 daba 39/39. Tras la edición manual del autor (párrafo de conflictos de interés, "condiciones ecológicas"), la v163 volvió a 38/39 con **11 nombres de archivo en cursiva** — `Medallion` ×1 y `parquet` ×10 — concentrados en los párrafos vecinos a los editados. **Es el patrón esperable: pegar o retipear dentro de un párrafo hereda el formato del run contiguo.** El bloque 4 de la auditoría lo caza solo.

### ⚠ Pasar a redonda un nombre de archivo puede empeorarlo

Al aplicar `split_run_italic` sobre `parquet` en las notas del anexo, el path quedó **partido entre dos tipografías**: `(gold/*.` en cursiva y `parquet` en redonda. Se ve peor que el defecto original, y **la auditoría daba 39/39 en ese estado** — solo se detecta mirando los runs. Hay que tratar el path como unidad, incluido el prefijo.

Mismo cuidado con `Bronze → Silver → Events → Gold`: viaja como un solo run y se procesa como cadena antes que los términos sueltos.

### Criterio ampliado: los nombres de las capas van en redonda

`states.parquet` va **entero en redonda**, extensión incluida: es un identificador literal, no un extranjerismo conceptual. Por la misma lógica, las capas y el identificador de registro son nombres propios de componentes — misma categoría que LightGBM:

| Término | v164 (red/cur) | v165 |
|---|---|---|
| `parquet` | 60 / 0 | 60 / 0 |
| Medallion | 6 / 0 | 6 / 0 |
| Gold | 21 / **6** | 28 / 0 |
| Events | 10 / **5** | 12 / 0 |
| Silver | 10 / **4** | 13 / 0 |
| Bronze | 11 / **3** | 14 / 0 |
| NightRecordID | 4 / **2** | 6 / 0 |

⚠ Verificado que **las cursivas NO eran las primeras menciones** (`Bronze` aparecía dos veces en redonda antes de su primera cursiva): era residuo concentrado en §3.3, no un criterio alternativo. Siguen en cursiva, como corresponde, `ad hoc`, `baseline` y `lead time`.

### También en la v164

`cuya escala y representatividad no es reproducible` → **`no son reproducibles`** (sujeto compuesto). Lo detectó el autor a partir de la revisión de "condiciones ecológicas"; es el tipo de error que ningún control automático encuentra y que busca el punto 10.

---

## 40. Enlaces de los índices y cursiva del aparato (Agosto 2026) — v166 → v169

### Consolidado vigente: `tesis_cap/Tesis_PAC_v169.docx` · 39/39

Scripts: `fix_v167.py` (7 marcadores) y `fix_v169.py` (3 marcadores). Los dos son quirúrgicos: mueven `w:bookmarkStart`/`w:bookmarkEnd`, que son invisibles, y no tocan una letra del texto.

### ⚠ Un enlace puede "funcionar" y aun así estar mal

El autor revisó **uno por uno** los tres índices haciendo clic. Encontró 9 destinos equivocados que **ningún control detecta y que no se ven en el XML**: el marcador estaba en el párrafo anterior al destino, así que el enlace saltaba —no estaba roto— pero Word dejaba el título fuera de pantalla. Solo se detecta haciendo clic.

| Marcador | caía en | corregido en |
|---|---|---|
| `ptr_4_1` | §4.2.1, justo tras el pie de la Fig. 4.2 | v167 |
| `cap_f_4_2` | antes de §4.2.2 | v167 |
| `cap_f_4_1` · `ptr_refrap` · `anx_trazab` · `cap_t_4_1` · `cap_t_5_2` | 1–4 elementos antes del destino | v167 |
| `cap_t_1_3` · `cap_t_1_2` · `ptr_trazab` | ídem | v169 |

### ⚠ Las TRES anclas se confunden fácil, y me confundí

Cuando el autor dijo *"la Tabla 1.3 va mal de ida"*, corregí `anx_trazab` (ida cuerpo → anexo). La que fallaba era la del **Índice de Tablas**, que usa `cap_t_1_3` — otra ancla. Recordatorio del §36:

| Ancla | Enlace |
|---|---|
| `cap_t_1_3` | Índice de Tablas → tabla |
| `anx_trazab` | cuerpo (▸) → anexo |
| `ptr_trazab` | anexo → cuerpo |

**Al reportar o corregir un enlace hay que decir cuál de los tres.** "Ida" y "vuelta" son ambiguos.

⚠ El título de la Tabla 1.3 en el anexo **no tiene campo HYPERLINK de vuelta** (la 1.2 sí). `ptr_trazab` quedó bien ubicada por si se agrega.

### Cambio de convención: el aparato va en cursiva íntegra

Decisión del autor, aplicada a mano sobre la v168. **Las notas (`Nota.`) y los punteros (`▸`) van en cursiva completa**: la cursiva ahí marca una *categoría de texto*, no un énfasis, así que adentro no se recortan nombres propios ni nombres de archivo.

Estado antes: de 75 notas en cursiva, **26 tenían islas en redonda** (48 fragmentos: `LOPO-CV` ×10, `Youden` ×6, `folds` ×5, `pipeline` ×4, `Gold` ×4, `gold/*.parquet` ×2…). El autor las unificó todas. Queda **1 puntero con isla**: el ▸ de la Tabla 1.3, cuya cola `(capítulo, notebook, tabla Gold y resultado clave)` sigue en redonda.

⚠ **En Word esto es 1 operación por párrafo, no 1 por fragmento**: seleccionar el párrafo entero y aplicar cursiva; con selección mixta Word pone todo en cursiva.

### La auditoría tuvo que adaptarse, o quedaba en rojo permanente

Con la convención nueva, los dos controles de cursivas del bloque 4 marcaban **16 falsos positivos** (`LightGBM`, `LOPO-CV`, `parquet`, `pipeline`, `baseline`…), todos dentro de notas. Eso es peor que el problema original: con la auditoría siempre en rojo se pierde la capacidad de distinguir una regresión real.

Se agregó `es_aparato(p)` en `auditar_tesis.py`: los párrafos que empiezan con `Nota.` o `▸` quedan fuera de esos dos controles.

**Verificado por inyección** —que es como hay que validar un control que se afloja—: sobre la v169 se inyectó `LightGBM` y `clustering` en cursiva **en prosa del cuerpo** y los dos controles volvieron a saltar. La exclusión cubre el aparato, no el cuerpo.

### Verificación visual: renderizar, no leer el XML

Los tres defectos de §29 y §30 tienen algo en común: **el XML se veía sano**. La única forma de detectarlos fue convertir a PDF y mirar la página. Conviene hacerlo al menos sobre la carátula, los tres índices y una página de cada capítulo antes de entregar.

---

## 41. Lectura fina de estilo — punto 10 del director (Agosto 2026) — v170 → v173

### Consolidado vigente: `tesis_cap/Tesis_PAC_v173.docx` · 39/39 · 887 párrafos

Primera pasada del punto 10, el único que seguía diferido. Informe completo en **`tesis_cap/Lectura_Fina_Estilo_v170_candidatos.md`**: 46 candidatos con ubicación, cita literal y tipo de defecto. **18 aplicados a mano en Word; 28 abiertos.** Ningún cambio tocó una cifra.

Cadena: **v171** (13 cambios: los cinco de mayor peso más los cinco gramaticales duros) → **v172** (4: los tres de credibilidad D11/D6/F4 más el `119 eventos` → `119 ventanas` de F3) → **v173** (1: cierre del 14).

**Los 28 que quedan no son errores**: son redundancia y calibración de tono. Todo lo identificado como error de lengua, referencia cruzada equivocada, cruce de métricas o riesgo de credibilidad ante el jurado quedó aplicado.

Método: barrido automático (concordancia, conectores repetidos, verbos taxativos, solapamiento léxico entre párrafos, puntuación) + lectura corrida de Cap. 1–10. **El barrido solo levantó 4 de los 13 aplicados.** Los otros 9 salieron de leer. Es el límite estructural del punto 10: no hay control que lo cubra.

### Lo aplicado

| # | Ubicación | Defecto | Cambio |
|---|---|---|---|
| 1 | §10.2 | enumeración anuncia «tres aspectos» y entrega cuatro | rayas → paréntesis; `publicado; su ortogonalidad` → `publicado, y su ortogonalidad` |
| 2 | §10.2 | `dimensionalmente informativa` | → `dimensión diagnósticamente informativa` |
| 3 | §10.2 | tono sobre un hallazgo de 7 noches | `reposicionando` → `lo que reposicionaría` |
| 4 | §8.8 | eco literal de §8.4 | eliminada la cláusula `lo que es consistente con un organismo que tiene memoria, no con uno que colapsa abruptamente` |
| 5 | §9.2.2 | `implica que … es estadísticamente independiente` | → `sugiere que … variaría con relativa independencia` + remisión al caveat de §4.3.1 |
| 6 | §9.2.2 | `Esta independencia se extiende a los índices de frecuencia nocturna` | → `A nivel de noche la asociación … también resulta débil (Cap. 4 §4.4)` |
| 7 | §9.2.2 | `La coherencia fisiopatológica directa es clara` | → `La lectura fisiopatológica es coherente` |
| 8 | §9.3.2 | remisión a la **Tabla 6.5** (importancia Gini) | → **Tabla 6.4** (fenotipos de trayectoria) |
| 9 | §8.4 | `un AUC que supera cuatro veces el nivel basal de prevalencia` | → `Average Precision`, y desacoplado del óptimo: `A H = 5 min, el horizonte que §8.5 identifica como óptimo, …` |
| 10 | §8.4 | `indica` + pleonasmo + `latencia` | → `sugiere` · `anticipar eventos con varios minutos de margen` · `conserva información fisiológica durante un lapso suficiente` |
| 11 | §6.6 | `se mide la balanced accuracy y el coeficiente κ` | → `se miden` + segundos dos puntos → punto |
| 12 | §8.6 | `se actualizaría … y activaría el estimulador` | → sujetos explícitos, `se activaría`, `supere` → `superara` |
| 13 | Cap. 5 apertura · §8.7 · §10.4 | `cada patrón se lo denomina` · `ventanas prospectas` · `regresión logística isotónica` | → `cada patrón se denomina` · `ventanas del análisis prospectivo` · `regresión isotónica` |
| **v172 · 14** | §6.1 | negación absoluta que §6.7 y §6.10 desmienten literalmente | `pero no anticipan lo que vendrá después` → `sin un horizonte de anticipación fijado de antemano` |
| **v172 · 15** | §9.7 | el Paciente 314 se hedgea en §8.4 y se explica con `porque` en §9.7 | → `Con las reservas señaladas en §8.4, una lectura posible es que … anticiparía mejor … cuanto más contrastara …` |
| **v172 · 16** | §3.5 | resultado central del Cap. 5 adelantado en Materiales y Métodos | cortado tras `cada dimensión de la fisiología nocturna.` |
| **v172 · 17** | §8.8 | `119 eventos positivos` (la unidad del capítulo es la ventana de 30 s) | → `119 ventanas positivas` |

⚠ **El 14 es el que más valía.** §6.1 abría el capítulo afirmando que los modelos «no anticipan lo que vendrá después» y §6.7 decía «el modelo anticipa dentro de la noche» y «predecir la severidad del próximo evento sin verlo es posible». La distinción de fondo era correcta —NB07 predice el evento siguiente *cuando llegue*; NB08 predice si habrá evento *dentro de H minutos*— pero estaba enunciada como negación total. «Sin un horizonte fijado de antemano» pone la frontera donde de verdad está, la misma de la Tabla 8.1.

| **v173 · 18** | §6.1 | `(anticipar eventos con margen temporal)` no contrastaba con el cambio 14 | → `(anticipar eventos con margen temporal **definido**)` |

⚠ **El 18 cierra el 14.** Sin `definido`, la parte derecha del contraste no cargaba el rasgo que la distingue: el mismo párrafo dice que los modelos del Cap. 6 operan «dentro de una ventana causal de unos 5 minutos», o sea que *también* tienen margen temporal. Lo que separa al Cap. 8 no es tener margen sino que el horizonte esté **fijado antes de mirar los datos** (H ∈ {2, 5, 10, 15} min). Se usó `definido` y no un eco literal de `fijado de antemano`, que a doce palabras de distancia sonaba a repetición.

### ⚠ La regla «sin rayas largas» rompió una enumeración

`§16` fijó «sin rayas largas en el cuerpo — reemplazar por paréntesis o punto y coma». Al consolidar se aplanaron a **comas**, no a paréntesis: el documento pasó de 17 rayas (borrador resumido) a 1. En §10.2 eso destruyó la enumeración, porque el punto y coma que vivía **dentro** de la raya del primer ítem quedó al mismo nivel que los separadores de ítems. Resultado: «tres aspectos» seguido de cuatro segmentos, con la ortogonalidad del ARI despegada del ARI y convertida en aspecto propio.

Verificado que el daño es **local**: es la única aposición de ese patrón en todo el documento. Pero la moraleja vale para cualquier regla tipográfica futura — **aplanar un delimitador sin reponer otro cambia la sintaxis, no solo el aspecto.**

### ⚠ Cómo se diagnostica un defecto de compresión: buscar en `Borradores de capitulos/`

Mi primera hipótesis sobre `dimensionalmente informativa` fue que era residuo del reemplazo global `features → dimensiones` de §26. **Era falsa.** La cadena real, reconstruida abriendo los borradores:

- **Extenso** (`Cap10_Conclusiones_v1` a `v4`, ¶31): «reposiciona la variabilidad noche a noche como **dimensión diagnósticamente informativa**»
- **Resumido v3** en adelante: al comprimir tres párrafos en una oración se perdió `diagnósticamente` y `dimensión` quedó convertida en adverbio
- **Consolidado v130 → v171**: arrastrado sin cambios

O sea: `dimensión` estaba **bien** (es el uso canónico del §26, «el ARI como dimensión ortogonal») y lo que faltaba era la otra palabra. Corregirlo por el lado equivocado —sacando `dimensión`— habría empeorado el texto.

**Receta**: ante una frase que no cierra, antes de teorizar, `grep` sobre `tesis_cap/Borradores de capitulos/Cap*_v*.docx`. La versión extensa suele tener la formulación completa.

### ⚠ Referencias cruzadas viejas que la auditoría no cruza

El bloque 9 cruza **figuras** ↔ referencias, pero **no tablas**. Por eso pasó desapercibida la remisión de §9.3.2 a la «Tabla 6.5» para el ARI por fenotipo, cuando esa tabla es la de importancia Gini.

No era un typo: **§22 de este archivo registra la tabla de fenotipos de trayectoria como «Tabla 6.5»** en la numeración de la v38. Se renumeró después y la remisión del Cap. 9 no siguió a la cascada — mismo mecanismo que §36.B.

⚠ **Trampa permanente del Cap. 6: las secciones y las tablas están corridas en uno.** §6.5 contiene la Tabla 6.4; §6.6 contiene la Tabla 6.5. Escribir «(Tabla 6.5)» pensando en «§6.5» es el error natural. Verificadas las otras tres remisiones a esas dos tablas (§6.5 p477, §6.6 p485, §6.10 p522): correctas.

**Candidato a control nuevo**: extender el bloque 9 al cruce tablas ↔ remisiones, comprobando que el contenido citado coincida con el título de la tabla.

### ⚠ Cuando se corrige una cifra, hay que releer la prosa que la rodeaba

§20 corrigió `ρ(ARI, ODI3) = 0,034` (era `drop_pct` mal rotulado; el valor real es −0,066 evento / −0,245 noche). El **número** se arregló en §9.2.2 —el párrafo cita bien `ρ = 0,035 vs. drop_pct`—, pero la oración siguiente quedó con el encuadre viejo: *«Esta independencia se extiende a los índices de frecuencia nocturna»*. Bajo el número corregido eso es falso: §4.4 documenta ρ = −0,245 y lo llama «asociación débil», que no es independencia.

**Un valor superado deja residuo verbal.** `cifras_canonicas.py` atrapa el número; no atrapa la frase que lo interpretaba. Al mover una cifra a `SUPERADOS`, releer el párrafo entero.

### ⚠ Un cruce de métricas se verifica dentro del propio documento

§8.4 decía «un **AUC** que supera cuatro veces el nivel basal de prevalencia». La Tabla 8.4 lo resuelve sin abrir NB08: columna «Mejora AP s/ base» = **4,1×** para H = 5 min (AP 0,326 / prevalencia 0,0804 = 4,05). El «cuatro veces» era exacto pero pertenecía al **AP**. El AUC no se referencia contra la prevalencia: tiene su basal en 0,50.

De paso: el mejor cociente AP es el de **H = 2 min (5,4×)**, no el de H = 5 min, así que la frase además insinuaba que ese 4× justificaba el óptimo. El criterio real está en §8.5 (balance AUC/PPV; H = 2 min se descarta por PPV = 9,6 %). Se desacopló.

### Hallazgo de formato: el espacio magnitud–unidad del §26 no está implementado

| Separador | Cuerpo | Tablas |
|---|---|---|
| U+0020 normal | **141** | 0 |
| U+00A0 duro | 3 | **49** |
| U+202F angosto | 3 | 0 |

§26 fija «espacio angosto (U+202F) entre magnitud y unidad (`30 s`, `5 min`)». En tablas se aplicó el **duro** (los 49 vienen de §37, para que `9,6 %` no se parta del `%`); **en el cuerpo el criterio no existe**. Y la auditoría da 39/39 con esos 141 encima, así que **el control no cubre el cuerpo**.

Tres salidas, ninguna urgente: aplicarlo document-wide, restringir el criterio a tablas y corregir el §26, o dejarlo anotado. El argumento real del espacio duro es que la unidad no se separe del número al final de renglón, y eso ya está resuelto donde importaba.

### Lo que queda abierto

1. **28 candidatos** en `tesis_cap/Lectura_Fina_Estilo_v170_candidatos.md`. Ninguno es un error: son redundancia y calibración de tono. Los de mayor valor:
   - **C · redundancia**: C2 (§9.7, misma definición de la fase de rodaje dos párrafos después), C4 (la escala L «no aporta dimensión propia», 5 veces), C6 (heterogeneidad 20× como «principal barrera», 7 veces, 4 de ellas dentro del Cap. 8), C7 (el PPV 20 % dicho dos veces en el mismo párrafo), C11 (el leitmotiv «dos casos con el mismo ODI3 y distinta fisiología», 8 apariciones; 5 de ellas en tres secciones consecutivas del Cap. 6).
   - **D · tono**: D3 (§9.4 «es real», «la señal de alerta llega»), D9 (§9.9 «la demostración de que»).
   - **F · consistencia**: F1 (tres aposiciones distintas de la sigla PAC), F5 (cinco estilos de párrafo distintos para texto corrido, entre ellos `font-claude-response-body`, importado de una interfaz web).

### Secuencia de entrega (queda esto, en este orden)

1. **Reconocimientos** — escrito, lo incorpora el autor recién en la versión final (decisión suya, Ago 2026).
2. **⌘A + F9 en Word, a mano** — Word no lo propone (§24, §26).
3. **Exportar el PDF desde Word**, nunca desde LibreOffice.
4. **Barrido visual sobre ese PDF** (§33 y §34): carátula, los tres índices y una página por capítulo. ⚠ **Está desactualizado desde la v156**: van dieciséis versiones y diecisiete ediciones manuales en Word desde entonces, y viudas, pies separados de su figura y tablas partidas **no los ve ningún control**.
5. **Carátula**: confirmación de secretaría académica (abierto desde §26; dependencia externa).

### Cerrado, no rehacer

- **Ortografía de la bibliografía**: hecha en §38 (v162), **cero typos** sobre los títulos. El §32 decía «quedó sin revisar» y quedó desactualizado. Lo que **nunca** se hizo es verificar el *contenido* de cada referencia contra la fuente (que el volumen, número y páginas sean los reales); la forma APA y el cruce citas↔referencias sí están cerrados.

---

## 42. Ronda de entrega: Reconocimientos y barrido visual (Agosto 2026) — v173 → v175

### Consolidado final: `tesis_cap/Tesis_PAC_v175.docx` · 164 páginas · 39/39 · **listo para entregar**

La versión de entrega se genera desde la v175 sin sufijo de versión. Cierra la secuencia del §41: Reconocimientos incorporado, carátula aprobada, campos actualizados, barrido visual limpio.

### Resultado del barrido (sobre el PDF de Word, §33 y §34)

| Control | v173 | v175 |
|---|---|---|
| Páginas | 165 | **164** |
| Páginas en blanco | 1 (la 98) | **0** |
| Pies de figura separados de su figura | 0 | 0 |
| Tablas partidas (título y Nota en páginas distintas) | 0 | 0 |
| Índice de figuras y tablas | 69/69 correctas | **69/69** |
| Índice general | sin discrepancias | **sin discrepancias** |

Los `PAGEREF` respondieron al F9: al eliminarse una página, las entradas del Índice de Tablas pasaron de 110/112 a 109/111 solas.

### ⚠ El texto que se agrega al final no pasa por ningún control

Reconocimientos entró recién en la versión de entrega, por decisión del autor, y traía **dos erratas**: `a mi hijos` (concordancia) y `hace nucho tiempo`. Ninguna de las dos la ve la auditoría —no hay corrector ortográfico en los 39 controles— y estaban en la **página 4**, de las primeras que abre un jurado. Solo aparecieron leyendo el PDF.

**Moraleja para cualquier sección que se incorpore al final** (Reconocimientos, dedicatoria, erratas): leerla a mano. Los 39 controles cubren el documento que ya existía, no el texto nuevo.

### ⚠ Dos defectos estructurales que solo se ven paginando

**1 · Página en blanco entre capítulos.** Comparar cómo está armado cada arranque de capítulo revela el patrón:

| | Cap. 2 (sano) | Cap. 9 (roto) |
|---|---|---|
| Párrafo anterior | lleva el `<w:br type="page">` | sin salto |
| Párrafo intermedio | no hay | **uno vacío** |
| `CAPÍTULO N` | sin salto | **lleva el salto** |

El párrafo vacío caía solo al principio de la página y recién entonces `CAPÍTULO 9` disparaba su salto. Se corrige **borrando el párrafo vacío**. Es el mismo defecto que §33 encontró entre Abstract y Reconocimientos: **el patrón a buscar es párrafo vacío + salto en el párrafo siguiente.**

⚠ Antes de diagnosticar, verificar si los capítulos abren en recto: si todos arrancaran en impar, un verso en blanco sería intencional. Acá arrancan indistintamente en par e impar (Cap. 2 → p. 20, Cap. 5 → p. 51, Cap. 6 → p. 60), así que no lo era.

**2 · Al Capítulo 1 le faltaba la etiqueta `CAPÍTULO 1`.** Los capítulos 2 a 10 la tenían; el 1 arrancaba directo en «Introducción». Ningún control cruza las aperturas de capítulo entre sí. La etiqueta es un párrafo `Normal` **sin `pPr` ni `rPr`** —formato heredado puro—, así que replicarla es trivial.

### ⚠ El `.docx` y el `.pdf` pueden separarse

El autor exportó el PDF con Reconocimientos pero subió dos veces un `.docx` **con el mismo md5 que la vuelta anterior**, sin Reconocimientos. El PDF quedó adelante de su propia fuente. Se detectó comparando md5 entre subidas consecutivas y buscando el texto nuevo en los dos artefactos.

**Verificar siempre que el `.docx` contenga lo que el PDF muestra**, no solo que el md5 coincida con `tesis_cap/`.

### ⚠ Cómo NO verificar los índices sobre el PDF

Cuatro «discrepancias» de esta ronda fueron artefactos de parsing, ninguna del documento:

- unir líneas con `re.S` o con un blob hace que el patrón cruce entradas y tome el número de la siguiente;
- las entradas envueltas con paréntesis dan falsos positivos (`escala M (5` → «página 5»);
- buscar la sección por `^N.N` agarra líneas de cuerpo que empiezan con ese número (`6.5 muestra dos noches…`, que viene de «La Fig. 6.5»).

**Método fiable**: anclar en el **título literal** tomado del `.docx` y exigir que la línea del cuerpo empiece con el numeral **y** contenga ese título normalizado. Dos métodos independientes que coincidan en cero es evidencia suficiente; un solo método «mejorado» que dispare 24 marcas es, casi siempre, el método.

### Pendiente heredado, no afecta la tesis

- **`y_Hmin`** desalineado en `window_risk_predictions.parquet` (viene de §24; hygiene de Gold).

### Queda abierto solo por decisión del autor

- **Página 15**: cola del Índice de Tablas con dos entradas sueltas. Cosmético; corregirlo mueve paginación y obliga a otro F9.
- **28 candidatos de estilo** del §41: redundancia y calibración de tono, ninguno un error.

---

## 43. Cinco puntos del director + autenticidad de citas (Agosto 2026) — v175 → v187

> ⚠ Esta sección **prevalece sobre §26 y §40** en materia de cursivas, y sobre §37 en el
> control de ancho de tabla. **Ninguna cifra cambió en toda la serie**: el texto de la v187
> es idéntico al de la v175 salvo la bibliografía y las correcciones puntuales listadas.

### Consolidado vigente: `tesis_cap/Tesis_PAC_v189.docx` · 172 páginas · **39/39**

Cadena: **v176** recuadros + tablas + primeras correcciones APA → **v177** (ediciones
manuales del autor) → **v178** estilo de tabla unificado → **v179** latinismos y
Platt scaling → **v180** autenticidad de citas → **v181–v182** entradas sin DOI →
**v183** `batch` → **v184–v185** Tabla 1.3 apaisada → **v186** comillas → **v187** `ramp-up` →
**v189** Tabla 1.3 compactada a 2 páginas (sobre las abreviaturas manuales del autor,
conservadas en `Tesis_PAC_v187_ediciones_autor.docx`).

### ⚠ El recuadro del Cap. 7 no estaba mal ubicado: estaba mal dimensionado

El director venía reclamando hace tiempo que el recuadro «¿Qué debe recordar el lector?»
del Cap. 7 partía una oración, y el autor no lo veía. **Los dos tenían razón.**

Los cinco recuadros (Cap. 4–8) eran **cuadros de texto flotantes** con `wrapSquare`, y su
`<a:ext>` guardaba el tamaño por defecto de 2 × 2 pulgadas mientras el recuadro visible
mide ~6,2. Word recalcula el autoajuste al abrir y por eso se veía bien; cualquier motor
que respete el valor guardado —otra versión de Word, exportación a PDF, LibreOffice—
ajusta el texto alrededor de una columna de 2 pulgadas y lo mete adentro del recuadro.
Reproducido: el párrafo «La PAC App invierte esa lógica…» se cortaba exactamente antes de
«visualizaciones interactivas».

**Solución: convertirlos en tablas de una celda con borde, en el flujo**, justo después
del título del capítulo. Renderizan igual en cualquier visor y no pueden volver a
interrumpir un párrafo.

⚠ **Moraleja general**: un defecto que uno ve y el otro no, sobre el mismo archivo, casi
siempre es un objeto flotante con geometría cacheada. Detección:
`re.findall(r'<wp:extent[^>]*/>', document.xml)` — si dice `cx="1828800" cy="1828800"`
en un objeto que claramente no es cuadrado de 2″, está mal.

### ⚠ La causa real de las «tablas cargadas» era el estilo Normal

No era alineación ni anchos: las celdas heredaban de `Normal` **interlineado 1,5 y texto
justificado**. Eso inflaba el alto de fila y producía los cortes de línea irregulares en
columnas angostas. Las 33 tablas de datos pasaron a interlineado simple, alineación
izquierda (numéricas centradas), ancho fijo a la caja y márgenes de celda 108 tw — las del
anexo tenían **10 tw**, o sea el texto tocaba las líneas. **El documento bajó 10 páginas.**

Estilo unificado al mayoritario: encabezado celeste `D5E8F0`, sin bandas. Se corrigieron
cuatro tablas: 6.1 y 1.2 tenían encabezado marino `1E3A5F`; 6.1, 8.2 y 8.3 tenían bandeado.

### ⚠ Cuatro DOI llevaban a papers equivocados

Verificación de las 58 entradas resolviendo cada DOI contra Crossref vía
`https://citation.doi.org/format?doi=<DOI>&lang=en-US&style=apa`, que devuelve la cita en
APA lista para comparar. **43 estaban perfectas; 14 tenían problemas.** Informe completo en
`tesis_cap/Verificacion_Citas_v179.md`.

| Entrada | Problema |
|---|---|
| Behar 2019 | DOI → paper de vacunas para VIH · correcto `10.1016/j.eclinm.2019.05.015` · y 2 autores inventados, 3 ausentes |
| **Oliven 2020** | **No existe.** El DOI, volumen y artículo son de un estudio sueco sobre ruido de aerogeneradores |
| Prabhakar 2016b | DOI → capítulo sobre agonistas opioides; el capítulo citado no está en el vol. 860 |
| Zinchuk & Yaggi 2020 | `.09.020` → lesiones torácicas por explosiones · correcto `.09.002` |
| Prabhakar 2016a | DOI `EP085601` → `EP085624`; y era 101(8), 975–985, no 101(3), 394–399 |
| Malhotra 2021 | del 5.º autor en adelante no coincide en nada; son 11, no 15 |
| Clifton | los dos primeros autores invertidos (es **Lei** Clifton) y el año es **2014**, no 2015 |
| Dempsey | `Veasna, P.` → `Veasey, S. C.` |
| Levendowski | 3 autores cambiados |
| Vasey | `Geerts, H.` → `B.`; 4 autores del tramo medio; el último debe ser Perkins, no el nombre del grupo |

**Reemplazo de Oliven** (verificado, y se comprobó que sostiene la afirmación):
Chen, S., Redline, S., Eden, U. T., & Prerau, M. J. (2022). *Dynamic models of obstructive
sleep apnea…* Sleep, 45(12), zsac189. El paper dice literalmente que los eventos
respiratorios «no son independientes» y modela sus patrones temporales — encaja mejor que
el original con el argumento del Cap. 5. **Prabhakar** quedó consolidado en una sola
entrada (2016), sin las letras `a`/`b`.

⚠ **Las 3 entradas con puntos suspensivos que quedan son correctas**: Brown, Masa y Vasey
superan los 20 autores y APA 7 pide 19 nombres, `…` y el último, **sin `&`**. Las 4 que
estaban mal usaban `…` con seis autores, que es APA 6.

### Criterio de cursivas — reemplaza al de §26 y §40

Decisión del autor: **todos los términos en inglés en cursiva, en todas sus apariciones**,
no sólo la primera. Coincide con la RAE (extranjerismo crudo) y con la Guía Editorial.

⚠ **APA no gobierna esto.** APA es una guía en inglés y pide lo contrario para
extranjerismos; en esta tesis rige **sólo la lista de referencias y las citas**. El único
punto de fricción es `et al.`, que por eso va en **redonda**.

| Categoría | Criterio |
|---|---|
| Términos en inglés | cursiva **siempre** |
| Anglicismos en el DLE (sensor, estándar) | redonda |
| Latinismos crudos (*ad hoc*, *a priori*, *per se*, *in vivo*) | cursiva |
| `versus` / `vs.` | **redonda** — está en el DLE, o sea naturalizado |
| `et al.` | **redonda** — aparato de cita, territorio APA |
| Campos y nombres de archivo (`events.parquet`, `NightRecordID`, `drop_pct`) | **redonda**, extensión incluida |
| Modelos y software (K-means, LightGBM, Random Forest, Platt scaling) | redonda |
| Métricas acuñadas (Risk Score PAC, Coupling Index, Average Precision) | redonda |
| Abstract y Keywords en inglés · títulos de sección e índices | fuera de la regla |

⚠ **Guía Editorial actualizada a v18** (`tesis_cap/Guia_Editorial_PAC_2026_v18.docx`): la
v17 decía «campos de datasets y archivos: cursiva» y «latinismos: cursiva» a secas, las dos
superadas acá.

### ⚠ Tres trampas técnicas que costaron una corrida cada una

**1 · Los offsets de `p.text` no coinciden con los de `p.runs`.** `Paragraph.text` incluye
el texto de los `w:hyperlink`; `Paragraph.runs` sólo devuelve los `w:r` hijos directos. Si
se calculan posiciones sobre `p.text` y se aplican recorriendo `p.runs`, en cualquier
párrafo con hipervínculo el marcado cae corrido. Hay que recorrer `p._p.iter(qn('w:r'))`,
que sí sigue el orden del documento. Se detectó comparando el perfil de cursiva carácter a
carácter contra la v175: 882 párrafos, 0 cursivas espurias tras rehacerlo.

**2 · `id()` de un elemento lxml no es estable entre recorridos.** lxml crea un proxy nuevo
en cada acceso, así que `id(child)` de `body.iterchildren()` e `id(t._tbl)` de `doc.tables`
no coinciden aunque envuelvan el mismo nodo. Cualquier mapeo entre los dos recorridos hay
que hacerlo **por posición**.

**3 · Al agregar una sección hay que quitarle `titlePg`.** El `sectPr` del documento lo
tiene activado para que la carátula quede sin encabezado. Al clonarlo para una sección
nueva, esa sección estrena su propia «primera página diferente» y —como hay
`footerReference type="first"` pero ningún `headerReference` equivalente— su primera página
queda **sin encabezado y con el pie de la carátula**. Pasó en las páginas 152 y 155.

### Tabla 1.3 en sección apaisada

La columna «Tabla Gold» necesitaba 3123 tw y tenía 2000: de ahí el corte a mitad de palabra
en `night_multiscale_features.parquet`. Pero reacomodar anchos en vertical no alcanzaba —la
suma de mínimos consume la caja entera—, así que la tabla pasó a **sección apaisada**
(12132 tw, +42 %) y se quitaron las 29 repeticiones de `.parquet`, declaradas una vez en la
Nota. **Sin costo de páginas**: sigue en 172.

⚠ Al hacerlo aparecieron dos páginas en blanco, las dos corregidas: el `sectPr` va **dentro
del `pPr` del párrafo que cierra cada sección**, no en un párrafo propio; y el párrafo vacío
que seguía a la Nota traía un salto de página que el cambio de sección ya aporta (mismo
patrón que §42).

### Auditoría actualizada — sigue en 39 controles

La v185 daba **35/39**, con 2 defectos reales (2 comillas rectas en la Tabla 1.1 y
`ramp-up` en redonda las 6 veces, que ninguna de mis listas cubría) y 3 falsos positivos
por criterios superados. Se tocó `auditar_tesis.py`:

- **Bloque 3**: `es_recuadro()` excluye los 5 recuadros. Un recuadro tiene borde izquierdo y
  derecho por diseño; no es una tabla de datos APA.
- **Bloque 4**: invertido. Antes marcaba «extranjerismos en cursiva más de una vez»; ahora
  marca **«extranjerismos que quedaron en redonda»**. Se agregaron el Abstract, los títulos
  y los índices a las exclusiones, y una lista de contextos protegidos para que no marque el
  `score` de Risk Score PAC ni el `accuracy` de balanced accuracy.
- **Bloque 14.2**: `_ancho_por_tabla()` mapea cada tabla a la caja **de su sección**.

⚠ **Verificado por inyección**, que es como hay que validar un control que se afloja: se
inyectó un `pipeline` en redonda, una línea vertical en una tabla de datos y una tabla
vertical desbordada — **los tres volvieron a saltar** y la auditoría salió con código 1.

### Pendiente

1. **Ctrl+E + F9 en Word** y exportar el PDF **desde Word**. La paginación se movió mucho.
2. **Barrido visual en Word** de las tres páginas apaisadas (152–154).
3. **URL de MacQueen** (`projecteuclid.org/euclid.bsmsp/1200512992`): no se pudo verificar
   porque Project Euclid bloquea el acceso automatizado. Abrirla una vez.
4. **`y_Hmin`** desalineado en `window_risk_predictions.parquet` (viene de §24).

---

## 44. Morfotipos escalares y vector de ventana (Agosto 2026) — hallazgo, no corregido

> Surge de preparar el guion de la defensa. **No afecta ningún resultado publicado**: los Estados PAC se entrenaron con el vector que se describe abajo y son los que son. Afecta a la documentación y a cualquiera que quiera reproducir o extender. **Tratamiento: revisar al pasar a producción.** Detalle operativo en `DEUDA_TECNICA_Y_PRODUCCION.md` §2.6.

### Lo que dice el código

Vector de ventana, `PAC_WINDOW_FEATURES` en `src/pac/config.py` — **24 variables**:

| Grupo | n | Variables |
|---|---|---|
| SpO₂ | 6 | media, desvío, mín, máx, p10, p90 |
| FC | 6 | media, desvío, mín, máx, p10, p90 |
| MOV | 3 | media, desvío, máx |
| Eventos | 6 | `n_edos_total`, `n_alpha`, `n_beta`, `n_gamma`, `n_delta`, `ird_mean_local` |
| Sueño | 3 | `frac_wake`, `frac_light_sleep`, `frac_deep_sleep` |

### Tres desajustes

**1 · Los morfotipos escalares son diez, no cuatro.** `models/edo_morphotype_metadata.json` declara `k: 10`, letras α a κ. Distribución en `gold/events.parquet`: β 51.801 · γ 8.590 · η 7.286 · κ 6.739 · α 4.675 · ζ 3.698 · θ 1.597 · ε 548 · ι 201 · δ 151.

**2 · El vector cuenta solo cuatro de los diez** (`src/pac/windows.py`, mapeo `"α": "n_alpha"` …). Quedan afuera η, κ y ζ —más frecuentes que dos de los contados— y queda adentro **δ, con 151 eventos en todo el corpus**, así que `n_delta` es prácticamente siempre cero. ~24 % de los eventos no contribuyen a ningún recuento por morfotipo. Tiene aspecto de residuo de cuando el modelo era K = 4.

**3 · La tesis describe otra cosa.** El Cap. 5 dice «densidad de morfotipos (conteo de EDOs por tipo **C1–C5** y ARI medio en la ventana)» — la implementación cuenta **α–δ**. El mismo pasaje menciona «**contexto temporal**», que **no existe en el vector**: no hay ninguna variable de posición dentro de la noche. (Sí la hay en NB08, `window_position`, pero es del módulo prospectivo, no de la construcción de estados.)

⚠ **No tocar el Gold ni los modelos por esto.** El principio de `DEUDA_TECNICA` §0.2 sigue vigente: `models/*.pkl` es canon congelado. Corregir el vector obligaría a re-fitear los tres clusterings de estados y a renumerar S/M/L, lo que invalidaría todas las cifras de los Cap. 5 a 8.

⚠ **Para la defensa**: la diapositiva d12 dice «recuento y morfología de los eventos», que es cierto bajo cualquiera de las dos lecturas. El riesgo es contestar siguiendo la tesis y decir C1–C5. Queda consignado en el guion (`scripts/defensa/build_guion.py`, `EXTRAS[12]`).

### 44.b · El IRD sobrevive en el vector de ventana *(Agosto 2026)*

Detectado en la misma revisión. El autor intentó erradicar el IRD y sus derivadas en su momento; **la limpieza no alcanzó a dos lugares**, y los dos alimentan a los Estados PAC.

**1 · Directo.** `src/pac/config.py` línea 274:

```python
"ird_mean_local",  # mean de ird_event sobre los EDOs de la ventana (0 si none)
```

Es el promedio de **`ird_event`**, no del ARI. La evidencia numérica es concluyente:

| | rango observado |
|---|---|
| `ird_event` (lo que entra al vector) | −0,21 a **25,41** |
| `ird_mov_comp`, su componente de movimiento | −0,95 a **125,87** |
| `mean_ari` (el ARI real, nivel noche) | 0,22 a 0,64 |

El ARI es un promedio ponderado de rangos percentiles: **acotado entre 0 y 1 por construcción**. Los centroides de los estados llegan a 6,22. No puede ser el ARI. Y es exactamente el índice cuyo defecto describe §20: *la combinación naïve descartada por escala, donde el MOV crudo absorbe ~98,5 %*.

**2 · Indirecto.** Los morfotipos escalares (§44) se entrenan sobre 10 variables, y **cuatro son IRD**: `ird_event`, `ird_spo2_comp`, `ird_hr_comp`, `ird_mov_comp`. Como sus recuentos entran al vector de ventana, el IRD llega a los Estados PAC **por dos caminos a la vez**.

**Qué no cambia.** Los Estados PAC se entrenaron con ese vector y son los que son. Ninguna cifra publicada se mueve.

⚠ **Qué sí toca: la interpretación.** Cuando el Cap. 5 atribuye a un estado «reactividad autonómica», conviene recordar que la variable que ayudó a definirlo está dominada por el movimiento crudo y no por la señal cardíaca. En la escala S se ve: el estado de mayor `ird_mean_local` (5,09) es también el de mayor `mov_mean` (21,54), muy por encima del resto.

⚠ **Documentación a corregir en la misma pasada.** El Cap. 5 dice «ARI medio en la ventana» y la diapositiva d12 decía «más el ARI»; en los dos casos lo correcto sería «respuesta autonómica media» o nombrar el IRD. Registrado en `DEUDA_TECNICA_Y_PRODUCCION.md` §2.7.
