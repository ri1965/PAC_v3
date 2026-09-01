#!/usr/bin/env python3
"""
Genera Guion_Defensa_PAC_v5.docx a partir de la v4 y del mazo v12.

QUE HACE
1. Usa la v4 como plantilla tipografica: clona un parrafo prototipo por cada
   rol (titulo, Heading 1/2/3, rotulo naranja, vineta, prosa, nota, pregunta,
   respuesta) y reconstruye el cuerpo. Asi hereda tamanos, colores,
   interlineados, bordes y la definicion de numeracion de las vinetas.
2. Lee el contenido de la v4 y lo reordena segun el mazo v12, que tiene una
   diapositiva mas y la de Resiliencia movida de bloque.
3. Sobreescribe las entradas que se reescribieron en sesion: d1, d2 y d10.

Uso:  build_guion_v5.py <v4.docx> <salida.docx>
"""
import copy
import re
import sys

from docx import Document
from docx.oxml.ns import qn

# ---------------------------------------------------------------- prototipos
PROTOTIPOS = {
    "titulo": 0, "subtitulo": 1, "referencia": 2, "autor": 3,
    "h1": 4, "cuerpo": 5, "bloque": 10, "entradilla": 19, "diapo": 20,
    "rotulo": 21, "vineta": 22, "prosa": 28, "nota": 31,
    "h2": 224, "pregunta": 225, "respuesta": 226,
}


def rol_de(p):
    """Clasifica un parrafo de la v4 por su firma tipografica."""
    estilo = p.style.name if p.style is not None else ""
    if estilo == "Heading 1":
        return "h1"
    if estilo == "Heading 2":
        return "h2"
    if estilo == "Heading 3":
        return "diapo"
    if estilo == "List Paragraph":
        return "vineta"
    r = p.runs[0]
    sz = r.font.size.pt if r.font.size else None
    col = str(r.font.color.rgb) if r.font.color and r.font.color.type is not None else None
    ind = p.paragraph_format.left_indent
    if sz == 9.0:
        return "rotulo"
    if sz == 9.5:
        return "nota"
    if sz == 10.5 and r.bold:
        return "pregunta"
    if sz == 10.5:
        return "respuesta"
    if sz == 11.0 and col == "6B7280":
        return "entradilla"
    if sz == 11.0 and ind is not None:
        return "prosa"
    return "cuerpo"


def leer_v4(doc):
    """Devuelve (entradas_por_diapo, cola). La cola es todo lo que va desde
    'Preguntas anticipadas' hasta el final: se conserva tal cual."""
    ps = [p for p in doc.paragraphs if p.text.strip()]
    entradas, cola, actual = {}, [], None
    en_cola = False
    for p in ps:
        rol, txt = rol_de(p), p.text.strip()
        if txt.startswith("Preguntas anticipadas"):
            en_cola = True
        if en_cola:
            cola.append((rol, txt))
            continue
        if rol == "diapo":
            m = re.match(r"Diapo\s+(\d+)", txt)
            actual = int(m.group(1)) if m else None
            if actual:
                entradas[actual] = []
            continue
        if actual:
            entradas[actual].append((rol, txt))
    return entradas, cola


# ------------------------------------------------------------------ escritura
NEGRITA = re.compile(r"\*\*(.+?)\*\*")


