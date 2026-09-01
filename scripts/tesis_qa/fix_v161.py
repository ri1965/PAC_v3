# -*- coding: utf-8 -*-
"""v160 -> v161: márgenes al mínimo APA y tablas dentro del ancho de texto.

MÁRGENES. APA 7 pide 1 pulgada (1440 twips) en los cuatro lados; la excepción
habitual es el izquierdo, que muchas universidades piden en 1,5" para encuadernación.
La v160 tenía der = 1134 (0,79") e inf = 1387 (0,96"), los dos por debajo del mínimo.

    izq 2268 (1,57" · encuadernación, se respeta)   der 1134 -> 1440
    sup 1554 (1,08" · ya cumple, se respeta)        inf 1387 -> 1440

TABLAS. Efecto colateral que ya existía y nadie había visto: **24 tablas medían
9000 twips con un ancho de texto de 8838**, o sea que ya se salían 3 mm del bloque.
Al subir el margen derecho el ancho baja a 8532 y el desborde sería visible, así que
todas las tablas se reescalan proporcionalmente al nuevo ancho.

Después del reescalado se revisa que ningún encabezado quede más angosto que su
palabra más larga (§31) y se ensancha lo que haga falta.

Uso: python3 scripts/tesis_qa/fix_v161.py <origen> <destino>
"""
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

AQUI = Path(__file__).parent
SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "tesis_cap/Tesis_PAC_v160.docx")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "tesis_cap/Tesis_PAC_v161.docx")

MINIMO_APA = 1440          # 1 pulgada
ANCHO_CARACTER = json.loads((AQUI / "anchos_caracter.json").read_text())
PADDING_CELDA = 216
FALLBACK = 145


def ancho_texto(s):
    return sum(ANCHO_CARACTER.get(c, FALLBACK) for c in s)


def trozos(texto):
    for pedazo in re.split(r"[ \t\n]+", texto):
        for sub in re.split(r"(?<=[-/])", pedazo):
            if sub:
                yield sub


def minimo_columna(celdas):
    return int(max((ancho_texto(t) for c in celdas for t in trozos(c)), default=0))


def escalar(tabla, destino):
    """Lleva la tabla al ancho `destino` conservando las proporciones."""
    grid = tabla._tbl.find(qn("w:tblGrid"))
    actuales = [int(c.get(qn("w:w"))) for c in grid]
    total = sum(actuales)
    if total <= destino:
        return actuales, actuales
    nuevos = [max(1, round(a * destino / total)) for a in actuales]
    nuevos[-1] += destino - sum(nuevos)
    return actuales, nuevos


def desahogar(tabla, anchos):
    """Ensancha las columnas que quedaron por debajo de su encabezado."""
    minimos = [minimo_columna([c.text for c in [fila.cells[i] for fila in tabla.rows]])
               + PADDING_CELDA for i in range(len(anchos))]
    faltan = [max(0, m - a) for a, m in zip(anchos, minimos)]
    if not any(faltan):
        return anchos, 0
    holguras = [max(0, a - m) for a, m in zip(anchos, minimos)]
    if sum(holguras) < sum(faltan):
        return anchos, -1                      # no entra: se reporta
    necesito = sum(faltan)
    salida = [a + f - (round(necesito * h / sum(holguras)) if h else 0)
              for a, f, h in zip(anchos, faltan, holguras)]
    salida[-1] += sum(anchos) - sum(salida)
    return salida, sum(1 for f in faltan if f)


def aplicar(tabla, anchos):
    grid = tabla._tbl.find(qn("w:tblGrid"))
    for col, w in zip(grid, anchos):
        col.set(qn("w:w"), str(w))
    for fila in tabla.rows:
        for celda, w in zip(fila.cells, anchos):
            tcPr = celda._tc.get_or_add_tcPr()
            tcW = tcPr.find(qn("w:tcW"))
            if tcW is None:
                tcPr.append(tcPr.makeelement(
                    qn("w:tcW"), {qn("w:w"): str(w), qn("w:type"): "dxa"}))
            else:
                tcW.set(qn("w:w"), str(w))
                tcW.set(qn("w:type"), "dxa")


# La Tabla 8.5 no entra con el ancho nuevo: se acortan los encabezados que la propia
# nota ya desarrolla ("Umbral de Youden: maximiza Sensibilidad + Especificidad − 1").
ABREVIAR = {"Umbral Youden": "Umbral", "Sensibilidad": "Sens.", "Especificidad": "Espec."}


def abreviar_encabezados(tabla):
    n = 0
    for celda in tabla.rows[0].cells:
        actual = celda.text.strip()
        if actual not in ABREVIAR:
            continue
        par = celda.paragraphs[0]
        if par.runs:
            par.runs[0].text = ABREVIAR[actual]
            for r in par.runs[1:]:
                r.text = ""
            n += 1
    return n


# ⚠ nada de \\b después de "%": no es carácter de palabra y el límite nunca matchea.
RE_PORCENTAJE = re.compile(r"(\d) (%|pp\b|s\b|min\b|ev/h)")


def espacios_duros(tabla):
    """'9,6 %' con espacio normal se parte al envolver: se ata con espacio duro.

    Solo dentro de tablas, que es donde el ancho de columna fuerza el corte.
    """
    n = 0
    for fila in tabla.rows:
        for celda in fila.cells:
            for par in celda.paragraphs:
                for r in par.runs:
                    nuevo = RE_PORCENTAJE.sub("\\1\u00a0\\2", r.text)
                    if nuevo != r.text:
                        r.text = nuevo
                        n += 1
    return n


def main():
    doc = Document(str(SRC))
    s = doc.sections[0]

    print("1. Márgenes")
    for nombre, attr in (("der", "right_margin"), ("inf", "bottom_margin"),
                         ("sup", "top_margin"), ("izq", "left_margin")):
        actual = getattr(s, attr).twips
        if nombre in ("der", "inf") and actual < MINIMO_APA:
            setattr(s, attr, __import__("docx").shared.Twips(MINIMO_APA))
            print(f"   {nombre}: {actual} -> {MINIMO_APA} twips (1\")")
        else:
            print(f"   {nombre}: {actual} twips — ya cumple, sin cambios")

    ancho = s.page_width.twips - s.left_margin.twips - s.right_margin.twips
    print(f"   ancho de texto: {ancho} twips")

    print("2. Tablas reescaladas al ancho de texto")
    escaladas = ajustadas = 0
    sin_lugar = []
    duros = 0
    for i, t in enumerate(doc.tables):
        duros += espacios_duros(t)
        if t.rows[0].cells[0].text.strip() == "Horizonte" and len(t.columns) == 6:
            if abreviar_encabezados(t):
                print("   Tabla 8.5: encabezados abreviados (Umbral, Sens., Espec.)")
        antes, nuevos = escalar(t, ancho)
        if nuevos != antes:
            escaladas += 1
        nuevos, n = desahogar(t, nuevos)
        if n == -1:
            sin_lugar.append((i, sum(antes)))
        elif n:
            ajustadas += 1
        aplicar(t, nuevos)
    print(f"   {escaladas} tablas reescaladas · {ajustadas} con columnas ensanchadas")
    print(f"   {duros} celdas con espacio duro entre magnitud y unidad")
    if sin_lugar:
        print(f"   ⚠ sin lugar para el encabezado: {sin_lugar}")

    doc.save(str(DST))
    print(f"\nguardado: {DST}")


if __name__ == "__main__":
    main()
