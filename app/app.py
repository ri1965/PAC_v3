"""
PAC App — app.py  (v2.0 — rediseño UI)

Streamlit app para análisis de una noche de oximetría.
Entrada: un archivo Excel (formato 3 bloques del dispositivo SOMNI).

Uso:
    cd PAC_v2
    streamlit run app/app.py

Tabs:
    1. Resumen        — Risk Score, KPIs, SpO₂ nocturna
    2. Eventos        — distribución morfotipos C1-C5 | timeline + P(severo)
    3. Estados PAC    — distribución S/M/L | secuencia temporal + transiciones
    4. Historia       — vista integrada | detalle SpO₂ + features
    5. Informe IA     — generación narrativa con LM Studio o Claude API
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ── Path setup ──────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).resolve().parent
_ROOT    = _APP_DIR.parent
_SRC     = _ROOT / "src"
_MODELS  = _ROOT / "models"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.pipeline import run_pipeline

_PIPELINE_VERSION = "v2.0"

# ── Page config ──────────────────────────────────────────────────────────────
from PIL import Image as _PILImage
_favicon_path = _APP_DIR / "assets" / "logo_pac_v3.png"
_favicon = _PILImage.open(_favicon_path) if _favicon_path.exists() else "🫁"

st.set_page_config(
    page_title="PAC — Análisis Nocturno",
    page_icon=_favicon,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS global ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Fondo blanco forzado */
.stApp, .stAppViewContainer, section[data-testid="stAppViewContainer"] {
    background-color: #FFFFFF !important;
}
section[data-testid="stSidebar"] {
    background-color: #F0F4F8 !important;
}

/* Tipografía base */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* Ocultar branding Streamlit */
#MainMenu {visibility: hidden;}
footer    {visibility: hidden;}
header    {visibility: hidden;}

/* ── Tab bar principal ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 6px;
    background: #EEF2F7;
    border-radius: 12px;
    padding: 5px 6px;
    border: none;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 7px 18px;
    font-size: 0.87rem;
    font-weight: 500;
    color: #64748B;
    background: transparent;
    border: none;
    transition: all 0.18s ease;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #1E3A5F;
    background: rgba(255,255,255,0.7);
}
.stTabs [aria-selected="true"] {
    background: #FFFFFF !important;
    color: #1E3A5F !important;
    font-weight: 600;
    box-shadow: 0 1px 6px rgba(30,58,95,0.12);
}

/* ── Sub-tabs (anidados) — tamaño más compacto ── */
.stTabs .stTabs [data-baseweb="tab-list"] {
    background: #F8FAFC;
    border-radius: 8px;
    padding: 3px 4px;
    gap: 4px;
}
.stTabs .stTabs [data-baseweb="tab"] {
    font-size: 0.82rem;
    padding: 5px 14px;
}
.stTabs .stTabs [aria-selected="true"] {
    box-shadow: 0 1px 4px rgba(30,58,95,0.10);
}

/* ── Métricas nativas: card con sombra suave ── */
[data-testid="metric-container"] {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 16px 10px 16px !important;
    box-shadow: 0 1px 6px rgba(0,0,0,0.05);
    transition: box-shadow 0.18s;
}
[data-testid="metric-container"]:hover {
    box-shadow: 0 3px 12px rgba(30,58,95,0.10);
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    color: #64748B !important;
    font-weight: 500 !important;
    letter-spacing: 0.04em;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: #1E293B !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #F8FAFC;
    border-right: 1px solid #E2E8F0;
}
[data-testid="stSidebar"] .stButton button {
    border-radius: 8px;
    font-size: 0.82rem;
}

/* ── Expander ── */
details summary {
    font-weight: 500;
    color: #475569;
}

/* ── Divider más sutil ── */
hr {
    border-color: #E2E8F0 !important;
    margin: 12px 0 !important;
}

/* ── Info/warning boxes ── */
[data-testid="stAlert"] {
    border-radius: 10px;
    font-size: 0.85rem;
}

/* ── Botón primario ── */
.stButton [kind="primary"] {
    background: #1E3A5F !important;
    border-radius: 8px;
    font-weight: 600;
}

/* ── Ocultar modebar de Plotly ── */
.modebar-container { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Paleta de colores ────────────────────────────────────────────────────────
MORPH_COLORS = {
    "C1": "#4878CF",
    "C2": "#6ACC65",
    "C3": "#F0A500",
    "C4": "#E05C5C",
    "C5": "#9B1C1C",
}
STATE_M_COLORS = {
    f"M{i}": c for i, c in enumerate(
        ["#4878CF","#6ACC65","#D65F5F","#B47CC7","#85C1E9","#F39C12","#1ABC9C","#E74C3C"]
    )
}
RISK_COLORS  = {"Bajo": "#16A34A", "Moderado": "#D97706", "Alto": "#DC2626"}
TRAJ_COLORS  = {
    "Estable-Protector":  "#4878CF",
    "Carga Intermedia":   "#D97706",
    "Carga Hipoxica Alta": "#DC2626",
    "Carga Hipóxica Alta": "#DC2626",
}

# ── Helpers ──────────────────────────────────────────────────────────────────
def _fmt_time(dt) -> str:
    try:
        return pd.Timestamp(dt).strftime("%H:%M")
    except Exception:
        return "—"

def _alert(msg: str, level: str = "warning") -> None:
    """Alerta con borde izquierdo oscuro del mismo color. level: warning | info | error"""
    _cfg = {
        "warning": {"bg": "#FFFBEB", "border": "#F59E0B", "icon": "⚠️", "text": "#78350F"},
        "info":    {"bg": "#EFF6FF", "border": "#3B82F6", "icon": "ℹ️", "text": "#1E3A8A"},
        "error":   {"bg": "#FEF2F2", "border": "#EF4444", "icon": "🔴", "text": "#7F1D1D"},
    }
    c = _cfg.get(level, _cfg["warning"])
    import re as _re
    safe = msg.replace("**", "<b>", 1)
    count = 0
    def _toggle(m):
        nonlocal count
        count += 1
        return "</b>" if count % 2 == 0 else "<b>"
    safe = _re.sub(r'\*\*', _toggle, msg)
    st.markdown(f"""
<div style="display:flex;gap:10px;align-items:flex-start;
            background:{c['bg']};border-left:4px solid {c['border']};
            border-radius:0 8px 8px 0;padding:12px 16px;margin:6px 0;
            font-size:0.85rem;color:{c['text']};line-height:1.6">
  <span style="font-size:1rem;flex-shrink:0;margin-top:1px">{c['icon']}</span>
  <span>{safe}</span>
</div>""", unsafe_allow_html=True)

def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m"

def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

_MORPH_LABELS = {
    "C1": "C1 Subcrítico",
    "C2": "C2 Leve/Gradual",
    "C3": "C3 Severo Agudo",
    "C4": "C4 Moderado V",
    "C5": "C5 Severo Progresivo",
}

# ── Sidebar ──────────────────────────────────────────────────────────────────
# ── Sidebar — siempre renderizado (patrón nativo Streamlit) ─────────────────
# El uploader vive aquí para evitar problemas de session_state con widgets
# condicionales. En la landing, el sidebar se oculta con CSS pero sigue activo.
with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:10px;padding:4px 0 12px 0">
      <div style="width:36px;height:36px;border-radius:50%;background:#1E3A5F;
                  display:flex;align-items:center;justify-content:center;
                  border:2px solid #4878CF;flex-shrink:0">
        <span style="font-size:20px;line-height:1;filter:brightness(0) invert(1)">🫁</span>
      </div>
      <div>
        <div style="font-size:1.05rem;font-weight:700;color:#1E3A5F;line-height:1.2">PAC App</div>
        <div style="font-size:0.72rem;color:#94A3B8">Análisis nocturno de oximetría</div>
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.divider()

    uploaded = st.file_uploader(
        "Cargar examen Excel",
        type=["xlsx"],
        label_visibility="collapsed",
        help="Formato 3 bloques: metadata · resumen clásico · señales 1 Hz",
    )

    if uploaded is not None:
        st.divider()
        if st.button("🔄 Limpiar caché", use_container_width=True,
                     help="Forzar re-análisis del archivo actual"):
            st.cache_data.clear()
            st.rerun()
        st.divider()

    # ── Descarga de informe (aparece cuando hay uno generado) ────────────────
    if st.session_state.get("last_report"):
        _sb_rpt       = st.session_state["last_report"]
        _sb_rpt_meta  = st.session_state.get("last_report_meta", {})
        _sb_rpt_type  = st.session_state.get("last_report_type", "especialista")
        _sb_rpt_label = "Informe médico" if _sb_rpt_type == "especialista" else "Resumen paciente"
        _sb_tipo_str  = "medico" if _sb_rpt_type == "especialista" else "paciente"

        st.markdown(
            f'<div style="font-size:0.72rem;color:#94A3B8;font-weight:500;'
            f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px">'
            f'Informe generado</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="font-size:0.8rem;color:#1E3A5F;font-weight:600;margin-bottom:8px">'
            f'{"🩺" if _sb_rpt_type == "especialista" else "🧑"} {_sb_rpt_label}</div>',
            unsafe_allow_html=True,
        )

        def _sb_build_docx(text, meta_info):
            import io
            try:
                from docx import Document as _D
                doc = _D()
                doc.add_heading(
                    f"Informe PAC — Paciente {meta_info.get('user_id','?')} · "
                    f"Examen {meta_info.get('exam_id','?')}", level=1
                )
                doc.add_paragraph(
                    f"Fecha: {meta_info.get('date','—')} | "
                    f"Risk Score: {meta_info.get('risk_score','—')} ({meta_info.get('risk_label','—')})"
                )
                doc.add_paragraph("")
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:              doc.add_paragraph("")
                    elif line.startswith("## "):  doc.add_heading(line[3:], level=2)
                    elif line.startswith("### "): doc.add_heading(line[4:], level=3)
                    elif line.startswith("**") and line.endswith("**"):
                        doc.add_paragraph().add_run(line.strip("*")).bold = True
                    elif line.startswith("- "): doc.add_paragraph(line[2:], style="List Bullet")
                    else: doc.add_paragraph(line)
                buf = io.BytesIO()
                doc.save(buf)
                return buf.getvalue()
            except ImportError:
                return text.encode("utf-8")

        _sb_fname = (
            f"informe_{_sb_tipo_str}_pac_{_sb_rpt_meta.get('exam_id','?')}_"
            f"{_sb_rpt_meta.get('date','').replace('/','')}.docx"
        )
        st.download_button(
            label="⬇️ Descargar .docx",
            data=_sb_build_docx(_sb_rpt, _sb_rpt_meta),
            file_name=_sb_fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
        st.divider()

    st.markdown(
        '<div style="font-size:0.72rem;color:#94A3B8;line-height:1.9">'
        'Pipeline: NB01→NB06<br>LightGBM + LR<br>'
        '<span style="color:#4878CF;font-weight:600">PAC v3</span></div>',
        unsafe_allow_html=True,
    )


# ── Landing (sin archivo) ────────────────────────────────────────────────────
# Para reemplazar el logo: cambiá el span por:
#   <img src="app/assets/logo.png" style="width:173px;height:173px;border-radius:50%">
_LOGO_HTML = """
<div style="width:173px;height:173px;border-radius:50%;background:#1E3A5F;
            display:flex;align-items:center;justify-content:center;
            border:4px solid #4878CF;margin:0 auto 36px auto;
            box-shadow:0 0 0 14px #EEF2F7">
  <span style="font-size:96px;line-height:1;filter:brightness(0) invert(1)">🫁</span>
