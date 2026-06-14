"""
Tests para src/pac/cohorts.py (Etapa 4.6).

Cobertura: invariantes de inclusión entre cohortes (strict ⊆ quality ⊆ all),
cohort_summary devuelve las claves esperadas, snapshot_cohort persiste
formato correcto.

NO mockea I/O — corre contra el corpus real del repo. Si el repo no
tiene datos (CI fresco), los tests pasan trivialmente porque las
cohortes devuelven sets vacíos.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path


from pac.cohorts import (
    cohort_summary,
    get_cohort_all,
    get_cohort_high_tst,
    get_cohort_quality,
    get_cohort_strict,
    get_cohort_with_clinical,
    snapshot_cohort,
)


class TestCohortInvariants:
    def test_strict_subset_of_quality(self):
        assert get_cohort_strict().issubset(get_cohort_quality())

    def test_quality_subset_of_all(self):
        assert get_cohort_quality().issubset(get_cohort_all())

    def test_high_tst_subset_of_quality(self):
        assert get_cohort_high_tst(min_tst_h=4.0).issubset(get_cohort_quality())

    def test_with_clinical_subset_of_quality(self):
        assert get_cohort_with_clinical().issubset(get_cohort_quality())

    def test_high_tst_monotone(self):
        """Más estricto = subconjunto."""
        c2h = get_cohort_high_tst(min_tst_h=2.0)
        c4h = get_cohort_high_tst(min_tst_h=4.0)
        c6h = get_cohort_high_tst(min_tst_h=6.0)
        assert c6h.issubset(c4h)
        assert c4h.issubset(c2h)


class TestCohortSummary:
    def test_summary_keys(self):
        s = cohort_summary()
        expected = {
            "all",
            "quality",
            "strict",
            "high_tst_4h",
            "with_clinical",
            "b2_fail_excluded",
            "flag_for_review",
        }
        assert set(s.keys()) == expected

    def test_summary_values_are_int(self):
        s = cohort_summary()
        for k, v in s.items():
            assert isinstance(v, int), f"{k} no es int: {v!r}"

    def test_summary_internal_consistency(self):
        s = cohort_summary()
        # quality = all - b2_fail (las 7 b2 están en states/ pero no en quality)
        assert s["quality"] == s["all"] - s["b2_fail_excluded"]
        # strict ≤ quality
        assert s["strict"] <= s["quality"]


class TestSnapshot:
    def test_snapshot_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            outpath = Path(tmp) / "test_snap.json"
            nrs = {"NR_aaa", "NR_bbb", "NR_ccc"}
            snapshot_cohort("test", nrs, outpath)
            assert outpath.exists()
            data = json.loads(outpath.read_text())
            assert data["name"] == "test"
            assert data["count"] == 3
            assert set(data["night_record_ids"]) == nrs
            assert "timestamp" in data

    def test_snapshot_creates_parent_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            outpath = Path(tmp) / "subdir" / "deeper" / "snap.json"
            snapshot_cohort("test", {"NR_x"}, outpath)
            assert outpath.exists()
