"""
PAC_v2 — Etapa 4 paso 8: tests para scripts/qa_pac_states_batch.py.

Cubre las funciones de check (B1/B2/B3/B4/B5) sin depender de los parquets
reales en states/. Toda la fixture es sintética y reproducible.

Tests (8):
  - b1_schema_pass            : parquet con OUTPUT_COLS + dtypes correctos → PASS
  - b1_schema_missing_col     : drop col → FAIL violator con cols_mismatch
  - b2_coverage_perfect       : ventanas disjuntas que llenan span → ratio≈1.0
  - b2_coverage_below_warn    : ventanas con gaps → ratio<0.95 → status WARN
  - b3_dominance_detects      : un cluster con >95% → flag B3
  - b4_outlier_frac_basic     : threshold conocido → frac correcta por escala
  - b5_coh_homogeneous        : todas m-windows mismo cluster → coh≈1.0
  - b5_coh_max_diverse        : m-windows uniforme sobre k clusters → coh≈0
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Importar el módulo a testear.
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import qa_pac_states_batch as qa  # noqa: E402


# ===========================================================================
# Fixtures sintéticas de DataFrames states/
# ===========================================================================
def _make_states_df(
    nr: str = "NR_test000001",
    n_l: int = 4,
    n_m: int = 24,
    n_s: int = 240,
    l_dur: float = 1800.0,
    m_dur: float = 300.0,
    s_dur: float = 30.0,
    cluster_pattern: dict | None = None,
    contiguous: bool = True,
) -> pd.DataFrame:
    """
    DataFrame sintético compatible con OUTPUT_COLS.
    cluster_pattern: dict {scale: array de cluster_int de len n_<scale>}.
                     Default: alternancia 0,1,2,... (cíclica con K=3).
    contiguous: si False, mete un gap de l_dur al medio (cobertura<1).
    """
    t0 = pd.Timestamp("2026-04-24 22:00:00")
    rows = []

    for scale, n, dur in [("l", n_l, l_dur), ("m", n_m, m_dur), ("s", n_s, s_dur)]:
        clusters = (cluster_pattern or {}).get(
            scale, np.arange(n) % 3,
        )
        for i in range(n):
            t_start_s = i * dur if contiguous else (i + (1 if i >= n // 2 else 0)) * dur
            t_end_s = t_start_s + dur
            c = int(clusters[i])
            rows.append({
                "night_record_id": nr,
                "scale": scale,
                "window_idx": i,
                "t_start": t0 + pd.Timedelta(seconds=t_start_s),
                "t_end": t0 + pd.Timedelta(seconds=t_end_s),
                "t_start_s": float(t_start_s),
                "t_end_s": float(t_end_s),
                "state_label": f"{scale.upper()}{c}" if c >= 0 else None,
                "cluster_int": c,
                "dist_to_centroid": float(np.random.default_rng(i).uniform(0.5, 3.0))
                                    if c >= 0 else float("nan"),
                "coverage": 1.0,
                "frac_wake": 0.1,
                "frac_light_sleep": 0.6,
                "frac_deep_sleep": 0.3,
                "training_eligible": True,
            })
    df = pd.DataFrame(rows)
    # Forzar dtypes esperados.
    df["window_idx"] = df["window_idx"].astype("int64")
    df["cluster_int"] = df["cluster_int"].astype("int64")
    df["training_eligible"] = df["training_eligible"].astype("bool")
    return df


def _write_states_parquet(df: pd.DataFrame, path: Path, k_per_scale: dict) -> None:
    """Escribe parquet + KV metadata mínima (k_per_scale) para que QA lo lea."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(df, preserve_index=False)
    import json as _json
    kv = {b"k_per_scale": _json.dumps(k_per_scale).encode()}
    new_md = {**(table.schema.metadata or {}), **kv}
    table = table.replace_schema_metadata(new_md)
    pq.write_table(table, path)


# ===========================================================================
# B1 schema_lock_per_night
# ===========================================================================
class TestB1Schema:
    def test_b1_schema_pass(self, tmp_path: Path):
        """Parquet con OUTPUT_COLS y dtypes correctos → PASS."""
        df = _make_states_df()
        p = tmp_path / "NR_b1pass00001.parquet"
        _write_states_parquet(df, p, {"s": 6, "m": 8, "l": 6})

        result = qa.check_b1_schema_lock([p])
        assert result["status"] == "PASS"
        assert result["n_violators"] == 0

    def test_b1_schema_missing_col(self, tmp_path: Path):
        """Si drop col 'coverage' → FAIL con cols_mismatch."""
        df = _make_states_df().drop(columns=["coverage"])
        p = tmp_path / "NR_b1bad000001.parquet"
        df.to_parquet(p)  # OK escribir sin la col

        result = qa.check_b1_schema_lock([p])
        assert result["status"] == "FAIL"
        assert result["n_violators"] == 1
        viol = result["violators"][0]
        assert viol["issue"] == "cols_mismatch"
        assert "coverage" in viol["missing"]


