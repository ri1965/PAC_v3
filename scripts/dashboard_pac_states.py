"""
PAC_v2 — Etapa 4 paso 6: dashboard HTML de estados PAC.

Genera reports/pac_states_dashboard.html con:

  1. Sweep overview: 3 escalas × 3 métricas (inertia / silhouette / DB) con
     marcadores para el anchor histórico (rojo) y los K candidatos (verde).
  2. Por cada escala × K candidato:
     - Tabla de tamaños de clusters.
     - Heatmap de centroides (cluster × 24 features, z-score).
     - Barras stacked: densidad de morphotypes (α/β/γ/δ) por cluster.
     - Barras stacked: composición de sleep_stage (wake/light/deep) por cluster.
     - Tabla de centroides en espacio original (colapsable).

Todas las imágenes se embebebn como SVG inline → HTML self-contained, sin CDN.

Pipeline:
  1. Lee reports/pac_states_sweep.json (si existe, para curvas del sweep).
  2. Reconstruye el pool por escala desde silver/*.parquet + events/*_edos.parquet
     (~15 min sobre 560 noches; usá --limit N para smoke).
  3. Entrena K candidatos on-the-fly (NO persiste modelos; la persistencia
     se hace recién con `train_pac_states.py --mode final`).

Corre:
  PYTHONPATH=src python scripts/dashboard_pac_states.py --limit 20 --verbose
  PYTHONPATH=src python scripts/dashboard_pac_states.py
  PYTHONPATH=src python scripts/dashboard_pac_states.py --candidates "s:6,7;m:6,8;l:4,6"
"""
from __future__ import annotations

import argparse
import io
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from pac import states as st
from pac import windows as wn
from pac.config import (
    EVENTS_DIR,
    PAC_SLEEP_COMPOSITION_FEATURES,
    PAC_STATE_PREFIXES,
    PAC_STATE_SCALES,
    PAC_STATES_HISTORICAL_K,
    PAC_STATES_RANDOM_STATE,
    PAC_WINDOW_FEATURES,
    REPORTS_DIR,
    SILVER_DIR,
)


sns.set_style("whitegrid")

DASHBOARD_HTML = REPORTS_DIR / "pac_states_dashboard.html"
SWEEP_REPORT_JSON = REPORTS_DIR / "pac_states_sweep.json"

# Candidatos por escala (ver pac_states_sweep.json — elegidos por codo + DB).
DEFAULT_CANDIDATES: dict[str, tuple[int, ...]] = {
    "s": (6, 7, 8),
    "m": (5, 6, 8),
    "l": (4, 6),
}

SCALE_LABEL: dict[str, str] = {
    "s": "s (30 s)",
    "m": "m (5 min)",
    "l": "l (30 min)",
}

# Paleta morphotypes (alineada con dashboard_morphotypes.py).
MORPH_PALETTE: dict[str, str] = {
    "α": "#E63946",
    "β": "#457B9D",
    "γ": "#F4A261",
    "δ": "#2A9D8F",
}

# Paleta sleep_stage (wake = amarillo, light = azul, deep = azul oscuro).
SLEEP_PALETTE: dict[str, str] = {
    "frac_wake": "#F4D35E",
    "frac_light_sleep": "#457B9D",
    "frac_deep_sleep": "#1D3557",
}


# ---------------------------------------------------------------------------
# Helpers render
# ---------------------------------------------------------------------------
def _fig_to_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _df_to_html_table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    return df.map(
        lambda v: float_fmt.format(v) if isinstance(v, (int, float)) and not pd.isna(v)
        else ("" if pd.isna(v) else str(v))
    ).to_html(classes="data", border=0, escape=False)


