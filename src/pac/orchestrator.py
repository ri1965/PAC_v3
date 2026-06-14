"""
PAC_v2 — Orquestador incremental (Etapa 6)

Módulo de detección de staleness y planning del pipeline. NO ejecuta
nada por sí mismo — eso es responsabilidad de scripts/orchestrate.py
(la CLI). Esto es la "biblioteca" pura que se puede testear sin
side-effects.

Política de detección:
  - mtime de archivos para staleness intra-pipeline (P1=mtime puro).
  - El reentrenamiento se detecta automáticamente porque toca los
    mtimes de models/* (P2=A: invalidación por modelo).
  - Si bumpeás el manifest sin reentrenar (caso bizarro), se incluye
    models/MANIFEST.json en la comparación para gold.

Limitación conocida:
  Los scripts silver/events son batch-full (no per-NR, no skip-if-fresh).
  El orquestador detecta stale por NR para diagnóstico, pero la
  ejecución es siempre full. Mejora futura: agregar `--only-stale`
  a esos scripts.

Etapas modeladas:
  1. silver   — bronze → silver
  2. events   — silver → events (incluye apply_morphotypes)
  3. states   — events + models → states
  4. gold     — events + states + scripts/build_*_gold.py → gold/*

Bronze (raw → bronze) NO está en el orquestador — es manual con
scripts/run_bronze.py (el naming raw es arbitrario, NR se calcula del
contenido). Para nuevas xlsx el usuario corre run_bronze antes de
arrancar el orquestador.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parents[2]

BRONZE_DIR = REPO_ROOT / "bronze"
SILVER_DIR = REPO_ROOT / "silver"
EVENTS_DIR = REPO_ROOT / "events"
STATES_DIR = REPO_ROOT / "states"
GOLD_DIR = REPO_ROOT / "gold"
MODELS_DIR = REPO_ROOT / "models"
SCRIPTS_DIR = REPO_ROOT / "scripts"

MODEL_FILES_MORPHO = [
    "edo_morphotype_centroids.csv",
    "edo_morphotype_metadata.json",
    "edo_morphotype_zscore.json",
    "edo_morphotype_kmeans.pkl",
]
MODEL_FILES_MORPHO_CURVE = [
    "edo_morphotype_curve_kmeans.pkl",
    "edo_morphotype_curve_centroids.csv",
    "edo_morphotype_curve_centroids.npy",
    "edo_morphotype_curve_metadata.json",
]
MODEL_FILES_PAC_S = [f"pac_states_s_{x}" for x in (
    "centroids.csv", "metadata.json", "zscore.json", "kmeans.pkl"
)]
MODEL_FILES_PAC_M = [f"pac_states_m_{x}" for x in (
    "centroids.csv", "metadata.json", "zscore.json", "kmeans.pkl"
)]
MODEL_FILES_PAC_L = [f"pac_states_l_{x}" for x in (
    "centroids.csv", "metadata.json", "zscore.json", "kmeans.pkl"
)]
MODEL_FILES_PAC = MODEL_FILES_PAC_S + MODEL_FILES_PAC_M + MODEL_FILES_PAC_L
MANIFEST_PATH = MODELS_DIR / "MANIFEST.json"

GOLD_TABLES = ["events", "events_curves", "states", "nights", "patients"]
GOLD_BUILD_SCRIPTS = [
    "build_events_gold.py",
    "build_events_curves_gold.py",
    "build_states_gold.py",
    "build_nights_gold.py",
    "build_patients_gold.py",
    "build_gold_manifest.py",
    "build_nights_columns_doc.py",
]


# --------------------------------------------------------------------- #
# Datatypes
# --------------------------------------------------------------------- #


@dataclass
class StageStatus:
    """Estado de una etapa del pipeline.

    n_total: NRs (o tablas, en el caso de gold) presentes en el output.
    n_stale: subset que está stale.
    stale_nrs: lista ordenada de NRs stale (para gold, lista de tablas).
    reasons: razones por las que están stale (input mtime > output, etc.).
    is_stale_global: True si HAY al menos un stale (basta para correr).
    """

    name: str
    n_total: int
    n_stale: int
    stale_nrs: List[str] = field(default_factory=list)
    reasons: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def is_stale_global(self) -> bool:
        return self.n_stale > 0


@dataclass
class PipelineStatus:
    """Estado completo del pipeline."""

    stages: Dict[str, StageStatus]

    @property
    def stale_stages(self) -> List[str]:
        return [name for name, st in self.stages.items() if st.is_stale_global]

    @property
    def is_clean(self) -> bool:
        return len(self.stale_stages) == 0


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _mtime(path: Path) -> float:
    """mtime de un archivo, o -inf si no existe (siempre 'más viejo')."""
    if not path.exists():
        return float("-inf")
    return path.stat().st_mtime


def _max_mtime(paths: List[Path]) -> float:
    """Máximo mtime de una lista de paths (ignora inexistentes)."""
    if not paths:
        return float("-inf")
    return max(_mtime(p) for p in paths)


import re

# NR canónico: NR_ + 10 chars hex
_NR_PATTERN = re.compile(r"^NR_[0-9a-f]{10}\.parquet$")


def _list_nrs_in(dir_path: Path, pattern: str = "NR_*.parquet") -> Set[str]:
    """Devuelve el conjunto de NRs presentes en un directorio.

    Filtra estrictamente por NR_<10hex>.parquet — excluye sub-archivos
    como _qc.parquet, _edos.parquet, etc. Para esos, usar helpers
    específicos (_list_nrs_events_edos).
    """
    if not dir_path.exists():
        return set()
    return {
        p.stem for p in dir_path.glob(pattern)
        if _NR_PATTERN.match(p.name)
    }


def _list_nrs_events_edos() -> Set[str]:
    """events/ tiene 3 archivos por NR; usamos _edos para enumerar."""
    if not EVENTS_DIR.exists():
        return set()
    return {p.stem.replace("_edos", "") for p in EVENTS_DIR.glob("NR_*_edos.parquet")}


# --------------------------------------------------------------------- #
# Detección por etapa
# --------------------------------------------------------------------- #


def detect_silver_stale() -> StageStatus:
    """silver/<NR>.parquet stale si bronze/<NR>.parquet es más nuevo."""
    bronze_nrs = _list_nrs_in(BRONZE_DIR)
    silver_nrs = _list_nrs_in(SILVER_DIR)
    stale_nrs: List[str] = []
    reasons: Dict[str, List[str]] = {}

    for nr in sorted(bronze_nrs):
        bronze_p = BRONZE_DIR / f"{nr}.parquet"
        silver_p = SILVER_DIR / f"{nr}.parquet"
        if not silver_p.exists():
            stale_nrs.append(nr)
            reasons[nr] = ["silver output missing"]
            continue
        if _mtime(bronze_p) > _mtime(silver_p):
            stale_nrs.append(nr)
            reasons[nr] = ["bronze mtime > silver mtime"]

    return StageStatus(
        name="silver",
        n_total=len(silver_nrs),
        n_stale=len(stale_nrs),
        stale_nrs=stale_nrs,
        reasons=reasons,
    )


def detect_events_stale() -> StageStatus:
    """events stale si:
      - el output _edos.parquet no existe, o
      - silver es más nuevo que events, o
      - el modelo de morfotipos cambió (mtime), o
      - el modelo de morfotipos no existe (apply_morphotypes nunca pudo correr).
    """
    silver_nrs = _list_nrs_in(SILVER_DIR)
    events_nrs = _list_nrs_events_edos()
    model_paths = [MODELS_DIR / f for f in MODEL_FILES_MORPHO]
    curve_model_paths = [MODELS_DIR / f for f in MODEL_FILES_MORPHO_CURVE]
    morpho_models_missing = not all(p.exists() for p in model_paths)
    morpho_curve_models_missing = not all(p.exists() for p in curve_model_paths)
    model_max_mtime = _max_mtime(model_paths + curve_model_paths)

    stale_nrs: List[str] = []
    reasons: Dict[str, List[str]] = {}

    for nr in sorted(silver_nrs):
        silver_p = SILVER_DIR / f"{nr}.parquet"
        events_p = EVENTS_DIR / f"{nr}_edos.parquet"
        if not events_p.exists():
            stale_nrs.append(nr)
            reasons[nr] = ["events output missing"]
            continue
        events_mt = _mtime(events_p)
        rs = []
        if _mtime(silver_p) > events_mt:
            rs.append("silver mtime > events mtime")
        if morpho_models_missing:
            rs.append("morphotype models missing — apply_morphotypes nunca corrió")
        elif morpho_curve_models_missing:
            rs.append("morphotype_curve models missing — apply_morphotypes_curve nunca corrió")
        elif model_max_mtime > events_mt:
            rs.append("morphotype model mtime > events mtime")
        if rs:
            stale_nrs.append(nr)
            reasons[nr] = rs

    return StageStatus(
        name="events",
        n_total=len(events_nrs),
        n_stale=len(stale_nrs),
        stale_nrs=stale_nrs,
        reasons=reasons,
    )


def _compute_pac_models_sha256() -> str | None:
    """SHA256 corto de los 3 archivos pac_states_{s,m,l}_centroids.csv.

    Esta función debe coincidir EXACTAMENTE con la lógica equivalente en
    scripts/apply_pac_states.py:compute_models_sha256(). Etapa 6.1.

    Devuelve None si falta algún archivo de centroides (modelos no entrenados).
    """
    import hashlib
    h = hashlib.sha256()
    for scale in ("s", "m", "l"):
        path = MODELS_DIR / f"pac_states_{scale}_centroids.csv"
        if not path.exists():
            return None
        with open(path, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:16]


def _read_states_models_sha256(parquet_path: Path) -> str | None:
    """Lee model_centroids_sha256 del KV metadata de un states/*.parquet.

    Devuelve None si el archivo no existe, no tiene KV o no tiene la clave
    (states pre-Etapa 6.1).
    """
    if not parquet_path.exists():
        return None
    try:
        import pyarrow.parquet as pq
        meta = pq.read_metadata(parquet_path)
        if not meta.metadata:
            return None
        kv = {k.decode(): v.decode() for k, v in meta.metadata.items()
              if not k.startswith(b"ARROW:")}
        return kv.get("model_centroids_sha256")
    except Exception:
        return None


def detect_states_stale() -> StageStatus:
    """states stale si:
      - events_p más nuevo que states_p (heurística mtime conservadora), Y
      - el SHA del modelo persistido en KV de states_p NO coincide con el
        SHA actual de los modelos PAC (Etapa 6.1: validación honesta).

    Lógica detallada por NR:
      1. Si events_p no existe → no aplicable.
      2. Si states_p no existe → stale (output missing).
      3. Si SHA persistido == SHA actual del modelo → vigente
         (incluso si events.mtime > states.mtime: significa que events
         cambió en cols que states no usa, ej. agregar morphotype).
      4. Si SHA persistido != SHA actual del modelo → stale por modelo.
      5. Si SHA persistido ausente (states pre-Etapa 6.1) → caer al
         comportamiento mtime: stale si events.mtime > states.mtime.
    """
    events_nrs = _list_nrs_events_edos()
    states_nrs = _list_nrs_in(STATES_DIR)
    current_sha = _compute_pac_models_sha256()

    stale_nrs: List[str] = []
    reasons: Dict[str, List[str]] = {}

    for nr in sorted(events_nrs):
        events_p = EVENTS_DIR / f"{nr}_edos.parquet"
        states_p = STATES_DIR / f"{nr}.parquet"
        if not states_p.exists():
            stale_nrs.append(nr)
            reasons[nr] = ["states output missing"]
            continue

        stored_sha = _read_states_models_sha256(states_p)

        if stored_sha is not None and current_sha is not None:
            # Etapa 6.1: validación honesta por SHA del modelo.
            if stored_sha != current_sha:
                stale_nrs.append(nr)
                reasons[nr] = [
                    f"pac_states model SHA changed "
                    f"(stored={stored_sha[:8]}.. current={current_sha[:8]}..)"
                ]
            # Si SHA coincide → vigente, no stale. Ignora mtime.
        else:
            # Fallback a mtime para states pre-Etapa 6.1 (sin KV) o si
            # falta el modelo en disk (current_sha None).
            states_mt = _mtime(states_p)
            rs = []
            if _mtime(events_p) > states_mt:
                rs.append("events mtime > states mtime (no SHA available)")
            model_paths = [MODELS_DIR / f for f in MODEL_FILES_PAC]
            if _max_mtime(model_paths) > states_mt:
                rs.append("pac_states model mtime > states mtime (no SHA)")
            if rs:
                stale_nrs.append(nr)
                reasons[nr] = rs

    return StageStatus(
        name="states",
        n_total=len(states_nrs),
        n_stale=len(stale_nrs),
        stale_nrs=stale_nrs,
        reasons=reasons,
    )


def detect_gold_stale() -> StageStatus:
    """
    gold stale si CUALQUIERA de:
      - alguna tabla gold/<t>.parquet falta
      - cualquier events/* o states/* es más nuevo que la tabla gold más vieja
      - cualquier scripts/build_*_gold.py es más nuevo que la tabla gold más vieja
      - models/MANIFEST.json es más nuevo (señal de bump de versión)
    """
    gold_paths = [GOLD_DIR / f"{t}.parquet" for t in GOLD_TABLES]
    missing_tables = [p.name.replace(".parquet", "") for p in gold_paths if not p.exists()]
    if missing_tables:
        return StageStatus(
            name="gold",
            n_total=len(GOLD_TABLES),
            n_stale=len(missing_tables),
            stale_nrs=missing_tables,
            reasons={t: ["gold table missing"] for t in missing_tables},
        )

    # Todas las tablas existen — comparar mtimes
    gold_mtimes = {p.name: _mtime(p) for p in gold_paths}
    oldest_gold_mtime = min(gold_mtimes.values())
    oldest_table = min(gold_mtimes, key=gold_mtimes.get)

    upstream_data = (
        list(EVENTS_DIR.glob("NR_*_edos.parquet"))
        + list(EVENTS_DIR.glob("NR_*_edo_curves.parquet"))
        + list(EVENTS_DIR.glob("NR_*_indices.parquet"))
        + list(STATES_DIR.glob("NR_*.parquet"))
    )
    upstream_max_data_mtime = _max_mtime(upstream_data) if upstream_data else float("-inf")

    upstream_scripts = [SCRIPTS_DIR / s for s in GOLD_BUILD_SCRIPTS]
    upstream_max_script_mtime = _max_mtime(upstream_scripts)

    manifest_mtime = _mtime(MANIFEST_PATH)

    reasons: List[str] = []
    if upstream_max_data_mtime > oldest_gold_mtime:
        reasons.append(
            f"upstream data mtime > {oldest_table} mtime"
        )
    if upstream_max_script_mtime > oldest_gold_mtime:
        reasons.append(
            f"build_*_gold.py mtime > {oldest_table} mtime"
        )
    if manifest_mtime > oldest_gold_mtime:
        reasons.append(
            f"models/MANIFEST.json mtime > {oldest_table} mtime"
        )

    if reasons:
        return StageStatus(
            name="gold",
            n_total=len(GOLD_TABLES),
            n_stale=1,  # gold es atómico: stale o no
            stale_nrs=["(rebuild all)"],
            reasons={"(rebuild all)": reasons},
        )

    return StageStatus(
        name="gold",
        n_total=len(GOLD_TABLES),
        n_stale=0,
        stale_nrs=[],
        reasons={},
    )


# --------------------------------------------------------------------- #
# Top-level
# --------------------------------------------------------------------- #


def detect_all() -> PipelineStatus:
    """Detección completa: las 4 etapas en orden."""
    return PipelineStatus(
        stages={
            "silver": detect_silver_stale(),
            "events": detect_events_stale(),
            "states": detect_states_stale(),
            "gold": detect_gold_stale(),
        }
    )


def _morpho_models_exist() -> bool:
    """True si todos los archivos del modelo de morfotipos (escalares) están presentes."""
    return all((MODELS_DIR / f).exists() for f in MODEL_FILES_MORPHO)


def _morpho_curve_models_exist() -> bool:
    """True si todos los archivos del modelo de morfotipos de curva están presentes."""
    return all((MODELS_DIR / f).exists() for f in MODEL_FILES_MORPHO_CURVE)


def _pac_states_models_exist() -> bool:
    """True si todos los archivos de los modelos PAC states están presentes."""
    return all((MODELS_DIR / f).exists() for f in MODEL_FILES_PAC)


def compute_plan(
    status: PipelineStatus,
    retrain_morpho: bool = False,
    retrain_states: bool = False,
) -> List[Dict[str, object]]:
    """
    Devuelve la lista ordenada de pasos a ejecutar para llevar el
    pipeline a estado limpio.

    Cada paso es un dict con:
      - "stage": nombre de la etapa
      - "label": descripción humana
      - "cmd": comando (lista de strings)
      - "n_stale": cuántos NRs están stale (informativo)

    Entrenamiento automático (bootstrap desde cero):
      - Si los modelos de morfotipos no existen, se agrega train_morphotypes.py
        antes de apply_morphotypes.py. El script elige K automáticamente.
      - Si los modelos de PAC states no existen, se agrega train_pac_states.py
        con los K históricos definidos en config.py (PAC_STATES_HISTORICAL_K).
        Para re-entrenar con K distinto, correr train_pac_states.py manualmente.

    Re-entrenamiento explícito (cuando modelos ya existen):
      - retrain_morpho=True → agrega train_morphotypes.py aunque el modelo exista.
      - retrain_states=True → agrega train_pac_states.py aunque el modelo exista.
      - Estos flags los setea orchestrate.py cuando el usuario confirma el re-entrenamiento.
    """
    plan: List[Dict[str, object]] = []

    # Política de propagación: si una etapa está stale, TODAS las
    # downstream también deben re-correrse aunque parezcan limpias
    # (porque al re-correr la upstream sus mtimes cambian).
    needs_silver = status.stages["silver"].is_stale_global
    needs_events = needs_silver or status.stages["events"].is_stale_global
    needs_states = needs_events or status.stages["states"].is_stale_global
    needs_gold = needs_states or status.stages["gold"].is_stale_global

    if needs_silver:
        plan.append({
            "stage": "silver",
            "label": "Silver QC (full batch — script no es per-NR)",
            "cmd": ["python", "-m", "pac.silver"],
            "n_stale": status.stages["silver"].n_stale,
        })
    if needs_events:
        # Events tiene 2 sub-pasos: pipeline (genera edos sin morphotype)
        # + apply_morphotypes (agrega columna morphotype). Plan los emite
        # como pasos separados para que falle ruidosamente si uno se rompe.
        plan.append({
            "stage": "events",
            "label": "Events pipeline (genera EDOs + indices)",
            "cmd": ["python", "-m", "pac.events_pipeline"],
            "n_stale": status.stages["events"].n_stale,
        })
        if not _morpho_models_exist():
            # Bootstrap: modelos de morfotipos ausentes → entrenar primero.
            # choose_k() elige K automáticamente (silhouette - 0.5×DB_norm).
            plan.append({
                "stage": "events",
                "label": "Train morphotypes (bootstrap — modelos ausentes, K auto)",
                "cmd": ["python", "scripts/train_morphotypes.py"],
                "n_stale": status.stages["events"].n_stale,
            })
        elif retrain_morpho:
            # Re-entrenamiento explícito solicitado por el usuario.
            plan.append({
                "stage": "events",
                "label": "Train morphotypes (re-entrenamiento con datos actualizados, K auto)",
                "cmd": ["python", "scripts/train_morphotypes.py"],
                "n_stale": status.stages["events"].n_stale,
            })
        plan.append({
            "stage": "events",
            "label": "Apply morphotypes (agrega columna morphotype a edos)",
            "cmd": ["python", "scripts/apply_morphotypes.py"],
            "n_stale": status.stages["events"].n_stale,
        })
        # Morfotipos de curva (shape-based, columna morphotype_curve).
        if not _morpho_curve_models_exist():
            plan.append({
                "stage": "events",
                "label": "Train morphotypes_curve (bootstrap — modelos ausentes, K=5 fijo)",
                "cmd": ["python", "scripts/train_morphotypes_curve.py"],
                "n_stale": status.stages["events"].n_stale,
            })
        elif retrain_morpho:
            plan.append({
                "stage": "events",
                "label": "Train morphotypes_curve (re-entrenamiento con datos actualizados)",
                "cmd": ["python", "scripts/train_morphotypes_curve.py"],
                "n_stale": status.stages["events"].n_stale,
            })
        plan.append({
            "stage": "events",
            "label": "Apply morphotypes_curve (agrega columna morphotype_curve a edos)",
            "cmd": ["python", "scripts/apply_morphotypes_curve.py"],
            "n_stale": status.stages["events"].n_stale,
        })
    if needs_states:
        if not _pac_states_models_exist() or retrain_states:
            from pac.config import PAC_STATES_HISTORICAL_K
            ks = PAC_STATES_HISTORICAL_K["s"]
            km = PAC_STATES_HISTORICAL_K["m"]
            kl = PAC_STATES_HISTORICAL_K["l"]
            label = (
                f"Train PAC states ({'re-entrenamiento con datos actualizados' if retrain_states else 'bootstrap — modelos ausentes'}, "
                f"K históricos: s={ks} m={km} l={kl})"
            )
            plan.append({
                "stage": "states",
                "label": label,
                "cmd": [
                    "python", "scripts/train_pac_states.py",
                    "--mode", "final",
                    "--k-s", str(ks),
                    "--k-m", str(km),
                    "--k-l", str(kl),
                ],
                "n_stale": status.stages["states"].n_stale,
            })
        # Validación post-fit: escribe validation_proceed en el gate.
        # Requerida siempre antes de apply_pac_states (entrenamiento nuevo o existente).
        plan.append({
            "stage": "states",
            "label": "Validate PAC states (post-fit checks C1–C5)",
            "cmd": ["python", "scripts/validate_pac_states.py"],
            "n_stale": status.stages["states"].n_stale,
        })
        plan.append({
            "stage": "states",
            "label": "Apply PAC States (batch)",
            "cmd": ["python", "scripts/apply_pac_states.py", "--mode", "batch"],
            "n_stale": status.stages["states"].n_stale,
        })
    if needs_gold:
        plan.append({
            "stage": "gold",
            "label": "Generate manifest (models/MANIFEST.json)",
            "cmd": ["python", "scripts/generate_manifest.py", "--force"],
            "n_stale": status.stages["gold"].n_stale,
        })
        plan.append({
            "stage": "gold",
            "label": "Build Gold (5 tablas + 2 sidecars)",
            "cmd": ["python", "scripts/build_gold_all.py", "--quiet"],
            "n_stale": status.stages["gold"].n_stale,
        })

    return plan


def render_status_text(status: PipelineStatus, verbose: bool = False) -> str:
    """Pretty-print del estado del pipeline para humanos."""
    lines = []
    lines.append("=" * 70)
    lines.append("PAC_v2 — Pipeline Status")
    lines.append("=" * 70)
    for name in ["silver", "events", "states", "gold"]:
        st = status.stages[name]
        if st.is_stale_global:
            symbol = "✗"
            tag = f"STALE ({st.n_stale}/{st.n_total})"
        else:
            symbol = "✓"
            tag = f"OK ({st.n_total} present)"
        lines.append(f"  {symbol} {name:8s} {tag}")
        if verbose and st.is_stale_global:
            for nr in st.stale_nrs[:5]:
                rs = ", ".join(st.reasons.get(nr, []))
                lines.append(f"      - {nr}: {rs}")
            if len(st.stale_nrs) > 5:
                lines.append(f"      ... y {len(st.stale_nrs) - 5} más")
    lines.append("=" * 70)
    if status.is_clean:
        lines.append("✓ Todo up-to-date — no hay nada para hacer.")
    else:
        lines.append(f"✗ {len(status.stale_stages)} etapa(s) stale: {', '.join(status.stale_stages)}")
    return "\n".join(lines)


def render_plan_text(plan: List[Dict[str, object]]) -> str:
    """Pretty-print del plan."""
    if not plan:
        return "Plan: (vacío — pipeline limpio)"
    lines = ["Plan de ejecución:"]
    for i, step in enumerate(plan, 1):
        lines.append(
            f"  {i}. [{step['stage']:7s}] {step['label']}  "
            f"(n_stale={step['n_stale']})"
        )
        lines.append(f"        $ {' '.join(step['cmd'])}")
    return "\n".join(lines)
