# -*- coding: utf-8 -*-
"""Utilidades de edición quirúrgica sobre .docx preservando formato."""
import copy, re
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

def iter_block_paragraphs(doc):
    """Todos los párrafos del cuerpo, incluidos los de dentro de tablas."""
    def walk(parent, el):
        for child in el.iterchildren():
            if child.tag == qn('w:p'):
                yield Paragraph(child, parent)
            elif child.tag == qn('w:tbl'):
                t = Table(child, parent)
                for row in t.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            yield p
                        for inner in cell.tables:
                            yield from walk(cell, inner._tbl.getparent())
    yield from walk(doc, doc.element.body)

def para_replace(p, old, new):
    """Reemplaza todas las ocurrencias de `old` por `new` en un parrafo aunque
    esten partidas entre runs. Una sola pasada: seguro aunque `new` contenga a `old`.
    El texto nuevo hereda el formato del run donde empieza la coincidencia."""
    runs = p.runs
    if not runs:
        return 0
    texts = [r.text for r in runs]
    full = ''.join(texts)
    if old not in full:
        return 0
    spans = []
    i = full.find(old)
    while i != -1:
        spans.append((i, i + len(old)))
        i = full.find(old, i + len(old))   # sin solapamiento
    bounds = []
    pos = 0
    for idx, t in enumerate(texts):
        bounds.append((pos, pos + len(t), idx))
        pos += len(t)

    def run_of(offset, start=True):
        for a, b, idx in bounds:
            if start:
                if a <= offset < b or (a == b == offset):
                    return idx
            else:
                if a < offset <= b:
                    return idx
        return len(texts) - 1

    for s, e in reversed(spans):          # de atras hacia adelante
        first = run_of(s, True)
        last = run_of(e, False)
        a0 = bounds[first][0]
        b1 = bounds[last][1]
        head = full[a0:s]
        tail = full[e:b1]
        texts[first] = head + new + tail
        for k in range(first + 1, last + 1):
            texts[k] = ''
    for r, t in zip(runs, texts):
        if r.text != t:
            r.text = t
    return len(spans)

def doc_replace(doc, old, new, limit=None):
    total = 0
    for p in iter_block_paragraphs(doc):
        total += para_replace(p, old, new)
        if limit and total >= limit:
            break
    return total

def split_run_italic(p, term, italic=True):
    """Parte los runs de un párrafo para poner `term` en cursiva/redonda.
    Devuelve la cantidad de ocurrencias tratadas."""
    count = 0
    for r in list(p.runs):
        txt = r.text
        if not txt or term not in txt:
            continue
        pieces = []
        idx = 0
        for m in re.finditer(r'(?<![\w\-])' + re.escape(term) + r'(?![\w\-])', txt):
            if m.start() > idx:
                pieces.append((txt[idx:m.start()], None))
            pieces.append((m.group(0), italic))
            idx = m.end()
        if not pieces:
            continue
        if idx < len(txt):
            pieces.append((txt[idx:], None))
        anchor = r._r
        r.text = pieces[0][0]
        if pieces[0][1] is not None:
            r.italic = pieces[0][1]
            count += 1
        prev = anchor
        for text, ital in pieces[1:]:
            new_r = copy.deepcopy(anchor)
            # limpiar hijos de texto
            for child in list(new_r):
                if child.tag in (qn('w:t'), qn('w:br'), qn('w:tab')):
                    new_r.remove(child)
            t = new_r.makeelement(qn('w:t'), {})
            t.text = text
            t.set(qn('xml:space'), 'preserve')
            new_r.append(t)
            prev.addnext(new_r)
            prev = new_r
            if ital is not None:
                rPr = new_r.find(qn('w:rPr'))
                if rPr is None:
                    rPr = new_r.makeelement(qn('w:rPr'), {})
                    new_r.insert(0, rPr)
                for it in rPr.findall(qn('w:i')):
                    rPr.remove(it)
                for it in rPr.findall(qn('w:iCs')):
                    rPr.remove(it)
                i_el = rPr.makeelement(qn('w:i'), {})
                if not ital:
                    i_el.set(qn('w:val'), '0')
                rPr.append(i_el)
                count += 1
    return count
