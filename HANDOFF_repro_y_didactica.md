# HANDOFF — Etapa de reproducibilidad + didáctica (Junio 2026)

> **Cómo usar este archivo:** cargalo junto con `CLAUDE.md` al abrir un chat nuevo.
> Es el puente entre la sesión de verificación/corrección (cerrada) y lo que falta
> (reproducibilidad del repo + claridad pedagógica + consolidación final de los 13 capítulos).
>
> **Modelo sugerido para esta etapa: Sonnet.** El "dato duro" ya está cerrado y verificado
> contra el Gold; lo que viene es redacción, limpieza de notebooks y trazabilidad. Reservar
> el modelo fuerte (Opus) solo si se reabre una decisión de cifra canónica.

---

## 0. Principio rector (no reabrir)

**El Gold (`gold/*.parquet`) es la única fuente de verdad.** Ya se verificó de forma
independiente (recomputando desde `gold/*.parquet` + NB01–NB08) que reproduce las cifras de la
tesis. La etapa de "verificación numérica" está **cerrada**. De acá en más es maquillaje,
pedagogía y reproducibilidad — no se tocan resultados.

> ## ⚠ REGLA CRÍTICA — NO RE-FITEAR LOS MODELOS
> El proyecto ya persistió los modelos entrenados en **`models/`** (K-means de morfotipos
> `edo_morphotype_curve_kmeans.pkl`; estados `pac_states_s/m/l_kmeans.pkl`; trayectorias
> `nb05_traj_kmeans.pkl`; predictivos `nb06_event_lgbm.pkl`, `nb06_night_lr.pkl`; arrays del ARI
> `ari_*_sorted.npy`; + centroides, `*_zscore.json` scalers y `*_metadata.json` con el mapeo
> etiqueta→nombre). **Estos modelos son canon congelado, igual que el Gold.**
>
> Al re-correr, **CARGAR y APLICAR los `models/*.pkl` (load + `predict`/`transform`), NUNCA
> volver a `.fit()`.** Cargando los modelos, el resultado es determinístico → mismos clusters,
> mismas etiquetas (C1–C5, S/M/L), mismos números, byte a byte: las conclusiones y las cifras
> no se mueven.
>
> Re-fitear de cero (hay `KMeans().fit()` dentro de NB01/NB04/NB05) introduce dos riesgos reales:
> **(a) permutación de etiquetas** (C4 podría pasar a llamarse C2 — no cambia la ciencia pero
> rompe todas las tablas/referencias de la tesis) y **(b) drift por versión de librería** (k-means++
> puede inicializar distinto aun con `random_state` fijo). Por eso: **load, no fit.**
>
> Si se quiere además una demo "desde cero" para el jurado, hacerla en **rama aparte**, pinear
> versiones exactas y **re-anclar las etiquetas a los centroides guardados** (asignar cada cluster
> nuevo al centroide más cercano), verificando contra el Gold congelado. El canon publicado sigue
> siendo el Gold + `models/`.

---

## 1. Decisiones canónicas ya tomadas (respetar)

- **ρ(ARI, ODI3) = 0,034 NO existe.** Era el valor de `drop_pct` mal etiquetado. El titular de
  ortogonalidad del ARI es **ρ(ARI, drop_pct) = 0,035**; el ODI3 va como mención secundaria.
  (ρ real vs ODI3 = −0,066 evento / −0,245 noche — no usar como titular.)
- **Risk Score = valores del Gold:** medianas **29,2 / 29,4 / 72,9 / 81,0** (Normal/Leve/Moderado/Severo);
  capturas @60: **100 % Severas · 77,6 % Moderadas · 9,0 % Leves** (n=494). Las viejas
  25,6/31,6/72,2/80,8 eran un artefacto no reproducible → **descartadas**. La mediana de Leve (29,4)
  cae en rango **Bajo (<30)**.
- **Cifras de titular completas:** ver la tabla "Referencia rápida — cifras de titular" al inicio
  del **Anexo Suplementario (v22)**.

---

## 2. Estado actual de la tesis — set CANON de 13 capítulos

Versiones finales en `~/Proyectos/PAC_v2/tesis_cap/` (verificadas, estado aceptado limpio):

| # | Capítulo | Versión | Notas |
|---|---|---|---|
| 1 | Introducción | **v12** | + párrafo de "mensaje único" |
| 2 | Marco Teórico | **v5** | copyedit (paréntesis) |
| 3 | Materiales y Métodos | **v12** | M2 + 77,6 % + doble coma |
| 4 | Fenotipado + ARI | **v20** | sin cambios (ya reproducía) |
| 5 | PAC States | **v22** | trabajo paralelo, verificado limpio |
| 6 | Modelado predictivo | **v36** | H1 (ARI) + H2 (Risk Score) |
| 7 | App clínica | **v12** | sin cambios |
| 8 | Predicción prospectiva | **v19** | trabajo paralelo, verificado limpio |
| 9 | Discusión | **v22** | H1 (ARI ortogonal) |
| 10 | Conclusiones | **v10** | H1 (ARI) |
| A | Referencias | **v5** | portada |
| B | Glosario | **v16** | H1 + H2 |
| Supl. | Material Suplementario | **v22** | H2 + tabla de titular + portada |

**Importante:** los capítulos están **con control de cambios**. Antes de ensamblar →
"Aceptar todos los cambios" en cada uno. (⚠ `accept_changes.py`/LibreOffice falló en el
entorno Cowork; aceptar manualmente en Word.)

