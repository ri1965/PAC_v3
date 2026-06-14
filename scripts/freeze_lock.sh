#!/usr/bin/env bash
# Etapa 4.6 — Genera requirements.lock.txt con versiones exactas del venv activo.
#
# Para reproducibilidad de tesis. Correr desde el directorio raíz del repo
# con el venv activado:
#
#   source .venv/bin/activate
#   bash scripts/freeze_lock.sh
#
# Resultado: requirements.lock.txt versionado en git.
# Política: regenerar al cierre de cada Etapa relevante o antes de defensa.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK_FILE="$REPO_ROOT/requirements.lock.txt"
TMP_FILE="$(mktemp)"

# Verificar que estamos en un venv (sanity check)
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
    echo "ADVERTENCIA: no se detectó VIRTUAL_ENV activado."
    echo "Asegurate de haber corrido 'source .venv/bin/activate' antes."
    echo "Continuando de todos modos en 3 segundos (Ctrl+C para abortar)..."
    sleep 3
fi

PY_VERSION="$(python --version 2>&1)"
TIMESTAMP="$(date -Iseconds)"

# Header con metadata + freeze ordenado
{
    echo "# PAC_v2 — requirements.lock.txt"
    echo "# Generado por scripts/freeze_lock.sh"
    echo "# Timestamp: $TIMESTAMP"
    echo "# Python: $PY_VERSION"
    echo "# Venv: ${VIRTUAL_ENV:-no detectado}"
    echo "#"
    echo "# Versiones exactas para reproducibilidad. NO editar a mano —"
    echo "# regenerar con scripts/freeze_lock.sh desde el venv real."
    echo ""
    pip freeze | sort -f
} > "$TMP_FILE"

mv "$TMP_FILE" "$LOCK_FILE"

LINES="$(wc -l < "$LOCK_FILE")"
echo "OK — $LOCK_FILE generado ($LINES líneas)"
echo "    Stagear con: git add requirements.lock.txt"
