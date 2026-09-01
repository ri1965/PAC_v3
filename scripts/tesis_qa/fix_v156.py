# -*- coding: utf-8 -*-
"""v155 -> v156: dos defectos del barrido visual (§33).

1. La linea de lugar y fecha de la caratula NO entraba en la pagina 1 y caia sola
   en la pagina 2, con encabezado, pie y numero de pagina. Es lo primero que ve el
   jurado. Se recupera espacio achicando dos espaciados grandes de la caratula,
   sin borrar parrafos ni cambiar el diseno.

2. Tres pies de figura (6.5, 6.11 y 7.2) quedaban al pie de una pagina y su figura
   arrancaba en la siguiente. Se marca 'mantener con el siguiente' (w:keepNext) en
   todos los pies de figura del cuerpo, para que no vuelva a pasar.

Uso: python3 scripts/tesis_qa/fix_v156.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v155.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v156.docx")

# (prefijo del parrafo, espacio_posterior_nuevo). Los valores viejos eran 600 y 480.
CARATULA = [("Tesis de Maestría", 360), ("Director:", 300)]

RE_PIE_FIGURA = re.compile(r"^Figura \d+\.\d+\.")


def tiene_imagen(p):
    return bool(p._p.findall(".//" + qn("w:drawing")))


def marcar_keep_next(p):
    pPr = p._p.get_or_add_pPr()
    if pPr.find(qn("w:keepNext")) is not None:
        return False
    pPr.insert(0, pPr.makeelement(qn("w:keepNext"), {}))
    return True


def arreglar_caratula(doc):
    n = 0
    for p in doc.paragraphs[:22]:
        for prefijo, nuevo in CARATULA:
            if not p.text.strip().startswith(prefijo):
                continue
            viejo = p.paragraph_format.space_after
            viejo = viejo.twips if viejo else 0
            if viejo <= nuevo:
                continue
            pPr = p._p.get_or_add_pPr()
            spacing = pPr.find(qn("w:spacing"))
            if spacing is None:
                spacing = pPr.makeelement(qn("w:spacing"), {})
                pPr.append(spacing)
            spacing.set(qn("w:after"), str(nuevo))
            print(f"  {prefijo!r}: espacio posterior {viejo} -> {nuevo} twips")
            n += 1
    return n


def arreglar_pies(doc):
    ps = doc.paragraphs
    n = 0
    for i, p in enumerate(ps):
        texto = p.text.strip()
        if "\t" in texto or not RE_PIE_FIGURA.match(texto):
            continue  # las entradas del indice llevan tabulacion
        # el pie va arriba de la figura: se busca la imagen en los parrafos siguientes
        for j in range(i + 1, min(i + 4, len(ps))):
            if tiene_imagen(ps[j]):
                if marcar_keep_next(p):
                    n += 1
                for k in range(i + 1, j):      # parrafos vacios intermedios
                    marcar_keep_next(ps[k])
                break
            if ps[j].text.strip():
                break                          # ya arranco otro texto: no es su figura
    return n


def quitar_pagina_blanca(doc):
    """Parrafo vacio con salto de pagina antes de 'Reconocimientos'.

    Ese parrafo ocupaba una pagina entera en blanco (con encabezado, pie y numero).
    Se elimina y el salto pasa a ser 'salto de pagina antes' del propio titulo.
    """
    ps = doc.paragraphs
    for i, p in enumerate(ps):
        if p.text.strip() != "Reconocimientos":
            continue
        previo = ps[i - 1]
        if previo.text.strip() or previo._p.find(".//" + qn("w:br")) is None:
            return 0
        pPr = p._p.get_or_add_pPr()
        if pPr.find(qn("w:pageBreakBefore")) is None:
            pPr.insert(0, pPr.makeelement(qn("w:pageBreakBefore"), {}))
        previo._p.getparent().remove(previo._p)
        print("  párrafo vacío eliminado; el salto pasa al título Reconocimientos")
        return 1
    return 0


def main():
    doc = Document(str(SRC))
    print("1. Carátula: recuperar espacio para la línea de lugar y fecha")
    a = arreglar_caratula(doc)
    print("2. Pies de figura: mantener con la figura")
    b = arreglar_pies(doc)
    print(f"  {b} pies marcados con keepNext")
    print("3. Página en blanco entre el Abstract y Reconocimientos")
    c = quitar_pagina_blanca(doc)
    doc.save(str(DST))
    print(f"\n{a} espaciados · {b} pies · {c} página en blanco · guardado: {DST}")


if __name__ == "__main__":
    main()
