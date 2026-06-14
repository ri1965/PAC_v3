"""
PAC_v2 — Orquestador incremental (Etapa 6) — CLI

Detecta qué etapas del pipeline están stale (por mtime de inputs vs
outputs) y las ejecuta en orden. Diseño híbrido: un solo script con
sub-comandos para los tres usos típicos, más un default sensato.

Uso:
  python scripts/orchestrate.py                # = `plan` + prompt y/N
  python scripts/orchestrate.py status         # solo inventario, no ejecuta
  python scripts/orchestrate.py status -v      # con detalle de NRs stale
  python scripts/orchestrate.py plan           # imprime plan, no ejecuta
  python scripts/orchestrate.py run            # ejecuta tras prompt y/N
  python scripts/orchestrate.py run --yes      # ejecuta sin prompt (CI)
  python scripts/orchestrate.py run --dry-run  # imprime plan sin ejecutar (alias de plan)

Política de detección:
  - mtime de archivos para staleness intra-pipeline.
  - Reentrenamientos detectados automáticamente porque tocan los mtimes
    de models/* (no requiere comparar versiones explícitamente).
  - Bronze (raw → bronze) NO está cubierto: el naming raw es arbitrario,
    el NR se calcula del contenido. Para nuevas xlsx, correr antes:
        python scripts/run_bronze.py

Limitación conocida:
  Los scripts silver/events son batch-full (procesan todos los NRs).
  El orquestador detecta stale por NR para diagnóstico, pero al
  ejecutar corre el script entero. Mejora futura: agregar `--only-stale`
  a esos scripts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pac.orchestrator import (  # noqa: E402
    _morpho_models_exist,
    _pac_states_models_exist,
    compute_plan,
    detect_all,
    render_plan_text,
    render_status_text,
)


def _ask_yes_no(prompt: str, default: str = "n") -> bool:
    suffix = " [y/N] " if default == "n" else " [Y/n] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default == "y"
    return ans in ("y", "yes", "s", "si", "sí")


def _run_plan(plan: List[dict], quiet: bool = False) -> int:
    """Ejecuta el plan paso por paso, abort si alguno falla."""
    if not plan:
        if not quiet:
            print("Plan vacío — nada para ejecutar.")
        return 0

    env = {**os.environ, "PYTHONPATH": "src"}
    t0 = time.time()
    for i, step in enumerate(plan, 1):
        cmd = step["cmd"]
        if not quiet:
            print()
            print(f"[{i}/{len(plan)}] {step['stage']} — {step['label']}")
            print(f"  $ {' '.join(cmd)}")
        ts = time.time()
        try:
            res = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
        except Exception as e:
            print(f"  ✗ paso {i} excepción: {e}")
            return 1
        if res.returncode != 0:
            print(f"  ✗ paso {i} falló (rc={res.returncode}). Abortando.")
            return res.returncode
        if not quiet:
            print(f"  ✓ paso {i} OK ({time.time() - ts:.1f}s)")

    if not quiet:
        print()
        print(f"✓ Pipeline completo — {time.time() - t0:.1f}s total")
    return 0


# --------------------------------------------------------------------- #
# Sub-comandos
# --------------------------------------------------------------------- #


def cmd_status(args: argparse.Namespace) -> int:
    """Inventario rápido — no toca nada."""
    status = detect_all()
    print(render_status_text(status, verbose=args.verbose))
    return 0 if status.is_clean else 1


def cmd_plan(args: argparse.Namespace) -> int:
    """Imprime status + plan, no pregunta ni ejecuta."""
    status = detect_all()
    print(render_status_text(status, verbose=args.verbose))
    print()
    plan = compute_plan(status)
    print(render_plan_text(plan))
    return 0 if status.is_clean else 1


def _ask_retrain(status, dry_run: bool, yes: bool) -> tuple[bool, bool]:
    """Pregunta si re-entrenar morfotipos y/o PAC states cuando hay datos nuevos.

    Solo pregunta cuando:
      - El modelo ya existe (no es bootstrap).
      - Hay etapas stale que implican datos nuevos (events o states).
      - No es --dry-run ni --yes (modo interactivo).

    Devuelve (retrain_morpho, retrain_states).
    """
    if dry_run or yes:
        return False, False

    needs_events = (
        status.stages["silver"].is_stale_global
        or status.stages["events"].is_stale_global
    )
    needs_states = needs_events or status.stages["states"].is_stale_global

    retrain_morpho = False
    retrain_states = False

    if _morpho_models_exist() and needs_events:
        print()
        print("ℹ  Hay datos nuevos y ya existe un modelo de morfotipos.")
        retrain_morpho = _ask_yes_no(
            "   ¿Re-entrenar morfotipos con todos los datos actualizados?",
            default="n",
        )

    if _pac_states_models_exist() and needs_states:
        print()
        print("ℹ  Hay datos nuevos y ya existen modelos de PAC states.")
        retrain_states = _ask_yes_no(
            "   ¿Re-entrenar PAC states con todos los datos actualizados?",
            default="n",
        )

    return retrain_morpho, retrain_states


def cmd_run(args: argparse.Namespace) -> int:
    """Ejecuta el plan. Prompt y/N salvo --yes."""
    status = detect_all()
    print(render_status_text(status, verbose=False))

    # Preguntar por re-entrenamiento antes de armar el plan final.
    retrain_morpho, retrain_states = _ask_retrain(status, args.dry_run, args.yes)

    plan = compute_plan(status, retrain_morpho=retrain_morpho, retrain_states=retrain_states)
    print()
    print(render_plan_text(plan))

    if not plan:
        return 0

    if args.dry_run:
        print()
        print("--dry-run: no se ejecuta.")
        return 0

    print()
    if not args.yes:
        if not _ask_yes_no("¿Ejecutar el plan?", default="n"):
            print("Abortado por el usuario.")
            return 0

    return _run_plan(plan, quiet=args.quiet)


def cmd_default(args: argparse.Namespace) -> int:
    """Default sin sub-comando: equivalente a `run` (con prompt)."""
    return cmd_run(args)


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command")

    # status
    p_status = sub.add_parser("status", help="Inventario sin ejecutar nada.")
    p_status.add_argument("-v", "--verbose", action="store_true",
                          help="Mostrar primeros NRs stale por etapa.")
    p_status.set_defaults(func=cmd_status)

    # plan
    p_plan = sub.add_parser("plan", help="Imprime status + plan, no ejecuta.")
    p_plan.add_argument("-v", "--verbose", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    # run
    p_run = sub.add_parser("run", help="Ejecuta el plan tras prompt y/N.")
    p_run.add_argument("--yes", action="store_true",
                       help="Auto-confirmar (CI/automatizado).")
    p_run.add_argument("--dry-run", action="store_true",
                       help="Imprime plan sin ejecutar (alias de plan).")
    p_run.add_argument("--quiet", action="store_true",
                       help="Suprime output detallado durante ejecución.")
    p_run.set_defaults(func=cmd_run)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        # Default: equivalente a `run` interactivo.
        # Necesitamos namespace con los flags que cmd_run espera.
        ns = argparse.Namespace(yes=False, dry_run=False, quiet=False)
        return cmd_default(ns)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
