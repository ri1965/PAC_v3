"""
PAC_v2 — Etapa 1 Bronze: helpers atómicos de ingest.

Cada función hace UNA cosa y se testea independiente.
El orquestador vive en bronze.py.

Flujo por noche:
    xlsx  →  load_xlsx_night  →  (meta, classical, signals_raw)
          →  normalize_signals  →  signals_canónicas (5 cols)
          →  write_signals_parquet + write_classical_sidecar
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from pac.config import (
    BRONZE_DIR,
    CLINICAL_COLS,
    CLINICAL_CSV,
    NIGHT_ID_HASH_LEN,
    NIGHT_ID_PREFIX,
    PATIENT_REGISTRY_CSV,
    REGISTRY_COLS,
    SAMPLING_HZ_NOMINAL,
    SIGNAL_COLS,
    XLSX_SIGNAL_MAP,
)
from pac.io import (
    read_clinical,
    read_patient_registry,
    write_identity_csv,
)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def compute_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 de un archivo en streaming (chunks de 1 MiB)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_night_record_id(source_sha256: str, ts_start_iso: str) -> str:
    """
    NightRecordID = NR_ + MD5(source_sha256 | ts_start_iso)[:10]

    Sin salt (decisión PAC_v2). Determinístico → idempotente.
    """
    payload = f"{source_sha256}|{ts_start_iso}".encode("utf-8")
    digest = hashlib.md5(payload).hexdigest()
    return f"{NIGHT_ID_PREFIX}{digest[:NIGHT_ID_HASH_LEN]}"


# ---------------------------------------------------------------------------
# Carga del xlsx (3 bloques)
# ---------------------------------------------------------------------------
# Estructura del xlsx (verificada sobre exam_12514.xlsx):
#   Bloque 1 (filas 1-2):   metadata    → id, time_start, time_end, user_id
#   Bloque 2 (filas 4-5):   ~21 índices clásicos pre-computados por el dispositivo
#   Bloque 3 (filas 7+):    per-second → somni_epoch, time, spo2, bpm,
#                                         acceleration_module, discharge_level,
#                                         battery_level, temperature, sleep_stage
# Separador entre bloques: filas completamente vacías.
def load_xlsx_night(path: Path) -> Tuple[Dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """
    Lee un xlsx de noche y devuelve (meta, classical, signals_raw).

    meta:       dict con id, time_start (datetime), time_end (datetime), user_id.
    classical:  DataFrame 1×N con los índices pre-computados (ahi, odi, etc.).
    signals_raw: DataFrame con las columnas originales del bloque per-second.
    """
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    ws = wb.active
    # Algunos xlsx vienen "unsized" (sin dimension tag). iter_rows igual
    # recorre el contenido. Si la versión de openpyxl soporta force=True, lo
    # usamos para asegurar max_row/max_col correctos; si no, pasamos.
    try:
        ws.calculate_dimension(force=True)  # type: ignore[call-arg]
    except TypeError:
        try:
            ws.reset_dimensions()
        except AttributeError:
            pass

    # Volcamos todo a una matriz de valores; después segmentamos por filas vacías.
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    # Índices de filas no vacías (alguna celda con contenido ≠ None y ≠ "").
    def is_empty(r):
        return all(v is None or (isinstance(v, str) and v.strip() == "") for v in r)

    # Segmentación en bloques (grupos de filas no vacías consecutivas).
    blocks: list[list[tuple]] = []
    current: list[tuple] = []
    for r in rows:
        if is_empty(r):
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(r)
    if current:
        blocks.append(current)

    if len(blocks) < 3:
        raise ValueError(
            f"xlsx con estructura inesperada: {len(blocks)} bloques (se esperaban 3). {path.name}"
        )

    # --- Bloque 1: metadata -------------------------------------------------
    meta_block = blocks[0]
    if len(meta_block) < 2:
        raise ValueError(f"Bloque 1 (metadata) sin fila de valores: {path.name}")
    meta_headers = [str(c).strip() if c is not None else "" for c in meta_block[0]]
    meta_values = list(meta_block[1])
    meta: Dict[str, Any] = {
        k: v for k, v in zip(meta_headers, meta_values) if k
    }

    # --- Bloque 2: classical indices ---------------------------------------
    clf_block = blocks[1]
    if len(clf_block) < 2:
        raise ValueError(f"Bloque 2 (classical) sin fila de valores: {path.name}")
    clf_headers = [str(c).strip() if c is not None else "" for c in clf_block[0]]
    # Filtra columnas vacías al final
    width = len([h for h in clf_headers if h])
    clf_headers = clf_headers[:width]
    clf_values = list(clf_block[1])[:width]
    classical = pd.DataFrame([clf_values], columns=clf_headers)

    # --- Bloque 3: per-second signals --------------------------------------
    sig_block = blocks[2]
    if len(sig_block) < 2:
        raise ValueError(f"Bloque 3 (signals) sin datos: {path.name}")
    sig_headers = [str(c).strip() if c is not None else "" for c in sig_block[0]]
    width = len([h for h in sig_headers if h])
    sig_headers = sig_headers[:width]
    signals_rows = [list(r)[:width] for r in sig_block[1:]]
    signals_raw = pd.DataFrame(signals_rows, columns=sig_headers)

    return meta, classical, signals_raw


# ---------------------------------------------------------------------------
# Reconstrucción de timestamps
# ---------------------------------------------------------------------------
# El xlsx trae `time` como string "HH:MM:SS AM/PM" con separador unicode
# \u202f (narrow no-break space). Las noches cruzan medianoche → hay que
# detectar el cambio de día vectorialmente.
_TIME_STR_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2}):(\d{2})\s*([AaPp][Mm])\s*$"
)


def _parse_ampm_time(s: str) -> Tuple[int, int, int]:
    """Parsea 'HH:MM:SS AM/PM' y devuelve (h24, m, s). Tolera unicode NBSP."""
    if s is None:
        raise ValueError("time string vacío")
    # Normalizar separadores raros: NBSP, narrow NBSP, tabs, etc.
    norm = str(s).replace("\u202f", " ").replace("\xa0", " ").strip()
    m = _TIME_STR_RE.match(norm)
    if not m:
        raise ValueError(f"time string no parseable: {s!r}")
    h = int(m.group(1))
    mm = int(m.group(2))
    ss = int(m.group(3))
    ampm = m.group(4).upper()
    if ampm == "AM":
        h24 = 0 if h == 12 else h
    else:  # PM
        h24 = 12 if h == 12 else h + 12
    return h24, mm, ss


def reconstruct_timestamps(
    time_strs: pd.Series,
    ts_start: datetime,
) -> pd.Series:
    """
    Reconstruye timestamps absolutos a partir de la columna `time` (HH:MM:SS AM/PM).

    Estrategia:
      1. Parsear cada string → segundos desde medianoche.
      2. Cambio de día = acumulado de bajadas en `seconds_since_midnight.diff()`.
         Un cruce medianoche ocurre cuando sec pasa de ≈86400 a ≈0 (diff < 0).
      3. Fecha base = fecha de `ts_start`.
      4. timestamp = date_base + day_offset + time_delta.

    Robusto a gaps: no asume muestreo 1 Hz estricto, sólo usa el string del xlsx.
    Si ts_start está en la tarde/noche del día D, día 0 = D, día 1 = D+1, etc.
    """
    secs = []
    for s in time_strs:
        h, m, sec = _parse_ampm_time(s)
        secs.append(h * 3600 + m * 60 + sec)
    secs = pd.Series(secs, index=time_strs.index, dtype="int64")

    # day_offset: cada vez que seconds_since_midnight baja → cruzó medianoche.
    # cumsum de (diff < 0) con shift=0 en la primera fila.
    diff = secs.diff().fillna(0)
    day_offset = (diff < 0).astype("int64").cumsum()

    # Fecha base: la fecha calendario del primer timestamp del archivo.
    # Esta fecha la inferimos del propio xlsx `time_start` (del bloque 1).
    base_date = ts_start.date()

    # Construcción vectorial de datetimes
    base_ts = pd.Timestamp(base_date)
    timestamps = (
        base_ts
        + pd.to_timedelta(day_offset, unit="D")
        + pd.to_timedelta(secs, unit="s")
    )

    # Sanity: el primer timestamp reconstruido debería coincidir con ts_start
    # (hasta nivel de segundo). Si no, ajustamos el offset base.
    first_ts = timestamps.iloc[0]
    expected = pd.Timestamp(ts_start.replace(microsecond=0))
    drift = (first_ts - expected).total_seconds()

    # Si el primer valor es ≥1 día posterior a ts_start (xlsx grabado antes de
    # medianoche y ts_start marca el día anterior), no corrige. En la práctica
    # ts_start del xlsx y el primer `time` coinciden por construcción.
    if abs(drift) >= 86400:
        timestamps = timestamps - pd.to_timedelta(round(drift / 86400), unit="D")

    return timestamps


# ---------------------------------------------------------------------------
# Normalización de signals
# ---------------------------------------------------------------------------
def normalize_signals(
    signals_raw: pd.DataFrame,
    ts_start: datetime,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Mapea signals_raw (columnas del xlsx) → DataFrame canónico con SIGNAL_COLS.

    Devuelve (df_canónico, diagnostics).

    diagnostics:
      - n_samples
      - sampling_hz_median (sanity)
      - n_gaps (muestras con delta > 1.5s)
      - ts_first, ts_last (iso)
      - duration_s
    """
    # Validar columnas mínimas
    required_xlsx = set(XLSX_SIGNAL_MAP.keys())
    missing = required_xlsx - set(signals_raw.columns)
    if missing:
        raise ValueError(f"xlsx signals sin columnas requeridas: {sorted(missing)}")

    # Subset + rename según mapping
    df = signals_raw[list(XLSX_SIGNAL_MAP.keys())].rename(columns=XLSX_SIGNAL_MAP).copy()

    # Reconstruir timestamp desde _time_str
    df["timestamp"] = reconstruct_timestamps(df["_time_str"], ts_start)
    df = df.drop(columns=["_time_str"])

    # Coerciones numéricas
    for col in ("spo2", "hr", "mov"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # sleep_stage puede ser entero o categórico — lo dejamos como viene,
    # coerción suave a numérico (Int64 nullable).
    df["sleep_stage"] = pd.to_numeric(df["sleep_stage"], errors="coerce").astype("Int64")

    # Reordenar según contrato
    df = df[SIGNAL_COLS]

    # Diagnósticos
    n = len(df)
    ts_first = df["timestamp"].iloc[0]
    ts_last = df["timestamp"].iloc[-1]
    duration_s = (ts_last - ts_first).total_seconds()
    # Mediana del paso entre muestras (Hz sanity)
    deltas = df["timestamp"].diff().dt.total_seconds().dropna()
    sampling_hz_median = float(1.0 / deltas.median()) if len(deltas) and deltas.median() > 0 else float("nan")
    n_gaps = int((deltas > 1.5).sum())

    diagnostics = {
        "n_samples": int(n),
        "sampling_hz_median": round(sampling_hz_median, 4),
        "sampling_hz_nominal": SAMPLING_HZ_NOMINAL,
        "n_gaps": n_gaps,
        "ts_first": ts_first.isoformat(),
        "ts_last": ts_last.isoformat(),
        "duration_s": float(duration_s),
    }
    return df, diagnostics


# ---------------------------------------------------------------------------
# Escritura parquet con metadata al nivel de schema
# ---------------------------------------------------------------------------
def write_signals_parquet(
    df: pd.DataFrame,
    path: Path,
    kv_metadata: Dict[str, str],
) -> None:
    """
    Escribe el parquet canónico con metadata al nivel de schema.
    pyarrow persiste el dict como bytes → se lee como schema.metadata.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=False)
    # Merge con cualquier metadata existente de pandas
    existing = table.schema.metadata or {}
    merged = dict(existing)
    merged.update({k.encode("utf-8"): str(v).encode("utf-8") for k, v in kv_metadata.items()})
    table = table.replace_schema_metadata(merged)
    pq.write_table(table, path, compression="snappy")


def write_classical_sidecar(
    classical: pd.DataFrame,
    path: Path,
    kv_metadata: Dict[str, str],
) -> None:
    """Sidecar 1-row con los índices clásicos pre-computados del dispositivo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(classical, preserve_index=False)
    merged = dict(table.schema.metadata or {})
    merged.update({k.encode("utf-8"): str(v).encode("utf-8") for k, v in kv_metadata.items()})
    table = table.replace_schema_metadata(merged)
    pq.write_table(table, path, compression="snappy")


# ---------------------------------------------------------------------------
# Auto-registro de pacientes nuevos (stubs en identity CSVs)
# ---------------------------------------------------------------------------
def peek_user_id(xlsx_path: Path) -> str:
    """
    Lee SÓLO el Bloque 1 (metadata) de un xlsx y devuelve `user_id` como str.

    Optimización: abre en read_only y rompe después de 2 filas, ~10-50 ms/xlsx
    vs ~5 s del load_xlsx_night completo.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    headers: list[str] = []
    values: list[Any] = []
    try:
        ws = wb.active
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                headers = [str(c).strip() if c is not None else "" for c in row]
            elif i == 1:
                values = list(row)
                break
    finally:
        wb.close()
    if not headers or not values:
        return ""
    meta = {k: v for k, v in zip(headers, values) if k}
    uid = meta.get("user_id", "")
    return str(uid).strip() if uid is not None else ""


def scan_xlsx_user_ids(xlsx_paths: list[Path]) -> Dict[str, list[str]]:
    """
    Escanea cada xlsx con peek_user_id y devuelve {user_id: [xlsx_filename, ...]}.
    Los xlsx que fallan al abrirse se ignoran silenciosamente (bronze los reportará
    como FAIL en la corrida normal).
    """
    m: Dict[str, list[str]] = {}
    for p in xlsx_paths:
        try:
            uid = peek_user_id(p)
        except Exception:  # noqa: BLE001
            continue
        if uid:
            m.setdefault(uid, []).append(p.name)
    return m


def register_stubs_for_unknown_ids(
    xlsx_user_ids: Dict[str, list[str]],
    verbose: bool = True,
) -> Dict[str, list[str]]:
    """
    Dado un mapping user_id → [xlsx], detecta los user_ids que NO están en
    patient_registry.csv y agrega filas stub (patient_id lleno, otros campos
    vacíos) a patient_registry.csv y clinical.csv.

    Idempotente: si todos los user_ids ya existen, no toca los CSVs.

    Returns:
        Dict con el subset de xlsx_user_ids que disparó creación de stub.
        Diccionario vacío si no se crearon stubs.
    """
    registry = read_patient_registry()
    clinical = read_clinical()
    known = set(
        str(x).strip() for x in registry["patient_id"].tolist() if str(x).strip()
    )

    new_ids = sorted(uid for uid in xlsx_user_ids.keys() if uid not in known)

    if not new_ids:
        if verbose:
            print(
                f"[autoreg] sin pacientes nuevos — {len(known)} ya en registry, 0 stubs creados."
            )
        return {}

    # Armar stubs con patient_id lleno y el resto en ""
    stub_registry = pd.DataFrame(
        {col: ([uid for uid in new_ids] if col == "patient_id" else [""] * len(new_ids))
         for col in REGISTRY_COLS}
    )
    stub_clinical = pd.DataFrame(
        {col: ([uid for uid in new_ids] if col == "patient_id" else [""] * len(new_ids))
         for col in CLINICAL_COLS}
    )

    new_registry = pd.concat([registry, stub_registry], ignore_index=True)
    new_clinical = pd.concat([clinical, stub_clinical], ignore_index=True)

    write_identity_csv(new_registry, PATIENT_REGISTRY_CSV, REGISTRY_COLS)
    write_identity_csv(new_clinical, CLINICAL_CSV, CLINICAL_COLS)

    result = {uid: xlsx_user_ids[uid] for uid in new_ids}

    if verbose:
        print("")
        print(f"[AUTOREG] Detectados {len(new_ids)} user_id nuevos en raw/:")
        for uid in new_ids:
            xlsxs = xlsx_user_ids[uid]
            preview = xlsxs[0] if len(xlsxs) == 1 else f"{xlsxs[0]} + {len(xlsxs)-1} más"
            print(f"   · {uid}  ({len(xlsxs)} xlsx: {preview})")
        print(f"   → filas stub agregadas a {PATIENT_REGISTRY_CSV.name} y {CLINICAL_CSV.name}")
        print("   → RECORDAR completar datos clínicos a mano antes del próximo análisis")
        print("")

    return result


# ---------------------------------------------------------------------------
# Parseo tolerante de datetime ts_start/ts_end
# ---------------------------------------------------------------------------
def parse_xlsx_datetime(v: Any) -> datetime:
    """
    El bloque 1 puede traer time_start como datetime (openpyxl) o como string.
    Normalizamos a datetime naive (sin timezone).
    """
    if isinstance(v, datetime):
        return v.replace(microsecond=0, tzinfo=None)
    s = str(v).strip()
    # Formatos frecuentes
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    # Fallback: pandas
    ts = pd.to_datetime(s, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"no se pudo parsear time_start/time_end: {v!r}")
    return ts.to_pydatetime().replace(microsecond=0, tzinfo=None)


# ---------------------------------------------------------------------------
# Pipeline por xlsx (usado por bronze.py)
# ---------------------------------------------------------------------------
def ingest_one(
    xlsx_path: Path,
    known_patient_ids: set[str],
) -> Dict[str, Any]:
    """
    Procesa un único xlsx. Devuelve un dict con el resultado (status + métricas).
    NO lanza excepciones: las captura y las reporta como status=FAIL.

    status posibles:
      - OK:           parquets generados.
      - SKIP_COHORT:  user_id no está en el patient_registry.
      - FAIL:         error en parseo / escritura.
    """
    result: Dict[str, Any] = {
        "xlsx": xlsx_path.name,
        "xlsx_bytes": xlsx_path.stat().st_size,
        "status": "FAIL",
        "error": "",
        "source_exam_id": "",
        "user_id": "",
        "ts_start": "",
        "ts_end": "",
        "night_record_id": "",
        "n_samples": 0,
        "sampling_hz_median": "",
        "n_gaps": 0,
        "duration_s": 0.0,
        "source_sha256": "",
    }
    try:
        # SHA antes que nada (barato, no lee openpyxl)
        sha = compute_sha256(xlsx_path)
        result["source_sha256"] = sha

        meta, classical, signals_raw = load_xlsx_night(xlsx_path)

        user_id = str(meta.get("user_id", "")).strip()
        source_exam_id = str(meta.get("id", "")).strip()
        ts_start = parse_xlsx_datetime(meta.get("time_start"))
        ts_end = parse_xlsx_datetime(meta.get("time_end"))

        result["user_id"] = user_id
        result["source_exam_id"] = source_exam_id
        result["ts_start"] = ts_start.isoformat()
        result["ts_end"] = ts_end.isoformat()

        # Filtro por cohorte
        if user_id not in known_patient_ids:
            result["status"] = "SKIP_COHORT"
            return result

        # NightRecordID
        nrid = compute_night_record_id(sha, ts_start.isoformat())
        result["night_record_id"] = nrid

        # Normalización
        signals, diag = normalize_signals(signals_raw, ts_start)
        result.update({
            "n_samples": diag["n_samples"],
            "sampling_hz_median": diag["sampling_hz_median"],
            "n_gaps": diag["n_gaps"],
            "duration_s": diag["duration_s"],
        })

        # Metadata para el schema
        kv = {
            "night_record_id": nrid,
            "source_file": xlsx_path.name,
            "source_sha256": sha,
            "source_exam_id": source_exam_id,
            "user_id": user_id,
            "ts_start": ts_start.isoformat(),
            "ts_end": ts_end.isoformat(),
            "n_samples": str(diag["n_samples"]),
            "sampling_hz_nominal": str(SAMPLING_HZ_NOMINAL),
            "sampling_hz_median": str(diag["sampling_hz_median"]),
            "n_gaps": str(diag["n_gaps"]),
            "duration_s": str(diag["duration_s"]),
            "pipeline_stage": "bronze",
            "pipeline_version": "pac_v2.1",
        }

        # Escritura (silent overwrite si ya existe)
        signals_path = BRONZE_DIR / f"{nrid}.parquet"
        classical_path = BRONZE_DIR / f"{nrid}_classical.parquet"
        write_signals_parquet(signals, signals_path, kv)
        write_classical_sidecar(classical, classical_path, kv)

        result["status"] = "OK"
    except Exception as e:  # noqa: BLE001
        result["status"] = "FAIL"
        result["error"] = f"{type(e).__name__}: {e}"
    return result
