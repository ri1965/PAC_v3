# -*- coding: utf-8 -*-
"""v152 -> v153: ninguna columna mas angosta que su propio encabezado.

Mismo defecto que las Tablas 4.4 (§29), 6.4 y 6.7: Word parte el encabezado a mitad
de palabra ('Sensibilid/ad', 'Umbr/al', 'Componen/te').

Contar caracteres no sirve como proxy: las letras tienen anchos muy distintos
('Sensibilidad' entra en 1560 twips y 'Umbral', mucho mas corta, se parte en 992).
Por eso el ancho de cada palabra se calcula con anchos por caracter MEDIDOS sobre el
PDF renderizado (`anchos_caracter.json`, error medio 28 twips), no estimados.

Regla: solo se ENSANCHA. Una columna que hoy anda no se toca, y lo que falta sale
de las columnas con holgura, a prorrata. Si no alcanza, se reporta: esa tabla
necesita que se acorte el encabezado (es el caso de las tablas mas densas).

Uso: python3 scripts/tesis_qa/fix_v153.py <origen> <destino>
"""
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

AQUI = Path(__file__).parent
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v152.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v153.docx")

ANCHO_CARACTER = json.loads((AQUI / "anchos_caracter.json").read_text())
PADDING_CELDA = 216  # margen izquierdo + derecho de celda (108 + 108, default de Word)
FALLBACK = 145       # caracteres no medidos


def ancho_texto(s):
    return sum(ANCHO_CARACTER.get(c, FALLBACK) for c in s)


def trozos(texto):
    """Fragmentos que Word NO puede partir.

    Se corta por espacio normal, guion y barra (ahi Word envuelve sin que se note),
    pero NO por espacio duro ni angosto: '20,3 %' viaja junto y necesita su ancho.
    """
    for pedazo in re.split(r"[ \t\n]+", texto):
        for sub in re.split(r"(?<=[-/])", pedazo):
            if sub:
                yield sub


def ancho_palabra_mas_ancha(texto):
    return max((ancho_texto(t) for t in trozos(texto)), default=0)


def bloques(doc):
    salida = []
    for ch in doc.element.body:
        if ch.tag.endswith("}tbl"):
            salida.append(("T", Table(ch, doc)))
        elif ch.tag.endswith("}p"):
            salida.append(("P", Paragraph(ch, doc)))
    return salida


def reparto(tabla):
    grid = tabla._tbl.find(qn("w:tblGrid"))
    actuales = [int(g.get(qn("w:w"))) for g in grid]
    total = sum(actuales)

    minimos = []
    for i in range(len(actuales)):
        encabezado = ancho_palabra_mas_ancha(tabla.rows[0].cells[i].text)
        datos = max((ancho_palabra_mas_ancha(f.cells[i].text)
                     for f in tabla.rows[1:]), default=0)
        minimos.append(int(max(encabezado, datos)) + PADDING_CELDA)
    faltantes = [max(0, m - a) for a, m in zip(actuales, minimos)]
    if not any(faltantes):
        return actuales, actuales, minimos

    holguras = [max(0, a - m) for a, m in zip(actuales, minimos)]
    necesito = sum(faltantes)
    if sum(holguras) < necesito:
        return None, actuales, minimos

    nuevos = [a + f - (int(necesito * h / sum(holguras)) if h else 0)
              for a, f, h in zip(actuales, faltantes, holguras)]
    nuevos[-1] += total - sum(nuevos)
    return nuevos, actuales, minimos


def fijar_anchos(tabla, anchos):
    grid = tabla._tbl.find(qn("w:tblGrid"))
    for col, ancho in zip(grid, anchos):
        col.set(qn("w:w"), str(ancho))
    for fila in tabla.rows:
        for celda, ancho in zip(fila.cells, anchos):
            tcPr = celda._tc.get_or_add_tcPr()
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcPr.append(tcPr.makeelement(
                    qn("w:tcW"), {qn("w:w"): str(ancho), qn("w:type"): "dxa"}))
            else:
                tcW.set(qn("w:w"), str(ancho))
                tcW.set(qn("w:type"), "dxa")


def main():
    doc = Document(str(SRC))
    items = bloques(doc)
    hechas, sin_lugar = 0, []
    for k, (tipo, obj) in enumerate(items):
        if tipo != "T":
            continue
        previos = [items[j][1].text.strip() for j in range(max(0, k - 3), k)
                   if items[j][0] == "P" and items[j][1].text.strip()]
        titulo = previos[-1] if previos else "(sin título)"
        nuevos, actuales, minimos = reparto(obj)
        if nuevos is None:
            sin_lugar.append((titulo, sum(minimos), sum(actuales),
                              [c.text.strip() for c in obj.rows[0].cells]))
            continue
        if nuevos == actuales:
            continue
        fijar_anchos(obj, nuevos)
        print(f"  {titulo[:56]}\n    {actuales} -> {nuevos}")
        hechas += 1

    if sin_lugar:
        print("\n  ── no entran: hay que acortar el encabezado ──")
        for titulo, pide, hay, hdr in sin_lugar:
            print(f"  {titulo[:56]}\n    pide {pide}, hay {hay} · {hdr}")

    doc.save(str(DST))
    print(f"\n{hechas} tablas ensanchadas · {len(sin_lugar)} sin lugar · guardado: {DST}")


if __name__ == "__main__":
    main()