# ===========================================================================
# B2 temporal_coverage
# ===========================================================================
class TestB2Coverage:
    def test_b2_coverage_perfect_contiguous(self):
        """Ventanas disjuntas y contiguas → ratio ≈ 1.0 en las 3 escalas."""
        df = _make_states_df(contiguous=True)
        cov = qa.compute_b2_coverage_for_night(df)
        # Cada escala debe sumar ≈ span total.
        for scale in ("s", "m", "l"):
            assert abs(cov[scale] - 1.0) < 1e-6, \
                f"scale {scale}: ratio={cov[scale]} (esperado ≈1.0)"

    def test_b2_coverage_below_warn_with_gaps(self):
        """Ventanas con gap grande al final → ratio bien por debajo de 0.95 → WARN/FAIL."""
        # Construyo manualmente: 10 l-windows de 1800s cada una, contiguas,
        # PERO la última está movida 5*1800s adelante (gap = 5 ventanas perdidas).
        # Suma = 10*1800 = 18000s. Span = 14*1800 = 25200s. Ratio = 18000/25200 = 0.714.
        rows = []
        t0 = pd.Timestamp("2026-04-24 22:00:00")
        for i in range(10):
            shift = 5 if i == 9 else 0  # mover sólo la última
            t_start_s = (i + shift) * 1800.0
            t_end_s = t_start_s + 1800.0
            rows.append({
                "night_record_id": "NR_b2gap000001",
                "scale": "l",
                "window_idx": i,
                "t_start": t0 + pd.Timedelta(seconds=t_start_s),
                "t_end": t0 + pd.Timedelta(seconds=t_end_s),
                "t_start_s": float(t_start_s),
                "t_end_s": float(t_end_s),
                "state_label": "L0",
                "cluster_int": 0,
                "dist_to_centroid": 1.0,
                "coverage": 1.0,
                "frac_wake": 0.1,
                "frac_light_sleep": 0.6,
                "frac_deep_sleep": 0.3,
                "training_eligible": True,
            })
        df = pd.DataFrame(rows)
        cov = qa.compute_b2_coverage_for_night(df)
        ratio = cov["l"]
        status = qa.b2_status_from_ratio(ratio)
        assert ratio < 0.85, f"ratio={ratio}"
        assert status == "FAIL", f"ratio={ratio}, status={status}"


# ===========================================================================
# B3 per_night_cluster_dominance
# ===========================================================================
class TestB3Dominance:
    def test_b3_no_dominance_normal(self):
        """Patrón balanceado → max_dom ≈ 1/3 → no flag."""
        df = _make_states_df()
        dom = qa.compute_b3_dominance_for_night(df)
        for scale in ("s", "m", "l"):
            assert dom[scale] < qa.B3_MAX_DOMINANCE

    def test_b3_dominance_detects_monopoly(self):
        """Si todos los clusters de m son 0 → max_dom=1.0 → flag."""
        df = _make_states_df(cluster_pattern={"m": np.zeros(24, dtype=int)})
        dom = qa.compute_b3_dominance_for_night(df)
        assert dom["m"] == 1.0
        assert dom["m"] > qa.B3_MAX_DOMINANCE


# ===========================================================================
# B4 dist_to_centroid_outliers
# ===========================================================================
class TestB4Outliers:
    def test_b4_outlier_frac_with_known_threshold(self):
        """Con thresholds dummy, frac es la cola observada."""
        df = _make_states_df()
        # threshold por escala = mediana → ~50% por encima
        thresholds = {
            scale: float(df[df["scale"] == scale]["dist_to_centroid"].median())
            for scale in ("s", "m", "l")
        }
        frac = qa.compute_b4_outlier_frac_for_night(df, thresholds)
        for scale in ("s", "m", "l"):
            # Debe estar entre 0 y 1 — y para mediana, cerca de 0.5.
            assert 0.0 <= frac[scale] <= 1.0
            # mediana → ~50% debería ser estricto >, así que ≤ 0.5
            assert frac[scale] <= 0.5 + 0.05


# ===========================================================================
# B5 cross_scale_consistency
# ===========================================================================
class TestB5Coherence:
    def test_b5_coherence_homogeneous(self):
        """Todos los m/s en cada l son del mismo cluster → coh ≈ 1.0."""
        # Con el helper default (n_m=24, n_s=240, n_l=4) y ventanas
        # contiguas alineadas en l_dur=1800s, m_dur=300s, s_dur=30s,
        # cada l contiene exactamente 6 m y 60 s.
        # Forzamos que TODOS los m sean cluster 0 y todos los s sean cluster 0.
        df = _make_states_df(cluster_pattern={
            "l": np.zeros(4, dtype=int),
            "m": np.zeros(24, dtype=int),
            "s": np.zeros(240, dtype=int),
        })
        coh = qa.compute_b5_coherence_for_night(df, {"s": 6, "m": 8, "l": 6})
        assert coh["coh_l_vs_m"] > 0.99, f"got {coh['coh_l_vs_m']}"
        assert coh["coh_l_vs_s"] > 0.99, f"got {coh['coh_l_vs_s']}"

    def test_b5_coherence_max_diverse(self):
        """m uniforme sobre k=8 clusters → entropy max → coh ≈ 0."""
        # Para que la entropía sea máxima dentro de cada l-window (que
        # contiene 6 m-windows), necesitamos los 6 clusters distintos
        # — dado que k_max=8, entropy=log2(6) y coh = 1 - log2(6)/log2(8)
        # ≈ 1 - 2.585/3 ≈ 0.138. Lo que verificamos es que sea BAJO,
        # claramente por debajo del caso homogéneo.
        m_pattern = np.tile(np.arange(6), 4)  # 24 = 4 ciclos de [0..5]
        s_pattern = np.tile(np.arange(6), 40)  # 240 = 40 ciclos de [0..5]
        df = _make_states_df(cluster_pattern={
            "l": np.zeros(4, dtype=int),
            "m": m_pattern,
            "s": s_pattern,
        })
        coh = qa.compute_b5_coherence_for_night(df, {"s": 6, "m": 8, "l": 6})
        # Coherencia debe ser baja (mucho más que 1.0).
        assert coh["coh_l_vs_m"] < 0.3, f"got {coh['coh_l_vs_m']}"
        assert coh["coh_l_vs_s"] < 0.3, f"got {coh['coh_l_vs_s']}"
