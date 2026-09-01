# -*- coding: utf-8 -*-
"""v151 -> v152: encabezados partidos a mitad de palabra en las Tablas 6.4 y 6.7.

Mismo defecto que la Tabla 4.4 (§29), detectado renderizando:

  Tabla 6.4  'Frac. M1 (sever/o)', 'Frac. M3 (antesal/a)', 'Entropí/a M'
  Tabla 6.7  'Average Precisio/n'

La 6.7 se arregla solo con anchos. La 6.4 tiene 7 columnas y ningun reparto alcanza,
asi que las glosas del encabezado ('(severo)', '(antesala)') pasan a la nota, que es
lo que pide APA: encabezado corto, aclaracion debajo.

Uso: python3 scripts/tesis_qa/fix_v152.py <origen> <destino>
"""
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import para_replace  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v151.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v152.docx")

# Encabezados que se acortan (solo en la fila de encabezado de la Tabla 6.4).
ENCABEZADOS_6_4 = {"Frac. M1 (severo)": "Frac. M1", "Frac. M3 (antesala)": "Frac. M3"}

# Suma 9000 en ambos casos, como el resto de las tablas del documento.
ANCHOS_6_4 = [1750, 1120, 1120, 1300, 1250, 1000, 1460]
ANCHOS_6_7 = [1752, 1159, 1505, 1417, 1560, 1607]

GLOSA = ("Frac. M1 y Frac. M3 son las fracciones nocturnas de los estados M1 "
         "(severo) y M3 (antesala). ")


def bloques(doc):
    salida = []
    for ch in doc.element.body:
        if ch.tag.endswith("}tbl"):
            salida.append(("T", Table(ch, doc)))
        elif ch.tag.endswith("}p"):
            salida.append(("P", Paragraph(ch, doc)))
    return salida


def buscar(doc, prefijo):
    """Devuelve (tabla, parrafo_de_nota) para el titulo que empieza con `prefijo`."""
    items = bloques(doc)
    for k, (tipo, obj) in enumerate(items):
        if tipo != "T":
            continue
        previos = [items[j][1].text.strip() for j in range(max(0, k - 3), k)
                   if items[j][0] == "P" and items[j][1].text.strip()]
        if not previos or not previos[-1].startswith(prefijo):
            continue
        nota = next((items[j][1] for j in range(k + 1, min(len(items), k + 4))
                     if items[j][0] == "P"
                     and items[j][1].text.strip().startswith("Nota.")), None)
        return obj, nota
    return None, None


def fijar_anchos(tabla, anchos):
    grid = tabla._tbl.find(qn("w:tblGrid"))
    previos = [int(g.get(qn("w:w"))) for g in grid]
    for col, ancho in zip(grid, anchos):
        col.set(qn("w:w"), str(ancho))
    for fila in tabla.rows:
        for celda, ancho in zip(fila.cells, anchos):
            tcPr = celda._tc.get_or_add_tcPr()
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcW = tcPr.makeelement(qn("w:tcW"),
                                       {qn("w:w"): str(ancho), qn("w:type"): "dxa"})
                tcPr.append(tcW)
            else:
                tcW.set(qn("w:w"), str(ancho))
                tcW.set(qn("w:type"), "dxa")
    return previos


def main():
    doc = Document(str(SRC))

    print("1. Tabla 6.4")
    t64, nota64 = buscar(doc, "Tabla 6.4.")
    if t64 is None:
        raise RuntimeError("no se encontro la Tabla 6.4")
    for celda in t64.rows[0].cells:
        viejo = celda.text.strip()
        if viejo in ENCABEZADOS_6_4:
            for p in celda.paragraphs:
                if para_replace(p, viejo, ENCABEZADOS_6_4[viejo]):
                    print(f"  encabezado {viejo!r} -> {ENCABEZADOS_6_4[viejo]!r}")
    print(f"  anchos {fijar_anchos(t64, ANCHOS_6_4)} -> {ANCHOS_6_4}")
    if nota64 is not None and "Frac. M1 y Frac. M3" not in nota64.text:
        para_replace(nota64, "Nota. ", "Nota. " + GLOSA)
        print("  glosa movida a la nota")

    print("2. Tabla 6.7")
    t67, _ = buscar(doc, "Tabla 6.7.")
    if t67 is None:
        raise RuntimeError("no se encontro la Tabla 6.7")
    print(f"  anchos {fijar_anchos(t67, ANCHOS_6_7)} -> {ANCHOS_6_7}")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
