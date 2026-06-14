"""
Tests para los sidecars de Gold (Etapa 5 paso 7):
  - scripts/build_gold_manifest.py → gold/MANIFEST.json
  - scripts/build_nights_columns_doc.py → gold/nights_columns.json

Cobertura:
- gold/MANIFEST.json tiene los campos esperados (model_version, git_sha,
  tables, build_order, cohort_policy).
- Cada tabla declarada coincide con n_rows/n_cols reales del parquet.
- nights_columns.json clasifica los 146 cols en los 5 kinds correctos.
- Cross-night cols efectivamente clasificadas (ahi_3_pct_corpus etc.).
- Override CSV: si existe, sobrescribe la descripción auto.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_spec1 = importlib.util.spec_from_file_location(
    "build_gold_manifest", REPO_ROOT / "scripts" / "build_gold_manifest.py"
)
build_gold_manifest_module = importlib.util.module_from_spec(_spec1)
_spec1.loader.exec_module(build_gold_manifest_module)

_spec2 = importlib.util.spec_from_file_location(
    "build_nights_columns_doc",
    REPO_ROOT / "scripts" / "build_nights_columns_doc.py",
)
build_nights_columns_doc_module = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(build_nights_columns_doc_module)


# --------------------------------------------------------------------- #
# gold/MANIFEST.json
# --------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def gold_manifest():
    if not (REPO_ROOT / "models" / "MANIFEST.json").exists():
        pytest.skip("Falta models/MANIFEST.json.")
    return build_gold_manifest_module.build_manifest()


class TestGoldManifest:
    def test_required_fields(self, gold_manifest):
        for f in [
            "manifest_version",
            "generated_at",
            "model_version",
            "tables",
            "build_order",
            "cohort_policy",
            "n_tables",
        ]:
            assert f in gold_manifest

    def test_build_order_canonical(self, gold_manifest):
        assert gold_manifest["build_order"] == [
            "events",
            "events_curves",
            "states",
            "nights",
            "patients",
        ]

    def test_n_tables_5(self, gold_manifest):
        assert gold_manifest["n_tables"] == 5

    def test_table_blocks_match_parquet(self, gold_manifest):
        """Para cada tabla presente, n_rows/n_cols deben coincidir con el parquet real."""
        for name, block in gold_manifest["tables"].items():
            if block.get("missing"):
                continue
            path = REPO_ROOT / block["path"]
            real_meta = pq.read_metadata(path)
            assert int(real_meta.num_rows) == block["n_rows"], f"{name} rows mismatch"
            assert int(real_meta.num_columns) == block["n_cols"], f"{name} cols mismatch"

    def test_sha256_short_present_for_all_present_tables(self, gold_manifest):
        for name, block in gold_manifest["tables"].items():
            if block.get("missing"):
                continue
            assert "sha256_short" in block
            assert len(block["sha256_short"]) == 16


# --------------------------------------------------------------------- #
# gold/nights_columns.json
# --------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def nights_doc():
    if not (REPO_ROOT / "gold" / "nights.parquet").exists():
        pytest.skip("Falta gold/nights.parquet.")
    return build_nights_columns_doc_module.build_doc(verbose=False)


class TestNightsColumnsDoc:
    def test_required_top_level(self, nights_doc):
        for f in [
            "manifest_version",
            "source",
            "n_columns",
            "summary_by_kind",
            "kind_legend",
            "columns",
        ]:
            assert f in nights_doc

    def test_n_columns_matches_parquet(self, nights_doc):
        path = REPO_ROOT / "gold" / "nights.parquet"
        real_meta = pq.read_metadata(path)
        assert nights_doc["n_columns"] == int(real_meta.num_columns)

    def test_summary_sums_to_n_columns(self, nights_doc):
        s = nights_doc["summary_by_kind"]
        total = sum(s.values())
        assert total == nights_doc["n_columns"]


class TestKindClassification:
    def test_identity_cols(self, nights_doc):
        ids = {c["name"] for c in nights_doc["columns"] if c["kind"] == "identity"}
        assert ids == {"night_record_id", "user_id", "model_version"}

    def test_flag_cols(self, nights_doc):
        flags = {c["name"] for c in nights_doc["columns"] if c["kind"] == "flag"}
        assert flags == {
            "in_quality",
            "in_strict",
            "in_high_tst",
            "flag_for_review",
            "b2_fail",
        }

    def test_cross_night_corpus_cols(self, nights_doc):
        cc = {
            c["name"]
            for c in nights_doc["columns"]
            if c["kind"] == "cross_night_corpus"
        }
        # Las 3 cross-night cohort que generamos en build_nights_gold.py
        for col in ["ahi_3_pct_corpus", "t90_frac_pct_corpus", "odi_3_pct_corpus"]:
            assert col in cc, f"falta {col}"

    def test_cross_night_patient_cols(self, nights_doc):
        cp = {
            c["name"]
            for c in nights_doc["columns"]
            if c["kind"] == "cross_night_patient"
        }
        for col in [
            "delta_ahi_3_vs_baseline_patient",
            "delta_t90_frac_vs_baseline_patient",
            "delta_odi_3_vs_baseline_patient",
        ]:
            assert col in cp


class TestDescriptionsCoverage:
    def test_no_placeholder_descriptions(self, nights_doc):
        """En el corpus actual, todas las cols deben tener descripción auto."""
        no_desc = [
            c for c in nights_doc["columns"] if "sin descripción" in c["description"]
        ]
        assert no_desc == [], (
            f"Cols sin descripción: {[c['name'] for c in no_desc]}"
        )

    def test_distribution_descriptions_well_formed(self, nights_doc):
        """frac_morpho_*, frac_state_*, n_transitions_*, entropy_* tienen descr."""
        for c in nights_doc["columns"]:
            if (
                c["name"].startswith("frac_morpho_")
                or c["name"].startswith("frac_state_")
                or c["name"].startswith("n_transitions_state_")
                or c["name"].startswith("entropy_state_")
            ):
                assert c["description"]
                assert "sin descripción" not in c["description"]


# --------------------------------------------------------------------- #
# Override desde CSV
# --------------------------------------------------------------------- #


class TestOverrideMechanism:
    def test_override_loaded_from_csv(self, monkeypatch):
        """Si existe el CSV, las descripciones manuales sobrescriben."""
        # Usar un path real bajo gold/ (no tmp_path porque el script
        # usa relative_to(REPO_ROOT)). Cleanup garantizado por finally.
        csv_path = REPO_ROOT / "gold" / "_test_override_descriptions.csv"
        df = pd.DataFrame(
            {
                "column_name": ["ahi_3", "tst_s"],
                "description": [
                    "AHI 3% MANUAL OVERRIDE",
                    "TST MANUAL OVERRIDE",
                ],
            }
        )
        df.to_csv(csv_path, index=False)

        try:
            monkeypatch.setattr(
                build_nights_columns_doc_module, "DESCRIPTIONS_OVERRIDE", csv_path
            )
            doc = build_nights_columns_doc_module.build_doc(verbose=False)
            ahi = next(c for c in doc["columns"] if c["name"] == "ahi_3")
            tst = next(c for c in doc["columns"] if c["name"] == "tst_s")
            assert "MANUAL OVERRIDE" in ahi["description"]
            assert "MANUAL OVERRIDE" in tst["description"]
            assert doc["n_overrides_applied"] == 2
        finally:
            csv_path.unlink(missing_ok=True)
