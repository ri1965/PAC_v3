#!/usr/bin/env python3
"""
Carga las notas del orador del .pptx a partir del generador del guion.

Se alimenta de la MISMA fuente que build_guion.py (ORDEN, NUEVAS, EXTRAS y
las entradas heredadas de la v4), asi que el guion y las notas no pueden
divergir: cuando cambia uno, se vuelve a correr esto y listo.

QUE PONE en cada diapositiva
  · numero, nombre y tiempo asignado
  · los puntos de apoyo (hasta 5)
  · las cifras exactas, si la entrada las tiene (hasta 4)
  · el remate, leido de la propia diapositiva

QUE NO PONE, a proposito
  · el bloque "Que decir": el texto hablado literal en la vista del
    presentador es una trampa -- cuando el nervio aprieta, se lee.
  · las advertencias del guion: las notas VIAJAN DENTRO DEL ARCHIVO, y hay
    material que no conviene que circule sin el autor delante.

Uso:  notas_desde_guion.py <v4.docx> <entrada.pptx> <salida.pptx>
"""
import re
import sys
from pathlib import Path

from pptx import Presentation

sys.path.insert(0, str(Path(__file__).parent))
import build_guion as G

MAX_APOYO, MAX_CIFRA, MAX_CHARS = 5, 4, 155


def primera_oracion(t):
    """Las notas del guion son prosa; en la vista del presentador solo entra
    la primera oración."""
    partes = re.split(r"(?<=[.:;?!])\s+", t)
    o = partes[0].strip()
    if o.endswith(":") and len(partes) > 1:   # los dos puntos anuncian: sin lo que sigue no dice nada
        o = (o + " " + partes[1]).strip()
    o = o.strip(" .")
    return (o[:MAX_CHARS - 1] + "…") if len(o) > MAX_CHARS else (o if len(o) > 12 else t)


def limpio_largo(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def limpio(t):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`(.+?)`", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_CHARS - 1] + "…" if len(t) > MAX_CHARS else t


def secciones(bloques):
    """(apoyos, cifras) leyendo los rotulos. Tres niveles de respaldo para las
    entradas heredadas de la v4, que no siempre traen el esquema de 4 bloques."""
    apoyo, cifra, sueltos, prosas, actual = [], [], [], [], None
    for rol, txt in bloques:
        if rol == "rotulo":
            b = txt.lower()
            actual = "apoyo" if ("punto" in b and "apoyo" in b) else \
                     "cifra" if "cifra" in b else None
            continue
        if rol not in ("vineta", "nota", "prosa"):
            continue
        t = limpio(txt)
        if not t or t.startswith(("⚠", "📌")):
            continue
        if actual == "apoyo":
            apoyo.append(t)
        elif actual == "cifra":
            cifra.append(t)
        elif rol == "prosa":
            prosas.append(txt)          # sin recortar: se parte en oraciones
        elif rol == "nota":
            sueltos.append(primera_oracion(t))
        else:
            sueltos.append(t)

    if not apoyo:
        apoyo = sueltos[:MAX_APOYO]
    if not apoyo:                        # entradas que solo tienen texto hablado
        for pr in prosas:                # se digiere en oraciones, no se copia entero
            for orac in re.split(r"(?<=[.:;?!])\s+", limpio_largo(pr)):
                orac = orac.strip(" .")
                if len(orac) > 12:
                    apoyo.append(orac[:MAX_CHARS])
                if len(apoyo) >= MAX_APOYO:
                    break
            if len(apoyo) >= MAX_APOYO:
                break
    return apoyo[:MAX_APOYO], cifra[:MAX_CIFRA]


def remate_de(slide):
    """El remate vive en el pie de la diapositiva. Los anchos varian mucho
    -- de 4,2" a 12,2" -- y algunas diapositivas tienen dos."""
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = re.sub(r"\s+", " ", sh.text_frame.text.strip().replace("\n", " "))
        if len(t) < 40:
            continue
        if t.startswith("Proyecto PAC · Tesis"):
            continue
        if "Universidad Austral" in t and "Agosto" in t:
            continue
        runs = [r for pr in sh.text_frame.paragraphs for r in pr.runs if r.text.strip()]
        if runs and all(r.font.italic for r in runs):
            continue                     # aparato: nota al pie, no remate
        if (sh.top or 0) / 914400 > 5.25:
            out.append(t)
    return "  ·  ".join(out) if out else None


def main():
    plantilla, entrada, salida = sys.argv[1], sys.argv[2], sys.argv[3]
    g = G.Guion(plantilla)
    prs = Presentation(entrada)

    orden = [(n, nom, t, o) for _, _, ds in G.ORDEN for n, nom, t, o in ds]
    if len(orden) != len(prs.slides):
        print(f"⚠ el guion tiene {len(orden)} entradas y el mazo {len(prs.slides)} "
              f"diapositivas — revisar ORDEN antes de seguir")
        sys.exit(1)

    for (num, nombre, tiempo, origen), slide in zip(orden, prs.slides):
        bloques = list(G.NUEVAS[num] if num in G.NUEVAS else g.entradas[origen])
        bloques += G.EXTRAS.get(num, [])
        apoyo, cifra = secciones(bloques)

        linea = [f"d{num} · {nombre} · {tiempo}", "─" * 34]
        linea += [f"• {a}" for a in apoyo]
        if cifra:
            linea += ["", "CIFRAS"] + [f"· {c}" for c in cifra]
        r = remate_de(slide)
        if r:
            linea += ["", f"REMATE   «{r}»"]

        slide.notes_slide.notes_text_frame.text = "\n".join(linea)
        print(f"  d{num:<2} {len(apoyo)} apoyos · {len(cifra)} cifras · "
              f"{'remate' if r else 'sin remate'}")

    prs.save(salida)
    print("\nescrito:", salida)


if __name__ == "__main__":
    main()
