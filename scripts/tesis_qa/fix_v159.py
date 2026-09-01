# -*- coding: utf-8 -*-
"""v158 -> v159: respuesta a las dos criticas accionables del arbitraje externo (§35).

CAMBIO 1 · §3.1, al final (despues del parrafo del NightRecordID)
    Nuevo parrafo: 'Declaracion de conflictos de interes y financiamiento'.
    Vinculo con el fabricante confirmado por el autor: ninguno.

CAMBIO 2 · §4.3.1, parrafo de ortogonalidad
    Se agrega una oracion: la ortogonalidad es propiedad de la ponderacion elegida,
    no un rasgo estructural del indice. Remite a la nueva Tabla 4.9.

CAMBIO 3 · Anexo C, despues de la Tabla 4.5
    Nueva Tabla 4.9 con el analisis de sensibilidad de los pesos del ARI, calculado
    sobre gold/events.parquet (85.277 EDOs). La tabla se construye copiando la
    Tabla 4.5, para heredar bordes, sombreado, cantSplit, tblHeader y tipografia.

CAMBIO 4 · Indice de Tablas
    Entrada de la Tabla 4.9. El indice es texto escrito a mano (§27): no se
    regenera con F9, hay que agregarla.

Uso: python3 scripts/tesis_qa/fix_v159.py <origen> <destino>
"""
import copy
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import para_replace  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v158.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v159.docx")

ANCLA_31 = "Dentro del pipeline PAC_v3, ese código de paciente se enmascara"

COI = (
    "Declaración de conflictos de interés y financiamiento. Los registros analizados "
    "provienen del protocolo CLP-275001, patrocinado por el fabricante del SOMNI 6000. "
    "El autor no participó en el diseño de ese protocolo ni en la recolección de los "
    "datos: la fase analítica objeto de esta tesis es retrospectiva e independiente, y "
    "se realizó sobre registros previamente recolectados y anonimizados. El autor no "
    "recibió financiamiento del fabricante ni mantiene con él relación laboral, de "
    "consultoría ni de participación accionaria. El fabricante no participó en el "
    "diseño del análisis, en la interpretación de los resultados ni en la redacción de "
    "esta tesis, y no ejerció derecho de revisión previa sobre su contenido."
)

ORTO_VIEJO = ("La percentilización de cada componente evita que el de mayor escala "
              "domine el índice (▸ Tabla 4.5, Anexo Suplementario).")
ORTO_NUEVO = (
    "La percentilización de cada componente evita que el de mayor escala domine el "
    "índice (▸ Tabla 4.5, Anexo Suplementario). Esta ortogonalidad debería leerse como "
    "una propiedad de la ponderación adoptada y no como un rasgo estructural del "
    "índice: un análisis de sensibilidad sobre los pesos (▸ Tabla 4.9, Anexo "
    "Suplementario) sugiere que la correlación con la profundidad de caída cruza el "
    "cero en las cercanías de 0,6/0,4, mientras que el gradiente inverso del C5 —el "
    "hallazgo fisiológico— se mantendría en todo el rango en que la señal cardíaca "
    "pesa al menos tanto como el movimiento."
)

TITULO_49 = ("Tabla 4.9. Análisis de sensibilidad de los pesos del ARI "
             "(N = 85.277 EDOs).")
NOTA_49 = (
    "Nota. Pesos: ponderación de hr_gain y mov_gain; 0,6 / 0,4 es la adoptada. Cada "
    "fila recalcula el ARI completo con esa ponderación, sobre el "
    "mismo corpus y sin ningún otro cambio. ρ con drop_pct: ortogonalidad respecto de "
    "la severidad del evento. ARI de C5: media del morfotipo más severo; C5 conserva "
    "el ARI más bajo del corpus —el gradiente inverso— en las cinco primeras filas, y "
    "deja de hacerlo cuando el movimiento pesa más que la señal cardíaca. ρ con el "
    "ARI canónico: correlación de Spearman entre cada variante y la definición "
    "adoptada. ICC noche: estabilidad inter-noche del ARI "
    "promedio por paciente, que alcanza su máximo en la ponderación adoptada. "
    "Fuente: capa Gold del Proyecto PAC."
)

