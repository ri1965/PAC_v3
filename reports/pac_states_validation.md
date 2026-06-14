# PAC_v2 — Validación post-fit de estados PAC

**Timestamp:** `2026-05-16T23:57:47`  
**Modelos:** s=7 · m=5 · l=4  
**Gate:** ⚠ **PROCEED con warnings** — 1 WARN. Avance permitido; revisar warnings antes de paso 7.

## Checks por escala

### Escala `s` — K=7

| ID | Check | Status | Detalle |
|----|-------|:------:|---------|
| C1 | cluster_sizes | ⚠ WARN | min=0.91% · max=32.49% · umbral_FAIL<0.3% · umbral_PASS≥2.0% · WARN=['S5', 'S6'] |
| C2 | centroid_separation | ✓ PASS | min_dist=2.887 · umbral=1.00 · par más cercano=(S0,S1) |
| C3 | morphotype_coherence | ✓ PASS | 3/7 morphotypes dominantes distintos (diversity=0.43 · umbral=0.50) · rango n_edos_total=1.07 (umbral=1.00) · PASS por n_edos_total_range |
| C4 | sleep_coherence | ✓ PASS | max_light=0.99 · max_deep=0.99 · max_wake=0.03 (informativo; wake excluida por training mask) · excepción deep-opcional aplicada |
| C5 | physiological_ranges | ✓ PASS | 24 features chequeadas — todas en rango · 8 valores en zona ε[-1e-03] |

### Escala `m` — K=5

| ID | Check | Status | Detalle |
|----|-------|:------:|---------|
| C1 | cluster_sizes | ✓ PASS | min=4.87% · max=27.75% · umbral_FAIL<0.3% · umbral_PASS≥2.0% |
| C2 | centroid_separation | ✓ PASS | min_dist=2.824 · umbral=1.00 · par más cercano=(M0,M2) |
| C3 | morphotype_coherence | ✓ PASS | 1/5 morphotypes dominantes distintos (diversity=0.20 · umbral=0.50) · rango n_edos_total=2.81 (umbral=1.00) · PASS por n_edos_total_range |
| C4 | sleep_coherence | ✓ PASS | max_light=0.91 · max_deep=0.92 · max_wake=0.13 (informativo; wake excluida por training mask) |
| C5 | physiological_ranges | ✓ PASS | 24 features chequeadas — todas en rango |

### Escala `l` — K=4

| ID | Check | Status | Detalle |
|----|-------|:------:|---------|
| C1 | cluster_sizes | ✓ PASS | min=11.69% · max=34.05% · umbral_FAIL<0.3% · umbral_PASS≥2.0% |
| C2 | centroid_separation | ✓ PASS | min_dist=3.406 · umbral=1.00 · par más cercano=(L1,L3) |
| C3 | morphotype_coherence | ✓ PASS | 1/4 morphotypes dominantes distintos (diversity=0.25 · umbral=0.50) · rango n_edos_total=13.10 (umbral=1.00) · PASS por n_edos_total_range |
| C4 | sleep_coherence | ✓ PASS | max_light=0.52 · max_deep=0.39 · max_wake=0.22 (informativo; wake excluida por training mask) |
| C5 | physiological_ranges | ✓ PASS | 24 features chequeadas — todas en rango · 1 valores en zona ε[-1e-03] |

---

## Umbrales usados

- **C1 cluster_sizes:** FAIL <0.3% · WARN [0.3, 2.0)% · PASS ≥2.0% (escalonado)
- **C2 centroid_separation:** min_dist z-space = 1.0
- **C3 morphotype_coherence:** PASS si diversity ≥ 0.5 o rango n_edos_total ≥ 1.0
- **C4 sleep_coherence:** ≥1 cluster con frac_light_sleep>0.3 y ≥1 con frac_deep_sleep>0.3 (escala s: deep opcional). Wake excluida por training mask (Q6=C).
- **C5 physiological_ranges:** ver PHYS_RANGES en el script (epsilon=0.001 para roundoff de -0.0)

## Interpretación

- **FAIL en C1** = cluster degenerado (<0.3% del training). Sugiere reducir K o revisar features. **WARN en C1** = cluster pequeño (<2.0%) — puede ser outlier clínico válido.
- **FAIL en C5** = algún centroide tiene valores no fisiológicos. Suele indicar bug de z-score o NaN propagado.
- **WARN en C2** = dos clusters están muy cerca en z-space. Considerar reducir K=1 si se confirma redundancia en el dashboard.
- **WARN en C3/C4** = coherencia semántica débil. No bloqueante pero marcarlo para interpretabilidad.
