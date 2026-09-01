# -*- coding: utf-8 -*-
"""
Cifras canónicas del Proyecto PAC, verificadas contra `gold/*.parquet`.

Fuente: CLAUDE.md §20 (checklist post-jurado), §22 (re-auditoría Cap. 6),
§23 (re-auditoría Cap. 5) y §25 (bug PATH_M). Ante conflicto, la sección
más reciente prevalece.

Tres estructuras:
  PRESENTES   — valores que DEBEN aparecer en el consolidado.
  SUPERADOS   — valores de corridas viejas que NO deben reaparecer nunca.
  ETIQUETADAS — pares (etiqueta_a, etiqueta_b, valor) para verificar que una
                misma métrica no figure con dos valores distintos.

Al actualizar una cifra del pipeline hay que tocar este archivo y mover el
valor viejo a SUPERADOS. Esa es la red que evita que un número vuelva atrás.
"""

# --------------------------------------------------------------- deben aparecer
# (nombre, literal buscado, mínimo de apariciones esperadas)
PRESENTES = [
    ("EDOs quality",                "85.277",  5),
    ("EDOs detectados",             "85.286",  1),
    ("noches in_quality",           "560",     5),
    ("noches cohorte estricta",     "540",     3),
    ("noches Bloque C (NB07)",      "494",     2),
    ("eventos Bloque B (NB07)",     "76.053",  1),
    ("ventanas NB08",               "452.955", 3),
    ("V de Cramér escala S",        "0,356",   3),
    ("V de Cramér escala M",        "0,231",   3),
    ("V de Cramér escala L",        "0,196",   3),
    ("AUC evento (LightGBM)",       "0,882",   2),
    ("AUC noche (LR)",              "0,905",   3),
    ("AUC noche (RF)",              "0,777",   2),
    ("AUC prospectivo H=5min",      "0,821",   3),
    ("AP noche",                    "0,834",   1),
    ("AP evento",                   "0,264",   1),
    ("PC1 de las 21 variables",     "36,7",    2),
    ("ARI del morfotipo C5",        "0,423",   2),
    ("Silhouette K=5",              "0,432",   2),
    ("rho(ARI, drop_pct)",          "0,035",   2),
    ("C4+C5 sobre el corpus",       "6,0",     3),
    ("carga hipóxica C4+C5",        "23,8",    1),
    ("Gini de Estados PAC",         "44,8",    2),
    ("baseline AP evento",          "5,57",    1),
    ("morfotipo C1",                "64,7",    2),
]

# --------------------------------------------------------------- no deben aparecer
# (nombre, patrón regex). Se evitan los números ambiguos que también son
# valores legítimos de otra métrica (p. ej. 0,783 es el AUC de H = 10 min).
SUPERADOS = [
    ("EDOs: era 84.248",                 r'84\.248'),
    ("EDOs: error de suma 84.193",       r'84\.193'),
    ("noches: era 553",                  r'553\s+noches'),
    ("C4+C5: era 5.177 eventos",         r'5\.177'),
    ("C4+C5: era 6,1 %",                 r'(?<![\d,])6,1\s*%'),
    ("V de Cramér: era 0,230",           r'0,230'),
    ("V de Cramér: era 0,229",           r'0,229'),
    ("V de Cramér: era 0,194",           r'0,194'),
    ("AUC evento: era 0,878",            r'0,878'),
    ("AP evento: era 0,240",             r'0,240'),
    ("AUC noche: era 0,874",             r'0,874'),
    ("AUC RF: era 0,815",                r'0,815'),
    ("AP noche: era 0,764",              r'0,764'),
    ("baseline AP noche: era 0,320",     r'0,320'),
    ("baseline AP evento: era 5,56 %",   r'5,56\s*%'),
    ("S4→ODI3: era 0,691",               r'0,691'),
    ("L0→T90: era 0,705",                r'0,705'),
    ("PC1: era 29,2 %",                  r'29,2\s*%'),
    ("Silhouette: era 0,386",            r'0,386'),
    ("IEI: era 82 s",                    r'82\s*s\b'),
    ("IEI: era 62,8 %",                  r'62,8'),
    ("RR de S6: era 4,70×",              r'4,70'),
    ("trayectorias: eran 511 noches",    r'511\s+noches'),
    ("rho(ARI,ODI3) mal rotulado 0,034", r'0,034'),
    ("r(ci_s,ci_m): era 0,066",          r'0,066'),
    ("r(ci_m,ci_l): era 0,291",          r'0,291'),
    ("CHA %severos: era 37,9",           r'37,9'),
    ("fracciones M: era 88,9 %",         r'88,9'),
    ("bal. accuracy PAC-only: era 0,521", r'0,521'),
    ("Risk Score PAC: era 25,6",         r'25,6'),
    ("Risk Score PAC: era 31,6",         r'31,6'),
    ("Risk Score PAC: era 72,2",         r'72,2'),
    ("Risk Score PAC: era 80,8",         r'80,8'),
    ("Risk Score PAC: era 72,9 / 81,0",  r'72,9|81,0'),
    ("K preliminar S=6 / M=8 / L=6",     r'S\s*=\s*6\b|M\s*=\s*8\b|L\s*=\s*6\b'),
]

# --------------------------------------------------------------- coherencia interna
# (etiqueta_a, etiqueta_b, valor único esperado)
ETIQUETADAS = [
    ("S4", "ODI3", "+0,690"),
    ("M1", "T90",  "+0,744"),
    ("S5", "ARI",  "+0,637"),
    ("L0", "T90",  "+0,683"),
    ("L3", "ARI",  "+0,357"),
]

# --------------------------------------------------------------- tono (advertencia)
# Verbos taxativos: el CLAUDE.md fija tono de potencialidad como no negociable.
# Se listan para revisión humana; no hacen fallar la auditoría porque hay usos
# legítimos (sustantivos, propiedades técnicas verificables).
VERBOS_TAXATIVOS = [
    r'\bdemuestra\b', r'\bdemuestran\b', r'\bprueba que\b', r'\bconfirma\b',
    r'\bconfirman\b', r'\bestablece que\b', r'\bgarantiza\b', r'\bevidencia que\b',
    r'\basegura que\b', r'\bcomprueba\b',
]
