"""
Tests para src/pac/orchestrator.py (Etapa 6).

Cobertura:
- Detección de stale por mtime (silver, events, states, gold).
- Detección de stale por modelo (mtime de models/* > output).
- Detección de stale por scripts (mtime de build_*_gold.py > gold/*).
- Detección de stale por MANIFEST (bumpear sin reentrenar).
- Plan respeta dependencias: si silver stale → events/states/gold también
  se incluyen aunque parezcan limpias.
- _list_nrs_in filtra estrictamente por NR_<10hex>.parquet (excluye _qc, _edos).

Tests usan tmp_path + monkeypatch para no depender del corpus real.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pac import orchestrator as orch


# --------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------- #


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """Crea estructura mínima del repo en tmp_path y redirige todas las
    constantes del módulo orchestrator hacia ahí."""
    bronze = tmp_path / "bronze"
    silver = tmp_path / "silver"
    events = tmp_path / "events"
    states = tmp_path / "states"
    gold = tmp_path / "gold"
    models = tmp_path / "models"
    scripts = tmp_path / "scripts"
    for d in [bronze, silver, events, states, gold, models, scripts]:
        d.mkdir()

    monkeypatch.setattr(orch, "BRONZE_DIR", bronze)
    monkeypatch.setattr(orch, "SILVER_DIR", silver)
    monkeypatch.setattr(orch, "EVENTS_DIR", events)
    monkeypatch.setattr(orch, "STATES_DIR", states)
    monkeypatch.setattr(orch, "GOLD_DIR", gold)
    monkeypatch.setattr(orch, "MODELS_DIR", models)
    monkeypatch.setattr(orch, "SCRIPTS_DIR", scripts)
    monkeypatch.setattr(orch, "MANIFEST_PATH", models / "MANIFEST.json")

    return tmp_path


def _touch(path: Path, mtime: float | None = None) -> Path:
    """Crea archivo con mtime opcional."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _setup_clean_pipeline(repo: Path, nrs=("NR_0000000001", "NR_0000000002")):
    """Pipeline en estado coherente: bronze < silver < events < states < gold."""
    base = 1000.0
    # Bronze
    for nr in nrs:
        _touch(repo / "bronze" / f"{nr}.parquet", mtime=base)
    # Silver
    for nr in nrs:
        _touch(repo / "silver" / f"{nr}.parquet", mtime=base + 100)
        _touch(repo / "silver" / f"{nr}_qc.parquet", mtime=base + 100)
    # Models (más viejos que outputs downstream)
    for f in orch.MODEL_FILES_MORPHO + orch.MODEL_FILES_PAC:
        _touch(repo / "models" / f, mtime=base + 50)
    _touch(repo / "models" / "MANIFEST.json", mtime=base + 50)
    # Events (3 archivos por NR)
    for nr in nrs:
        for suf in ("_edos", "_edo_curves", "_indices"):
            _touch(repo / "events" / f"{nr}{suf}.parquet", mtime=base + 200)
    # States
    for nr in nrs:
        _touch(repo / "states" / f"{nr}.parquet", mtime=base + 300)
    # Gold tables
    for t in orch.GOLD_TABLES:
        _touch(repo / "gold" / f"{t}.parquet", mtime=base + 400)
    # Scripts (más viejos que gold)
    for s in orch.GOLD_BUILD_SCRIPTS:
        _touch(repo / "scripts" / s, mtime=base + 350)
    return base


# --------------------------------------------------------------------- #
# _list_nrs_in: filtrado estricto
# --------------------------------------------------------------------- #


