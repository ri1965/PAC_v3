# -*- coding: utf-8 -*-
"""v153 -> v154: 'latella', residuo de un reemplazo global.

Detectado en la primera pasada de ortografia (diccionario hunspell es, via spylls).
El parrafo decia:

    'La predicción en tiempo real con latella explícito y habilitación del
     estimulador terapéutico es objeto del Capítulo 8.'

Debe decir 'lead time' (CLAUDE.md §14, y las otras 9 apariciones del documento).
Va en redonda: §26 pide cursiva solo en la primera aparicion, que esta mas arriba.

Uso: python3 scripts/tesis_qa/fix_v154.py <origen> <destino>
"""
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import iter_block_paragraphs, para_replace  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v153.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v154.docx")

CORRECCIONES = [("con latella explícito", "con lead time explícito")]


def main():
    doc = Document(str(SRC))
    total = 0
    for p in iter_block_paragraphs(doc):
        for viejo, nuevo in CORRECCIONES:
            if viejo in p.text:
                n = para_replace(p, viejo, nuevo)
                total += n
                if n:
                    print(f"  {viejo!r} -> {nuevo!r}")
                    print(f"     ...{p.text.strip()[:150]}")
    if not total:
        print("  nada que corregir (¿ya aplicado?)")
    doc.save(str(DST))
    print(f"\n{total} correcciones · guardado: {DST}")


if __name__ == "__main__":
    main()
