# Puesta al día del repo tras la entrega — paso a paso

> Repo: `https://github.com/ri1965/PAC_v3.git` (**público**) · rama actual al día con el remoto (0 commits sin pushear).
> Nada de lo que sigue es destructivo salvo el Paso 6, que está marcado y es opcional.
> Regla general: **revisar antes de cada `commit`**, y no hacer `git add .` en ningún momento.

---

## Paso 0 · Decisión previa: `patients/clinical.csv`

Está trackeado desde el commit inicial (`9c5ff4c`) en un repo público. 12 filas:

```
patient_id ; sexo ; peso_kg ; talla_cm ; apnea_prev ; diabetes ; hta ; marcapasos
```

Los `patient_id` (175, 314, 656…) son los mismos que nombra la tesis. El Anexo D dice que «el repositorio no incluye registros clínicos de pacientes».

Elegir una antes de seguir:

- **(a) Dejarlo como está** → saltear al Paso 1.
- **(b) Dejar de servirlo de ahora en más** → hacerlo en el Paso 4b.
- **(c) Borrarlo también de la historia** → Paso 6 (opcional, pesado).

---

## Paso 1 · Ver dónde estás parado

```bash
cd ~/Proyectos/PAC_v2
git status
git log --oneline -3
```

Esperado: rama limpia respecto del remoto, y estos cambios pendientes:

```
 M CLAUDE.md
 M notebooks/figuras/06C_01_roc_clasificacion_noche.png
 D tesis_cap/Tesis_PAC_v64.docx
?? CLAUDE.md.bak
?? DEUDA_TECNICA_Y_PRODUCCION.md
?? HANDOFF_revision_final.md
?? exam_11585.xlsx
?? scripts/tesis_qa/
```

---

## Paso 2 · `.gitignore` primero (antes de cualquier `add`)

Abrir `.gitignore`. Hay **dos bloques duplicados** de `tesis_cap` (líneas ~91–94):

```
tesis_cap/**
!tesis_cap/Tesis_PAC_v62.docx

# --- tesis_cap: solo el texto final en el repo (resto = intermedios) ---
tesis_cap/**
!tesis_cap/Tesis_PAC_v64.docx
```

Reemplazar **los dos bloques** por uno solo:

```
# --- tesis_cap: solo la versión de entrega en el repo (resto = intermedios) ---
tesis_cap/**
!tesis_cap/Tesis_final.docx
!tesis_cap/Tesis_final.pdf

# --- datos de examen: nunca al repo (Anexo D) ---
exam_*.xlsx
~$*.docx
```

Ajustar `Tesis_final` al nombre exacto que uses.

⚠ La negación `!tesis_cap/...` **solo funciona con archivos que estén directamente dentro de `tesis_cap/`**, no en subcarpetas. Ya está probado: así es como quedó trackeada la v64.

Verificar que quedó bien:

```bash
git check-ignore -v exam_11585.xlsx                 # debe decir que lo ignora
git check-ignore -v tesis_cap/Tesis_PAC_v174.docx   # debe ignorarlo
git check-ignore    tesis_cap/Tesis_final.docx      # NO debe imprimir nada
echo "exit=$?"                                       # exit=1 significa "no ignorado" = correcto
```

Commit:

```bash
git add .gitignore
git commit -m "chore(git): excluir datos de examen y dejar solo la versión de entrega en tesis_cap"
```

---

## Paso 3 · La versión de entrega reemplaza a la v64

Hoy el repo sirve `Tesis_PAC_v64.docx` — 111 versiones atrás, anterior a todo el re-baseo contra el Gold. Y en tu disco ya no existe.

Copiar la versión de entrega a `tesis_cap/` con el nombre sin versión, y después:

```bash
git rm --cached tesis_cap/Tesis_PAC_v64.docx     # deja de trackearla
git add -f tesis_cap/Tesis_final.docx            # -f: hace falta por el tesis_cap/**
git add -f tesis_cap/Tesis_final.pdf             # si también querés el PDF
git status                                        # revisar antes de commitear
git commit -m "docs(tesis): versión de entrega; retira el intermedio v64"
```

`git rm --cached` **no borra el archivo de tu disco**, solo lo saca del índice.

---

## Paso 4 · El resto de los cambios, un commit por tema

### 4a · El toolkit de auditoría (recomendado)

176 KB, ~24 archivos, y **es la única copia que existe**: `auditar_tesis.py` (los 39 controles), `cifras_canonicas.py` (la red que evita que un número vuelva atrás), `lib_docx.py`, `parse_refs.py` y los `fix_v*.py`.

```bash
git add scripts/tesis_qa/
git status --short scripts/tesis_qa/ | head -30    # revisar la lista
git commit -m "feat(qa): toolkit de auditoría de la tesis (39 controles + cifras canónicas)"
```

