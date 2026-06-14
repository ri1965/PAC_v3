#!/usr/bin/env bash
# scripts/git_init_etapa_0.sh
# Corré este script UNA vez en tu Mac desde la carpeta raíz PAC_v2/
# para inicializar git y dejar el commit de baseline de Etapa 0.
#
# Uso:
#   cd "ruta/a/Proyecto APNEA-PAC/PAC_v2"
#   bash scripts/git_init_etapa_0.sh

set -euo pipefail

# 1) Limpiar un .git parcial que pueda haber quedado del sandbox
if [ -d ".git" ]; then
  echo "[INFO] .git existente detectado — lo remuevo antes de inicializar."
  rm -rf .git
fi

# 2) Init fresh
git init -b main -q

# 3) Config local (ajustá si querés usar otro mail/nombre)
git config user.email "robertoinza@gmail.com"
git config user.name "Roberto Inza"

# 4) Stage all (el .gitignore ya excluye raws, registry, bronze/silver/gold, reports, .DS_Store)
git add -A

# 5) Status antes del commit para inspección visual
echo ""
echo "=== git status ==="
git status --short
echo ""

# 6) Commit baseline
git commit -q -m "Etapa 0: scaffold + identidad + hygiene

- Scaffold medallion (raw/bronze/silver/gold/patients/reports)
- src/pac: config.py + io.py (parse_birthdate, parquet helpers)
- scripts/bootstrap_patient_files.py: one-shot CSV origen -> 3 archivos
- 12 pacientes cargados en patient_registry.csv + clinical.csv
- tests/test_parse_birthdate.py: 12 casos OK
- requirements.txt, .gitignore, README.md
- run.py: validador de scaffold (PASSED)

Decisiones cerradas:
- Salvador Martinez (687) -> 2009 confirmado manualmente
- Columna fumador removida (no hay origen de datos)
- Columna fecha_nacimiento_flag_audit removida del contrato
- Columna edad no persistida (se computa en Etapa 5)"

echo ""
echo "=== git log ==="
git log --oneline
echo ""
echo "[DONE] Baseline de Etapa 0 commiteada."