</div>
"""

if uploaded is None:
    # En la landing el sidebar muestra solo el uploader, sin controles de análisis.
    # El contenido principal muestra logo + título centrado.
    st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
    st.markdown(_LOGO_HTML, unsafe_allow_html=True)
    st.markdown(
        "<h2 style='color:#1E3A5F;font-size:3.2rem;font-weight:800;margin:0 0 12px 0;"
        "letter-spacing:-0.03em;text-align:center'>PAC — Análisis Nocturno</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#475569;font-size:1.15rem;text-align:center;"
        "margin:0 auto 40px auto;max-width:500px;line-height:1.6'>"
        "Morfotipos · Estados PAC · Score de riesgo · Informe IA</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#64748B;font-size:0.9rem;text-align:center;margin-top:8px'>"
        "← Cargá el archivo Excel en el panel izquierdo</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='text-align:center;margin-top:20px;"
        "font-size:0.8rem;color:#64748B;line-height:2'>"
        "Pipeline: NB01→NB06 &nbsp;·&nbsp; LightGBM + LR &nbsp;·&nbsp; "
        "<span style='color:#4878CF;font-weight:500'>PAC v3</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ── Pipeline ─────────────────────────────────────────────────────────────────
@st.cache_data(show_spinner="⏳ Analizando la noche…")
def _run(file_bytes: bytes, filename: str, version: str):
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        result = run_pipeline(tmp_path, models_dir=_MODELS, verbose=False)
    finally:
        os.unlink(tmp_path)
    return result


file_bytes = uploaded.getvalue()
try:
    result = _run(file_bytes, uploaded.name, version=_PIPELINE_VERSION)
except Exception as exc:
    st.error(f"❌ Error al procesar el archivo: {exc}")
    st.exception(exc)
    st.stop()

meta        = result["meta"]
sig         = result["sig"]
ev_df       = result["ev_df"]
state_win   = result["state_windows"]
night_feats = result["night_feats"]
n_events    = result["n_events"]
n_severe    = result["n_severe"]
risk_score  = result["risk_score"]
risk_label  = result["risk_label"]
p_night     = result["p_night"]
p_sev_mean  = result.get("p_severe_mean", np.nan)
traj_name   = result["traj_name"]
duration_s  = float(
    (sig["timestamp"].iloc[-1] - sig["timestamp"].iloc[0]).total_seconds()
)

# ── Header de paciente (siempre visible encima de los tabs) ──────────────────
user_id  = meta.get("user_id", "—").strip()
exam_id  = meta.get("exam_id", meta.get("id", "—"))
t_start  = _fmt_time(meta.get("start_time"))
t_end    = _fmt_time(meta.get("end_time"))
date_str = ""
try:
    date_str = pd.Timestamp(meta.get("start_time")).strftime("%d/%m/%Y")
except Exception:
    pass

risk_color = RISK_COLORS.get(risk_label, "#888")
risk_num   = f"{risk_score:.0f}" if not np.isnan(risk_score) else "—"

st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;
            background:#FFFFFF;border:1px solid #E2E8F0;border-radius:14px;
            padding:12px 20px;margin-bottom:14px;
            box-shadow:0 1px 6px rgba(0,0,0,0.05)">
  <div>
    <div style="font-size:0.75rem;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.06em;font-weight:500">Paciente</div>
    <div style="font-size:1.1rem;font-weight:700;color:#1E3A5F">
      {user_id} &nbsp;·&nbsp;
      <span style="font-weight:400;color:#475569">Examen {exam_id}</span>
    </div>
    <div style="font-size:0.8rem;color:#94A3B8;margin-top:1px">
      {date_str} &nbsp; {t_start} → {t_end} &nbsp;·&nbsp; {_fmt_duration(duration_s)}
    </div>
  </div>
  <div style="text-align:right">
    <div style="font-size:0.72rem;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.06em;font-weight:500">Risk Score PAC</div>
    <div style="font-size:2.2rem;font-weight:900;color:{risk_color};line-height:1.1">
      {risk_num}
    </div>
    <div style="font-size:0.8rem;font-weight:600;color:{risk_color}">{risk_label}</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Banner global: registro corto ───────────────────────────────────────────
_SHORT_NIGHT_GLOBAL = duration_s < 14400
if _SHORT_NIGHT_GLOBAL:
    _dur_h_g = duration_s / 3600
    _alert(
        f"**Registro corto ({_dur_h_g:.1f} h < 4 h recomendadas)** — el pipeline PAC_v3 fue entrenado "
        f"sobre noches completas (6–10 h). Con {_dur_h_g:.1f} h de señal, las fracciones de estados PAC "
        f"son estadísticamente menos estables, los coupling indices pueden no estar disponibles (CI = —) "
        f"y el ODI está calculado sobre una ventana reducida. "
        f"Todos los resultados de esta sesión son **orientativos**; interpretar con mayor cautela.",
    )

# ═══════════════════════════════════════════════════════════════════════════════
# TABS PRINCIPALES
# ═══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Resumen",
    "🔵 Eventos",
    "🔷 Estados PAC",
    "📈 Historia",
    "📋 Informe IA",
])


# ══════════════════════════════
# TAB 1 — RESUMEN
# Sub-tab A: Gauge + KPIs + Trayectoria
# Sub-tab B: Señal SpO₂ nocturna
# ══════════════════════════════
with tab1:
    res_sub_a, res_sub_b = st.tabs(["📊 Resumen clínico", "📉 Señal SpO₂"])

    with res_sub_a:
        col_risk, col_kpis = st.columns([1, 2], gap="large")

    with col_risk:
        gauge_val = float(risk_score) if not np.isnan(risk_score) else 0.0
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=gauge_val,
            number={"suffix": " / 100", "font": {"size": 22, "color": risk_color}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#CBD5E1"},
                "bar": {"color": risk_color, "thickness": 0.28},
                "bgcolor": "white",
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 30],   "color": "#DCFCE7"},
                    {"range": [30, 60],  "color": "#FEF3C7"},
                    {"range": [60, 100], "color": "#FEE2E2"},
                ],
                "threshold": {
                    "line": {"color": risk_color, "width": 4},
                    "thickness": 0.75,
                    "value": gauge_val,
                },
            },
        ))
        fig_gauge.update_layout(
            height=220,
            margin=dict(t=20, b=0, l=20, r=20),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_gauge, use_container_width=True)
        st.caption(
            "**Risk Score PAC 0–100**: estimación del riesgo de eventos de desaturación severos durante la noche. "
            "Verde 0–30: bajo riesgo · Naranja 30–60: moderado · Rojo 60–100: alto.",
            help=(
                "El score integra frecuencia de eventos **y** contexto fisiológico global — "
                "no solo cuántos eventos severos hubo.\n\n"
                "Una noche con muchos eventos leves en estados M de carga moderada puede puntuar 40 "
                "aunque no haya eventos severos.\n\n"
                "**Leelo junto con:** trayectoria nocturna, CI_M y T90 para entender "
                "*qué tipo* de riesgo tiene la noche."
            )
        )

        # Trayectoria
        traj_color = TRAJ_COLORS.get(traj_name, "#888")
        st.markdown(f"""
<div style="text-align:center;padding:10px 14px;border-radius:10px;
            background:{traj_color}14;border:1.5px solid {traj_color}40;">
  <div style="font-size:0.7rem;color:#94A3B8;font-weight:500;text-transform:uppercase;
              letter-spacing:0.05em">Trayectoria nocturna</div>
  <div style="font-size:0.95rem;font-weight:700;color:{traj_color};margin-top:2px">
    {traj_name}
  </div>
</div>
""", unsafe_allow_html=True)

    with col_kpis:
        odi_approx = (
            round(n_events / (duration_s / 3600), 1)
            if duration_s > 0 and n_events > 0 else 0
        )
        k1, k2, k3 = st.columns(3)
        k1.metric("EDOs detectados", n_events)
        _pct_sev_label = f"{n_severe/max(n_events,1)*100:.1f}%"
        k2.metric("Severos C4/C5", f"{n_severe}  ({_pct_sev_label})")
        _odi_short_note = f"\n\n⚠ Calculado sobre {duration_s/3600:.1f} h (registro corto — no comparable al ODI clínico de noche completa)." if _SHORT_NIGHT_GLOBAL else ""
        k3.metric("ODI estimado (ev/h)", odi_approx,
            help=f"Desaturaciones por hora (umbral ≥ 2 pp).\n\n- **< 5** → leve\n- **5–15** → moderado\n- **> 15** → alto{_odi_short_note}")

        k4, k5, k6 = st.columns(3)
        k4.metric("P(noche alto riesgo)",
                  f"{p_night:.3f}" if not np.isnan(p_night) else "—",
                  help=(
                      "Probabilidad de que esta noche tenga un perfil fisiológico de riesgo. "
                      "Componente principal del Risk Score (60%).\n\n"
                      "Por encima de 0.5 el perfil de la noche domina el score."
                  ))
        k5.metric("P̄(evento severo)",
                  f"{p_sev_mean:.3f}" if not np.isnan(p_sev_mean) else "—",
                  help=(
                      "Cuán probables son los eventos severos en esta noche en particular.\n\n"
                      "Si este número es bajo pero el ODI es alto, la noche tiene muchos eventos "
                      "pero morfológicamente leves."
                  ))
        spo2_vals = sig["spo2_clean"].dropna()
        t90_pct   = float((spo2_vals < 90).mean() * 100) if len(spo2_vals) > 0 else np.nan
        k6.metric("T90 (%)", f"{t90_pct:.1f}%" if not np.isnan(t90_pct) else "—",
            help="Tiempo con oxígeno bajo 90%.\n\n- **< 1%** → mínimo\n- **1–5%** → leve-moderado\n- **> 5%** → significativo")

        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)

        # ci_m / ci_l / ci_s — usados también en alertas de Resumen
        ci_m      = night_feats.get("ci_m", np.nan)
        ci_l      = night_feats.get("ci_l", np.nan)
        ci_s      = night_feats.get("ci_s", np.nan)
        m_ari_raw = night_feats.get("mean_ari", np.nan)

        # Normalizar ARI usando la fórmula canónica (Cap04 §4.3, T1):
        # ARIᵢ = 0.6·P(hr_gain) + 0.4·P(mov_gain)
        # hr_gain = delta_hr_bpm / drop_pct
        # mov_gain = (peak_mov - baseline_mov) / drop_pct
        # P(·) = percentil dentro del corpus (n=85.277 quality events)
        _hr_sorted  = _MODELS / "ari_hr_gain_sorted.npy"
        _mov_sorted = _MODELS / "ari_mov_gain_sorted.npy"
        _ari_ok = (
            _hr_sorted.exists() and _mov_sorted.exists()
            and not ev_df.empty
            and all(c in ev_df.columns for c in ["delta_hr_bpm", "drop_pct", "peak_mov", "baseline_mov"])
        )
        if _ari_ok:
            _c_hr  = np.load(str(_hr_sorted))
            _c_mov = np.load(str(_mov_sorted))
            _ev    = ev_df.dropna(subset=["delta_hr_bpm","drop_pct","peak_mov","baseline_mov"]).copy()
            _ev    = _ev[_ev["drop_pct"] > 0]  # evitar div/0
            if len(_ev) > 0:
                _hr_gain  = (_ev["delta_hr_bpm"] / _ev["drop_pct"]).values
                _mov_gain = ((_ev["peak_mov"] - _ev["baseline_mov"]) / _ev["drop_pct"]).values
                _P_hr  = np.searchsorted(_c_hr,  _hr_gain)  / len(_c_hr)
                _P_mov = np.searchsorted(_c_mov, _mov_gain) / len(_c_mov)
                _ari_per_event = 0.6 * _P_hr + 0.4 * _P_mov
                m_ari = float(np.mean(_ari_per_event))   # 0–1, mediana del corpus = 0.50
            else:
                m_ari = m_ari_raw
        else:
            m_ari = m_ari_raw  # fallback al campo bruto si faltan columnas

        pct_s     = night_feats.get("pct_severe", 0)
        ci_m_str  = f"{ci_m:.3f}"  if not np.isnan(ci_m)  else "—"
        m_ari_str = f"{m_ari:.3f}" if not np.isnan(m_ari) else "—"
        pct_s_str = f"{pct_s*100:.1f}%"
        st.markdown(f"""