def escribir(p_xml, texto):
    """Reparte el texto en runs clonados del primero del prototipo. Los tramos
    marcados con **doble asterisco** salen en negrita; el resto conserva
    EXACTAMENTE el rPr del prototipo, negrita nativa incluida.

    ⚠ No forzar w:b=0 en los tramos sin marca: deja en redonda el titulo, los
    Heading, las lineas de bloque y los rotulos, que en la v4 son bold nativo.
    """
    runs = p_xml.findall(qn("w:r"))
    if not runs:
        return p_xml
    modelo = runs[0]
    for extra in runs[1:]:
        p_xml.remove(extra)
    rPr_base = modelo.find(qn("w:rPr"))
    rPr_base = copy.deepcopy(rPr_base) if rPr_base is not None else None

    tramos, pos = [], 0
    for m in NEGRITA.finditer(texto):
        if m.start() > pos:
            tramos.append((texto[pos:m.start()], False))
        tramos.append((m.group(1), True))
        pos = m.end()
    if pos < len(texto):
        tramos.append((texto[pos:], False))
    tramos = tramos or [("", False)]

    anterior = modelo
    for i, (frag, bold) in enumerate(tramos):
        run = modelo if i == 0 else copy.deepcopy(modelo)
        if i:
            anterior.addnext(run)
        for hijo in list(run):
            run.remove(hijo)
        if rPr_base is not None:
            run.append(copy.deepcopy(rPr_base))
        t = run.makeelement(qn("w:t"), {})
        t.text, _ = frag, t.set(qn("xml:space"), "preserve")
        run.append(t)
        if bold:
            rPr = run.find(qn("w:rPr"))
            if rPr is None:
                rPr = run.makeelement(qn("w:rPr"), {})
                run.insert(0, rPr)
            for tag in ("w:b", "w:bCs"):
                if rPr.find(qn(tag)) is None:
                    rPr.insert(0, rPr.makeelement(qn(tag), {}))
        anterior = run
    return p_xml


class Guion:
    def __init__(self, plantilla):
        self.doc = Document(plantilla)
        self.proto = {r: copy.deepcopy(self.doc.paragraphs[i]._p)
                      for r, i in PROTOTIPOS.items()}
        self.entradas, self.cola = leer_v4(self.doc)
        body = self.doc.element.body
        for hijo in list(body):
            if hijo.tag != qn("w:sectPr"):
                body.remove(hijo)
        self.body = body
        self.sectPr = body.find(qn("w:sectPr"))

    def add(self, rol, texto):
        p = copy.deepcopy(self.proto[rol])
        escribir(p, texto)
        self.body.insert(list(self.body).index(self.sectPr), p)

    def encabezado(self, texto):
        """La v4 dice 'Guión' con tilde; la RAE fija 'guion' como monosilabo."""
        for p in self.doc.sections[0].header.paragraphs:
            for r in p.runs:
                if "Gui" in r.text:
                    r.text = texto

    def guardar(self, ruta):
        self.doc.save(ruta)


# ============================================================== contenido nuevo
# d1, d2 y d10 se reescribieron en sesion; el resto se hereda de la v4.

