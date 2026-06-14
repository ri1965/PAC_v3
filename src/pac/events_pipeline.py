"""
PAC_v2 — Etapa 3 Events: orquestador.

Lee silver/{NR}.parquet (9 cols) y opcionalmente bronze/{NR}_classical.parquet
(sidecar classical del dispositivo). Corre:
  - Detección de EDOs permisiva (drop ≥ 2%, duración ≥ 10 s).
  - Caracterización morfológica (slopes, AUC, meets_Npct, IRD).
  - Flags de contexto: near_gap, in_sleep.
  - Índices nocturnos (~35): ODI_N, AHI_N, T<N/CT<N, HB, HR/mov stats,
    sueño, IRD nocturno + stats.
  - Quintetos de validación vs sidecar classical para índices con gemelo.

Escribe 3 parquets por noche:
  - events/{NR}_edos.parquet         → N filas × ~25 cols (1 por EDO)
  - events/{NR}_edo_curves.parquet   → N filas × 3 curvas de 30 pts (sidecar)
  - events/{NR}_indices.parquet      → 1 fila × ~60 cols (nocturnos + quintetos)

Y al cerrar el batch:
  - reports/events_gate.json        → resumen agregado + distribuciones
  - reports/events_summary.csv      → 1 fila por noche con indices principales

Decisiones Etapa 3 (cerradas con Roberto R1–R5 + Q1–Q15, ver PAC_v2_ETAPAS.md):
  - Detección permisiva; clustering real/ruido difiere a Etapa 4 (Q12b).
  - Todas las 560 noches se procesan con flags; filtrado clínico en Gold (Q4d+4c).
  - Curvas resampleadas a 30 puntos en sidecar (Q15c).
  - Pesos IRD default 0.5/0.3/0.2 swappables (R4 + Q13a).
  - Validación vs classical: quintetos {pac_v2, device, diff_abs, diff_rel, diff_flag} (Q6).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pac.config import (
    ALGORITHM_VERSION_PAC_V2,
    BRONZE_DIR,
    CLINICAL_COLS,
    CLINICAL_CSV,
    CSV_SEP,
    DIFF_REL_FLAG_THRESHOLD,
    EDO_BASELINE_WINDOW_S,
    EDO_DROP_THRESHOLDS_PCT,
    EDO_MIN_DURATION_S,
    EDO_RECOVERY_PCT,
    EDO_RESAMPLE_N_POINTS,
    EVENTS_DIR,
    EVENTS_SCHEMA_VERSION,
    HR_BRADY_THRESHOLD_BPM,
    HR_EXTREME_MIN_DURATION_S,
    HR_TACHY_THRESHOLD_BPM,
    IRD_WEIGHTS,
    NEAR_GAP_WINDOW_S,
    REPORTS_DIR,
    SAMPLING_HZ_NOMINAL,
    SILVER_DIR,
    T_UNDER_THRESHOLDS_PCT,
    VALIDATED_INDICES,
    ensure_dirs,
)
from pac.events import (
    characterize_edo,
    compute_baseline_moving,
    compute_gaps,
    detect_edo_candidates,
    mark_in_sleep,
    mark_near_gap,
)
from pac.indices import (
    compute_ct_under,
    compute_delta_hr_stats,
    compute_diff_vs_device,
    compute_edo_morphology_stats,
    compute_hr_stats,
    compute_hypoxic_burden,
    compute_ird_event_stats,
    compute_ird_night,
    compute_mov_stats,
    compute_odi_ahi_family,
    compute_sleep_stats,
    compute_spo2_stats,
    compute_t_under,
    count_sustained_extremes,
)


EVENTS_GATE_JSON = REPORTS_DIR / "events_gate.json"
EVENTS_SUMMARY_CSV = REPORTS_DIR / "events_summary.csv"
EVENTS_CLINICAL_PRECHECK_JSON = REPORTS_DIR / "events_clinical_precheck.json"
SILVER_QC_SUMMARY_CSV = REPORTS_DIR / "silver_qc_summary.csv"


# Mapeo canónico: índice PAC_v2 → columna en sidecar classical.
# Los que no existan en classical se comparan contra None → quinteto NaN.
CLASSICAL_COL_MAP = {
    "odi_3":            "odi_3",
    "odi_4":            "odi_4",
    "ahi_3":            "ahi_3",
    "ahi_4":            "ahi_4",
    "t90_frac":         None,  # no existe en sidecar
    "hypoxic_burden_3": "hypoxic_burden_3",
    "hypoxic_burden_4": "hypoxic_burden_4",
    "tst_s":            "tst",
    "sleep_efficiency": "efficiency",
    "waso_s":           "waso",
}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _read_parquet_with_kv(path: Path) -> Tuple[pd.DataFrame, Dict[str, str]]:
    table = pq.read_table(path)
    df = table.to_pandas()
    md_raw = table.schema.metadata or {}
    kv = {
        k.decode("utf-8"): v.decode("utf-8")
        for k, v in md_raw.items()
        if not k.startswith(b"pandas")
    }
    return df, kv


def _write_parquet_with_kv(
    df: pd.DataFrame,
    path: Path,
    kv_metadata: Dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    existing = table.schema.metadata or {}
    merged = dict(existing)
    merged.update(
        {k.encode("utf-8"): str(v).encode("utf-8") for k, v in kv_metadata.items()}
    )
    table = table.replace_schema_metadata(merged)
    pq.write_table(table, path, compression="snappy")


def _read_classical_sidecar(bronze_dir: Path, nr_id: str) -> Optional[dict]:
    """
    Lee bronze/{NR}_classical.parquet y devuelve un dict {col: float}.
    Los valores están como strings con espacios → los parseo a float.
    None si el sidecar no existe.
    """
    path = bronze_dir / f"{nr_id}_classical.parquet"
    if not path.exists():
        return None
    df, _ = _read_parquet_with_kv(path)
    if df.empty:
        return None
    row = df.iloc[0].to_dict()
    out: dict = {}
    for k, v in row.items():
        if v is None:
            out[k] = np.nan
            continue
        try:
            out[k] = float(str(v).strip())
        except (ValueError, TypeError):
            out[k] = np.nan
    return out


# ---------------------------------------------------------------------------
# Safety net: clinical.csv pre-check
# ---------------------------------------------------------------------------
def clinical_precheck(
    clinical_path: Path = CLINICAL_CSV,
    silver_summary_csv: Path = SILVER_QC_SUMMARY_CSV,
    verbose: bool = True,
) -> dict:
    """
    Auditoría pre-batch: ¿cuántos user_id de silver tienen clínica completa?

    No bloquea el batch (decisión Q4d+4c: procesar todas las 560 noches con
    flags; filtrar en Gold). Genera un snapshot JSON para trazabilidad:

      {
        "timestamp": ...,
        "clinical_csv": "...",
        "n_silver_nights": 560,
        "n_silver_users": 200,
        "n_clinical_users": 12,
        "n_users_covered": 12,
        "n_users_missing": 188,
        "pct_nights_covered": 0.04,
        "missing_user_ids": [...],
        "partially_filled_user_ids": [...],   # clinical.csv sin algún campo
      }

    Args:
        clinical_path: patients/clinical.csv.
        silver_summary_csv: reports/silver_qc_summary.csv (producto de Etapa 2).
        verbose: imprime warning si cobertura < 80%.

    Returns:
        El dict con las métricas (además persistido a JSON).
    """
    # --- Leer clinical ----------------------------------------------------
    clinical_present = clinical_path.exists()
    clinical_users: set[str] = set()
    partial_users: list[str] = []
    clinical_cols_found: list[str] = []
    if clinical_present:
        try:
            clin = pd.read_csv(clinical_path, sep=CSV_SEP, dtype=str)
            clinical_cols_found = list(clin.columns)
            if "patient_id" in clin.columns:
                clinical_users = set(clin["patient_id"].dropna().astype(str).tolist())
                # "partial" = alguna col de CLINICAL_COLS (excluye patient_id) NaN
                non_id_cols = [c for c in CLINICAL_COLS if c != "patient_id"
                               and c in clin.columns]
                for _, row in clin.iterrows():
                    pid = str(row.get("patient_id", "")).strip()
                    if not pid:
                        continue
                    incomplete = any(
                        pd.isna(row[c]) or str(row[c]).strip() == ""
                        for c in non_id_cols
                    )
                    if incomplete:
                        partial_users.append(pid)
        except Exception:  # noqa: BLE001
            clinical_users = set()

    # --- Leer silver summary ---------------------------------------------
    silver_users: set[str] = set()
    n_nights = 0
    user_to_n_nights: dict[str, int] = {}
    if silver_summary_csv.exists():
        sil = pd.read_csv(silver_summary_csv, dtype=str)
        if "user_id" in sil.columns and "status" in sil.columns:
            ok = sil[sil["status"] == "OK"]
            n_nights = int(len(ok))
            for uid in ok["user_id"].dropna().astype(str):
                uid = uid.strip()
                if not uid:
                    continue
                silver_users.add(uid)
                user_to_n_nights[uid] = user_to_n_nights.get(uid, 0) + 1

    covered = silver_users & clinical_users
    missing = silver_users - clinical_users
    n_nights_covered = sum(user_to_n_nights.get(u, 0) for u in covered)
    pct_nights_covered = (n_nights_covered / n_nights) if n_nights else 0.0

    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "clinical_csv": str(clinical_path),
        "clinical_csv_exists": clinical_present,
        "clinical_cols_found": clinical_cols_found,
        "clinical_cols_expected": CLINICAL_COLS,
        "n_silver_nights": n_nights,
        "n_silver_users": len(silver_users),
        "n_clinical_users": len(clinical_users),
        "n_users_covered": len(covered),
        "n_users_missing": len(missing),
        "n_nights_covered": n_nights_covered,
        "pct_nights_covered": round(pct_nights_covered, 4),
        "missing_user_ids_sample": sorted(missing)[:20],
        "partially_filled_user_ids": sorted(set(partial_users)),
    }
    EVENTS_CLINICAL_PRECHECK_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(EVENTS_CLINICAL_PRECHECK_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if verbose:
        print("")
        print("[events] clinical pre-check:")
        print(f"         clinical_csv_exists = {clinical_present}")
        print(f"         silver_users        = {len(silver_users)}")
        print(f"         clinical_users      = {len(clinical_users)}")
        print(f"         covered             = {len(covered)}  "
              f"({n_nights_covered}/{n_nights} nights, "
              f"{pct_nights_covered:.1%})")
        if len(missing) > 0:
            print(f"         MISSING             = {len(missing)} users "
                  f"(ver {EVENTS_CLINICAL_PRECHECK_JSON.name})")
        if partial_users:
            print(f"         partial in clinical = {len(set(partial_users))} users")
        if pct_nights_covered < 0.80 and n_nights > 0:
            print("         ⚠  cobertura <80% — el batch corre igual; "
                  "filtrado clínico se aplica en Gold (Q4d+4c).")

    return result


# ---------------------------------------------------------------------------
# process_one_events — pipeline por noche
# ---------------------------------------------------------------------------
def process_one_events(
    nr_silver_path: Path,
    bronze_dir: Path = BRONZE_DIR,
    events_dir: Path = EVENTS_DIR,
) -> dict:
    """
    Procesa silver/{NR}.parquet + bronze/{NR}_classical.parquet →
    events/{NR}_edos.parquet + events/{NR}_edo_curves.parquet +
    events/{NR}_indices.parquet.

    Returns:
        Dict resumen con las columnas principales para events_summary.csv.
    """
    # --- Read silver -------------------------------------------------------
    df, kv = _read_parquet_with_kv(nr_silver_path)
    nr_id = kv.get("night_record_id", nr_silver_path.stem)
    user_id = kv.get("user_id", "")
    fs = float(SAMPLING_HZ_NOMINAL)

    # Orden temporal defensivo.
    if not df["timestamp"].is_monotonic_increasing:
        df = df.sort_values("timestamp").reset_index(drop=True)

    ts = df["timestamp"]
    spo2_clean = df["spo2_clean"]
    hr_clean = df["hr_clean"]
    mov = df["mov"]
    sleep_stage = df["sleep_stage"]

    # --- Baseline móvil + detección permisiva ------------------------------
    baseline = compute_baseline_moving(
        spo2_clean,
        window_s=EDO_BASELINE_WINDOW_S,
        sampling_hz=fs,
    )
    candidates = detect_edo_candidates(
        spo2_clean=spo2_clean,
        ts=ts,
        baseline=baseline,
        min_duration_s=EDO_MIN_DURATION_S,
        recovery_pct=EDO_RECOVERY_PCT,
        min_drop_pct=float(min(EDO_DROP_THRESHOLDS_PCT)),
    )

    # --- Contexto: gaps + sleep stage --------------------------------------
    gaps = compute_gaps(ts, min_gap_s=30.0)

    # --- Caracterización morfológica por EDO -------------------------------
    edos_rows: list[dict] = []
    curves_rows: list[dict] = []
    for edo in candidates:
        char = characterize_edo(
            edo,
            df,
            drop_thresholds_pct=EDO_DROP_THRESHOLDS_PCT,
            n_resample_points=EDO_RESAMPLE_N_POINTS,
            context_window_s=60,
            ird_weights=IRD_WEIGHTS,
        )
        # Flags de contexto.
        near_gap = mark_near_gap(
            char["ts_start"], char["ts_end"],
            gaps, window_s=NEAR_GAP_WINDOW_S,
        )
        in_sleep = mark_in_sleep(
            edo["start_idx"], edo["end_idx"],
            sleep_stage, wake_values={0},
        )

        # Fila "plana" del _edos.parquet (sin curvas).
        row = {
            "night_record_id": nr_id,
            "ts_start": char["ts_start"],
            "ts_end": char["ts_end"],
            "duration_s": char["duration_s"],
            "baseline_spo2": char["baseline_spo2"],
            "nadir_spo2": char["nadir_spo2"],
            "drop_pct": char["drop_pct"],
            "slope_desat_pct_s": char["slope_desat_pct_s"],
            "slope_recov_pct_s": char["slope_recov_pct_s"],
            "auc_spo2_pct_s": char["auc_spo2_pct_s"],
            "delta_hr_bpm": char["delta_hr_bpm"],
            "baseline_hr_bpm": char["baseline_hr_bpm"],
            "peak_mov": char["peak_mov"],
            "baseline_mov": char["baseline_mov"],
            "ird_spo2_comp": char["ird_spo2_comp"],
            "ird_hr_comp": char["ird_hr_comp"],
            "ird_mov_comp": char["ird_mov_comp"],
            "ird_event": char["ird_event"],
            "near_gap": bool(near_gap),
            "in_sleep": bool(in_sleep),
        }
        # meets_Npct flags
        for pct in EDO_DROP_THRESHOLDS_PCT:
            row[f"meets_{int(pct)}pct"] = char[f"meets_{int(pct)}pct"]
        edos_rows.append(row)

        # Sidecar curvas: mismo ts_start como key + 3 arrays de 30 pts.
        curves_rows.append(
            {
                "night_record_id": nr_id,
                "ts_start": char["ts_start"],
                "spo2_curve": char["_spo2_curve"].tolist(),
                "hr_curve": char["_hr_curve"].tolist(),
                "mov_curve": char["_mov_curve"].tolist(),
            }
        )

    events_df = pd.DataFrame(edos_rows)
    curves_df = pd.DataFrame(curves_rows)

    # --- Índices nocturnos -------------------------------------------------
    # Sleep stats primero (necesario para ODI/AHI/HB/IRD normalizados a TST).
    sleep = compute_sleep_stats(
        sleep_stage=sleep_stage,
        ts=ts,
        wake_values={0},
        sampling_hz=fs,
    )
    tst_s = float(sleep["tst_s"])

    # SpO2 family
    spo2_stats = compute_spo2_stats(spo2_clean)
    t_under: dict = {}
    ct_under: dict = {}
    for thr in T_UNDER_THRESHOLDS_PCT:
        t_under[f"t{int(thr)}_frac"] = compute_t_under(spo2_clean, float(thr))
        ct_under[f"ct{int(thr)}_min"] = compute_ct_under(
            spo2_clean, float(thr), sampling_hz=fs
        )
    hb_3 = compute_hypoxic_burden(
        spo2_clean, ts, threshold_pct=float(spo2_stats.get("median_spo2", 90.0)) - 3.0
        if not np.isnan(spo2_stats["median_spo2"]) else 90.0,
        sampling_hz=fs,
    )
    # HB canónico a 90% (alineado con el sidecar hypoxic_burden_3/_4)
    hb_90 = compute_hypoxic_burden(spo2_clean, ts, threshold_pct=90.0, sampling_hz=fs)
    hb_88 = compute_hypoxic_burden(spo2_clean, ts, threshold_pct=88.0, sampling_hz=fs)

    # HR family
    hr_stats = compute_hr_stats(hr_clean)
    n_brady = count_sustained_extremes(
        hr_clean, threshold=HR_BRADY_THRESHOLD_BPM, comparator="<",
        min_duration_s=HR_EXTREME_MIN_DURATION_S, sampling_hz=fs,
    )
    n_tachy = count_sustained_extremes(
        hr_clean, threshold=HR_TACHY_THRESHOLD_BPM, comparator=">",
        min_duration_s=HR_EXTREME_MIN_DURATION_S, sampling_hz=fs,
    )
    delta_hr_stats = compute_delta_hr_stats(events_df)

    # Movement
    mov_stats = compute_mov_stats(mov, ts, sampling_hz=fs)

    # Event-based
    ird_night_val = compute_ird_night(events_df, tst_s=tst_s)
    ird_event_stats = compute_ird_event_stats(events_df)
    morph_stats = compute_edo_morphology_stats(events_df)
    odi_ahi_family = compute_odi_ahi_family(
        events_df, tst_s=tst_s, thresholds=EDO_DROP_THRESHOLDS_PCT,
    )

    # --- Validación quinteto vs classical ----------------------------------
    classical = _read_classical_sidecar(bronze_dir, nr_id)
    pac_v2_values = {
        "odi_3":            odi_ahi_family.get("odi_3", 0.0),
        "odi_4":            odi_ahi_family.get("odi_4", 0.0),
        "ahi_3":            odi_ahi_family.get("ahi_3", 0.0),
        "ahi_4":            odi_ahi_family.get("ahi_4", 0.0),
        "t90_frac":         t_under.get("t90_frac", 0.0),
        "hypoxic_burden_3": hb_90,   # HB a 90% del absoluto → paralelo a sidecar
        "hypoxic_burden_4": hb_88,   # HB a 88% ≈ 4% del basal típico 92
        "tst_s":            tst_s,
        "sleep_efficiency": sleep["sleep_efficiency"],
        "waso_s":           sleep["waso_s"],
    }
    quintets: dict = {}
    for idx_name in VALIDATED_INDICES:
        classical_col = CLASSICAL_COL_MAP.get(idx_name)
        device_val: Optional[float]
        if classical is None or classical_col is None:
            device_val = None
        else:
            device_val = classical.get(classical_col, None)
        q = compute_diff_vs_device(
            pac_v2_value=float(pac_v2_values[idx_name]),
            device_value=device_val,
            flag_threshold=DIFF_REL_FLAG_THRESHOLD,
        )
        for k, v in q.items():
            quintets[f"{idx_name}_{k}"] = v

    # --- Armar fila de indices.parquet -------------------------------------
    indices_row: dict = {
        "night_record_id": nr_id,
        "user_id": user_id,
        "ts_start": kv.get("ts_start", ""),
        "ts_end": kv.get("ts_end", ""),
        "duration_s": float((ts.iloc[-1] - ts.iloc[0]).total_seconds()) if len(ts) >= 2 else 0.0,
        # sleep
        **sleep,
        # spo2 stats + t/ct under + HB
        **spo2_stats,
        **t_under,
        **ct_under,
        "hypoxic_burden_90": float(hb_90),
        "hypoxic_burden_88": float(hb_88),
        # hr
        **hr_stats,
        "n_brady_episodes": int(n_brady),
        "n_tachy_episodes": int(n_tachy),
        **delta_hr_stats,
        # mov
        **mov_stats,
        # event-based
        "n_edos_total": morph_stats["n_edos_total"],
        "mean_drop_pct": morph_stats["mean_drop_pct"],
        "mean_duration_s_per_edo": morph_stats["mean_duration_s"],
        "max_duration_s_per_edo": morph_stats["max_duration_s"],
        "ird_night": float(ird_night_val),
        **ird_event_stats,
        # ODI/AHI family + counts
        **odi_ahi_family,
        # Quintetos
        **quintets,
        # metadata
        "algorithm_version": ALGORITHM_VERSION_PAC_V2,
        "events_schema_version": EVENTS_SCHEMA_VERSION,
    }

    # --- Metadata KV para los parquets events ------------------------------
    events_kv = dict(kv)
    events_kv.update({
        "pipeline_stage": "events",
        "events_schema_version": EVENTS_SCHEMA_VERSION,
        "events_processed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "algorithm_version": ALGORITHM_VERSION_PAC_V2,
        "edo_baseline_window_s": str(EDO_BASELINE_WINDOW_S),
        "edo_recovery_pct": str(EDO_RECOVERY_PCT),
        "edo_min_duration_s": str(EDO_MIN_DURATION_S),
        "ird_weights": json.dumps(IRD_WEIGHTS),
    })

    # --- Escribir parquets -------------------------------------------------
    edos_path = events_dir / f"{nr_id}_edos.parquet"
    curves_path = events_dir / f"{nr_id}_edo_curves.parquet"
    indices_path = events_dir / f"{nr_id}_indices.parquet"

    # Fuerzar un schema consistente incluso cuando no hay eventos:
    if events_df.empty:
        events_df = pd.DataFrame(columns=[
            "night_record_id", "ts_start", "ts_end", "duration_s",
            "baseline_spo2", "nadir_spo2", "drop_pct",
            "slope_desat_pct_s", "slope_recov_pct_s", "auc_spo2_pct_s",
            "delta_hr_bpm", "baseline_hr_bpm",
            "peak_mov", "baseline_mov",
            "ird_spo2_comp", "ird_hr_comp", "ird_mov_comp", "ird_event",
            "near_gap", "in_sleep",
            *[f"meets_{int(p)}pct" for p in EDO_DROP_THRESHOLDS_PCT],
        ])
        curves_df = pd.DataFrame(columns=[
            "night_record_id", "ts_start", "spo2_curve", "hr_curve", "mov_curve",
        ])

    _write_parquet_with_kv(events_df, edos_path, events_kv)
    _write_parquet_with_kv(curves_df, curves_path, events_kv)
    _write_parquet_with_kv(
        pd.DataFrame([indices_row]), indices_path, events_kv
    )

    # --- Fila resumen para summary ----------------------------------------
    summary = {
        "night_record_id": nr_id,
        "user_id": user_id,
        "n_edos_total": indices_row["n_edos_total"],
        "odi_3": indices_row.get("odi_3", 0.0),
        "odi_4": indices_row.get("odi_4", 0.0),
        "ahi_3": indices_row.get("ahi_3", 0.0),
        "ahi_4": indices_row.get("ahi_4", 0.0),
        "ird_night": indices_row["ird_night"],
        "tst_s": tst_s,
        "sleep_efficiency": indices_row["sleep_efficiency"],
        "t90_frac": indices_row.get("t90_frac", 0.0),
        "hypoxic_burden_90": indices_row["hypoxic_burden_90"],
        # flags de diff con device
        "odi_3_diff_flag":          indices_row.get("odi_3_diff_flag", False),
        "odi_4_diff_flag":          indices_row.get("odi_4_diff_flag", False),
        "ahi_3_diff_flag":          indices_row.get("ahi_3_diff_flag", False),
        "ahi_4_diff_flag":          indices_row.get("ahi_4_diff_flag", False),
        "tst_s_diff_flag":          indices_row.get("tst_s_diff_flag", False),
        "sleep_efficiency_diff_flag": indices_row.get("sleep_efficiency_diff_flag", False),
        "has_classical_sidecar": bool(classical is not None),
    }
    return summary


# ---------------------------------------------------------------------------
# run_events — orquestador
# ---------------------------------------------------------------------------
def run_events(
    silver_dir: Path = SILVER_DIR,
    events_dir: Path = EVENTS_DIR,
    bronze_dir: Path = BRONZE_DIR,
    limit: Optional[int] = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Itera sobre silver/NR_*.parquet (excluye *_qc.parquet).
    Por cada noche llama a process_one_events con isolation.
    Al cerrar: reports/events_gate.json + reports/events_summary.csv.
    """
    ensure_dirs()

    # Safety net clinical — no bloquea, sólo registra.
    clinical_precheck(verbose=verbose)

    candidates = sorted(silver_dir.glob("NR_*.parquet"))
    candidates = [p for p in candidates if not p.name.endswith("_qc.parquet")]
    if limit is not None:
        candidates = candidates[:limit]
    if verbose:
        print(f"[events] silver parquets a procesar: {len(candidates)}")

    t0 = time.time()
    rows = []
    for i, p in enumerate(candidates, start=1):
        try:
            s = process_one_events(p, bronze_dir=bronze_dir, events_dir=events_dir)
            s["status"] = "OK"
            s["error"] = ""
            msg_tail = (
                f"n_edos={s['n_edos_total']:>4}  odi_3={s['odi_3']:.2f}  "
                f"ird={s['ird_night']:.4f}  tst={s['tst_s']:.0f}s"
            )
        except Exception as e:  # noqa: BLE001
            s = {
                "night_record_id": p.stem,
                "status": "FAIL",
                "error": f"{type(e).__name__}: {e}",
            }
            msg_tail = f"ERROR: {s['error']}"
        rows.append(s)
        if verbose:
            print(f"[{i:>4}/{len(candidates)}] {p.name} → {s['status']}  {msg_tail}")

    elapsed = time.time() - t0

    # --- Summary CSV -------------------------------------------------------
    df_summary = pd.DataFrame(rows)
    EVENTS_SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_summary.to_csv(EVENTS_SUMMARY_CSV, index=False)

    # --- Gate JSON ---------------------------------------------------------
    n_ok = int((df_summary["status"] == "OK").sum())
    n_fail = int((df_summary["status"] == "FAIL").sum())
    ok_df = df_summary[df_summary["status"] == "OK"]

    def _dist(col: str) -> dict:
        if ok_df.empty or col not in ok_df.columns:
            return {"median": None, "p5": None, "p95": None, "min": None, "max": None}
        s = pd.to_numeric(ok_df[col], errors="coerce").dropna()
        if s.empty:
            return {"median": None, "p5": None, "p95": None, "min": None, "max": None}
        return {
            "median": float(np.median(s)),
            "p5":     float(np.percentile(s, 5)),
            "p95":    float(np.percentile(s, 95)),
            "min":    float(s.min()),
            "max":    float(s.max()),
        }

    def _count_true(col: str) -> int:
        if ok_df.empty or col not in ok_df.columns:
            return 0
        return int(ok_df[col].astype(bool).sum())

    gate = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "silver_dir": str(silver_dir),
        "events_dir": str(events_dir),
        "bronze_dir": str(bronze_dir),
        "n_silver_input": int(len(df_summary)),
        "n_ok": n_ok,
        "n_fail": n_fail,
        "elapsed_s": round(elapsed, 2),
        "algorithm_version": ALGORITHM_VERSION_PAC_V2,
        "events_schema_version": EVENTS_SCHEMA_VERSION,
        "thresholds": {
            "edo_baseline_window_s": EDO_BASELINE_WINDOW_S,
            "edo_recovery_pct": EDO_RECOVERY_PCT,
            "edo_min_duration_s": EDO_MIN_DURATION_S,
            "edo_drop_thresholds_pct": EDO_DROP_THRESHOLDS_PCT,
            "edo_resample_n_points": EDO_RESAMPLE_N_POINTS,
            "near_gap_window_s": NEAR_GAP_WINDOW_S,
            "hr_brady_threshold_bpm": HR_BRADY_THRESHOLD_BPM,
            "hr_tachy_threshold_bpm": HR_TACHY_THRESHOLD_BPM,
            "diff_rel_flag_threshold": DIFF_REL_FLAG_THRESHOLD,
            "ird_weights": IRD_WEIGHTS,
        },
        "metrics_distribution": {
            "n_edos_total": _dist("n_edos_total"),
            "odi_3": _dist("odi_3"),
            "odi_4": _dist("odi_4"),
            "ahi_3": _dist("ahi_3"),
            "ahi_4": _dist("ahi_4"),
            "ird_night": _dist("ird_night"),
            "tst_s": _dist("tst_s"),
            "sleep_efficiency": _dist("sleep_efficiency"),
            "t90_frac": _dist("t90_frac"),
            "hypoxic_burden_90": _dist("hypoxic_burden_90"),
        },
        "diff_flag_counts": {
            "odi_3_diff_flag": _count_true("odi_3_diff_flag"),
            "odi_4_diff_flag": _count_true("odi_4_diff_flag"),
            "ahi_3_diff_flag": _count_true("ahi_3_diff_flag"),
            "ahi_4_diff_flag": _count_true("ahi_4_diff_flag"),
            "tst_s_diff_flag": _count_true("tst_s_diff_flag"),
            "sleep_efficiency_diff_flag": _count_true("sleep_efficiency_diff_flag"),
        },
        "has_classical_sidecar_count": _count_true("has_classical_sidecar"),
    }
    with open(EVENTS_GATE_JSON, "w", encoding="utf-8") as f:
        json.dump(gate, f, indent=2, ensure_ascii=False, default=str)

    if verbose:
        print("")
        print("=" * 60)
        print(f"[events] DONE en {elapsed:.1f}s — OK={n_ok}  FAIL={n_fail}")
        print(f"[events] summary: {EVENTS_SUMMARY_CSV}")
        print(f"[events] gate:    {EVENTS_GATE_JSON}")

    return df_summary


def main() -> int:
    """CLI mínima: --limit N."""
    limit = None
    args = sys.argv[1:]
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("uso: python -m pac.events_pipeline [--limit N]")
            return 2
    df = run_events(limit=limit)
    return 0 if (df["status"] == "OK").any() else 1


if __name__ == "__main__":
    sys.exit(main())