<div style="display:flex;gap:10px;flex-wrap:wrap">
  <div style="flex:1;min-width:100px;background:#F8FAFC;border:1px solid #E2E8F0;
              border-radius:10px;padding:10px 14px">
    <div style="font-size:0.7rem;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.04em;font-weight:500">ci_m (coupling M)</div>
    <div style="font-size:1.2rem;font-weight:700;color:#1E293B;margin-top:2px">
      {ci_m_str}</div>
  </div>
  <div style="flex:1;min-width:100px;background:#F8FAFC;border:1px solid #E2E8F0;
              border-radius:10px;padding:10px 14px">
    <div style="font-size:0.7rem;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.04em;font-weight:500">ARI medio (FC+MOV)</div>
    <div style="font-size:1.2rem;font-weight:700;color:#1E293B;margin-top:2px">
      {m_ari_str}</div>
  </div>
  <div style="flex:1;min-width:100px;background:#F8FAFC;border:1px solid #E2E8F0;
              border-radius:10px;padding:10px 14px">
    <div style="font-size:0.7rem;color:#94A3B8;text-transform:uppercase;
                letter-spacing:0.04em;font-weight:500">% severos</div>
    <div style="font-size:1.2rem;font-weight:700;color:#1E293B;margin-top:2px">
      {pct_s_str}</div>
  </div>
</div>
""", unsafe_allow_html=True)
        # ── Alerta de inconsistencia modelo vs. índices brutos ───────────────
        # Suprimida si ya dispara la alerta de discordancia CI (más informativa)
        _ci_disc_active = not np.isnan(ci_m) and ci_m >= 0.7 and risk_score < 61
        _pct_val_check = pct_s * 100
        _model_understates = (
            not _ci_disc_active and (
                _pct_val_check > 10 and risk_score < 60
                or (not np.isnan(p_night) and p_night < 0.1 and _pct_val_check > 10)
            )
        )
        if _model_understates:
            _reasons = []
            if _pct_val_check > 15:
                _reasons.append(f"% severos = {_pct_val_check:.1f}% (muy alto, > 15%)")
            elif _pct_val_check > 10:
                _reasons.append(f"% severos = {_pct_val_check:.1f}% (alto, > 10%)")
            if not np.isnan(p_night) and p_night < 0.05 and _pct_val_check > 10:
                _reasons.append(f"P(noche alto riesgo) = {p_night:.3f} (modelo subestima)")
            odi_check = n_events / (duration_s / 3600) if duration_s > 0 else 0
            if odi_check > 15:
                _reasons.append(f"ODI = {odi_check:.1f} ev/h (moderado-severo)")
            _reason_str = " · ".join(_reasons)
            st.markdown(f"""
<div style="margin-top:12px;padding:12px 16px;border-radius:10px;
            background:#FEF3C7;border-left:4px solid #D97706;">
  <div style="font-size:0.82rem;font-weight:700;color:#92400E;margin-bottom:4px">
    ⚠️ Posible subestimación del riesgo por el modelo
  </div>
  <div style="font-size:0.78rem;color:#78350F;line-height:1.5">
    Los índices brutos sugieren mayor riesgo que el Risk Score ({risk_score:.0f} — {risk_label}).
    <br>{_reason_str}.
    <br><span style="color:#92400E">Integrar con criterio clínico. El modelo fue entrenado con n=8 pacientes y puede no generalizar a este fenotipo.</span>
  </div>
