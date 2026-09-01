# -*- coding: utf-8 -*-
"""v150 -> v151: reconstruye el campo HYPERLINK de la entrada 4.4 del indice general.

fix_v150 saco el codigo de campo que se veia como texto, pero esa entrada tambien
habia perdido el campo HYPERLINK en si: quedaba en negro, sin enlace, mientras el
resto del indice va en azul. F9 la regeneraria, pero conviene que el .docx se vea
bien tambien antes de actualizar campos.

Estructura de una entrada sana del indice (TDC):

    fldChar begin | instrText HYPERLINK \\l "ancla" | fldChar separate
    run del titulo (rStyle Hipervnculo)
    tab | campo PAGEREF | fldChar end   <- cierra el HYPERLINK

Uso: python3 scripts/tesis_qa/fix_v151.py <origen> <destino>
"""
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v150.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v151.docx")

PREFIJO = "4.4  Síntesis de variables nocturnas"
ANCLA = "_Toc232926391"


def run_con(p, hijos):
    """Crea un w:r suelto (sin insertar) con los hijos indicados."""
    r = p._p.makeelement(qn("w:r"), {})
    for h in hijos:
        r.append(h)
    return r


def el(p, tag, attrs=None, texto=None):
    e = p._p.makeelement(qn("w:" + tag), attrs or {})
    if texto is not None:
        e.text = texto
    return e


def reconstruir(p, ancla):
    """Envuelve el contenido del parrafo en un campo HYPERLINK."""
    # el run del titulo es el primero que tiene w:t
    titulo = next(r for r in p._p.iter(qn("w:r")) if r.find(qn("w:t")) is not None)

    # 1. apertura del campo, antes del run del titulo
    inicio = run_con(p, [el(p, "fldChar", {qn("w:fldCharType"): "begin"})])
    instr = run_con(p, [el(p, "instrText", {}, f'HYPERLINK \\l "{ancla}"')])
    sep = run_con(p, [el(p, "fldChar", {qn("w:fldCharType"): "separate"})])
    # addprevious inserta siempre pegado al titulo, asi que el orden natural
    # (begin, instrText, separate) es el correcto: el ultimo queda mas cerca.
    for nodo in (inicio, instr, sep):
        titulo.addprevious(nodo)

    # 2. el titulo toma el estilo de hipervinculo
    rPr = titulo.find(qn("w:rPr"))
    if rPr is None:
        rPr = el(p, "rPr")
        titulo.insert(0, rPr)
    rPr.append(el(p, "rStyle", {qn("w:val"): "Hipervnculo"}))
    rPr.append(el(p, "noProof"))

    # 3. cierre del campo, despues del ultimo run del parrafo
    ultimo = [r for r in p._p.iter(qn("w:r"))][-1]
    ultimo.addnext(run_con(p, [el(p, "fldChar", {qn("w:fldCharType"): "end"})]))


def main():
    doc = Document(str(SRC))
    objetivo = None
    for p in doc.paragraphs:
        if p.style.name.lower().startswith("toc") and p.text.strip().startswith(PREFIJO):
            objetivo = p
            break
    if objetivo is None:
        raise RuntimeError(f"no se encontro la entrada {PREFIJO!r}")

    campos = [e.text for e in objetivo._p.iter(qn("w:instrText"))]
    if any("HYPERLINK" in (c or "") for c in campos):
        print("  ya tiene campo HYPERLINK, nada que hacer")
    else:
        reconstruir(objetivo, ANCLA)
        print(f"  campo HYPERLINK \\l \"{ANCLA}\" reconstruido")
        print(f"  campos ahora: {[e.text for e in objetivo._p.iter(qn('w:instrText'))]}")
        print(f"  texto: {objetivo.text.strip()[:70]!r}")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