⚠ Antes de commitear, confirmar que no se cuela ningún `.docx` intermedio ni `__pycache__`:

```bash
git diff --cached --name-only | grep -Ei '\.docx$|__pycache__' || echo "limpio"
```

Si aparece `__pycache__`, sacarlo con `git rm -r --cached scripts/tesis_qa/__pycache__` y agregar `__pycache__/` al `.gitignore`.

### 4b · Documentación y figura

```bash
git add CLAUDE.md notebooks/figuras/06C_01_roc_clasificacion_noche.png
git commit -m "docs: contexto de la tesis al día (§41 lectura de estilo, §42 entrega) + figura ROC"
```

Si elegiste la opción **(b)** del Paso 0:

```bash
git rm --cached patients/clinical.csv
echo "patients/clinical.csv" >> .gitignore
git add .gitignore
git commit -m "chore(datos): retirar patients/clinical.csv del repo (Anexo D)"
```

### 4c · Los tres untracked de decisión tuya

`CLAUDE.md.bak` no iría (es un backup). Los otros dos son documentación real:

```bash
git add DEUDA_TECNICA_Y_PRODUCCION.md HANDOFF_revision_final.md
git commit -m "docs: deuda técnica y handoff de revisión final"
```

Y para que el `.bak` no moleste más:

```bash
echo "*.bak" >> .gitignore && git add .gitignore && git commit -m "chore(git): ignorar backups"
```

---

## Paso 5 · Verificación antes de pushear

**Esta es la parte que no conviene saltear.**

```bash
# 1. ¿Se coló algún dato de paciente en lo que estás por subir?
git log origin/HEAD..HEAD --name-only --pretty=format: \
  | grep -Ei '\.xlsx$|^(raw|bronze|silver|events|states)/|clinical' | sort -u
#    Vacío = bien.

# 2. ¿Qué commits vas a subir?
git log --oneline origin/HEAD..HEAD

# 3. ¿Qué archivos, en total?
git diff --stat origin/HEAD..HEAD

# 4. ¿Quedó algo grande?
git diff --name-only origin/HEAD..HEAD | xargs -I{} du -h {} 2>/dev/null | sort -rh | head -5
```

Si los cuatro se ven bien:

```bash
git push
```

Y comprobar en el navegador que `tesis_cap/` muestra la versión de entrega y no la v64.

---

## Paso 6 · (OPCIONAL Y DESTRUCTIVO) Borrar `clinical.csv` de la historia

Solo si elegiste la opción **(c)** del Paso 0. Reescribe la historia y exige `--force`.

⚠ El repo es público: si alguien ya lo clonó o GitHub lo tiene cacheado, esto **no deshace la exposición**. Sirve para el futuro, no para el pasado.

```bash
# copia de seguridad primero, sin excepción
cd ~/Proyectos && cp -R PAC_v2 PAC_v2_backup_$(date +%Y%m%d)

pip install git-filter-repo --break-system-packages
cd PAC_v2
git filter-repo --path patients/clinical.csv --invert-paths --force
git remote add origin https://github.com/ri1965/PAC_v3.git   # filter-repo lo borra
git push --force origin main    # o master, según tu rama
```

Después, verificar que se fue:

```bash
git log --all --oneline -- patients/clinical.csv    # debe salir vacío
```

---

## Resumen de commits que quedarían

| # | Commit | Paso |
|---|---|---|
| 1 | `chore(git): excluir datos de examen y dejar solo la versión de entrega en tesis_cap` | 2 |
| 2 | `docs(tesis): versión de entrega; retira el intermedio v64` | 3 |
| 3 | `feat(qa): toolkit de auditoría de la tesis (39 controles + cifras canónicas)` | 4a |
| 4 | `docs: contexto de la tesis al día + figura ROC` | 4b |
| 5 | `chore(datos): retirar patients/clinical.csv del repo` | 4b, solo opción (b) |
| 6 | `docs: deuda técnica y handoff de revisión final` | 4c |
| 7 | `chore(git): ignorar backups` | 4c |

---

## Lo que NO hay que hacer

- ❌ `git add .` o `git add -A` — mete `exam_11585.xlsx` (1,4 MB de datos de examen) y `CLAUDE.md.bak`.
- ❌ `git add -f` sobre nada que no sea el archivo de la tesis. El `-f` existe para saltear el `.gitignore`, y ahí es donde se cuelan los datos.
- ❌ `git push --force` fuera del Paso 6.
- ❌ Commitear `gold/*.parquet`, `models/*.pkl` grandes o cualquier cosa de `raw/`, `bronze/`, `silver/`, `events/`, `states/` (ya están ignoradas: **no las designores**).