</div>
""", unsafe_allow_html=True)

        # ── Alerta: RS moderado/alto con 0 C4/C5 (posible sobreestimación) ──
        _n_severe_ev = int(ev_df["morphotype_curve"].isin(["C4","C5"]).sum()) if "morphotype_curve" in ev_df.columns else 0
        _SHORT_NIGHT = duration_s < 14400  # < 4 horas
        if risk_score >= 40 and _n_severe_ev == 0:
            _dur_h = duration_s / 3600
            if _SHORT_NIGHT:
                _alert(
                    f"**Discordancia — RS {risk_score:.0f} ({risk_label}) sin eventos C4/C5 · registro corto ({_dur_h:.1f} h):** "
                    f"el Risk Score refleja las features de estados PAC y P(noche alto riesgo) (peso 60%), no los morfotipos. "
                    f"Con {_dur_h:.1f} h de registro (< 4 h recomendadas), las fracciones de estados son menos estables "
                    f"y el modelo opera fuera de su rango de validez. "
                    f"La carga morfológica real (0 eventos C4/C5, T90 {t90_pct:.1f}%) sugiere baja severidad. "
                    f"**El RS puede estar sobreestimando — interpretar con cautela.**",
                )
            else:
                _alert(
                    f"**RS {risk_score:.0f} ({risk_label}) con 0 eventos C4/C5:** el score está siendo impulsado por el contexto "
                    f"fisiológico (estados PAC, P(noche alto riesgo) = {p_night:.3f}), no por morfotipos severos. "
                    f"Revisar distribución de estados M y trayectoria nocturna para entender el origen del riesgo contextual.",
                )

        # ── Discordancia CI alto + RS bajo (subestimación) — también en Resumen ──
        if not np.isnan(ci_m) and risk_score < 61:
            if ci_m >= 0.7 and ci_l >= 0.5:
                _alert(
                    f"**Discordancia estructural:** Risk Score {risk_score:.0f} ({risk_label}), "
                    f"pero CI_M = {ci_m:.3f} y CI_L = {ci_l:.3f} — todos o casi todos los eventos severos "
                    f"ocurrieron en estados M y L patológicos. El score puede estar **subestimando la carga estructural**. "
                    f"Revisar distribución de morfotipos, trayectoria nocturna y pestaña Historia.",
                )
            elif ci_m >= 0.7:
                _alert(
                    f"**Discordancia de acoplamiento:** Risk Score {risk_score:.0f} ({risk_label}), "
                    f"pero CI_M = {ci_m:.3f} — los eventos severos se concentraron en estados M patológicos (M1/M3). "
                    f"El score refleja baja frecuencia de C4/C5, pero su contexto fisiológico es de alto riesgo. "
                    f"Ver pestaña Historia para detalle de acoplamiento.",
                )

        st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)
        # ── Interpretaciones dinámicas según valores de la noche ──────────
        if not np.isnan(ci_m):
            if ci_m >= 0.99:
                _ci_interp = (
                    f"**{ci_m_str}** (máximo): el 100% de los eventos severos ocurrió durante estados fisiológicos patológicos (M1, M3). "
                    f"Los episodios graves no fueron aleatorios — el organismo estaba sistemáticamente comprometido cuando cayó el oxígeno. "
                    f"Clínicamente sugiere que intervenciones que modifiquen el estado fisiológico global (CPAP, posición) "
                    f"podrían reducir los eventos severos."
                )
            elif ci_m > 0.7:
                _ci_interp = (
                    f"**{ci_m_str}** (acoplamiento fuerte): la mayoría de los eventos severos coincidió con estados patológicos. "
                    f"El organismo tiende a estar en mal estado cuando ocurren los peores episodios. "
                    f"Intervenciones sistémicas probablemente efectivas."
                )
            elif ci_m > 0.4:
                _ci_interp = (
                    f"**{ci_m_str}** (acoplamiento moderado): los eventos severos ocurren tanto en estados patológicos como en estados normales. "
                    f"El disparador no es puramente sistémico — puede haber factores locales o mecánicos coexistentes."
                )
            else:
                _ci_interp = (
                    f"**{ci_m_str}** (acoplamiento bajo): los eventos severos ocurren independientemente del estado fisiológico activo. "
                    f"Clínicamente sugiere disparadores locales o mecánicos (anatomía de vía aérea, posición) más que un estado sistémico comprometido. "
                    f"Potencialmente más difíciles de controlar con intervenciones sistémicas."
                )
        else:
            _ci_interp = "**ci_m**: sin datos suficientes."

        if not np.isnan(m_ari):
            if m_ari > 0.6:
                _ari_interp = f"reactividad autonómica **alta**: el organismo genera respuesta cardíaca y motora intensa ante las caídas de oxígeno."
            elif m_ari > 0.4:
                _ari_interp = f"reactividad autonómica **normal** (cerca de la mediana del corpus): respuesta cardíaca y motora dentro del rango esperado."
            else:
                _ari_interp = f"reactividad autonómica **baja**: respuesta cardíaca y motora reducida ante las caídas de oxígeno, posible agotamiento autonómico."
            _ari_note = (
                f"**{m_ari:.2f}** (percentil {m_ari*100:.0f}° del corpus PAC_v3, n=85.277 eventos): {_ari_interp} "
                f"El ARI combina respuesta de FC (60%) y movimiento (40%) por unidad de caída de SpO₂. "
                f"Escala 0–1 donde 0.50 = mediana del corpus. "
                f"Referencia: < 0.40 = baja · 0.40–0.60 = normal · > 0.60 = alta. "
                f"Paradoja PAC: los morfotipos más severos (C5) tienen el ARI más bajo del corpus (percentil ~42°), "
                f"sugiriendo agotamiento autonómico en las desaturaciones profundas."
            )
        else:
            _ari_note = "**ARI**: sin datos suficientes."

        _pct_val = pct_s * 100
        if _pct_val > 15:
            _pct_interp = f"**{pct_s_str}** — carga severa **muy alta** (> 15%): noche con predominio de eventos de desaturación profunda."
        elif _pct_val > 10:
            _pct_interp = f"**{pct_s_str}** — carga severa **alta** (10–15%): proporción de eventos graves significativamente por encima de la media del corpus (6.1%)."
        elif _pct_val >= 6:
            _pct_interp = f"**{pct_s_str}** — carga severa **moderada** (6–10%): levemente por encima de la media del corpus (6.1%), dentro del rango esperable."
        else:
            _pct_interp = f"**{pct_s_str}** — carga severa **baja** (< 6%): por debajo de la media del corpus (6.1%)."

        st.caption(
            f"**ci_m (Coupling M):** {_ci_interp} "
            f"Referencia: < 0.3 = disparador local/mecánico (posición, anatomía) · 0.3–0.7 = mixto · > 0.7 = compromiso sistémico predominante."
        )
        st.caption(
            f"**ARI medio:** {_ari_note}"
        )
        st.caption(
            f"**% severos:** {_pct_interp} "
            f"Orientación: < 6% baja · 6–10% moderada · 10–15% alta · > 15% muy alta."
        )

    with res_sub_b:
        step      = max(1, len(sig) // 5000)
        sig_plot  = sig.iloc[::step].copy()
        fig_spo2  = go.Figure()
        fig_spo2.add_trace(go.Scatter(
            x=sig_plot["timestamp"], y=sig_plot["spo2_clean"],
            mode="lines", name="SpO₂",
            line=dict(color="#4878CF", width=1.2),
            hovertemplate="%{x|%H:%M:%S}  SpO₂: %{y:.0f}%<extra></extra>",
        ))
        if not ev_df.empty:
            for _, row in ev_df.iterrows():
                clr = MORPH_COLORS.get(row.get("morphotype_curve", "C1"), "#888")
                sev = row.get("is_severe", 0)
                fig_spo2.add_vrect(
                    x0=row["ts_start"], x1=row["ts_end"],
                    fillcolor=clr, opacity=0.28 if sev else 0.11, line_width=0,
                )
        fig_spo2.add_hline(y=90, line_dash="dash", line_color="#DC2626",
                           annotation_text="T90 90%", annotation_position="bottom right",
                           annotation_font_color="#DC2626")
        fig_spo2.update_layout(
            height=460, margin=dict(t=20, b=30, l=40, r=20),
            xaxis_title="Hora", yaxis_title="SpO₂ (%)",
            yaxis=dict(range=[60, 102]),
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="#FAFBFD",
        )
        fig_spo2.update_xaxes(showgrid=False)
        fig_spo2.update_yaxes(gridcolor="#EEF2F7")
        st.plotly_chart(fig_spo2, use_container_width=True)
        st.caption("Señal de SpO₂ a 1 Hz durante toda la noche. Las regiones sombreadas corresponden a EDOs detectados, coloreados según morfotipo (C1 azul → C5 rojo oscuro; mayor opacidad = evento severo). La línea roja punteada marca el umbral T90 (90%): el tiempo acumulado por debajo de este valor es un predictor independiente de mortalidad cardiovascular (Azarbarzin et al., 2019).")


# ══════════════════════════════
# TAB 2 — EVENTOS Y MORFOTIPOS
# Sub-tab A: Distribución | Sub-tab B: Timeline + P(severo)
# ══════════════════════════════
with tab2:
    if ev_df.empty:
        st.warning("No se detectaron eventos en esta noche.")
    else:
        ev_sub_a, ev_sub_b, ev_sub_c = st.tabs([
            "📊 Distribución morfotipos",
            "⏱ Timeline de eventos",
            "⚡ P(severo) por evento",
        ])

        # ── Sub-tab A: Distribución ──────────────────────────────────────────
        with ev_sub_a:
            col_pie, col_box = st.columns([1, 2], gap="large")

            with col_pie:
                morph_counts = (
                    ev_df["morphotype_curve"]
                    .value_counts()
                    .reindex(["C1","C2","C3","C4","C5"], fill_value=0)
                    .reset_index()
                )
                morph_counts.columns = ["Morfotipo", "Count"]
                morph_counts["Nombre"] = morph_counts["Morfotipo"].map(_MORPH_LABELS)
                fig_pie = px.pie(
                    morph_counts, names="Nombre", values="Count",
                    color="Morfotipo",
                    color_discrete_map={_MORPH_LABELS[k]: v for k, v in MORPH_COLORS.items()},
                    hole=0.48,
                    title="Distribución morfotipos C1–C5",
                )
                fig_pie.update_traces(
                    textposition="inside", textinfo="percent+label", textfont_size=11,
                )
                fig_pie.update_layout(
                    height=270, margin=dict(t=40, b=0, l=0, r=0),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                )
                st.plotly_chart(fig_pie, use_container_width=True)
                st.caption("**C1** subcrítico (caída <3pp) · **C2** leve/gradual · **C3** severo agudo · **C4** moderado en V · **C5** severo progresivo. C4+C5 son los morfotipos de riesgo; su fracción sobre el total es el indicador de severidad morfológica de la noche.")

            with col_box:
                fig_box = px.box(
                    ev_df, x="morphotype_curve", y="drop_pct",
                    color="morphotype_curve",
                    color_discrete_map=MORPH_COLORS,
                    category_orders={"morphotype_curve": ["C1","C2","C3","C4","C5"]},
                    labels={"morphotype_curve": "Morfotipo", "drop_pct": "Caída SpO₂ (%)"},
                    title="Profundidad de caída por morfotipo",
                    points="outliers",
                )
                fig_box.update_layout(
                    height=270, margin=dict(t=40, b=20, l=40, r=20),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="#FAFBFD",
                )
                fig_box.update_yaxes(gridcolor="#EEF2F7")
                st.plotly_chart(fig_box, use_container_width=True)
                st.caption("Profundidad mediana de caída de SpO₂ por morfotipo. La progresión C1→C5 refleja la jerarquía de severidad del fenotipado morfológico. Los puntos fuera de los bigotes son eventos atípicos dentro de cada clase.")

            # Tabla resumen — fila por morfotipo, altura fija para 5 filas
            st.divider()
            morph_summary = ev_df.groupby("morphotype_curve").agg(
                N=("duration_s","count"),
                Drop_med=("drop_pct","median"),
                Dur_med=("duration_s","median"),
            ).reindex(["C1","C2","C3","C4","C5"]).dropna(how="all").reset_index()
            morph_summary.columns = ["Morfotipo","N eventos","Caída mediana (pp)","Duración mediana (s)"]
            morph_summary["Caída mediana (pp)"]   = morph_summary["Caída mediana (pp)"].round(1)
            morph_summary["Duración mediana (s)"] = morph_summary["Duración mediana (s)"].round(0)
            st.dataframe(morph_summary, use_container_width=True, hide_index=True, height=215)

        # ── Sub-tab B: Timeline de eventos ─────────────────────────────────
        with ev_sub_b:
            st.markdown("**Eventos a lo largo de la noche** — color y altura: real &nbsp;·&nbsp; ◆: predicho por el modelo")
            # Construir leyenda legible: primero morfotipos (círculo), luego predichos (◆)
            _MORPH_NAMES = {
                "C1": "C1 Subcrítico", "C2": "C2 Leve/Gradual",
                "C3": "C3 Severo Agudo", "C4": "C4 Moderado en V", "C5": "C5 Severo Progresivo",
            }
            _scatter_df = ev_df.copy()
            _scatter_df["_morph_label"] = _scatter_df["morphotype_curve"].map(_MORPH_NAMES).fillna(_scatter_df["morphotype_curve"])
            _scatter_df["_symbol"] = _scatter_df["is_severe"].map({0: "circle", 1: "diamond"}).fillna("circle")

            fig_scatter = px.scatter(
                _scatter_df,
                x="ts_start", y="drop_pct",
                color="_morph_label",
                color_discrete_map={v: MORPH_COLORS.get(k, "#999") for k, v in _MORPH_NAMES.items()},
                size="duration_s", size_max=18,
                symbol="_symbol",
                symbol_map={"circle": "circle", "diamond": "diamond"},
                labels={
                    "ts_start": "Hora", "drop_pct": "Caída SpO₂ (%)",
                    "_morph_label": "Morfotipo", "duration_s": "Duración (s)",
                    "_symbol": "Predicción",
                },
                hover_data={
                    "ts_start": "|%H:%M:%S",
                    "morphotype_curve": True,
                    "drop_pct": ":.1f",
                    "duration_s": ":.0f",
                    "state_m_label": True,
                    "p_severe": ":.3f",
                    "_morph_label": False,
                    "_symbol": False,
                },
                title=None,
                category_orders={"_morph_label": [v for v in _MORPH_NAMES.values()]},
            )
            # Renombrar trazos de símbolo para leyenda limpia
            for trace in fig_scatter.data:
                if hasattr(trace, "name"):
                    if ", circle" in trace.name:
                        trace.name = trace.name.replace(", circle", "")
                    elif ", diamond" in trace.name:
                        trace.name = trace.name.replace(", diamond", "  ◆ predicho")
            fig_scatter.update_layout(
                height=480, margin=dict(t=20, b=100, l=40, r=20),
                hovermode="closest",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#FAFBFD",
                legend=dict(
                    orientation="h", y=-0.22, x=0.5, xanchor="center",
                    title_text="", tracegroupgap=2,
                ),
            )
            fig_scatter.update_yaxes(gridcolor="#EEF2F7")
            st.plotly_chart(fig_scatter, use_container_width=True)

            # ── Caption dinámico del timeline ──────────────────────────────
            _n_tot   = len(ev_df)
            _n_sev   = int(ev_df["morphotype_curve"].isin(["C4","C5"]).sum()) if "morphotype_curve" in ev_df.columns else 0
            _pct_sev = 100 * _n_sev / _n_tot if _n_tot else 0

            # Concentración temporal (primera vs segunda mitad de la noche)
            if "ts_start" in ev_df.columns and _n_tot > 1:
                _t_mid = ev_df["ts_start"].min() + (ev_df["ts_start"].max() - ev_df["ts_start"].min()) / 2
                _n_first  = int((ev_df["ts_start"] <= _t_mid).sum())
                _n_second = _n_tot - _n_first
                if _n_second > _n_first * 1.5:
                    _temporal = f"concentrados en la **segunda mitad** ({_n_second} de {_n_tot}), sugiriendo deterioro progresivo"
                elif _n_first > _n_second * 1.5:
                    _temporal = f"concentrados en la **primera mitad** ({_n_first} de {_n_tot}), sugiriendo mejoría a lo largo de la noche"
                else:
                    _temporal = f"distribuidos de forma **relativamente uniforme** a lo largo de la noche"
            else:
                _temporal = ""

            # Drop máximo y mediano
            if "drop_pct" in ev_df.columns:
                _drop_max = ev_df["drop_pct"].max()
                _drop_med = ev_df["drop_pct"].median()
                _drop_txt = f"Caída máxima **{_drop_max:.1f} pp** · mediana **{_drop_med:.1f} pp**."
            else:
                _drop_txt = ""

            # Evento más largo
            if "duration_s" in ev_df.columns:
                _dur_max = ev_df["duration_s"].max()
                _dur_txt = f"Evento más largo: **{int(_dur_max)} s**."
            else:
                _dur_txt = ""

            if _n_tot > 0:
                _esta_noche_scatter = (
                    f"**{_n_tot} eventos detectados** en la noche, {_temporal}. "
                    f"Morfotipos severos C4/C5: **{_n_sev} eventos ({_pct_sev:.0f}%)**. "
                    f"{_drop_txt} {_dur_txt}"
                )
            else:
                _esta_noche_scatter = "Sin eventos detectados en esta noche."

            st.caption(
                "Este gráfico combina dos dimensiones: **lo que ocurrió** y **lo que el modelo anticipó**.\n\n"
                "— **Color**: morfotipo real del evento (qué forma tuvo la curva SpO₂). "
                "— **Eje Y**: caída real de SpO₂ respecto al baseline local (cuán profundo fue). "
                "— **Tamaño**: duración real del evento. "
                "— **Símbolo ◆** (diamante): el modelo predijo que ese evento sería severo, basándose en el contexto fisiológico activo "
                "*antes* de conocer el resultado. Un círculo (●) significa que el modelo no lo anticipó como severo.\n\n"
                f"**En esta noche:** {_esta_noche_scatter}\n\n"
                "**Para qué sirve:** cruzar morfotipo real con predicción del modelo. "
                "Un ◆ en C1/C2 (azul/verde) indica que el evento resultó leve pero el contexto lo hacía esperable grave — riesgo oculto. "
                "Un ● en C4/C5 (naranja/rojo) indica un evento severo que el modelo no anticipó."
            )

        # ── Sub-tab C: P(severo) por evento + tabla ─────────────────────────
        with ev_sub_c:
            if "p_severe" in ev_df.columns:
                fig_prob = go.Figure()
                colors_ev = ev_df["morphotype_curve"].map(MORPH_COLORS).fillna("#888")
                fig_prob.add_trace(go.Bar(
                    x=ev_df["ts_start"], y=ev_df["p_severe"],
                    marker_color=colors_ev, name="P(severo)",
                    showlegend=False,
                    hovertemplate="%{x|%H:%M:%S}  P(severo)=%{y:.3f}<extra></extra>",
                ))
                # Trazas invisibles para leyenda de morfotipos
                _morph_labels = {
                    "C1": "C1 Subcrítico",
                    "C2": "C2 Leve/Gradual",
                    "C3": "C3 Severo Agudo",
                    "C4": "C4 Moderado en V",
                    "C5": "C5 Severo Progresivo",
                }
                _morphs_present = ev_df["morphotype_curve"].dropna().unique()
                for _mc in ["C1","C2","C3","C4","C5"]:
                    if _mc in _morphs_present:
                        fig_prob.add_trace(go.Bar(
                            x=[None], y=[None],
                            marker_color=MORPH_COLORS.get(_mc, "#888"),
                            name=_morph_labels.get(_mc, _mc),
                            showlegend=True,
                        ))
                # Umbral Youden como traza visible en leyenda
                fig_prob.add_trace(go.Scatter(
                    x=[None], y=[None],
                    mode="lines",
                    line=dict(color="#DC2626", dash="dash", width=2),
                    name="Umbral Youden (0.386)",
                    showlegend=True,
                ))
                fig_prob.add_hline(
                    y=0.386, line_dash="dash", line_color="#DC2626",
                )
                fig_prob.update_layout(
                    height=340, margin=dict(t=20, b=30, l=40, r=20),
                    xaxis_title="Hora", yaxis_title="P(evento severo)",
                    yaxis=dict(range=[0, 1]),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="#FAFBFD",
                    legend=dict(
                        orientation="v", x=0.01, y=0.99,
                        xanchor="left", yanchor="top",
                        bgcolor="rgba(255,255,255,0.85)",
                        bordercolor="#E2E8F0", borderwidth=1,
                        font=dict(size=11),
                    ),
                )
                fig_prob.update_yaxes(gridcolor="#EEF2F7")
                st.plotly_chart(fig_prob, use_container_width=True)
                # ── Caption dinámico ──────────────────────────────────────────
                _ev_p  = ev_df.dropna(subset=["p_severe"]).copy()
                _n_total   = len(_ev_p)
                _THOLD     = 0.386
                _n_above   = int((_ev_p["p_severe"] > _THOLD).sum())
                _pct_above = _n_above / _n_total * 100 if _n_total > 0 else 0

                # Patrón temporal
                if _n_total > 1:
                    _mid   = _ev_p["ts_start"].quantile(0.5)
                    _above = _ev_p[_ev_p["p_severe"] > _THOLD]
                    if len(_above) == 0:
                        _patron = "ningún evento supera el umbral — noche de alta frecuencia pero morfológicamente leve."
                    else:
                        _n_first  = int((_above["ts_start"] <= _mid).sum())
                        _n_second = int((_above["ts_start"] >  _mid).sum())
                        _ratio    = _n_second / len(_above)
                        if _ratio > 0.65:
                            _patron = (f"concentradas en la **segunda mitad** ({_n_second} de {len(_above)}), "
                                       f"sugiriendo deterioro progresivo —posible fatiga muscular o cambio de fase de sueño—.")
                        elif _ratio < 0.35:
                            _patron = (f"concentradas en la **primera mitad** ({_n_first} de {len(_above)}), "
                                       f"con tendencia a mejorar hacia el amanecer.")
                        else:
                            _patron = (f"distribuidas a lo largo de **toda la noche** "
                                       f"({_n_first} primera mitad, {_n_second} segunda), indicando riesgo estructural sostenido.")
                else:
                    _patron = "datos insuficientes para detectar patrón temporal."

                # Riesgo contextual: eventos leves (C1/C2) con P alto
                _leves_alto = _ev_p[
                    (_ev_p["p_severe"] > _THOLD) &
                    (_ev_p["morphotype_curve"].isin(["C1","C2"]))
                ]
                _n_leves_alto = len(_leves_alto)
                if _n_leves_alto > 0 and _n_above > 0:
                    _pct_leves = _n_leves_alto / _n_above * 100
                    _contexto = (
                        f" **{_n_leves_alto} de esos eventos ({_pct_leves:.0f}%) son C1/C2 (leves) con probabilidad alta**: "
                        f"el organismo estaba en contexto fisiológico de riesgo aunque los eventos resultaron morfológicamente leves. "
                        f"Esto indica riesgo contextual que el ODI y el morfotipo aislado no capturan."
                    )
                else:
                    _contexto = ""

                # Fragmentación: C1/C2 dentro de 90s después de un evento C3/C4/C5
                _FRAG_WINDOW_S = 90
                _severos_ev = _ev_p[_ev_p["morphotype_curve"].isin(["C3","C4","C5"])].copy()
                _leves_ev   = _ev_p[_ev_p["morphotype_curve"].isin(["C1","C2"])].copy()
                _n_frag = 0
                if not _severos_ev.empty and not _leves_ev.empty:
                    for _, _sev_row in _severos_ev.iterrows():
                        _t_end_sev = _sev_row["ts_end"] if "ts_end" in _sev_row else _sev_row["ts_start"]
                        _t_window  = _t_end_sev + pd.Timedelta(seconds=_FRAG_WINDOW_S)
                        _candidates = _leves_ev[
                            (_leves_ev["ts_start"] > _sev_row["ts_start"]) &
                            (_leves_ev["ts_start"] <= _t_window)
                        ]
                        _n_frag += len(_candidates)
                if _n_frag > 0:
                    _fragm = (
                        f" Se detectaron **{_n_frag} evento/s C1/C2 dentro de los 90s posteriores a un evento severo**: "
                        f"podrían ser la fase de recuperación de un episodio más largo fragmentado por el algoritmo de detección "
                        f"(baseline local ya descendida). El ODI podría estar sobreestimando eventos independientes en esta noche."
                    )
                else:
                    _fragm = ""

                # Texto "en esta noche"
                if _n_above == 0:
                    _esta_noche = (
                        "ningún evento superó el umbral — noche de alta frecuencia de desaturaciones pero morfológicamente leve."
                    )
                else:
                    _esta_noche = (
                        f"**{_n_above} de {_n_total} eventos** superaron el umbral ({_pct_above:.0f}%), {_patron}"
                        f"{_contexto}{_fragm}"
                    )

                st.caption(
                    "El **color** indica el morfotipo real del evento (lo que fue); "
                    "la **altura** indica lo que el modelo predijo que sería, basado en el contexto fisiológico activo — no en el evento mismo. "
                    "Una barra azul o verde alta significa que el evento ocurrió en un contexto típico de eventos graves pero resultó leve.\n\n"
                    f"**En esta noche:** {_esta_noche}\n\n"
                    "**Para qué sirve:** identificar si el riesgo es episódico o sostenido, en qué momento concentra, "
                    "y si hay riesgo contextual oculto detrás de morfotipos aparentemente leves.\n\n"
                    "**Patrón clúster:** un grupo denso de barras altas en C1/C2 (azul/verde) concentradas en 10–20 min "
                    "no indica múltiples eventos independientes de riesgo oculto — es la firma predictiva de un episodio "
                    "prolongado que el algoritmo fragmentó. Todos los fragmentos comparten el mismo estado PAC activo, "
                    "por eso el modelo les asigna P(severo) alta. En ese caso la "
                    "hypoxic burden del período es más informativa que el conteo de eventos."
                )
            else:
                st.info("Probabilidades de evento severo no disponibles.")

            st.divider()
            with st.expander("Tabla completa de eventos", expanded=False):
                disp_cols = [
                    "ts_start","ts_end","duration_s","morphotype_curve",
                    "drop_pct","nadir_spo2","baseline_spo2",
                    "state_m_label","state_s_label","ird_event","p_severe","is_severe",
                ]
                disp_cols = [c for c in disp_cols if c in ev_df.columns]
                ev_show = ev_df[disp_cols].copy()
                ev_show["ts_start"] = ev_show["ts_start"].dt.strftime("%H:%M:%S")
                ev_show["ts_end"]   = ev_show["ts_end"].dt.strftime("%H:%M:%S")
                for col in ["drop_pct","nadir_spo2","baseline_spo2","ird_event","p_severe"]:
                    if col in ev_show:
                        ev_show[col] = ev_show[col].round(3)
                st.dataframe(ev_show, use_container_width=True, height=300)


# ══════════════════════════════
# TAB 3 — ESTADOS PAC
# Sub-tab A: Distribución S/M/L + fracciones
# Sub-tab B: Secuencia temporal + matriz de transición
# ══════════════════════════════
with tab3:
    _SCALE_META = {
        "S (30s)":   ("s", 7,  "S"),
        "M (5min)":  ("m", 5,  "M"),
        "L (30min)": ("l", 4,  "L"),
    }
    _SCALE_OPTIONS = ["S (30s)", "M (5min)", "L (30min)"]
    if "pac_scale" not in st.session_state:
        st.session_state["pac_scale"] = "M (5min)"
    _scale_sel = st.radio(
        "Escala temporal",
        _SCALE_OPTIONS,
        index=_SCALE_OPTIONS.index(st.session_state["pac_scale"]),
        key="pac_scale_radio",
        horizontal=True,
    )
    st.session_state["pac_scale"] = _scale_sel
    _scale_key, _n_states, _prefix = _SCALE_META.get(_scale_sel, ("m", 5, "M"))

    _PATH_STATES = {
        "S": {"S2","S4","S6"},
        "M": {"M1","M3"},
        "L": {"L0","L1"},
    }
    _path_set = _PATH_STATES.get(_prefix, set())

    st_sub_a, st_sub_b, st_sub_c, st_sub_d = st.tabs([
        "📊 Distribución",
        "📉 Fracción",
        "⏱ Secuencia",
        "🔀 Transición",
    ])

    # ── Sub-tab A: Distribución ─────────────────────────────────────────────
    with st_sub_a:
        col_s, col_m, col_l = st.columns(3, gap="medium")

        for col_ui, scale, label in [
            (col_s, "s", "S-scale · 30 s"),
            (col_m, "m", "M-scale · 5 min"),
            (col_l, "l", "L-scale · 30 min"),
        ]:
            win_df = state_win.get(scale, pd.DataFrame())
            if win_df.empty:
                col_ui.warning(f"{label}: sin datos")
                continue
            cnt = win_df["state_label"].value_counts().reset_index()
            cnt.columns = ["Estado", "Ventanas"]
            cnt["Fracción"] = (cnt["Ventanas"] / cnt["Ventanas"].sum() * 100).round(1)
            cnt = cnt.sort_values("Estado")

            _path_local = _PATH_STATES.get(label[0], set())
            cnt["Patológico"] = cnt["Estado"].isin(_path_local)
            cnt["Color"]      = cnt["Patológico"].map(
                {True: "#DC2626", False: "#4878CF"}
            )

            fig_bar = go.Figure(go.Bar(
                x=cnt["Estado"], y=cnt["Fracción"],
                marker_color=cnt["Color"],
                text=cnt["Fracción"].astype(str) + "%",
                textposition="outside",
                hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
            ))
            fig_bar.update_layout(
                height=260, margin=dict(t=40, b=20, l=10, r=10),
                title=dict(text=label, font=dict(size=13)),
                xaxis_title="", yaxis_title="",
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="#FAFBFD",
                yaxis=dict(range=[0, cnt["Fracción"].max() * 1.25], showticklabels=False),
            )
            fig_bar.update_yaxes(gridcolor="#EEF2F7")
            col_ui.plotly_chart(fig_bar, use_container_width=True)

        # Nota: el gráfico de fracción de tiempo se movió al sub-tab B
        # para evitar scroll en esta vista

    win_sel = state_win.get(_scale_key, pd.DataFrame())

    # ── Sub-tab B: Fracción de tiempo ───────────────────────────────────────
    with st_sub_b:
        if win_sel.empty:
            st.info(f"Sin datos para la escala {_scale_sel}.")
        else:
            _path_label = ", ".join(sorted(_path_set)) if _path_set else "—"
            st.markdown(
                f"##### Fracción de tiempo · {_prefix}-states "
                f"<span style='color:#DC2626;font-size:0.85em'>(patológicos: {_path_label})</span>",
                unsafe_allow_html=True,
            )
            vc      = win_sel["state_label"].dropna().value_counts(normalize=True)
            frac_df = pd.DataFrame({"Estado": vc.index, "Fracción": vc.values}).sort_values("Estado")
            frac_df["Patológico"] = frac_df["Estado"].isin(_path_set)
            frac_df["Color"]      = frac_df["Patológico"].map({True:"#DC2626",False:"#4878CF"})
            fig_frac = go.Figure(go.Bar(
                x=frac_df["Estado"], y=(frac_df["Fracción"]*100).round(1),
                marker_color=frac_df["Color"],
                text=(frac_df["Fracción"]*100).round(1).astype(str)+"%",
                textposition="outside",
                hovertemplate="%{x}: %{y:.1f}%<extra></extra>",
            ))
            fig_frac.update_layout(
                height=380, margin=dict(t=20, b=40, l=40, r=20),
                xaxis_title=f"Estado {_prefix}", yaxis_title="% ventanas",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFBFD",
                yaxis=dict(range=[0, frac_df["Fracción"].max()*130]),
            )
            fig_frac.update_yaxes(gridcolor="#EEF2F7")
            st.plotly_chart(fig_frac, use_container_width=True)
            st.caption(f"Porcentaje del tiempo nocturno que el sistema pasó en cada {_prefix}-state. Los estados en **rojo** (patológicos) se asocian a mayor concentración de morfotipos severos C4/C5 en el corpus de entrenamiento (V de Cramér S=0.356, M=0.231, L=0.196).")

    # ── Sub-tab C: Secuencia temporal ───────────────────────────────────────
    with st_sub_c:
        if win_sel.empty:
            st.info(f"Sin datos para la escala {_scale_sel}.")
        else:
            win_plot = win_sel.copy()
            win_plot["state_num"] = win_plot["state_label"].str.extract(r"(\d+)$").astype(float)
            fig_seq = go.Figure()
            fig_seq.add_trace(go.Scatter(
                x=win_plot["t_start"], y=win_plot["state_num"],
                mode="lines", line=dict(color="#CBD5E1", width=1.5, dash="dot"),
                showlegend=False, hoverinfo="skip",
            ))
            for lbl in sorted(win_plot["state_label"].dropna().unique()):
                sub = win_plot[win_plot["state_label"] == lbl]
                fig_seq.add_trace(go.Scatter(
                    x=sub["t_start"], y=sub["state_num"],
                    mode="markers", name=lbl,
                    marker=dict(color=STATE_M_COLORS.get(lbl, "#888"), size=9,
                                symbol="square", line=dict(color="white", width=1)),
                    hovertemplate=f"<b>{lbl}</b> · %{{x|%H:%M}}<extra></extra>",
                ))
            _tick_max = int(win_plot["state_num"].dropna().max()) + 1
            fig_seq.update_layout(
                height=480, margin=dict(t=30, b=30, l=50, r=20),
                title=f"Secuencia temporal · {_scale_sel}",
                xaxis_title="Hora", yaxis_title=f"Estado {_prefix}",
                yaxis=dict(tickvals=list(range(_tick_max)),
                           ticktext=[f"{_prefix}{i}" for i in range(_tick_max)],
                           gridcolor="#EEF2F7"),
                hovermode="x", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFBFD",
                legend=dict(orientation="h", y=1.08, font=dict(size=11)),
            )
            fig_seq.update_xaxes(showgrid=False)
            st.plotly_chart(fig_seq, use_container_width=True)
            st.caption(f"Evolución del {_prefix}-state activo a lo largo de la noche. Cada punto es una ventana de {'30s' if _prefix=='S' else '5min' if _prefix=='M' else '30min'}. Los saltos verticales frecuentes indican alta dinámica de transición entre estados fisiológicos.")

    # ── Sub-tab D: Matriz de transición ────────────────────────────────────
    with st_sub_d:
        if win_sel.empty:
            st.info(f"Sin datos para la escala {_scale_sel}.")
        else:
            st.markdown(f"##### Matriz de transición · {_prefix}-states")
            labels_seq = win_sel["state_label"].dropna().tolist()
            all_states = sorted(set(labels_seq))
            n_st       = len(all_states)
            idx_map    = {s: i for i, s in enumerate(all_states)}
            trans_mat  = np.zeros((n_st, n_st))
            for a, b in zip(labels_seq, labels_seq[1:]):
                trans_mat[idx_map[a], idx_map[b]] += 1
            row_sums   = trans_mat.sum(axis=1, keepdims=True)
            trans_norm = np.divide(trans_mat, row_sums, where=row_sums > 0)
            fig_heat = px.imshow(
                trans_norm, x=all_states, y=all_states,
                color_continuous_scale="Blues",
                labels=dict(x="Estado siguiente", y="Estado actual", color="P"),
                zmin=0, zmax=1, text_auto=".2f",
            )
            fig_heat.update_layout(
                height=480, margin=dict(t=20, b=40, l=60, r=20),
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_heat, use_container_width=True)
            st.caption(f"Probabilidad de transición entre {_prefix}-states consecutivos (filas = estado origen, columnas = estado destino). Valores altos en la diagonal principal indican **inercia**: el sistema tiende a permanecer en el mismo estado. Los atractores del corpus son S1, M0 y L3.")


# ══════════════════════════════
# TAB 4 — HISTORIA NOCTURNA
# Sub-tab A: Vista integrada (combo chart + coupling)
# Sub-tab B: Detalle (3 subplots + features NB06)
# ══════════════════════════════
with tab4:
    win_m = state_win.get("m", pd.DataFrame())

    h_sub_a, h_sub_b = st.tabs(["🗺 Vista integrada", "🔬 Detalle SpO₂ + features"])

    # ── Sub-tab A: Vista integrada ──────────────────────────────────────────
    with h_sub_a:
        # Coupling metrics strip
        ci_s  = night_feats.get("ci_s",  np.nan)
        ci_m  = night_feats.get("ci_m",  np.nan)
        ci_l  = night_feats.get("ci_l",  np.nan)
        entr  = night_feats.get("entropy_state_m", np.nan)
        n_tr  = night_feats.get("n_transitions_state_m", 0)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("CI_S (S-scale)", f"{ci_s:.3f}" if not np.isnan(ci_s) else "—",
            help=(
                "Fracción de eventos C4/C5 que ocurrieron en un estado S patológico (S2, S4, S6).\n\n"
                "Mide el acoplamiento a escala de **30 segundos** — el microentorno inmediato del evento.\n\n"
                "- **NaN** → sin eventos C4/C5 en la noche\n"
                "- **0.0–0.3** → bajo acoplamiento local\n"
                "- **0.3–0.7** → acoplamiento moderado\n"
                "- **0.7–1.0** → alto acoplamiento — eventos severos en contexto S patológico"
            ))
        m2.metric("CI_M (M-scale)", f"{ci_m:.3f}" if not np.isnan(ci_m) else "—",
            help=(
                "Fracción de eventos C4/C5 que ocurrieron en un estado M patológico (M1, M3).\n\n"
                "Mide el acoplamiento a escala de **5 minutos** — el contexto de regulación intermedia. "
                "Es el índice más correlacionado con carga hipóxica (ρ T90 = +0.744 para M1).\n\n"
                "- **NaN** → sin eventos C4/C5 en la noche\n"
                "- **0.0–0.3** → bajo acoplamiento — riesgo episódico\n"
                "- **0.3–0.7** → acoplamiento moderado\n"
                "- **0.7–1.0** → alto acoplamiento — riesgo estructural"
            ))
        m3.metric("CI_L (L-scale)", f"{ci_l:.3f}" if not np.isnan(ci_l) else "—",
            help=(
                "Fracción de eventos C4/C5 que ocurrieron en un estado L patológico (L0, L1).\n\n"
                "Mide el acoplamiento a escala de **30 minutos** — la arquitectura global de la noche.\n\n"
                "- **NaN** → sin eventos C4/C5 en la noche\n"
                "- **0.0–0.2** → arquitectura global protectora\n"
                "- **> 0.2** → arquitectura global comprometida — eventos severos en hipoxemia sostenida\n\n"
                "CI_M alto + CI_L bajo → riesgo episódico. CI_M alto + CI_L alto → riesgo estructural."
            ))
        m4.metric("ENTROPÍA M  (máx. 1.609)", f"{entr:.3f}" if not np.isnan(entr) else "—",
            help=(
                "Mide cuán distribuido está el tiempo de la noche entre los 5 estados M (K=5).\n\n"
                "**Fórmula:** H = −Σ pᵢ · ln(pᵢ) sobre M0–M4\n\n"
                "**Máximo teórico:** ln(5) = 1.609 → distribución perfectamente uniforme (20% en cada estado)\n\n"
                "- **< 0.8** → Régimen sostenido — uno o dos estados dominan la noche\n"
                "- **0.8–1.4** → Variabilidad moderada — distribución heterogénea pero con estructura\n"
                "- **> 1.4** → Alta variabilidad — el sistema transitó por todos los estados sin dominancia clara\n\n"
                "Entropía alta **no implica** mayor riesgo; depende de qué estados dominan. "
                "Leer junto con las fracciones de M1/M3 (patológicos) en la pestaña Estados PAC."
            ))
        _n_win_m = len(win_m) if not win_m.empty else 0
        _pct_tr  = (n_tr / (_n_win_m - 1) * 100) if _n_win_m > 1 else 0
        _tr_label = (
            "rígida"      if _pct_tr < 30  else
            "moderada"    if _pct_tr < 55  else
            "fragmentada" if _pct_tr < 75  else
            "alta fragm."
        )
        m5.metric(
            f"TRANSICIONES M  (total: {_n_win_m})",
            f"{n_tr:.0f}  ({_pct_tr:.0f}% · {_tr_label})",
            help=(
                "Porcentaje de cambios de estado M sobre N−1 pasos posibles.\n\n"
                "- **< 30%** → Rígida — sistema sostenido en pocos estados\n"
                "- **30–55%** → Moderada — bloques organizados\n"
                "- **55–75%** → Fragmentada — switching frecuente\n"
                "- **> 75%** → Alta fragmentación — próxima al azar (K=5 ~80%)"
            )
        )

        # (registro corto ya cubierto por banner global)

        # Info card cuando ci_m/ci_l no son calculables por ausencia de eventos severos
        _ci_nan = np.isnan(ci_m) or np.isnan(ci_l)
        if _ci_nan:
            _n_sev_check = n_severe  # from header (C4+C5 count)
            if _n_sev_check == 0:
                _ci_msg = (
                    "**Sin eventos C4/C5 en esta noche** — los índices de acoplamiento "
                    "(ci_m, ci_l) requieren al menos un evento severo para calcularse. "
                    "Esto es una **característica de esta noche** (baja severidad morfológica), "
                    "no un error del sistema. Un ci no calculable es en sí mismo información: "
                    "indica que los eventos de la noche no alcanzaron morfotipos de riesgo."
                )
            else:
                _ci_msg = (
                    f"**Índice de acoplamiento no calculable** — se detectó/n {_n_sev_check} "
                    "evento/s C4/C5, pero su timestamp no pudo mapearse a una ventana de "
                    "estado M o L (posiblemente en el borde final del registro). "
                    "Esto es una **característica de esta noche**, no un error del sistema."
                )
            _alert(_ci_msg, "info")

        # ── Alerta de discordancia Risk Score vs acoplamiento ──────────────────
        _disc_msg = None
        if not np.isnan(ci_m) and risk_score < 61:
            if ci_m >= 0.7 and ci_l >= 0.5:
                _disc_msg = (
                    f"**Discordancia estructural:** Risk Score {risk_score:.0f} ({risk_label}), "
                    f"pero CI_M = {ci_m:.3f} y CI_L = {ci_l:.3f} — todos o casi todos los eventos "
                    "severos ocurrieron en estados M y L patológicos. "
                    "El score puede estar **subestimando la carga estructural** de esta noche: "
                    "los eventos C4/C5 no fueron aislados, sino sistemáticamente acoplados al peor "
                    "contexto fisiológico disponible. Revisar distribución de morfotipos y trayectoria nocturna."
                )
            elif ci_m >= 0.7:
                _disc_msg = (
                    f"**Discordancia de acoplamiento medio:** Risk Score {risk_score:.0f} ({risk_label}), "
                    f"pero CI_M = {ci_m:.3f} — los eventos severos se concentraron en estados M patológicos "
                    "(M1/M3). El score refleja baja frecuencia de C4/C5, pero su contexto fisiológico "
                    "es de alto riesgo. Considerar la lectura conjunta de CI_M y trayectoria nocturna."
                )
        if _disc_msg:
            _alert(_disc_msg)

        st.divider()
        st.markdown("##### SpO₂ + bandas de estado M + EDOs por morfotipo")
        st.caption("Fondo = estado M activo (5 min) · color de evento = morfotipo C1–C5 · ▼ = severo")

        fig_combo = go.Figure()

        # Bandas M-state
        _mstate_alpha = {
            "M0":"rgba(72,120,207,0.16)",  "M1":"rgba(106,204,101,0.16)",
            "M2":"rgba(214,95,95,0.16)",   "M3":"rgba(180,124,199,0.16)",
            "M4":"rgba(133,193,233,0.16)", "M5":"rgba(243,156,18,0.16)",
            "M6":"rgba(26,188,156,0.16)",  "M7":"rgba(231,76,60,0.20)",
        }
        if not win_m.empty:
            for _, row in win_m.iterrows():
                lbl   = str(row.get("state_label", ""))
                color = _mstate_alpha.get(lbl, "rgba(150,150,150,0.10)")
                fig_combo.add_vrect(
                    x0=row["t_start"], x1=row["t_end"],
                    fillcolor=color, line_width=0, layer="below",
                )

        # SpO₂
        step   = max(1, len(sig) // 4000)
        sig_s  = sig.iloc[::step]
        fig_combo.add_trace(go.Scatter(
            x=sig_s["timestamp"], y=sig_s["spo2_clean"],
            mode="lines", name="SpO₂",
            line=dict(color="#1E3A5F", width=1.5),
            hovertemplate="%{x|%H:%M:%S}  SpO₂=%{y:.0f}%<extra></extra>",
        ))

        # T90 line
        fig_combo.add_hline(y=90, line_dash="dot", line_color="#DC2626",
                            annotation_text="90%", annotation_position="right",
                            annotation_font_color="#DC2626")

        # EDOs coloreados por morfotipo
        if not ev_df.empty:
            for _, ev in ev_df.iterrows():
                mc      = MORPH_COLORS.get(str(ev.get("morphotype_curve","")), "#888888")
                opacity = 0.55 if str(ev.get("morphotype_curve","")) in ["C4","C5"] else 0.25
                fig_combo.add_vrect(
                    x0=ev["ts_start"], x1=ev["ts_end"],
                    fillcolor=_hex_to_rgba(mc, opacity),
                    line_width=0.5, line_color=mc, layer="above",
                )
            # Severos marker
            sev = ev_df[ev_df.get("is_severe", pd.Series(dtype=float)) == 1] \
                  if "is_severe" in ev_df.columns else pd.DataFrame()
            if not sev.empty:
                nadir_t = sev["ts_start"] + pd.to_timedelta(sev["duration_s"] / 2, unit="s")
                fig_combo.add_trace(go.Scatter(
                    x=nadir_t, y=sev["nadir_spo2"],
                    mode="markers", name="Severo C4/C5",
                    marker=dict(color="#9B1C1C", size=10, symbol="triangle-down",
                                line=dict(color="white", width=1)),
                    hovertemplate="Severo · nadir=%{y:.0f}%<extra></extra>",
                ))

        # Leyenda M-states
        if not win_m.empty:
            for lbl, col in STATE_M_COLORS.items():
                if lbl in win_m["state_label"].values:
                    fig_combo.add_trace(go.Scatter(
                        x=[None], y=[None], mode="markers",
                        marker=dict(color=col, size=11, symbol="square"),
                        name=lbl, showlegend=True,
                    ))

        fig_combo.update_layout(
            height=380, margin=dict(t=10, b=40, l=50, r=80),
            xaxis_title="Hora", yaxis_title="SpO₂ (%)",
            yaxis=dict(range=[75, 102], gridcolor="#EEF2F7"),
            hovermode="x unified",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFBFD",
            legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=11)),
        )
        fig_combo.update_xaxes(showgrid=False)
        st.plotly_chart(fig_combo, use_container_width=True)
        st.caption("**Fondo**: estado M activo en cada ventana de 5 min (color por estado). **Línea azul**: señal SpO₂. **Regiones sombreadas**: EDOs coloreados por morfotipo (mayor opacidad = C4/C5). **▼**: eventos severos en su nadir. La co-ocurrencia entre bandas de estados patológicos y regiones C4/C5 refleja el acoplamiento morfotipo–estado.")

    # ── Sub-tab B: Detalle (dos sub-tabs internos) ──────────────────────────
    with h_sub_b:
        det_sub_1, det_sub_2 = st.tabs(["📈 SpO₂ / Estado M / P(severo)", "🧮 Features + Trayectoria"])
        with det_sub_1:
            st.markdown("##### SpO₂ / Estado M / P(severo) — eje temporal compartido")

        with det_sub_1:
            fig_hist = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                row_heights=[0.50, 0.28, 0.22],
                vertical_spacing=0.04,
                subplot_titles=["SpO₂ (%)", "Estado M activo", "P(evento severo)"],
            )

            # SpO₂
            step    = max(1, len(sig) // 3000)
            sig_sub = sig.iloc[::step]
            fig_hist.add_trace(go.Scatter(
                x=sig_sub["timestamp"], y=sig_sub["spo2_clean"],
                mode="lines", name="SpO₂",
                line=dict(color="#1E3A5F", width=1.2),
                hovertemplate="%{x|%H:%M:%S}  SpO₂=%{y:.0f}%<extra></extra>",
            ), row=1, col=1)

            if not ev_df.empty:
                sev_ev = ev_df[ev_df.get("is_severe", pd.Series(dtype=float)) == 1] \
                         if "is_severe" in ev_df.columns else pd.DataFrame()
                if not sev_ev.empty:
                    fig_hist.add_trace(go.Scatter(
                        x=sev_ev["ts_start"], y=sev_ev["nadir_spo2"],
                        mode="markers", name="Severo",
                        marker=dict(color="#DC2626", size=8, symbol="triangle-down"),
                        hovertemplate="%{x|%H:%M:%S}  nadir=%{y:.0f}%<extra></extra>",
                    ), row=1, col=1)

            fig_hist.add_hline(y=90, line_dash="dash", line_color="#DC2626",
                               opacity=0.5, row=1, col=1)

            # Estado M
            if not win_m.empty:
                win_m_num = win_m.copy()
                win_m_num["state_num"] = win_m_num["state_label"].str.extract(r"(\d+)$").astype(float)
                colors_m = win_m_num["state_label"].map(lambda x: STATE_M_COLORS.get(x, "#888"))
                fig_hist.add_trace(go.Scatter(
                    x=win_m_num["t_start"], y=win_m_num["state_num"],
                    mode="lines+markers", name="Estado M",
                    line=dict(color="#CBD5E1", width=1),
                    marker=dict(color=colors_m, size=7, line=dict(color="white", width=0.5)),
                    hovertemplate="%{x|%H:%M}  %{text}<extra></extra>",
                    text=win_m_num["state_label"],
                ), row=2, col=1)

            # P(severo)
            if not ev_df.empty and "p_severe" in ev_df.columns:
                ev_valid = ev_df.dropna(subset=["p_severe"])
                fig_hist.add_trace(go.Bar(
                    x=ev_valid["ts_start"], y=ev_valid["p_severe"],
                    name="P(severo)",
                    marker_color=ev_valid["morphotype_curve"].map(MORPH_COLORS).fillna("#888"),
                    hovertemplate="%{x|%H:%M:%S}  P=%{y:.3f}<extra></extra>",
                ), row=3, col=1)
                fig_hist.add_hline(y=0.386, line_dash="dash", line_color="#DC2626",
                                   opacity=0.6, row=3, col=1)

            fig_hist.update_layout(
                height=500, margin=dict(t=40, b=20, l=60, r=20),
                showlegend=True, hovermode="x unified",
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFBFD",
                legend=dict(orientation="h", y=1.04),
            )
            fig_hist.update_yaxes(range=[60,102], title_text="SpO₂ (%)",
                                  gridcolor="#EEF2F7", row=1, col=1)
            fig_hist.update_yaxes(
                title_text="Estado M",
                tickvals=list(range(8)),
                ticktext=[f"M{i}" for i in range(8)],
                gridcolor="#EEF2F7", row=2, col=1,
            )
            fig_hist.update_yaxes(title_text="P(severo)", range=[0,1],
                                  gridcolor="#EEF2F7", row=3, col=1)
            st.plotly_chart(fig_hist, use_container_width=True)

        with det_sub_2:
            st.markdown("##### Perfil de features nocturnas NB06")
            col_feats, col_traj = st.columns([2, 1], gap="large")

            with col_feats:
                feat_items = {
                    "ci_s":     night_feats.get("ci_s", np.nan),
                    "ci_m":     night_feats.get("ci_m", np.nan),
                    "ci_l":     night_feats.get("ci_l", np.nan),
                    "pct_severe": night_feats.get("pct_severe", 0),
                    "mean_ari": night_feats.get("mean_ari", np.nan),
                    "entropy_m":  night_feats.get("entropy_state_m", np.nan),
                }
                feat_df = pd.DataFrame([
                    {"Feature": k, "Valor": round(v, 4)}
                    for k, v in feat_items.items() if not (isinstance(v, float) and np.isnan(v))
                ])
                fig_feat = px.bar(
                    feat_df, x="Valor", y="Feature", orientation="h",
                    color="Valor", color_continuous_scale="RdYlGn_r",
                    labels={"Valor": "", "Feature": ""},
                )
                fig_feat.update_layout(
                    height=240, margin=dict(t=10, b=20, l=100, r=20),
                    coloraxis_showscale=False,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FAFBFD",
                )
                fig_feat.update_xaxes(gridcolor="#EEF2F7")
                st.plotly_chart(fig_feat, use_container_width=True)

            with col_traj:
                traj_c = TRAJ_COLORS.get(traj_name, "#888")
                st.markdown(f"""