ENCABEZADOS_49 = ["Pesos", "ρ drop_pct", "ARI C5", "ρ canónico", "ICC noche"]
FILAS_49 = [
    ["1,0 / 0,0", "−0,14", "0,26", "0,82", "0,56"],
    ["0,8 / 0,2", "−0,08", "0,34", "0,93", "0,65"],
    ["0,7 / 0,3", "−0,03", "0,38", "0,98", "0,69"],
    ["0,6 / 0,4", "0,03", "0,42", "1,00", "0,71"],
    ["0,5 / 0,5", "0,11", "0,46", "0,97", "0,70"],
    ["0,4 / 0,6", "0,19", "0,50", "0,88", "0,67"],
    ["0,0 / 1,0", "0,29", "0,66", "0,45", "0,46"],
]
ANCHOS_49 = [1900, 1900, 1500, 1900, 1800]   # suma 9000


def clonar_parrafo_limpio(origen, texto):
    """Clona un párrafo y le pone `texto`, descartando campos y marcadores.

    ⚠ No alcanza con 'dejar solo el primer run': si ese run contiene un `fldChar
    begin` (los títulos de tabla lo tienen), el clon queda con un campo sin cerrar
    y Word y LibreOffice se tragan todo lo que sigue — la tabla desaparece del
    render aunque esté en el XML. Hay que quedarse con el formato y tirar la
    maquinaria de campo.
    """
    nuevo = copy.deepcopy(origen)

    # rPr del primer run que realmente lleve texto (ese tiene el formato bueno)
    rPr = None
    for r in nuevo.iter(qn("w:r")):
        if r.find(qn("w:t")) is not None:
            encontrado = r.find(qn("w:rPr"))
            if encontrado is not None:
                rPr = copy.deepcopy(encontrado)
            break

    for hijo in list(nuevo):
        if hijo.tag in (qn("w:r"), qn("w:hyperlink"), qn("w:bookmarkStart"),
                        qn("w:bookmarkEnd"), qn("w:fldSimple")):
            nuevo.remove(hijo)

    run = nuevo.makeelement(qn("w:r"), {})
    if rPr is not None:
        run.append(rPr)
    t = run.makeelement(qn("w:t"), {qn("xml:space"): "preserve"})
    t.text = texto
    run.append(t)
    nuevo.append(run)
    return nuevo


def parrafo_que_empieza(doc, prefijo, con_tab=False):
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith(prefijo) and (("\t" in t) == con_tab):
            return p
    return None


def texto_de_celda(celda, texto):
    """Reescribe la celda conservando el formato del primer run."""
    p = celda.paragraphs[0]
    if not p.runs:
        p.add_run(texto)
        return
    p.runs[0].text = texto
    for r in p.runs[1:]:
        r.text = ""


def clonar_tabla_45(doc):
    """Copia la Tabla 4.5 (5 columnas) y la deja con 7 filas de datos."""
    from docx.table import Table
    titulo = None
    for i, ch in enumerate(doc.element.body):
        if ch.tag.endswith("}tbl"):
            t = Table(ch, doc)
            if t.rows and len(t.columns) == 5:
                # el titulo es el parrafo previo con texto
                j = i - 1
                while j >= 0 and not "".join(doc.element.body[j].itertext()).strip():
                    j -= 1
                if "".join(doc.element.body[j].itertext()).strip().startswith("Tabla 4.5."):
                    titulo = (j, i, t)
                    break
    if titulo is None:
        raise RuntimeError("no se encontró la Tabla 4.5")
    return titulo


