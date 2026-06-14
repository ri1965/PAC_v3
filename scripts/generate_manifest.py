"""
Etapa 4.6 — Genera/actualiza models/MANIFEST.json.

El manifest es la fuente única de verdad sobre qué modelos están
activos, sobre qué corpus fueron entrenados, y con qué parámetros.
Es leído por:
  - scripts/retrain_check.py  (para detectar drift de corpus)
  - apply_pac_states.py       (para versionado en metadata KV)
  - la app                    (para inferencia frozen)
  - Gold                      (para incluir versión en metadatos por noche)

Uso:
    python scripts/generate_manifest.py              # genera v1 si no existe
    python scripts/generate_manifest.py --bump v2    # bumpea a v2 (post reentreno)
    python scripts/generate_manifest.py --force      # regenera v_actual sin bumpear
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

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"
STATES_DIR = REPO_ROOT / "states"
REPORTS_DIR = REPO_ROOT / "reports"
PATIENTS_DIR = REPO_ROOT / "patients"
MANIFEST_PATH = MODELS_DIR / "MANIFEST.json"

# Si pac/cohorts.py está disponible, lo usamos para tamaños de cohorte
sys.path.insert(0, str(REPO_ROOT / "src"))
try:
    from pac.cohorts import cohort_summary  # type: ignore

    _COHORTS_AVAILABLE = True
except Exception:
    _COHORTS_AVAILABLE = False


def _sha256(path: Path) -> str:
    """SHA256 de un archivo, hex truncado a 16 chars para legibilidad."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _git_sha() -> Optional[str]:
    """SHA del HEAD de git, o None si no estamos en un repo git."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()[:12]
    except Exception:
        return None


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _model_block(prefix: str, label: str) -> dict:
    """
    Construye el bloque de un modelo a partir de los archivos en models/
    con prefijo dado (ej. 'edo_morphotype' o 'pac_states_s').
    """
    metadata_path = MODELS_DIR / f"{prefix}_metadata.json"
    centroids_path = MODELS_DIR / f"{prefix}_centroids.csv"
    zscore_path = MODELS_DIR / f"{prefix}_zscore.json"
    pkl_path = MODELS_DIR / f"{prefix}_kmeans.pkl"

    if not metadata_path.exists():
        raise FileNotFoundError(f"No se encontró metadata: {metadata_path}")
    if not centroids_path.exists():
        raise FileNotFoundError(f"No se encontraron centroides: {centroids_path}")

    md = _load_json(metadata_path)

    block = {
        "label": label,
        "type": "kmeans",
        "k": md.get("k"),
        "n_training": md.get("n_training"),
        "random_state": md.get("random_state"),
        "schema_version": md.get("schema_version"),
        "algorithm_version": md.get("algorithm_version"),
        "feature_cols": md.get("feature_cols"),
        "training_mask": md.get("training_mask"),
        "labels": md.get("greek_letters") or md.get("state_labels"),
        "centroids_path": str(centroids_path.relative_to(REPO_ROOT)),
        "centroids_sha256_short": _sha256(centroids_path),
        "metadata_path": str(metadata_path.relative_to(REPO_ROOT)),
    }
    if zscore_path.exists():
        block["zscore_path"] = str(zscore_path.relative_to(REPO_ROOT))
        block["zscore_sha256_short"] = _sha256(zscore_path)
    if pkl_path.exists():
        block["kmeans_pkl_path"] = str(pkl_path.relative_to(REPO_ROOT))
        block["kmeans_pkl_sha256_short"] = _sha256(pkl_path)

    return block


def _corpus_snapshot() -> dict:
    """Resumen del corpus: pacientes, noches, cohortes."""
    snap: dict = {
        "states_dir": str(STATES_DIR.relative_to(REPO_ROOT)),
        "n_state_files": 0,
        "first_nr": None,
        "last_nr": None,
    }
    if STATES_DIR.exists():
        nr_files = sorted(STATES_DIR.glob("NR_*.parquet"))
        snap["n_state_files"] = len(nr_files)
        if nr_files:
            snap["first_nr"] = nr_files[0].stem
            snap["last_nr"] = nr_files[-1].stem

    # Patient count via silver_qc_summary
    silver_qc = REPORTS_DIR / "silver_qc_summary.csv"
    if silver_qc.exists():
        import pandas as pd

        df = pd.read_csv(silver_qc, usecols=["user_id"])
        snap["n_patients"] = int(df["user_id"].nunique())
        snap["n_silver_qc_rows"] = int(len(df))

    if _COHORTS_AVAILABLE:
        snap["cohort_sizes"] = cohort_summary()
    return snap


def _exclusion_lists() -> dict:
    """Lista de exclusiones aplicadas/recomendadas para el corpus."""
    out: dict = {}
    b2 = REPORTS_DIR / "b2_fail_excluded.json"
    if b2.exists():
        out["b2_fail_excluded"] = {
            "path": str(b2.relative_to(REPO_ROOT)),
            "n": len(_load_json(b2).get("night_record_ids", [])),
            "policy": "exclusión obligatoria en análisis (silver_qc fail confirmado)",
        }
    review = REPORTS_DIR / "pac_states_flag_for_review.csv"
    if review.exists():
        import pandas as pd

        df = pd.read_csv(review)
        out["flag_for_review"] = {
            "path": str(review.relative_to(REPO_ROOT)),
            "n": int(len(df)),
            "policy": "atención reducida o cohorte separada (B3 dominance ∪ B4 outliers)",
        }
    return out


def build_manifest(model_version: str = "v1") -> dict:
    """Construye el manifest completo a partir del estado actual del repo."""
    manifest = {
        "manifest_version": "1.0",
        "model_version": model_version,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "notes": (
            f"Versión {model_version} de los modelos congelados de PAC_v2. "
            f"Generado por scripts/generate_manifest.py. "
            "Defensa de tesis usa esta versión salvo bump explícito."
        ),
        "corpus_snapshot": _corpus_snapshot(),
        "models": {
            "morphotypes": _model_block("edo_morphotype", "Morfotipos α/β/γ/δ (Etapa 3b)"),
            "pac_states_s": _model_block("pac_states_s", "PAC States escala s (30s)"),
            "pac_states_m": _model_block("pac_states_m", "PAC States escala m (5min)"),
            "pac_states_l": _model_block("pac_states_l", "PAC States escala l (30min)"),
        },
        "k_per_scale_pac_states": {"s": 6, "m": 8, "l": 6},
        "exclusion_lists": _exclusion_lists(),
        "retrain_policy": {
            "trigger_threshold_new_nights": 100,
            "trigger_threshold_new_patients": 10,
            "k_decision_on_retrain": (
                "El sweep se re-ejecuta. Si las K sugeridas difieren de las "
                "actuales, el orquestador pregunta si aceptar (versión "
                "best-fit) o mantener (versión incremental). Default: "
                "mantener para versiones post-tesis, ofrecer cambio para "
                "versiones de investigación."
            ),
        },
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bump",
        type=str,
        default=None,
        help="Bumpear a esta versión (ej: v2). Si se omite, usa v1 si no existe manifest, o conserva la versión actual.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerar el manifest aunque ya exista en la versión actual.",
    )
    args = parser.parse_args()

    if MANIFEST_PATH.exists() and not args.force and not args.bump:
        existing = _load_json(MANIFEST_PATH)
        print(
            f"Ya existe MANIFEST.json (model_version={existing.get('model_version')}). "
            "Pasá --force para regenerar o --bump vN para nueva versión."
        )
        return 1

    if args.bump:
        version = args.bump
    else:
        version = (
            _load_json(MANIFEST_PATH).get("model_version", "v1")
            if MANIFEST_PATH.exists()
            else "v1"
        )

    manifest = build_manifest(model_version=version)

    MODELS_DIR.mkdir(exist_ok=True)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"OK — {MANIFEST_PATH.relative_to(REPO_ROOT)} generado")
    print(f"    model_version: {manifest['model_version']}")
    print(f"    git_sha:       {manifest['git_sha']}")
    print(f"    n_state_files: {manifest['corpus_snapshot']['n_state_files']}")
    print(f"    n_patients:    {manifest['corpus_snapshot'].get('n_patients', '?')}")
    print(f"    models:        {list(manifest['models'].keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
