"""
Etapa 5 paso 7a — Build gold/MANIFEST.json.

Sidecar que documenta el snapshot de Gold:
  - Versión activa de modelo (apunta a models/MANIFEST.json).
  - Lista de las 5 tablas gold con SHA256 truncado, n_rows, n_cols.
  - git_sha del HEAD.
  - Política de cohorte aplicada (B — todas con flags).
  - Build order canónico.

Generado al final del pipeline Gold (después de build_*_gold.py × 5).
Versionado en git como fuente de verdad de qué se entregó.

Uso:
  python scripts/build_gold_manifest.py            # genera/regenera
  python scripts/build_gold_manifest.py --dry-run  # imprime, no escribe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = REPO_ROOT / "gold"
MODELS_MANIFEST = REPO_ROOT / "models" / "MANIFEST.json"
OUT_PATH = GOLD_DIR / "MANIFEST.json"

# Build order canónico — refleja dependencias entre tablas.
BUILD_ORDER = ["events", "events_curves", "states", "nights", "patients"]


def _sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _git_sha() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()[:12]
    except Exception:
        return None


def _table_block(name: str, path: Path) -> dict:
    if not path.exists():
        return {
            "path": str(path.relative_to(REPO_ROOT)),
            "missing": True,
        }
    pq_meta = pq.read_metadata(path)
    n_rows = int(pq_meta.num_rows)
    n_cols = int(pq_meta.num_columns)
    size_bytes = path.stat().st_size
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "n_rows": n_rows,
        "n_cols": n_cols,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 3),
        "sha256_short": _sha256_short(path),
    }


def build_manifest() -> dict:
    if not MODELS_MANIFEST.exists():
        raise FileNotFoundError(
            f"No existe {MODELS_MANIFEST}. Generar con scripts/generate_manifest.py"
        )
    with open(MODELS_MANIFEST) as f:
        models_md = json.load(f)

    tables = {}
    for name in BUILD_ORDER:
        path = GOLD_DIR / f"{name}.parquet"
        tables[name] = _table_block(name, path)

    manifest = {
        "manifest_version": "1.0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "model_manifest_path": str(MODELS_MANIFEST.relative_to(REPO_ROOT)),
        "model_version": models_md.get("model_version"),
        "tables": tables,
        "build_order": BUILD_ORDER,
        "cohort_policy": (
            "B — todas las noches con flags (in_quality, in_strict, "
            "in_high_tst, flag_for_review, b2_fail). Las cross-night "
            "_pct_corpus se computan SOBRE in_quality como referencia."
        ),
        "n_tables": len(tables),
        "n_tables_present": sum(1 for t in tables.values() if not t.get("missing")),
        "notes": (
            "Sidecar versionado en git. SHA256 truncado a 16 chars para "
            "trazabilidad. Regenerar con scripts/build_gold_manifest.py "
            "después de cualquier rebuild de Gold."
        ),
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Imprime, no escribe.")
    args = parser.parse_args()

    manifest = build_manifest()

    if args.dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        print("\n--dry-run: NO escribo gold/MANIFEST.json")
        return 0

    GOLD_DIR.mkdir(exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"OK — {OUT_PATH.relative_to(REPO_ROOT)} generado")
    print(f"  model_version:    {manifest['model_version']}")
    print(f"  git_sha:          {manifest['git_sha']}")
    print(f"  tables presentes: {manifest['n_tables_present']}/{manifest['n_tables']}")
    for name in BUILD_ORDER:
        t = manifest["tables"][name]
        if t.get("missing"):
            print(f"    ✗ {name}: MISSING")
        else:
            print(
                f"    ✓ {name:15s}: {t['n_rows']:>8,} rows × {t['n_cols']:>3} cols  "
                f"({t['size_mb']:>6.2f} MB)  sha={t['sha256_short']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
