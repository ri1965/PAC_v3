#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auditoría editorial del consolidado de la tesis (Proyecto PAC).

Uso:
    python3 scripts/tesis_qa/auditar_tesis.py tesis_cap/Tesis_PAC_v145.docx

Corre tres bloques de control y devuelve código de salida 0 si todo pasa:
  A. Defectos puntuales y criterios de formato (APA, tablas, cursivas, terminología, carátula)
  B. Cruce citas ↔ referencias (huérfanas y citas sin entrada)
  C. Cruce figuras ↔ referencias cruzadas
  D. Cifras canónicas contra el Gold: presentes, superadas y coherencia interna
  E. Tono de potencialidad (advertencia: se lista, no hace fallar)

Notas de interpretación:
  - El texto dentro de los índices automáticos (contenidos, figuras, tablas) son
    campos de Word: se regeneran al actualizar campos (⌘A + F9) y por eso se excluyen.
  - La bibliografía lleva cursiva por norma APA, así que se excluye del control de cursivas.

Requiere: python-docx  (pip install python-docx)
Origen: sesión de cierre editorial, julio 2026 (ver CLAUDE.md §26).
"""
import re
import sys
import unicodedata
import collections
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib_docx import iter_block_paragraphs          # noqa: E402
from parse_refs import analizar                      # noqa: E402
from cifras_canonicas import (PRESENTES, SUPERADOS, ETIQUETADAS,  # noqa: E402
                              VERBOS_TAXATIVOS)

# --------------------------------------------------------------------------- utilidades

def norm(txt):
    txt = unicodedata.normalize('NFD', txt)
    return ''.join(c for c in txt if unicodedata.category(c) != 'Mn').lower()


def es_campo(p):
    """True si el párrafo es contenido de un índice automático de Word."""
    return '\t' in p.text or bool(p._p.findall('.//' + qn('w:hyperlink')))


class Reporte:
    def __init__(self):
        self.ok = 0
        self.fail = 0

    def chk(self, nombre, valor, esperado=0):
        bien = valor == esperado
        print(f"  [{'OK ' if bien else 'MAL'}] {nombre:54} {valor}")
        if bien:
            self.ok += 1
        else:
            self.fail += 1


# --------------------------------------------------------------------------- bloques

RE_CODIGO_CAMPO = re.compile(r'(?:HYPERLINK|PAGEREF|REF|TOC)\s+\\')


def _codigos_visibles(doc):
    """Cuenta w:t con codigo de campo como texto literal (no instrText)."""
    n = 0
    for r in doc.element.body.iter(qn('w:r')):
        t = r.find(qn('w:t'))
        if t is not None and t.text and RE_CODIGO_CAMPO.search(t.text):
            n += 1
    return n


def es_aparato(p):
    """True si el párrafo es aparato: nota de tabla/figura o puntero '▸'.

    Criterio del proyecto (CLAUDE.md §40): el aparato va en **cursiva íntegra**.
    La cursiva ahí marca una categoría de texto, no un énfasis, así que adentro no
    se recortan los nombres propios ni los nombres de archivo. Por eso estos
    párrafos quedan fuera de los dos controles de cursivas del bloque 4: si no,
    la convención adoptada aparecería como ~48 errores permanentes y la auditoría
    perdería la capacidad de señalar una regresión real en el cuerpo.
    """
    t = p.text.strip()
    return t.startswith('Nota.') or t.startswith('▸')


def _estilo_con_bordes(doc, style_id):
    """True si el estilo de tabla define bordes propios (heredables por la tabla)."""
    if not style_id:
        return False
    for st in doc.styles.element.findall(qn('w:style')):
        if st.get(qn('w:styleId')) != style_id:
            continue
        return st.find('.//' + qn('w:tblBorders')) is not None
    return False


_CACHE_ESTILO_CURSIVA = {}


def _estilo_es_cursiva(doc, style_id):
    """True si el estilo de carácter aplica cursiva (p. ej. 'nfasis' = Emphasis)."""
    if not style_id:
        return False
    if style_id in _CACHE_ESTILO_CURSIVA:
        return _CACHE_ESTILO_CURSIVA[style_id]
    val = False
    for st in doc.styles.element.findall(qn('w:style')):
        if st.get(qn('w:styleId')) != style_id:
            continue
        i = st.find(qn('w:rPr') + '/' + qn('w:i')) if st.find(qn('w:rPr')) is not None else None
        if i is None:
            rpr = st.find(qn('w:rPr'))
            i = rpr.find(qn('w:i')) if rpr is not None else None
        val = i is not None and i.get(qn('w:val')) not in ('0', 'false')
        break
    _CACHE_ESTILO_CURSIVA[style_id] = val
    return val


def es_cursiva(run, doc):
    """Cursiva efectiva de un run: formato directo, y si no lo hay, estilo de carácter.

    ⚠ `run.italic` de python-docx sólo lee el `w:i` directo. Word **elimina el `w:i`
    redundante** cuando el run ya usa un estilo de carácter que aporta la cursiva
    (`nfasis` / Emphasis). Sin esta resolución, cada guardado en Word reintroduce
    falsos positivos en el bloque 4 sobre texto que en pantalla está en cursiva.
    """
    if run.italic is not None:
        return run.italic
    rPr = run._r.find(qn('w:rPr'))
    if rPr is None:
        return False
    rs = rPr.find(qn('w:rStyle'))
    return _estilo_es_cursiva(doc, rs.get(qn('w:val')) if rs is not None else None)


def _ids_abstract(doc):
    """ids de los párrafos del Abstract y las Keywords (texto íntegro en inglés).

    No se les aplica el control de cursivas: marcar cada término técnico dentro de
    un texto que ya está entero en inglés no tiene sentido y generaría decenas de
    falsos positivos.
    """
    ps = doc.paragraphs
    ini = next((i for i, p in enumerate(ps)
                if p.style.name == 'TituloCap' and p.text.strip() == 'Abstract'), None)
    if ini is None:
        return set()
    fin = next((i for i in range(ini + 1, len(ps))
                if ps[i].style.name == 'TituloCap'), len(ps))
    return {id(ps[i]._p) for i in range(ini, fin)}


def es_recuadro(t):
    """True si la tabla es un recuadro '¿Qué debe recordar el lector?' (Cap. 4-8).

    Son tablas de una sola celda que dibujan una caja alrededor del texto: el borde
    izquierdo y el derecho son parte del diseño, no una linea de tabla APA. Antes
    eran cuadros de texto flotantes, pero su ancho declarado estaba mal y el texto
    se ajustaba por dentro, cortando una oracion del Cap. 7; se convirtieron en
    tablas en flujo para que rendericen igual en cualquier visor. Quedan fuera del
    bloque 3, que controla tablas de datos.
    """
    if len(t.rows) != 1 or len(t.columns) != 1:
        return False
    return 'debe recordar' in t.rows[0].cells[0].text


def _ancho_por_tabla(doc):
    """Ancho de caja de texto (twips) que corresponde a cada tabla, por seccion.

    El documento dejo de tener una sola seccion: la tabla de trazabilidad del anexo
    vive en una seccion apaisada propia, donde la caja mide 12132 tw en lugar de
    8532. Comparar todas las tablas contra la primera seccion marcaba esa tabla como
    desbordada siendo correcta.
    """
    anchos = [s.page_width.twips - s.left_margin.twips - s.right_margin.twips
              for s in doc.sections]
    # Se indexa por POSICION de la tabla, no por id() del elemento: lxml crea un
    # proxy nuevo en cada recorrido, asi que id(child) e id(t._tbl) no coinciden
    # aunque envuelvan el mismo nodo.
    por_pos = []
    idx = 0
    for child in doc.element.body.iterchildren():
        if child.tag == qn('w:tbl'):
            por_pos.append(anchos[min(idx, len(anchos) - 1)])
        elif child.tag == qn('w:p'):
            pPr = child.find(qn('w:pPr'))
            if pPr is not None and pPr.find(qn('w:sectPr')) is not None:
                idx += 1          # ese parrafo cierra la seccion actual
    return por_pos, anchos


def bloque_formato(doc, rep):
    ps = doc.paragraphs
    T = "\n".join(p.text for p in iter_block_paragraphs(doc))
    cuerpo = "\n".join(p.text for p in iter_block_paragraphs(doc) if not es_campo(p))

    print("\n1. Defectos puntuales (huecos dejados por reemplazos globales)")
    rep.chk("'Cap' suelto pegado a un paréntesis", T.count(').Cap'))
    rep.chk("'construcción de .' sin completar", T.count('construcción de .'))
    rep.chk("':  ' seguido de signo (sujeto faltante)",
            len(re.findall(r':\s{2,}[=,;)]', cuerpo)))
    rep.chk("'(, ' paréntesis que abre sin sujeto", len(re.findall(r'\(\s*,', cuerpo)))
    rep.chk("'dimensiones' dentro de un título en inglés",
            T.count('heartbeat interval dimensiones'))
    rep.chk("'dimensión matrix' (feature matrix a medio traducir)",
            T.count('dimensión matrix'))
    # U+202F es correcto entre magnitud y unidad ('30 s', '5 min') y en 'Tabla 5.1'.
    # Solo se marca cuando separa 'Cap' de un numero: ese fue el defecto real.
    rep.chk("'Cap' + espacio angosto + numero", len(re.findall('Cap\u202f\\d', T)))
    # Codigo de campo aplanado a texto visible: se ve literal el HYPERLINK \l "ancla".
    # Hay que mirar los w:t, no p.text, porque instrText es legitimo dentro de un campo.
    rep.chk("c\u00f3digo de campo visible como texto", _codigos_visibles(doc))

    print("\n2. Referencias en formato APA 7")
    s = next(i for i, p in enumerate(ps)
             if p.text.strip() == 'Referencias' and p.style.name.startswith('Heading'))
    e = next(i for i in range(s + 1, len(ps)) if ps[i].text.strip().startswith('ANEXO B'))
    refs = [ps[i] for i in range(s + 1, e) if ps[i].text.strip()]
    sin_sangria = [p for p in refs
                   if not (p.paragraph_format.first_line_indent
                           and p.paragraph_format.first_line_indent.pt < 0)]
    sin_cursiva = [p for p in refs if not any(r.italic for r in p.runs if r.text.strip())]
    con_etal = [p for p in refs if 'et al.' in p.text]
    rep.chk(f"entradas sin sangría francesa (de {len(refs)})", len(sin_sangria))
    rep.chk(f"entradas sin cursiva (de {len(refs)})", len(sin_cursiva))
    rep.chk("entradas con 'et al.' en la lista", len(con_etal))

    print("\n3. Tablas en formato APA (sin verticales ni interiores)")
    # Word poda los bordes con val="none" al guardar, por considerarlos redundantes.
    # Un borde ausente NO dibuja linea salvo que el estilo de la tabla la defina, asi
    # que solo se marca el borde presente con un valor distinto de none/nil.
    SIN_LINEA = (None, 'none', 'nil')
    malas = 0
    datos = [t for t in doc.tables if not es_recuadro(t)]
    for t in datos:
        tblPr = t._tbl.find(qn('w:tblPr'))
        b = tblPr.find(qn('w:tblBorders')) if tblPr is not None else None
        estilo = tblPr.find(qn('w:tblStyle')) if tblPr is not None else None
        if b is None:
            # sin bordes propios: solo es problema si hereda de un estilo con bordes
            if estilo is not None and _estilo_con_bordes(doc, estilo.get(qn('w:val'))):
                malas += 1
            continue
        for tag in ('insideV', 'left', 'right', 'insideH'):
            el = b.find(qn('w:' + tag))
            if el is not None and el.get(qn('w:val')) not in SIN_LINEA:
                malas += 1
                break
    rep.chk(f"tablas con líneas verticales/interiores (de {len(datos)})", malas)

    print("\n4. Cursivas con criterio único")
    # Criterio vigente (decision del autor, Ago 2026, alineado con la Guia Editorial
    # v17 "Terminos en ingles: cursiva" y con la RAE): el extranjerismo crudo va en
    # cursiva en TODAS sus apariciones, no solo la primera. Antes este bloque exigia
    # lo contrario -- cursiva una sola vez -- y con el criterio nuevo marcaba 11
    # terminos como error permanente.
    CURSIVA_SIEMPRE = ['pipeline', 'baseline', 'clustering', 'lead time', 'fold', 'folds',
                       'backend', 'ramp-up', 'trade-off', 'framework', 'notebook',
                       'notebooks', 'ranking', 'target', 'dataset', 'batch', 'bootstrap',
                       'cluster', 'clusters', 'gauge', 'hash', 'overfitting']
    SIEMPRE_REDONDA = ['LightGBM', 'Random Forest', 'Streamlit', 'Plotly', 'LOPO-CV',
                       'PAC App', 'K-means', 'Silhouette', 'Medallion', 'parquet']
    # Contextos donde el termino integra un nombre propio o una metrica acuñada y
    # por lo tanto NO se marca (criterio del autor, punto 5 de la ronda de cursivas).
    PROTEGIDOS = ['Risk Score', 'Coupling Index', 'Average Precision', 'Random Forest',
                  'balanced accuracy', 'Platt scaling', 'Estados PAC', 'Cross-Validation']
    ref_ids = {id(ps[i]._p) for i in range(s + 1, e)}
    abs_ids = _ids_abstract(doc)           # Abstract y Keywords van integros en ingles
    cnt = collections.defaultdict(collections.Counter)
    for p in iter_block_paragraphs(doc):
        if id(p._p) in ref_ids or id(p._p) in abs_ids:
            continue                       # bibliografía y Abstract quedan fuera
        if p.style.name.startswith(('toc', 'Heading')) or p.style.name == 'TituloCap':
            continue                       # títulos e índices no se marcan: son
                                           # nombres de sección y las entradas del
                                           # índice deben coincidir con ellos
        if es_aparato(p):
            continue                       # notas y punteros: cursiva íntegra (§40)
        full = p.text
        prot = [m.span() for x in PROTEGIDOS
                for m in re.finditer(re.escape(x), full, re.I)]
        off = 0
        for r in p.runs:
            for term in CURSIVA_SIEMPRE + SIEMPRE_REDONDA:
                for m in re.finditer(r'(?<![\w\-])' + re.escape(term) + r'(?![\w\-])',
                                     r.text, re.I):
                    gs, ge = off + m.start(), off + m.end()
                    if any(gs < pe and ge > ps_ for ps_, pe in prot):
                        continue
                    cnt[term]['i' if es_cursiva(r, doc) else 'r'] += 1
            off += len(r.text)
    en_redonda = {t: cnt[t]['r'] for t in CURSIVA_SIEMPRE if cnt[t]['r']}
    redonda_mal = {t: cnt[t]['i'] for t in SIEMPRE_REDONDA if cnt[t]['i']}
    rep.chk("extranjerismos que quedaron en redonda", len(en_redonda))
    if en_redonda:
        print("         ", en_redonda)
    rep.chk("nombres propios/archivos aún en cursiva", len(redonda_mal))
    if redonda_mal:
        print("         ", redonda_mal)

    print("\n5. Terminología unificada")
    rep.chk("'K-Medias' (debe ser K-means)", len(re.findall(r'K-Medias', cuerpo)))
    rep.chk("'cohorte full' / 'cohorte strict'",
            len(re.findall(r'cohortes? (full|strict)', cuerpo)))
    rep.chk("'Risk Score' sin 'PAC'",
            len(re.findall(r'Risk Score(?! PAC)(?<!PAC Risk Score)', cuerpo)))
    rep.chk("'características' como sinónimo de variables",
            len(re.findall(r'vectores? de características|características por ventana', cuerpo)))
    rep.chk("'Cap. N' en prosa corrida (debe ser 'Capítulo N')",
            len(re.findall(r'(?:validado|introducido|descrito) en (?:el )?Cap\.\s?\d+(?!\s*\u00a7)', cuerpo)))

    print("\n6. Carátula")
    cov = [p.text.strip() for p in ps[:20]]
    rep.chk("dice 'Tutor' (el corpus Austral usa 'Director')",
            sum(1 for c in cov if c.startswith('Tutor')))
    rep.chk("falta 'Director:'", 0 if any(c.startswith('Director:') for c in cov) else 1)
    rep.chk("falta la designación del trabajo",
            0 if any(c == 'Tesis de Maestría' for c in cov) else 1)
    rep.chk("falta la fórmula de grado",
            0 if any('cumplimiento parcial' in c for c in cov) else 1)

    print("\n7. Estilo")
    sin_campos = re.sub(r'HYPERLINK[^\t\n]*', '', cuerpo)
    rep.chk("comillas rectas", sin_campos.count('"'))
    rep.chk("espacio antes de puntuación",
            len(re.findall(r'(?<=[a-záéíóúñ0-9%\)])\s+[.,](?=\s)', cuerpo)))
    rep.chk("paréntesis vacíos", len(re.findall(r'\(\s*\)', cuerpo)))
    rep.chk("marcadores de plantilla / TODO",
            len(re.findall(r'\b(TODO|XXX|FIXME|TBD)\b|\{\{|\}\}', cuerpo)))


def bloque_citas(doc, rep):
    print("\n8. Cruce citas ↔ referencias")
    ps = doc.paragraphs
    s = next(i for i, p in enumerate(ps)
             if p.text.strip() == 'Referencias' and p.style.name.startswith('Heading'))
    e = next(i for i in range(s + 1, len(ps)) if ps[i].text.strip().startswith('ANEXO B'))
    refs = [ps[i].text.strip() for i in range(s + 1, e) if ps[i].text.strip()]

    cuerpo, dentro = [], False
    for p in iter_block_paragraphs(doc):
        t = p.text.strip()
        if t == 'Referencias' and p.style.name.startswith('Heading'):
            dentro = True
        if t.startswith('ANEXO B'):
            dentro = False
        if not dentro:
            cuerpo.append(p.text)
    T = "\n".join(cuerpo)
    TN = norm(T)

    entradas = []
    for t in refs:
        m = re.match(r'^(.+?)\((\d{4}[a-z]?)\)', t)
        if m:
            ape = norm(re.split(r'[,&]', m.group(1))[0].strip().rstrip(' .'))
            entradas.append((ape, m.group(2), t))

    huerfanas = []
    for ape, anio, t in entradas:
        visto = any(anio in TN[max(0, m.start() - 190):m.start() + 300]
                    for m in re.finditer(re.escape(ape), TN))
        if not visto:
            huerfanas.append(t)

    citas = set()
    for m in re.finditer(r'\(([^()]{0,320}?\d{4}[a-z]?)\)', T):
        for seg in m.group(1).split(';'):
            mm = re.search(r'([A-ZÁÉÍÓÚÑ][^,]*?),?\s*(?:et al\.,?\s*)?(\d{4}[a-z]?)\s*$', seg.strip())
            if mm:
                citas.add((norm(mm.group(1).split()[-1].rstrip(',')), mm.group(2)))
    for m in re.finditer(r'([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ\-]+)\s+(?:et al\.|y|&)?\s*\((\d{4}[a-z]?)\)', T):
        citas.add((norm(m.group(1)), m.group(2)))

    faltantes = []
    for ape, anio in sorted(citas):
        if ape in ('junio', 'somni'):
            continue
        if not any(cy == anio and ape in norm(t[:t.find('(') + 7]) for _, cy, t in entradas):
            faltantes.append((ape, anio))

    print(f"       entradas en la bibliografía: {len(entradas)}")
    rep.chk("referencias no citadas en el texto", len(huerfanas))
    for h in huerfanas:
        print("          -", h[:100])
    rep.chk("citas sin entrada en la bibliografía", len(faltantes))
    for a, y in faltantes:
        print("          -", a, y)


def bloque_figuras(doc, rep):
    print("\n9. Cruce figuras ↔ referencias cruzadas")
    pies, refs = set(), set()
    for p in iter_block_paragraphs(doc):
        t = p.text
        if '\t' in t:
            continue                        # índice de figuras: es un campo
        m = re.match(r'^\s*Figura (\d+\.\d+)\.', t.strip())
        if m:
            pies.add(m.group(1))
            continue
        # admite '(Fig. 5.3)', 'Figs. 7.6, 7.7 y 7.8', 'La Figura 7.2'
        for pat in (r'\bFigs?\.\s*(\d+\.\d+)((?:\s*(?:,|y)\s*\d+\.\d+)*)',
                    r'\bFiguras?\s+(\d+\.\d+)((?:\s*(?:,|y)\s*\d+\.\d+)*)'):
            for mm in re.finditer(pat, t):
                refs.add(mm.group(1))
                refs.update(re.findall(r'(\d+\.\d+)', mm.group(2) or ''))
    print(f"       pies de figura: {len(pies)}   referenciadas: {len(refs)}")
    rep.chk("figuras sin referencia cruzada en el texto", len(pies - refs))
    for f in sorted(pies - refs):
        print("          - Fig.", f)
    rep.chk("referencias a figuras inexistentes", len(refs - pies))
    for f in sorted(refs - pies):
        print("          - Fig.", f)


def bloque_cifras(doc, rep):
    """Las cifras del consolidado contra la lista canónica verificada en el Gold."""
    T = "\n".join(p.text for p in iter_block_paragraphs(doc))

    print("\n10. Cifras canónicas presentes")
    ausentes = [(n, v) for n, v, k in PRESENTES if len(re.findall(re.escape(v), T)) < k]
    rep.chk("cifras de titular ausentes o por debajo del mínimo", len(ausentes))
    for n, v in ausentes:
        print(f"          - {n}: no aparece '{v}'")

    print("\n11. Valores superados que no deben reaparecer")
    revividos = []
    for nombre, pat in SUPERADOS:
        occ = list(re.finditer(pat, T))
        if occ:
            revividos.append((nombre, len(occ), pat))
    rep.chk("valores de corridas viejas reaparecidos", len(revividos))
    for nombre, n, pat in revividos:
        print(f"          - {nombre}  ({n}x)")
        for m in list(re.finditer(r'.{0,60}' + pat + r'.{0,40}', T))[:2]:
            print(f"              …{m.group(0)}…")

    print("\n12. Coherencia interna de métricas etiquetadas")
    incoherentes = []
    for a, b, esperado in ETIQUETADAS:
        pat = re.escape(a) + r'[^\n]{0,70}?' + re.escape(b) + r'[^\n]{0,28}?([+-]?\d,\d{3})'
        hallados = set(re.findall(pat, T))
        distintos = hallados - {esperado}
        if distintos:
            incoherentes.append((f"{a}→{b}", esperado, sorted(distintos)))
    rep.chk("métricas con más de un valor en el documento", len(incoherentes))
    for etq, esp, otros in incoherentes:
        print(f"          - {etq}: se esperaba {esp}, también aparece {otros}")


def bloque_tono(doc):
    """Advertencia, no control: el tono requiere criterio humano."""
    T = "\n".join(p.text for p in iter_block_paragraphs(doc))
    print("\n13. Tono de potencialidad (revisión manual)")
    total = 0
    for v in VERBOS_TAXATIVOS:
        for m in re.finditer(r'.{0,80}' + v + r'.{0,60}', T, re.I):
            total += 1
            print(f"       …{m.group(0).strip()}…")
    if not total:
        print("       sin verbos taxativos")
    else:
        print(f"       {total} para revisar. Muchos son legítimos (sustantivos, "
              f"propiedades técnicas); el criterio del CLAUDE.md aplica a los resultados.")


# --------------------------------------------------------------------------- main

def bloque_pagina(doc, rep):
    """Bloque 14 · formato de página.

    ⚠ Estos controles NO verifican APA estricto: verifican el criterio del proyecto,
    que se aparta de APA en tres puntos de forma deliberada, porque son convenciones
    de tesis encuadernada y no de manuscrito para revista (ver CLAUDE.md §37):

        · APA pide sangría de primera línea de 0,5"; el documento separa por espaciado.
        · APA pide el folio arriba a la derecha; el documento lo lleva al pie.
        · APA pide interlineado doble; el documento usa 1,5 en el cuerpo y 1,0 en el
          aparato (notas y punteros "▸").

    Lo que sí se controla contra APA es el mínimo de márgenes, que es el único de los
    cuatro que un jurado puede medir con una regla.
    """
    print("\n14. Formato de página")
    s = doc.sections[0]
    ancho = s.page_width.twips - s.left_margin.twips - s.right_margin.twips

    # 14.1 · márgenes: 1" mínimo; el izquierdo se admite mayor por encuadernación
    chicos = [n for n, v in (("der", s.right_margin), ("sup", s.top_margin),
                             ("inf", s.bottom_margin)) if v.twips < 1440]
    if s.left_margin.twips < 2160:
        chicos.append("izq (<1,5\" de encuadernación)")
    rep.chk(f"márgenes por debajo del mínimo (texto {ancho} tw)", len(chicos))
    if chicos:
        print(f"          {chicos}")

    # 14.2 · ninguna tabla más ancha que la caja de texto DE SU SECCIÓN
    por_tabla, anchos_sec = _ancho_por_tabla(doc)
    anchas = []
    for i, t in enumerate(doc.tables):
        grid = t._tbl.find(qn('w:tblGrid'))
        if grid is None:
            continue
        w = sum(int(c.get(qn('w:w'))) for c in grid)
        caja = por_tabla[i] if i < len(por_tabla) else ancho
        if w > caja:
            anchas.append((i, w, caja))
    rep.chk(f"tablas más anchas que el texto (de {len(doc.tables)})", len(anchas))
    if anchas:
        print(f"          {anchas}")

    # 14.3 · interlineado: 1,5 en el cuerpo, 1,0 en notas y punteros
    malos = 0
    for p in doc.paragraphs:
        t = p.text.strip()
        if len(t) < 120:
            continue
        ls = p.paragraph_format.line_spacing
        aparato = t.startswith(("Nota.", "▸")) or t.startswith(("Figura ", "Tabla "))
        if aparato and ls not in (1.0, None):
            malos += 1
        elif not aparato and ls not in (None, 1.5):
            malos += 1
    rep.chk("párrafos fuera del interlineado del documento", malos)

    # 14.4 · sangría de primera línea: el documento no usa (separa por espaciado)
    con_sangria = sum(1 for p in doc.paragraphs
                      if p.paragraph_format.first_line_indent is not None
                      and p.paragraph_format.first_line_indent.twips > 0)
    rep.chk("párrafos con sangría de primera línea", con_sangria)

    # 14.5 · folio: campo PAGE presente en el pie de todas las secciones
    sin_folio = [i for i, sec in enumerate(doc.sections)
                 if not any('PAGE' in (e.text or '')
                            for p in sec.footer.paragraphs
                            for e in p._p.iter(qn('w:instrText')))]
    rep.chk(f"secciones sin folio en el pie (de {len(doc.sections)})", len(sin_folio))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ruta = sys.argv[1]
    doc = Document(ruta)
    print(f"=== AUDITORÍA EDITORIAL — {Path(ruta).name} ===")
    rep = Reporte()
    bloque_formato(doc, rep)
    bloque_citas(doc, rep)
    bloque_figuras(doc, rep)
    bloque_cifras(doc, rep)
    bloque_pagina(doc, rep)
    bloque_tono(doc)
    print(f"\n=== {rep.ok} OK / {rep.fail} pendientes ===")
    if rep.fail:
        print("\nRecordatorio: si el pendiente aparece sólo dentro de un índice, "
              "abrí el .docx en Word y actualizá los campos (⌘A + F9) antes de volver a correr.")
    return 1 if rep.fail else 0


if __name__ == '__main__':
    sys.exit(main())
