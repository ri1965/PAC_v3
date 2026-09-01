# HANDOFF — Revisión editorial final · Tesis PAC

> **Para qué es este archivo.** Abrir un chat nuevo con contexto fresco para una **pasada editorial** sobre la tesis consolidada, sin arrastrar los supuestos de las sesiones previas.
>
> **Qué cargar en ese chat:** este archivo + el `.docx` vigente. Opcionalmente `CLAUDE.md` (contexto del proyecto) y acceso a `~/Proyectos/PAC_v2` para los casos en que una duda editorial requiera verificar un número.
>
> **Alcance: EDICIÓN, no datos.** La verificación numérica contra el Gold está cerrada. Ver §5 para el criterio de corte.
>
> *Generado en la sesión de edición de Julio 2026 (v133 → v139).*

---

## 1. Estado del documento

Versión vigente al cierre de esta sesión: **`tesis_cap/Tesis_PAC_v139.docx`**.

Capítulos 1 a 6 revisados y cerrados. Capítulos 7 a 10 en curso al momento de generar este archivo.

Ya auditado de forma sistemática en todo el documento, **no hace falta repetirlo**:

- Referencias de figuras y tablas: las 30 referencias de callouts ▸ y los 73 captions tienen anclaje en prosa.
- Eliminación completa de SHAP (se declaraba en Métodos pero nunca se reportaba; lo que se usa es importancia Gini, ganancia y coeficientes).
- Estandarización de MOV ("movimiento de dedo (MOV)", definido una sola vez) y de FC.
- Capas del pipeline (Bronze / Silver / Events / Gold) unificadas a redonda.
- Convención "Capítulo N" / "Cap. N" aplicada en todo el documento.
- Colapso de despliegues redundantes de LOPO-CV.

---

## 2. Convenciones editoriales vigentes

**Tono de potencialidad.** Nunca afirmaciones taxativas sobre resultados o capacidades. Condicional siempre: "podría", "sugiere", "resultaría". Evitar el indicativo pleno en "es", "demuestra", "cuantifica", "confirma". Excepción: la descripción directa de datos observados ("el ARI en CHA es más bajo") admite indicativo.

**Audiencia: científicos de datos, no especialistas en medicina del sueño.** La clínica se explica; el vocabulario de ciencia de datos se asume conocido.

**Itálica.** Solo para extranjerismos que se introducen y glosan en su primera mención (*hypoxic burden*, *baseline*, *batch*). **No** para nombres propios: algoritmos (K-means, PCA, LightGBM), marcas (SOMNI 6000), organismos (ANMAT, FDA), capas del pipeline (Bronze, Silver, Events, Gold), software (PAC_v3). Ninguno de estos va en negrita tampoco: la negrita se reserva a títulos y epígrafes.

**Capítulos.** "Capítulo N" cuando es parte de la oración ("El Capítulo 5 introduce…"); "Cap. N" en remisiones entre paréntesis o encadenadas con secciones ("(Cap. 4 §4.3.1)"). Nunca con cero a la izquierda en prosa.

**Estados PAC.** Plural en mayúscula cuando nombra el sistema ("los Estados PAC en tres escalas"); singular en minúscula cuando designa una instancia ("el estado PAC activo en los 5 min previos"). La regla ya se cumple en el 96 % de los casos.

**Puntuación.** Sin rayas largas (—) en el cuerpo: se reemplazan por dos puntos, punto y coma, comas o paréntesis. Sin espacio antes de punto y coma.

**Figuras y tablas.** Toda figura o tabla necesita mención en prosa, no alcanza el callout ▸. Formato de remisión al Anexo: "(Tabla 4.8; Fig. 4.6, Anexo Suplementario)".

**Prosa y números.** La prosa describe y argumenta; los números viven en las tablas. No transcribir una tabla a texto corrido.

**Redundancia entre capítulos.** Cada capítulo asume que el lector leyó los anteriores. Los párrafos puente son transiciones, no resúmenes: no deben repetir datos ya establecidos.

---

## 3. Decisiones deliberadas — NO revertir

Lo siguiente parece inconsistente pero se decidió así:

- **Nota de la Fig. 5.4**: "nombrados en §5.3 y en el Cap. 6" usa la forma abreviada en texto corrido, para mantener el paralelismo con la sección coordinada.
- **Rótulos del Anexo** del tipo "Cap. 4 Fenotipado Morfológico…": son encabezados estructurales que agrupan figuras por capítulo, no prosa. La convención de capítulos no aplica.
- **§4.6**: "cada patrón se lo denomina Estado PAC", singular en mayúscula, porque es el momento en que se acuña el término.
- **Figura 6.4** (esquema conceptual del acoplamiento en escala M): repite datos de la Fig. 6.2 y de la 6.3, pero se conserva por su valor didáctico. Se movió a §6.2 en la v138.
- **Glosario**: las notas de tabla y las entradas del glosario repiten definiciones a propósito, porque se leen sueltas.
- **Cuadros flotantes "¿Qué debe recordar el lector?"**: son didácticos por diseño; su redundancia con el cuerpo es intencional.

