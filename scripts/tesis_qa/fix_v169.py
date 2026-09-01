# -*- coding: utf-8 -*-
"""v168 -> v169: tres marcadores que quedaron fuera de destino. Cambio quirúrgico.

Solo se mueven `w:bookmarkStart` / `w:bookmarkEnd`, que son invisibles. No se toca
ni una letra del texto, ni formato, ni tablas, ni márgenes.

    cap_t_1_3   ¶1050 -> envuelve ¶1054, el título de la Tabla 1.3 en el anexo
                (el enlace del Índice de Tablas caía 4 elementos antes)
    cap_t_1_2   ¶1044 -> envuelve ¶1047, el título de la Tabla 1.2 en el anexo
                (mismo desfase; se corrige por consistencia)
    ptr_trazab  ¶372  -> envuelve ¶372, el ▸ de la Tabla 1.3 en el cuerpo
                (estaba después del párrafo, no envolviéndolo)

⚠ Cada tabla del anexo usa TRES anclas y es fácil confundirlas (CLAUDE.md §36):
    cap_t_1_3   destino del Índice de Tablas      <- esta fallaba
    anx_trazab  ida cuerpo -> anexo               <- ya corregida en la v167
    ptr_trazab  vuelta anexo -> cuerpo
En la v167 se corrigió `anx_trazab` creyendo que era "la ida" que reportaba el autor;
la que fallaba era la del índice, que usa otra ancla.

⚠ `ptr_trazab` hoy no tiene efecto visible: el título de la Tabla 1.3 en el anexo
no tiene campo HYPERLINK de vuelta. Se deja bien ubicada por si se agrega.

Uso: python3 scripts/tesis_qa/fix_v169.py <origen> <destino>
"""
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v168.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v169.docx")

DESTINOS = {
    "cap_t_1_3":  "Tabla 1.3. Tabla de trazabilidad",
    "cap_t_1_2":  "Tabla 1.2. Referencia rápida",
    "ptr_trazab": "▸ Tabla complementaria en el Anexo Suplementario: Tabla 1.3",
}


def texto(el):
    return "".join(x.text or "" for x in el.iter(qn("w:t"))).strip()


def es_entrada_indice(el):
    """Las entradas de índice llevan tabulador y un campo PAGEREF."""
    return el.find(".//" + qn("w:tab")) is not None and \
        any("PAGEREF" in (x.text or "") for x in el.iter(qn("w:instrText")))


def main():
    doc = Document(str(SRC))
    body = doc.element.body

    for nombre, prefijo in DESTINOS.items():
        objetivo = [ch for ch in body
                    if ch.tag.endswith("}p")
                    and texto(ch).startswith(prefijo)
                    and not es_entrada_indice(ch)]
        if len(objetivo) != 1:
            raise RuntimeError(f"{nombre}: {len(objetivo)} destinos para {prefijo!r}")
        par = objetivo[0]

        inicio = next((b for b in body.iter(qn("w:bookmarkStart"))
                       if b.get(qn("w:name")) == nombre), None)
        if inicio is None:
            raise RuntimeError(f"no existe el marcador {nombre}")
        bid = inicio.get(qn("w:id"))
        fin = next((b for b in body.iter(qn("w:bookmarkEnd"))
                    if b.get(qn("w:id")) == bid), None)

        antes = texto(inicio.getparent())[:44] if inicio.getparent().tag.endswith("}p") \
            else "(nivel de cuerpo)"
        inicio.getparent().remove(inicio)
        if fin is not None:
            fin.getparent().remove(fin)
        par.addprevious(inicio)
        par.addnext(fin if fin is not None else
                    body.makeelement(qn("w:bookmarkEnd"), {qn("w:id"): bid}))
        print(f"  {nombre:12s} de {antes!r}")
        print(f"  {'':12s} a  {texto(par)[:52]!r}")

    doc.save(str(DST))
    print(f"\n{len(DESTINOS)} marcadores reubicados · guardado: {DST}")


if __name__ == "__main__":
    main()
