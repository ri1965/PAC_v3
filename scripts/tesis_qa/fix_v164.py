# -*- coding: utf-8 -*-
"""v163 -> v164: regresión de cursivas de la edición manual + concordancia.

1. CURSIVAS. La v162 daba 39/39; al editar en Word aparecieron 11 nombres de archivo
   y de método en cursiva, que el §26 pide siempre en redonda: `Medallion` ×1 y
   `parquet` ×10. Es el efecto típico de pegar o retipear dentro de un párrafo: el
   texto nuevo hereda el formato del run vecino.

   ⚠ No alcanza con poner `italic = False` en el run: si el run mezcla el nombre de
   archivo con texto que SÍ va en cursiva, hay que partirlo. Se usa
   `split_run_italic` de lib_docx, que parte el run y deja en redonda solo el término.

2. CONCORDANCIA. "cuya escala y representatividad no es reproducible" -> sujeto
   compuesto, va "no son reproducibles".

Uso: python3 scripts/tesis_qa/fix_v164.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import iter_block_paragraphs, para_replace, split_run_italic  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v163.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v164.docx")

# §26: nombres propios de método/software y nombres de archivo, siempre en redonda.
REDONDA = ["Medallion", "LightGBM", "Random Forest", "Streamlit", "Plotly",
           "LOPO-CV", "PAC App", "K-means", "Silhouette"]
RE_ARCHIVO = re.compile(r"[\w/*.\-]*\.parquet")

CONCORDANCIA = [("cuya escala y representatividad no es reproducible",
                 "cuya escala y representatividad no son reproducibles")]


def bloque_referencias(doc):
    """La bibliografía lleva cursiva por norma APA: se excluye."""
    ps = doc.paragraphs
    s = next(i for i, p in enumerate(ps)
             if p.text.strip() == "Referencias" and p.style.name.startswith("Heading"))
    e = next(i for i in range(s + 1, len(ps))
             if ps[i].text.strip().startswith("ANEXO B"))
    return {id(ps[i]._p) for i in range(s + 1, e)}


def quitar_cursiva(doc, refs):
    """Pasa a redonda los nombres propios y los nombres de archivo *.parquet."""
    n = 0
    for p in iter_block_paragraphs(doc):
        if id(p._p) in refs:
            continue
        # nombres de archivo: se recogen del texto del run, que puede traer varios
        for r in list(p.runs):
            if not r.italic or not r.text.strip():
                continue
            for archivo in sorted(set(RE_ARCHIVO.findall(r.text)), key=len, reverse=True):
                n += split_run_italic(p, archivo, italic=False)
        # ⚠ Si el path quedó partido entre runs ('(gold/*.' en cursiva + 'parquet'
        # ya en redonda), hay que pasar también el prefijo, o el nombre de archivo
        # se ve cortado al medio con dos tipografías.
        for prefijo in ("gold/*.",):
            if any(r.italic and prefijo in r.text for r in p.runs):
                n += split_run_italic(p, prefijo, italic=False)
        for termino in REDONDA:
            if any(r.italic and termino in r.text for r in p.runs):
                n += split_run_italic(p, termino, italic=False)
    return n


def main():
    doc = Document(str(SRC))
    refs = bloque_referencias(doc)

    print("1. Cursivas indebidas (nombres propios y de archivo)")
    print(f"   {quitar_cursiva(doc, refs)} fragmentos pasados a redonda")

    print("2. Concordancia")
    for viejo, nuevo in CONCORDANCIA:
        hecho = False
        for p in iter_block_paragraphs(doc):
            if viejo in p.text and para_replace(p, viejo, nuevo):
                print(f"   {viejo!r}\n      -> {nuevo!r}")
                hecho = True
                break
        if not hecho:
            print(f"   !! no encontrado: {viejo!r}")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