<div style="padding:18px;border-radius:12px;background:{traj_c}12;
            border:1.5px solid {traj_c}40;text-align:center;margin-top:8px">
  <div style="font-size:0.7rem;color:#94A3B8;font-weight:500;text-transform:uppercase;
              letter-spacing:0.05em">Trayectoria nocturna</div>
  <div style="font-size:1.1rem;font-weight:700;color:{traj_c};margin:6px 0">
    {traj_name}
  </div>
  <div style="font-size:0.75rem;color:#94A3B8;line-height:1.7">
    0 = Estable-Protector<br>1 = Carga Intermedia<br>2 = Carga Hipóxica Alta
  </div>
</div>
<div style="margin-top:10px;padding:12px 14px;border-radius:10px;
            background:#F8FAFC;border:1px solid #E2E8F0;font-size:0.82rem;color:#475569">
  <b>Risk Score:</b>&nbsp;
  <span style="color:{RISK_COLORS.get(risk_label,'#888')};font-weight:700">
    {risk_score:.0f} ({risk_label})</span><br>
  <b>P(noche riesgo):</b> {p_night:.3f}<br>
  <b>P̄(severo):</b> {f"{p_sev_mean:.3f}" if not np.isnan(p_sev_mean) else "—"}<br>
  <b>Trans. M:</b> {night_feats.get("n_transitions_state_m",0):.0f}
