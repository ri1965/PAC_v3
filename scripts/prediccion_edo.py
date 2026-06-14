"""
NB07 — Predicción en tiempo real de EDOs (Eventos de Desaturación de Oxígeno)
==============================================================================
Objetivo: dado un instante t, ¿habrá un EDO en los próximos H segundos?

Diseño:
- Ventana de lookback: 120s de señales brutas (SpO2, HR, Mov)
- Horizontes de predicción: 30s, 60s, 120s (tres modelos separados)
- Positivos: 1 muestra por evento (calidad + sueño), ventana terminada H segundos
  antes de ts_start (sin leakage)
- Negativos: ratio 4:1, excluidos ±30s alrededor de cualquier evento
- Contexto nocturno: mean_ari, odi_3, t90_frac, frac_c1-c5, estados PAC
- Validación: LOPO-CV (Leave-One-Patient-Out), 12 pacientes
- Modelo: LightGBM con scale_pos_weight
- Guardado: /PAC_v2/gold/nb07_results.json
"""

import os, json, warnings, time
import numpy as np
import pandas as pd
from pathlib import Path
from collections import defaultdict

warnings.filterwarnings('ignore')

# ── Rutas ────────────────────────────────────────────────────────────────────
PAC    = Path('/sessions/wonderful-nice-ritchie/mnt/PAC_v2')
BRONZE = PAC / 'bronze'
GOLD   = PAC / 'gold'
OUT    = GOLD / 'nb07_results.json'

# ── Hiperparámetros ──────────────────────────────────────────────────────────
LOOKBACK_S   = 120          # ventana de features (segundos hacia atrás)
HORIZONS     = [30, 60, 120]
NEG_RATIO    = 4            # negativos por positivo
MIN_CLEAR_S  = 30           # zona prohibida alrededor de eventos (cada lado)
MIN_ROWS_WIN = 60           # mínimo de filas válidas en ventana para usar muestra
RANDOM_SEED  = 42

MORPHO_SEV = {'δ': 1, 'α': 2, 'β': 3, 'γ': 4}

import lightgbm as lgb
from sklearn.metrics import roc_auc_score, balanced_accuracy_score, roc_curve

print("="*60)
print("NB07 — Predicción de EDOs en tiempo real")
print("="*60)
print(f"LightGBM {lgb.__version__}")
print(f"Lookback: {LOOKBACK_S}s | Horizontes: {HORIZONS}s | Neg ratio: {NEG_RATIO}:1")
print()

t0 = time.time()

# ── 1. Carga de eventos ───────────────────────────────────────────────────────
print("Cargando eventos...")
events = pd.read_parquet(GOLD / 'events.parquet')
ev_ok = events[(events['in_quality'] == True) & (events['in_sleep'] == True)].copy()
print(f"  quality+sleep: {len(ev_ok):,} | pacientes: {ev_ok['user_id'].nunique()} | noches: {ev_ok['night_record_id'].nunique()}")

ev_ok['ts_start_ns'] = ev_ok['ts_start'].astype('int64')
ev_ok['ts_end_ns']   = ev_ok['ts_end'].astype('int64')
ev_ok['morpho_sev']  = ev_ok['morphotype'].map(MORPHO_SEV).fillna(2).astype(int)

# ── 2. Contexto nocturno: night_features + nights ────────────────────────────
print("Cargando contexto nocturno...")

# night_features: ARI, morfotipos, índices clínicos nocturnos
NF_COLS = ['night_record_id', 'mean_ari', 'p90_ari', 'odi_3', 't90_frac',
           'hypoxic_burden_3_pac_v2', 'frac_c1', 'frac_c2', 'frac_c3',
           'frac_c4', 'frac_c5', 'sleep_efficiency', 'n_edos_total',
           'mean_drop_pct', 'mean_hr', 'std_hr', 'mean_mov']
nf = pd.read_parquet(GOLD / 'night_features.parquet')
nf = nf[[c for c in NF_COLS if c in nf.columns]].copy()
print(f"  night_features: {len(nf)} noches, {len(nf.columns)} cols")

# nights: estados PAC (top features NB05)
PAC_STATE_COLS = (
    [f'frac_state_s_S{i}' for i in range(6)] +
    [f'frac_state_m_M{i}' for i in range(8)] +
    [f'frac_state_l_L{i}' for i in range(6)] +
    ['n_transitions_state_s', 'n_transitions_state_m', 'n_transitions_state_l',
     'entropy_state_s', 'entropy_state_m', 'entropy_state_l',
     'odi_3', 't90_frac', 'hypoxic_burden_90', 'tst_s', 'mean_spo2', 'min_spo2']
)
nights = pd.read_parquet(GOLD / 'nights.parquet')
nights_cols = ['night_record_id'] + [c for c in PAC_STATE_COLS if c in nights.columns]
nights = nights[nights_cols].copy()
print(f"  nights PAC states: {len(nights)} noches, {len(nights_cols)-1} cols")

