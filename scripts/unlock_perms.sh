#!/usr/bin/env bash
# scripts/unlock_perms.sh
# -----------------------------------------------------------------------------
# Limpia xattrs que Cowork (o Finder/iCloud) aplica a archivos en ~/Documents y
# que a veces bloquean `python` nativo de Terminal con "Operation not permitted".
#
# Es seguro: `xattr -c` sólo borra metadata, no el contenido.
# Corré este script después de cada sesión de Cowork, desde la raíz PAC_v2/.
#
# Uso:
#   bash scripts/unlock_perms.sh
#
# Qué hace:
#   1) Lista xattrs actuales en archivos clave (diagnóstico).
#   2) Limpia recursivo en src/, scripts/, tests/, y *.py del root.
#   3) Re-lista para confirmar limpieza.
# -----------------------------------------------------------------------------

set -u

echo "=== unlock_perms.sh ==="
echo "pwd: $(pwd)"
echo ""

# ----- Diagnóstico pre-limpieza ---------------------------------------------
echo "--- xattrs ANTES ---"
for f in run.py scripts/run_bronze.py scripts/bootstrap_patient_files.py \
         src/pac/config.py src/pac/bronze.py src/pac/ingest.py; do
  if [ -f "$f" ]; then
    xa=$(xattr "$f" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    if [ -n "$xa" ]; then
      echo "  $f  →  $xa"
    else
      echo "  $f  →  (sin xattrs)"
    fi
  fi
done
echo ""

# ----- Limpieza -------------------------------------------------------------
echo "--- limpieza (xattr -rc) ---"
targets=(src scripts tests run.py requirements.txt README.md .gitignore)
for t in "${targets[@]}"; do
  if [ -e "$t" ]; then
    xattr -rc "$t" 2>/dev/null && echo "  cleared: $t" || echo "  WARN   : $t (ignorado)"
  fi
done
echo ""

# ----- Permisos (por las dudas) ---------------------------------------------
chmod -R u+rwX src scripts tests 2>/dev/null || true
chmod u+rw run.py requirements.txt README.md 2>/dev/null || true

# ----- Diagnóstico post-limpieza -------------------------------------------
echo "--- xattrs DESPUÉS ---"
for f in run.py scripts/run_bronze.py scripts/bootstrap_patient_files.py \
         src/pac/config.py src/pac/bronze.py src/pac/ingest.py; do
  if [ -f "$f" ]; then
    xa=$(xattr "$f" 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    if [ -n "$xa" ]; then
      echo "  $f  →  $xa"
    else
      echo "  $f  →  clean"
    fi
  fi
done

echo ""
echo "[DONE] Ahora probá:"
echo "  python scripts/run_bronze.py --limit 3"
