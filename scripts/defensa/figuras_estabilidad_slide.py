#!/usr/bin/env python3
"""
Figuras de estabilizacion multi-noche para la diapositiva 10 de la defensa.

Genera ODI3 y ARI con estilo IDENTICO, para que se lean como un par apilado.
Las figuras de la tesis (03_odi3_estabilidad_multinoche.png = Fig 4.6) NO se
tocan: estas se guardan con prefijo slide_.

Decisiones que fija este script y que antes diferian entre las dos figuras:
  - misma cohorte: estricta (>=10 noches in_strict -> 8 pacientes, 540 noches),
    que es la que reproduce la Tabla 4.8 de la tesis al decimal
  - misma banda: IQR bootstrap (percentiles 25-75). La del ARI usaba 5-95,
    lo que la hacia parecer mas dispersa por construccion
  - mismo eje x: 1 a 14 noches, marca en cada entero
  - sin cuadricula, solo ejes izquierdo e inferior
  - separador decimal coma en marcas y anotaciones
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from pathlib import Path

RAIZ = Path("/sessions/determined-youthful-cray/mnt/PAC_v2")
SALIDA = RAIZ / "notebooks" / "figuras"

AZUL_TITULO = "#1E3A5F"
AZUL_LINEA = "#2E75B6"
AZUL_BANDA = "#CFE0EF"
ROJO = "#E74C3C"
GRIS_TEXTO = "#1E252D"

MAX_K = 14
N_BOOT = 500
SEMILLA = 42
ANOTAR = (1, 3, 7, 14)


def coma(dec):
    return FuncFormatter(lambda v, _: f"{v:.{dec}f}".replace(".", ","))


def cohorte_estricta(df):
    """Pacientes con 10 o mas noches in_strict. Es la definicion que usan
    NB06, NB07 y NB08, y la que reproduce la Tabla 4.8."""
    n = df[df.in_strict].groupby("user_id").size()
    pacientes = n[n >= 10].index.tolist()
    return df[df.in_strict & df.user_id.isin(pacientes)], pacientes


def curva_mae(df, columna, max_k=MAX_K, n_boot=N_BOOT, semilla=SEMILLA):
    grupos = {
        u: v[columna].dropna().values
        for u, v in df.groupby("user_id")
        if v[columna].dropna().shape[0] >= 5
    }
    rng = np.random.default_rng(semilla)
    medias, q25, q75 = [], [], []
    for k in range(1, max_k + 1):
        boot = []
        for _ in range(n_boot):
            errs = [
                abs(rng.choice(v, size=k, replace=False).mean() - v.mean())
                for v in grupos.values()
                if len(v) >= k
            ]
            boot.append(np.mean(errs))
        medias.append(np.mean(boot))
        q25.append(np.percentile(boot, 25))
        q75.append(np.percentile(boot, 75))
    return grupos, np.array(medias), np.array(q25), np.array(q75)


def dibujar(titulo, y_label, medias, q25, q75, umbral, umbral_txt,
            decimales, y_max, offsets, ruta):
    ks = np.arange(1, len(medias) + 1)
    fig, ax = plt.subplots(figsize=(7.2, 4.0))

    ax.fill_between(ks, q25, q75, color=AZUL_BANDA, alpha=0.85,
                    label="IQR bootstrap", zorder=1)
    ax.plot(ks, medias, color=AZUL_LINEA, lw=2.4, marker="o", ms=5,
            label="MAE medio", zorder=3)
    ax.axhline(umbral, color=ROJO, lw=1.6, ls="--", label=umbral_txt, zorder=2)

    for k in ANOTAR:
        v = medias[k - 1]
        dx, dy = offsets[k]
        ax.annotate(f"{v:.{decimales}f}".replace(".", ","),
                    xy=(k, v), xytext=(k + dx, v + dy),
                    fontsize=11, fontweight="bold", color=AZUL_TITULO, zorder=4)

    ax.set_title(titulo, fontsize=13, fontweight="bold",
                 color=AZUL_TITULO, pad=12)
    ax.set_xlabel("Número de noches promediadas", fontsize=11, color=GRIS_TEXTO)
    ax.set_ylabel(y_label, fontsize=11, color=GRIS_TEXTO)

    ax.set_xlim(0.5, MAX_K + 1.6)
    ax.set_xticks(range(1, MAX_K + 1))
    ax.set_ylim(0, y_max)
    ax.yaxis.set_major_formatter(coma(decimales))

    ax.grid(False)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color("#9AA5B1")
    ax.tick_params(labelsize=10, colors=GRIS_TEXTO)

    # "center right" en AMBAS: es la unica zona libre en las dos figuras a la
    # vez. En el ARI el umbral de 0,05 corre por el margen superior y cruzaria
    # una leyenda arriba a la derecha.
    ax.legend(loc="center right", frameon=False, fontsize=10)
    fig.tight_layout()
    fig.savefig(ruta, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("guardada:", ruta.name)


def main():
    df = pd.read_parquet(RAIZ / "gold" / "night_features.parquet")
    estricta, pacientes = cohorte_estricta(df)
    print(f"cohorte estricta: {len(pacientes)} pacientes · {len(estricta)} noches")

    g, m, lo, hi = curva_mae(estricta, "odi_3")
    print("ODI3 :", " ".join(f"n{k}={m[k-1]:.3f}" for k in ANOTAR),
          f"({len(g)} pacientes con >=5 noches)")
    dibujar("Estabilización del ODI3: error vs. noches promediadas",
            "MAE vs. referencia interna (ev/h)", m, lo, hi,
            umbral=2, umbral_txt="umbral = 2 ev/h", decimales=1, y_max=6.0,
            # el 1,7 va bien despegado: cae justo sobre el umbral de 2 ev/h
            offsets={1: (0.25, 0.25), 3: (0.25, 0.30), 7: (0.20, 0.55),
                     14: (0.28, -0.10)},
            ruta=SALIDA / "slide_estabilidad_odi3.png")

    g, m, lo, hi = curva_mae(estricta, "mean_ari")
    print("ARI  :", " ".join(f"n{k}={m[k-1]:.4f}" for k in ANOTAR),
          f"({len(g)} pacientes con >=5 noches)")
    dibujar("Estabilización del ARI: error vs. noches promediadas",
            "MAE del ARI paciente-nivel", m, lo, hi,
            umbral=0.05, umbral_txt="umbral = 0,05", decimales=3, y_max=0.058,
            offsets={1: (0.25, 0.0035), 3: (0.25, 0.0035), 7: (0.25, 0.0035),
                     14: (0.28, -0.0010)},
            ruta=SALIDA / "slide_estabilidad_ari.png")


if __name__ == "__main__":
    main()