---

## 4. Trampas técnicas del archivo

Aquí se perdió más tiempo que en ninguna otra parte. Tres auditorías de esta sesión entregaron datos incorrectos por estos motivos.

**Cuadros de texto flotantes.** Hay diez (cinco duplicados por el anclaje de Word) con el bloque "¿Qué debe recordar el lector antes de continuar?". **`python-docx` no los ve al recorrer `document.paragraphs`.** Hay que buscarlos con `body.findall(qn('w:txbxContent'))`. **Nunca fueron auditados con criterio editorial completo** — es tarea pendiente.

**Índices y TOC son campos automáticos.** El Índice de Figuras, el de Tablas y el índice general se regeneran de los captions. No editarlos a mano: se corrige el caption y se actualiza con F9 en Word.

**Referencias cruzadas.** Algunas menciones como la "Fig. 4.5" de §4.3 son campos de Word, no texto. Su contenido no aparece al concatenar `runs` (sí en `paragraph.text`). Editarlas por texto las rompe.

**Marcadores de capítulo corridos.** Los párrafos "CAPÍTULO N" solo existen del 2 al 10; el Capítulo 1 no está rotulado así. Indexar capítulos por posición en esa lista da un corrimiento de uno.

**Tablas y figuras comparten numeración.** Buscar "8.5" sin distinguir tipo hace que "Tabla 8.5" satisfaga una búsqueda de "Figura 8.5". Todo chequeo de referencias debe discriminar por tipo.

**Hipervínculos anidados.** Se encontró y corrigió uno (caption de la Fig. 6.6) que volvía el párrafo invisible para `python-docx`. Si vuelve a aparecer un caption "vacío", revisar esto.

**Edición segura.** Para modificar texto conservando formato: ubicar el run que contiene la cadena y editarlo, en lugar de reescribir el párrafo. Si la cadena cruza varios runs, escribir el reemplazo en el primero y vaciar el tramo en los siguientes.

---

## 5. Alcance de la pasada y criterio de corte

**Qué buscar:**

1. Redundancia conceptual dentro de un capítulo y entre capítulos (especialmente Discusión y Conclusiones).
2. Coherencia de los puentes narrativos: lo que un capítulo promete, ¿lo entrega el siguiente?
3. Afirmaciones taxativas que deberían ir en condicional.
4. Contradicciones internas: una sección que afirma lo que otra matiza.
5. Anglicismos, calcos y jerga clínica no glosada.
6. Los diez cuadros de texto flotantes, nunca auditados.

**Regla de admisión.** Se corrige solo lo que un jurado podría señalar como **error**: contradicciones, afirmaciones sin respaldo, referencias rotas, datos que no cierran. Las preferencias de estilo, los sinónimos y los matices de redacción se anotan y **no se tocan**.

**Por qué existe esta regla.** Las evaluaciones de jurado ya dieron 9,5 sobre 10, con el 0,5 restante explícitamente estructural (n = 8, circularidad PAC). Ninguna edición mueve esa nota: solo protege lo ya logrado. Y cada versión nueva es una oportunidad de romper algo — en esta sesión se rompieron las referencias de las Tablas 1.2 y 1.3 al reescribir §1.3, y se detectó por casualidad.

**Corte.** Cuando se completen los seis puntos de "qué buscar" y los tres pendientes del §6. No se reabre.

---

## 6. Pendientes concretos al cierre de esta sesión

1. **Auditar los diez cuadros de texto flotantes** con criterio editorial completo. El único hallazgo conocido: en el cuadro del Cap. 4, "los índices clásicos (AHI, ODI3, T90) resumen la carga global de la noche" contradice §2.1, donde el argumento es que esos índices **no** capturan la carga hipóxica. Reemplazo sugerido: "resumen la noche en valores escalares de frecuencia o de tiempo acumulado".
2. **Verificar §7.4 contra las capturas reales.** Las descripciones de las Fig. 7.4 a 7.10 se dedujeron de los rótulos del callout, sin ver cada imagen.
3. **Actualizar campos en Word (F9)** al final de todo: índices, TOC y referencias cruzadas.

---

## 7. Nota de método

Buena parte de la verificación conviene hacerla con scripts antes que leyendo: inventarios de referencias, conteos de convenciones, detección de afirmaciones huérfanas. Es más confiable. Pero los scripts también fallan: los tres errores de auditoría de esta sesión fueron de programación, no de lectura, y se detectaron porque el autor dudó de los resultados. **Cuando un resultado agregado sorprenda, verificar un caso a mano antes de reportarlo.**