class TestListNrsIn:
    def test_filters_qc_subfile(self, fake_repo):
        nrs = ("NR_aabbccdd11", "NR_aabbccdd22")
        for nr in nrs:
            _touch(fake_repo / "silver" / f"{nr}.parquet")
            _touch(fake_repo / "silver" / f"{nr}_qc.parquet")
        result = orch._list_nrs_in(fake_repo / "silver")
        assert result == set(nrs)  # _qc no debería estar

    def test_filters_edos_subfile(self, fake_repo):
        # En events/, NR_*_edos.parquet NO debe ser tomado por _list_nrs_in
        _touch(fake_repo / "events" / "NR_aabbccdd11_edos.parquet")
        _touch(fake_repo / "events" / "NR_aabbccdd11.parquet")  # canónico
        result = orch._list_nrs_in(fake_repo / "events")
        # Solo debe tomar el canónico (NR_<hex>.parquet)
        assert result == {"NR_aabbccdd11"}

    def test_empty_dir(self, fake_repo):
        result = orch._list_nrs_in(fake_repo / "silver")
        assert result == set()

    def test_nonexistent_dir(self, tmp_path):
        result = orch._list_nrs_in(tmp_path / "nope")
        assert result == set()


# --------------------------------------------------------------------- #
# Pipeline limpio
# --------------------------------------------------------------------- #


class TestCleanPipeline:
    def test_all_stages_ok(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        status = orch.detect_all()
        assert status.is_clean
        assert status.stale_stages == []

    def test_plan_empty_when_clean(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        status = orch.detect_all()
        assert orch.compute_plan(status) == []


# --------------------------------------------------------------------- #
# Detección por etapa
# --------------------------------------------------------------------- #


class TestSilverStale:
    def test_missing_silver_output_is_stale(self, fake_repo):
        nrs = ("NR_0000000001",)
        _touch(fake_repo / "bronze" / f"{nrs[0]}.parquet", mtime=1000)
        # Silver NO existe
        st = orch.detect_silver_stale()
        assert st.n_stale == 1
        assert nrs[0] in st.stale_nrs

    def test_bronze_newer_than_silver(self, fake_repo):
        nr = "NR_0000000001"
        _touch(fake_repo / "silver" / f"{nr}.parquet", mtime=1000)
        _touch(fake_repo / "bronze" / f"{nr}.parquet", mtime=2000)
        st = orch.detect_silver_stale()
        assert st.n_stale == 1
        assert "bronze mtime > silver mtime" in st.reasons[nr]


class TestEventsStale:
    def test_silver_newer_than_events(self, fake_repo):
        nr = "NR_0000000001"
        _touch(fake_repo / "silver" / f"{nr}.parquet", mtime=2000)
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=1000)
        # Modelos viejos para no contaminar
        for f in orch.MODEL_FILES_MORPHO:
            _touch(fake_repo / "models" / f, mtime=500)
        st = orch.detect_events_stale()
        assert st.n_stale == 1
        assert "silver mtime > events mtime" in st.reasons[nr]

    def test_morphotype_model_newer_than_events_invalidates(self, fake_repo):
        """P2: si reentrenás morfotipos, todos los events quedan stale."""
        nr = "NR_0000000001"
        _touch(fake_repo / "silver" / f"{nr}.parquet", mtime=1000)
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=1500)
        # El modelo se reentrenó después
        for f in orch.MODEL_FILES_MORPHO:
            _touch(fake_repo / "models" / f, mtime=2000)
        st = orch.detect_events_stale()
        assert st.n_stale == 1
        assert "morphotype model mtime > events mtime" in st.reasons[nr]


class TestStatesStale:
    def test_pac_model_newer_invalidates_via_mtime_fallback(self, fake_repo):
        """P2 + Etapa 6.1: si el states no tiene SHA en KV (pre-Etapa 6.1),
        cae al fallback de mtime → reentreno detectado."""
        nr = "NR_0000000001"
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=1000)
        _touch(fake_repo / "states" / f"{nr}.parquet", mtime=1500)
        for f in orch.MODEL_FILES_PAC:
            _touch(fake_repo / "models" / f, mtime=2000)
        st = orch.detect_states_stale()
        assert st.n_stale == 1
        # Mensaje incluye "(no SHA)" porque cae al fallback mtime
        assert any("no SHA" in r for r in st.reasons[nr])


