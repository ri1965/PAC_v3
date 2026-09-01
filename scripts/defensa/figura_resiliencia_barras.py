#!/usr/bin/env python3
"""
Figura de resiliencia post-evento severo para la d26 del mazo de defensa.

Rehace el grafico de barras apiladas con la LEYENDA CORREGIDA. El grafico
anterior decia "Vuelve a un estado protector", pero la metrica es
"ventana siguiente NO patologica" (CLAUDE.md, §22): incluye M4, que es
moderado, ni protector ni patologico.

Por que importaba: el panel derecho de la misma diapositiva muestra
"Volver directo a M0 o M2 = 4,3 %", que si es estrictamente protector.
Con la leyenda vieja quedaban dos frases equivalentes en castellano
--"vuelve a un estado protector"-- con 12,3 % y 4,3 % a veinte
centimetros de distancia.

Valores: NB05 §B4 / CLAUDE.md §22.

Uso:  figura_resiliencia_barras.py [salida.png]
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

plt.rcParams["font.family"] = "Carlito"

TEAL, ROJO, GRIS = "#16979E", "#C13C3C", "#D9E0E6"
TINTA, MARCO = "#1F2933", "#C9D2DA"

# escala, sale del estado patologico, sigue patologico
FILAS = [("S · 30 s", 43.3, 40.2),
         ("M · 5 min", 12.3, 80.4),
         ("L · 30 min", 1.3, 74.5)]


def construir(salida):
    fig = plt.figure(figsize=(6.6, 3.67), dpi=200)
    fig.patch.set_facecolor("white")
    fig.patches.append(FancyBboxPatch(
        (.006, .010), .988, .980, boxstyle="round,pad=0,rounding_size=.02",
        transform=fig.transFigure, facecolor="none", edgecolor=MARCO,
        linewidth=1.1, zorder=0))

    ax = fig.add_axes([.115, .130, .790, .700])
    ys = [2, 1, 0]

    for y, (_, sale, sigue) in zip(ys, FILAS):
        resto = 100 - sale - sigue
        ax.barh(y, sale, color=TEAL, height=.52, zorder=3)
        ax.barh(y, sigue, left=sale, color=ROJO, height=.52, zorder=3)
        ax.barh(y, resto, left=sale + sigue, color=GRIS, height=.52, zorder=3)

        # el 1,3 % no entra adentro de la barra: va afuera, a la derecha
        if sale >= 5:
            ax.text(sale / 2, y, f"{sale:.1f} %".replace(".", ","), ha="center",
                    va="center", color="white", fontsize=10, fontweight="bold", zorder=4)
        else:
            ax.text(101.5, y, f"{sale:.1f} %".replace(".", ","), ha="left",
                    va="center", color=TEAL, fontsize=10, fontweight="bold", zorder=4)
        ax.text(sale + sigue / 2, y, f"{sigue:.1f} %".replace(".", ","), ha="center",
                va="center", color="white", fontsize=10, fontweight="bold", zorder=4)

    ax.set_yticks(ys, [f[0] for f in FILAS], fontsize=9.5, fontweight="bold", color=TINTA)
    ax.set_xticks(range(0, 101, 25), ["0", "25 %", "50 %", "75 %", "100 %"],
                  fontsize=9, color=TINTA)
    ax.set_xlim(0, 100); ax.set_ylim(-.62, 2.62)
    ax.grid(axis="x", color="#EDF1F4", lw=.9, zorder=1)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#C9D2DA")
    ax.tick_params(length=0)

    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor=TEAL, label="Sale del estado patológico"),
                       Patch(facecolor=ROJO, label="Sigue en estado patológico"),
                       Patch(facecolor=GRIS, label="No hay ventana siguiente")],
              loc="lower left", bbox_to_anchor=(-.115, 1.02, 1.230, .12), mode="expand",
              ncol=3, frameon=False, handlelength=1.5, handleheight=.9,
              handletextpad=.6, columnspacing=1.2, fontsize=9, labelcolor=TINTA)

    fig.savefig(salida, dpi=200, facecolor="white")
    print("escrita:", salida)


if __name__ == "__main__":
    construir(sys.argv[1] if len(sys.argv) > 1
              else "notebooks/figuras/diapo_resiliencia_barras.png")