</div>
""", unsafe_allow_html=True)


# ══════════════════════════════
# TAB 5 — INFORME IA
# ══════════════════════════════
with tab5:
    st.markdown("#### Informe clínico generado por IA")
    st.caption("Generá un informe narrativo personalizado usando LM Studio (local) o Claude API.")

    col_back, col_model = st.columns([3, 2], gap="medium")

    with col_back:
        backend     = st.radio(
            "Motor de IA",
            ["🖥️ LM Studio (local)", "☁️ Claude API (Anthropic)"],
            horizontal=True,
        )
    use_lmstudio = backend.startswith("🖥️")

    col_cfg1, col_cfg2 = st.columns([3, 2], gap="medium")

    if use_lmstudio:
        with col_cfg1:
            lm_url = st.text_input("LM Studio URL", value="http://localhost:1234/v1")
        with col_cfg2:
            lm_model = st.text_input("Nombre del modelo", value="local-model",
                                     placeholder="ej: llama-3-8b-instruct")
        api_key = "lm-studio"
        ready   = bool(lm_url)
    else:
        with col_cfg1:
            api_key = st.text_input("Anthropic API Key", type="password",
                                    placeholder="sk-ant-…",
                                    help="No se almacena. Obtené una en console.anthropic.com")
        with col_cfg2:
            claude_model = st.selectbox(
                "Modelo Claude",
                ["claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
                help="Sonnet: mejor calidad. Haiku: más rápido.",
            )
        ready = bool(api_key)

    # ── Tipo de informe ──────────────────────────────────────────────────────
    st.divider()
    report_type = st.radio(
        "Tipo de informe",
        ["🩺 Informe para el especialista", "🧑 Resumen para el paciente"],
        horizontal=True,
    )
    _for_specialist = report_type.startswith("🩺")

    extra_instructions = st.text_area(
        "Instrucciones adicionales *(opcional)*",
        height=80,
        placeholder=(
            "Ej: Agregá una conclusión en negrita al final de cada sección.\n"
            "Ej: Enfatizá las recomendaciones terapéuticas concretas."
            if _for_specialist else
            "Ej: Usá un tono muy tranquilizador.\nEj: Incluí consejos de higiene del sueño."
        ),
    )

    # ── Warnings pre-generación ──────────────────────────────────────────────
    _informe_warnings = []
    if _SHORT_NIGHT_GLOBAL:
        _informe_warnings.append(
            f"**Registro corto ({duration_s/3600:.1f} h):** los datos provienen de una noche incompleta. "
            f"El informe generado reflejará esta limitación — interpretar con cautela."
        )
    _n_sev_inf = int(ev_df["morphotype_curve"].isin(["C4","C5"]).sum()) if "morphotype_curve" in ev_df.columns else 0
    if risk_score >= 40 and _n_sev_inf == 0:
        _informe_warnings.append(
            f"**RS {risk_score:.0f} sin eventos C4/C5:** el Risk Score puede estar sobreestimando el riesgo morfológico."
        )
    if not np.isnan(ci_m) and ci_m >= 0.7 and risk_score < 61:
        _informe_warnings.append(
            f"**Discordancia CI_M/RS:** CI_M = {ci_m:.3f} alto con RS {risk_score:.0f} bajo — el score puede subestimar la carga estructural."
        )
    if _informe_warnings:
        _alert(
            "**Limitaciones activas que aparecerán en el informe:**\n\n" +
            "\n\n".join(f"- {w}" for w in _informe_warnings),
        )

    generate_btn = st.button(
        f"🧠 Generar {'informe médico' if _for_specialist else 'resumen para el paciente'}",
        disabled=not ready,
        use_container_width=True,
        type="primary",
    )

    if not ready:
        if use_lmstudio:
            st.info("Asegurate de tener LM Studio corriendo con un modelo cargado.")
        else:
            st.info("Ingresá tu API key de Anthropic. Obtená una en [console.anthropic.com](https://console.anthropic.com)")

    if generate_btn and ready:
        odi          = n_events / (duration_s / 3600) if duration_s > 0 else 0.0
        morph_counts = {}
        if not ev_df.empty and "morphotype_curve" in ev_df.columns:
            morph_counts = ev_df["morphotype_curve"].value_counts().to_dict()
        frac_m = {
            k.replace("frac_state_m_", ""): f"{v*100:.1f}%"
            for k, v in night_feats.items() if k.startswith("frac_state_m_")
        }
        spo2_vals = sig["spo2_clean"].dropna()
        spo2_mean = float(spo2_vals.mean()) if len(spo2_vals) > 0 else float("nan")
        spo2_min  = float(spo2_vals.min())  if len(spo2_vals) > 0 else float("nan")
        t90_pct   = float((spo2_vals < 90).mean() * 100) if len(spo2_vals) > 0 else float("nan")
        exam_date = meta.get("start_time", "")
        date_str2 = pd.Timestamp(exam_date).strftime("%d/%m/%Y") if exam_date else "—"

        # Disclaimer dinámico para el informe
        _disc_lines = []
        if _SHORT_NIGHT_GLOBAL:
            _disc_lines.append(f"- REGISTRO CORTO ({duration_s/3600:.1f} h < 4 h recomendadas): resultados de estados PAC y coupling indices menos estables. ODI calculado sobre ventana reducida.")
        if risk_score >= 40 and _n_sev_inf == 0:
            _disc_lines.append(f"- RS {risk_score:.0f} SIN EVENTOS C4/C5: el Risk Score refleja contexto fisiológico (estados PAC), no morfotipos severos. Puede estar sobreestimando.")
        if not np.isnan(ci_m) and ci_m >= 0.7 and risk_score < 61:
            _disc_lines.append(f"- DISCORDANCIA CI_M/RS: CI_M = {ci_m:.3f} con RS {risk_score:.0f} — el score puede subestimar la carga estructural de acoplamiento.")
        _disclaimer_block = ""
        if _disc_lines:
            _disclaimer_block = "\n## ⚠ LIMITACIONES Y ADVERTENCIAS\n" + "\n".join(_disc_lines) + "\nMENCIONAR ESTAS LIMITACIONES EXPLÍCITAMENTE EN EL INFORME.\n"

        _data_block = f"""
