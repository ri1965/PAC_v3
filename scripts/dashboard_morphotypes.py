"""
PAC_v2 — Etapa 3b paso 4b: dashboard HTML de morphotypes.

Genera reports/morphotypes_dashboard_k{K}.html con:

  1. Sweep K + tabla de criterios.
  2. Centroides en espacio original (tabla).
  3. Boxplots de las 10 features por morfotipo (fila × feature, col = cluster).
  4. Composición de meets_Npct por morfotipo (stacked bar).
  5. Proyección 2D con PCA, EDOs coloreados por morfotipo.
  6. Curvas morfológicas promedio por morfotipo (de {NR}_edo_curves.parquet,
     muestra de hasta 500 EDOs por cluster).

Todas las imágenes embebidas como SVG inline → HTML standalone, sin CDN.

Por default usa el modelo persistido en models/. Con --k re-fita on-the-fly
(sin tocar el modelo persistido) para comparar K alternativos.

Corre:  PYTHONPATH=src python scripts/dashboard_morphotypes.py
        PYTHONPATH=src python scripts/dashboard_morphotypes.py --k 4
"""
from __future__ import annotations

import argparse
import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import seaborn as sns
from sklearn.decomposition import PCA

from pac import morphotypes as mt
from pac.config import (
    EVENTS_DIR,
    MODELS_DIR,
    MORPHOTYPE_FEATURES,
    MORPHOTYPE_TRAINING_MASK,
    REPORTS_DIR,
)


sns.set_style("whitegrid")


def _dashboard_path(k: int) -> Path:
    return REPORTS_DIR / f"morphotypes_dashboard_k{k}.html"

# Paleta distintiva por morphotype.
PALETTE = {
    "α": "#E63946",  # rojo — severos
    "β": "#457B9D",  # azul — leves
    "γ": "#F4A261",  # naranja — respuesta motora
    "δ": "#2A9D8F",
    "ε": "#8E44AD",
}


# ---------------------------------------------------------------------------
# Helpers de renderizado
# ---------------------------------------------------------------------------
def _fig_to_svg(fig) -> str:
    """Convierte fig mpl a SVG inline (string)."""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _df_to_html_table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    """Formatea un DataFrame como tabla HTML."""
    return df.applymap(
        lambda v: float_fmt.format(v) if isinstance(v, (int, float)) and not pd.isna(v)
        else ("" if pd.isna(v) else str(v))
    ).to_html(classes="data", border=0, escape=False)


# ---------------------------------------------------------------------------
# Plot: sweep K
# ---------------------------------------------------------------------------
def plot_sweep(sweep: pd.DataFrame, k_chosen: int) -> str:
    fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
    for ax, col, title in zip(
        axes,
        ["inertia", "silhouette", "davies_bouldin"],
        ["Inertia (menor = mejor fit, pero baja siempre)",
         "Silhouette (mayor = mejor separación)",
         "Davies-Bouldin (menor = mejor)"],
    ):
        ax.plot(sweep["k"], sweep[col], "o-", color="#264653", linewidth=2)
        ax.axvline(k_chosen, color="#E63946", linestyle="--", alpha=0.7,
                   label=f"K elegido = {k_chosen}")
        ax.set_xlabel("K")
        ax.set_ylabel(col)
        ax.set_title(title, fontsize=10)
        ax.legend(fontsize=9)
    fig.suptitle("Sweep K=2..10 — selección de K", fontsize=12, y=1.02)
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: boxplots por feature
# ---------------------------------------------------------------------------
def plot_feature_boxplots(labeled: pd.DataFrame) -> str:
    feats = list(MORPHOTYPE_FEATURES)
    n_cols = 5
    n_rows = 2
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(18, 7))
    order = sorted(labeled["morphotype"].unique())
    palette = [PALETTE.get(m, "#777") for m in order]
    for ax, feat in zip(axes.ravel(), feats):
        sns.boxplot(
            data=labeled, x="morphotype", y=feat, order=order,
            palette=palette, ax=ax, showfliers=False,
        )
        ax.set_title(feat, fontsize=10)
        ax.set_xlabel("")
        ax.set_ylabel("")
    fig.suptitle(
        "Distribución de cada feature por morfotipo (training universe, 42.819 EDOs canónicos) · outliers ocultos",
        fontsize=11, y=1.02,
    )
    fig.tight_layout()
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: composición de meets_Npct
# ---------------------------------------------------------------------------
def plot_meets_composition(labeled: pd.DataFrame) -> str:
    meets_cols = [c for c in ("meets_2pct", "meets_3pct", "meets_4pct", "meets_5pct")
                  if c in labeled.columns]
    comp = labeled.groupby("morphotype")[meets_cols].mean() * 100
    fig, ax = plt.subplots(figsize=(9, 4))
    order = sorted(comp.index.tolist())
    x = np.arange(len(order))
    width = 0.2
    colors = ["#264653", "#2A9D8F", "#E9C46A", "#E76F51"]
    for i, col in enumerate(meets_cols):
        vals = [comp.loc[m, col] for m in order]
        ax.bar(x + i * width, vals, width, label=col, color=colors[i])
    ax.set_xticks(x + width * (len(meets_cols) - 1) / 2)
    ax.set_xticklabels(order)
    ax.set_ylabel("% de EDOs que cumplen el criterio")
    ax.set_title("Composición de meets_Npct por morfotipo",
                 fontsize=11)
    ax.legend(ncol=4, fontsize=9, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Plot: PCA 2D
# ---------------------------------------------------------------------------
def plot_pca(Xz: np.ndarray, labels: np.ndarray, *, n_sample: int = 8000) -> tuple[str, dict]:
    pca = PCA(n_components=2, random_state=42)
    # Subsample para no sobrecargar el SVG.
    rng = np.random.default_rng(42)
    if len(Xz) > n_sample:
        idx = rng.choice(len(Xz), n_sample, replace=False)
    else:
        idx = np.arange(len(Xz))
    X2 = pca.fit_transform(Xz)
    X2s = X2[idx]
    labs = labels[idx]

    fig, ax = plt.subplots(figsize=(8, 6))
    for m in sorted(np.unique(labs)):
        sel = labs == m
        ax.scatter(
            X2s[sel, 0], X2s[sel, 1],
            s=4, alpha=0.35, color=PALETTE.get(m, "#777"),
            label=f"{m}  (n={sel.sum()})",
        )
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.1f}% var)")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.1f}% var)")
    ax.set_title("PCA 2D — EDOs de training coloreados por morfotipo")
    ax.legend(loc="best", fontsize=10, framealpha=0.9)
    return _fig_to_svg(fig), {
        "var_pc1": float(pca.explained_variance_ratio_[0]),
        "var_pc2": float(pca.explained_variance_ratio_[1]),
        "n_scatter": int(len(idx)),
    }


