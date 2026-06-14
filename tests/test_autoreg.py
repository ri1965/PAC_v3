"""
PAC_v2 — Etapa 1.1 autoreg: tests unitarios.

Cubre `register_stubs_for_unknown_ids`:
  - crea stubs para user_ids nuevos (patient_id lleno, otros campos vacíos)
  - idempotente: segunda corrida no duplica filas
  - no toca filas existentes del registry o del clinical

No testea peek_user_id (depende de openpyxl + xlsx real → se valida con el
smoke batch en raw/ y con el path feliz ya verificado de load_xlsx_night).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd

# Hacer `pac` importable como paquete local
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac import ingest as ingest_mod  # noqa: E402
from pac import io as io_mod  # noqa: E402
from pac.config import CLINICAL_COLS, CSV_SEP, REGISTRY_COLS  # noqa: E402


def _redirect_identity_csvs_to(tmpdir: Path) -> tuple[Path, Path]:
    """Monkey-patch temporal: redirige registry + clinical a un tmpdir."""
    reg = tmpdir / "patient_registry.csv"
    cli = tmpdir / "clinical.csv"
    # Tanto io como ingest importan los paths al namespace → hay que patchear ambos.
    io_mod.PATIENT_REGISTRY_CSV = reg
    io_mod.CLINICAL_CSV = cli
    ingest_mod.PATIENT_REGISTRY_CSV = reg
    ingest_mod.CLINICAL_CSV = cli
    return reg, cli


def _seed_registry(reg: Path, patient_ids: list[str]) -> None:
    df = pd.DataFrame({
        "patient_id": patient_ids,
        "nombre": [f"Nombre{i}" for i in range(len(patient_ids))],
        "apellido": [f"Apellido{i}" for i in range(len(patient_ids))],
        "fecha_nacimiento": ["1970-01-01"] * len(patient_ids),
    })
    df.to_csv(reg, sep=CSV_SEP, index=False)


def _seed_clinical(cli: Path, patient_ids: list[str]) -> None:
    df = pd.DataFrame({
        "patient_id": patient_ids,
        "sexo": ["M"] * len(patient_ids),
        "peso_kg": ["80"] * len(patient_ids),
        "talla_cm": ["170"] * len(patient_ids),
        "apnea_prev": ["0"] * len(patient_ids),
        "diabetes": ["0"] * len(patient_ids),
        "hta": ["0"] * len(patient_ids),
        "marcapasos": ["0"] * len(patient_ids),
    })
    df.to_csv(cli, sep=CSV_SEP, index=False)


# ---------------------------------------------------------------------------
# Test 1: stub creation para un user_id nuevo
# ---------------------------------------------------------------------------
def test_autoreg_creates_stub_for_unknown_user_id():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        reg, cli = _redirect_identity_csvs_to(tdir)
        _seed_registry(reg, ["100", "101"])
        _seed_clinical(cli, ["100", "101"])

        xlsx_map = {
            "100": ["exam_001.xlsx"],     # ya existe → no crea stub
            "712": ["exam_999.xlsx"],     # nuevo → crea stub
            "715": ["exam_777.xlsx", "exam_778.xlsx"],  # nuevo → crea stub
        }
        result = ingest_mod.register_stubs_for_unknown_ids(xlsx_map, verbose=False)

        # 2 stubs creados, no 3
        assert set(result.keys()) == {"712", "715"}, f"esperados {{'712','715'}}, got {set(result.keys())}"

        # Registry ahora tiene 4 filas
        reg_df = pd.read_csv(reg, sep=CSV_SEP, dtype=str, keep_default_na=False)
        assert len(reg_df) == 4, f"esperadas 4 filas en registry, hay {len(reg_df)}"
        new_reg_ids = set(reg_df["patient_id"]) - {"100", "101"}
        assert new_reg_ids == {"712", "715"}

        # Stubs con patient_id lleno y resto vacío
        stubs = reg_df[reg_df["patient_id"].isin(["712", "715"])]
        for col in REGISTRY_COLS:
            if col == "patient_id":
                continue
            assert (stubs[col] == "").all(), f"col {col} debería estar vacía en stubs"

        # Clinical idem
        cli_df = pd.read_csv(cli, sep=CSV_SEP, dtype=str, keep_default_na=False)
        assert len(cli_df) == 4
        stubs_cli = cli_df[cli_df["patient_id"].isin(["712", "715"])]
        for col in CLINICAL_COLS:
            if col == "patient_id":
                continue
            assert (stubs_cli[col] == "").all(), f"col {col} debería estar vacía en stubs clinical"


# ---------------------------------------------------------------------------
# Test 2: idempotencia
# ---------------------------------------------------------------------------
def test_autoreg_idempotent_on_second_run():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        reg, cli = _redirect_identity_csvs_to(tdir)
        _seed_registry(reg, ["100"])
        _seed_clinical(cli, ["100"])

        xlsx_map = {"712": ["exam_999.xlsx"]}

        # Primera corrida: crea el stub
        result1 = ingest_mod.register_stubs_for_unknown_ids(xlsx_map, verbose=False)
        assert result1 == {"712": ["exam_999.xlsx"]}

        reg_df_1 = pd.read_csv(reg, sep=CSV_SEP, dtype=str, keep_default_na=False)
        assert len(reg_df_1) == 2

        # Segunda corrida con el mismo mapping: no debería duplicar
        result2 = ingest_mod.register_stubs_for_unknown_ids(xlsx_map, verbose=False)
        assert result2 == {}, f"esperado {{}}, got {result2}"

        reg_df_2 = pd.read_csv(reg, sep=CSV_SEP, dtype=str, keep_default_na=False)
        assert len(reg_df_2) == 2, f"registry no debería crecer, hay {len(reg_df_2)} filas"

        cli_df_2 = pd.read_csv(cli, sep=CSV_SEP, dtype=str, keep_default_na=False)
        assert len(cli_df_2) == 2


# ---------------------------------------------------------------------------
# Test 3: no mutar filas existentes
# ---------------------------------------------------------------------------
def test_autoreg_preserves_existing_rows_unchanged():
    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)
        reg, cli = _redirect_identity_csvs_to(tdir)
        _seed_registry(reg, ["100", "101"])
        _seed_clinical(cli, ["100", "101"])

        # Snapshot inicial
        reg_before = pd.read_csv(reg, sep=CSV_SEP, dtype=str, keep_default_na=False)
        cli_before = pd.read_csv(cli, sep=CSV_SEP, dtype=str, keep_default_na=False)

        xlsx_map = {
            "100": ["exam_001.xlsx"],
            "712": ["exam_999.xlsx"],
        }
        ingest_mod.register_stubs_for_unknown_ids(xlsx_map, verbose=False)

        # Las filas 100 y 101 deben estar EXACTAMENTE iguales (mismas columnas,
        # mismos valores, misma posición).
        reg_after = pd.read_csv(reg, sep=CSV_SEP, dtype=str, keep_default_na=False)
        cli_after = pd.read_csv(cli, sep=CSV_SEP, dtype=str, keep_default_na=False)

        for pid in ("100", "101"):
            row_before_r = reg_before[reg_before["patient_id"] == pid].iloc[0]
            row_after_r = reg_after[reg_after["patient_id"] == pid].iloc[0]
            for col in REGISTRY_COLS:
                assert row_before_r[col] == row_after_r[col], (
                    f"registry pid={pid} col={col} cambió: "
                    f"{row_before_r[col]!r} → {row_after_r[col]!r}"
                )

            row_before_c = cli_before[cli_before["patient_id"] == pid].iloc[0]
            row_after_c = cli_after[cli_after["patient_id"] == pid].iloc[0]
            for col in CLINICAL_COLS:
                assert row_before_c[col] == row_after_c[col], (
                    f"clinical pid={pid} col={col} cambió: "
                    f"{row_before_c[col]!r} → {row_after_c[col]!r}"
                )


# ---------------------------------------------------------------------------
# Runner manual (sin pytest): python -m tests.test_autoreg
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    fail = 0
    for t in tests:
        try:
            t()
            print(f"  OK   {t.__name__}")
        except AssertionError as e:
            fail += 1
            print(f"  FAIL {t.__name__}: {e or '(assertion)'}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  FAIL {t.__name__}: {type(e).__name__}: {e}")
    total = len(tests)
    print()
    print(f"[tests/test_autoreg] {total - fail}/{total} OK")
    sys.exit(0 if fail == 0 else 1)
