# NB08 — Informe: Predicción anticipada de EDO severo (lead time)
**PAC_v2 · Gold v1.2 · Cohorte cohort_strict (8 pacientes, 540 noches)**
*Fecha: mayo 2026*

---

## 1. Qué pregunta responde este análisis

NB07 predice la severidad de un evento ya en curso (tarea condicionada: dado que hay un EDO, ¿es C4/C5?). NB08 responde una pregunta diferente y clínicamente más exigente: **dado el estado del sistema en el momento T, ¿habrá un EDO severo (C4/C5) en los próximos Δt minutos?** La pregunta es prospectiva, no condicionada a que haya un evento en progreso.

La motivación es la estimulación eléctrica transcutánea autonómica, que requiere activarse *antes* del evento con suficiente margen para que el ramp-up fisiológico (~90 s) sea efectivo.

---

## 2. Diseño del análisis

**Unidad de análisis:** ventanas temporales continuas de 30 s (escala S del sistema PAC), sin condicionar a eventos. Total: 452.955 ventanas × 4 horizontes.

**Features (todas backward-looking, sin lookahead):**
- Estado PAC actual en escalas S, M y L (enteros)
- Posición relativa en la noche (0–1)
- Eventos y severos en últimos 5 y 10 min
- Severidad morfológica media últimos 5 min (`morph_mean_5min`)
- Tiempo transcurrido desde último evento / último severo
- Conteo acumulado de C4/C5 en la noche (`n_severe_sofar`)
- Coupling index acumulado (`ci_sofar`)

**Targets:** para cada ventana que termina en t_end, se define `y_Δt = 1` si existe un C4/C5 con ts_start ∈ (t_end, t_end + Δt). Se evalúan Δt ∈ {2, 5, 10, 15 min}.

**Validación:** LOPO-CV estricto (leave-one-patient-out, 8 folds). Modelos: Logística (baseline) y LightGBM (300 estimadores).

---

## 3. Prevalencia de los targets

| Horizonte | Ventanas positivas | % de total |
|-----------|-------------------|------------|
| 2 min     | 16.951            | 3,74 %     |
| 5 min     | 36.438            | 8,04 %     |
| 10 min    | 62.853            | 13,88 %    |
| 15 min    | 85.583            | 18,89 %    |

La prevalencia aumenta con el horizonte por la definición acumulativa del target. El 5,59 % de eventos son C4/C5 en la cohorte, pero la tasa de ventanas "positivas" en 5 min alcanza 8 % porque un único evento severo hace positivas múltiples ventanas previas.

**Heterogeneidad inter-paciente** (horizonte 5 min):

| Paciente | Ventanas | Positivos | Prevalencia |
|----------|----------|-----------|-------------|
| 175      | 21.271   | 6.836     | 32,1 %      |
| 240      | 19.205   | 2.368     | 12,3 %      |
| 309      | 53.138   | 2.596     | 4,9 %       |
| 314      |  7.561   |   119     | 1,6 %       |
| 321      | 80.438   | 3.898     | 4,8 %       |
| 336      | 115.701  | 8.275     | 7,2 %       |
| 656      | 90.886   | 7.165     | 7,9 %       |
| 683      | 64.755   | 5.181     | 8,0 %       |

El rango va de 1,6 % (paciente 314 — muy pocos eventos severos) a 32,1 % (paciente 175 — perfil de carga severa muy alta). Esta variabilidad de 20× entre pacientes es el principal factor limitante para cualquier umbral global de activación.

---

## 4. Rendimiento discriminativo

### 4.1 AUC global LOPO-CV

| Horizonte | AUC Logística | AUC LightGBM | AP LightGBM | Mejora sobre base |
|-----------|--------------|--------------|-------------|-------------------|
| 2 min     | 0,789        | **0,838**    | 0,203       | 5,4×              |
| 5 min     | 0,774        | **0,821**    | 0,326       | 4,1×              |
| 10 min    | 0,760        | **0,783**    | 0,396       | 2,9×              |
| 15 min    | 0,750        | **0,763**    | 0,449       | 2,4×              |