# Merge
ctx = nf.merge(nights, on='night_record_id', how='outer', suffixes=('', '_n'))
# Si odi_3 aparece dos veces, quedarse con la primera
ctx = ctx.loc[:, ~ctx.columns.duplicated()]
ctx = ctx.set_index('night_record_id')

CTX_COLS = [c for c in ctx.columns]
print(f"  Contexto total: {len(CTX_COLS)} features de noche")

def get_night_ctx(nr):
    if nr in ctx.index:
        row = ctx.loc[nr]
        return {f'nc_{c}': float(row[c]) if pd.notna(row[c]) else 0.0 for c in CTX_COLS}
    return {f'nc_{c}': 0.0 for c in CTX_COLS}

# ── 3. Bronze files ───────────────────────────────────────────────────────────
bronze_files = {f.stem: f for f in BRONZE.glob('NR_*.parquet') if '_classical' not in f.name}
print(f"  Bronze files: {len(bronze_files)}")

# ── 4. Extracción de features de ventana ─────────────────────────────────────
LOOKBACK_NS = LOOKBACK_S * 1_000_000_000

def slope_fast(arr):
    n = len(arr)
    if n < 2: return 0.0
    x = np.arange(n, dtype=np.float32)
    xm, ym = x.mean(), arr.mean()
    denom = float(((x-xm)**2).sum())
    return float(((x-xm)*(arr-ym)).sum() / denom) if denom > 0 else 0.0