# ---------------------------------------------------------------------------
# Pool builder (mismo path que train_pac_states.build_pool)
# ---------------------------------------------------------------------------
def build_pool_from_silver(
    silver_paths: list[Path],
    scales: list[str],
    verbose: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    Itera silver/*.parquet + events/{NR}_edos.parquet y arma el pool por escala.
    Copia intencional de train_pac_states.build_pool (evitamos acoplar scripts).
    """
    buckets: dict[str, list[pd.DataFrame]] = defaultdict(list)
    n_skipped = 0
    for i, sp in enumerate(silver_paths, start=1):
        nr = sp.stem
        ep = EVENTS_DIR / f"{nr}_edos.parquet"
        try:
            silver_df = pd.read_parquet(sp)
            edos_df = (
                pd.read_parquet(ep) if ep.exists()
                else pd.DataFrame(columns=["ts_start", "morphotype", "ird_event"])
            )
        except Exception as e:
            n_skipped += 1
            if verbose:
                print(f"  [SKIP {i}/{len(silver_paths)}] {nr}: {e}")
            continue

        for scale in scales:
            w = wn.build_windows_for_night(silver_df, edos_df, scale)
            if len(w) == 0:
                continue
            w = w.copy()
            w.insert(0, "night_record_id", nr)
            buckets[scale].append(w)

        if verbose and (i % 50 == 0 or i == len(silver_paths)):
            print(f"  [{i:4d}/{len(silver_paths)}] {nr}")

    pool: dict[str, pd.DataFrame] = {}
    for scale in scales:
        pool[scale] = (
            pd.concat(buckets[scale], ignore_index=True) if buckets[scale]
            else pd.DataFrame()
        )
    if n_skipped:
        print(f"[dash] {n_skipped} noches skippeadas por error de lectura.")
    return pool


# ---------------------------------------------------------------------------
# Plot: sweep overview (3 escalas × 3 métricas)
# ---------------------------------------------------------------------------
def plot_sweep_panel(
    sweep_by_scale: dict,
    candidates: dict[str, tuple[int, ...]],
    scales: list[str],
) -> str:
    metrics = [
        ("inertia", "Inertia (↓ mejor · baja siempre)"),
        ("silhouette", "Silhouette (↑ mejor)"),
        ("davies_bouldin", "Davies-Bouldin (↓ mejor)"),
    ]
    n_rows = len(scales)
    fig, axes = plt.subplots(n_rows, 3, figsize=(16, 3.2 * n_rows))
    if n_rows == 1:
        axes = np.array([axes])

    for row, scale in enumerate(scales):
        scale_sweep = sweep_by_scale.get(scale, {})
        sweep = pd.DataFrame(scale_sweep.get("k_sweep", []))
        if sweep.empty:
            for col in range(3):
                axes[row, col].set_title(f"escala {scale}: sin sweep", fontsize=10)
            continue

        for col, (metric, title) in enumerate(metrics):
            ax = axes[row, col]
            ax.plot(sweep["k"], sweep[metric], "o-", color="#264653", linewidth=2)
            # anchor histórico
            anchor = PAC_STATES_HISTORICAL_K[scale]
            ax.axvline(
                anchor, color="#E63946", linestyle="--", alpha=0.7,
                label=f"anchor={anchor}",
            )
            # candidatos
            for kc in candidates.get(scale, ()):
                ax.axvline(kc, color="#2A9D8F", linestyle=":", alpha=0.55)
            ax.set_xlabel("K")
            if col == 0:
                ax.set_ylabel(f"escala {SCALE_LABEL[scale]}\n{metric}")
            else:
                ax.set_ylabel(metric)
            if row == 0:
                ax.set_title(title, fontsize=10)
            ax.legend(fontsize=8, loc="best")

    fig.suptitle(
        "Sweep K=2..10 · anchor (rojo) + candidatos (verde)",
        fontsize=12, y=1.005,
    )
    fig.tight_layout()
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: heatmap centroides z-score
# ---------------------------------------------------------------------------
def plot_centroid_heatmap(
    Xz: np.ndarray, labels: np.ndarray, scale: str,
) -> str:
    uniq = np.unique(labels)
    k = len(uniq)
    cen_z = np.zeros((k, Xz.shape[1]))
    for i, u in enumerate(uniq):
        cen_z[i] = Xz[labels == u].mean(axis=0)
    cluster_names = [f"{PAC_STATE_PREFIXES[scale]}{u}" for u in uniq]
    df = pd.DataFrame(
        cen_z, index=cluster_names, columns=list(PAC_WINDOW_FEATURES),
    )
    fig, ax = plt.subplots(figsize=(16, 0.55 * k + 2.2))
    sns.heatmap(
        df, ax=ax, cmap="RdBu_r", center=0, vmin=-2, vmax=2,
        cbar_kws={"label": "z-score"},
        annot=False, linewidths=0.3, linecolor="#fff",
    )
    ax.set_xticklabels(ax.get_xticklabels(), rotation=55, ha="right", fontsize=8)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=9)
    ax.set_title(
        f"Centroides en z-score ({k} clusters × 24 features)",
        fontsize=10,
    )
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: morphotypes por cluster (densidad promedio)
# ---------------------------------------------------------------------------
def plot_morphotype_by_cluster(
    train_df: pd.DataFrame, labels: np.ndarray, scale: str,
) -> str:
    df = train_df.copy().reset_index(drop=True)
    df["cluster"] = labels
    morph_cols = ["n_alpha", "n_beta", "n_gamma", "n_delta"]
    means = df.groupby("cluster")[morph_cols].mean()
    uniq = sorted(means.index.tolist())
    means = means.loc[uniq]
    cluster_names = [f"{PAC_STATE_PREFIXES[scale]}{u}" for u in uniq]
    k = len(uniq)

    fig, ax = plt.subplots(figsize=(max(6, 0.9 * k + 3.2), 4))
    x = np.arange(k)
    bottoms = np.zeros(k)
    for col, letter in zip(morph_cols, ["α", "β", "γ", "δ"]):
        vals = means[col].values
        ax.bar(
            x, vals, bottom=bottoms,
            color=MORPH_PALETTE[letter], label=letter,
        )
        bottoms += vals
    ax.set_xticks(x)
    ax.set_xticklabels(cluster_names)
    ax.set_ylabel("n EDOs promedio por ventana")
    ax.set_xlabel("cluster")
    ax.set_title(
        "Densidad de morphotypes por cluster (mean n_α/β/γ/δ)",
        fontsize=10,
    )
    ax.legend(title="morphotype", loc="upper right", fontsize=9)
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: sleep_stage por cluster (fracciones promedio)
# ---------------------------------------------------------------------------
def plot_sleep_by_cluster(
    train_df: pd.DataFrame, labels: np.ndarray, scale: str,
) -> str:
    df = train_df.copy().reset_index(drop=True)
    df["cluster"] = labels
    sleep_cols = list(PAC_SLEEP_COMPOSITION_FEATURES)
    means = df.groupby("cluster")[sleep_cols].mean()
    uniq = sorted(means.index.tolist())
    means = means.loc[uniq]
    cluster_names = [f"{PAC_STATE_PREFIXES[scale]}{u}" for u in uniq]
    k = len(uniq)

    fig, ax = plt.subplots(figsize=(max(6, 0.9 * k + 3.2), 4))
    x = np.arange(k)
    bottoms = np.zeros(k)
    for col in sleep_cols:
        vals = means[col].values
        label = col.replace("frac_", "")
        ax.bar(
            x, vals, bottom=bottoms,
            color=SLEEP_PALETTE[col], label=label,
        )
        bottoms += vals
    ax.set_xticks(x)
    ax.set_xticklabels(cluster_names)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("fracción promedio (suma ≈ 1)")
    ax.set_xlabel("cluster")
    ax.set_title(
        "Composición de sleep_stage por cluster (mean fractions)",
        fontsize=10,
    )
    ax.legend(title="stage", loc="upper right", fontsize=9)
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Sección por candidato (scale, k)
# ---------------------------------------------------------------------------
def build_candidate_section(
    scale: str,
    k: int,
    Xz: np.ndarray,
    labels: np.ndarray,
    train_df: pd.DataFrame,
    zparams: st.ZScoreParams,
    sweep_record: dict | None,
) -> str:
    uniq = np.unique(labels)
    counts = np.array([(labels == u).sum() for u in uniq])
    cluster_names = [f"{PAC_STATE_PREFIXES[scale]}{u}" for u in uniq]
    sizes = pd.DataFrame({
        "n_training": counts,
        "pct": (counts / counts.sum() * 100).round(2),
    }, index=cluster_names)
    sizes_html = _df_to_html_table(sizes, float_fmt="{:,.2f}")

    svg_heat = plot_centroid_heatmap(Xz, labels, scale)
    svg_morph = plot_morphotype_by_cluster(train_df, labels, scale)
    svg_sleep = plot_sleep_by_cluster(train_df, labels, scale)

    # Centroides en espacio original (traspuestos para que las features queden
    # en filas y los clusters en columnas — más legible en HTML).
    cen_z = np.vstack([Xz[labels == u].mean(axis=0) for u in uniq])
    cen_orig = cen_z * zparams.std + zparams.mean
    cen_df = pd.DataFrame(
        cen_orig, index=cluster_names, columns=list(PAC_WINDOW_FEATURES),
    ).T
    cen_html = _df_to_html_table(cen_df, float_fmt="{:.2f}")

    # Métricas del sweep o warning si vienen de cómputo on-the-fly
    if sweep_record is not None:
        sil = sweep_record.get("silhouette")
        db = sweep_record.get("davies_bouldin")
        inertia = sweep_record.get("inertia")
        sil_str = f"{sil:.4f}" if sil is not None else "—"
        db_str = f"{db:.4f}" if db is not None else "—"
        inertia_str = f"{inertia:,.1f}" if inertia is not None else "—"
    else:
        sil_str = db_str = inertia_str = "—"

    anchor_tag = (
        ' <em>(anchor histórico)</em>'
        if PAC_STATES_HISTORICAL_K[scale] == k else ''
    )

    return f"""
<h3 id="scale-{scale}-k{k}">Escala {SCALE_LABEL[scale]} — K = {k}{anchor_tag}</h3>
<p class="meta">silhouette = <strong>{sil_str}</strong> ·
   Davies-Bouldin = <strong>{db_str}</strong> ·
   inertia = {inertia_str} · training N = {len(labels):,}</p>

<h4>Tamaños de clusters</h4>
{sizes_html}

<h4>Centroides (cluster × feature, z-score)</h4>
{svg_heat}

<h4>Densidad de morphotypes por cluster</h4>
{svg_morph}

<h4>Composición de sleep_stage por cluster</h4>
{svg_sleep}

<details>
<summary>Centroides en espacio original (feature × cluster)</summary>
{cen_html}
</details>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Dashboard HTML de PAC states.")
    p.add_argument(
        "--limit", type=int, default=None,
        help="Smoke test: procesar sólo las primeras N noches.",
    )
    p.add_argument(
        "--candidates", type=str, default=None,
        help='Override candidatos. Formato: "s:6,7,8;m:5,6,8;l:4,6".',
    )
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def _parse_candidates(raw: str | None) -> dict[str, tuple[int, ...]]:
    if not raw:
        return {s: tuple(DEFAULT_CANDIDATES[s]) for s in PAC_STATE_SCALES}
    out: dict[str, tuple[int, ...]] = {}
    for part in raw.split(";"):
        if not part.strip():
            continue
        scale, ks = part.split(":")
        scale = scale.strip()
        if scale not in PAC_STATE_SCALES:
            raise ValueError(f"Escala desconocida en --candidates: {scale!r}")
        out[scale] = tuple(int(k) for k in ks.split(",") if k.strip())
    return out


def main() -> None:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    candidates = _parse_candidates(args.candidates)
    scales = list(candidates.keys())
    print(f"[dash] candidatos: {candidates}")

    # 1. Listar silver.
    silver_paths = sorted(
        p for p in SILVER_DIR.glob("NR_*.parquet")
        if not p.stem.endswith("_qc")
    )
    if args.limit:
        silver_paths = silver_paths[: args.limit]
    print(f"[dash] procesando {len(silver_paths)} noches …")

    # 2. Build pool.
    t0 = time.time()
    pool = build_pool_from_silver(silver_paths, scales, verbose=args.verbose)
    elapsed_pool = time.time() - t0
    for scale in scales:
        print(f"[dash] pool[{scale}] = {len(pool[scale])}")
    print(f"[dash] pool built en {elapsed_pool:.1f}s")

    # 3. Cargar sweep report (si existe).
    sweep_by_scale: dict = {}
    if SWEEP_REPORT_JSON.exists():
        with open(SWEEP_REPORT_JSON, encoding="utf-8") as f:
            sweep_data = json.load(f)
        sweep_by_scale = sweep_data.get("by_scale", {})
        print(f"[dash] sweep cargado desde {SWEEP_REPORT_JSON.name}")
    else:
        print("[dash] WARN: no se encontró sweep report; corré train_pac_states.py --mode sweep.")

    # 4. Entrenar candidatos por escala.
    sections_by_scale: dict[str, list[str]] = {s: [] for s in scales}
    t0 = time.time()
    for scale in scales:
        pool_scale = pool[scale]
        if len(pool_scale) == 0:
            sections_by_scale[scale].append(
                f"<p><em>Pool vacío para escala {scale}.</em></p>"
            )
            continue

        mask = st.build_training_mask(pool_scale)
        train_df = pool_scale.loc[mask].copy()
        train_df = st.sort_pool_for_training(train_df)
        X, kept_idx = st.build_feature_matrix(
            train_df, list(PAC_WINDOW_FEATURES),
        )
        train_df_kept = train_df.loc[kept_idx].reset_index(drop=True)
        zparams = st.fit_zscore(X, list(PAC_WINDOW_FEATURES))
        Xz = st.apply_zscore(X, zparams)
        print(f"[dash] escala {scale}: N={X.shape[0]} ventanas de training")

        for k in candidates[scale]:
            print(f"  [{scale}] fit K={k} …")
            model = st.fit_kmeans(Xz, k=k, random_state=PAC_STATES_RANDOM_STATE)
            labels = model.predict(Xz)

            sweep_record = None
            scale_rec = sweep_by_scale.get(scale, {})
            for r in scale_rec.get("k_sweep", []):
                if r.get("k") == k:
                    sweep_record = r
                    break

            section = build_candidate_section(
                scale, k, Xz, labels, train_df_kept, zparams, sweep_record,
            )
            sections_by_scale[scale].append(section)
    elapsed_train = time.time() - t0

    # 5. Plot sweep overview.
    svg_sweep = (
        plot_sweep_panel(sweep_by_scale, candidates, scales)
        if sweep_by_scale else "<p><em>Sin sweep previo — corré el trainer en modo sweep primero.</em></p>"
    )

    # 6. Armar HTML.
    candidates_str = "; ".join(
        f"{s}:{','.join(map(str, ks))}" for s, ks in candidates.items()
    )
    toc_items = []
    scale_section_blocks = []
    section_idx = 2
    for scale in scales:
        ks_str = ",".join(str(k) for k in candidates[scale])
        toc_items.append(
            f'<li><a href="#scale-{scale}">{section_idx} · Escala {SCALE_LABEL[scale]} — K∈{{{ks_str}}}</a></li>'
        )
        scale_section_blocks.append(
            f'<h2 id="scale-{scale}">{section_idx} · Escala {SCALE_LABEL[scale]} — candidatos K∈{{{ks_str}}}</h2>\n'
            + "".join(sections_by_scale[scale])
        )
        section_idx += 1

    toc_html = "\n".join(toc_items)
    scale_sections_html = "\n".join(scale_section_blocks)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>PAC_v2 — Etapa 4 · Dashboard de estados PAC</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1400px; margin: 2em auto; color: #1d3557; padding: 0 1em; }}
  h1 {{ border-bottom: 3px solid #E63946; padding-bottom: 0.2em; }}
  h2 {{ color: #E63946; margin-top: 2.4em; border-top: 1px solid #eee; padding-top: 1em; }}
  h3 {{ color: #457B9D; margin-top: 1.8em; }}
  h4 {{ color: #2A9D8F; margin-top: 1em; font-size: 1.0em; }}
  .meta {{ color: #555; font-size: 0.9em; }}
  table.data {{ border-collapse: collapse; margin: 1em 0; font-size: 0.85em; }}
  table.data th, table.data td {{ padding: 5px 10px; border-bottom: 1px solid #ddd; text-align: right; }}
  table.data th {{ background: #f0f0f0; text-align: center; }}
  details {{ margin: 1em 0; background: #fafafa; border: 1px solid #eee; padding: 0.6em 1em; border-radius: 4px; }}
  details summary {{ cursor: pointer; color: #264653; font-weight: bold; }}
  svg {{ max-width: 100%; height: auto; display: block; }}
  .legend {{ background: #f8f9fa; border-left: 4px solid #457B9D; padding: 0.8em 1em; margin: 1em 0; font-size: 0.9em; }}
  .footer {{ color: #888; font-size: 0.85em; border-top: 1px solid #ddd; margin-top: 3em; padding-top: 1em; }}
  nav.toc {{ background: #f8f9fa; padding: 1em 1.4em; border-radius: 4px; margin: 1em 0; }}
  nav.toc ul {{ margin: 0.2em 0 0 1em; padding: 0; }}
</style>
</head>
<body>

<h1>PAC_v2 — Etapa 4 · Dashboard de estados PAC</h1>
<p class="meta">Generado {datetime.now().isoformat(timespec="seconds")} ·
  n_nights = {len(silver_paths)} ·
  candidatos = <code>{candidates_str}</code> ·
  mask = <code>frac_wake ≤ 0.5 AND coverage ≥ 0.5</code> ·
  random_state = {PAC_STATES_RANDOM_STATE} ·
  pool build = {elapsed_pool:.1f}s ·
  fits = {elapsed_train:.1f}s</p>

<div class="legend">
  <strong>Cómo usar este dashboard:</strong> en la sección 1 mirás las curvas de sweep
  (inertia / silhouette / DB) por escala para identificar codos. En las secciones
  siguientes, cada candidato K muestra <em>centroides z-score</em> (qué features
  definen cada cluster), <em>morphotype × cluster</em> (qué tipo de EDO domina cada
  estado) y <em>sleep × cluster</em> (qué fracción de wake/light/deep hay por estado).
  La decisión de K se hace mirando <strong>codos + interpretabilidad</strong>, no sólo métricas.
</div>

<nav class="toc">
  <strong>Índice:</strong>
  <ul>
    <li><a href="#sweep">1 · Sweep overview (inertia / silhouette / Davies-Bouldin)</a></li>
{toc_html}
  </ul>
</nav>

<h2 id="sweep">1 · Sweep overview (K=2..10)</h2>
<p>Líneas rojas = anchor histórico del PAC viejo (s=7, m=6, l=4).
   Líneas verdes = K candidatos evaluados abajo.</p>
{svg_sweep}

{scale_sections_html}

<div class="footer">
  <p>Reporte fuente del sweep: <code>reports/pac_states_sweep.json</code>.
     Cuando decidas K definitivos, correr
     <code>PYTHONPATH=src python scripts/train_pac_states.py --mode final --k-s N --k-m N --k-l N</code>
     para persistir los 12 artefactos (4 × 3 escalas) en <code>models/</code>
     y emitir <code>reports/pac_states_training_report.json</code>.</p>
</div>

</body>
</html>
"""

    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n[dash] escrito: {DASHBOARD_HTML}")
    print(f"[dash] DONE en {elapsed_pool + elapsed_train:.1f}s")


if __name__ == "__main__":
    main()
