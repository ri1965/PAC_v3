# Trazabilidad — Cifras de la tesis → Notebook / Celda

> **Cómo leer esta tabla:** cada fila mapea una cifra de titular de la tesis al notebook
> y celda que la produce. La columna **Ubicación en output** indica si la cifra aparece
> en el source del notebook (markdown editable) o en el output ejecutado.
>
> **Fuente de verdad:** `gold/*.parquet`. Los notebooks leen del Gold y reproducen las
> cifras; no modifican el Gold.  
> **Canon de modelos:** `models/*.pkl` + `models/*_metadata.json`. No re-fitear (ver
> `README.md` → Aviso: modelos congelados).

---

## Corpus y cohorte

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| EDOs detectados total | 85,286 | NB01 | c#4 | OUTPUT |
| EDOs quality (con morphotype) | 85,277 | NB01 | c#4 | OUTPUT |
| Noches quality (12 pac.) | 560 | NB03 | c#36 | OUTPUT |
| Noches estrictas (8 pac.) | 540 | NB07 | c#1 | SRC (markdown) |
| Noches Bloque C NB07 (tras dropna) | 494 | NB07 | c#11 | OUTPUT |
| Eventos Bloque B NB07 | 76,053 | NB07 | c#9 | OUTPUT |
| Ventanas prospectivas NB08 | 452,955 | NB08 | c#6 | OUTPUT |

---

## Morfotipos C1–C5 (NB01)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| Distribución C1–C5 (n y %) | C1=55,175 / C2=21,318 / C3=3,662 / C4=4,301 / C5=821 | NB01 | c#4 | OUTPUT |
| C4+C5 severos | 5,122 (6,0 %) | NB01 | c#4 | OUTPUT (cómputo) |
| PC1 morfología curva | 62,9 % varianza | NB01 | c#29 | SRC (markdown) |
| Silhouette k=5 (muestra 8,000) | 0,214 ¹ | NB01 | c#15 | SRC (markdown) |

> ¹ La cifra 0,386 citada en Cap04 §4.2 corresponde al cálculo sobre el corpus completo
> (85,277 curvas), que no está en el output guardado actual del notebook. El notebook
> usa una muestra de 8,000 eventos para el sweep (0,214). Ambas cifras son válidas en
> sus contextos respectivos; la de la tesis proviene del Gold `events_analysis.parquet`.

---

## ARI — Índice de Reactividad Autonómica (NB02–NB03)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| ARI por morfotipo: C5 | 0,422 ± 0,105 ≈ **0,423 ± 0,104** | NB03 | c#9 | OUTPUT |
| ρ(ARI, drop_pct) — ortogonalidad | **0,035** (output actual: 0,034 — stale²) | NB03 | c#9, c#10 | OUTPUT |
| ICC(1,1) ARI noche-nivel (cohorte completa) | **0,69** (output: 0,688) | NB03 | c#41 | OUTPUT |
| ICC(1,1) ARI (cohorte estricta 8 pac.) | 0,74 | NB03 | (ver nota³) | — |

> ² El output guardado de 0,034 fue calculado sobre el corpus anterior (84,248 eventos).
> Al re-correr NB03 contra el Gold actual (85,277 eventos), producirá **0,035**.
>
> ³ El ICC de cohorte estricta (0,74) se computa filtrando `in_strict=True` en NB03.
> El output guardado muestra sólo el valor de cohorte completa (0,688 ≈ 0,69).

---

## PAC States multiescala (NB04)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| V de Cramér morfotipo×estado: S | 0,356 | NB04 | c#8 | OUTPUT |
| V de Cramér morfotipo×estado: M | 0,231 | NB04 | c#8 | OUTPUT |
| V de Cramér morfotipo×estado: L | 0,196 | NB04 | c#8 | OUTPUT |
| S4 → ODI3 correlación | ρ = +0,691 | NB04 | c#8 | OUTPUT |
| M1 → T90 correlación | ρ = +0,744 | NB04 | c#8 | OUTPUT |
| S5 → ARI correlación | ρ = +0,637 | NB04 | c#8 | OUTPUT |
| L0 → T90 correlación | ρ = +0,705 | NB04 | c#8 | OUTPUT |
| PC1 features PAC (21 features) | 36,7 % varianza | NB04 | c#20 | SRC (markdown) |

