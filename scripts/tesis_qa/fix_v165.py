# -*- coding: utf-8 -*-
"""v164 -> v165: unifica en redonda los nombres de las capas del pipeline.

Criterio (§26, ampliado): los nombres de archivo (`states.parquet`) y los nombres
propios de componentes van SIEMPRE en redonda. Son identificadores literales, no
extranjerismos conceptuales — la misma categoría que LightGBM o Random Forest.
La cursiva de "solo la primera vez" aplica a `pipeline`, `baseline`, `clustering`,
no a los nombres de las capas.

Estado en la v164:

    parquet         60 redonda ·  0 cursiva  ✓
    Medallion        6 redonda ·  0 cursiva  ✓
    Gold            22 redonda ·  6 cursiva  ✗
    Events           9 redonda ·  5 cursiva  ✗
    Silver          10 redonda ·  4 cursiva  ✗
    Bronze          11 redonda ·  3 cursiva  ✗
    NightRecordID    4 redonda ·  2 cursiva  ✗

⚠ Verificado que las cursivas NO son las primeras menciones (`Bronze` aparece dos
veces en redonda antes de su primera cursiva): es residuo, concentrado en §3.3,
no un criterio alternativo coherente.

⚠ La flecha `Bronze → Silver → Events → Gold` viaja como un solo run en cursiva en
algunos lugares: hay que tratarla como unidad o queda media cadena en cada tipografía,
que es peor que el defecto original (pasó con `gold/*.parquet` en la v164).

Uso: python3 scripts/tesis_qa/fix_v165.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import iter_block_paragraphs, split_run_italic  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v164.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v165.docx")

# La cadena completa primero: si se procesa suelto, queda partida entre tipografías.
CADENAS = ["Bronze → Silver → Events → Gold", "Bronze→Gold"]
CAPAS = ["NightRecordID", "Medallion", "Bronze", "Silver", "Events", "Gold"]


def bloque_referencias(doc):
    ps = doc.paragraphs
    s = next(i for i, p in enumerate(ps)
             if p.text.strip() == "Referencias" and p.style.name.startswith("Heading"))
    e = next(i for i in range(s + 1, len(ps))
             if ps[i].text.strip().startswith("ANEXO B"))
    return {id(ps[i]._p) for i in range(s + 1, e)}


def contar(doc, refs, terminos):
    salida = {}
    for t in terminos:
        r_ = c_ = 0
        for p in iter_block_paragraphs(doc):
            if id(p._p) in refs:
                continue
            for run in p.runs:
                if not run.text.strip():
                    continue
                n = len(re.findall(r"(?<![\w\-])" + re.escape(t) + r"(?![\w\-])", run.text))
                if n:
                    if run.italic:
                        c_ += n
                    else:
                        r_ += n
        salida[t] = (r_, c_)
    return salida


def main():
    doc = Document(str(SRC))
    refs = bloque_referencias(doc)

    antes = contar(doc, refs, CAPAS)
    total = 0
    for p in iter_block_paragraphs(doc):
        if id(p._p) in refs:
            continue
        for termino in CADENAS + CAPAS:
            if any(r.italic and termino in r.text for r in p.runs):
                total += split_run_italic(p, termino, italic=False)

    despues = contar(doc, refs, CAPAS)
    print(f"{'término':16s} {'antes (red/cur)':>18s} {'después (red/cur)':>20s}")
    for t in CAPAS:
        print(f"  {t:14s} {antes[t][0]:8d} /{antes[t][1]:4d} {despues[t][0]:14d} /{despues[t][1]:4d}")
    print(f"\n{total} fragmentos pasados a redonda")

    doc.save(str(DST))
    print(f"guardado: {DST}")


if __name__ == "__main__":
    main()
