# -*- coding: utf-8 -*-
"""v154 -> v155: las dos palabras inexistentes que dejo la pasada de ortografia (§32).

  §5.4  'las noches mejor arquitecturadas' -> 'las noches con mejor arquitectura'
        ('arquitecturado' no existe; se conserva el sentido de la escala L,
         que el propio capitulo llama 'arquitectura global')

  §3.4  'paso evaluatorio previo al K-means' -> 'paso preparatorio previo al K-means'
        (el PCA prepara los datos, no los evalua)

Uso: python3 scripts/tesis_qa/fix_v155.py <origen> <destino>
"""
import sys
from pathlib import Path

from docx import Document

sys.path.insert(0, str(Path(__file__).parent))
from lib_docx import iter_block_paragraphs, para_replace  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v154.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v155.docx")

CORRECCIONES = [
    ("las noches mejor arquitecturadas", "las noches con mejor arquitectura"),
    ("paso evaluatorio previo", "paso preparatorio previo"),
]


def main():
    doc = Document(str(SRC))
    pendientes = dict(CORRECCIONES)
    for p in iter_block_paragraphs(doc):
        for viejo in list(pendientes):
            if viejo not in p.text:
                continue
            nuevo = pendientes[viejo]
            if para_replace(p, viejo, nuevo):
                del pendientes[viejo]
                print(f"  {viejo!r}\n     -> {nuevo!r}")
                i = p.text.find(nuevo)
                print(f"     ...{p.text[max(0, i - 90):i + 110].strip()}...")
    for viejo in pendientes:
        print(f"  !! no encontrado: {viejo!r}")
    doc.save(str(DST))
    print(f"\n{len(CORRECCIONES) - len(pendientes)}/{len(CORRECCIONES)} aplicadas · "
          f"guardado: {DST}")


if __name__ == "__main__":
    main()