## DATOS DEL ESTUDIO

**Identificación:**
- Paciente ID: {meta.get('user_id','—')}
- Examen ID: {meta.get('exam_id','—')}
- Fecha: {date_str2}
- Duración del registro: {_fmt_duration(duration_s)}

**Score de Riesgo PAC:**
- Risk Score: {risk_score:.1f} / 100 → **{risk_label}**
- P(noche alto riesgo): {p_night:.3f}
- P(evento severo, promedio): {f"{p_sev_mean:.3f}" if not np.isnan(p_sev_mean) else "sin datos"}

**Eventos de Desaturación (EDOs):**
- Total detectados: {n_events}
- ODI estimado: {odi:.1f} eventos/hora
- Severos C4/C5: {n_severe} ({f"{n_severe/n_events*100:.1f}" if n_events>0 else "0"}%)
- Distribución morfotipos: {', '.join(f"{k}={v}" for k,v in sorted(morph_counts.items()))}

**Señal SpO₂:**
- Media nocturna: {spo2_mean:.1f}%
- Mínimo registrado: {spo2_min:.1f}%
- T90 (% tiempo bajo 90%): {t90_pct:.1f}%

**Estados PAC (M-scale, ventanas 5 min):**
- Distribución: {', '.join(f"{k}={v}" for k,v in sorted(frac_m.items())) if frac_m else "sin datos"}
- Trayectoria nocturna: {result.get('traj_name','—')}
- Entropía M-states: {night_feats.get('entropy_state_m',float('nan')):.3f}
- Número de transiciones M: {night_feats.get('n_transitions_state_m',0):.0f}

