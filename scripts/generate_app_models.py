"""
generate_app_models.py
======================
Genera los modelos que necesita app/pipeline.py para inferencia:
  - models/nb06_config.json        feature lists + thresholds
  - models/nb06_event_lgbm.pkl     LightGBM binario (is_severe a nivel evento)
  - models/nb06_night_lr.pkl       Logistic Regression (risk_tier a nivel noche)

Entrenamiento fiel al protocolo de NB07_prediccion.ipynb.

Uso:
    cd ~/Proyectos/PAC_v2
    PYTHONPATH=src python3 scripts/generate_app_models.py
"""

import json
import pickle
import re
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler

warnings.filterwarnings("ignore")

ROOT      = Path(__file__).resolve().parent.parent
GOLD      = ROOT / "gold"
MODELS    = ROOT / "models"

# ── Config ────────────────────────────────────────────────────────────────────

EVENT_FEATURES = [
    "state_m_enc", "state_s_enc", "state_l_enc",
    "pre_state_m_enc", "pre_eq_current",
    "frac_path_m_30ev", "recent_morph_mean",
    "ci_so_far", "n_severe_so_far", "event_position",
]

NIGHT_FEATURES = [
    "ci_s", "ci_m", "ci_l", "coupling_index",
    "frac_state_m_M0", "frac_state_m_M1", "frac_state_m_M2", "frac_state_m_M3",
    "frac_state_m_M4", "frac_state_m_M5", "frac_state_m_M6", "frac_state_m_M7",
    "entropy_state_m", "pct_severe", "mean_ari", "night_traj_cluster",
]

TRAJ_FEATURES = [
    "frac_state_m_M1", "frac_state_m_M3", "mean_ari",
    "n_transitions_state_m", "entropy_state_m",
    "frac_state_l_L0", "frac_state_s_S4",
]

PATH_M = [1, 3]  # M1, M3 — canonical pathological M states (PAC_v3, NB04)