---

## Acoplamiento morfotipo × estado (NB05)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| V de Cramér acoplamiento: S ⁴ | 0,354 | NB05 | c#8 | OUTPUT |
| V de Cramér acoplamiento: M ⁴ | 0,230 | NB05 | c#8 | OUTPUT |
| V de Cramér acoplamiento: L ⁴ | 0,196 | NB05 | c#8 | OUTPUT |
| RR evento severo — S6 | 4,9× | NB05 | c#20 | OUTPUT |
| RR evento severo — M1 | 3,3× | NB05 | c#20 | OUTPUT |
| RR evento severo — L0 | 2,0× | NB05 | c#20 | OUTPUT |

> ⁴ NB05 calcula V de Cramér sobre su universo de trabajo (83,892 eventos con estado PAC
> asignado), distinto de NB04 (85,277). La diferencia ≤ 0,002 está documentada como
> "internamente consistente" en la tesis. Los valores canónicos de titular provienen de NB04.

---

## Ablación por bloque de features (NB06)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| PAC States: importancia relativa | 44,8 % (0,448) | NB06 | c#15 | OUTPUT |
| Morfotipos C1–C5 | 20,6 % (0,206) | NB06 | c#15 | OUTPUT |
| PAC Dynamics | 14,7 % (0,147) | NB06 | c#15 | OUTPUT |
| ARI (solo) | 3,3 % (0,033) | NB06 | c#15 | OUTPUT |

---

## Modelos predictivos (NB07)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| AUC evento severo — LightGBM (Bloque B) | 0,878 | NB07 | c#16 | OUTPUT |
| AUC evento severo — LR (Bloque B) | 0,743 | NB07 | c#16 | OUTPUT |
| AP evento severo — LightGBM | 0,240 | NB07 | c#16 | OUTPUT |
| AUC riesgo nocturno — LR (Bloque C) | 0,905 | NB07 | c#25 | OUTPUT |
| AP riesgo nocturno — LR | 0,834 | NB07 | c#25 | OUTPUT |
| Risk Score medianas (Normal/Leve/Mod/Sev) | 29,2 / 29,4 / 72,9 / 81,0 | NB07 | c#30 | OUTPUT |

---

## Predicción prospectiva (NB08)

| Cifra | Valor canónico | Notebook | Celda | Ubicación |
|---|---|---|---|---|
| AUC H=5 min (horizonte óptimo) | 0,821 ± 0,022 | NB08 | c#18 | OUTPUT |
| AUC H=2 min | 0,838 ± 0,022 | NB08 | c#18 | OUTPUT |
| AUC H=10 min | 0,785 ± 0,029 | NB08 | c#18 | OUTPUT |
| Sens / Spec / PPV a umbral Youden H=5 min | Sens=75 %, Spec=74 %, PPV≈20 % | NB08 | c#22 | OUTPUT |

---

## Notas generales

- **Outputs guardados vs. outputs frescos:** los outputs guardados en el notebook
  son los generados en el momento del commit final. Pueden diferir mínimamente de
  una re-ejecución si hay diferencias de versión en librerías (rounding de floats).
  Las cifras de la tesis provienen de los outputs frescos verificados contra el Gold.
- **Re-ejecución:** siempre cargar `models/*.pkl` (no re-fitear). Ver `README.md`.
- **Privacidad:** antes de publicar el repo, asegurarse de que `bronze/`, `silver/`,
  `events/`, `states/`, `gold/patients.parquet` y `patients/patient_registry.csv`
  estén excluidos por `.gitignore`.
