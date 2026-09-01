#!/usr/bin/env python3
"""
Corredor de estados M para la d26 del mazo de defensa.

Todos los valores verificados contra gold/states.parquet (matriz de
transicion de la escala M, n = 45.901 transiciones contiguas).

Que cambia respecto del PNG anterior:

1. Las dos flechas de salida nacian visualmente entre M3 y M1 y sus
   etiquetas quedaban debajo de M3/M4, asi que "31,5 %" se leia como
   M3 -> M4. NO lo es: M3 -> M4 = 18,4 %. El 31,5 % es M1 -> M4. Ahora
   cada flecha lleva su par de estados escrito.
2. El recuadro del 4,3 % no decia desde donde. Es M1 -> M0 o M2.
3. Se marca cuales son los estados patologicos (M3 y M1), que es el
   vocabulario que usa el panel de barras de la misma diapositiva y que
   este panel no compartia.

Uso:  figura_corredor_m.py [salida.png]
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.family"] = "Carlito"

TINTA, GRIS, MARCO = "#1F3A5F", "#6B7A8C", "#C9D2DA"
OSCURO, CLARO = "#1F3A5F", "#8FA6C4"
BANDA = "#FBF1F1"

# etiqueta, glosa, relleno, color de texto, se queda %
ESTADOS = [("M0", "protector",  "#CAD6E4", TINTA, 58.7),
           ("M2", "protector",  "#B1C0D9", TINTA, 52.7),
           ("M4", "moderado",   "#93A8C1", TINTA, 65.4),
           ("M3", "carga alta", "#738DAE", "white", 37.2),
           ("M1", "severo",     "#253F64", "white", 47.3)]
CX = [.115, .300, .485, .670, .855]
BW, BY, BH = .150, .420, .215


def pct(v):
    return f"{v:.1f} %".replace(".", ",")


def construir(salida):
    fig, ax = plt.subplots(figsize=(6.6, 3.05), dpi=200)
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(FancyBboxPatch((.004, .008), .992, .984,
                                boxstyle="round,pad=0,rounding_size=.012",
                                facecolor="none", edgecolor=MARCO, lw=1.1))

    # banda de estados patologicos, detras de M3 y M1
    ax.add_patch(FancyBboxPatch((CX[3] - BW / 2 - .022, BY - .045), 
                                (CX[4] - CX[3]) + BW + .044, BH + .215,
                                boxstyle="round,pad=0,rounding_size=.018",
                                facecolor=BANDA, edgecolor="none", zorder=1))
    ax.text((CX[3] + CX[4]) / 2, .855, "estados patológicos", ha="center",
            va="center", fontsize=7.5, style="italic", color="#B4726F", zorder=2)

    # eje de severidad
    ax.annotate("", xy=(.965, .945), xytext=(.045, .945),
                arrowprops=dict(arrowstyle="-|>", color="#B8C4D2", lw=1.1))
    ax.text(.5, .945, "  severidad creciente  ", ha="center", va="center",
            fontsize=8.5, style="italic", color=GRIS,
            bbox=dict(facecolor="white", edgecolor="none", pad=1.5))

    for cx, (lab, glosa, relleno, tinta, queda) in zip(CX, ESTADOS):
        ax.add_patch(FancyBboxPatch((cx - BW / 2, BY), BW, BH,
                                    boxstyle="round,pad=0,rounding_size=.016",
                                    facecolor=relleno, edgecolor="none", zorder=3))
        ax.text(cx, BY + BH * .60, lab, ha="center", va="center", fontsize=13.5,
                fontweight="bold", color=tinta, zorder=4)
        ax.text(cx, BY + BH * .24, glosa, ha="center", va="center",
                fontsize=8, color=tinta, alpha=.85, zorder=4)

        ax.add_patch(FancyArrowPatch((cx + .028, BY + BH + .008),
                                     (cx + .058, BY + BH + .008),
                                     connectionstyle="arc3,rad=-1.25",
                                     arrowstyle="-|>", mutation_scale=8,
                                     color=OSCURO, lw=1.2, zorder=4))
        ax.text(cx - .012, BY + BH + .105, pct(queda), ha="center", va="center",
                fontsize=8.8, fontweight="bold", color=OSCURO, zorder=4)
        ax.text(cx - .012, BY + BH + .045, "se queda", ha="center", va="center",
                fontsize=7.5, color=GRIS, zorder=4)

    # salidas desde M1 · cada valor va bajo SU punta de flecha, no en el arco
    for destino, valor, rad, color in [(2, 31.5, -.22, OSCURO),
                                       (3, 16.9, -.40, CLARO)]:
        ax.add_patch(FancyArrowPatch((CX[4] - .040, BY - .020),
                                     (CX[destino] + .020, BY - .020),
                                     connectionstyle=f"arc3,rad={rad}",
                                     arrowstyle="-|>", mutation_scale=11,
                                     color=color, lw=1.7, zorder=2))
        ax.text(CX[destino], .300, pct(valor), ha="center", va="center",
                fontsize=9, fontweight="bold", color=color, zorder=4)
    ax.text((CX[2] + CX[3]) / 2, .238, "salidas desde M1", ha="center",
            va="center", fontsize=7.5, style="italic", color=GRIS, zorder=4)

    ax.add_patch(FancyBboxPatch((.022, .035), .300, .112,
                                boxstyle="round,pad=0,rounding_size=.016",
                                facecolor="#F4F7FA", edgecolor="#DDE4EC", lw=.9))
    ax.text(.172, .121, "Desde M1, volver directo a M0 o M2", ha="center",
            va="center", fontsize=7, color=GRIS)
    ax.text(.172, .072, "4,3 %", ha="center", va="center", fontsize=12,
            fontweight="bold", color=OSCURO)

    ax.text(.672, .112, "Desde el estado severo la salida más frecuente pasa por M4.",
            ha="center", va="center", fontsize=8.3, color=TINTA)
    ax.text(.672, .055, "Cada paso son 5 minutos: recuperarse lleva varias ventanas.",
            ha="center", va="center", fontsize=8.3, color=TINTA)

    fig.savefig(salida, dpi=200, facecolor="white", bbox_inches="tight", pad_inches=.02)
    print("escrita:", salida)


if __name__ == "__main__":
    construir(sys.argv[1] if len(sys.argv) > 1
              else "notebooks/figuras/diapo_corredor_m.png")