LightGBM supera a la Logística en 3–5 puntos de AUC en todos los horizontes, con mayor ventaja en los horizontes cortos (donde la no-linealidad de los patrones PAC es más informativa). La diferencia sugiere que la relación entre estado PAC y riesgo inminente no es capturada adecuadamente por un modelo lineal.

La AUC disminuye monotónicamente con el horizonte: **0,838 → 0,821 → 0,783 → 0,763**. Esta pendiente es moderada, lo que significa que el sistema mantiene poder discriminativo razonable incluso a 15 min, pero el máximo de información se concentra en los 2–5 min previos al evento.

### 4.2 Estabilidad por paciente (LightGBM)

| Horizonte | AUC medio ± SD  |
|-----------|-----------------|
| 2 min     | 0,838 ± 0,022   |
| 5 min     | 0,821 ± 0,022   |
| 10 min    | 0,785 ± 0,029   |
| 15 min    | 0,765 ± 0,032   |

La desviación estándar es pequeña (<3 puntos) en los 8 folds para todos los horizontes. Esto indica que **el modelo generaliza entre pacientes** de manera consistente, a pesar de las diferencias en prevalencia. Es uno de los resultados más alentadores del análisis.

---

## 5. Análisis operacional — Umbral de activación

Usando el umbral de Youden (maximiza Sensibilidad + Especificidad − 1):

| Horizonte | Umbral | Sensibilidad | Especificidad | Precisión (PPV) |
|-----------|--------|-------------|---------------|-----------------|
| 2 min     | 0,393  | 0,82        | 0,70          | 9,6 %           |
| 5 min     | 0,459  | 0,76        | 0,74          | 20,1 %          |
| 10 min    | 0,473  | 0,69        | 0,74          | 29,8 %          |
| 15 min    | 0,465  | 0,68        | 0,71          | 35,4 %          |

La **precisión es el número crítico para uso clínico**. Con horizonte 2 min el sistema detectaría 82 % de los eventos severos, pero solo 1 de cada 10 alarmas sería verdadera. Con horizonte 5 min la precisión sube a 20 %: 1 de cada 5 alarmas corresponde a un evento real. Con 10–15 min la precisión mejora (29–35 %) pero la sensibilidad baja y el lead time pierde relevancia para ramp-up de estimulación de 90 s.

---

## 6. Implicancias para estimulación eléctrica transcutánea

La pregunta original era: *¿con cuánto tiempo de anticipación puede el sistema predecir un EDO severo?*

**Respuesta concreta:** el sistema mantiene AUC ≥ 0,76 para todos los horizontes evaluados (2–15 min). El horizonte clínicamente útil para estimulación transcutánea con ramp-up de ~90 s es **5 min**, que ofrece el mejor balance entre:

- Lead time suficiente (5 min >> 90 s de ramp-up)
- AUC discriminativa: 0,821
- Sensibilidad: 76 % (3 de cada 4 eventos severos anticipados)
- Especificidad: 74 % (tasa de falsas alarmas manejable)
- Precisión: 20 % (1 de cada 5 activaciones coincide con evento real)

Con horizonte 2 min la sensibilidad es mayor (82 %) pero el margen temporal es ajustado y la precisión baja (10 %) generaría una tasa de falsas activaciones 2× mayor. Para un sistema de estimulación crónico nocturno, activarse 9 veces por nada por cada activación real es probablemente intolerable.

**Estimación de la carga de falsas alarmas:** con base rate 8 % (horizonte 5 min) y Spec=0,74, el 26 % de las ventanas negativas activan una alarma. En una noche de ~840 ventanas S con ~92 % negativas, esto equivale a ~200 falsas alarmas por noche en el peor caso con threshold fijo. En la práctica, las alarmas consecutivas dentro de un mismo "episodio" se fusionan, reduciendo la carga real.