**Carpeta volátil:** `tesis_cap/` se sincroniza/edita por fuera y aparecen versiones paralelas.
**Confirmar versión por versión** antes de ensamblar (no asumir que la última guardada es la que está).

**Archivos viejos a borrar** (quedaron de iteraciones): Cap01 v8/v9/v10/v11 · Cap02 v4 ·
Cap03 v9/v11 · Cap06 v34/v35 · Cap09 v21 · Cap10 v9 · Anexo A v4 · Anexo B v12/v15 ·
Anexo Suplementario v18/v19/v20/v21.

---

## 3. Trabajo pendiente — Reproducibilidad del repo (jury-ready)

Objetivo: que un jurado de Ciencia de Datos que mire el repo en git vea **los mismos números
que la tesis**. Hoy el *Gold* coincide, pero los notebooks como artefacto publicado **no del
todo** (salidas/markdown viejos + notebooks exploratorios). Tareas:

1. **Re-correr NB01–NB08 de punta a punta contra el Gold final**, para que salidas y figuras
   (`notebooks/figuras/`) reflejen el canon — **cargando los `models/*.pkl`, sin re-fitear**
   (ver REGLA CRÍTICA arriba).
2. **Corregir labels viejos en markdown/celdas:** `553 → 560` noches (NB01/NB03 al menos);
   `84.248 → 85.277` (NB01); C4 `4.377 → 4.301`, C5 `800 → 821`; y barrer otros restos
   (84.193, V de Cramér vieja, S=6/M=8/L=6 preliminar, Risk Score 25,6/31,6).
3. **Mover NB09–NB11 a `/exploratory`** (o marcarlos "no incluidos en la tesis"). La tesis usa
   solo NB01–NB08; NB09 (optimización trigger), NB10 (clasificador temprano) y NB11 (predicción
   mejorada) son paralelos y pueden confundir/contradecir si quedan sin aclaración.
4. **README de trazabilidad:** tabla "cifra de la tesis → notebook/celda que la produce". Es lo
   que más tranquiliza a un jurado de DS y juega a favor. Base: la tabla de titular del Anexo Supl. v22.
5. **Fijar/documentar el etiquetado de clusters y versiones de librería.** El mapeo etiqueta→nombre
   ya está resuelto si se **cargan los modelos guardados** (`models/*_kmeans.pkl` + `*_metadata.json`);
   solo hay riesgo de **permutación** si se re-fitea (no hacerlo — ver REGLA CRÍTICA). Documentar el
   mapeo de los metadata en el README y **pinear versiones exactas** de librerías (`requirements.txt`
   ya existe).

### Agregados recomendados (importantes)

6. **PRIVACIDAD / datos médicos — crítico antes de pushear.** El repo tiene datos fisiológicos a
   nivel paciente (`bronze/`, `raw/`, `silver/`, `states/`, `events/`) y demográficos/clínicos en
   `patients.parquet` (sexo, peso, talla, apnea_prev, diabetes, hta, marcapasos). Eso es **dato de
   salud identificable**: **no publicar sin de-identificación y consentimiento**. Recomendado:
   `.gitignore` para todas las capas de datos crudos/intermedios y publicar **solo código** (o, a lo
   sumo, Gold agregado y de-identificado). Revisar también que los **outputs guardados de los
   notebooks** no impriman series/IDs de pacientes.
7. **Verificar permutación de clusters tras re-correr:** confirmar que C1–C5 (y S/M/L) siguen
   significando lo mismo; si permutan, re-mapear antes de regenerar figuras/tablas.
8. **Confirmar Risk Score post-corrida:** que NB07 siga dando 29,2/29,4/72,9/81,0 (fórmula
   `p_ev_norm = p_ev / p_ev.max()`).
9. **README principal del repo:** propósito, cohorte (12 pac / 560 noches), pipeline
   Bronze→Silver→Events→Gold, orden de ejecución, y disclaimer (observacional; el estimulador del
   SOMNI 6000 es hipótesis operacional, no eficacia demostrada).

---

## 4. Tarea final

Una vez re-corrido y validado todo contra el Gold:

- Reconciliar (si hiciera falta) los 13 capítulos canon → **versión final consolidada** (cambios
  aceptados, números confirmados contra el Gold y contra las salidas frescas de los notebooks).
- Recién entonces: **ensamblar los 13 en el documento único** de la tesis.

---

## 5. Notas de entorno / gotchas

- **Build docx:** Node.js + librería `docx`; control de cambios vía XML (`<w:del>`/`<w:ins>`,
  autor "Claude"). Validar con `scripts/office/validate.py`; ojo con el orden de elementos
  (`tblBorders` antes de `tblLook`; bordes de párrafo no llevan left/right con esa librería).
- **`accept_changes.py` (LibreOffice) puede fallar** en Cowork → aceptar en Word.
- **Desfasaje de portadas** (cover vs nombre de archivo): ya alineado en las versiones nuevas;
  vigilarlo si se generan más versiones.
- **`tesis_cap/` es un blanco móvil** (edición en paralelo): subir/confirmar el archivo real antes
  de operar sobre él.

---

*Generado al cierre de la sesión de verificación/corrección, Junio 2026. Estado: 13 capítulos canon
verificados contra el Gold; pendiente la limpieza de notebooks/repo y el ensamblado final.*