**Índices de Acoplamiento EDO-Estado:**
- ci_s (S-scale, 30s): {night_feats.get('ci_s',float('nan')):.3f}
- ci_m (M-scale, 5min): {night_feats.get('ci_m',float('nan')):.3f}
- ci_l (L-scale, 30min): {night_feats.get('ci_l',float('nan')):.3f}
- coupling_index (global): {night_feats.get('coupling_index',float('nan')):.3f}

**Contexto del modelo:**
- Entrenado con n=8 pacientes (Gold dataset, LOPO-CV)
- AUC evento severo: 0.878 | AUC clasificación nocturna: 0.874
- Trayectorias: 0=Estable-Protector, 1=Carga Intermedia, 2=Carga Hipóxica Alta
- Estados M patológicos (entrenamiento): M1, M3
{_disclaimer_block}"""

        if _for_specialist:
            prompt = f"""Sos un asistente médico especializado en medicina del sueño y análisis de oximetría nocturna.
Generá un INFORME MÉDICO-TÉCNICO en español, dirigido al médico especialista.

Incluí las siguientes secciones:
1. Carga de eventos: interpretación de EDOs, ODI, distribución de morfotipos C1–C5
2. Estados PAC: distribución M-scale, trayectoria nocturna, entropía, transiciones
3. Acoplamiento EDO–Estado: ci_s, ci_m, ci_l y su significado fisiopatológico
4. Risk Score PAC: interpretación de P_night y P_severe
5. Conclusión clínica y recomendaciones (estudios complementarios, seguimiento)
{("6. Limitaciones del estudio: mencionar EXPLÍCITAMENTE las advertencias indicadas en la sección ⚠ LIMITACIONES Y ADVERTENCIAS del bloque de datos." if _disc_lines else "")}

Estilo: terminología clínica. Al final de cada sección, una oración de cierre en **negrita** que resuma el hallazgo en lenguaje de guardia.
{f"Instrucciones adicionales: {extra_instructions}" if extra_instructions.strip() else ""}

{_data_block}"""
        else:
            prompt = f"""Sos un asistente de salud que ayuda a explicar estudios de sueño.
Escribí un RESUMEN PARA EL PACIENTE en español, en lenguaje simple y accesible, sin jerga técnica.

Incluí:
1. Qué pasó durante su noche de sueño (en términos simples)
2. Qué tan graves fueron los episodios de baja de oxígeno
3. Qué significa su puntaje de riesgo ({risk_score:.0f}/100 — {risk_label})
4. Próximos pasos recomendados (tono amable y tranquilizador)
{("5. Una nota breve y clara (en lenguaje simple, sin alarmar) sobre por qué los resultados de esta noche son orientativos y conviene consultarlos con el médico." if _disc_lines else "")}

Evitá términos técnicos. Si los usás, explicalos con palabras simples.
{f"Instrucciones adicionales: {extra_instructions}" if extra_instructions.strip() else ""}

{_data_block}"""

        try:
            if use_lmstudio:
                # Llamada directa via httpx (evita conflicto openai/pydantic/typing_extensions)
                import httpx, json as _json
                _payload = {
                    "model": lm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 4000,
                    "temperature": 0.3,
                }
                with st.spinner(f"🖥️ Generando con LM Studio ({lm_model}) — puede tardar 2-4 min con modelos grandes…"):
                    _resp = httpx.post(
                        f"{lm_url.rstrip('/')}/chat/completions",
                        json=_payload,
                        headers={"Authorization": "Bearer lm-studio",
                                 "Content-Type": "application/json"},
                        timeout=600.0,
                    )
                    _resp.raise_for_status()
                report_text = _resp.json()["choices"][0]["message"]["content"]
            else:
                import anthropic as _ant
                client = _ant.Anthropic(api_key=api_key)
                with st.spinner("☁️ Generando con Claude…"):
                    response = client.messages.create(
                        model=claude_model,
                        max_tokens=2500,
                        messages=[{"role":"user","content":prompt}],
                    )
                report_text = response.content[0].text

            st.session_state["last_report"]      = report_text
            st.session_state["last_report_type"] = "especialista" if _for_specialist else "paciente"
            st.session_state["last_report_meta"] = {
                "user_id":    meta.get("user_id","—"),
                "exam_id":    meta.get("exam_id","—"),
                "date":       date_str2,
                "risk_score": risk_score,
                "risk_label": risk_label,
            }
            # Forzar re-render para que el sidebar muestre el tipo correcto de inmediato
            st.rerun()

        except Exception as e:
            st.error(f"❌ Error generando el informe: {e}")
            if use_lmstudio:
                st.warning("Verificá que LM Studio esté corriendo y tenga un modelo cargado.")
            st.exception(e)

    if "last_report" in st.session_state:
        rpt       = st.session_state["last_report"]
        rpt_meta  = st.session_state.get("last_report_meta", {})
        rpt_type  = st.session_state.get("last_report_type", "especialista")
        rpt_label = "Informe médico" if rpt_type == "especialista" else "Resumen para el paciente"

        # Ancla para el scroll
        st.markdown('<div id="pac-report-anchor"></div>', unsafe_allow_html=True)

        # Scroll automático al título del informe
        import streamlit.components.v1 as _components
        _components.html("""
<script>
  (function() {
    var attempts = 0;
    function scrollToReport() {
      var anchor = window.parent.document.getElementById('pac-report-anchor');
      if (anchor) {
        anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
      } else if (attempts < 10) {
        attempts++;
        setTimeout(scrollToReport, 200);
      }
    }
    setTimeout(scrollToReport, 300);
  })();
</script>
""", height=0)

        st.divider()
        st.markdown(
            f"### {rpt_label} — Paciente {rpt_meta.get('user_id','?')} · "
            f"Examen {rpt_meta.get('exam_id','?')} · {rpt_meta.get('date','')}"
        )
        st.markdown(rpt)
        st.divider()

        def _build_docx_bytes(text: str, meta_info: dict) -> bytes:
            import io
            try:
                from docx import Document as DocxDocument
                doc = DocxDocument()
                doc.add_heading(
                    f"Informe PAC — Paciente {meta_info.get('user_id','?')} · "
                    f"Examen {meta_info.get('exam_id','?')}", level=1
                )
                doc.add_paragraph(
                    f"Fecha: {meta_info.get('date','—')} | "
                    f"Risk Score: {meta_info.get('risk_score','—')} ({meta_info.get('risk_label','—')})"
                )
                doc.add_paragraph("")
                for line in text.split("\n"):
                    line = line.strip()
                    if not line:
                        doc.add_paragraph("")
                    elif line.startswith("## "):
                        doc.add_heading(line[3:], level=2)
                    elif line.startswith("### "):
                        doc.add_heading(line[4:], level=3)
                    elif line.startswith("**") and line.endswith("**"):
                        p = doc.add_paragraph()
                        p.add_run(line.strip("*")).bold = True
                    elif line.startswith("- "):
                        doc.add_paragraph(line[2:], style="List Bullet")
                    else:
                        doc.add_paragraph(line)
                buf = io.BytesIO()
                doc.save(buf)
                return buf.getvalue()
            except ImportError:
                return text.encode("utf-8")

        docx_bytes = _build_docx_bytes(rpt, rpt_meta)
        _tipo_str  = "medico" if rpt_type == "especialista" else "paciente"
        fname = (
            f"informe_{_tipo_str}_pac_{rpt_meta.get('exam_id','?')}_"
            f"{rpt_meta.get('date','').replace('/','')}.docx"
        )
        st.download_button(
            label=f"⬇️ Descargar {'informe médico' if rpt_type == 'especialista' else 'resumen para el paciente'} (.docx)",
            data=docx_bytes,
            file_name=fname,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
