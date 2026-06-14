"""
PAC_v2 — Etapa 4 paso 8.5: dashboard de stratigraphy por noche.

Genera 5 HTMLs interactivos (Plotly) que superponen, en un mismo eje
temporal, los componentes de UNA noche:

  Row 1  SpO2 line                           — silver.spo2_clean
  Row 2  HR line                             — silver.hr_clean
  Row 3  Hipnograma                          — silver.sleep_stage
  Row 4  EDO markers + ±2 min ctx shading    — events/<NR>_edos.parquet
  Row 5  States stripe escala l (30 min)     — states/<NR>.parquet (scale=l)
  Row 6  States stripe escala m (5 min)      — states/<NR>.parquet (scale=m)
  Row 7  States stripe escala s (30 s)       — states/<NR>.parquet (scale=s)
  Row 8  Morfotipo events (β/δ/...)          — events/<NR>_edos.parquet.morphotype

Selección de noches (Q4=A, Roberto):
  1. SAOS severo  — argmax(ahi_3) sobre 553 noches válidas (excl. b2_fail).
  2. Control      — argmin(ahi_3) entre noches con tst_s ≥ 5h.
  3. L3 cluster   — noche con mayor presencia del cluster outlier L3.
  4. Flag B3      — primera noche con dominio>95% en alguna escala.
  5. Flag B4      — primera noche con >20% ventanas en top-5% dist.

Decisiones cerradas (Q1..Q7=A/B/B/A/C/A/A, Roberto):
  Q1=A: HTML+Plotly (interactivo).
  Q2=B: 5 archivos separados.
  Q3=B: tracks completos (incluye hipnograma + morfotipos).
  Q4=A: 5 noches representativas (SAOS+control+L3+B3+B4).
  Q5=C: EDO span con ±2 min context shading.
  Q6=A: reports/stratigraphy/<NR>.html
  Q7=A: persistir reports/stratigraphy_nights_selected.json

Corre:
  PYTHONPATH=src python scripts/build_stratigraphy_dashboard.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pac.config import (
    EVENTS_DIR,
    PAC_STATE_PREFIXES,
    REPORTS_DIR,
    SILVER_DIR,
    STATES_DIR,
)

# Outputs
DASHBOARD_DIR = REPORTS_DIR / "stratigraphy"
SELECTION_JSON = REPORTS_DIR / "stratigraphy_nights_selected.json"

# Inputs auxiliares
EVENTS_INDICES = REPORTS_DIR / "events_indices_pooled.parquet"
B2_EXCLUDED_JSON = REPORTS_DIR / "b2_fail_excluded.json"
FLAG_REVIEW_CSV = REPORTS_DIR / "pac_states_flag_for_review.csv"

# Constantes visuales
EDO_CONTEXT_S = 120  # ±2 min de sombreado contextual antes/después del EDO
SPO2_YRANGE = (75, 100)
HR_YRANGE = (40, 110)

# Mapeo sleep_stage → label/color (Mapeo B usado en silver)
SLEEP_LABELS = {0: "wake", 1: "light", 2: "light", 3: "deep"}
SLEEP_COLORS = {0: "#fde68a", 1: "#bfdbfe", 2: "#bfdbfe", 3: "#1e40af"}

# Paletas para state stripes (consistentes por escala)
def _state_palette(prefix: str, k: int) -> dict:
    """Devuelve {label: color} para los k clusters de una escala."""
    base = {
        "S": ["#0ea5e9", "#22c55e", "#facc15", "#f97316", "#ef4444", "#a855f7"],
        "M": ["#0e7490", "#16a34a", "#ca8a04", "#ea580c", "#dc2626", "#9333ea",
              "#1e40af", "#db2777"],
        "L": ["#0c4a6e", "#15803d", "#a16207", "#9a3412", "#991b1b", "#581c87"],
    }
    palette = base.get(prefix, base["S"])
    return {f"{prefix}{i}": palette[i % len(palette)] for i in range(k)}


# ===========================================================================
# Selección de las 5 noches representativas
# ===========================================================================
def select_representative_nights(seed: int = 42) -> dict:
    """
    Devuelve {tag: NR_id} con las 5 noches y los criterios usados.
    """
    print("[strata] cargando índices y exclusiones …")
    idx = pd.read_parquet(EVENTS_INDICES)

    with open(B2_EXCLUDED_JSON, encoding="utf-8") as f:
        b2_ex = set(json.load(f)["night_record_ids"])
    print(f"        excluidas (b2 fail): {len(b2_ex)}")

    # Pool válido
    pool = idx[~idx["night_record_id"].isin(b2_ex)].copy()
    pool = pool[pool["qc_coverage_ok"] == True]  # noqa: E712 (parquet bool)

    # 1) SAOS severo: top ahi_3
    saos = pool.sort_values("ahi_3", ascending=False).iloc[0]
    nr_saos = saos["night_record_id"]

    # 2) Control: bottom ahi_3 entre noches con sueño real (≥5h tst)
    real_sleep = pool[pool["tst_s"] >= 5 * 3600]
    ctrl = real_sleep.sort_values("ahi_3").iloc[0]
    nr_ctrl = ctrl["night_record_id"]

    # 3) L3 cluster: scan states/ buscando el outlier l-cluster
    print("[strata] scaneando states/ para cluster L3 …")
    nr_l3 = None
    n_l3_max = 0
    for p in sorted(STATES_DIR.glob("NR_*.parquet")):
        nr = p.stem
        if nr in b2_ex:
            continue
        df = pd.read_parquet(p, columns=["scale", "state_label"])
        n_l3 = int(((df["scale"] == "l") & (df["state_label"] == "L3")).sum())
        if n_l3 > n_l3_max:
            n_l3_max = n_l3
            nr_l3 = nr
    print(f"        L3 max-presence: {nr_l3} ({n_l3_max} ventanas)")

    # 4) Flag B3 dominance, 5) Flag B4 outlier
    review = pd.read_csv(FLAG_REVIEW_CSV)
    review = review[~review["nr"].isin(b2_ex)]
    rng = np.random.default_rng(seed)
    b3 = review[review["flag_b3"]].sample(1, random_state=rng.integers(2**31)).iloc[0]
    b4 = review[review["flag_b4"] & ~review["flag_b3"]].sample(
        1, random_state=rng.integers(2**31)
    ).iloc[0]

    selection = {
        "saos_severo": {
            "night_record_id": nr_saos,
            "criterion": f"argmax(ahi_3)={saos['ahi_3']:.2f}, "
                         f"ird_night={saos['ird_night']:.2f}, "
                         f"n_edos_total={int(saos['n_edos_total'])}",
        },
        "control": {
            "night_record_id": nr_ctrl,
            "criterion": f"argmin(ahi_3)={ctrl['ahi_3']:.2f} dentro de tst≥5h, "
                         f"n_edos_total={int(ctrl['n_edos_total'])}",
        },
        "cluster_L3": {
            "night_record_id": nr_l3,
            "criterion": f"argmax(L3 windows)={n_l3_max}",
        },
        "flag_b3_dominance": {
            "night_record_id": b3["nr"],
            "criterion": f"flag_b3=True, max_dom_l={b3['b3_max_dom_l']:.3f}",
        },
        "flag_b4_outliers": {
            "night_record_id": b4["nr"],
            "criterion": f"flag_b4=True (no b3), out_frac_s={b4['b4_outlier_frac_s']:.3f}",
        },
    }
    return selection


# ===========================================================================
# Carga de datos por noche
# ===========================================================================
def load_night_data(nr: str) -> dict:
    """Carga silver, events EDOs y states para una noche."""
    silver = pd.read_parquet(SILVER_DIR / f"{nr}.parquet")
    edos = pd.read_parquet(EVENTS_DIR / f"{nr}_edos.parquet")
    states = pd.read_parquet(STATES_DIR / f"{nr}.parquet")

    t0 = silver["timestamp"].min()
    silver["t_min"] = (silver["timestamp"] - t0).dt.total_seconds() / 60
    edos["t_start_min"] = (edos["ts_start"] - t0).dt.total_seconds() / 60
    edos["t_end_min"] = (edos["ts_end"] - t0).dt.total_seconds() / 60
    states["t_start_min"] = states["t_start_s"] / 60
    states["t_end_min"] = states["t_end_s"] / 60

    return {"silver": silver, "edos": edos, "states": states, "t0": t0}


# ===========================================================================
# Construcción del plot (Plotly)
# ===========================================================================
def build_figure(nr: str, tag: str, criterion: str, data: dict) -> go.Figure:
    silver = data["silver"]
    edos = data["edos"]
    states = data["states"]

    # Detectar K por escala
    k_per_scale = {
        s: int(states.loc[(states["scale"] == s) &
                          (states["cluster_int"] >= 0), "cluster_int"].max() + 1)
        if (states["scale"] == s).any() else 0
        for s in ("s", "m", "l")
    }

    # Subplots: 8 filas
    fig = make_subplots(
        rows=8, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.015,
        row_heights=[0.18, 0.13, 0.07, 0.07, 0.08, 0.08, 0.13, 0.10],
        subplot_titles=(
            "SpO₂ (%) + EDOs",
            "HR (bpm)",
            "Hipnograma",
            "EDOs (markers + ±2 min ctx)",
            "States escala l (30 min)",
            "States escala m (5 min)",
            "States escala s (30 s)",
            "Morfotipos por EDO",
        ),
    )

    # ── Row 1: SpO2
    fig.add_trace(
        go.Scattergl(
            x=silver["t_min"], y=silver["spo2_clean"],
            mode="lines", line=dict(color="#0284c7", width=1),
            name="SpO₂", hovertemplate="t=%{x:.1f} min<br>SpO₂=%{y:.1f}%",
        ),
        row=1, col=1,
    )
    fig.update_yaxes(range=SPO2_YRANGE, row=1, col=1, title_text="%")

    # ── Row 2: HR
    fig.add_trace(
        go.Scattergl(
            x=silver["t_min"], y=silver["hr_clean"],
            mode="lines", line=dict(color="#dc2626", width=1),
            name="HR", hovertemplate="t=%{x:.1f} min<br>HR=%{y:.0f} bpm",
        ),
        row=2, col=1,
    )
    fig.update_yaxes(range=HR_YRANGE, row=2, col=1, title_text="bpm")

    # ── Row 3: Hipnograma (step)
    sleep_y_map = {0: 3, 1: 2, 2: 2, 3: 1}  # wake top, deep bottom (clínico)
    sleep_y = silver["sleep_stage"].map(sleep_y_map).astype(float)
    fig.add_trace(
        go.Scattergl(
            x=silver["t_min"], y=sleep_y,
            mode="lines", line=dict(color="#7c3aed", width=1, shape="hv"),
            name="sleep", hovertemplate="t=%{x:.1f} min<br>stage=%{y}",
        ),
        row=3, col=1,
    )
    fig.update_yaxes(
        tickmode="array", tickvals=[1, 2, 3], ticktext=["deep", "light", "wake"],
        range=[0.5, 3.5], row=3, col=1,
    )

    # ── Row 4: EDOs markers + ±2 min context
    for _, e in edos.iterrows():
        # Sombra de contexto (±2 min) — leve.
        fig.add_vrect(
            x0=e["t_start_min"] - EDO_CONTEXT_S / 60,
            x1=e["t_end_min"] + EDO_CONTEXT_S / 60,
            fillcolor="#fde68a", opacity=0.15,
            line_width=0, row=4, col=1,
        )
        # Span del EDO mismo (rojo más fuerte).
        fig.add_vrect(
            x0=e["t_start_min"], x1=e["t_end_min"],
            fillcolor="#ef4444", opacity=0.45,
            line_width=0, row=4, col=1,
        )
    # Trace fantasma para tooltip por EDO (centrado).
    if len(edos) > 0:
        fig.add_trace(
            go.Scatter(
                x=(edos["t_start_min"] + edos["t_end_min"]) / 2,
                y=[1] * len(edos),
                mode="markers",
                marker=dict(symbol="diamond", color="#dc2626", size=8,
                            line=dict(color="white", width=1)),
                customdata=np.stack([
                    edos["duration_s"].fillna(-1),
                    edos["nadir_spo2"].fillna(-1),
                    edos["drop_pct"].fillna(-1),
                    edos["delta_hr_bpm"].fillna(0),
                    edos["morphotype"].fillna("?"),
                    edos["meets_3pct"].astype(str),
                    edos["meets_4pct"].astype(str),
                ], axis=1),
                hovertemplate=(
                    "t=%{x:.1f} min<br>"
                    "dur=%{customdata[0]} s · nadir=%{customdata[1]}% · "
                    "drop=%{customdata[2]:.1f}%<br>"
                    "ΔHR=%{customdata[3]:.1f} bpm · morfo=%{customdata[4]}<br>"
                    "meets3%=%{customdata[5]} · meets4%=%{customdata[6]}"
                    "<extra></extra>"
                ),
                showlegend=False,
            ),
            row=4, col=1,
        )
    fig.update_yaxes(range=[0, 2], showticklabels=False, row=4, col=1)

    # ── Rows 5, 6, 7: state stripes (l, m, s) — usamos shapes (rectángulos)
    for row_idx, scale in enumerate(("l", "m", "s"), start=5):
        sub = states[states["scale"] == scale].sort_values("window_idx")
        palette = _state_palette(PAC_STATE_PREFIXES[scale], k_per_scale[scale])
        for _, w in sub.iterrows():
            color = palette.get(w["state_label"], "#9ca3af")  # gris para -1
            opacity = 1.0 if w["cluster_int"] >= 0 else 0.25
            fig.add_shape(
                type="rect",
                x0=w["t_start_min"], x1=w["t_end_min"],
                y0=0, y1=1,
                fillcolor=color, opacity=opacity, line_width=0,
                row=row_idx, col=1,
            )
        # Trace fantasma para hover (centrado por ventana, samplea cada N).
        if len(sub) > 0:
            stride = max(1, len(sub) // 200)  # cap a ~200 hover markers/escala
            samp = sub.iloc[::stride]
            fig.add_trace(
                go.Scatter(
                    x=(samp["t_start_min"] + samp["t_end_min"]) / 2,
                    y=[0.5] * len(samp),
                    mode="markers",
                    marker=dict(size=4, color="rgba(0,0,0,0)"),
                    customdata=np.stack([
                        samp["state_label"].fillna("DROP"),
                        samp["coverage"].fillna(-1),
                        samp["frac_wake"].fillna(-1),
                        samp["dist_to_centroid"].fillna(-1),
                    ], axis=1),
                    hovertemplate=(
                        f"<b>{scale}-window</b> t=%{{x:.1f}} min<br>"
                        "state=%{customdata[0]} · cov=%{customdata[1]:.2f}<br>"
                        "frac_wake=%{customdata[2]:.2f} · "
                        "dist=%{customdata[3]:.2f}"
                        "<extra></extra>"
                    ),
                    showlegend=False,
                ),
                row=row_idx, col=1,
            )
        fig.update_yaxes(showticklabels=False, range=[0, 1], row=row_idx, col=1)

    # ── Row 8: morfotipos como barras verticales coloreadas
    morpho_colors = {
        "α": "#10b981", "β": "#f97316", "γ": "#0ea5e9",
        "δ": "#a855f7", "ε": "#facc15", "ζ": "#dc2626",
    }
    if len(edos) > 0:
        for _, e in edos.iterrows():
            mc = morpho_colors.get(e["morphotype"], "#9ca3af")
            fig.add_shape(
                type="rect",
                x0=e["t_start_min"] - 0.3, x1=e["t_end_min"] + 0.3,
                y0=0, y1=1,
                fillcolor=mc, opacity=0.85, line_width=0,
                row=8, col=1,
            )
        # Tooltip sólo (markers transparentes)
        fig.add_trace(
            go.Scatter(
                x=(edos["t_start_min"] + edos["t_end_min"]) / 2,
                y=[0.5] * len(edos),
                mode="markers",
                marker=dict(size=6, color="rgba(0,0,0,0)"),
                customdata=edos[["morphotype", "ird_event"]].values,
                hovertemplate=(
                    "morfo=%{customdata[0]} · "
                    "IRD=%{customdata[1]:.2f}<extra></extra>"
                ),
                showlegend=False,
            ),
            row=8, col=1,
        )
    fig.update_yaxes(showticklabels=False, range=[0, 1], row=8, col=1)

    # ── Layout global
    fig.update_xaxes(title_text="tiempo (min desde inicio)", row=8, col=1)
    title_lines = [
        f"<b>{nr}</b> — {tag}",
        f"<sub>{criterion}</sub>",
        f"<sub>K={k_per_scale} · n_edos={len(edos)} · "
        f"duración={(silver['t_min'].max()):.0f} min</sub>",
    ]
    fig.update_layout(
        title=dict(text="<br>".join(title_lines), x=0.02, xanchor="left"),
        height=1100, width=1600,
        margin=dict(l=60, r=20, t=110, b=40),
        hovermode="x unified",
        showlegend=False,
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(family="Inter, system-ui, sans-serif", size=11),
    )
    for i in range(1, 9):
        fig.update_xaxes(showgrid=True, gridcolor="#f3f4f6", row=i, col=1)
        fig.update_yaxes(showgrid=False, row=i, col=1)

    return fig


# ===========================================================================
# Main
# ===========================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Etapa 4 paso 8.5: stratigraphy dashboard.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    selection = select_representative_nights(seed=args.seed)
    print()
    print("[strata] selección final:")
    for tag, info in selection.items():
        print(f"  {tag:20s}  {info['night_record_id']}  · {info['criterion']}")
    print()

    # Build dashboards
    paths = {}
    for tag, info in selection.items():
        nr = info["night_record_id"]
        print(f"[strata] construyendo {tag} ({nr}) …", flush=True)
        data = load_night_data(nr)
        fig = build_figure(nr, tag, info["criterion"], data)
        out = DASHBOARD_DIR / f"{nr}__{tag}.html"
        fig.write_html(out, include_plotlyjs="cdn", full_html=True)
        size_kb = out.stat().st_size / 1024
        paths[tag] = {"nr": nr, "html": str(out.relative_to(ROOT)),
                      "size_kb": round(size_kb, 1)}
        print(f"        → {out.name} ({size_kb:.0f} KB)")

    # Persist selection JSON (Q7=A)
    with open(SELECTION_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "seed": args.seed,
            "scope": "Etapa 4 paso 8.5 — stratigraphy multi-scale + EDOs",
            "selection": selection,
            "outputs": paths,
        }, f, indent=2, ensure_ascii=False)
    print()
    print(f"[strata] selección persistida: {SELECTION_JSON.name}")
    print(f"[strata] dashboards en {DASHBOARD_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
