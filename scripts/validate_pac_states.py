"""
PAC_v2 — Etapa 4 paso 5 (validación post-fit): 5 checks sobre los modelos
de estados PAC ya persistidos en models/.

Checks:
  C1  cluster_sizes       — escalonado: FAIL <0.3%, WARN [0.3, 2)%, PASS ≥2%.
                            Distingue cluster degenerado (FAIL bloqueante) de
                            cluster pequeño-pero-válido (WARN, outlier clínico).
  C2  centroid_separation — distancia min entre centroides z-space ≥ 1.0.
  C3  morphotype_coherence— PASS si diversity ≥ 0.5 o rango n_edos_total ≥ 1.0.
                            Combina dominante (idxmax) + intensidad total.
  C4  sleep_coherence     — ≥1 cluster con frac_light>0.3 y ≥1 con frac_deep>0.3
                            (excepción: escala s, deep opcional).
                            NO exige cluster wake-dominante: el training mask
                            Q6=C excluye wake por diseño (frac_wake≤0.5).
  C5  physiological_ranges— centroides de-normalizados en rangos fisiológicos
                            con tolerancia epsilon=1e-3 para roundoff de -0.0.

Gate:
  C1, C5 FAIL → bloquea avance a paso 7 (apply_pac_states).
  C2..C4 WARN → avisa pero no bloquea.

Output:
  reports/pac_states_validation.md   (human-readable, tabla por escala)
  reports/pac_states_validation.json (machine-readable, para CI)
  Actualiza reports/pac_states_batch_gate.json con `validation_all_ok`.

Corre:
  PYTHONPATH=src python scripts/validate_pac_states.py
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from pac import states as st
from pac.config import (
    MODELS_DIR,
    PAC_STATE_PREFIXES,
    PAC_STATE_SCALES,
    REPORTS_DIR,
)


TRAINING_REPORT_JSON = REPORTS_DIR / "pac_states_training_report.json"
BATCH_GATE_JSON = REPORTS_DIR / "pac_states_batch_gate.json"
VALIDATION_MD = REPORTS_DIR / "pac_states_validation.md"
VALIDATION_JSON = REPORTS_DIR / "pac_states_validation.json"


# Umbrales (hardcoded — si hace falta parametrizar, pasar a config.py).
# C1 escalonado (Q1=A): FAIL si <0.3% (cluster degenerado), WARN si 0.3..2%
# (cluster pequeño pero válido — captura outliers clínicos), PASS si ≥2%.
C1_MIN_CLUSTER_PCT_FAIL = 0.3     # < 0.3% → FAIL (cluster degenerado)
C1_MIN_CLUSTER_PCT_PASS = 2.0     # ≥ 2.0% → PASS; en [0.3, 2.0) → WARN
C2_MIN_CENTROID_DIST = 1.0        # mínimo 1σ en z-space entre pares
C3_MIN_DOMINANT_DIVERSITY = 0.5   # ≥50% de clusters con morphotype dominante distinto
C3_MIN_NTOT_RANGE = 1.0           # rango de n_edos_total entre clusters (fallback)

# Tolerancia epsilon para C5 (Q2=A): centroides de KMeans en espacio
# original pueden producir -0.0 por roundoff de punto flotante en
# `centroid_z * std + mean`. Permitimos -1e-3 como cota inferior efectiva.
C5_EPSILON = 1e-3

# Rangos fisiológicos de centroides de-normalizados (C5)
# spo2_min relajado a [50, 100] (Q2=A): pacientes SAOS severos pueden
# sostener tramos con mínimos de 50-55%; cluster-outlier (ej. L3) es
# clínicamente válido y NO debería disparar FAIL.
PHYS_RANGES = {
    "spo2_mean": (70.0, 100.0),
    "spo2_min":  (50.0, 100.0),    # ← relajado de 60 a 50
    "spo2_max":  (70.0, 100.0),
    "spo2_p10":  (50.0, 100.0),    # ← relajado de 60 a 50
    "spo2_p90":  (70.0, 100.0),
    "spo2_std":  (0.0, 20.0),
    "hr_mean":   (40.0, 120.0),
    "hr_min":    (30.0, 120.0),
    "hr_max":    (40.0, 180.0),
    "hr_p10":    (30.0, 120.0),
    "hr_p90":    (40.0, 150.0),
    "hr_std":    (0.0, 30.0),
    "mov_mean":  (0.0, 1_000_000.0),
    "mov_std":   (0.0, 1_000_000.0),
    "mov_max":   (0.0, 1_000_000.0),
    # densidades morphotype: ≥ 0 (con epsilon) y razonables
    "n_edos_total":   (0.0, 1_000.0),
    "n_alpha":        (0.0, 1_000.0),
    "n_beta":         (0.0, 1_000.0),
    "n_gamma":        (0.0, 1_000.0),
    "n_delta":        (0.0, 1_000.0),
    "ird_mean_local": (0.0, 100.0),
    # sleep fractions ∈ [0, 1]
    "frac_wake":        (0.0, 1.0),
    "frac_light_sleep": (0.0, 1.0),
    "frac_deep_sleep":  (0.0, 1.0),
}


@dataclass
class CheckResult:
    check_id: str
    name: str
    status: str      # "PASS" / "WARN" / "FAIL"
    detail: str
    data: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_cluster_sizes(
    sizes_training: dict[str, int],
    fail_pct: float = C1_MIN_CLUSTER_PCT_FAIL,
    pass_pct: float = C1_MIN_CLUSTER_PCT_PASS,
) -> CheckResult:
    """C1 escalonado (Q1=A): FAIL <fail_pct · WARN [fail_pct, pass_pct) · PASS ≥pass_pct.

    Un cluster muy pequeño puede ser degenerado (FAIL <0.3%) o un outlier
    clínico válido (WARN 0.3-2%). Solo bloquea si hay clusters degenerados.
    """
    total = sum(sizes_training.values())
    if total == 0:
        return CheckResult("C1", "cluster_sizes", "FAIL",
                           "training total = 0",
                           {"sizes": sizes_training})

    pcts = {k: v / total * 100 for k, v in sizes_training.items()}
    fail_violators = {k: p for k, p in pcts.items() if p < fail_pct}
    warn_violators = {k: p for k, p in pcts.items()
                      if fail_pct <= p < pass_pct}

    if fail_violators:
        status = "FAIL"
    elif warn_violators:
        status = "WARN"
    else:
        status = "PASS"

    detail_bits = [
        f"min={min(pcts.values()):.2f}%",
        f"max={max(pcts.values()):.2f}%",
        f"umbral_FAIL<{fail_pct:.1f}%",
        f"umbral_PASS≥{pass_pct:.1f}%",
    ]
    if fail_violators:
        detail_bits.append(f"FAIL={list(fail_violators.keys())}")
    if warn_violators:
        detail_bits.append(f"WARN={list(warn_violators.keys())}")
    detail = " · ".join(detail_bits)

    return CheckResult(
        "C1", "cluster_sizes", status, detail,
        {"pcts": {k: round(v, 3) for k, v in pcts.items()},
         "fail_violators": fail_violators,
         "warn_violators": warn_violators,
         "fail_pct_threshold": fail_pct,
         "pass_pct_threshold": pass_pct},
    )


def check_centroid_separation(
    model,
    min_dist: float = C2_MIN_CENTROID_DIST,
    scale: str = "",
) -> CheckResult:
    """C2: distancia mínima entre pares de centroides en z-space."""
    centroids_z = model.cluster_centers_
    k = centroids_z.shape[0]
    min_d = np.inf
    min_pair = None
    for i in range(k):
        for j in range(i + 1, k):
            d = float(np.linalg.norm(centroids_z[i] - centroids_z[j]))
            if d < min_d:
                min_d = d
                min_pair = (i, j)
    prefix = PAC_STATE_PREFIXES.get(scale, scale.upper())
    if min_d >= min_dist:
        status = "PASS"
    elif min_d >= min_dist * 0.7:
        status = "WARN"
    else:
        status = "FAIL"
    detail = (
        f"min_dist={min_d:.3f} · umbral={min_dist:.2f} · "
        f"par más cercano=({prefix}{min_pair[0]},{prefix}{min_pair[1]})"
        if min_pair is not None else f"min_dist={min_d:.3f}"
    )
    return CheckResult(
        "C2", "centroid_separation", status, detail,
        {"min_dist": round(min_d, 6),
         "closest_pair": list(min_pair) if min_pair else None,
         "min_dist_threshold": min_dist},
    )


def check_morphotype_coherence(
    centroids_orig: pd.DataFrame,
    min_diversity: float = C3_MIN_DOMINANT_DIVERSITY,
    min_ntot_range: float = C3_MIN_NTOT_RANGE,
) -> CheckResult:
    """C3 rediseñado (Q4=A): coherencia morphotype con doble criterio.

    PASS si CUALQUIERA de:
      (a) diversity de morphotype dominante (idxmax) ≥ min_diversity
      (b) rango de n_edos_total entre clusters ≥ min_ntot_range
          (los clusters difieren en intensidad total aunque compartan
           el morphotype dominante)

    Si ambos fallan → WARN (no bloqueante, solo aviso de redundancia).
    """
    morph_cols = ["n_alpha", "n_beta", "n_gamma", "n_delta"]
    missing = [c for c in morph_cols if c not in centroids_orig.columns]
    if missing:
        return CheckResult("C3", "morphotype_coherence", "WARN",
                           f"columnas faltantes en centroides: {missing}", {})

    # Morphotype dominante por cluster = el de mayor densidad
    dominant = centroids_orig[morph_cols].idxmax(axis=1)
    n_clusters = len(dominant)
    n_unique = dominant.nunique()
    diversity = n_unique / n_clusters

    # Total de morphotypes también varía?
    totals = (
        centroids_orig["n_edos_total"]
        if "n_edos_total" in centroids_orig.columns else None
    )
    total_range = (
        float(totals.max() - totals.min()) if totals is not None else None
    )

    diversity_ok = diversity >= min_diversity
    ntot_range_ok = (total_range is not None) and (total_range >= min_ntot_range)

    if diversity_ok or ntot_range_ok:
        status = "PASS"
    else:
        status = "WARN"  # no bloqueante

    pass_reason = []
    if diversity_ok: pass_reason.append("diversity")
    if ntot_range_ok: pass_reason.append("n_edos_total_range")

    detail = (
        f"{n_unique}/{n_clusters} morphotypes dominantes distintos "
        f"(diversity={diversity:.2f} · umbral={min_diversity:.2f})"
    )
    if total_range is not None:
        detail += (
            f" · rango n_edos_total={total_range:.2f} "
            f"(umbral={min_ntot_range:.2f})"
        )
    if pass_reason:
        detail += f" · PASS por {'+'.join(pass_reason)}"
    return CheckResult(
        "C3", "morphotype_coherence", status, detail,
        {"dominant_by_cluster": dominant.to_dict(),
         "n_unique_dominant": int(n_unique),
         "diversity": round(diversity, 3),
         "n_edos_total_range": total_range,
         "diversity_ok": diversity_ok,
         "ntot_range_ok": ntot_range_ok,
         "min_diversity_threshold": min_diversity,
         "min_ntot_range_threshold": min_ntot_range},
    )


def check_sleep_coherence(
    centroids_orig: pd.DataFrame,
    scale: str,
) -> CheckResult:
    """C4 rediseñado (Q3=A): coherencia de sueño SIN exigir cluster wake.

    El training mask Q6=C exige `frac_wake ≤ 0.5`, por lo que wake está
    excluida por diseño del pool de entrenamiento. Pedir un cluster
    wake-dominante era contradictorio.

    Verifica:
      (a) ≥1 cluster con frac_light_sleep > 0.3
      (b) ≥1 cluster con frac_deep_sleep  > 0.3 (excepto escala s, opcional)

    Ambas presentes → PASS · alguna ausente → WARN (no bloqueante).
    """
    if "frac_light_sleep" not in centroids_orig.columns:
        return CheckResult("C4", "sleep_coherence", "WARN",
                           "frac_light_sleep no en centroides", {})

    has_light = bool((centroids_orig["frac_light_sleep"] > 0.3).any())
    has_deep = bool((centroids_orig["frac_deep_sleep"] > 0.3).any()) \
        if "frac_deep_sleep" in centroids_orig.columns else False
    max_wake = (
        float(centroids_orig["frac_wake"].max())
        if "frac_wake" in centroids_orig.columns else float("nan")
    )
    max_light = float(centroids_orig["frac_light_sleep"].max())
    max_deep = (
        float(centroids_orig["frac_deep_sleep"].max())
        if "frac_deep_sleep" in centroids_orig.columns else float("nan")
    )

    # Escala s: deep es tolerable que no supere 0.3 (ventanas de 30s)
    deep_required = scale != "s"
    has_all = has_light and (has_deep or not deep_required)

    status = "PASS" if has_all else "WARN"

    missing = []
    if not has_light: missing.append("light")
    if deep_required and not has_deep: missing.append("deep")
    detail = (
        f"max_light={max_light:.2f} · max_deep={max_deep:.2f}"
        f" · max_wake={max_wake:.2f} (informativo; wake excluida por training mask)"
        + (f" · sin cluster con {missing}>0.3" if missing else "")
        + (" · excepción deep-opcional aplicada" if scale == "s" else "")
    )
    return CheckResult(
        "C4", "sleep_coherence", status, detail,
        {"max_wake": round(max_wake, 3) if not np.isnan(max_wake) else None,
         "max_light_sleep": round(max_light, 3),
         "max_deep_sleep": round(max_deep, 3) if not np.isnan(max_deep) else None,
         "has_light": has_light, "has_deep": has_deep,
         "deep_required": deep_required,
         "scale_s_exception_applied": scale == "s",
         "wake_excluded_by_training_mask": True},
    )


def check_physiological_ranges(
    centroids_orig: pd.DataFrame,
    epsilon: float = C5_EPSILON,
) -> CheckResult:
    """C5: centroides de-normalizados en rangos fisiológicos plausibles.

    Tolerancia epsilon en cota inferior (Q2=A): KMeans en espacio z y luego
    de-normalización `centroid_z * std + mean` puede producir -0.0 por
    roundoff de punto flotante en features con muchos ceros (n_beta, n_gamma).
    Permitimos `value > lo - epsilon` para evitar FAIL espurios.
    """
    violators: list[dict] = []
    near_zero_clipped = 0
    for feat, (lo, hi) in PHYS_RANGES.items():
        if feat not in centroids_orig.columns:
            continue
        col = centroids_orig[feat]
        for cluster, val in col.items():
            if pd.isna(val):
                continue
            v = float(val)
            # Tolerar -epsilon en cota inferior (roundoff de punto flotante)
            if v < lo - epsilon or v > hi + epsilon:
                violators.append({
                    "cluster": cluster, "feature": feat,
                    "value": round(v, 3),
                    "expected": [lo, hi],
                })
            elif lo - epsilon <= v < lo:
                near_zero_clipped += 1

    status = "FAIL" if violators else "PASS"
    if violators:
        detail = f"{len(violators)} violaciones"
    else:
        detail = f"{len(PHYS_RANGES)} features chequeadas — todas en rango"
        if near_zero_clipped:
            detail += f" · {near_zero_clipped} valores en zona ε[{-epsilon:.0e}]"
    return CheckResult(
        "C5", "physiological_ranges", status, detail,
        {"n_violators": len(violators),
         "violators": violators[:20],  # cap para el JSON
         "epsilon": epsilon,
         "near_zero_clipped": near_zero_clipped},
    )


# ---------------------------------------------------------------------------
# Orquestación por escala
# ---------------------------------------------------------------------------
def validate_scale(scale: str, models_dir: Path = MODELS_DIR) -> dict:
    """Corre C1..C5 sobre una escala. Devuelve dict con resultados."""
    model, zparams, meta = st.load_model(scale, models_dir=models_dir)

    # Centroides en espacio original (vía helper del módulo)
    centroids_orig = st.centroids_original_space(model, zparams, scale=scale)

    # Sizes del training report (preferible) o re-inferidas si no existe.
    sizes_training: dict[str, int] = {}
    if TRAINING_REPORT_JSON.exists():
        with open(TRAINING_REPORT_JSON, encoding="utf-8") as f:
            tr = json.load(f)
        scale_rec = tr.get("by_scale", {}).get(scale, {})
        raw_sizes = scale_rec.get("cluster_sizes_training", {})
        sizes_training = {str(k): int(v) for k, v in raw_sizes.items()}

    checks = [
        check_cluster_sizes(sizes_training),
        check_centroid_separation(model, scale=scale),
        check_morphotype_coherence(centroids_orig),
        check_sleep_coherence(centroids_orig, scale=scale),
        check_physiological_ranges(centroids_orig),
    ]
    return {
        "scale": scale,
        "k": int(model.n_clusters),
        "sizes_training": sizes_training,
        "checks": [asdict(c) for c in checks],
    }


def compute_gate(results: list[dict]) -> dict:
    """C1 o C5 FAIL → bloquea. WARN en otros no bloquea."""
    any_fail_blocking = False
    any_warn = False
    failed_checks: list[str] = []
    warned_checks: list[str] = []
    for r in results:
        for c in r["checks"]:
            tag = f"{r['scale']}.{c['check_id']}"
            if c["status"] == "FAIL":
                if c["check_id"] in ("C1", "C5"):
                    any_fail_blocking = True
                    failed_checks.append(tag)
                else:
                    any_warn = True
                    warned_checks.append(tag)
            elif c["status"] == "WARN":
                any_warn = True
                warned_checks.append(tag)
    return {
        "validation_all_ok": not any_fail_blocking and not any_warn,
        "validation_proceed": not any_fail_blocking,   # WARN no bloquea
        "any_fail_blocking": any_fail_blocking,
        "any_warn": any_warn,
        "failed_checks": failed_checks,
        "warned_checks": warned_checks,
    }


# ---------------------------------------------------------------------------
# Reporte markdown
# ---------------------------------------------------------------------------
def _status_emoji(status: str) -> str:
    return {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}.get(status, "?")


def render_markdown(results: list[dict], gate: dict, timestamp: str) -> str:
    lines: list[str] = []
    lines.append("# PAC_v2 — Validación post-fit de estados PAC")
    lines.append("")
    lines.append(f"**Timestamp:** `{timestamp}`  ")
    k_map = {r["scale"]: r["k"] for r in results}
    k_str = " · ".join(f"{s}={k_map[s]}" for s in PAC_STATE_SCALES if s in k_map)
    lines.append(f"**Modelos:** {k_str}  ")
    # Gate
    if gate["validation_all_ok"]:
        gate_msg = "✓ **PASS** — todos los checks verdes; avanzar a paso 7."
    elif gate["validation_proceed"]:
        gate_msg = (
            f"⚠ **PROCEED con warnings** — {len(gate['warned_checks'])} WARN. "
            "Avance permitido; revisar warnings antes de paso 7."
        )
    else:
        gate_msg = (
            f"✗ **BLOCKED** — {len(gate['failed_checks'])} FAIL bloqueante(s). "
            "Revisar C1 (tamaños) o C5 (rangos). No avanzar a paso 7."
        )
    lines.append(f"**Gate:** {gate_msg}")
    lines.append("")
    lines.append("## Checks por escala")
    lines.append("")

    for r in results:
        lines.append(f"### Escala `{r['scale']}` — K={r['k']}")
        lines.append("")
        lines.append("| ID | Check | Status | Detalle |")
        lines.append("|----|-------|:------:|---------|")
        for c in r["checks"]:
            emoji = _status_emoji(c["status"])
            detail = c["detail"].replace("|", "\\|")
            lines.append(
                f"| {c['check_id']} | {c['name']} | {emoji} {c['status']} | {detail} |"
            )
        lines.append("")

    # Apéndice: umbrales
    lines.append("---")
    lines.append("")
    lines.append("## Umbrales usados")
    lines.append("")
    lines.append(
        f"- **C1 cluster_sizes:** FAIL <{C1_MIN_CLUSTER_PCT_FAIL}% · "
        f"WARN [{C1_MIN_CLUSTER_PCT_FAIL}, {C1_MIN_CLUSTER_PCT_PASS})% · "
        f"PASS ≥{C1_MIN_CLUSTER_PCT_PASS}% (escalonado)")
    lines.append(f"- **C2 centroid_separation:** min_dist z-space = {C2_MIN_CENTROID_DIST}")
    lines.append(
        f"- **C3 morphotype_coherence:** PASS si diversity ≥ {C3_MIN_DOMINANT_DIVERSITY} "
        f"o rango n_edos_total ≥ {C3_MIN_NTOT_RANGE}")
    lines.append(
        "- **C4 sleep_coherence:** ≥1 cluster con frac_light_sleep>0.3 y "
        "≥1 con frac_deep_sleep>0.3 (escala s: deep opcional). "
        "Wake excluida por training mask (Q6=C).")
    lines.append(
        f"- **C5 physiological_ranges:** ver PHYS_RANGES en el script "
        f"(epsilon={C5_EPSILON} para roundoff de -0.0)")
    lines.append("")
    lines.append("## Interpretación")
    lines.append("")
    lines.append(
        f"- **FAIL en C1** = cluster degenerado (<{C1_MIN_CLUSTER_PCT_FAIL}% del training). "
        "Sugiere reducir K o revisar features. "
        f"**WARN en C1** = cluster pequeño (<{C1_MIN_CLUSTER_PCT_PASS}%) — "
        "puede ser outlier clínico válido.")
    lines.append("- **FAIL en C5** = algún centroide tiene valores no fisiológicos. "
                 "Suele indicar bug de z-score o NaN propagado.")
    lines.append("- **WARN en C2** = dos clusters están muy cerca en z-space. "
                 "Considerar reducir K=1 si se confirma redundancia en el dashboard.")
    lines.append("- **WARN en C3/C4** = coherencia semántica débil. "
                 "No bloqueante pero marcarlo para interpretabilidad.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not TRAINING_REPORT_JSON.exists():
        print(f"[validate] WARN: {TRAINING_REPORT_JSON.name} no existe; "
              "los checks C1 (sizes) van a fallar por falta de datos.")

    timestamp = datetime.now().isoformat(timespec="seconds")
    results = []
    for scale in PAC_STATE_SCALES:
        paths = st._paths_for_scale(scale)
        if not paths["kmeans_pkl"].exists():
            print(f"[validate] SKIP escala {scale!r}: modelo no persistido "
                  f"({paths['kmeans_pkl'].name}).")
            continue
        print(f"[validate] escala {scale!r} …")
        results.append(validate_scale(scale))

    if not results:
        print("[validate] ERROR: ninguna escala tiene modelo persistido. "
              "Correr train_pac_states.py --mode final primero.")
        return

    gate = compute_gate(results)

    # JSON
    report_json = {
        "timestamp": timestamp,
        "scales_validated": [r["scale"] for r in results],
        "k_per_scale": {r["scale"]: r["k"] for r in results},
        "thresholds": {
            "C1_min_cluster_pct_fail": C1_MIN_CLUSTER_PCT_FAIL,
            "C1_min_cluster_pct_pass": C1_MIN_CLUSTER_PCT_PASS,
            "C2_min_centroid_dist": C2_MIN_CENTROID_DIST,
            "C3_min_dominant_diversity": C3_MIN_DOMINANT_DIVERSITY,
            "C3_min_ntot_range": C3_MIN_NTOT_RANGE,
            "C5_epsilon": C5_EPSILON,
        },
        "by_scale": results,
        "gate": gate,
    }
    with open(VALIDATION_JSON, "w", encoding="utf-8") as f:
        json.dump(report_json, f, indent=2, ensure_ascii=False, default=str)

    # Markdown
    md = render_markdown(results, gate, timestamp)
    with open(VALIDATION_MD, "w", encoding="utf-8") as f:
        f.write(md)

    # Actualizar batch_gate.json con flags de validación
    if BATCH_GATE_JSON.exists():
        with open(BATCH_GATE_JSON, encoding="utf-8") as f:
            bg = json.load(f)
    else:
        bg = {}
    bg["validation_timestamp"] = timestamp
    bg["validation_all_ok"] = gate["validation_all_ok"]
    bg["validation_proceed"] = gate["validation_proceed"]
    bg["validation_failed_checks"] = gate["failed_checks"]
    bg["validation_warned_checks"] = gate["warned_checks"]
    with open(BATCH_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(bg, f, indent=2, ensure_ascii=False)

    # Log final
    print(f"\n[validate] escrito: {VALIDATION_MD.name}, {VALIDATION_JSON.name}")
    print(f"[validate] batch_gate actualizado: {BATCH_GATE_JSON.name}")
    print(f"[validate] gate: all_ok={gate['validation_all_ok']} · "
          f"proceed={gate['validation_proceed']} · "
          f"FAIL={len(gate['failed_checks'])} · WARN={len(gate['warned_checks'])}")


if __name__ == "__main__":
    main()