D1 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Saludar y agradecer al jurado y al director. Una línea, no más."),
    ("vineta", "Nombrar el título completo **una sola vez**. Después es «Proyecto PAC» durante toda la defensa."),
    ("vineta", "**Anunciar el arco de cuatro tramos**: evento, noche, paciente, extensión prospectiva. Ya no está en la portada, así que el jurado lo recibe solo de vos hasta la d4."),
    ("vineta", "Enunciar la línea de la portada como lo que venís a mostrar, sin explicarla."),
    ("rotulo", "Qué decir"),
    ("prosa", "Buenos días. Gracias al jurado por el tiempo, y a mi director, Rodrigo Del Rosso, por el acompañamiento."),
    ("prosa", "Soy Roberto Inza y presento el Proyecto PAC: Perfilamiento y Análisis Continuo de la fisiología nocturna del Síndrome de Apnea Obstructiva del Sueño. De acá en adelante, Proyecto PAC."),
    ("prosa", "El recorrido tiene cuatro tramos: el evento, la noche, el paciente, y una extensión prospectiva."),
    ("prosa", "Todo apunta a lo que dice esa línea: pasar del índice escalar a la fisiología dinámica de la noche. Eso es lo que vengo a mostrar."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«cuatro tramos»** es la única estructura que el jurado se lleva de este minuto. Decilo y hacé una pausa corta antes de enumerar. Los cuatro van separados por coma en el papel, pero hablados van con un silencio breve entre uno y otro: el evento · la noche · el paciente · y una extensión prospectiva. Si los decís de corrido, se pierden."),
    ("vineta", "**«del índice escalar a la fisiología dinámica de la noche»**: bajá la velocidad, es la oración más importante del minuto. Las dos mitades tienen que sonar opuestas, así que apoyá escalar y apoyá dinámica."),
    ("vineta", "**«Eso es lo que vengo a mostrar»**: punto final, silencio de dos segundos, y recién ahí pasás la diapositiva."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "**No cambies de diapositiva mientras hablás.** Terminá la frase, callate, pasá. Vale para toda la defensa, pero acá es donde se establece el ritmo."),
    ("vineta", "**El título largo se dice una vez y no vuelve.** Si lo repetís entero más adelante, suena a relleno."),
    ("vineta", "Mirá al jurado, no a la pantalla. La portada no tiene nada que señalar: es la única diapositiva donde toda tu atención puede ir a ellos. Aprovechala para fijar contacto visual con los tres antes de entrar en contenido."),
    ("vineta", "Manos visibles y quietas. Nada de bolsillos ni de apoyarse en la mesa."),
    ("vineta", "**No te disculpes por nada**, ni por el n, ni por el tiempo, ni por la voz. El primer minuto define con qué actitud te escuchan los otros cuarenta y cinco."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide unas 85 palabras: 38 a 42 segundos a ritmo de defensa. Está calibrado, no lo estires."),
    ("vineta", "El saludo es lo que se descontrola. Cronometrá este tramo por separado en los ensayos: si te vas de un minuto, estás gastando tiempo de la d2, que es la que no se puede apurar."),
    ("nota", "⚠ Esa línea de la portada es la misma que vas a tener proyectada en la d33 durante todo el turno de preguntas. Acá se enuncia, allá se entiende. Si la explicás en el minuto cero, quemás el cierre."),
]

D2 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Tres bloques, en el orden de las columnas: **qué pasa durante el sueño**, **qué mide este trabajo**, **qué índices existen hoy**."),
    ("vineta", "El segundo bloque abre presentando el instrumento: el oxímetro **no mide el flujo de aire, mide su consecuencia**, y de ahí sale que la unidad de análisis sea la desaturación y no la apnea. Recién después vienen las tres señales."),
    ("vineta", "La frecuencia se lee en el dedo: es un **indicador** de la frecuencia cardíaca. Decirlo al pasar, con la salvedad pegada."),
    ("vineta", "Cerrar con el remate proyectado: todos los índices miden cuántas veces o cuánto tiempo; **ninguno mide cómo**."),
    ("rotulo", "Qué decir"),
    ("prosa", "Antes de entrar, tres cosas que sostienen todo lo que viene."),
    ("prosa", "Primero, qué pasa durante el sueño. La vía aérea se colapsa y el flujo de aire se interrumpe diez segundos o más: eso es una apnea; si se reduce sin cortarse, una hipopnea. Cae el oxígeno en sangre, y el organismo reacciona: se acelera el corazón y aparece un microdespertar con movimiento. El ciclo se repite decenas o cientos de veces por noche."),
    ("prosa", "Segundo, qué medimos. Un oxímetro de dedo no mide el flujo de aire: mide su consecuencia. Por eso la unidad de análisis acá no es la apnea, que no vemos, sino la desaturación, que sí. Lo hace con tres señales a un hercio: la saturación, que es la consecuencia; la frecuencia cardíaca, que es la respuesta autonómica; y el movimiento, que marca el microdespertar. La frecuencia la leemos en el dedo, así que es un indicador de la cardíaca: coinciden salvo en arritmias o mala perfusión."),
    ("prosa", "Y tercero, los índices de hoy. El AHI cuenta apneas más hipopneas por hora y necesita polisomnografía. El ODI3 cuenta caídas de saturación de tres puntos o más por hora, y eso el oxímetro sí lo mide. El T90 es el porcentaje de la noche por debajo de noventa."),
    ("prosa", "Los tres miden cuántas veces o cuánto tiempo. Ninguno mide cómo."),
    ("rotulo", "Cifras y apoyos"),
    ("nota", "Apnea: interrupción del flujo de 10 s o más. Hipopnea: reducción sin interrupción."),
    ("nota", "Tres señales a 1 Hz: SpO₂ primaria · FC secundaria · MOV auxiliar."),
    ("nota", "Cortes AASM, los mismos para AHI y para ODI3: normal < 5 · leve 5 a 15 · moderado 15 a 30 · severo > 30."),
    ("nota", "T90: porcentaje de la noche con saturación por debajo de 90 %."),
    ("nota", "Remate, dicho tal cual: todos miden cuántas veces o cuánto tiempo; ninguno mide cómo."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«no mide el flujo de aire: mide su consecuencia»** es la bisagra de la diapositiva y de toda la tesis. Pausa breve después de los dos puntos. Si el jurado se lleva una sola frase de estos noventa segundos, tiene que ser esta."),
    ("vineta", "**«Ninguno mide cómo»** es el remate. Apoyá cómo y hacé silencio. Es la primera vez en toda la defensa que aparece la palabra que sostiene el trabajo entero."),
    ("vineta", "Numerá los tres bloques con la voz — primero · segundo · y tercero — y acompañá cada uno señalando su columna. Es la única diapositiva de tres columnas donde el orden de lectura importa: si no la guiás, el jurado lee la que quiere."),
    ("vineta", "**Dentro del segundo bloque el orden también importa**, y el texto hablado sigue exactamente el de la tarjeta: primero el instrumento y qué no puede ver, después la consecuencia sobre la unidad de análisis, y recién entonces las tres señales. Es la primera vez que aparece el oxímetro en toda la defensa: nombrarlo después de sus propias variables dejaba las señales colgadas de un aparato todavía no presentado."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "**La salvedad de la frecuencia de pulso va rápido, como subordinada.** Es media oración y sigue. Si te frenás a explicarla, invitás la pregunta en vez de cerrarla, que es exactamente lo contrario de lo que buscás con esa aclaración."),
    ("vineta", "**No leas los cortes AASM en voz alta.** Están proyectados como material de consulta, para que el jurado los tenga cuando aparezcan «moderado» y «severo» más adelante. Leerlos gasta veinte segundos y no agrega nada."),
    ("vineta", "**No la conviertas en clase de fisiología.** El jurado es de ciencia de datos: no sabe qué es una hipopnea, pero tampoco necesita la anatomía de la vía aérea. Definición, consecuencia, y seguís."),
    ("vineta", "No te disculpes por estar explicando algo básico. Estás pagando una deuda didáctica deliberada, no perdiendo el tiempo."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide 220 palabras: 88 a 102 segundos según el ritmo. Entra en el minuto y medio si sostenés el paso; a ritmo lento se va a 1:40."),
    ("vineta", "**Es la diapositiva que no se puede apurar**, porque es la única que nivela al jurado; pero tampoco se estira. Si venís tarde de la d1, lo primero que sale es la oración del T90: es el índice que menos aparece después."),
    ("nota", "⚠ El «cómo» del remate es la semilla de todo el trabajo: reaparece en la d7 («¿cómo cayó y cómo recuperó?»), en los morfotipos de la d8 y en el ARI de la d9. Decilo acá con intención de que el jurado lo reconozca cuando vuelva."),
]

D10 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "La pregunta obligada antes de subir de nivel: ¿es confiable la medida de una noche?"),
    ("vineta", "Dos curvas, mismo bootstrap, misma cohorte estricta. **Lo que las distingue no es la forma sino dónde arranca cada una respecto de su propio umbral.**"),
    ("vineta", "El ODI3 empieza al doble de su umbral y lo cruza recién entre 5 y 7 noches. El ARI ya empieza por debajo del suyo."),
    ("vineta", "Cierre: contar exige repetir noches; caracterizar, no."),
    ("rotulo", "Qué decir"),
    ("prosa", "Antes de subir de nivel, una pregunta obligada: ¿es confiable la medida de una noche?"),
    ("prosa", "Arriba está el error del ODI3 según cuántas noches se promedien. Con una sola noche el error es de casi cinco eventos por hora, y el umbral razonable, la línea roja, está en dos. Recién entre cinco y siete noches lo cruza."),
    ("prosa", "Abajo, el mismo cálculo para el ARI, sobre los mismos ocho pacientes y con el mismo bootstrap. Las dos curvas bajan parecido, y quiero que miren otra cosa: dónde arranca cada una respecto de su propia línea roja. El ODI3 empieza al doble de su umbral. El ARI ya empieza por debajo del suyo: con una sola noche el error es de veintiséis milésimas, sobre una escala que va de cero a uno."),
    ("prosa", "Eso es lo que dice la diapositiva. El recuento necesita repetir noches para ser confiable; la caracterización del evento, no."),
    ("rotulo", "Cifras y apoyos"),
    ("nota", "Error del ODI3: 4,8 ev/h con 1 noche · 2,7 con 3 · 1,7 con 7 · 1,2 con 14. Umbral 2 ev/h."),
    ("nota", "Error del ARI: 0,026 · 0,015 · 0,009 · 0,006 para las mismas noches. Umbral 0,05, que es el 5 % de la escala del índice."),
    ("nota", "Las dos curvas: cohorte estricta de 8 pacientes y 540 noches, 500 remuestreos, banda = IQR del bootstrap. Los valores del ODI3 son los de la Tabla 4.8 de la tesis."),
    ("nota", "Remate: el recuento necesita repetir noches para ser confiable; la caracterización del evento, no."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«dónde arranca cada una respecto de su propia línea roja»** es la diapositiva entera. Señalá las dos líneas rojas con la mano, primero la de arriba y después la de abajo. Sin ese gesto la comparación no se ve."),
    ("vineta", "**«El ARI ya empieza por debajo del suyo»**: pausa antes de dar el número. Es el único dato de la diapositiva que el jurado no espera."),
    ("vineta", "El remate va lento y separado en dos mitades, porque son dos afirmaciones opuestas sobre el mismo corpus."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "⚠ **Las dos curvas bajan con la misma forma.** Si no señalás los umbrales, el jurado concluye lo contrario de lo que estás diciendo: que el ARI también necesita muchas noches. El argumento no está en la pendiente, está en el punto de partida."),
    ("vineta", "⚠ **No digas que el ARI es más reproducible que el ODI3 a secas.** Por ICC entre noches gana el ODI3: 0,77 y 0,79 contra 0,69 y 0,74. Son preguntas distintas — el ICC mide qué proporción de la varianza es entre pacientes; estas curvas miden cuántas noches hacen falta para estabilizar la estimación. Lo defendible es lo segundo, y con esas palabras."),
    ("vineta", "**Tené lista la respuesta del 0,05.** Los 2 ev/h del ODI3 tienen tradición clínica; el umbral del ARI es una elección propia: es el 5 % de una escala que va de 0 a 1. Decilo sin titubear y sin pedir disculpas por la elección."),
    ("vineta", "No te quedes explicando el bootstrap. Si preguntan: 500 remuestreos por número de noches, y la banda son los percentiles 25 y 75."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide unas 190 palabras: 82 a 88 segundos."),
    ("vineta", "Si venís tarde, el párrafo que se recorta es el del ODI3: la curva se explica sola y el jurado ya tiene el número en la tarjeta. El del ARI no se toca, porque es el que justifica que esta diapositiva esté en el bloque de evento."),
    ("nota", "⚠ Esta diapositiva cambió de función respecto de versiones anteriores. Antes solo mostraba la fragilidad del ODI3, que es un índice nocturno, y quedaba desalineada dentro del bloque de nivel evento. Ahora compara los dos índices, y por eso el separador de la d11 la recoge en su última línea. Si alguna vez se saca el gráfico del ARI, la diapositiva vuelve a pertenecer al bloque siguiente."),
]

# ------------------------------------------------------------------- estructura
# (nueva, titulo, tiempo, origen en la v4 o None si se reescribio en sesion)
ORDEN = [
    ("Bloque 1 · Apertura y método",
     "Siete minutos. Acá el jurado forma la primera impresión y decide con qué actitud escucha el resto.", [
        (1, "Portada", "0:40", None),
        (2, "Qué es una apnea y qué se mide", "1:30", None),
        (3, "Problema clínico y analítico", "1:00", 2),
        (4, "Tesis central", "1:20", 3),
        (5, "Diseño del estudio y corpus", "1:40", 4),
        (6, "Pipeline PAC_v3", "1:00", 5),
     ]),
    ("Bloque 2 · Nivel evento",
     "Siete minutos. Primer bloque de resultados propios: bajá el ritmo y dejá que las cifras respiren.", [
        (7, "El EDO como unidad fisiológica", "1:20", 6),
        (8, "Morfotipos C1–C5", "1:40", 7),
        (9, "ARI · reactividad autonómica", "1:40", 8),
        (10, "Reproducibilidad multinoche", "1:20", None),
        (11, "Separador · Nivel Evento", "1:00", 10),
     ]),
    ("Bloque 3 · Estados PAC",
     "Cinco minutos. Es el bloque más conceptual: no te demores en la mecánica del agrupamiento.", [
        (12, "Construcción del vocabulario multiescala", "1:20", 11),
        (13, "Una noche, tres escalas", "1:20", 12),
        (14, "Especialización funcional", "1:40", 13),
        (15, "Transición · dos vocabularios", "0:40", 14),
     ]),
    ("Bloque 4 · Acoplamiento",
     "Cuatro minutos y veinte. Se acortó respecto de versiones anteriores: la resiliencia se mudó al Bloque 6, donde empalma con la predicción.", [
        (16, "Acoplamiento · el contexto cambia el riesgo", "1:00", 15),
        (17, "El estado no es fondo, es terreno medible", "1:40", 16),
        (18, "Coupling Index", "1:40", 17),
     ]),
    ("Bloque 5 · Modelos y Risk Score",
     "Siete minutos. El bloque de mayor densidad y del que más van a salir preguntas.", [
        (19, "Dos modelos de riesgo", "2:00", 19),
        (20, "De dos modelos a dos scores", "1:40", 20),
        (21, "Risk Score PAC", "2:20", 21),
        (22, "Separador · Nivel Noche", "1:00", 22),
     ]),
    ("Bloque 6 · App clínica y resiliencia",
     "Tres minutos y cuarenta. La app no es el foco evaluativo; la resiliencia sí, porque es la bisagra hacia el bloque prospectivo.", [
        (23, "PAC App", "2:00", 23),
        (24, "Resiliencia e inercia", "1:40", 18),
     ]),
    ("Bloque 7 · Predicción prospectiva",
     "Siete minutos. Es el bloque mejor calificado en las revisiones internas: mostralo con confianza.", [
        (25, "Gancho", "0:40", 24),
        (26, "Cómo está construido el modelo", "2:00", 25),
        (27, "Resultado", "3:00", 26),
        (28, "Separador · Nivel Prospectivo", "1:20", 27),
     ]),
    ("Bloque 8 · Cierre",
     "Cinco minutos. Define la impresión final: sostené el tono condicional hasta el último renglón.", [
        (29, "Tres preguntas que los índices clásicos no responden", "1:30", 28),
        (30, "Limitaciones", "1:10", 29),
        (31, "Agenda de trabajo futuro", "1:00", 30),
        (32, "Conclusiones", "1:00", 31),
        (33, "Gracias", "0:20", 32),
     ]),
]

NUEVAS = {1: D1, 2: D2, 10: D10}

PREGUNTA_NUEVA = (
    "¿La FC que usan es frecuencia cardíaca o frecuencia de pulso?",
    "Frecuencia de pulso, medida por fotopletismografía en el dedo. Es un indicador de la "
    "frecuencia cardíaca y coinciden salvo en déficit de pulso: fibrilación auricular, "
    "extrasístoles frecuentes o hipoperfusión marcada. La objeción conocida de la literatura "
    "es sobre la variabilidad latido a latido, donde la variabilidad del pulso no sustituye "
    "bien a la del ritmo cardíaco en apnea del sueño; el ARI no usa variabilidad sino el "
    "incremento de frecuencia en lpm durante el evento, que es una tasa promediada y bastante "
    "más robusta a ese problema.",
)


def main():
    plantilla, salida = sys.argv[1], sys.argv[2]
    g = Guion(plantilla)
    g.encabezado("Guion de defensa oral · Proyecto PAC")

    total = sum(int(t.split(":")[0]) * 60 + int(t.split(":")[1])
                for _, _, bs in ORDEN for _, _, t, _ in bs)
    tot_txt = f"{total // 60} minutos y {total % 60:02d} segundos" if total % 60 else f"{total // 60} minutos"

    for rol, txt in [
        ("titulo", "Guion de defensa oral"),
        ("subtitulo", "Proyecto PAC — Perfilamiento y Análisis Continuo"),
        ("referencia", "Sobre Tesis_PAC_presentacion_conceptual_Mac_editable_v12.pptx · "
                       f"33 diapositivas · {tot_txt}"),
        ("autor", "Roberto Inza · Universidad Austral · Agosto 2026"),
        ("h1", "Cómo usar este guion"),
        ("cuerpo", "Cada diapositiva tiene hasta cuatro bloques, siempre en el mismo orden."),
        ("vineta", "**Puntos de apoyo** es el esqueleto de la diapositiva. Sirve para engancharte si se corta el hilo y para repasar en los minutos previos."),
        ("vineta", "**Qué decir** es el texto hablado literal, escrito como se dice. Está medido: cada entrada respeta el tiempo asignado a esa diapositiva. Sirve para practicar con cronómetro, no para leer."),
        ("vineta", "**Cifras y apoyos** son los números exactos y el remate. Esto sí conviene tenerlo memorizado al dígito: un número dicho con precisión vale más que tres dichos con aproximación. Solo aparece donde hay números."),
        ("vineta", "**Énfasis y atención** es la puesta en escena: dónde marcar la voz, qué cuidar, cuándo callarse y qué mirar. Incluye el control de reloj de esa diapositiva."),
        ("cuerpo", "Las diapositivas 1, 2 y 10 están escritas con este esquema completo. El resto conserva por ahora el desarrollo de la versión anterior, renumerado según el mazo v12, y se va reescribiendo diapositiva por diapositiva."),
        ("cuerpo", "Si un bloque se estira, recortar primero el Bloque 6 (la app) y después el Bloque 3 (construcción de los estados)."),
        ("h1", "Estructura y tiempos"),
    ]:
        g.add(rol, txt)

    for titulo, _, diapos in ORDEN:
        ini, fin = diapos[0][0], diapos[-1][0]
        seg = sum(int(t.split(":")[0]) * 60 + int(t.split(":")[1]) for _, _, t, _ in diapos)
        dur = f"{seg // 60} min" + (f" {seg % 60} s" if seg % 60 else "")
        g.add("bloque", f"{titulo}   d{ini} – d{fin}   {dur}")

    for titulo, entradilla, diapos in ORDEN:
        g.add("h1", titulo)
        g.add("entradilla", entradilla)
        for num, nombre, tiempo, origen in diapos:
            g.add("diapo", f"Diapo {num}   {nombre}   ·   {tiempo}")
            for rol, txt in (NUEVAS[num] if num in NUEVAS else g.entradas[origen]):
                g.add(rol, txt)

    for i, (rol, txt) in enumerate(g.cola):
        g.add(rol, txt)
        # la pregunta sobre la señal cardíaca entra al final del bloque II
        if txt.startswith("¿Por qué LightGBM"):
            continue
        if rol == "respuesta" and g.cola[i - 1][1].startswith("¿Por qué LightGBM"):
            g.add("pregunta", PREGUNTA_NUEVA[0])
            g.add("respuesta", PREGUNTA_NUEVA[1])

    g.guardar(salida)
    print("escrito:", salida)
    print("total:", tot_txt)


if __name__ == "__main__":
    main()
