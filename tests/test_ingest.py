"""
PAC_v2 — Etapa 1 Bronze: tests unitarios de helpers de ingest.

Cubre sólo las funciones puras (sin I/O):
  - _parse_ampm_time
  - reconstruct_timestamps   (incluyendo cruce de medianoche)
  - compute_night_record_id  (determinismo + sensibilidad a cambios)
  - compute_sha256           (determinismo sobre contenido)
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

# Hacer `pac` importable como paquete local
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from pac.ingest import (  # noqa: E402
    _parse_ampm_time,
    compute_night_record_id,
    compute_sha256,
    reconstruct_timestamps,
)


# ---------------------------------------------------------------------------
# _parse_ampm_time
# ---------------------------------------------------------------------------
def test_ampm_am_basic():
    assert _parse_ampm_time("06:00:18 AM") == (6, 0, 18)


def test_ampm_pm_basic():
    assert _parse_ampm_time("11:03:23 PM") == (23, 3, 23)


def test_ampm_12am_is_midnight():
    assert _parse_ampm_time("12:00:00 AM") == (0, 0, 0)


def test_ampm_12pm_is_noon():
    assert _parse_ampm_time("12:30:45 PM") == (12, 30, 45)


def test_ampm_narrow_nbsp_separator():
    # El xlsx usa U+202F narrow no-break space entre segundos y AM/PM
    s = "11:03:23\u202fPM"
    assert _parse_ampm_time(s) == (23, 3, 23)


def test_ampm_lowercase():
    assert _parse_ampm_time("07:15:00 pm") == (19, 15, 0)


# ---------------------------------------------------------------------------
# reconstruct_timestamps
# ---------------------------------------------------------------------------
def test_reconstruct_no_midnight_cross():
    ts_start = datetime(2026, 1, 17, 23, 3, 23)
    times = pd.Series(["11:03:23 PM", "11:03:24 PM", "11:03:25 PM"])
    out = reconstruct_timestamps(times, ts_start)
    assert list(out) == [
        pd.Timestamp("2026-01-17 23:03:23"),
        pd.Timestamp("2026-01-17 23:03:24"),
        pd.Timestamp("2026-01-17 23:03:25"),
    ]


def test_reconstruct_midnight_cross():
    """Pase de 23:59:59 PM a 12:00:00 AM → +1 día."""
    ts_start = datetime(2026, 1, 17, 23, 59, 58)
    times = pd.Series(
        ["11:59:58 PM", "11:59:59 PM", "12:00:00 AM", "12:00:01 AM"]
    )
    out = reconstruct_timestamps(times, ts_start)
    assert list(out) == [
        pd.Timestamp("2026-01-17 23:59:58"),
        pd.Timestamp("2026-01-17 23:59:59"),
        pd.Timestamp("2026-01-18 00:00:00"),
        pd.Timestamp("2026-01-18 00:00:01"),
    ]


def test_reconstruct_with_gaps():
    """Gaps en los datos no rompen el cruce de medianoche."""
    ts_start = datetime(2026, 1, 17, 23, 59, 50)
    times = pd.Series(
        ["11:59:50 PM", "11:59:55 PM", "12:00:10 AM", "12:01:00 AM"]
    )
    out = reconstruct_timestamps(times, ts_start)
    assert out.iloc[0] == pd.Timestamp("2026-01-17 23:59:50")
    assert out.iloc[-1] == pd.Timestamp("2026-01-18 00:01:00")
    # Monotonía estricta
    assert (out.diff().dropna() > pd.Timedelta(0)).all()


def test_reconstruct_am_to_am_no_false_crossing():
    """Noche que arranca AM no debe detectar cruce hacia atrás."""
    ts_start = datetime(2026, 1, 18, 2, 0, 0)
    times = pd.Series(["02:00:00 AM", "02:00:01 AM", "02:00:02 AM"])
    out = reconstruct_timestamps(times, ts_start)
    assert out.iloc[0] == pd.Timestamp("2026-01-18 02:00:00")
    assert out.iloc[-1] == pd.Timestamp("2026-01-18 02:00:02")


# ---------------------------------------------------------------------------
# compute_night_record_id
# ---------------------------------------------------------------------------
def test_nrid_deterministic():
    sha = "a" * 64
    ts = "2026-01-17T23:03:23"
    assert compute_night_record_id(sha, ts) == compute_night_record_id(sha, ts)


def test_nrid_prefix_and_length():
    nrid = compute_night_record_id("x" * 64, "2026-01-17T23:03:23")
    assert nrid.startswith("NR_")
    assert len(nrid) == 3 + 10  # prefix + hash_len


def test_nrid_changes_with_sha():
    a = compute_night_record_id("a" * 64, "2026-01-17T23:03:23")
    b = compute_night_record_id("b" * 64, "2026-01-17T23:03:23")
    assert a != b


def test_nrid_changes_with_ts_start():
    sha = "c" * 64
    a = compute_night_record_id(sha, "2026-01-17T23:03:23")
    b = compute_night_record_id(sha, "2026-01-17T23:03:24")
    assert a != b


# ---------------------------------------------------------------------------
# compute_sha256
# ---------------------------------------------------------------------------
def test_sha256_matches_hashlib():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"PAC_v2 unit test payload")
        p = Path(f.name)
    try:
        expected = hashlib.sha256(b"PAC_v2 unit test payload").hexdigest()
        assert compute_sha256(p) == expected
    finally:
        p.unlink()


# ---------------------------------------------------------------------------
# Runner manual (sin pytest): python -m tests.test_ingest
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
    print(f"[tests/test_ingest] {total - fail}/{total} OK")
    sys.exit(0 if fail == 0 else 1)
