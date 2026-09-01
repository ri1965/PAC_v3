# -*- coding: utf-8 -*-
"""Detecta el tramo que va en cursiva en cada referencia APA 7."""
import re

EDITORIALES = ('Press', 'Wiley', 'Springer', 'Hall', 'CRC', 'Elsevier',
               'Routledge', 'Sage', 'Guilford', 'McGraw', 'Academic')

def analizar(t):
    """Devuelve (inicio, fin) del tramo en cursiva, y el tipo detectado."""
    m = re.match(r'^(.*?\(\d{4}[a-z]?\)\.\s+)(.*)$', t)
    if not m:
        return None, 'SIN-ANIO'
    head, rest = m.group(1), m.group(2)
    off = len(head)
    u = re.search(r'\shttps?://', rest)
    body = rest[:u.start()] if u else rest

    # 1) articulo de revista con volumen
    mv = re.search(r'(?:^|\.\s)([^.]*?),\s(\d+)(?=\(|,)', body)
    if mv:
        return (off + mv.start(1), off + mv.end(2)), 'articulo'

    # 2) libro con mencion de edicion
    me = re.match(r'^(.*?)\s\((?:\d(?:st|nd|rd|th)\sed\.|Ed\.|Eds\.)\)', body)
    if me:
        return (off, off + len(me.group(1))), 'libro-ed'

    partes = re.split(r'(?<=[a-z0-9\)])\.\s', body)

    # 3) libro sin edicion: el ultimo segmento es una editorial -> cursiva al titulo
    if len(partes) >= 2 and any(k in partes[-1] for k in EDITORIALES):
        titulo = partes[-2].strip() if len(partes) > 2 else partes[0].strip()
        ini = body.find(titulo)
        if ini >= 0:
            return (off + ini, off + ini + len(titulo)), 'libro'

    # 4) fuente sin volumen (revista o actas); se excluye el rango de paginas
    if len(partes) >= 2:
        ult = partes[-1].rstrip('. ')
        ult = re.sub(r',\s*\d+[\u2013-]\d+\s*$', '', ult)   # quita ", 56-61"
        ini = body.rfind(ult)
        if ini > 0 and len(ult) < 95:
            return (off + ini, off + ini + len(ult)), 'fuente-sin-vol'

    # 5) obra independiente (software, sitio web)
    tt = body.rstrip('. ')
    return (off, off + len(tt)), 'obra-independiente'

if __name__ == '__main__':
    from docx import Document
    doc = Document('v143_s1.docx')
    ps = doc.paragraphs
    s = next(i for i, p in enumerate(ps) if p.text.strip() == 'Referencias' and p.style.name.startswith('Heading'))
    e = next(i for i in range(s + 1, len(ps)) if ps[i].text.strip().startswith('ANEXO B'))
    for i in range(s + 1, e):
        t = ps[i].text.strip()
        if not t:
            continue
        span, tipo = analizar(t)
        if span is None:
            print(f"  !! {tipo}: {t[:90]}")
            continue
        a, b = span
        print(f"[{tipo:20}] {t[:38]:38} >>> «{t[a:b]}»")