# ---------------------------------------------------------------------------
# Plot: curvas morfológicas promedio por cluster
# ---------------------------------------------------------------------------
def plot_mean_curves(
    labeled_train: pd.DataFrame,
    events_dir: Path = EVENTS_DIR,
    n_per_cluster: int = 500,
) -> str:
    """
    Para cada cluster: muestrea hasta `n_per_cluster` EDOs, carga sus curvas
    desde {NR}_edo_curves.parquet y grafica mean ± IQR.

    Join por (night_record_id, ts_start).
    """
    # Subsample por cluster.
    rng = np.random.default_rng(42)
    picks = []
    for m in sorted(labeled_train["morphotype"].unique()):
        sub = labeled_train[labeled_train["morphotype"] == m]
        if len(sub) > n_per_cluster:
            sub = sub.sample(n=n_per_cluster, random_state=42)
        picks.append(sub[["night_record_id", "ts_start", "morphotype"]])
    sampled = pd.concat(picks, ignore_index=True)

    # Cargar curves para las noches presentes.
    nights = sampled["night_record_id"].unique().tolist()
    frames = []
    for nr in nights:
        p = events_dir / f"{nr}_edo_curves.parquet"
        if p.exists():
            frames.append(pq.read_table(p).to_pandas())
    if not frames:
        return "<p><em>No se encontraron curvas para graficar.</em></p>"
    curves = pd.concat(frames, ignore_index=True)

    # El parquet de curvas guarda 1 fila × (ts_start, point_idx, value_pct).
    # Join con sampled por (night_record_id, ts_start).
    if "point_idx" not in curves.columns or "value_pct" not in curves.columns:
        # Fallback: identificar columnas
        return f"<p><em>Schema inesperado en edo_curves: {list(curves.columns)}</em></p>"

    merged = curves.merge(
        sampled, on=["night_record_id", "ts_start"], how="inner"
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    order = sorted(merged["morphotype"].unique())
    for m in order:
        sub = merged[merged["morphotype"] == m]
        pivot = sub.pivot_table(
            index=["night_record_id", "ts_start"],
            columns="point_idx",
            values="value_pct",
        )
        mean = pivot.mean(axis=0)
        p25 = pivot.quantile(0.25, axis=0)
        p75 = pivot.quantile(0.75, axis=0)
        ax.plot(mean.index, mean.values, color=PALETTE.get(m, "#777"),
                linewidth=2.2, label=f"{m}  (n={pivot.shape[0]})")
        ax.fill_between(mean.index, p25.values, p75.values,
                        color=PALETTE.get(m, "#777"), alpha=0.18)
    ax.set_xlabel("Punto resampleado (0 = inicio, 30 = fin del EDO)")
    ax.set_ylabel("SpO₂ como % del baseline (≈100 = sin drop)")
    ax.set_title(
        "Curvas morfológicas promedio por morfotipo (mean ± IQR, hasta 500 EDOs/cluster)",
        fontsize=11,
    )
    ax.legend(loc="lower right", fontsize=10)
    ax.axhline(100, color="#888", linestyle=":", alpha=0.6)
    return _fig_to_svg(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Dashboard HTML de morphotypes.")
    parser.add_argument(
        "--k", type=int, default=None,
        help="Si se pasa, re-fita KMeans con este K on-the-fly (NO pisa el "
             "modelo persistido en models/). Si se omite, usa el modelo persistido.",
    )
    args = parser.parse_args()

    print("[dashboard] cargando modelo persistido y pool …")
    persisted_model, zparams, meta = mt.load_model(MODELS_DIR)

    pool = mt.load_edo_pool(EVENTS_DIR)
    mask = mt.build_training_mask(pool, MORPHOTYPE_TRAINING_MASK)
    train_df = pool.loc[mask].reset_index(drop=True)
    X, kept_idx = mt.build_feature_matrix(train_df, list(zparams.feature_cols))
    Xz = mt.apply_zscore(X, zparams)

    if args.k is not None and args.k != persisted_model.n_clusters:
        print(f"[dashboard] --k={args.k} → re-fit on-the-fly (sin tocar models/)")
        model = mt.fit_kmeans(Xz, k=int(args.k))
        on_the_fly = True
    else:
        model = persisted_model
        on_the_fly = False
    k = model.n_clusters
    print(f"            K = {k} · features = {len(zparams.feature_cols)}")
    labels_int = model.predict(Xz)
    labels_greek = mt.int_to_greek(labels_int)

    labeled_train = train_df.iloc[kept_idx].reset_index(drop=True).copy()
    labeled_train["morphotype"] = labels_greek

    centroids = mt.centroids_original_space(model, zparams)
    cluster_sizes = labeled_train.groupby("morphotype").size().rename("n_training")
    size_pct = (cluster_sizes / cluster_sizes.sum() * 100).round(2).rename("pct")

    sweep_records = meta.get("k_sweep") or []
    sweep = pd.DataFrame(sweep_records)
    # silhouette/DB del K actual (puede no estar en el sweep si es re-fit on-the-fly).
    if not sweep.empty and k in sweep["k"].values:
        sil_here = sweep.loc[sweep["k"] == k, "silhouette"].iloc[0]
        db_here = sweep.loc[sweep["k"] == k, "davies_bouldin"].iloc[0]
    else:
        from sklearn.metrics import silhouette_score, davies_bouldin_score
        rng = np.random.default_rng(42)
        sample = rng.choice(len(Xz), size=min(5000, len(Xz)), replace=False)
        sil_here = float(silhouette_score(Xz[sample], labels_int[sample]))
        db_here = float(davies_bouldin_score(Xz, labels_int))

    # Leyenda dinámica de lectura de centroides (ordenada por drop_pct desc).
    drop_ranked = centroids.sort_values("drop_pct", ascending=False)
    legend_lines = []
    for i, (letter, row) in enumerate(drop_ranked.iterrows()):
        color = PALETTE.get(letter, "#555")
        legend_lines.append(
            f'<li><strong style="color:{color}">{letter}</strong> — '
            f'drop {row["drop_pct"]:.1f}% · nadir {row["nadir_spo2"]:.1f}% · '
            f'AUC {row["auc_spo2_pct_s"]:.0f} · IRD {row["ird_event"]:.1f} · '
            f'mov_comp {row["ird_mov_comp"]:.1f}</li>'
        )
    legend_html = (
        '<ul style="margin:0.4em 0 0 1.2em; padding:0">'
        + "".join(legend_lines)
        + "</ul>"
    )

    # Plots
    print("[dashboard] generando plots …")
    svg_sweep = plot_sweep(sweep, k_chosen=k) if not sweep.empty else ""
    svg_box = plot_feature_boxplots(labeled_train)
    svg_meets = plot_meets_composition(labeled_train)
    svg_pca, pca_info = plot_pca(Xz, labels_greek)
    svg_curves = plot_mean_curves(labeled_train, EVENTS_DIR)

    # Tablas
    centroids_tbl = _df_to_html_table(centroids, float_fmt="{:.2f}")
    sizes_tbl = _df_to_html_table(
        pd.concat([cluster_sizes, size_pct], axis=1).sort_index(),
        float_fmt="{:,.0f}",
    )
    sweep_tbl = _df_to_html_table(sweep.set_index("k") if not sweep.empty else sweep,
                                   float_fmt="{:.4f}")

    # HTML final
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>PAC_v2 — Etapa 3b · Morphotypes Dashboard (K=3)</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1280px; margin: 2em auto; color: #1d3557; padding: 0 1em; }}
  h1 {{ border-bottom: 3px solid #E63946; padding-bottom: 0.2em; }}
  h2 {{ color: #E63946; margin-top: 2em; }}
  h3 {{ color: #457B9D; }}
  .meta {{ color: #555; font-size: 0.9em; }}
  table.data {{ border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }}
  table.data th, table.data td {{ padding: 6px 12px; border-bottom: 1px solid #ddd; text-align: right; }}
  table.data th {{ background: #f0f0f0; text-align: center; }}
  .legend {{ background: #f8f9fa; border-left: 4px solid #457B9D; padding: 1em 1.2em; margin: 1em 0; }}
  .legend strong {{ color: #E63946; }}
  svg {{ max-width: 100%; height: auto; }}
  .footer {{ color: #888; font-size: 0.85em; border-top: 1px solid #ddd; margin-top: 3em; padding-top: 1em; }}
</style>
</head>
<body>

<h1>PAC_v2 — Etapa 3b · Morphotype dashboard (K={k}){' · <em>comparativo (no persistido)</em>' if on_the_fly else ''}</h1>
<p class="meta">Generado {datetime.now().isoformat(timespec="seconds")} ·
  algorithm <code>{meta.get("algorithm_version")}</code> ·
  random_state {meta.get("random_state")} ·
  training_mask <code>{meta.get("training_mask")}</code> ·
  silhouette <code>{sil_here:.4f}</code> · DB <code>{db_here:.4f}</code></p>

<div class="legend">
  <strong>Training universe:</strong> {cluster_sizes.sum():,} EDOs "canónicos"
  (in_sleep=True, near_gap=False, meets_3pct=True), extraídos del pool total de
  {len(pool):,} EDOs en 560 noches. Los EDOs marginales (meets_2pct only) quedan
  fuera del training pero reciben label en el paso de batch labeling (Etapa 3b paso 5).
</div>

<h2>1 · Sweep K=2..10</h2>
<p>Criterio triple: inertia (elbow), silhouette (mayor = mejor separación),
   Davies-Bouldin (menor = mejor). Silhouette pico en K=2 (separación binaria),
   plateau en K=3..6 (~0.30). Elegimos <strong>K=3</strong> como primer punto del
   plateau — rompe la dicotomía y mantiene parsimonia.</p>
{svg_sweep}
{sweep_tbl}

<h2>2 · Centroides en espacio original</h2>
<p>Cada fila es el valor promedio de la feature en el centro del cluster
   (de-normalizado desde z-space). Las 6 primeras son morfológicas, las 4 últimas son IRD multi-signal.</p>
{centroids_tbl}

<h3>Tamaño de los clusters (training)</h3>
{sizes_tbl}

<div class="legend">
  <strong>Lectura rápida de los centroides (ordenados por drop % descendente):</strong>
  {legend_html}
</div>

<h2>3 · Distribución de features por morfotipo</h2>
<p>Boxplots (outliers ocultos para legibilidad). Confirma que los centroides son
   representativos de la masa de cada cluster, no promedios engañosos.</p>
{svg_box}

<h2>4 · Composición de umbrales clínicos meets_Npct por morfotipo</h2>
<p>¿Qué fracción de los EDOs de cada cluster supera cada umbral clínico (2/3/4/5%)?
   Permite anclar los morfotipos al vocabulario clínico tradicional.</p>
{svg_meets}

<h2>5 · Proyección PCA 2D</h2>
<p>Proyección lineal de los EDOs canónicos en los 2 primeros componentes principales.
   Explicación varianza: PC1 = {pca_info['var_pc1']*100:.1f}%, PC2 = {pca_info['var_pc2']*100:.1f}%.
   Scatter de {pca_info['n_scatter']:,} puntos coloreados por morfotipo.</p>
{svg_pca}

<h2>6 · Curvas morfológicas promedio por morfotipo</h2>
<p>SpO₂ normalizada al baseline, resampleada a 30 puntos (0 = inicio del drop,
   30 = fin del evento). Línea = mean, franja = IQR (p25-p75). Hasta 500 EDOs
   por cluster para mantener el SVG liviano.</p>
{svg_curves}

<div class="footer">
  <p>Archivos del modelo persistidos en <code>models/</code>:
     <code>edo_morphotype_kmeans.pkl</code>, <code>edo_morphotype_zscore.json</code>,
     <code>edo_morphotype_centroids.csv</code>, <code>edo_morphotype_metadata.json</code>.
     Reports asociados: <code>morphotypes_training_report.json</code>,
     <code>morphotypes_interpretability.md</code>.</p>
</div>

</body>
</html>
"""

    out_path = _dashboard_path(k)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[dashboard] escrito: {out_path}")


if __name__ == "__main__":
    main()
