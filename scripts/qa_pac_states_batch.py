"""
PAC_v2 — Etapa 4 paso 8: validación + QA del labeling batch.

Recorre los 560 `states/<NR>.parquet` generados por apply_pac_states.py
y corre 5 checks de consistencia:

  B1  schema_lock_per_night     — todas las noches tienen las 15 OUTPUT_COLS
                                  con dtypes idénticos.
  B2  temporal_coverage         — ratio sum(t_end_s - t_start_s) / max(t_end_s)
                                  por escala. ≈1.0 esperado.
                                  FAIL <0.85 · WARN <0.95 · PASS ≥0.95.
  B3  per_night_cluster_dominance — ninguna noche debería tener un solo
                                  cluster acaparando >95% de sus ventanas
                                  en cualquier escala. WARN si pasa.
  B4  dist_to_centroid_outliers — flagea noches donde >20% de ventanas
                                  están en el top-5% global de
                                  dist_to_centroid (por escala).
                                  WARN no bloqueante (puede ser noche
                                  clínicamente atípica).
  B5  cross_scale_consistency   — para cada l-window, mide la coherencia
                                  (1 - entropy/log2(K)) de las m-windows y
                                  s-windows que solapa. Mean coherence
                                  global por escala-par.
                                  WARN si mean coherence < 0.3 (mucha
                                  diversidad → escalas desconectadas).

Decisiones cerradas (Q1..Q5=A, Roberto):
  Q1=A: B5 incluido (validación clave del PAC multi-escala).
  Q2=A: B4 outlier flagging por-escala (no global cross-scale).
  Q3=A: persistir CSV per-night auxiliar (560 filas).
  Q4=A: tests sobre las funciones de check.
  Q5=A: script independiente (no auto-ejecutado por apply).

Gate:
  B1 + B2 FAIL → bloquea Etapa 5 (gold).
  B3 + B4 + B5 WARN → no bloqueante (informativo).

Outputs:
  reports/pac_states_apply_qa.md   — resumen humano por check + tablas
  reports/pac_states_apply_qa.json — máquina; lista NR_ids flagged
  reports/pac_states_apply_qa.csv  — 1 fila × NR_id × ~14 cols flag
  Actualiza pac_states_batch_gate.json con `apply_qa_proceed`.

Corre:
  PYTHONPATH=src python scripts/qa_pac_states_batch.py
  PYTHONPATH=src python scripts/qa_pac_states_batch.py --limit 10  # smoke
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Importar OUTPUT_COLS del script apply_pac_states.py (fuente única de verdad).
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import apply_pac_states as ap  # noqa: E402

from pac.config import (
    PAC_STATE_SCALES,
    REPORTS_DIR,
    STATES_DIR,
)


# Outputs.
QA_MD = REPORTS_DIR / "pac_states_apply_qa.md"
QA_JSON = REPORTS_DIR / "pac_states_apply_qa.json"
QA_CSV = REPORTS_DIR / "pac_states_apply_qa.csv"
BATCH_GATE_JSON = REPORTS_DIR / "pac_states_batch_gate.json"
# Listas auxiliares (Q1+Q2, Roberto):
B2_FAIL_EXCLUDED_JSON = REPORTS_DIR / "b2_fail_excluded.json"
FLAG_FOR_REVIEW_CSV = REPORTS_DIR / "pac_states_flag_for_review.csv"
# Cross-check: silver QC summary (para validar que las 7 B2 FAIL son known-bad).
SILVER_QC_CSV = REPORTS_DIR / "silver_qc_summary.csv"

# Schema canónico (de apply_pac_states.OUTPUT_COLS).
EXPECTED_COLS = list(ap.OUTPUT_COLS)
EXPECTED_DTYPES = {
    "night_record_id":  "object",
    "scale":            "object",
    "window_idx":       "int64",
    "t_start":          "datetime64[ns]",
    "t_end":            "datetime64[ns]",
    "t_start_s":        "float64",
    "t_end_s":          "float64",
    "state_label":      "object",
    "cluster_int":      "int64",
    "dist_to_centroid": "float64",
    "coverage":         "float64",
    "frac_wake":        "float64",
    "frac_light_sleep": "float64",
    "frac_deep_sleep":  "float64",
    "training_eligible": "bool",
}

# Umbrales (exhibidos en el reporte).
B2_FAIL_RATIO = 0.85
B2_WARN_RATIO = 0.95
B3_MAX_DOMINANCE = 0.95
B4_OUTLIER_PCTL = 95         # define "outlier" = top 5% global
B4_OUTLIER_FRAC_THRESHOLD = 0.20
B5_COHERENCE_WARN = 0.30


# ---------------------------------------------------------------------------
# Helpers de carga
# ---------------------------------------------------------------------------
def list_states_files(states_dir: Path, limit: int | None = None) -> list[Path]:
    """Lista parquets válidos (excluye .gitkeep, _qc, etc)."""
    paths = sorted(
        p for p in states_dir.glob("NR_*.parquet")
        if not p.stem.endswith("_qc")
    )
    if limit:
        paths = paths[:limit]
    return paths


# ---------------------------------------------------------------------------
# B1  schema_lock_per_night
# ---------------------------------------------------------------------------
def check_b1_schema_lock(paths: list[Path]) -> dict:
    """Verifica que todos los parquets tengan EXPECTED_COLS y dtypes."""
    violators: list[dict] = []
    for p in paths:
        try:
            df = pd.read_parquet(p)
        except Exception as e:
            violators.append({
                "nr": p.stem, "issue": f"read_error: {type(e).__name__}: {e}",
            })
            continue

        missing = [c for c in EXPECTED_COLS if c not in df.columns]
        extra = [c for c in df.columns if c not in EXPECTED_COLS]
        if missing or extra:
            violators.append({
                "nr": p.stem, "issue": "cols_mismatch",
                "missing": missing, "extra": extra,
            })
            continue

        # Dtype check (best-effort: pandas dtype name).
        bad_dtypes = []
        for col, expected in EXPECTED_DTYPES.items():
            actual = str(df[col].dtype)
            # datetime64 admite [ns] o [us] como variantes equivalentes.
            if expected.startswith("datetime64"):
                if not actual.startswith("datetime64"):
                    bad_dtypes.append((col, expected, actual))
            elif actual != expected:
                bad_dtypes.append((col, expected, actual))
        if bad_dtypes:
            violators.append({
                "nr": p.stem, "issue": "dtype_mismatch",
                "diffs": bad_dtypes,
            })

    status = "FAIL" if violators else "PASS"
    detail = (
        f"{len(violators)} violadores" if violators
        else f"{len(paths)} noches con schema canónico"
    )
    return {
        "id": "B1", "name": "schema_lock_per_night",
        "status": status, "detail": detail,
        "n_total": len(paths),
        "n_violators": len(violators),
        "violators": violators[:50],  # cap
    }


# ---------------------------------------------------------------------------
# B2  temporal_coverage
# ---------------------------------------------------------------------------
def compute_b2_coverage_for_night(df: pd.DataFrame) -> dict[str, float]:
    """coverage_ratio por escala = sum(window_seconds) / max(t_end_s)."""
    out = {}
    for scale in PAC_STATE_SCALES:
        sub = df[df["scale"] == scale]
        if len(sub) == 0:
            out[scale] = float("nan")
            continue
        total_window_s = float((sub["t_end_s"] - sub["t_start_s"]).sum())
        span_s = float(sub["t_end_s"].max())
        out[scale] = total_window_s / span_s if span_s > 0 else float("nan")
    return out


def b2_status_from_ratio(ratio: float) -> str:
    if pd.isna(ratio):
        return "WARN"
    if ratio < B2_FAIL_RATIO:
        return "FAIL"
    if ratio < B2_WARN_RATIO:
        return "WARN"
    return "PASS"


# ---------------------------------------------------------------------------
# B3  per_night_cluster_dominance
# ---------------------------------------------------------------------------
def compute_b3_dominance_for_night(df: pd.DataFrame) -> dict[str, float]:
    """Máxima fracción de un solo cluster por escala (sobre rows con cluster≥0)."""
    out = {}
    for scale in PAC_STATE_SCALES:
        sub = df[(df["scale"] == scale) & (df["cluster_int"] >= 0)]
        if len(sub) == 0:
            out[scale] = float("nan")
            continue
        counts = sub["state_label"].value_counts(normalize=True)
        out[scale] = float(counts.max()) if len(counts) > 0 else float("nan")
    return out


# ---------------------------------------------------------------------------
# B4  dist_to_centroid_outliers
# ---------------------------------------------------------------------------
def compute_b4_global_thresholds(
    paths: list[Path], pctl: float = B4_OUTLIER_PCTL,
) -> dict[str, float]:
    """Pasada 1: percentil global de dist_to_centroid por escala."""
    bag: dict[str, list[float]] = {s: [] for s in PAC_STATE_SCALES}
    for p in paths:
        df = pd.read_parquet(p, columns=["scale", "cluster_int", "dist_to_centroid"])
        for scale in PAC_STATE_SCALES:
            sub = df[(df["scale"] == scale) & (df["cluster_int"] >= 0)]
            if len(sub) > 0:
                bag[scale].extend(sub["dist_to_centroid"].dropna().tolist())
    return {
        s: float(np.percentile(v, pctl)) if v else float("nan")
        for s, v in bag.items()
    }


def compute_b4_outlier_frac_for_night(
    df: pd.DataFrame, thresholds: dict[str, float],
) -> dict[str, float]:
    """Fracción de ventanas con dist > p_global por escala."""
    out = {}
    for scale in PAC_STATE_SCALES:
        sub = df[(df["scale"] == scale) & (df["cluster_int"] >= 0)]
        if len(sub) == 0 or pd.isna(thresholds.get(scale)):
            out[scale] = 0.0
            continue
        thr = thresholds[scale]
        out[scale] = float((sub["dist_to_centroid"] > thr).mean())
    return out


# ---------------------------------------------------------------------------
# B5  cross_scale_consistency
# ---------------------------------------------------------------------------
def _coherence_index(labels: pd.Series, k_max: int) -> float:
    """1 - entropy(labels, base=2) / log2(k_max). 1=homogéneo, 0=máx diverso."""
    if len(labels) == 0 or k_max < 2:
        return float("nan")
    counts = labels.value_counts().to_numpy()
    probs = counts / counts.sum()
    entropy = float(-np.sum(probs * np.log2(probs + 1e-12)))
    max_entropy = float(np.log2(k_max))
    return 1.0 - entropy / max_entropy if max_entropy > 0 else 1.0


def compute_b5_coherence_for_night(
    df: pd.DataFrame, k_per_scale: dict[str, int],
) -> dict[str, float]:
    """
    Para cada l-window, computa coherencia de las m-windows y s-windows que
    solapan (por intervalo [t_start_s, t_end_s)).
    Retorna {coh_l_vs_m: float, coh_l_vs_s: float} (mean across l-windows).
    """
    l_df = df[(df["scale"] == "l") & (df["cluster_int"] >= 0)]
    m_df = df[(df["scale"] == "m") & (df["cluster_int"] >= 0)]
    s_df = df[(df["scale"] == "s") & (df["cluster_int"] >= 0)]

    if len(l_df) == 0 or len(m_df) == 0 or len(s_df) == 0:
        return {"coh_l_vs_m": float("nan"), "coh_l_vs_s": float("nan")}

    coh_m = []
    coh_s = []
    for _, lw in l_df.iterrows():
        t0, t1 = lw["t_start_s"], lw["t_end_s"]
        m_in = m_df[(m_df["t_start_s"] >= t0) & (m_df["t_start_s"] < t1)]
        s_in = s_df[(s_df["t_start_s"] >= t0) & (s_df["t_start_s"] < t1)]
        if len(m_in) > 0:
            coh_m.append(_coherence_index(m_in["state_label"], k_per_scale["m"]))
        if len(s_in) > 0:
            coh_s.append(_coherence_index(s_in["state_label"], k_per_scale["s"]))

    return {
        "coh_l_vs_m": float(np.nanmean(coh_m)) if coh_m else float("nan"),
        "coh_l_vs_s": float(np.nanmean(coh_s)) if coh_s else float("nan"),
    }


# ---------------------------------------------------------------------------
# Cross-check con silver_qc (Q1=A, Roberto)
# ---------------------------------------------------------------------------
def cross_check_b2_with_silver_qc(
    b2_fail_nrs: list[str],
    silver_qc_path: Path = SILVER_QC_CSV,
) -> dict:
    """
    Verifica si las noches B2-FAIL ya están marcadas como bad-coverage
    en silver_qc. Si TODAS están conocidas, el gate puede relajarse a
    PROCEED (la detección es redundante con QC anterior).

    Devuelve:
      {
        "all_known_bad": bool,
        "known_bad": [<NRs flagged in silver_qc>],
        "unknown_bad": [<NRs FAIL en B2 pero PASS en silver_qc>],
        "silver_qc_available": bool,
      }
    """
    if not silver_qc_path.exists():
        return {
            "all_known_bad": False,
            "known_bad": [],
            "unknown_bad": list(b2_fail_nrs),
            "silver_qc_available": False,
        }
    qc = pd.read_csv(silver_qc_path)
    sub = qc[qc["night_record_id"].isin(b2_fail_nrs)]
    # known-bad si qc_coverage_ok=False O qc_max_gap_ok=False
    known_bad_mask = (~sub["qc_coverage_ok"].astype(bool)) | (~sub["qc_max_gap_ok"].astype(bool))
    known_bad = sub.loc[known_bad_mask, "night_record_id"].tolist()
    unknown_bad = [nr for nr in b2_fail_nrs if nr not in known_bad]
    return {
        "all_known_bad": len(unknown_bad) == 0 and len(b2_fail_nrs) > 0,
        "known_bad": known_bad,
        "unknown_bad": unknown_bad,
        "silver_qc_available": True,
    }


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------
def run_qa(
    states_dir: Path = STATES_DIR,
    limit: int | None = None,
    verbose: bool = False,
) -> tuple[dict, pd.DataFrame]:
    """Corre los 5 checks. Devuelve (report_dict, per_night_df)."""
    paths = list_states_files(states_dir, limit=limit)
    if not paths:
        raise SystemExit(f"[qa] no se encontraron states/*.parquet en {states_dir}")
    print(f"[qa] {len(paths)} noches a chequear …")

    # Detectar K_per_scale del primer parquet (KV metadata).
    import pyarrow.parquet as pq
    first_tbl = pq.read_table(paths[0])
    kv = {k.decode(): v.decode() for k, v in (first_tbl.schema.metadata or {}).items()
          if not k.startswith(b"pandas")}
    k_per_scale = json.loads(kv.get("k_per_scale", "{}"))
    if not k_per_scale:
        # Fallback: inferir del max(cluster_int) por escala.
        df0 = first_tbl.to_pandas()
        k_per_scale = {
            s: int(df0[df0["scale"] == s]["cluster_int"].max() + 1)
            for s in PAC_STATE_SCALES
        }
    print(f"[qa] K detectado: {k_per_scale}")

    # B1  schema lock
    print("[qa] B1 schema_lock …")
    b1 = check_b1_schema_lock(paths)

    # B4 needs global thresholds first (one extra pass).
    print(f"[qa] B4 calculando p{B4_OUTLIER_PCTL} global por escala …")
    b4_thresholds = compute_b4_global_thresholds(paths)
    print(f"        thresholds: {b4_thresholds}")

    # Pasada principal: B2/B3/B4/B5 por noche.
    rows = []
    t0 = time.time()
    for i, p in enumerate(paths, start=1):
        nr = p.stem
        df = pd.read_parquet(p)
        b2 = compute_b2_coverage_for_night(df)
        b3 = compute_b3_dominance_for_night(df)
        b4 = compute_b4_outlier_frac_for_night(df, b4_thresholds)
        b5 = compute_b5_coherence_for_night(df, k_per_scale)

        row = {"nr": nr,
               "n_windows_s": int((df["scale"] == "s").sum()),
               "n_windows_m": int((df["scale"] == "m").sum()),
               "n_windows_l": int((df["scale"] == "l").sum())}
        for scale in PAC_STATE_SCALES:
            row[f"b2_coverage_{scale}"] = round(b2[scale], 4)
            row[f"b3_max_dom_{scale}"] = round(b3[scale], 4)
            row[f"b4_outlier_frac_{scale}"] = round(b4[scale], 4)
        row["b5_coh_l_vs_m"] = (round(b5["coh_l_vs_m"], 4)
                                if not np.isnan(b5["coh_l_vs_m"]) else None)
        row["b5_coh_l_vs_s"] = (round(b5["coh_l_vs_s"], 4)
                                if not np.isnan(b5["coh_l_vs_s"]) else None)

        # Flags por noche.
        row["flag_b2"] = any(
            b2_status_from_ratio(b2[s]) in ("FAIL", "WARN")
            for s in PAC_STATE_SCALES
        )
        row["flag_b3"] = any(
            (not pd.isna(b3[s])) and (b3[s] > B3_MAX_DOMINANCE)
            for s in PAC_STATE_SCALES
        )
        row["flag_b4"] = any(
            b4[s] > B4_OUTLIER_FRAC_THRESHOLD for s in PAC_STATE_SCALES
        )
        rows.append(row)

        if verbose or i % 50 == 0 or i == len(paths):
            print(f"  [{i:4d}/{len(paths)}] {nr}: "
                  f"cov={b2} dom={b3} out={b4}")
    elapsed = time.time() - t0

    per_night = pd.DataFrame(rows)

    # Agregados B2/B3/B4/B5 globales.
    b2_status_per_night = per_night.apply(
        lambda r: max(
            (b2_status_from_ratio(r[f"b2_coverage_{s}"])
             for s in PAC_STATE_SCALES),
            key=lambda x: {"PASS": 0, "WARN": 1, "FAIL": 2}[x],
        ),
        axis=1,
    )
    b2 = {
        "id": "B2", "name": "temporal_coverage",
        "status": "FAIL" if (b2_status_per_night == "FAIL").any()
                  else "WARN" if (b2_status_per_night == "WARN").any()
                  else "PASS",
        "detail": (
            f"{(b2_status_per_night == 'FAIL').sum()} FAIL · "
            f"{(b2_status_per_night == 'WARN').sum()} WARN · "
            f"{(b2_status_per_night == 'PASS').sum()} PASS"
        ),
        "thresholds": {"FAIL_below": B2_FAIL_RATIO, "WARN_below": B2_WARN_RATIO},
        "violators_fail": per_night.loc[b2_status_per_night == "FAIL", "nr"].tolist()[:50],
        "violators_warn": per_night.loc[b2_status_per_night == "WARN", "nr"].tolist()[:50],
    }

    n_b3 = int(per_night["flag_b3"].sum())
    b3_check = {
        "id": "B3", "name": "per_night_cluster_dominance",
        "status": "WARN" if n_b3 > 0 else "PASS",
        "detail": f"{n_b3} noches con un cluster >{B3_MAX_DOMINANCE * 100:.0f}% en alguna escala",
        "threshold": B3_MAX_DOMINANCE,
        "violators": per_night.loc[per_night["flag_b3"], "nr"].tolist()[:50],
    }

    n_b4 = int(per_night["flag_b4"].sum())
    b4_check = {
        "id": "B4", "name": "dist_to_centroid_outliers",
        "status": "WARN" if n_b4 > 0 else "PASS",
        "detail": (
            f"{n_b4} noches con >{B4_OUTLIER_FRAC_THRESHOLD * 100:.0f}% "
            f"de ventanas en top-{100 - B4_OUTLIER_PCTL}% de dist por escala"
        ),
        "thresholds_p95_per_scale": {s: round(b4_thresholds[s], 4)
                                      for s in PAC_STATE_SCALES},
        "outlier_frac_threshold": B4_OUTLIER_FRAC_THRESHOLD,
        "violators": per_night.loc[per_night["flag_b4"], "nr"].tolist()[:50],
    }

    coh_lm_mean = float(np.nanmean(per_night["b5_coh_l_vs_m"].astype(float)))
    coh_ls_mean = float(np.nanmean(per_night["b5_coh_l_vs_s"].astype(float)))
    b5_check = {
        "id": "B5", "name": "cross_scale_consistency",
        "status": ("WARN" if (coh_lm_mean < B5_COHERENCE_WARN
                              or coh_ls_mean < B5_COHERENCE_WARN)
                   else "PASS"),
        "detail": (f"mean coherence l-vs-m={coh_lm_mean:.3f} · "
                   f"l-vs-s={coh_ls_mean:.3f} · umbral={B5_COHERENCE_WARN}"),
        "mean_coh_l_vs_m": round(coh_lm_mean, 4),
        "mean_coh_l_vs_s": round(coh_ls_mean, 4),
        "threshold_warn_below": B5_COHERENCE_WARN,
    }

    # ── Cross-check Q1=A: si TODAS las B2-FAIL son known-bad en silver_qc,
    # bajamos el bloqueo (la detección es redundante con QC anterior).
    b2_fail_nrs = b2["violators_fail"]
    cc = cross_check_b2_with_silver_qc(b2_fail_nrs)
    b2["cross_check_silver_qc"] = cc
    if b2["status"] == "FAIL" and cc["all_known_bad"]:
        b2["status_original"] = "FAIL"
        b2["status"] = "WARN"
        b2["detail"] += (
            f" (downgraded FAIL→WARN: las {len(cc['known_bad'])} noches ya están "
            f"flagged en silver_qc)"
        )

    # Gate final.
    gate_blocking = b1["status"] == "FAIL" or b2["status"] == "FAIL"
    any_warn = any(c["status"] == "WARN" for c in (b2, b3_check, b4_check, b5_check))
    gate = {
        "apply_qa_proceed": not gate_blocking,
        "apply_qa_all_ok": not gate_blocking and not any_warn,
        "n_fail_blocking": int(gate_blocking),
        "n_warn": int(any_warn),
    }

    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "states_dir": str(states_dir),
        "n_nights": len(paths),
        "k_per_scale": k_per_scale,
        "elapsed_s": round(elapsed, 2),
        "checks": {"B1": b1, "B2": b2, "B3": b3_check,
                   "B4": b4_check, "B5": b5_check},
        "gate": gate,
    }
    return report, per_night


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------
def _emoji(status: str) -> str:
    return {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}.get(status, "?")


def render_markdown(report: dict, per_night: pd.DataFrame) -> str:
    g = report["gate"]
    if g["apply_qa_all_ok"]:
        gate_msg = "✓ **PASS** — todos los checks verdes; avanzar a Etapa 5."
    elif g["apply_qa_proceed"]:
        gate_msg = ("⚠ **PROCEED con warnings** — sin FAIL bloqueante. "
                    "Revisar warnings antes de Etapa 5.")
    else:
        gate_msg = "✗ **BLOCKED** — FAIL en B1 o B2. Revisar antes de Etapa 5."

    lines = [
        "# PAC_v2 — QA del labeling batch (Etapa 4 paso 8)",
        "",
        f"**Timestamp:** `{report['timestamp']}`  ",
        f"**Noches chequeadas:** {report['n_nights']}  ",
        f"**K por escala:** {report['k_per_scale']}  ",
        f"**Elapsed:** {report['elapsed_s']}s  ",
        f"**Gate:** {gate_msg}",
        "",
        "## Checks",
        "",
        "| ID | Check | Status | Detalle |",
        "|----|-------|:------:|---------|",
    ]
    for cid, c in report["checks"].items():
        lines.append(
            f"| {c['id']} | {c['name']} | "
            f"{_emoji(c['status'])} {c['status']} | {c['detail']} |"
        )
    lines.append("")

    # Distribución de flags
    n_total = len(per_night)
    n_b2 = int(per_night["flag_b2"].sum())
    n_b3 = int(per_night["flag_b3"].sum())
    n_b4 = int(per_night["flag_b4"].sum())
    lines.append("## Distribución de flags por noche")
    lines.append("")
    lines.append(f"- **flag_b2** (cobertura<{B2_WARN_RATIO}): "
                 f"{n_b2}/{n_total} ({100 * n_b2 / n_total:.1f}%)")
    lines.append(f"- **flag_b3** (cluster dominante >{B3_MAX_DOMINANCE * 100:.0f}%): "
                 f"{n_b3}/{n_total} ({100 * n_b3 / n_total:.1f}%)")
    lines.append(f"- **flag_b4** (>{B4_OUTLIER_FRAC_THRESHOLD * 100:.0f}% en top-"
                 f"{100 - B4_OUTLIER_PCTL}% dist): "
                 f"{n_b4}/{n_total} ({100 * n_b4 / n_total:.1f}%)")
    lines.append("")

    # Cross-scale coherence interpretation
    b5 = report["checks"]["B5"]
    lines.append("## Interpretación de B5 (cross-scale coherence)")
    lines.append("")
    lines.append(f"- `coh_l_vs_m`={b5['mean_coh_l_vs_m']}: "
                 "mean coherencia de m-states dentro de cada l-window. "
                 "Cercano a 1.0 = m anidada, escalas redundantes-zoomeables. "
                 "Cercano a 0 = m diversa, captura sub-estructura no visible en l.")
    lines.append(f"- `coh_l_vs_s`={b5['mean_coh_l_vs_s']}: ídem para s-states.")
    lines.append("")
    lines.append("**Lectura PAC**: coherencia *moderada* (0.3-0.6) es lo deseable: "
                 "las escalas se relacionan pero no son redundantes. "
                 "Coherencia muy alta (>0.8) sugiere que una escala es redundante "
                 "y podría descartarse. Coherencia muy baja (<0.2) sugiere que las "
                 "escalas describen fenómenos independientes y no son comparables.")
    lines.append("")

    # Cross-check B2 con silver_qc (si aplica)
    b2 = report["checks"]["B2"]
    cc = b2.get("cross_check_silver_qc")
    if cc and cc.get("silver_qc_available"):
        lines.append("## Cross-check B2 ↔ silver_qc")
        lines.append("")
        lines.append(f"- noches B2-FAIL: **{len(b2['violators_fail'])}**")
        lines.append(f"- ya marcadas en silver_qc (qc_coverage_ok=False ó qc_max_gap_ok=False): "
                     f"**{len(cc['known_bad'])}**")
        lines.append(f"- **NO** previamente flagged: **{len(cc['unknown_bad'])}**")
        if cc["all_known_bad"]:
            lines.append("")
            lines.append("✓ **Detección redundante con silver_qc** — gate B2 "
                         "*downgraded* FAIL→WARN. Lista persistida en "
                         "`reports/b2_fail_excluded.json` para exclusión en Etapa 5.")
        elif cc["unknown_bad"]:
            lines.append("")
            lines.append("⚠ Hay noches B2-FAIL **no** detectadas por silver_qc: "
                         f"{cc['unknown_bad']} — investigar antes de Etapa 5.")
        lines.append("")

    # Listas auxiliares persistidas
    lines.append("## Listas auxiliares persistidas")
    lines.append("")
    lines.append("- `reports/b2_fail_excluded.json` — exclusión obligatoria en Etapa 5 (gold).")
    lines.append("- `reports/pac_states_flag_for_review.csv` — noches B3∪B4 a revisar "
                 "en paso 8.5 (dashboard de stratigraphy) y a tratar con cuidado en gold "
                 "(p. ej. peso reducido o cohorte separado).")
    lines.append("")

    # Top violators (si hay)
    for c in report["checks"].values():
        viols = c.get("violators") or c.get("violators_fail") or []
        if viols:
            lines.append(f"### {c['id']} — primeros violadores ({len(viols)} mostrados)")
            lines.append("")
            for nr in viols[:20]:
                lines.append(f"- `{nr}`")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Etapa 4 paso 8: QA del labeling batch."
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Si se pasa, chequea sólo las primeras N noches (smoke).")
    parser.add_argument("--states-dir", type=Path, default=STATES_DIR)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report, per_night = run_qa(
        states_dir=args.states_dir,
        limit=args.limit,
        verbose=args.verbose,
    )

    # Persist outputs.
    with open(QA_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    md = render_markdown(report, per_night)
    with open(QA_MD, "w", encoding="utf-8") as f:
        f.write(md)
    per_night.to_csv(QA_CSV, index=False)

    print(f"\n[qa] reporte md:  {QA_MD.name}")
    print(f"[qa] reporte json: {QA_JSON.name}")
    print(f"[qa] csv per-night: {QA_CSV.name}")

    # Q1=A: lista de exclusión para Etapa 5 (gold).
    b2_check = report["checks"]["B2"]
    b2_excluded = {
        "timestamp": report["timestamp"],
        "reason": "B2 temporal_coverage FAIL — known-bad en silver_qc (cobertura/gap).",
        "n_excluded": len(b2_check["violators_fail"]),
        "night_record_ids": b2_check["violators_fail"],
        "cross_check_silver_qc": b2_check.get("cross_check_silver_qc", {}),
    }
    with open(B2_FAIL_EXCLUDED_JSON, "w", encoding="utf-8") as f:
        json.dump(b2_excluded, f, indent=2, ensure_ascii=False)
    print(f"[qa] exclusión B2 (gold): {B2_FAIL_EXCLUDED_JSON.name} "
          f"({b2_excluded['n_excluded']} noches)")

    # Q2=A: noches flag B3∪B4 para review en paso 8.5 + atención en gold.
    review_mask = per_night["flag_b3"] | per_night["flag_b4"]
    review_df = per_night.loc[review_mask, [
        "nr", "n_windows_s", "n_windows_m", "n_windows_l",
        "b3_max_dom_s", "b3_max_dom_m", "b3_max_dom_l",
        "b4_outlier_frac_s", "b4_outlier_frac_m", "b4_outlier_frac_l",
        "flag_b3", "flag_b4",
    ]].copy()
    review_df["review_reason"] = (
        review_df["flag_b3"].map({True: "dominance", False: ""}) + "+" +
        review_df["flag_b4"].map({True: "outliers", False: ""})
    ).str.strip("+")
    review_df.to_csv(FLAG_FOR_REVIEW_CSV, index=False)
    print(f"[qa] flags review (gold-attention): {FLAG_FOR_REVIEW_CSV.name} "
          f"({len(review_df)} noches B3∪B4)")

    # Update batch_gate.json
    if BATCH_GATE_JSON.exists():
        with open(BATCH_GATE_JSON, encoding="utf-8") as f:
            bg = json.load(f)
    else:
        bg = {}
    bg["apply_qa_timestamp"] = report["timestamp"]
    bg["apply_qa_proceed"] = report["gate"]["apply_qa_proceed"]
    bg["apply_qa_all_ok"] = report["gate"]["apply_qa_all_ok"]
    bg["apply_qa_n_warn"] = report["gate"]["n_warn"]
    with open(BATCH_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(bg, f, indent=2, ensure_ascii=False)
    print(f"[qa] batch_gate actualizado: {BATCH_GATE_JSON.name}")

    # Resumen
    g = report["gate"]
    print()
    print(f"[qa] gate: proceed={g['apply_qa_proceed']} · "
          f"all_ok={g['apply_qa_all_ok']} · n_warn={g['n_warn']}")
    for cid, c in report["checks"].items():
        print(f"         {cid} {c['name']}: {c['status']} — {c['detail']}")


if __name__ == "__main__":
    main()
