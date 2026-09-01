# -*- coding: utf-8 -*-
"""v159 -> v160: los cinco cambios pendientes del §36, en una sola pasada.

A. §3.1 · el parrafo de conflictos de interes baja de 5 oraciones a 2 (3 repetian
   lo que ya dicen los parrafos 1 y 2 de la misma seccion).
B. La tabla nueva pasa de 4.9 a 4.6 (orden de primera mencion), con cascada
   4.6->4.7, 4.7->4.8, 4.8->4.9. Se renumera el texto Y los marcadores.
C. §4.3.1 · se agrega el parrafo '▸ Tabla complementaria...', que faltaba.
D. Se crean las TRES anclas que usa cada tabla del anexo: cap_t_4_6 (destino del
   Indice de Tablas), anx_T4_6 (ida cuerpo->anexo) y ptr_T4_6 (vuelta anexo->cuerpo),
   mas el campo HYPERLINK del titulo en el anexo.
E. La entrada del Indice de Tablas apuntaba a cap_t_4_5: se corrige.

⚠ Renumerar de mayor a menor, o los reemplazos se pisan. La tabla nueva pasa
primero por un marcador temporal para no chocar con la 4.9 que se crea.

Uso: python3 scripts/tesis_qa/fix_v160.py <origen> <destino>
"""
import copy
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v159.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v160.docx")

TMP = "4.@@"

COI_VIEJO_INICIO = "Declaración de conflictos de interés y financiamiento."
COI_NUEVO = (
    "Declaración de conflictos de interés y financiamiento. El autor no recibió "
    "financiamiento del fabricante del SOMNI 6000 ni mantiene con él relación "
    "laboral, de consultoría ni de participación accionaria. El fabricante no "
    "participó en el diseño del análisis, en la interpretación de los resultados ni "
    "en la redacción de esta tesis, y no ejerció derecho de revisión previa sobre su "
    "contenido."
)

GLOSA_46 = " (análisis de sensibilidad de los pesos del ARI)."


def textos(doc):
    return list(doc.element.body.iter(qn("w:t"))) + \
           list(doc.element.body.iter(qn("w:instrText")))


def renumerar(doc, pares):
    """Reemplaza 'Tabla X' -> 'Tabla Y' y los marcadores cap_t_X -> cap_t_Y."""
    n = 0
    for el in textos(doc):
        if not el.text:
            continue
        nuevo = el.text
        for viejo, destino in pares:
            nuevo = nuevo.replace(f"Tabla {viejo}", f"Tabla {destino}")
            nuevo = nuevo.replace(f"cap_t_{viejo.replace('.', '_')}",
                                  f"cap_t_{destino.replace('.', '_')}")
        if nuevo != el.text:
            el.text = nuevo
            n += 1
    for atributo, tag in ((qn("w:name"), qn("w:bookmarkStart")),
                          (qn("w:anchor"), qn("w:hyperlink"))):
        for el in doc.element.body.iter(tag):
            v = el.get(atributo)
            if not v:
                continue
            nuevo = v
            for viejo, destino in pares:
                a, b = viejo.replace(".", "_"), destino.replace(".", "_")
                nuevo = nuevo.replace(f"cap_t_{a}", f"cap_t_{b}")
                nuevo = nuevo.replace(f"anx_T{a}", f"anx_T{b}")
                nuevo = nuevo.replace(f"ptr_T{a}", f"ptr_T{b}")
            if nuevo != v:
                el.set(atributo, nuevo)
                n += 1
    return n


def id_libre(doc):
    ids = [int(b.get(qn("w:id")) or 0) for b in doc.element.body.iter(qn("w:bookmarkStart"))]
    return max(ids) + 1 if ids else 1000


def marcador(doc, nombre, bid):
    ini = doc.element.body.makeelement(
        qn("w:bookmarkStart"), {qn("w:id"): str(bid), qn("w:name"): nombre})
    fin = doc.element.body.makeelement(qn("w:bookmarkEnd"), {qn("w:id"): str(bid)})
    return ini, fin


