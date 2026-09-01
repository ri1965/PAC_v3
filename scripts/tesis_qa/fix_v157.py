# -*- coding: utf-8 -*-
"""v156 -> v157: tablas cortadas entre paginas (punto 5 del director).

Diagnostico sobre el PDF renderizado: 11 de 32 tablas se parten, y en varias el
titulo queda solo al pie de una pagina con todas las filas en la siguiente.

Las filas ya tenian `cantSplit` (ninguna se parte por la mitad) y el encabezado ya
se repetia. Faltaba lo otro:

1. `keepNext` en el parrafo de TITULO de cada tabla -> el titulo nunca queda huerfano.
2. `keepNext` en todas las filas menos la ultima, para las tablas de hasta 10 filas
   de datos -> la tabla entera viaja junta a la pagina siguiente si no entra.

Las tablas largas (1.1 con 20 filas, 1.2 con 16, 1.3 con 30) se dejan partir a
proposito: no entran en una pagina. Para ellas alcanza con el encabezado repetido,
que ya esta.

⚠ keepNext es una preferencia: si la tabla no entra en ninguna pagina, Word la parte
igual. Por eso es seguro aplicarlo.

Uso: python3 scripts/tesis_qa/fix_v157.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v156.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v157.docx")

MAX_FILAS_JUNTAS = 10          # por encima de esto, la tabla se deja partir
RE_TITULO = re.compile(r"^Tabla \d+\.\d+\.")


def bloques(doc):
    salida = []
    for ch in doc.element.body:
        if ch.tag.endswith("}tbl"):
            salida.append(("T", Table(ch, doc)))
        elif ch.tag.endswith("}p"):
            salida.append(("P", Paragraph(ch, doc)))
    return salida


def keep_next_parrafo(p):
    pPr = p._p.get_or_add_pPr()
    if pPr.find(qn("w:keepNext")) is not None:
        return False
    pPr.insert(0, pPr.makeelement(qn("w:keepNext"), {}))
    return True


def keep_next_fila(fila):
    """En una fila, keepNext va en el pPr de cada parrafo de cada celda."""
    tocado = False
    for celda in fila.cells:
        for p in celda.paragraphs:
            tocado = keep_next_parrafo(p) or tocado
    return tocado


def main():
    doc = Document(str(SRC))
    items = bloques(doc)
    titulos = juntas = sueltas = 0

    for k, (tipo, obj) in enumerate(items):
        if tipo != "T":
            continue
        # el titulo es el ultimo parrafo con texto antes de la tabla
        titulo = None
        for j in range(k - 1, max(-1, k - 4), -1):
            if items[j][0] == "P" and items[j][1].text.strip():
                titulo = items[j][1]
                break
        if titulo is None or not RE_TITULO.match(titulo.text.strip()):
            continue
        num = titulo.text.strip().split(".")[0] + "." + titulo.text.strip().split(".")[1]

        if keep_next_parrafo(titulo):
            titulos += 1

        datos = len(obj.rows) - 1
        if datos <= MAX_FILAS_JUNTAS:
            for fila in obj.rows[:-1]:      # la ultima no, o arrastra lo que sigue
                keep_next_fila(fila)
            juntas += 1
        else:
            sueltas += 1
            print(f"  {num}: {datos} filas de datos — se deja partir (encabezado repetido)")

    doc.save(str(DST))
    print(f"\n{titulos} títulos con keepNext · {juntas} tablas forzadas a viajar enteras · "
          f"{sueltas} largas sin tocar")
    print(f"guardado: {DST}")


if __name__ == "__main__":
    main()