CONFIG = {
    "EVENT_FEATURES":        EVENT_FEATURES,
    "NIGHT_FEATURES":        NIGHT_FEATURES,
    "traj_features":         TRAJ_FEATURES,
    "pathological_states_m": PATH_M,
    "event_threshold":       0.386,
    "night_threshold":       0.303,
    "risk_w_event":          0.4,
    "risk_w_night":          0.6,
    "risk_low_max":          30,
    "risk_high_min":         60,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def encode_state_label(label):
    if pd.isna(label):
        return np.nan
    m = re.search(r"(\d+)$", str(label))
    return float(m.group(1)) if m else np.nan


def rolling_event_features(group: pd.DataFrame, window: int = 30) -> pd.DataFrame:
    """Replicate NB07 Cell-8 rolling_event_features()."""
    path_m_set = set(PATH_M)
    n   = len(group)
    idx = group.index

    is_sev    = group["is_severe"].values.astype(bool)
    morph_n   = group["morph_num"].values
    state_m   = group["state_m_enc"].values
    in_path_m = np.array([1.0 if (not np.isnan(s) and int(s) in path_m_set) else 0.0
                          for s in state_m])

    frac_path_prev = np.full(n, np.nan)
    recent_morph   = np.full(n, np.nan)
    ci_so_far      = np.full(n, np.nan)
    n_severe_sofar = np.full(n, np.nan)
    event_position = np.arange(n) / max(n - 1, 1)

    cumul_severe = 0
    cumul_total  = 0
    for i in range(n):
        if cumul_total > 0:
            ci_so_far[i] = cumul_severe / cumul_total
        n_severe_sofar[i] = float(cumul_severe)
        lo = max(0, i - window)
        if i > lo:
            frac_path_prev[i] = in_path_m[lo:i].mean()
            recent_morph[i]   = float(np.nanmean(morph_n[lo:i]))
        if is_sev[i]:
            cumul_severe += 1
        cumul_total += 1

    return pd.DataFrame({
        "frac_path_m_30ev": frac_path_prev,
        "recent_morph_mean": recent_morph,
        "ci_so_far": ci_so_far,
        "n_severe_so_far": n_severe_sofar,
        "event_position": event_position,
    }, index=idx)


# ── Step 1: nb06_config.json ──────────────────────────────────────────────────

print("=" * 60)
print("Step 1 — Escribir nb06_config.json")
print("=" * 60)

config_path = MODELS / "nb06_config.json"
with open(config_path, "w") as f:
    json.dump(CONFIG, f, indent=2)
print(f"  ✓ {config_path}")


# ── Step 2: Cargar Gold y preparar dataset de eventos ────────────────────────

print()
print("=" * 60)
print("Step 2 — Preparar dataset de eventos (event_states_multiscale)")
print("=" * 60)

esm = pd.read_parquet(GOLD / "event_states_multiscale.parquet")
print(f"  Cargado: {esm.shape}")

# Filtrar cohort que tiene aasm_sev asignado
esm = esm[esm["aasm_sev"].notna()].copy()
print(f"  Filtrado aasm_sev notna: {esm.shape}")

# Encode estados
esm["state_m_enc"] = esm["state_m_label"].apply(encode_state_label)
esm["state_s_enc"] = esm["state_s_label"].apply(encode_state_label)
esm["state_l_enc"] = esm["state_l_label"].apply(encode_state_label)

# pre_state_m (estado M del evento anterior en la noche)
esm["pre_state_m"] = esm.groupby("night_record_id")["state_m_label"].shift(1)
esm["pre_state_m_enc"] = esm["pre_state_m"].apply(
    lambda x: float(str(x)[1:]) if pd.notna(x) and len(str(x)) > 1 else np.nan
)
esm["pre_eq_current"] = (esm["pre_state_m"] == esm["state_m_label"]).astype(float)

morph_num = {"C1": 0, "C2": 1, "C3": 2, "C4": 3, "C5": 4}
esm["morph_num"] = esm["morphotype_curve"].map(morph_num)

# Rolling features por noche
print("  Computando rolling features por noche...")
feat_list = [
    rolling_event_features(g)
    for _, g in esm.groupby("night_record_id", sort=False)
]
esm = esm.join(pd.concat(feat_list))

# Descartar los 5 primeros eventos por noche (sin contexto suficiente)
esm["event_rank"] = esm.groupby("night_record_id").cumcount()
ev_df = esm[esm["event_rank"] >= 5][EVENT_FEATURES + ["is_severe", "user_id", "night_record_id"]].dropna()

print(f"  Dataset evento final: {len(ev_df):,} eventos")
print(f"  Severos: {ev_df['is_severe'].sum():,} ({ev_df['is_severe'].mean()*100:.2f}%)")
print(f"  Pacientes: {ev_df['user_id'].nunique()}")


# ── Step 3: Entrenar nb06_event_lgbm.pkl ─────────────────────────────────────

print()
print("=" * 60)
print("Step 3 — Entrenar LightGBM evento (nb06_event_lgbm.pkl)")
print("=" * 60)

import lightgbm as lgb

lgbm_params = dict(
    n_estimators=300, max_depth=5, learning_rate=0.05, num_leaves=31,
    class_weight="balanced", subsample=0.8, colsample_bytree=0.8,
    random_state=42, n_jobs=-1, verbose=-1,
)
clf_lgbm = lgb.LGBMClassifier(**lgbm_params)
clf_lgbm.fit(ev_df[EVENT_FEATURES].values, ev_df["is_severe"].values)

event_model_path = MODELS / "nb06_event_lgbm.pkl"
with open(event_model_path, "wb") as f:
    pickle.dump(clf_lgbm, f)
print(f"  ✓ {event_model_path}")

# Quick sanity: predict on train (expected AUC >> 0.5)
from sklearn.metrics import roc_auc_score
p_train = clf_lgbm.predict_proba(ev_df[EVENT_FEATURES].values)[:, 1]
auc_train = roc_auc_score(ev_df["is_severe"].values, p_train)
print(f"  AUC entrenamiento (in-sample): {auc_train:.3f}")


# ── Step 4: Preparar dataset de noches ───────────────────────────────────────

print()
print("=" * 60)
print("Step 4 — Preparar dataset de noches (night_multiscale_features)")
print("=" * 60)

nmf = pd.read_parquet(GOLD / "night_multiscale_features.parquet")
print(f"  Cargado: {nmf.shape}")

# Verificar que todas las NIGHT_FEATURES están presentes
missing_nf = [f for f in NIGHT_FEATURES if f not in nmf.columns]
if missing_nf:
    print(f"  ⚠ Features faltantes: {missing_nf}")
    NIGHT_FEATURES_AVAIL = [f for f in NIGHT_FEATURES if f in nmf.columns]
else:
    NIGHT_FEATURES_AVAIL = NIGHT_FEATURES

# Encode night_traj_cluster si es string
if nmf["night_traj_cluster"].dtype == object:
    le_traj = LabelEncoder()
    nmf["night_traj_cluster"] = le_traj.fit_transform(
        nmf["night_traj_cluster"].fillna("Unknown").astype(str)
    )
    print(f"  night_traj_cluster encoding: {dict(enumerate(le_traj.classes_))}")

# Target: risk_tier = 1 si Moderado o Severo
nmf["risk_tier"] = nmf["aasm_sev"].isin(["Moderado", "Severo"]).astype(int)

# user_id no está en night_multiscale_features — tomarlo de night_features
nf_ids = pd.read_parquet(GOLD / "night_features.parquet")[["night_record_id", "user_id"]]
nmf = nmf.merge(nf_ids, on="night_record_id", how="left")

night_df = nmf[NIGHT_FEATURES_AVAIL + ["risk_tier", "user_id", "night_record_id", "aasm_sev"]].dropna()
print(f"  Dataset noche final: {len(night_df)} noches")
print(f"  risk_tier=1 (Mod+Sev): {night_df['risk_tier'].sum()} ({night_df['risk_tier'].mean()*100:.1f}%)")
print(f"  Pacientes: {night_df['user_id'].nunique()}")


# ── Step 5: Entrenar nb06_night_lr.pkl ───────────────────────────────────────

print()
print("=" * 60)
print("Step 5 — Entrenar Logística noche (nb06_night_lr.pkl)")
print("=" * 60)

# Pipeline: StandardScaler + LogisticRegression (replicando NB07 D1)
night_pipe = Pipeline([
    ("scaler", StandardScaler()),
    ("clf", LogisticRegression(C=1.0, class_weight="balanced",
                               max_iter=1000, random_state=42)),
])
night_pipe.fit(night_df[NIGHT_FEATURES_AVAIL].values, night_df["risk_tier"].values)

night_model_path = MODELS / "nb06_night_lr.pkl"
with open(night_model_path, "wb") as f:
    pickle.dump(night_pipe, f)
print(f"  ✓ {night_model_path}")

p_night_train = night_pipe.predict_proba(night_df[NIGHT_FEATURES_AVAIL].values)[:, 1]
auc_night = roc_auc_score(night_df["risk_tier"].values, p_night_train)
print(f"  AUC entrenamiento (in-sample): {auc_night:.3f}")

# Risk score distribution by AASM severity
night_df = night_df.copy()
night_df["p_night"] = p_night_train
print("\n  P(high risk) by AASM:")
for sev in ["Normal", "Leve", "Moderado", "Severo"]:
    sub = night_df[night_df["aasm_sev"] == sev]["p_night"]
    if len(sub):
        print(f"    {sev:10s}: median={sub.median():.3f}  mean={sub.mean():.3f}  n={len(sub)}")


# ── Step 6: Actualizar CONFIG con NIGHT_FEATURES reales ──────────────────────

if NIGHT_FEATURES_AVAIL != NIGHT_FEATURES:
    CONFIG["NIGHT_FEATURES"] = NIGHT_FEATURES_AVAIL
    with open(config_path, "w") as f:
        json.dump(CONFIG, f, indent=2)
    print(f"\n  ⚠ nb06_config.json actualizado con NIGHT_FEATURES disponibles")


# ── Resumen ───────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("RESUMEN — Modelos generados")
print("=" * 60)
for p in [config_path, event_model_path, night_model_path]:
    size = p.stat().st_size
    print(f"  ✓ {p.name:35s}  {size:>8,} bytes")

print()
print("Listo. La app.py debería correr sin errores de modelos faltantes.")