def envolver_en_hyperlink(par, ancla):
    """Mete el contenido del párrafo dentro de un campo HYPERLINK \\l 'ancla'."""
    p = par._p
    primero = next((r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None), None)
    if primero is None:
        return False
    def run(hijo):
        r = p.makeelement(qn("w:r"), {})
        r.append(hijo)
        return r
    begin = run(p.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "begin"}))
    instr = p.makeelement(qn("w:instrText"), {})
    instr.text = f'HYPERLINK \\l "{ancla}"'
    sep = run(p.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "separate"}))
    # orden natural: el ultimo insertado queda pegado al texto (§30)
    for nodo in (begin, run(instr), sep):
        primero.addprevious(nodo)
    ultimo = [r for r in p.iter(qn("w:r"))][-1]
    ultimo.addnext(run(p.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"})))
    return True


def main():
    doc = Document(str(SRC))
    body = doc.element.body

    # ---------- A · conflictos de interés
    coi = next((p for p in doc.paragraphs if p.text.strip().startswith(COI_VIEJO_INICIO)), None)
    if coi is None:
        raise RuntimeError("no se encontró el párrafo de conflictos de interés")
    runs = [r for r in coi._p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]
    runs[0].find(qn("w:t")).text = COI_NUEVO
    for r in runs[1:]:
        r.find(qn("w:t")).text = ""
    print(f"  A · §3.1: conflictos de interés, {len(COI_NUEVO.split('. '))} oraciones")

    # ---------- B · renumeración (de mayor a menor, con paso temporal)
    print("  B · renumeración por orden de mención:")
    for pares, etiqueta in (
            ([("4.9", TMP)], "4.9 (nueva) → temporal"),
            ([("4.8", "4.9")], "4.8 → 4.9"),
            ([("4.7", "4.8")], "4.7 → 4.8"),
            ([("4.6", "4.7")], "4.6 → 4.7"),
            ([(TMP, "4.6")], "temporal → 4.6")):
        print(f"      {etiqueta}: {renumerar(doc, pares)} elementos")

    # ---------- C+D+E · anclas y párrafo ▸ de la nueva Tabla 4.6
    bid = id_libre(doc)

    # título de la tabla en el anexo (ya renumerado a 4.6)
    titulo = next((p for p in doc.paragraphs
                   if p.text.strip().startswith("Tabla 4.6. Análisis de sensibilidad")
                   and "\t" not in p.text), None)
    if titulo is None:
        raise RuntimeError("no se encontró el título de la nueva tabla en el anexo")
    envolver_en_hyperlink(titulo, "ptr_T4_6")
    for nombre in ("anx_T4_6", "cap_t_4_6"):
        ini, fin = marcador(doc, nombre, bid)
        titulo._p.addprevious(ini)
        titulo._p.addnext(fin)
        bid += 1
    print("  D · anexo: anclas anx_T4_6 y cap_t_4_6 + campo HYPERLINK → ptr_T4_6")

    # párrafo ▸ en el cuerpo, clonando el de la Tabla 4.5
    ptr45 = next((p for p in doc.paragraphs
                  if p.text.strip().startswith("▸ Tabla complementaria")
                  and "Tabla 4.5" in p.text), None)
    if ptr45 is None:
        raise RuntimeError("no se encontró el párrafo ▸ de la Tabla 4.5")
    nuevo = copy.deepcopy(ptr45._p)
    for b in list(nuevo.iter(qn("w:bookmarkStart"))) + list(nuevo.iter(qn("w:bookmarkEnd"))):
        b.getparent().remove(b)
    for h in nuevo.iter(qn("w:hyperlink")):
        h.set(qn("w:anchor"), "anx_T4_6")
        for t in h.iter(qn("w:t")):
            if t.text and t.text.startswith("Tabla 4.5"):
                t.text = "Tabla 4.6"
    for t in nuevo.iter(qn("w:t")):
        if t.text and t.text.startswith(" (problema de escala"):
            t.text = GLOSA_46
    ini, fin = marcador(doc, "ptr_T4_6", bid)
    bid += 1
    nuevo.insert(0, ini)
    nuevo.append(fin)
    ptr45._p.addnext(nuevo)
    print("  C · §4.3.1: párrafo ▸ agregado, con marcador ptr_T4_6")

    # entrada del Índice de Tablas: apuntaba a cap_t_4_5
    idx = next((p for p in doc.paragraphs
                if "\t" in p.text and p.text.strip().startswith("Tabla 4.6. Análisis")), None)
    if idx is None:
        raise RuntimeError("no se encontró la entrada de índice de la nueva tabla")
    for h in idx._p.iter(qn("w:hyperlink")):
        h.set(qn("w:anchor"), "cap_t_4_6")
    for e in idx._p.iter(qn("w:instrText")):
        if e.text and "PAGEREF" in e.text:
            e.text = re.sub(r"PAGEREF\s+\S+", "PAGEREF cap_t_4_6", e.text)
    print("  E · Índice de Tablas: la entrada ya apunta a cap_t_4_6")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