class TestStatesStaleByShaModel:
    """Etapa 6.1: validación honesta por SHA del modelo (no mtime)."""

    def _write_states_with_sha(self, fake_repo, nr, sha_value, states_mtime=1500):
        """Helper: crea un states/<NR>.parquet con KV model_centroids_sha256."""
        import pyarrow as pa
        import pyarrow.parquet as pq
        states_p = fake_repo / "states" / f"{nr}.parquet"
        tbl = pa.table({"x": [1, 2, 3]})
        kv = {"model_centroids_sha256": sha_value}
        tbl = tbl.replace_schema_metadata(kv)
        pq.write_table(tbl, states_p)
        os.utime(states_p, (states_mtime, states_mtime))
        return states_p

    def _setup_real_pac_centroids(self, fake_repo):
        """Crea 3 archivos de centroides reales (CSV) en models/."""
        import pandas as pd
        for scale in ("s", "m", "l"):
            df = pd.DataFrame({"f0": [1.0, 2.0], "f1": [3.0, 4.0]})
            df.to_csv(fake_repo / "models" / f"pac_states_{scale}_centroids.csv",
                      index=False)
        return orch._compute_pac_models_sha256()

    def test_sha_match_means_not_stale(self, fake_repo):
        """Si SHA persistido == SHA actual → no stale (incluso si events más nuevo)."""
        nr = "NR_aabbccdd11"
        sha = self._setup_real_pac_centroids(fake_repo)
        # events MÁS NUEVO que states (escenario que antes daba falso positivo)
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=9999)
        self._write_states_with_sha(fake_repo, nr, sha, states_mtime=1000)
        st = orch.detect_states_stale()
        assert st.n_stale == 0

    def test_sha_mismatch_means_stale(self, fake_repo):
        """Si SHA persistido != SHA actual → stale (modelo cambió)."""
        nr = "NR_aabbccdd11"
        sha = self._setup_real_pac_centroids(fake_repo)
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=1000)
        self._write_states_with_sha(fake_repo, nr, "0000oldsha000000",
                                     states_mtime=2000)
        st = orch.detect_states_stale()
        assert st.n_stale == 1
        assert any("SHA changed" in r for r in st.reasons[nr])

    def test_no_sha_falls_back_to_mtime(self, fake_repo):
        """Si states no tiene KV (pre-Etapa 6.1) → fallback mtime."""
        nr = "NR_aabbccdd11"
        self._setup_real_pac_centroids(fake_repo)
        _touch(fake_repo / "events" / f"{nr}_edos.parquet", mtime=2000)
        # states sin KV (mock con _touch normal, no _write_states_with_sha)
        _touch(fake_repo / "states" / f"{nr}.parquet", mtime=1000)
        st = orch.detect_states_stale()
        assert st.n_stale == 1
        assert any("no SHA" in r for r in st.reasons[nr])

    def test_compute_sha_returns_none_when_models_missing(self, fake_repo):
        """_compute_pac_models_sha256 devuelve None si falta algún centroide."""
        # No creamos centroides
        sha = orch._compute_pac_models_sha256()
        assert sha is None


class TestGoldStale:
    def test_missing_gold_table(self, fake_repo):
        # Solo crear 4 de las 5 tablas
        for t in orch.GOLD_TABLES[:4]:
            _touch(fake_repo / "gold" / f"{t}.parquet")
        st = orch.detect_gold_stale()
        assert st.n_stale > 0
        # La 5ta tabla debe aparecer
        assert orch.GOLD_TABLES[4] in st.stale_nrs

    def test_upstream_data_newer_invalidates_gold(self, fake_repo):
        for t in orch.GOLD_TABLES:
            _touch(fake_repo / "gold" / f"{t}.parquet", mtime=1000)
        for s in orch.GOLD_BUILD_SCRIPTS:
            _touch(fake_repo / "scripts" / s, mtime=500)
        _touch(fake_repo / "models" / "MANIFEST.json", mtime=500)
        # Un evento más nuevo que las tablas
        _touch(fake_repo / "events" / "NR_0000000001_edos.parquet", mtime=2000)
        st = orch.detect_gold_stale()
        assert st.n_stale == 1
        assert any("upstream data" in r for r in st.reasons["(rebuild all)"])

    def test_build_script_newer_invalidates_gold(self, fake_repo):
        """P4: cambiar build_*_gold.py invalida gold."""
        for t in orch.GOLD_TABLES:
            _touch(fake_repo / "gold" / f"{t}.parquet", mtime=1000)
        _touch(fake_repo / "models" / "MANIFEST.json", mtime=500)
        # Un build script más nuevo
        _touch(fake_repo / "scripts" / "build_nights_gold.py", mtime=2000)
        st = orch.detect_gold_stale()
        assert st.n_stale == 1
        assert any("build_*_gold.py" in r for r in st.reasons["(rebuild all)"])

    def test_manifest_bump_invalidates_gold(self, fake_repo):
        """Bumpear MANIFEST.json sin reentrenar igual invalida gold."""
        for t in orch.GOLD_TABLES:
            _touch(fake_repo / "gold" / f"{t}.parquet", mtime=1000)
        for s in orch.GOLD_BUILD_SCRIPTS:
            _touch(fake_repo / "scripts" / s, mtime=500)
        _touch(fake_repo / "models" / "MANIFEST.json", mtime=2000)
        st = orch.detect_gold_stale()
        assert st.n_stale == 1
        assert any("MANIFEST" in r for r in st.reasons["(rebuild all)"])


