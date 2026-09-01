# -*- coding: utf-8 -*-
"""v149 -> v150: codigo de campo HYPERLINK aplanado a texto visible.

Tres parrafos tenian el codigo de campo `HYPERLINK \\l "ancla"` como texto normal
dentro de un w:t, en vez de como instrText dentro de un campo. Se ve literal en el
documento. Residuo de una sesion anterior que inserto anclas escribiendo el codigo
como texto.

  ¶67   indice general   4.4  Sintesis de variables nocturnasHYPERLINK \\l "_Toc232926391"
  ¶333  cuerpo, sec 4.2.1  ...de los cinco fenotiposHYPERLINK \\l "bk232926385"
  ¶926  cuerpo, Anexo C    Cap. 7  App Clinica Interactiva (HYPERLINK \\l "bkCap07"PAC App)

Ojo: el del indice general lo regenera F9, pero el del cuerpo NO. Si se corrige solo
el indice, el proximo F9 vuelve a copiar la basura desde el encabezado del cuerpo.

Uso: python3 scripts/tesis_qa/fix_v150.py <origen> <destino>
"""
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v149.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v150.docx")

# Codigos de campo que nunca deben aparecer como texto visible.
RE_CODIGO = re.compile(r'\s*(?:HYPERLINK|PAGEREF|REF)\s+\\?\w*\s*"[^"]*"\s*')


def limpiar(doc):
    """Saca el codigo de campo de todo w:t del documento, cuerpo y tablas."""
    tocados = []
    for r in doc.element.body.iter(qn("w:r")):
        t = r.find(qn("w:t"))
        if t is None or not t.text or not RE_CODIGO.search(t.text):
            continue
        antes = t.text
        t.text = RE_CODIGO.sub("", antes)
        t.set(qn("xml:space"), "preserve")
        tocados.append((antes, t.text))
    return tocados


def main():
    doc = Document(str(SRC))
    tocados = limpiar(doc)
    for antes, despues in tocados:
        print(f"  {antes[:88]}\n     -> {despues[:88]}")
    doc.save(str(DST))
    print(f"\n{len(tocados)} párrafos limpiados · guardado: {DST}")


if __name__ == "__main__":
    main()
