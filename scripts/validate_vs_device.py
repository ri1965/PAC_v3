"""
PAC_v2 — Etapa 3 paso 9: análisis de validación vs sidecar classical.

Consolida los 560 events/*_indices.parquet en un pooled DataFrame, luego:

  1. Por cada índice validado, computa estadísticas del diff_abs, diff_rel,
     correlación Pearson/Spearman (pac_v2 vs device), y regresión lineal
     pac_v2 = a*device + b.
  2. Cross-tab de diff_flag con QC flags de Silver (coverage, duration)
     para ver si los mismatches están concentrados en noches marginales
     o son hallazgos reales.
  3. Persiste:
       reports/events_indices_pooled.parquet       (pool de 560 filas × ~104 cols)
       reports/events_validation_by_index.csv      (1 fila por índice: stats)
       reports/events_validation_report.json       (resumen + cross-tab)

Corre desde la raíz del repo:  PYTHONPATH=src python scripts/validate_vs_device.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from pac.config import (
    DIFF_REL_FLAG_THRESHOLD,
    EVENTS_DIR,
    REPORTS_DIR,
    VALIDATED_INDICES,
)


POOLED_PARQUET = REPORTS_DIR / "events_indices_pooled.parquet"
VALIDATION_CSV = REPORTS_DIR / "events_validation_by_index.csv"
VALIDATION_JSON = REPORTS_DIR / "events_validation_report.json"


# ---------------------------------------------------------------------------
# Pool consolidation
# ---------------------------------------------------------------------------
def load_pool(events_dir: Path = EVENTS_DIR) -> pd.DataFrame:
    paths = sorted(events_dir.glob("NR_*_indices.parquet"))
    frames = []
    for p in paths:
        df = pq.read_table(p).to_pandas()
        frames.append(df)
    if not frames:
        raise RuntimeError("No se encontraron *_indices.parquet en events/")
    pool = pd.concat(frames, ignore_index=True)
    return pool


def attach_silver_qc(pool: pd.DataFrame) -> pd.DataFrame:
    """Joinea pool con silver_qc_summary para cross-tab QC × diff_flag."""
    sil = REPORTS_DIR / "silver_qc_summary.csv"
    if not sil.exists():
        return pool
    qc = pd.read_csv(sil, dtype={"night_record_id": str})
    keep = [
        "night_record_id", "coverage", "max_contiguous_gap_s",
        "qc_coverage_ok", "qc_max_gap_ok", "qc_duration_aborted",
        "qc_duration_short", "frac_spo2_invalid", "frac_hr_invalid",
    ]
    keep = [c for c in keep if c in qc.columns]
    merged = pool.merge(qc[keep], on="night_record_id", how="left")
    return merged


# ---------------------------------------------------------------------------
# Per-index stats
# ---------------------------------------------------------------------------
def per_index_stats(pool: pd.DataFrame, indices: list[str]) -> pd.DataFrame:
    rows = []
    for idx in indices:
        pac = pd.to_numeric(pool.get(f"{idx}_pac_v2"), errors="coerce")
        dev = pd.to_numeric(pool.get(f"{idx}_device"), errors="coerce")
        da  = pd.to_numeric(pool.get(f"{idx}_diff_abs"), errors="coerce")
        dr  = pd.to_numeric(pool.get(f"{idx}_diff_rel"), errors="coerce")
        flag = pool.get(f"{idx}_diff_flag")

        n_nights = len(pool)
        n_comparable = int((pac.notna() & dev.notna()).sum())
        n_flag = int(pd.Series(flag).fillna(False).astype(bool).sum()) \
                 if flag is not None else 0

        # Stats sólo donde ambos disponibles y dr finito.
        mask = pac.notna() & dev.notna() & np.isfinite(dr)
        pac_m = pac[mask]
        dev_m = dev[mask]
        da_m = da[mask]
        dr_m = dr[mask]

        def _safe(agg, s: pd.Series) -> float:
            if len(s) == 0: return float("nan")
            return float(agg(s))

        # Correlaciones.
        if len(pac_m) >= 3:
            pear = float(pac_m.corr(dev_m, method="pearson"))
            spea = float(pac_m.corr(dev_m, method="spearman"))
        else:
            pear = float("nan")
            spea = float("nan")

        # Regresión lineal pac = a*dev + b (OLS).
        if len(pac_m) >= 3 and dev_m.std(ddof=0) > 1e-9:
            a, b = np.polyfit(dev_m.to_numpy(), pac_m.to_numpy(), deg=1)
        else:
            a = float("nan")
            b = float("nan")

        rows.append({
            "index": idx,
            "n_nights": n_nights,
            "n_comparable": n_comparable,
            "n_diff_flag": n_flag,
            "pct_diff_flag": round(100.0 * n_flag / n_nights, 2),
            "pac_v2_median": _safe(np.median, pac_m),
            "device_median": _safe(np.median, dev_m),
            "diff_abs_median": _safe(np.median, da_m),
            "diff_rel_median": _safe(np.median, dr_m),
            "diff_rel_p5":     _safe(lambda s: np.percentile(s, 5), dr_m),
            "diff_rel_p95":    _safe(lambda s: np.percentile(s, 95), dr_m),
            "pearson_r":   round(pear, 4) if not np.isnan(pear) else None,
            "spearman_r":  round(spea, 4) if not np.isnan(spea) else None,
            "slope_ols":   round(a, 4) if not np.isnan(a) else None,
            "intercept_ols": round(b, 4) if not np.isnan(b) else None,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Cross-tab: diff_flag × QC flags
# ---------------------------------------------------------------------------
def crosstab_flag_vs_qc(pool: pd.DataFrame, idx: str) -> dict:
    """
    Para un índice, cruza diff_flag con QC flags de Silver.
    Devuelve conteos absolutos y proporciones.
    """
    flag_col = f"{idx}_diff_flag"
    if flag_col not in pool.columns:
        return {}
    flags = pool[flag_col].fillna(False).astype(bool)
    out = {
        "n_total": int(len(pool)),
        "n_diff_flag": int(flags.sum()),
        "pct_diff_flag_overall": round(100.0 * flags.mean(), 2),
    }
    for qc_col in ("qc_duration_aborted", "qc_duration_short",
                   "qc_coverage_ok", "qc_max_gap_ok"):
        if qc_col not in pool.columns:
            continue
        qc = pool[qc_col].fillna(False).astype(bool)
        # Para coverage_ok y max_gap_ok: flip (ver si falla QC ↔ diff_flag)
        if qc_col in ("qc_coverage_ok", "qc_max_gap_ok"):
            qc_fail = ~qc
            qc_label = qc_col.replace("_ok", "_fail")
        else:
            qc_fail = qc
            qc_label = qc_col
        n_qc_fail = int(qc_fail.sum())
        if n_qc_fail == 0:
            pct_flag_in_qc_fail = 0.0
        else:
            pct_flag_in_qc_fail = round(
                100.0 * (flags & qc_fail).sum() / n_qc_fail, 2
            )
        out[qc_label] = {
            "n": n_qc_fail,
            "pct_with_diff_flag": pct_flag_in_qc_fail,
        }
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("[validate] consolidando pool …")
    pool = load_pool()
    print(f"           pool: {pool.shape[0]} noches × {pool.shape[1]} cols")
    pool = attach_silver_qc(pool)
    print(f"           pool + silver qc: {pool.shape[1]} cols")

    # Persist pooled (bronze para Gold).
    POOLED_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    pool.to_parquet(POOLED_PARQUET, index=False)
    print(f"           pool persistido: {POOLED_PARQUET.name}")

    # Per-index stats
    print("[validate] stats por índice …")
    stats = per_index_stats(pool, list(VALIDATED_INDICES))
    stats.to_csv(VALIDATION_CSV, index=False)
    print(f"           csv: {VALIDATION_CSV.name}")
    print(stats.to_string(index=False))

    # Cross-tab diff_flag × QC para los índices clave (ODI_3, AHI_3, TST_s).
    print()
    print("[validate] cross-tab diff_flag × QC flags …")
    crosstabs = {
        idx: crosstab_flag_vs_qc(pool, idx)
        for idx in ("odi_3", "odi_4", "ahi_3", "ahi_4",
                    "tst_s", "sleep_efficiency")
    }
    for idx, ct in crosstabs.items():
        print(f"  {idx}:")
        for k, v in ct.items():
            print(f"    {k}: {v}")

    # JSON report
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "diff_rel_flag_threshold": DIFF_REL_FLAG_THRESHOLD,
        "n_nights_in_pool": int(len(pool)),
        "per_index_stats": stats.to_dict(orient="records"),
        "crosstabs_flag_vs_qc": crosstabs,
    }
    with open(VALIDATION_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print()
    print(f"[validate] JSON report: {VALIDATION_JSON.name}")


if __name__ == "__main__":
    main()
