#!/usr/bin/env python3
"""
Launcher de Etapa 1 Bronze — no requiere PYTHONPATH.

Uso:
  python scripts/run_bronze.py              # procesa todo raw/*.xlsx
  python scripts/run_bronze.py --limit 20   # smoke test primeros 20

Equivalente a `PYTHONPATH=src python -m pac.bronze` pero evita el error de
bootstrap de Python 3.12 + macOS + conda con PYTHONPATH relativo.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Agregar src/ al sys.path ANTES de importar nada de pac
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.bronze import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
