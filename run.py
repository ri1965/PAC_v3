#!/usr/bin/env python3
"""
PAC_v2 — Front door único del pipeline.

Wrapper fino sobre los scripts existentes (scripts/run_bronze.py,
scripts/orchestrate.py). Inyecta PYTHONPATH=src automáticamente y
unifica los flujos típicos detrás de subcomandos.

Uso:
  python run.py                # AUTO: si hay xlsx nuevos en raw/, propone
                               #       ingest; después corre orquestador
                               #       interactivo (status + plan + y/N).
  python run.py status         # Inventario sin ejecutar nada.
  python run.py plan           # Plan sin ejecutar.
  python run.py ingest         # Solo raw → bronze (run_bronze.py).
  python run.py update         # Solo orquestador (silver/events/states/gold).
                               # No toca bronze.
  python run.py all [--yes]    # ingest + orquestador, todo, en una.
  python run.py validate       # Sanity check del scaffold (dirs + identity).
  python run.py --help         # Ayuda completa.

Diseño:
  - Cada subcomando es un wrapper fino sobre un script existente.
    No duplica lógica.
  - `update` y `all` delegan en scripts/orchestrate.py — ese script ya
    tiene su propia lógica de detección de staleness y plan.
  - `ingest` delega en scripts/run_bronze.py.
  - El default (sin subcomando) es la combinación más útil: detecta
    xlsx pendientes → ingest si corresponde → orquestador interactivo.

Si algún día querés correr los scripts originales directo (con flags
exóticos no expuestos acá), todos siguen funcionando como antes.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
RAW_DIR = PROJECT_ROOT / "raw"
BRONZE_DIR = PROJECT_ROOT / "bronze"

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
RUN_BRONZE = SCRIPTS_DIR / "run_bronze.py"
ORCHESTRATE = SCRIPTS_DIR / "orchestrate.py"


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _env_with_pythonpath() -> dict:
    """Devuelve un env con PYTHONPATH=src sin pisar otros valores."""
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    return env


def _run(cmd: Sequence[str]) -> int:
    """Ejecuta un subprocess en cwd=PROJECT_ROOT con PYTHONPATH=src.

    Imprime el comando antes de correrlo para que el usuario sepa qué
    está pasando, y propaga el returncode.
    """
    print(f"  $ {' '.join(cmd)}", flush=True)
    sys.stdout.flush()
    try:
        res = subprocess.run(list(cmd), cwd=PROJECT_ROOT, env=_env_with_pythonpath())
    except FileNotFoundError as e:
        print(f"  ✗ no se encontró el ejecutable: {e}")
        return 127
    except KeyboardInterrupt:
        print("  ✗ interrumpido por el usuario.")
        return 130
    return res.returncode


def _ask_yes_no(prompt: str, default: str = "n") -> bool:
    """Prompt y/N con default. Maneja Ctrl-C / EOF como "no"."""
    suffix = " [y/N] " if default == "n" else " [Y/n] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return default == "y"
    return ans in ("y", "yes", "s", "si", "sí")


def _count_raw_xlsx() -> int:
    if not RAW_DIR.exists():
        return 0
    return len(list(RAW_DIR.glob("*.xlsx")))


def _count_bronze_nrs() -> int:
    """Cuenta NR_*.parquet (excluye sidecars _classical)."""
    if not BRONZE_DIR.exists():
        return 0
    return len([
        p for p in BRONZE_DIR.glob("NR_*.parquet")
        if not p.stem.endswith("_classical")
    ])


def _bronze_pending() -> int:
    """Devuelve cuántos xlsx parecen no haber sido ingestados.

    Heurística simple: count(raw/*.xlsx) − count(bronze/NR_*.parquet).
    No es exacta (xlsx malformados pueden inflar el delta), pero
    funciona como señal de "hay trabajo pendiente". Negativo se
    redondea a 0.
    """
    delta = _count_raw_xlsx() - _count_bronze_nrs()
    return max(delta, 0)


# --------------------------------------------------------------------- #
# Subcomandos
# --------------------------------------------------------------------- #


def cmd_status(args: argparse.Namespace) -> int:
    """Inventario completo: bronze coverage + estado del orquestador."""
    n_raw = _count_raw_xlsx()
    n_bronze = _count_bronze_nrs()
    pending = _bronze_pending()

    print("=" * 70)
    print("PAC_v2 — run.py status")
    print("=" * 70)
    print(f"Bronze coverage:")
    print(f"  raw/*.xlsx           {n_raw}")
    print(f"  bronze/NR_*.parquet  {n_bronze}")
    if pending > 0:
        print(f"  ⚠  pending ingest    ~{pending}  → correr `python run.py ingest`")
    else:
        print(f"  ✓  bronze al día")
    print()

    cmd = ["python", str(ORCHESTRATE), "status"]
    if args.verbose:
        cmd.append("-v")
    rc = _run(cmd)
    return rc


def cmd_plan(args: argparse.Namespace) -> int:
    """Plan del orquestador (silver+events+states+gold), sin ejecutar."""
    cmd = ["python", str(ORCHESTRATE), "plan"]
    if args.verbose:
        cmd.append("-v")
    return _run(cmd)


def cmd_ingest(args: argparse.Namespace) -> int:
    """raw → bronze. Wrapper fino sobre scripts/run_bronze.py."""
    cmd = ["python", str(RUN_BRONZE)]
    if args.limit is not None:
        cmd += ["--limit", str(args.limit)]
    if args.no_autoreg:
        cmd.append("--no-autoreg")
    return _run(cmd)


def cmd_update(args: argparse.Namespace) -> int:
    """Solo orquestador: silver/events/states/gold. No toca bronze."""
    cmd = ["python", str(ORCHESTRATE), "run"]
    if args.yes:
        cmd.append("--yes")
    if args.dry_run:
        cmd.append("--dry-run")
    if args.quiet:
        cmd.append("--quiet")
    return _run(cmd)


def cmd_all(args: argparse.Namespace) -> int:
    """Pipeline completo end-to-end: ingest + orquestador."""
    print("[1/2] Ingest raw → bronze")
    rc = cmd_ingest(args)
    if rc != 0:
        print(f"\n✗ ingest falló (rc={rc}). Abortando antes del orquestador.")
        return rc

    print("\n[2/2] Orquestador (silver/events/states/gold)")
    return cmd_update(args)


def cmd_validate(args: argparse.Namespace) -> int:
    """Sanity check del scaffold + identidad. (Lo que hacía el run.py viejo.)"""
    sys.path.insert(0, str(SRC_DIR))
    try:
        from pac.config import (  # noqa: E402
            BRONZE_DIR as CFG_BRONZE,
            CLINICAL_CSV,
            GOLD_DIR as CFG_GOLD,
            PATIENT_REGISTRY_CSV,
            RAW_DIR as CFG_RAW,
            REPORTS_DIR as CFG_REPORTS,
            SILVER_DIR as CFG_SILVER,
            as_dict,
            ensure_dirs,
        )
        from pac.io import (  # noqa: E402
            read_clinical,
            read_patient_registry,
        )
    except Exception as e:
        print(f"✗ no se pudo importar pac.config / pac.io: {e}")
        return 1

    def _check(label: str, ok: bool, detail: str = "") -> bool:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
        return ok

    print("=" * 60)
    print("PAC_v2 — validación de scaffold")
    print("=" * 60)

    ensure_dirs()
    cfg = as_dict()
    print(f"project_root: {cfg['project_root']}\n")

    print("Directorios:")
    dirs_ok = all([
        _check("raw/",     CFG_RAW.is_dir()),
        _check("bronze/",  CFG_BRONZE.is_dir()),
        _check("silver/",  CFG_SILVER.is_dir()),
        _check("gold/",    CFG_GOLD.is_dir()),
        _check("reports/", CFG_REPORTS.is_dir()),
    ])

    print("\nIdentidad:")
    reg_ok = _check("patients/patient_registry.csv", PATIENT_REGISTRY_CSV.exists())
    cli_ok = _check("patients/clinical.csv",         CLINICAL_CSV.exists())

    if reg_ok:
        reg = read_patient_registry()
        print(f"         registry: {len(reg)} paciente(s)")
    if cli_ok:
        cli = read_clinical()
        print(f"         clinical: {len(cli)} fila(s)")

    print("\nCoherencia registry ↔ clinical:")
    if reg_ok and cli_ok:
        reg_ids = set(reg["patient_id"].astype(str))
        cli_ids = set(cli["patient_id"].astype(str))
        only_reg = reg_ids - cli_ids
        only_cli = cli_ids - reg_ids
        _check("patient_id consistentes",
               not only_reg and not only_cli,
               f"solo_registry={sorted(only_reg) or '-'} "
               f"solo_clinical={sorted(only_cli) or '-'}")

    print("\nRaws:")
    n_raw = _count_raw_xlsx()
    if n_raw == 0:
        print("         (raw/ vacío)")
    else:
        print(f"         total .xlsx: {n_raw}")

    all_ok = dirs_ok and reg_ok and cli_ok
    print("\n" + "=" * 60)
    print("RESULTADO:", "PASSED" if all_ok else "FAILED")
    print("=" * 60)
    return 0 if all_ok else 1


# --------------------------------------------------------------------- #
# Default (sin subcomando): auto-detect + flujo interactivo
# --------------------------------------------------------------------- #


def cmd_auto() -> int:
    """Default: detecta xlsx pendientes, ofrece ingest, corre orquestador.

    Flujo:
      1. Si hay xlsx pendientes (raw > bronze), pregunta si ingest. Si sí,
         corre run_bronze.
      2. Después corre `orchestrate.py` (default = run interactivo con
         status + plan + prompt y/N).
    """
    print("=" * 70)
    print("PAC_v2 — run.py (auto)")
    print("=" * 70)
    n_raw = _count_raw_xlsx()
    n_bronze = _count_bronze_nrs()
    pending = _bronze_pending()
    print(f"  raw/*.xlsx: {n_raw}    bronze/NR_*.parquet: {n_bronze}    "
          f"pending ≈ {pending}")
    print()

    if pending > 0:
        if _ask_yes_no(
            f"Hay ~{pending} xlsx sin ingestar. ¿Correr ingest (raw → bronze)?",
            default="y",
        ):
            print()
            rc = _run(["python", str(RUN_BRONZE)])
            if rc != 0:
                print(f"\n✗ ingest falló (rc={rc}). Abortando.")
                return rc
            print()
        else:
            print("  → skip ingest. Orquestador correrá sobre bronze actual.")
            print()
    else:
        print("  ✓  bronze al día — saltando ingest.")
        print()

    # Orquestador: invocación default (sin subcomando) = run interactivo.
    print("Orquestador (silver/events/states/gold):")
    return _run(["python", str(ORCHESTRATE)])


# --------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run.py",
        description="PAC_v2 — front door único del pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python run.py                  # auto: ingest si hace falta + orquestador\n"
            "  python run.py status           # inventario\n"
            "  python run.py ingest           # solo raw → bronze\n"
            "  python run.py update           # solo silver/events/states/gold\n"
            "  python run.py all --yes        # todo end-to-end sin prompts\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    # status
    p_status = sub.add_parser("status", help="Inventario sin ejecutar nada.")
    p_status.add_argument("-v", "--verbose", action="store_true",
                          help="Detalle de NRs stale por etapa.")
    p_status.set_defaults(func=cmd_status)

    # plan
    p_plan = sub.add_parser("plan", help="Plan del orquestador, no ejecuta.")
    p_plan.add_argument("-v", "--verbose", action="store_true")
    p_plan.set_defaults(func=cmd_plan)

    # ingest
    p_ing = sub.add_parser("ingest", help="raw → bronze (scripts/run_bronze.py).")
    p_ing.add_argument("--limit", type=int, default=None,
                       help="Procesar solo los primeros N xlsx (smoke test).")
    p_ing.add_argument("--no-autoreg", action="store_true",
                       help="Desactiva auto-registro de pacientes nuevos.")
    p_ing.set_defaults(func=cmd_ingest)

    # update
    p_upd = sub.add_parser("update",
                           help="Solo orquestador (silver/events/states/gold).")
    p_upd.add_argument("--yes", action="store_true",
                       help="Auto-confirmar plan (sin prompt y/N).")
    p_upd.add_argument("--dry-run", action="store_true",
                       help="Imprime plan, no ejecuta.")
    p_upd.add_argument("--quiet", action="store_true",
                       help="Output mínimo durante la ejecución.")
    p_upd.set_defaults(func=cmd_update)

    # all
    p_all = sub.add_parser("all", help="ingest + orquestador (end-to-end).")
    p_all.add_argument("--yes", action="store_true",
                       help="Auto-confirmar plan del orquestador.")
    p_all.add_argument("--dry-run", action="store_true",
                       help="Imprime plan del orquestador, no ejecuta.")
    p_all.add_argument("--quiet", action="store_true",
                       help="Output mínimo.")
    p_all.add_argument("--limit", type=int, default=None,
                       help="Procesar solo los primeros N xlsx en ingest.")
    p_all.add_argument("--no-autoreg", action="store_true",
                       help="Desactiva auto-registro de pacientes nuevos.")
    p_all.set_defaults(func=cmd_all)

    # validate
    p_val = sub.add_parser("validate",
                           help="Sanity check del scaffold (dirs + identity).")
    p_val.set_defaults(func=cmd_validate)

    return p


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        return cmd_auto()

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