def extract_window_feats(ts_arr, spo2_arr, hr_arr, mov_arr, t_end_ns):
    i0 = int(np.searchsorted(ts_arr, t_end_ns - LOOKBACK_NS, 'left'))
    i1 = int(np.searchsorted(ts_arr, t_end_ns, 'left'))
    if i1 - i0 < MIN_ROWS_WIN:
        return None

    spo2_w = spo2_arr[i0:i1]
    hr_w   = hr_arr[i0:i1]
    mov_w  = mov_arr[i0:i1]

    valid = (spo2_w > 50) & (hr_w > 20)
    if valid.sum() < MIN_ROWS_WIN:
        return None

    s = spo2_w[valid].astype(np.float32)
    h = hr_w[valid].astype(np.float32)
    m = mov_w[valid].astype(np.float32)
    n = len(s)
    last30 = max(1, int(30 * n / LOOKBACK_S))

    feats = {}

    # SpO2
    feats['spo2_mean']         = float(s.mean())
    feats['spo2_std']          = float(s.std()) if n > 1 else 0.0
    feats['spo2_min']          = float(s.min())
    feats['spo2_max']          = float(s.max())
    feats['spo2_range']        = float(s.max() - s.min())
    feats['spo2_slope']        = slope_fast(s)
    feats['spo2_last30_mean']  = float(s[-last30:].mean())
    feats['spo2_last30_min']   = float(s[-last30:].min())
    feats['spo2_last30_slope'] = slope_fast(s[-last30:])
    feats['spo2_drift']        = float(s[-1] - s[0])
    feats['spo2_pct_below92']  = float((s < 92).mean())
    feats['spo2_pct_below90']  = float((s < 90).mean())
    feats['spo2_pct_below88']  = float((s < 88).mean())
    # Desaceleración en la caída (cuánto bajó en el último tercio vs primer tercio)
    third = max(1, n // 3)
    feats['spo2_late_drop']    = float(s[-third:].mean() - s[:third].mean())

    # HR
    feats['hr_mean']           = float(h.mean())
    feats['hr_std']            = float(h.std()) if n > 1 else 0.0
    feats['hr_max']            = float(h.max())
    feats['hr_min']            = float(h.min())
    feats['hr_range']          = float(h.max() - h.min())
    feats['hr_slope']          = slope_fast(h)
    feats['hr_last30_mean']    = float(h[-last30:].mean())
    feats['hr_last30_slope']   = slope_fast(h[-last30:])
    feats['hr_late_rise']      = float(h[-third:].mean() - h[:third].mean())

    # MOV
    feats['mov_mean']          = float(m.mean())
    feats['mov_std']           = float(m.std()) if n > 1 else 0.0
    feats['mov_max']           = float(m.max())
    feats['mov_last30_max']    = float(m[-last30:].max())
    feats['mov_last30_mean']   = float(m[-last30:].mean())
    feats['mov_last30_std']    = float(m[-last30:].std()) if last30 > 1 else 0.0

    # Correlación SpO2–HR
    if n > 5 and s.std() > 0 and h.std() > 0:
        feats['corr_spo2_hr'] = float(np.corrcoef(s, h)[0, 1])
    else:
        feats['corr_spo2_hr'] = 0.0

    # Ratio HR/SpO2 (indicador de respuesta autonómica)
    feats['hr_spo2_ratio'] = float(h.mean() / max(s.mean(), 1.0))

    return feats

# ── 5. Construcción del dataset ───────────────────────────────────────────────
print("\nConstruyendo muestras por noche...")

ev_by_night = {nr: grp.sort_values('ts_start').reset_index(drop=True)
               for nr, grp in ev_ok.groupby('night_record_id')}

all_samples = {H: [] for H in HORIZONS}
rng = np.random.default_rng(RANDOM_SEED)

nights_ok = 0
nights_skip = 0

for nr, ev_night in ev_by_night.items():
    uid = ev_night['user_id'].iloc[0]
    bf_path = bronze_files.get(nr)
    if bf_path is None:
        nights_skip += 1
        continue

    try:
        bronze = pd.read_parquet(bf_path)
    except Exception:
        nights_skip += 1
        continue

    if len(bronze) < LOOKBACK_S + 30:
        nights_skip += 1
        continue

    ts_arr   = bronze['timestamp'].astype('int64').values
    spo2_arr = bronze['spo2'].values.astype(np.float32)
    hr_arr   = bronze['hr'].values.astype(np.float32)
    mov_arr  = bronze['mov'].values.astype(np.float32)

    # Ordenar por tiempo
    si = np.argsort(ts_arr)
    ts_arr, spo2_arr, hr_arr, mov_arr = ts_arr[si], spo2_arr[si], hr_arr[si], mov_arr[si]

    ts_min, ts_max = ts_arr[0], ts_arr[-1]

    ev_starts_ns = ev_night['ts_start_ns'].values
    ev_ends_ns   = ev_night['ts_end_ns'].values

    nc_feats = get_night_ctx(nr)

    MIN_CLEAR_NS = MIN_CLEAR_S * 1_000_000_000
    forbidden_starts = ev_starts_ns - MIN_CLEAR_NS
    forbidden_ends   = ev_ends_ns   + MIN_CLEAR_NS

    for H in HORIZONS:
        H_NS = H * 1_000_000_000
        h_samples = []

        # ── POSITIVOS ──────────────────────────────────────────────────────
        for idx, row in ev_night.iterrows():
            t_pred_ns = row['ts_start_ns'] - H_NS
            if t_pred_ns - LOOKBACK_NS < ts_min or t_pred_ns > ts_max:
                continue

            feats = extract_window_feats(ts_arr, spo2_arr, hr_arr, mov_arr, t_pred_ns)
            if feats is None:
                continue

            # Evento previo
            prev_evs = ev_night[ev_night['ts_start_ns'] < row['ts_start_ns']]
            if len(prev_evs) > 0:
                last = prev_evs.iloc[-1]
                feats['prev_morpho_sev'] = float(last['morpho_sev'])
                feats['prev_drop_pct']   = float(last.get('drop_pct', 3.0))
                gap_s = (row['ts_start_ns'] - last['ts_end_ns']) / 1e9
                feats['prev_gap_s']      = float(np.clip(gap_s, 0, 600))
                feats['has_prev_event']  = 1.0
            else:
                feats['prev_morpho_sev'] = 2.0
                feats['prev_drop_pct']   = 3.0
                feats['prev_gap_s']      = 600.0
                feats['has_prev_event']  = 0.0

            feats.update(nc_feats)
            feats['label']   = 1
            feats['user_id'] = uid
            h_samples.append(feats)

        n_pos = len(h_samples)
        if n_pos == 0:
            continue

        # ── NEGATIVOS ──────────────────────────────────────────────────────
        n_neg_need = n_pos * NEG_RATIO
        i_min = int(np.searchsorted(ts_arr, ts_min + LOOKBACK_NS, 'left'))
        i_max = len(ts_arr) - 1
        if i_max <= i_min:
            all_samples[H].extend(h_samples)
            continue

        pool_size = min(n_neg_need * 25, i_max - i_min)
        cand_idx  = rng.choice(np.arange(i_min, i_max), size=pool_size, replace=False)
        cand_ts   = ts_arr[cand_idx]

        # Filtro zona prohibida
        in_forb = np.zeros(len(cand_ts), dtype=bool)
        for fs, fe in zip(forbidden_starts, forbidden_ends):
            in_forb |= (cand_ts >= fs) & (cand_ts <= fe)
        cand_ts = cand_ts[~in_forb]
        rng.shuffle(cand_ts)

        neg_added = 0
        for tc in cand_ts:
            if neg_added >= n_neg_need:
                break
            feats = extract_window_feats(ts_arr, spo2_arr, hr_arr, mov_arr, int(tc))
            if feats is None:
                continue

            # Evento previo al negativo
            prev_before = ev_starts_ns[ev_starts_ns < tc]
            if len(prev_before) > 0:
                last_ns = prev_before[-1]
                mask = ev_night['ts_start_ns'] == last_ns
                if mask.any():
                    last = ev_night[mask].iloc[0]
                    feats['prev_morpho_sev'] = float(last['morpho_sev'])
                    feats['prev_drop_pct']   = float(last.get('drop_pct', 3.0))
                    gap_s = (tc - last['ts_end_ns']) / 1e9
                    feats['prev_gap_s']      = float(np.clip(gap_s, 0, 600))
                    feats['has_prev_event']  = 1.0
                else:
                    feats['prev_morpho_sev'] = 2.0
                    feats['prev_drop_pct']   = 3.0
                    feats['prev_gap_s']      = 600.0
                    feats['has_prev_event']  = 0.0
            else:
                feats['prev_morpho_sev'] = 2.0
                feats['prev_drop_pct']   = 3.0
                feats['prev_gap_s']      = 600.0
                feats['has_prev_event']  = 0.0

            feats.update(nc_feats)
            feats['label']   = 0
            feats['user_id'] = uid
            h_samples.append(feats)
            neg_added += 1

        all_samples[H].extend(h_samples)

    nights_ok += 1
    if nights_ok % 50 == 0:
        n_pos30 = sum(1 for s in all_samples[30] if s['label'] == 1)
        print(f"  {nights_ok} noches | pos(H30)={n_pos30}")

print(f"\nNoches OK: {nights_ok}, saltadas: {nights_skip}")
for H in HORIZONS:
    n_pos = sum(1 for s in all_samples[H] if s['label'] == 1)
    n_neg = sum(1 for s in all_samples[H] if s['label'] == 0)
    print(f"  H={H}s → pos={n_pos}, neg={n_neg}")

# ── 6. LOPO-CV por horizonte ──────────────────────────────────────────────────
print("\nEjecutando LOPO-CV con LightGBM...")

lgb_params = dict(
    objective='binary',
    metric='auc',
    verbosity=-1,
    n_estimators=500,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=30,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=0.1,
    reg_lambda=0.1,
    random_state=RANDOM_SEED,
    n_jobs=-1,
)

results = {}

for H in HORIZONS:
    samples = all_samples[H]
    if len(samples) < 20:
        print(f"  H={H}s: insuficientes muestras.")
        continue

    df = pd.DataFrame(samples)
    feat_cols = [c for c in df.columns if c not in ('label', 'user_id')]
    df[feat_cols] = df[feat_cols].fillna(0).astype(np.float32)

    users = df['user_id'].unique()
    print(f"\n  H={H}s | {len(df):,} muestras | {len(users)} pacientes | {len(feat_cols)} features")

    fold_metrics = []
    all_probs, all_trues = [], []

    for test_uid in sorted(users):
        tr = df[df['user_id'] != test_uid]
        te = df[df['user_id'] == test_uid]

        if len(te) < 5 or len(tr) < 20:
            continue
        n_pos_tr = (tr['label'] == 1).sum()
        n_neg_tr = (tr['label'] == 0).sum()
        if n_pos_tr < 2:
            continue

        spw = float(n_neg_tr / n_pos_tr)
        params = {**lgb_params, 'scale_pos_weight': spw}

        model = lgb.LGBMClassifier(**params)
        model.fit(
            tr[feat_cols].values, tr['label'].values,
            eval_set=[(te[feat_cols].values, te['label'].values)],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)]
        )

        y_prob = model.predict_proba(te[feat_cols].values)[:, 1]
        y_true = te['label'].values
        y_pred = (y_prob >= 0.5).astype(int)

        auc  = float(roc_auc_score(y_true, y_prob)) if len(np.unique(y_true)) > 1 else 0.5
        bacc = float(balanced_accuracy_score(y_true, y_pred))

        # Sensibilidad a 80% especificidad
        if len(np.unique(y_true)) > 1:
            fpr, tpr, _ = roc_curve(y_true, y_prob)
            idx80 = np.where((1 - fpr) >= 0.80)[0]
            s80 = float(tpr[idx80[-1]]) if len(idx80) > 0 else 0.0
        else:
            s80 = 0.0

        fold_metrics.append(dict(
            patient=test_uid,
            auc=round(auc, 4),
            balanced_acc=round(bacc, 4),
            sens_at_80spec=round(s80, 4),
            n_pos=int((y_true == 1).sum()),
            n_neg=int((y_true == 0).sum()),
        ))
        all_probs.extend(y_prob.tolist())
        all_trues.extend(y_true.tolist())

        print(f"    {test_uid:8s} | AUC={auc:.3f} | bACC={bacc:.3f} | "
              f"Sens@80sp={s80:.3f} | pos={int((y_true==1).sum())}")

    # Métricas globales (pooled)
    if len(all_probs) > 0 and len(np.unique(all_trues)) > 1:
        g_auc  = float(roc_auc_score(all_trues, all_probs))
        g_bacc = float(balanced_accuracy_score(all_trues, (np.array(all_probs) >= 0.5).astype(int)))
        fpr_g, tpr_g, _ = roc_curve(all_trues, all_probs)
        idx80_g = np.where((1 - fpr_g) >= 0.80)[0]
        g_s80 = float(tpr_g[idx80_g[-1]]) if len(idx80_g) > 0 else 0.0
    else:
        g_auc = g_bacc = g_s80 = 0.0

    # Reentrenamiento completo para feature importance
    n_pos_all = (df['label'] == 1).sum()
    n_neg_all = (df['label'] == 0).sum()
    model_full = lgb.LGBMClassifier(**{**lgb_params, 'scale_pos_weight': float(n_neg_all / max(n_pos_all, 1))})
    model_full.fit(df[feat_cols].values, df['label'].values, callbacks=[lgb.log_evaluation(-1)])
    importances = dict(zip(feat_cols, model_full.feature_importances_.tolist()))
    top10 = sorted(importances.items(), key=lambda x: -x[1])[:10]

    results[str(H)] = dict(
        horizon_s=H,
        n_samples=len(df),
        n_positives=int((df['label'] == 1).sum()),
        n_negatives=int((df['label'] == 0).sum()),
        n_patients=len(users),
        n_features=len(feat_cols),
        global_auc=round(g_auc, 4),
        global_balanced_acc=round(g_bacc, 4),
        global_sens_at_80spec=round(g_s80, 4),
        mean_auc_folds=round(np.mean([f['auc'] for f in fold_metrics]), 4) if fold_metrics else 0.0,
        std_auc_folds=round(np.std([f['auc'] for f in fold_metrics]), 4)  if fold_metrics else 0.0,
        mean_bacc_folds=round(np.mean([f['balanced_acc'] for f in fold_metrics]), 4) if fold_metrics else 0.0,
        std_bacc_folds=round(np.std([f['balanced_acc'] for f in fold_metrics]), 4)  if fold_metrics else 0.0,
        fold_results=fold_metrics,
        top10_features=[{'feature': k, 'importance': int(v)} for k, v in top10],
        feature_names=feat_cols,
    )

    print(f"\n  ── H={H}s GLOBAL ──")
    print(f"    AUC={g_auc:.3f} | bACC={g_bacc:.3f} | Sens@80sp={g_s80:.3f}")
    print(f"    Top-5: {[k for k,_ in top10[:5]]}")

# ── 7. Guardar ────────────────────────────────────────────────────────────────
t_total = round(time.time() - t0, 1)

output = dict(
    notebook='NB07',
    description='Predicción en tiempo real de EDOs — LOPO-CV LightGBM',
    config=dict(
        lookback_s=LOOKBACK_S,
        horizons_s=HORIZONS,
        neg_ratio=NEG_RATIO,
        min_clear_s=MIN_CLEAR_S,
        min_rows_window=MIN_ROWS_WIN,
        n_estimators=lgb_params['n_estimators'],
        learning_rate=lgb_params['learning_rate'],
        num_leaves=lgb_params['num_leaves'],
    ),
    runtime_s=t_total,
    horizons=results,
)

with open(OUT, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\n{'='*60}")
print(f"✓ Resultados guardados: {OUT}")
print(f"  Tiempo total: {t_total}s")
print("="*60)