# --------------------------------------------------------------------- #
# Plan: propagación downstream
# --------------------------------------------------------------------- #


class TestPlanPropagation:
    def test_silver_stale_includes_all_downstream(self, fake_repo):
        """Si silver está stale, plan incluye silver+events(x2)+states+gold
        aunque events/states/gold parezcan internamente OK."""
        _setup_clean_pipeline(fake_repo)
        # Hacer silver stale tocando bronze
        nr = "NR_0000000001"
        _touch(fake_repo / "bronze" / f"{nr}.parquet", mtime=9999)

        status = orch.detect_all()
        plan = orch.compute_plan(status)
        stages_in_plan = [step["stage"] for step in plan]
        # events tiene 2 sub-pasos (pipeline + apply_morphotypes)
        assert stages_in_plan == ["silver", "events", "events", "states", "gold"]

    def test_events_stale_includes_states_and_gold(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        # Forzar events stale (modelo morfotipos más nuevo)
        for f in orch.MODEL_FILES_MORPHO:
            _touch(fake_repo / "models" / f, mtime=9999)

        status = orch.detect_all()
        plan = orch.compute_plan(status)
        stages_in_plan = [step["stage"] for step in plan]
        # silver no, pero events(x2)+states+gold sí
        assert "silver" not in stages_in_plan
        assert stages_in_plan == ["events", "events", "states", "gold"]
        # 2do paso es apply_morphotypes
        assert "apply_morphotypes" in " ".join(plan[1]["cmd"])

    def test_only_gold_stale(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        # Solo cambia un build script (gold-only stale)
        _touch(fake_repo / "scripts" / "build_nights_gold.py", mtime=9999)

        status = orch.detect_all()
        plan = orch.compute_plan(status)
        stages_in_plan = [step["stage"] for step in plan]
        assert stages_in_plan == ["gold"]


# --------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------- #


class TestRender:
    def test_render_status_clean(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        status = orch.detect_all()
        text = orch.render_status_text(status)
        assert "✓" in text
        assert "Todo up-to-date" in text

    def test_render_status_stale(self, fake_repo):
        nr = "NR_0000000001"
        _touch(fake_repo / "bronze" / f"{nr}.parquet", mtime=1000)
        # Silver missing → stale
        status = orch.detect_all()
        text = orch.render_status_text(status, verbose=True)
        assert "STALE" in text
        assert nr in text

    def test_render_plan_empty(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        status = orch.detect_all()
        plan = orch.compute_plan(status)
        text = orch.render_plan_text(plan)
        assert "vacío" in text

    def test_render_plan_with_steps(self, fake_repo):
        _setup_clean_pipeline(fake_repo)
        nr = "NR_0000000001"
        _touch(fake_repo / "bronze" / f"{nr}.parquet", mtime=9999)
        status = orch.detect_all()
        plan = orch.compute_plan(status)
        text = orch.render_plan_text(plan)
        assert "silver" in text
        assert "events" in text
        assert "states" in text
        assert "gold" in text
