# -*- coding: utf-8 -*-
"""v148 -> v149: encabezados de la Tabla 4.4 partidos a mitad de palabra.

Las columnas 1 y 3 de la Tabla 4.4 eran unos puntos mas angostas que sus propios
encabezados a 12 pt, asi que Word los parte: 'Morfotip/o' e 'Interpretació/n'.
El ancho sobrante se toma de la ultima columna, que tiene holgura.

Ademas: la entrada de la Tabla 1.1 en el Indice de Tablas estaba en 10 pt
mientras el resto del indice va en 12 pt.

Uso: python3 scripts/tesis_qa/fix_v149.py
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).parent))

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v148.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v149.docx")

# Tabla 4.4: [Morfotipo, ICC(1,1), Interpretacion, Observacion]. Suma = 9000.
ANCHOS_4_4 = [1450, 1299, 2150, 4101]


def bloques(doc):
    """Pares (tipo, objeto) del cuerpo, en orden."""
    salida = []
    for ch in doc.element.body:
        if ch.tag.endswith("}tbl"):
            salida.append(("T", Table(ch, doc)))
        elif ch.tag.endswith("}p"):
            salida.append(("P", Paragraph(ch, doc)))
    return salida


def tabla_por_titulo(doc, prefijo):
    """La tabla cuyo parrafo de titulo (arriba) empieza con `prefijo`."""
    items = bloques(doc)
    for k, (tipo, obj) in enumerate(items):
        if tipo != "T":
            continue
        previos = [items[j][1].text.strip() for j in range(max(0, k - 3), k)
                   if items[j][0] == "P" and items[j][1].text.strip()]
        if previos and previos[-1].startswith(prefijo):
            return obj
    return None


def fijar_anchos(tabla, anchos):
    """Reescribe tblGrid y el tcW de cada celda. Devuelve los anchos previos."""
    grid = tabla._tbl.find(qn("w:tblGrid"))
    previos = [int(g.get(qn("w:w"))) for g in grid]
    for col, ancho in zip(grid, anchos):
        col.set(qn("w:w"), str(ancho))
    for fila in tabla.rows:
        for celda, ancho in zip(fila.cells, anchos):
            tcW = celda._tc.get_or_add_tcPr().find(qn("w:tcW"))
            if tcW is None:
                tcW = celda._tc.tcPr.makeelement(
                    qn("w:tcW"), {qn("w:w"): str(ancho), qn("w:type"): "dxa"})
                celda._tc.tcPr.append(tcW)
            else:
                tcW.set(qn("w:w"), str(ancho))
                tcW.set(qn("w:type"), "dxa")
    return previos


def normalizar_indice_tabla_1_1(doc):
    """Saca el sz=20 (10 pt) de la entrada de la Tabla 1.1 en el Indice de Tablas."""
    n = 0
    for p in doc.paragraphs:
        texto = p.text.strip()
        if "\t" not in texto or not re.match(r"^Tabla 1\.1\.", texto):
            continue
        for r in p._p.iter(qn("w:r")):
            rPr = r.find(qn("w:rPr"))
            if rPr is None:
                continue
            for tag in ("sz", "szCs"):
                el = rPr.find(qn("w:" + tag))
                if el is not None:
                    rPr.remove(el)
                    n += 1
    return n


def main():
    doc = Document(str(SRC))

    print("1. Tabla 4.4 - encabezados partidos a mitad de palabra")
    t44 = tabla_por_titulo(doc, "Tabla 4.4.")
    if t44 is None:
        raise RuntimeError("no se encontro la Tabla 4.4")
    previos = fijar_anchos(t44, ANCHOS_4_4)
    print(f"  encabezados: {[c.text.strip() for c in t44.rows[0].cells]}")
    print(f"  anchos {previos} -> {ANCHOS_4_4}  (suma {sum(ANCHOS_4_4)})")

    print("2. Indice de Tablas - entrada de la Tabla 1.1 en 10 pt")
    n = normalizar_indice_tabla_1_1(doc)
    print(f"  {n} propiedades de tamano eliminadas (queda en 12 pt como el resto)")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