def main():
    doc = Document(str(SRC))
    body = doc.element.body

    # ---- CAMBIO 1: declaración de conflictos de interés al final de §3.1
    ancla = parrafo_que_empieza(doc, ANCLA_31)
    if ancla is None:
        raise RuntimeError("no se encontró el final de §3.1")
    ancla._p.addnext(clonar_parrafo_limpio(ancla._p, COI))
    print("  CAMBIO 1 · §3.1: párrafo de conflictos de interés insertado")

    # ---- CAMBIO 2: matiz de ortogonalidad en §4.3.1
    orto = next((p for p in doc.paragraphs if ORTO_VIEJO in p.text), None)
    if orto is None:
        raise RuntimeError("no se encontró el párrafo de ortogonalidad")
    para_replace(orto, ORTO_VIEJO, ORTO_NUEVO)
    print("  CAMBIO 2 · §4.3.1: matiz de sensibilidad agregado")

    # ---- CAMBIO 3: Tabla 4.9 en el Anexo, clonando la 4.5
    j_tit, i_tbl, t45 = clonar_tabla_45(doc)
    p_titulo_45 = body[j_tit]
    tbl45 = body[i_tbl]
    # la nota es el primer parrafo con texto despues de la tabla
    k = i_tbl + 1
    while not "".join(body[k].itertext()).strip():
        k += 1
    p_nota_45 = body[k]

    nueva_tbl = copy.deepcopy(tbl45)
    filas = nueva_tbl.findall(qn("w:tr"))
    plantilla = copy.deepcopy(filas[1])
    for extra in filas[1:]:
        nueva_tbl.remove(extra)
    for _ in FILAS_49:
        nueva_tbl.append(copy.deepcopy(plantilla))

    from docx.table import Table
    tabla = Table(nueva_tbl, doc)
    for celda, txt in zip(tabla.rows[0].cells, ENCABEZADOS_49):
        texto_de_celda(celda, txt)
    for fila, datos in zip(tabla.rows[1:], FILAS_49):
        for celda, txt in zip(fila.cells, datos):
            texto_de_celda(celda, txt)

    # sin justificar: el justificado estira los encabezados y los vuelve ilegibles.
    # ⚠ hay que usar la API de python-docx: w:jc tiene una posición fija dentro de
    # w:pPr y agregarlo al final invalida el XML (Word descarta el contenido).
    for fila in tabla.rows:
        for celda in fila.cells:
            for par in celda.paragraphs:
                par.alignment = WD_ALIGN_PARAGRAPH.LEFT

    grid = nueva_tbl.find(qn("w:tblGrid"))
    for col, w in zip(grid, ANCHOS_49):
        col.set(qn("w:w"), str(w))
    for fila in tabla.rows:
        for celda, w in zip(fila.cells, ANCHOS_49):
            tcPr = celda._tc.get_or_add_tcPr()
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcPr.append(tcPr.makeelement(
                    qn("w:tcW"), {qn("w:w"): str(w), qn("w:type"): "dxa"}))
            else:
                tcW.set(qn("w:w"), str(w))
                tcW.set(qn("w:type"), "dxa")

    p_nota_49 = clonar_parrafo_limpio(p_nota_45, NOTA_49)
    p_tit_49 = clonar_parrafo_limpio(p_titulo_45, TITULO_49)
    p_nota_45.addnext(p_nota_49)
    p_nota_45.addnext(nueva_tbl)
    p_nota_45.addnext(p_tit_49)
    print("  CAMBIO 3 · Anexo C: Tabla 4.9 insertada después de la Tabla 4.5")

    # ---- CAMBIO 4: entrada en el Índice de Tablas
    idx45 = parrafo_que_empieza(doc, "Tabla 4.5.", con_tab=True)
    if idx45 is None:
        raise RuntimeError("no se encontró la entrada de la Tabla 4.5 en el índice")
    idx49 = copy.deepcopy(idx45._p)
    for r in idx49.iter(qn("w:r")):
        for t in r.findall(qn("w:t")):
            if t.text and t.text.startswith("Tabla 4.5."):
                t.text = TITULO_49[:-1] + ". (Anexo Suplementario)"
    idx45._p.addnext(idx49)
    print("  CAMBIO 4 · Índice de Tablas: entrada de la Tabla 4.9 agregada")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
