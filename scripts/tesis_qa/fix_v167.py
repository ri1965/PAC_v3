# -*- coding: utf-8 -*-
"""v166 -> v167: reubica los siete marcadores cuyos enlaces caían fuera de destino.

Detectados por revisión manual del autor, uno por uno, sobre los tres índices.
El texto del documento NO se toca: solo se mueven marcadores (`w:bookmarkStart` /
`w:bookmarkEnd`), que son invisibles.

    marcador      caía en                              debe envolver
    ptr_4_1       §4.2.1 (justo tras el pie Fig 4.2)   ▸ Figura complementaria Fig. 4.1
    cap_f_4_2     antes de §4.2.2                      pie de la Figura 4.2
    cap_f_4_1     3 elementos antes                    pie de la Figura 4.1 (anexo)
    ptr_refrap    párrafo anterior al ▸                ▸ Tabla complementaria Tabla 1.2
    anx_trazab    la prosa previa al título            título de la Tabla 1.3 (anexo)
    cap_t_4_1     párrafo anterior al título           título de la Tabla 4.1
    cap_t_5_2     párrafo anterior al título           título de la Tabla 5.2

⚠ Un marcador que cae en el párrafo ANTERIOR al destino no se ve como error en el
XML: el enlace funciona, pero Word desplaza la vista dejando el destino fuera de
pantalla. Solo se detecta haciendo clic, que es lo que hizo el autor.

⚠ `cap_t_1_2` y `anx_refrap` quedan donde están: el autor verificó que esos dos
enlaces funcionan bien, y el criterio de esta pasada es tocar lo mínimo.

Uso: python3 scripts/tesis_qa/fix_v167.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v166.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v167.docx")

# marcador -> (patrón del párrafo destino, ¿es del cuerpo o del anexo?)
# El destino se identifica por su texto; 'orden' elige la aparición cuando hay dos
# (el pie del cuerpo y la entrada del índice, o el título del cuerpo y el del anexo).
DESTINOS = {
    "ptr_4_1":    r"^▸ Figura complementaria .*Fig\. 4\.1",
    "cap_f_4_2":  r"^Figura 4\.2\. Selección de K",
    "cap_f_4_1":  r"^Figura 4\.1\. Análisis de componentes",
    "ptr_refrap": r"^▸ Tabla complementaria .*Tabla 1\.2",
    "anx_trazab": r"^Tabla 1\.3\. Tabla de trazabilidad",
    "cap_t_4_1":  r"^Tabla 4\.1\. Distribución de la cohorte",
    "cap_t_5_2":  r"^Tabla 5\.2\. Especialización funcional",
}
# Para los que aparecen dos veces (índice y cuerpo/anexo), la buena es la ÚLTIMA:
# los índices van al principio del documento.
ULTIMA = {"cap_f_4_1", "anx_trazab"}


def texto_visible(el):
    """Solo w:t: deja afuera los instrText, que son código de campo."""
    return "".join(x.text or "" for x in el.iter(qn("w:t"))).strip()


def es_entrada_indice(el):
    return el.find(".//" + qn("w:tab")) is not None and \
        any("PAGEREF" in (x.text or "") for x in el.iter(qn("w:instrText")))


def main():
    doc = Document(str(SRC))
    body = doc.element.body

    # 1. localizar los párrafos destino
    destino = {}
    for nombre, patron in DESTINOS.items():
        rx = re.compile(patron)
        candidatos = [ch for ch in body
                      if ch.tag.endswith("}p")
                      and rx.match(texto_visible(ch))
                      and not es_entrada_indice(ch)]
        if not candidatos:
            raise RuntimeError(f"sin destino para {nombre}: {patron}")
        destino[nombre] = candidatos[-1] if nombre in ULTIMA else candidatos[0]

    # 2. mover cada marcador: se sacan start y end de donde estén y se reponen
    #    envolviendo el párrafo destino
    for nombre, par in destino.items():
        inicio = fin = None
        for b in body.iter(qn("w:bookmarkStart")):
            if b.get(qn("w:name")) == nombre:
                inicio = b
                break
        if inicio is None:
            raise RuntimeError(f"no existe el marcador {nombre}")
        bid = inicio.get(qn("w:id"))
        for b in body.iter(qn("w:bookmarkEnd")):
            if b.get(qn("w:id")) == bid:
                fin = b
                break
        origen = texto_visible(inicio.getparent())[:52] or "(elemento vacío)"
        inicio.getparent().remove(inicio)
        if fin is not None:
            fin.getparent().remove(fin)
        par.addprevious(inicio)
        par.addnext(fin if fin is not None else
                    body.makeelement(qn("w:bookmarkEnd"), {qn("w:id"): bid}))
        print(f"  {nombre:12s} de {origen[:46]!r}")
        print(f"  {'':12s} a  {texto_visible(par)[:46]!r}")

    doc.save(str(DST))
    print(f"\n{len(destino)} marcadores reubicados · guardado: {DST}")


if __name__ == "__main__":
    main()