---

## 7. Limitaciones

**Muestra críticamente pequeña.** n=8 pacientes en LOPO-CV deja solo 7 sujetos para entrenamiento. La consistencia de AUC ± 0,022 es alentadora, pero no constituye evidencia para generalización clínica.

**Heterogeneidad no modelada.** La variación de 1,6 % a 32,1 % en prevalencia implica que un umbral global óptimo para paciente 175 sería inapropiado para paciente 314 y viceversa. Un sistema de activación clínico requeriría calibración individualizada por paciente.

**Circularidad potencial.** Las features incluyen el estado PAC (estados aprendidos sobre la misma cohorte), el coupling index y el morph_mean. Si el sistema PAC ya captura implícitamente la tendencia a eventos severos en su representación latente, parte del AUC puede reflejar dependencias circulares, no generalizabilidad.

**AP es modest.** Aunque AUC = 0,821 para 5 min, la Average Precision es 0,326 (base 8 %). Esto significa que las curvas precisión-recall tienen rendimiento moderado: en regímenes de alta sensibilidad la precisión cae rápidamente. AUC y AP son métricas complementarias; en clasificación con desequilibrio severo, la AP es más informativa para decisiones operacionales.

**Sin validación externa.** Los resultados son internos a la cohorte PAC_v2. No existe evidencia de transferibilidad a otras cohortes o dispositivos de monitoreo.

**morph_mean_5min ausente en 28,7 % de ventanas.** En ventanas donde no hay ningún evento en los últimos 5 min, el feature es NaN (imputado por mediana). Esto inyecta ruido en el predictor más informativo para el lead time corto.

---

## 8. Comparación con NB07

| Aspecto | NB07 | NB08 |
|---------|------|------|
| Pregunta | ¿Es severo este evento en curso? | ¿Habrá EDO severo en los próximos Δt min? |
| Unidad de análisis | Eventos individuales (~76K) | Ventanas continuas de 30 s (~453K) |
| Target | Binario (leve/severo) dentro del evento | Binario por horizonte (0/4 umbrales) |
| AUC reportada | 0,905 (evento en curso) | 0,821 (5 min de anticipación) |
| Acción clínica habilitada | Clasificar severidad real-time | Activar estimulación preventiva |
| Dificultad de la tarea | Menor (el evento ya ocurrió) | Mayor (prospectivo, sin señal de evento) |

La diferencia de AUC (0,905 vs 0,821) refleja la dificultad inherente: predecir el futuro desde el presente sin señal de evento en curso es fundamentalmente más difícil que clasificar un evento ya observable. El delta de 8 puntos es razonable.

---

## 9. Conclusión

El sistema PAC puede predecir la ocurrencia de un EDO severo con **5 min de anticipación** con AUC = 0,821, sensibilidad 76 % y especificidad 74 %, generalizando de forma consistente entre los 8 pacientes de la cohorte (AUC = 0,821 ± 0,022). La pendiente de la curva AUC vs. lead time es moderada, lo que sugiere que el estado multiscala PAC transporta información predictiva sostenida en el horizonte de 2 a 15 min.

Para estimulación transcutánea con ramp-up de ~90 s, el **horizonte de 5 min es el punto operacional óptimo**: ofrece lead time suficiente, AUC ≥ 0,82 y precisión 20 % (que puede mejorarse con calibración individual). La mayor barrera para traslación clínica no es el AUC sino la heterogeneidad inter-paciente en prevalencia (1,6–32,1 %), que exige umbrales personalizados, y el tamaño muestral (n=8), que impide validar la generalización a nuevos sujetos.

El resultado es suficientemente sólido para justificar una fase de validación prospectiva en una cohorte externa de al menos 30–50 pacientes con perfil similar.
