#!/usr/bin/env python3
"""
Figura conceptual del Coupling Index para la d19 del mazo de defensa.

Reconstruye la figura de las dos noches (mismo ODI3, CI opuesto) que hasta
ahora existia solo como PNG sin fuente. Cambios respecto del PNG viejo:

1. Los pies dicen "eventos SEVEROS": el CI se define sobre C4-C5, no sobre
   todos los eventos. En el PNG viejo decia solo "eventos" y no cerraba con
   la definicion de la diapositiva.
2. M3 cuenta como estado patologico, igual que en la tabla de la diapositiva
   (patologicos = M1, M3). El PNG viejo lo pintaba de naranja como
   "transicion" y NO lo sumaba, con lo que la figura se contradecia con su
   propia tabla.
3. Los puntos son binarios -- dentro o fuera de estado patologico -- que es
   exactamente lo que mide el indice. El PNG viejo los coloreaba segun el
   color del estado (habia puntos azules en M2), lo que sugeria una tercera
   categoria inexistente.
4. Nota al pie que explica por que se ven 8 puntos si el ODI3 es 14 ev/h.

Uso:  figura_ci_dos_noches.py [salida.png]
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

FUENTE = "Carlito"          # metricamente compatible con Calibri/Aptos
plt.rcParams["font.family"] = FUENTE

FONDO   = "#F7F9FB"
GRIS    = "#5F6B76"
GRIS_CL = "#8C97A1"
VERDE   = "#2E7D32"
ROJO    = "#C62828"
PT_OK   = "#4CAF50"
PT_MAL  = "#E53935"

ESTADO = {                       # relleno, color de etiqueta, patologico
    "M0": ("#C9E6CB", "#2E6B33", False),
    "M1": ("#FBCFD2", "#A33B41", True),
    "M2": ("#BFDCF5", "#2C5F8A", False),
    "M3": ("#FDF3C4", "#8A6D1F", True),
}

# (estado, ancho relativo)
NOCHE_A = [("M0", .30), ("M1", .16), ("M2", .20), ("M0", .19), ("M3", .15)]
NOCHE_B = [("M0", .16), ("M1", .42), ("M3", .16), ("M1", .26)]
# posiciones de los eventos severos, en fraccion de la barra
EV_A = [.06, .13, .22, .36, .50, .56, .70, .79]
EV_B = [.05, .11, .22, .32, .42, .52, .66, .85]


def patologico(tramos, pos):
    """True si la posicion cae dentro de un estado patologico."""
    x = 0.0
    for est, w in tramos:
        if x <= pos < x + w:
            return ESTADO[est][2]
        x += w
    return ESTADO[tramos[-1][0]][2]


def panel(ax, x0, x1, titulo, color_tit, tramos, eventos, ci):
    ancho = x1 - x0
    y_bar, h_bar = .655, .125
    y_pt = .565

    ax.text((x0 + x1) / 2, .915, titulo, ha="center", va="center",
            fontsize=15, fontweight="bold", color=color_tit)
    ax.text((x0 + x1) / 2, .845, "ODI3 = 14 ev/h", ha="center", va="center",
            fontsize=11.5, color=GRIS)
    ax.text(x0, .805, "22:00", ha="left", va="center", fontsize=9, color=GRIS_CL)
    ax.text(x1, .805, "06:00", ha="right", va="center", fontsize=9, color=GRIS_CL)

    x = x0
    for est, w in tramos:
        relleno, tinta, _ = ESTADO[est]
        ax.add_patch(FancyBboxPatch(
            (x + .0012, y_bar), w * ancho - .0024, h_bar,
            boxstyle="round,pad=0,rounding_size=.005",
            facecolor=relleno, edgecolor="none", zorder=2))
        ax.text(x + w * ancho / 2, y_bar + h_bar / 2, est, ha="center",
                va="center", fontsize=10, fontweight="bold", color=tinta, zorder=3)
        x += w * ancho

    n_mal = 0
    for pos in eventos:
        px = x0 + pos * ancho
        mal = patologico(tramos, pos)
        n_mal += mal
        ax.plot([px, px], [y_pt + .028, y_bar - .004], ls=(0, (1.4, 1.8)),
                lw=1.1, color=PT_MAL if mal else PT_OK, alpha=.55, zorder=1)
        ax.scatter([px], [y_pt], s=118, color=PT_MAL if mal else PT_OK,
                   edgecolors="white", linewidths=1.4, zorder=4)

    ax.text((x0 + x1) / 2, .487,
            f"{n_mal} de {len(eventos)} eventos severos en zona patológica",
            ha="center", va="center", fontsize=10.5, color=GRIS)

    caja, borde = (("#EAF6EA", PT_OK) if ci < .5 else ("#FDECEC", PT_MAL))
    ax.add_patch(FancyBboxPatch(
        (x0 + ancho * .085, .270), ancho * .83, .180,
        boxstyle="round,pad=0,rounding_size=.02",
        facecolor=caja, edgecolor=borde, linewidth=1.7, zorder=2))
    ax.text((x0 + x1) / 2, .412, "Coupling Index", ha="center", va="center",
            fontsize=11, color=color_tit, zorder=3)
    ax.text((x0 + x1) / 2, .335, f"{ci:.2f}".replace(".", ","), ha="center",
            va="center", fontsize=21, fontweight="bold", color=color_tit, zorder=3)


def construir(salida):
    fig, ax = plt.subplots(figsize=(12, 3.11), dpi=200)
    fig.patch.set_facecolor(FONDO)
    ax.set_facecolor(FONDO)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    panel(ax, .035, .475, "Noche A — CI bajo", VERDE, NOCHE_A, EV_A, 1 / 8)
    panel(ax, .525, .965, "Noche B — CI alto", ROJO,  NOCHE_B, EV_B, 6 / 8)

    ax.plot([.5, .5], [.28, .90], ls=(0, (4, 5)), lw=1.3, color="#C3CCD6")

    ax.add_patch(FancyBboxPatch(
        (.383, .175), .234, .062, boxstyle="round,pad=0,rounding_size=.028",
        facecolor="#E8EEF5", edgecolor="none"))
    ax.text(.5, .206, "ODI3 idéntico — CI opuesto", ha="center", va="center",
            fontsize=11, fontweight="bold", color="#3E5871")

    ax.plot([.035, .965], [.128, .128], lw=.9, color="#DDE3EA")

    ax.scatter([.300], [.086], s=70, color=PT_MAL, edgecolors="white", linewidths=1.1)
    ax.text(.315, .086, "dentro de un estado patológico", ha="left", va="center",
            fontsize=9, color=GRIS)
    ax.scatter([.590], [.086], s=70, color=PT_OK, edgecolors="white", linewidths=1.1)
    ax.text(.605, .086, "fuera de él", ha="left", va="center",
            fontsize=9, color=GRIS)

    ax.text(.5, .030,
            "Los puntos son los eventos severos de cada noche (morfotipos C4–C5).  "
            "El ODI3 cuenta el total: unas 112 desaturaciones por noche en ambos casos.",
            ha="center", va="center", fontsize=8.5, style="italic", color=GRIS_CL)

    fig.savefig(salida, dpi=200, facecolor=FONDO, bbox_inches="tight", pad_inches=.06)
    print("escrita:", salida)


if __name__ == "__main__":
    construir(sys.argv[1] if len(sys.argv) > 1
              else "notebooks/figuras/diapo_CI_dos_noches_v2.png")
