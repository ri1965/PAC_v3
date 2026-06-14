"""
Etapa 4.6 — Retrain gateway.

Compara el inventario actual del corpus contra el snapshot guardado en
models/MANIFEST.json y, si supera el umbral de reentreno, ofrece
disparar el ciclo de retrain. NUNCA reentrena sin confirmación
explícita del usuario.

Uso:
    python scripts/retrain_check.py            # interactivo (prompt y/N)
    python scripts/retrain_check.py --json     # solo reporta, no pregunta
    python scripts/retrain_check.py --auto-yes # asume yes (CI/automatizado)
    python scripts/retrain_check.py --dry-run  # muestra plan, no ejecuta

Política:
- Modelos congelados como v1. Reentreno produce v2 (manual via --bump).
- El retrain corre: train_morphotypes → train_pac_states → apply →
  qa_pac_states_batch (todos vía subprocess).
- En las decisiones de K, el script muestra el sweep nuevo y deja al
  usuario decidir si acepta nueva K o mantiene la anterior (default
  para tesis: mantener).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "models" / "MANIFEST.json"
STATES_DIR = REPO_ROOT / "states"
SILVER_QC_SUMMARY = REPO_ROOT / "reports" / "silver_qc_summary.csv"

DEFAULT_THRESHOLD_NIGHTS = 100
DEFAULT_THRESHOLD_PATIENTS = 10


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No existe {MANIFEST_PATH}. Generar primero con "
            "scripts/generate_manifest.py"
        )
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def _current_inventory() -> dict:
    """Inventario actual: archivos en states/ + pacientes únicos en silver_qc."""
    n_state_files = (
        len(list(STATES_DIR.glob("NR_*.parquet"))) if STATES_DIR.exists() else 0
    )
    n_patients: Optional[int] = None
    if SILVER_QC_SUMMARY.exists():
        import pandas as pd

        df = pd.read_csv(SILVER_QC_SUMMARY, usecols=["user_id"])
        n_patients = int(df["user_id"].nunique())
    return {
        "n_state_files": n_state_files,
        "n_patients": n_patients,
    }


def _diff_against_snapshot(inv: dict, manifest: dict) -> dict:
    """Calcula deltas vs snapshot del manifest."""
    snap = manifest.get("corpus_snapshot", {})
    snap_n_files = snap.get("n_state_files", 0)
    snap_n_pat = snap.get("n_patients", 0)
    return {
        "snapshot_n_state_files": snap_n_files,
        "snapshot_n_patients": snap_n_pat,
        "current_n_state_files": inv["n_state_files"],
        "current_n_patients": inv["n_patients"],
        "delta_n_state_files": inv["n_state_files"] - snap_n_files,
        "delta_n_patients": (
            (inv["n_patients"] - snap_n_pat) if inv["n_patients"] is not None else None
        ),
    }


def _decide_trigger(diff: dict, t_nights: int, t_patients: int) -> dict:
    """¿Hay drift suficiente para sugerir retrain?"""
    triggers = []
    if diff["delta_n_state_files"] >= t_nights:
        triggers.append(
            f"noches nuevas ({diff['delta_n_state_files']}) ≥ umbral ({t_nights})"
        )
    if (
        diff["delta_n_patients"] is not None
        and diff["delta_n_patients"] >= t_patients
    ):
        triggers.append(
            f"pacientes nuevos ({diff['delta_n_patients']}) ≥ umbral ({t_patients})"
        )
    return {"should_retrain": len(triggers) > 0, "reasons": triggers}


def _print_human_report(manifest: dict, diff: dict, decision: dict) -> None:
    print("=" * 70)
    print("PAC_v2 — Retrain gateway")
    print("=" * 70)
    print(f"Manifest activo:   {manifest.get('model_version', '?')}")
    print(f"Generado:          {manifest.get('generated_at', '?')}")
    print(f"git_sha:           {manifest.get('git_sha', '?')}")
    print()
    print("Snapshot del corpus al entrenar:")
    print(f"  - noches:    {diff['snapshot_n_state_files']}")
    print(f"  - pacientes: {diff['snapshot_n_patients']}")
    print()
    print("Inventario actual:")
    print(f"  - noches:    {diff['current_n_state_files']}")
    print(f"  - pacientes: {diff['current_n_patients']}")
    print()
    print("Deltas:")
    print(f"  - noches:    +{diff['delta_n_state_files']}")
    if diff["delta_n_patients"] is not None:
        print(f"  - pacientes: +{diff['delta_n_patients']}")
    print()
    print(f"Decisión: {'⚠ SUGERIR RETRAIN' if decision['should_retrain'] else '✓ no es necesario reentrenar'}")
    if decision["reasons"]:
        for r in decision["reasons"]:
            print(f"  - {r}")
    print("=" * 70)


def _ask_yes_no(prompt: str, default: str = "n") -> bool:
    """Prompt yes/no en consola. default='n' por seguridad."""
    suffix = " [y/N] " if default == "n" else " [Y/n] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default == "y"
    return ans in ("y", "yes", "s", "si", "sí")


def _run_retrain_pipeline(dry_run: bool) -> int:
    """
    Ejecuta el ciclo de retrain. NO bumpea manifest automáticamente —
    el usuario lo hace explícitamente con generate_manifest.py --bump
    una vez que está conforme con los resultados.
    """
    steps = [
        ("Re-train morfotipos (Etapa 3b)", ["python", "scripts/train_morphotypes.py"]),
        ("Re-train PAC States (Etapa 4 paso 5)", ["python", "scripts/train_pac_states.py"]),
        ("Validate PAC States", ["python", "scripts/validate_pac_states.py"]),
        ("Apply morfotipos (events/)", ["python", "scripts/apply_morphotypes.py"]),
        ("Apply PAC States batch (states/)", ["python", "scripts/apply_pac_states.py", "--mode", "batch"]),
        ("QA PAC States batch", ["python", "scripts/qa_pac_states_batch.py"]),
    ]
    print()
    print("Plan de retrain:")
    for i, (label, cmd) in enumerate(steps, 1):
        print(f"  {i}. {label}")
        print(f"     $ {' '.join(cmd)}")
    print()
    if dry_run:
        print("--dry-run: no se ejecuta ningún paso.")
        return 0

    env_hint = "PYTHONPATH=src "
    print("NOTA: cada paso se ejecuta con PYTHONPATH=src cwd=repo_root.")
    print()

    for i, (label, cmd) in enumerate(steps, 1):
        print(f"[{i}/{len(steps)}] {label}")
        try:
            res = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                env={**__import__("os").environ, "PYTHONPATH": "src"},
            )
            if res.returncode != 0:
                print(f"  ✗ paso {i} falló (returncode={res.returncode}). Abortando.")
                return res.returncode
            print(f"  ✓ paso {i} OK")
        except Exception as e:
            print(f"  ✗ paso {i} excepción: {e}")
            return 1

    print()
    print("Retrain completo. Próximos pasos manuales:")
    print("  1. Revisar reports/pac_states_sweep.json — ¿K cambia?")
    print("  2. Revisar reports/pac_states_validation.md")
    print("  3. Revisar reports/pac_states_apply_qa.md")
    print("  4. Si todo OK, bumpear manifest:")
    print("       python scripts/generate_manifest.py --bump v2")
    print("  5. Commitear nuevos centroides + nuevo MANIFEST.json")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold-nights",
        type=int,
        default=DEFAULT_THRESHOLD_NIGHTS,
        help=f"Umbral de noches nuevas para sugerir retrain (default {DEFAULT_THRESHOLD_NIGHTS}).",
    )
    parser.add_argument(
        "--threshold-patients",
        type=int,
        default=DEFAULT_THRESHOLD_PATIENTS,
        help=f"Umbral de pacientes nuevos para sugerir retrain (default {DEFAULT_THRESHOLD_PATIENTS}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Salida JSON (no interactivo, no ejecuta retrain).",
    )
    parser.add_argument(
        "--auto-yes",
        action="store_true",
        help="Asume yes al prompt (CI/automatizado).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el plan de retrain pero no ejecuta los scripts.",
    )
    args = parser.parse_args()

    manifest = _load_manifest()
    inv = _current_inventory()
    diff = _diff_against_snapshot(inv, manifest)
    decision = _decide_trigger(
        diff, t_nights=args.threshold_nights, t_patients=args.threshold_patients
    )

    if args.json:
        print(
            json.dumps(
                {
                    "manifest_version": manifest.get("model_version"),
                    "diff": diff,
                    "decision": decision,
                },
                indent=2,
            )
        )
        return 0

    _print_human_report(manifest, diff, decision)

    if not decision["should_retrain"]:
        return 0

    proceed = args.auto_yes or _ask_yes_no(
        "\n¿Lanzar pipeline de retrain ahora?", default="n"
    )
    if not proceed:
        print("Retrain pospuesto. Re-correr cuando se decida.")
        return 0

    return _run_retrain_pipeline(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
