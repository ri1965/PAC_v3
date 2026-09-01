#!/usr/bin/env python3
"""
Genera el guion de defensa a partir de la v4 (plantilla + contenido heredado)
y del mazo vigente.

⚠ Script SIN version en el nombre, a proposito: la version del guion se pasa
por argumento. Versionar el script obligaba a duplicar 400 lineas por cada
ronda de correcciones.

QUE HACE
1. Usa la v4 como plantilla tipografica: clona un parrafo prototipo por cada
   rol (titulo, Heading 1/2/3, rotulo naranja, vineta, prosa, nota, pregunta,
   respuesta) y reconstruye el cuerpo. Asi hereda tamanos, colores,
   interlineados, bordes y la definicion de numeracion de las vinetas.
2. Lee el contenido de la v4 y lo reordena segun el mazo v12, que tiene una
   diapositiva mas y la de Resiliencia movida de bloque.
3. Sobreescribe las entradas que se reescribieron en sesion: d1, d2 y d10.

Uso:  build_guion.py <v4.docx> <salida.docx>
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
        if rol == "h1":
            # ⚠ Los encabezados de bloque de la v4 viven ENTRE entradas de
            # diapositiva. Sin este corte quedaban capturados dentro de la
            # entrada anterior, y el .docx salía con el encabezado viejo
            # («Bloque 4 · Acoplamiento y dinámica · Seis minutos») pegado al
            # final de esa diapositiva, justo antes del encabezado nuevo.
            # Defecto presente desde la v5 hasta la v12.
            actual = None
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
    ("nota", "⚠ Esa línea de la portada es la misma que vas a tener proyectada en la d35 durante todo el turno de preguntas. Acá se enuncia, allá se entiende. Si la explicás en el minuto cero, quemás el cierre."),
]

D2 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Tres bloques, en el orden de las columnas: **qué pasa durante el sueño**, **qué mide este trabajo**, **qué índices acepta la clínica hoy**."),
    ("vineta", "El segundo bloque abre presentando el instrumento: el oxímetro **no mide el flujo de aire, mide su consecuencia**, y de ahí sale que la unidad de análisis sea la desaturación y no la apnea. Recién después vienen las tres señales."),
    ("vineta", "La frecuencia se lee en el dedo: es un **indicador** de la frecuencia cardíaca. Decirlo al pasar, con la salvedad pegada."),
    ("vineta", "El AHI está proyectado en gris: **decilo en voz alta**. Es el único de los cuatro índices que esta cohorte no puede medir, porque necesita polisomnografía."),
    ("vineta", "Cerrar con el remate proyectado: los cuatro resumen la noche en un número; **ninguno describe cómo**."),
    ("rotulo", "Qué decir"),
    ("prosa", "Antes de entrar, tres cosas que sostienen todo lo que viene."),
    ("prosa", "Primero, qué pasa durante el sueño. La vía aérea se colapsa y el flujo de aire se interrumpe diez segundos o más: eso es una apnea; si se reduce sin cortarse, una hipopnea. Cae el oxígeno en sangre, y el organismo reacciona: se acelera el corazón y aparece un microdespertar con movimiento. El ciclo se repite decenas o cientos de veces por noche."),
    ("prosa", "Segundo, qué medimos. Un oxímetro de dedo no mide el flujo de aire: mide su consecuencia. Por eso la unidad de análisis acá no es la apnea, que no vemos, sino la desaturación, que sí. Lo hace con tres señales a un hercio: saturación, frecuencia cardíaca y movimiento. La frecuencia la leemos en el dedo, así que es un indicador de la cardíaca: coinciden salvo en arritmias o mala perfusión."),
    ("prosa", "Y tercero, los índices de hoy. El AHI cuenta apneas más hipopneas por hora: es el estándar clínico, y lo puse en gris porque necesita polisomnografía. Es el único de los cuatro que esta cohorte no puede medir. El ODI3 cuenta caídas de tres puntos o más por hora, y eso el oxímetro sí lo mide. El T90 es el porcentaje de la noche por debajo de noventa. Y la carga hipóxica es el área bajo las desaturaciones: cuánto oxígeno se perdió, no cuántas veces."),
    ("prosa", "Los cuatro resumen la noche en un número. Ninguno describe cómo."),
    ("rotulo", "Cifras y apoyos"),
    ("nota", "Apnea: interrupción del flujo de 10 s o más. Hipopnea: reducción sin interrupción."),
    ("nota", "Tres señales a 1 Hz: SpO₂ primaria · FC secundaria · MOV auxiliar."),
    ("nota", "Cortes AASM, los mismos para AHI y para ODI3: normal < 5 · leve 5 a 15 · moderado 15 a 30 · severo > 30."),
    ("nota", "T90: porcentaje de la noche con saturación por debajo de 90 %. Carga hipóxica: área bajo las desaturaciones respecto del baseline previo, sumada sobre la noche y dividida por el tiempo de sueño (%·min/h). Ni el T90 ni la carga hipóxica tienen umbral consensuado."),
    ("nota", "Respaldo del «decenas o cientos», si lo piden: en este corpus la mediana es de 81 eventos por noche contados por ODI3, con percentil 90 en 173 y máximo 408. Contando EDOs con umbral de 2 pp, mediana 140 y máximo 434."),
    ("nota", "Remate, dicho tal cual: los cuatro resumen la noche en un número; ninguno describe cómo."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«no mide el flujo de aire: mide su consecuencia»** es la bisagra de la diapositiva y de toda la tesis. Pausa breve después de los dos puntos. Si el jurado se lleva una sola frase de estos noventa segundos, tiene que ser esta."),
    ("vineta", "**«Ninguno describe cómo»** es el remate. Apoyá cómo y hacé silencio. Es la primera vez en toda la defensa que aparece la palabra que sostiene el trabajo entero."),
    ("vineta", "Numerá los tres bloques con la voz — primero · segundo · y tercero — y acompañá cada uno señalando su columna. Es la única diapositiva de tres columnas donde el orden de lectura importa: si no la guiás, el jurado lee la que quiere."),
    ("vineta", "**Dentro del segundo bloque el orden también importa**, y el texto hablado sigue exactamente el de la tarjeta: primero el instrumento y qué no puede ver, después la consecuencia sobre la unidad de análisis, y recién entonces las tres señales. Es la primera vez que aparece el oxímetro en toda la defensa: nombrarlo después de sus propias variables dejaba las señales colgadas de un aparato todavía no presentado."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "**La salvedad de la frecuencia de pulso va rápido, como subordinada.** Es media oración y sigue. Si te frenás a explicarla, invitás la pregunta en vez de cerrarla, que es exactamente lo contrario de lo que buscás con esa aclaración."),
    ("vineta", "**No leas los cortes AASM en voz alta.** Están proyectados como material de consulta, para que el jurado los tenga cuando aparezcan «moderado» y «severo» más adelante. Leerlos gasta veinte segundos y no agrega nada."),
    ("vineta", "**No la conviertas en clase de fisiología.** El jurado es de ciencia de datos: no sabe qué es una hipopnea, pero tampoco necesita la anatomía de la vía aérea. Definición, consecuencia, y seguís."),
    ("vineta", "No te disculpes por estar explicando algo básico. Estás pagando una deuda didáctica deliberada, no perdiendo el tiempo."),
    ("nota", "**La carga hipóxica es la que puede traerte pregunta**"),
    ("vineta", "Es el único de los cuatro que **sí parte de información de evento**: profundidad por duración de cada caída, que el AHI y el ODI3 descartan. Azarbarzin 2019, que citás en la tesis, muestra que predice mortalidad cardiovascular independientemente del AHI. Si alguien te dice que la carga hipóxica ya mide algo del «cómo», tiene parte de razón."),
    ("vineta", "La respuesta corta, y es la que afila tu punto: **no es que no mire el evento, es que lo colapsa**. Al sumar sobre la noche pierde la distribución — una noche de muchos eventos leves y otra de pocos severos pueden dar la misma carga hipóxica. Eso es exactamente lo que separan los morfotipos de la d8."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide 240 palabras: 96 a 111 segundos según el ritmo. El cuarto índice empujó la diapositiva de 1:30 a 1:45."),
    ("vineta", "**Es la diapositiva que no se puede apurar**, porque es la única que nivela al jurado; pero tampoco se estira. Si venís tarde de la d1, lo primero que sale es la oración del T90: es el índice que menos aparece después."),
    ("nota", "⚠ El remate cambió de forma por una razón de fondo. Decía «todos miden cuántas veces o cuánto tiempo», y esa dicotomía cerraba con tres índices: el AHI y el ODI3 cuentan veces, el T90 cuenta tiempo. La carga hipóxica no hace ninguna de las dos — integra profundidad por duración — así que la enumeración quedaba corta. «Resumen la noche en un número» es inmune a cuántos índices haya en la tarjeta."),
    ("nota", "⚠ El «cómo» del remate es la semilla de todo el trabajo: reaparece en la d7 («¿cómo cayó y cómo recuperó?»), en los morfotipos de la d8 y en el ARI de la d9. Decilo acá con intención de que el jurado lo reconozca cuando vuelva."),
]

D10 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "La pregunta obligada antes de cerrar el nivel evento: ¿cuántas noches hacen falta para confiar en lo que medimos? **Y la respuesta no es la misma para los dos índices.**"),
    ("vineta", "Arriba, el ODI3: con una sola noche puede cambiarle la categoría AASM a un paciente que esté cerca de un corte. Cruza su umbral recién en la sexta noche."),
    ("vineta", "Abajo, el ARI: **se lee desde el primer registro porque su referencia es el corpus entero, no la noche**. Es una propiedad de diseño, no un resultado."),
    ("vineta", "Con 8 pacientes esto es exploratorio, y se dice."),

    ("rotulo", "Qué decir"),
    ("prosa", "Definido el ARI, queda una pregunta obligada antes de cerrar el nivel evento: ¿cuántas noches hacen falta para confiar en lo que medimos?"),
    ("prosa", "Arriba está el error del ODI3 según cuántas noches se promedien. Con una sola noche ronda los cinco eventos por hora, y eso alcanza para que un paciente que está cerca de un corte de la AASM quede clasificado en la categoría equivocada. El umbral razonable, la línea roja, está en dos eventos por hora, y se cruza recién en la sexta noche."),
    ("prosa", "Abajo, el mismo cálculo para el ARI, sobre los mismos ocho pacientes y con el mismo bootstrap. Y acá hay algo de diseño que conviene explicar: el ARI no mide una cantidad, mide la posición de cada evento entre todos los del estudio. La referencia es siempre la misma, así que su valor se puede leer desde el primer registro."),
    ("prosa", "Con ocho pacientes esto es exploratorio y lo digo con todas las letras. Pero la dirección es clara: el recuento exige varias noches; la reactividad, al parecer, menos."),

    ("rotulo", "Cifras y apoyos"),
    ("nota", "Error del ODI3: 4,8 ev/h con 1 noche · 2,7 con 3 · 1,7 con 7 · 1,2 con 14. Umbral 2 ev/h, cruzado en la noche 6."),
    ("nota", "Error del ARI: 0,026 · 0,015 · 0,009 · 0,006 para las mismas noches. Umbral 0,05, que es el 5 % de una escala de 0 a 1."),
    ("nota", "Las dos curvas: cohorte estricta de 8 pacientes y 540 noches, 500 remuestreos, banda = IQR del bootstrap. Los valores del ODI3 son los de la Tabla 4.8 de la tesis."),
    ("nota", "Mala clasificación AASM: con una noche, cerca del 20 % de las estimaciones caen en otra categoría; con seis, el 4,5 %. ⚠ Ese porcentaje depende de dónde caiga cada paciente respecto de los cortes — el que promedia 14,4 se da vuelta casi siempre, el que promedia 64,8 no se mueve nunca."),
    ("nota", "Remate: el recuento exige varias noches; la reactividad, al parecer, menos."),

    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«quede clasificado en la categoría equivocada»** es la consecuencia que nadie te va a discutir: los cortes de la AASM están en 5, 15 y 30, y un error de cinco eventos por hora los cruza. Es lo más sólido de la diapositiva."),
    ("vineta", "**«la referencia es siempre la misma»** es el mecanismo del ARI, no su resultado. Decilo como explicación de diseño y no como hallazgo: es lo que lo vuelve inatacable."),
    ("vineta", "El remate va lento y con **«al parecer» dicho, no tragado**. Esa locución es la que mantiene la afirmación dentro de lo que sostiene la tesis."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "⚠ **No digas que el ARI es más estable ni más reproducible que el ODI3.** Se verificó de cinco formas y ninguna lo respalda: ICC 0,796 contra 0,739 · error de una noche relativo a la dispersión entre pacientes 35 % contra 49 % · caída del error entre la noche 1 y la 6, 60 % contra 62 % · error de una noche sobre la asíntota 4,0 contra 4,3 · conservación del orden de los pacientes con una noche, 85 % contra 84 %. **Normalizado, el ARI no gana.** Lo defendible es lo que dice el §4.5: cada índice llega a su propio umbral en distinto número de noches."),
    ("vineta", "⚠ **El umbral de 0,05 es una elección propia.** Si preguntan: es el 5 % de una escala que va de 0 a 1, y no existen categorías clínicas del ARI contra las cuales fijar otra cosa. Decilo sin pedir disculpas — que la vara no esté establecida es precisamente lo que el trabajo señala como pendiente."),
    ("vineta", "⚠ **«Estable desde la primera noche» no significa que no mejore**: el error va de 0,026 a 0,006. Lo correcto es que ya arranca dentro de su margen. Si decís que no cambia, el gráfico te desmiente a la vista."),
    ("vineta", "No te quedes explicando el bootstrap. Si preguntan: 500 remuestreos por número de noches, banda de percentiles 25 y 75."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide unas 185 palabras: 79 a 85 segundos."),
    ("vineta", "Si venís tarde, lo que sale es el párrafo del mecanismo del ARI. El de la categoría AASM no se toca: es el único argumento incontrovertible del bloque."),
    ("nota", "⚠ Esta diapositiva cambió de función respecto de versiones anteriores. Antes mostraba solo la fragilidad del ODI3 —un índice nocturno— y quedaba desalineada dentro del bloque de nivel evento. Ahora compara los dos índices, y por eso el separador de la d11 la recoge en su tercera línea. Si alguna vez se saca el gráfico del ARI, la diapositiva vuelve a pertenecer al bloque siguiente."),
]

D11 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Tres líneas y un silencio. **Es un cierre, no una explicación**: no agregues nada que no esté proyectado."),
    ("vineta", "Cada una avanza sobre la anterior: qué hace cada enfoque, qué encuentra, qué cuesta."),
    ("vineta", "Después de la tercera, dos segundos de silencio antes de pasar."),

    ("rotulo", "Qué decir"),
    ("prosa", "Cierro el nivel evento con tres ideas. El ODI3 cuenta eventos; el morfotipo y el ARI los caracterizan."),
    ("prosa", "Dos eventos con la misma caída no son iguales: su forma y su respuesta autonómica revelan lo que el recuento no registra."),
    ("prosa", "Y caracterizar el evento no solo agrega información: podría requerir menos noches."),

    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "Las tres líneas se leen con una pausa entre medio, no de corrido. Es el único momento del bloque en que el jurado puede recapitular; si lo llenás de palabras, le sacás el lugar."),
    ("vineta", "La segunda es **la mejor respaldada de las tres** y podés decirla con toda seguridad: C3 y C4 caen lo mismo, 12,8 y 13,0 puntos, y concentran 8,8 % y 17,9 % de la carga hipóxica. Está demostrado dos diapositivas antes."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "⚠ La tercera línea va en condicional —**podría requerir**— por la misma razón que el remate de la d10. Es la formulación del §4.5 de la tesis. No la conviertas en indicativo al decirla, que es lo que pasa naturalmente cuando uno está cómodo."),
    ("vineta", "No adelantes el nivel noche acá. El separador cierra; la puerta de entrada la abre la d12."),
    ("nota", "**Reloj**"),
    ("vineta", "Unas 55 palabras: 25 segundos de habla. El minuto asignado incluye los silencios, que son parte del contenido de esta diapositiva."),
    ("nota", "⚠ **Falta un puente al nivel noche y no está en ninguna parte.** Este separador cierra el evento y la d12 arranca construyendo el vocabulario multiescala, sin nada en el medio. Resolverlo con una frase hablada al abrir la d12."),
]



D6 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Arquitectura Medallion: Bronze, Silver, Events y Gold. Del Excel crudo del oxímetro a cinco tablas analíticas."),
    ("vineta", "**Events es una capa propia y hay que decirlo.** El patrón tiene tres capas; la cuarta la agregaste vos porque ahí cambia la unidad de análisis, de la señal al evento."),
    ("vineta", "Las dos decisiones que están en las leyendas: **Silver marca pero no excluye** —delega a Gold— y **Events usa umbral permisivo de 2 pp**, no los 3 del ODI3."),
    ("vineta", "El remate declara el préstamo: Medallion es un patrón, no un estándar."),

    ("rotulo", "Qué decir"),
    ("prosa", "El procesamiento sigue una arquitectura Medallion: Bronze, Silver, Events y Gold. Del Excel crudo del oxímetro a cinco tablas analíticas."),
    ("prosa", "Dos aclaraciones. La primera: Medallion tiene tres capas y acá hay cuatro. Events es una capa propia, y la agregué porque ahí cambia la unidad de análisis: Bronze y Silver trabajan sobre la señal a un hercio, y Events produce una entidad nueva, el evento de desaturación, con su morfología y su ARI. Y lo digo con todas las letras: esto no es un data warehouse. Tomé el patrón para ordenar el procesamiento de una tesis."),
    ("prosa", "La segunda son las dos decisiones que están en pantalla. Silver marca la calidad de la señal pero no descarta noches: delega esa decisión a Gold. Y Events detecta con un umbral permisivo de dos puntos, no los tres del ODI3, porque acá el objetivo es caracterizar la forma del evento, no diagnosticar."),

    ("rotulo", "Cifras y apoyos"),
    ("nota", "Trazabilidad: cada noche recibe un NightRecordID derivado por hash del archivo y del timestamp de inicio. El mismo archivo produce siempre el mismo identificador."),
    ("nota", "Detección de EDO: caída ≥ 2 pp, duración ≥ 10 s, recuperación al 90 % del baseline móvil de 120 s."),
    ("nota", "Gold: cinco tablas — eventos, curvas, ventanas, noches y pacientes."),
    ("nota", "Si preguntan por el umbral: el 3 % del ODI3 es una convención diagnóstica, no una frontera fisiológica. El ODI3 se calcula igual, como subconjunto, para conservar compatibilidad."),
    ("nota", "Remate: Medallion es un patrón, no un estándar; Events es una capa propia donde la unidad de análisis pasa de la señal al evento."),

    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«Events es una capa propia»** es la frase que justifica la única desviación del patrón. Decila vos, con naturalidad, antes de que alguien la note. Una desviación declarada es un criterio; una desviación descubierta por el jurado es un descuido."),
    ("vineta", "**«esto no es un data warehouse»** desarma al purista. Va dicho sin disculpas y sin énfasis defensivo: es una constatación, no una concesión."),
    ("vineta", "Las **dos decisiones** —Silver que no excluye, Events con umbral permisivo— son las que te blindan. Señalá la leyenda correspondiente al decir cada una."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "**No leas las monedas.** El texto en relieve es ilegible proyectado y además quedó desactualizado: dice «dimensiones» donde hoy corresponde «variables» y «flags» donde corresponde «marcas». Lo que vale son las cuatro leyendas de abajo, que sí están al día."),
    ("vineta", "No entres en el detalle técnico del hash. Que cada noche tiene un identificador irrepetible alcanza; la fórmula está en «Cifras y apoyos» por si preguntan."),
    ("vineta", "Cuidá el tono: **adaptación declarada, no ortodoxia defendida**. Si sonás a que estás justificando un error, el jurado va a buscar el error."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide 149 palabras: 60 a 69 segundos."),
    ("vineta", "Si venís tarde, lo que sale es la segunda mitad de la justificación de Events —la que explica el cambio de grano— y se conserva «es una capa propia» más las dos decisiones. Lo que nunca se recorta es el umbral de 2 pp: es la pregunta más probable de todo el Bloque 1."),
    ("nota", "⚠ Esta diapositiva sostiene dos cosas que reaparecen mucho después. El umbral de 2 pp es la razón por la que el corpus tiene 85.277 eventos y no muchos menos, que es lo que hace viable el agrupamiento morfológico de la d8. Y que Gold sea una sola fuente es el argumento de la d24: la app y los cuadernos comparten módulos, no hay dos implementaciones."),
]

D15 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Tres ideas y una pregunta. **Es consolidación, no explicación**: las tres líneas están escritas, se leen y se dejan."),
    ("vineta", "Bajá el ritmo. El jurado viene de tres diapositivas densas y esta es donde acomoda lo que escuchó."),
    ("vineta", "**La tercera línea es la que el Bloque 7 va a cobrar**: sin memoria no hay nada que anticipar."),
    ("vineta", "**No cierres con la transición**: la diapositiva de «dos vocabularios» sigue existiendo y es la siguiente. Este resumen consolida y para ahí."),

    ("rotulo", "Qué decir"),
    ("prosa", "Antes de seguir, tres cosas para llevarse de los Estados PAC."),
    ("prosa", "Un estado resume en una etiqueta lo que pasa en una ventana de tiempo: el nivel de las señales, los eventos que ocurren y la respuesta del organismo."),
    ("prosa", "La misma noche se lee a tres resoluciones, y cada una ve algo distinto: ninguna alcanza sola."),
    ("prosa", "Y lo más importante: la noche deja de ser un promedio. Es una secuencia con dirección y memoria."),

    ("rotulo", "Énfasis y atención"),
    ("nota", "**Dónde marcar**"),
    ("vineta", "**«dirección y memoria»** es la promesa del mazo. Apoyala y hacé un silencio: es la única frase de este bloque que el Capítulo 8 va a cobrar literalmente."),
    ("vineta", "Silencio antes de la pregunta final. El cambio de registro —de afirmar a preguntar— es lo que abre el bloque siguiente."),
    ("nota", "**Qué cuidar**"),
    ("vineta", "**No expliques las tres líneas.** Están proyectadas y son cortas; leerlas y comentarlas duplica. Si sentís que hay que aclarar alguna, la que la necesita es la primera, y con «una etiqueta por ventana» alcanza."),
    ("vineta", "⚠ **Esta diapositiva se insertó, no reemplazó a nada.** La transición «dos vocabularios» sigue viva en la d16, así que el mazo pasó a 35 diapositivas y todo lo que sigue corrió un lugar. Si en algún momento decidís fusionarlas, hay que renumerar el guion entero desde acá."),
    ("vineta", "En el habla decís «cada una ve algo distinto», que nombra la especialización funcional — el hallazgo central de la d14. La diapositiva no lo dice con esas palabras, y **no hace falta que lo diga**: el texto hablado puede cargar lo que la pantalla resume."),
    ("nota", "**Reloj**"),
    ("vineta", "El texto de «Qué decir» mide unas 70 palabras: 30 a 33 segundos. Sobra margen dentro de los 0:40, que es lo que corresponde a una diapositiva de consolidación."),
]

# ------------------------------------------------------------------- estructura
# (nueva, titulo, tiempo, origen en la v4 o None si se reescribio en sesion)
# Reemplazos quirúrgicos sobre entradas heredadas de la v4 que quedaron
# desactualizadas respecto del mazo. Se aplican en main(), antes de escribir.
REEMPLAZOS = {
    27: [("Remate: el modelo no ve el evento; la noche tiene memoria.",
          "Remate: el modelo no ve el evento; reconoce el estado que lo precede.")],
}


D31 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "**Nueve limitaciones en dos columnas**: cinco de evidencia y cuatro traslacionales. No las leas todas — nombrá las dos o tres que un jurado nombraría primero y dejá que el resto se lea."),
    ("vineta", "Las de evidencia acotan **qué se puede afirmar**: n, sesgo, ausencia de polisomnografía, circularidad y falta de validación externa. Las traslacionales acotan **qué se puede usar**."),
    ("vineta", "El remate concede primero y afirma después. **Ese orden es el que corresponde acá**, y la segunda oración encadena con la agenda: la diapositiva siguiente es la respuesta a ésta."),
    ("rotulo", "Qué decir"),
    ("prosa", "Las limitaciones no aparecieron al final: están acotadas desde el diseño, y las separo en dos grupos."),
    ("prosa", "Las de evidencia dicen qué se puede afirmar. Son doce pacientes, ocho en la cohorte estricta, y con ese número el fenotipo longitudinal por paciente queda fuera de alcance: se caracterizan eventos y noches, no individuos. Hay sesgo de selección —once de los doce son varones—, no hay polisomnografía simultánea, los agrupamientos se entrenaron sobre la misma cohorte que después alimentó los modelos, y nada se validó fuera de este corpus."),
    ("prosa", "Las traslacionales dicen qué se puede usar. Las probabilidades no están calibradas, el Risk Score y sus umbrales son operativos y no clínicos, la prevalencia varía veinte veces entre pacientes, y el efecto terapéutico del estimulador no está demostrado acá."),
    ("prosa", "Lo que la tesis muestra requiere una cohorte mayor para confirmarse. El pipeline para hacerlo ya está construido."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Decilas sin bajar la voz.** Es la diapositiva donde más se nota la seguridad: si las enunciás como quien declara el alcance, suenan a control; si las enunciás pidiendo disculpas, suenan a debilidad. Son las mismas palabras."),
    ("nota", "⚠ **No agregues atenuantes.** Ni «pero igual», ni «de todos modos creo que». La atenuación en una diapositiva de limitaciones trabaja en contra: el remate ya hace ese trabajo, y lo hace mejor porque llega después de haber concedido."),
    ("nota", "**El remate es lo único que conviene decir textual.** Las dos oraciones, con una pausa breve entre ellas — la primera concede, la segunda afirma, y la pausa es lo que las separa."),
    ("nota", "📌 **No hay pausa de cierre al final.** Encadená directo con la agenda: es la respuesta a lo que acabás de decir, y el efecto se pierde si dejás silencio en el medio."),
    ("nota", "**Reloj**: unas 170 palabras, 1:10 a ritmo de defensa. Si venís tarde, la que se recorta es la enumeración traslacional — están en pantalla y se leen solas."),
]

D33 = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "**Cuatro conclusiones, en orden ascendente**: el instrumento, el hallazgo, la consecuencia y el estatus de lo que queda."),
    ("vineta", "La cuarta —«deja hipótesis con forma medible»— **suma, no reclasifica**. Las tres anteriores están medidas sobre 85.277 eventos y 560 noches: no son conjeturas."),
    ("vineta", "**Esta diapositiva no cierra**: la frase final tiene diapositiva propia. Terminá la cuarta viñeta y pasá."),
    ("rotulo", "Qué decir"),
    ("prosa", "Cuatro conclusiones."),
    ("prosa", "Un único sensor domiciliario permite reconstruir la fisiología de la noche, no solo contar sus eventos. Ni los eventos son equivalentes ni la noche es homogénea: tienen forma, respuesta autonómica y un orden que el índice descarta. Esa estructura anticipa: permite estimar el riesgo del próximo evento con minutos de margen."),
    ("prosa", "Y el Proyecto PAC deja hipótesis con forma medible: define qué se debería probar y con qué diseño."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Las tres primeras son afirmaciones, la cuarta es una entrega.** Decilas con esa diferencia: las tres primeras cierran lo hecho, la cuarta abre lo que sigue."),
    ("nota", "⚠ **No digas «solo» ni «apenas» en la cuarta.** «Deja hipótesis con forma medible» es un resultado, no una disculpa — y viene después de tres hallazgos medidos, así que no necesita atenuarse."),
    ("nota", "**Pausá al terminar y recién ahí pasá.** La diapositiva siguiente es una sola frase sobre pantalla en blanco: necesita entrar sobre silencio, no sobre el final de una oración."),
    ("nota", "**Reloj**: unas 95 palabras, 0:40. Perdió veinte segundos respecto de versiones anteriores porque el remate se mudó a su propia diapositiva."),
]

ORDEN = [
    ("Bloque 1 · Apertura y método",
     "Siete minutos y cuarto. Acá el jurado forma la primera impresión y decide con qué actitud escucha el resto.", [
        (1, "Portada", "0:40", None),
        (2, "Qué es una apnea y qué se mide", "1:45", None),
        (3, "Problema clínico y analítico", "1:00", 2),
        (4, "Tesis central", "1:20", 3),
        (5, "Diseño del estudio y corpus", "1:40", 4),
        (6, "Pipeline PAC_v3", "1:10", 5),
     ]),
    ("Bloque 2 · Nivel evento",
     "Siete minutos. Primer bloque de resultados propios: bajá el ritmo y dejá que las cifras respiren.", [
        (7, "El EDO como unidad de análisis", "1:20", 6),
        (8, "Morfotipos C1–C5", "1:40", 7),
        (9, "ARI · reactividad autonómica", "1:40", 8),
        (10, "Reproducibilidad de los índices de evento", "1:20", None),
        (11, "Separador · Nivel Evento", "1:00", 10),
     ]),
    ("Bloque 3 · Estados PAC",
     "Cinco minutos y cuarenta. Es el bloque más conceptual: no te demores en la mecánica del agrupamiento y apoyate en el resumen de la d15.", [
        (12, "Construcción del vocabulario multiescala", "1:20", 11),
        (13, "Una noche, tres escalas", "1:20", 12),
        (14, "Especialización funcional", "1:40", 13),
        (15, "Resumen · Estados PAC", "0:40", None),
        (16, "Transición · dos vocabularios", "0:40", 14),
     ]),
    ("Bloque 4 · Acoplamiento",
     "Cuatro minutos y veinte. Se acortó respecto de versiones anteriores: la resiliencia se mudó al Bloque 7, donde abre la predicción prospectiva.", [
        (17, "Acoplamiento · el contexto cambia el riesgo", "1:00", 15),
        (18, "El estado no es fondo, es terreno medible", "1:40", 16),
        (19, "Coupling Index", "1:40", 17),
     ]),
    ("Bloque 5 · Modelos y Risk Score",
     "Siete minutos. El bloque de mayor densidad y del que más van a salir preguntas.", [
        (20, "Dos modelos de riesgo", "2:00", 19),
        (21, "De dos modelos a dos scores", "1:40", 20),
        (22, "Risk Score PAC", "2:20", 21),
        (23, "Separador · Nivel Noche", "1:00", 22),
     ]),
    ("Bloque 6 · App clínica",
     "Dos minutos. Una sola diapositiva y sin separador de cierre: la app es transferencia clínica, no un nivel de análisis. Su función acá es dejar instalado que el Risk Score PAC se calcula al día siguiente — el contraste que hace estallar la pregunta de la diapositiva que sigue.", [
        (24, "PAC App", "2:00", 23),
     ]),
    ("Bloque 7 · Predicción prospectiva",
     "Ocho minutos y cuarenta. Abre con la pregunta a sangre completa y sigue con la resiliencia como premisa fisiológica: primero se pregunta si se puede anticipar, después se muestra por qué la pregunta tiene sentido. Es el bloque mejor calificado en las revisiones internas: mostralo con confianza.", [
        (25, "Gancho", "0:40", 24),
        (26, "Resiliencia e inercia", "1:40", 18),
        (27, "Cómo está construido el modelo", "2:00", 25),
        (28, "Resultado", "3:00", 26),
        (29, "Separador · Nivel Prospectivo", "1:20", 27),
     ]),
    ("Bloque 8 · Cierre",
     "Cinco minutos. Define la impresión final: sostené el tono condicional hasta el último renglón.", [
        (30, "Tres preguntas que los índices clásicos no responden", "1:30", 28),
        (31, "Limitaciones", "1:10", 29),
        (32, "Agenda de trabajo futuro", "1:00", 30),
        (33, "Conclusiones", "0:40", 31),
        (34, "La frase final", "0:20", None),
        (35, "Gracias", "0:20", 32),
     ]),
]

NUEVAS = {1: D1, 2: D2, 6: D6, 10: D10, 11: D11, 15: D15, 31: D31, 33: D33}

# Bloques que se AGREGAN al final de una entrada heredada de la v4, sin
# reescribirla. Sirve para incorporar material nuevo a diapositivas que
# todavia no se revisaron con el esquema de cuatro bloques.
EXTRAS = {
    20: [
        ("rotulo", "El 3,3 % del ARI está proyectado: decilo vos"),
        ("nota", "La tabla muestra las seis filas, así que **el ARI aparece último, con 3,3 %**. Si lo señala el jurado, es una debilidad; si lo señalás vos, es coherencia. Decir al pasar: «el ARI aporta poco a esta tarea, y es lo esperable — fue construido para ser ortogonal a la severidad, no para predecirla»."),
        ("nota", "⚠ **Y no des vuelta la inferencia.** Que una variable no ayude **no demuestra** que mida otra cosa: una variable de puro ruido daría el mismo resultado. La ortogonalidad del ARI está establecida por ρ = 0,035 contra `drop_pct`, no por su lugar en esta tabla. Si te empujan, el aporte del ARI es el de la d10: estabilidad de paciente, ICC 0,69."),
        ("rotulo", "Los dos AP no se comparan entre sí"),
        ("nota", "AP 0,264 al lado de AP 0,834 parece un fracaso, y es al revés. **Las prevalencias son 5,57 % a nivel evento y 34,8 % a nivel noche**, así que el 0,264 levanta **4,7×** sobre el azar y el 0,834 solo **2,4×**. El número que se ve peor es el que más discrimina."),
        ("rotulo", "Dónde está el Coupling Index"),
        ("nota", "Quien vio la d19 lo va a buscar en esta tabla y no está. **La tabla es del modelo de noche**, cuyos bloques son las fracciones de estado, los morfotipos, la dinámica, las clínicas, el sueño y el ARI. El Coupling Index entra al **modelo de evento**, como `ci_so_far`, y ahí es la **tercera variable más importante**, detrás de la posición del evento y de la morfología reciente."),
        ("nota", "📌 **Decilo aunque no pregunten**, porque es lo que vuelve literalmente cierta la última oración del bloque: en la d23 vas a decir que el Risk Score PAC está construido desde esas capas. **Los Estados PAC alimentan el Score de Noche y el Coupling Index alimenta el Score de Evento** — una capa para cada componente."),
    ],
    21: [
        ("rotulo", "Por qué 0,60 a la noche y 0,40 al evento"),
        ("nota", "La tesis declara los pesos **heurísticos**: no están ajustados. Pero hay un argumento medible detrás, y conviene tenerlo. ICC por paciente sobre las 494 noches de la cohorte estricta: **Score de Noche 0,704 · Score de Evento 0,031**. O sea que el de noche es un rasgo del paciente —ICC en la liga del ARI— y el de evento prácticamente no tiene estructura de paciente."),
        ("nota", "⚠ **Y anticipá la repregunta obvia**: «si el componente de evento no distingue pacientes, ¿para qué pesa 0,40?». La respuesta es la mejor parte del argumento: **es complementario justamente porque su ICC es bajo**. El de noche dice *quién es el paciente*; el de evento dice *qué pasó esa noche en particular*. Si los dos fueran estables, el índice daría casi lo mismo todas las noches y no serviría para seguimiento longitudinal. Menos peso porque oscila; se conserva porque es lo único que separa dos noches del mismo paciente."),
        ("rotulo", "La palabra que plantás acá"),
        ("nota", "El contraste de las dos preguntas —**«¿qué tipo de eventos?» / «¿en qué terreno ocurrieron?»**— no es decorativo: **terreno** es la palabra con la que remata la d22 y reaparece en la d23. Decila con intención de que el jurado la reconozca cuando vuelva."),
        ("nota", "📌 **Esta diapositiva y la siguiente son un solo movimiento**: los componentes y después el índice. Por eso la d21 no lleva remate. **No hagas la pausa de cierre** — encadená directo con la pregunta de la d22."),
        ("nota", "⚠ Los valores 0,76 y 0,91 son **ilustrativos** y así lo dice el pie. Elegidos para que la cuenta de la d22 cierre a la vista: 0,40 × 0,76 + 0,60 × 0,91 = 0,85, o sea Risk Score PAC 85. Si alguien hace la cuenta, da."),
    ],
    22: [
        ("rotulo", "Tres preguntas que esta diapositiva provoca"),
        ("nota", "**¿Es 0,76 una probabilidad?** El Score de Noche sí. El de Evento es un promedio de probabilidades **normalizado por el máximo del corpus**, así que estrictamente no. Por eso el título dice «dos componentes» y no «dos probabilidades». Es una costura conocida, no un error."),
        ("nota", "**¿Por qué el umbral en 60?** Captura el 100 % de las noches severas y el 77,6 % de las moderadas — **con un 9,0 % de leves por encima**, que es el costo. Está en pantalla a propósito: un umbral presentado solo con su sensibilidad no es creíble."),
        ("nota", "**¿Por qué Normal y Leve son indistinguibles?** 28,2 contra 29,3: el índice no los separa, y **334 de las 560 noches son leves** — es la categoría modal. Si el SAOS leve es casi universal, que no se separe del normal es coherente. Lo que el índice sí separa es lo que importa: el salto de 29,3 a 73,1 entre Leve y Moderado."),
        ("rotulo", "El remate, dicho con cuidado"),
        ("nota", "⚠ **No digas «diagnóstico».** La diapositiva decía eso y se corrigió: es una **caracterización** retrospectiva. Para un índice ordinal, no calibrado, sin validación externa y con n = 8, «diagnóstico» es la única palabra de la diapositiva que un clínico del jurado puede objetar de plano."),
        ("nota", "El contraste final —**el ODI3 cuenta eventos, el Risk Score PAC describe el terreno**— es el que cobra la palabra plantada en la d21 y el que la d23 vuelve a usar. Tres apariciones, una sola idea."),
    ],
    26: [
        ("rotulo", "La definición operativa exacta"),
        ("nota", "⚠ **«Resiliente» significa que la ventana siguiente NO es patológica**, no que sea protectora. Son cosas distintas: entre lo patológico y lo protector hay estados neutros, y caen del lado resiliente. Si en pantalla dice «volver a un estado protector», al decirlo conviene precisar «**salir del estado patológico**»."),
        ("nota", "**Y el resto hasta el 100 % no es «no se recuperó»**: son eventos **sin ventana siguiente**, o sea el último de la noche. Es la respuesta si preguntan por qué las tres filas no suman igual."),
        ("nota", "Los tres valores: **43,3 % en la escala de 30 s · 12,3 % a 5 min · 1,3 % a 30 min**. La lectura es que la ventana para recuperarse se cierra a medida que sube la escala — no que el organismo no se recupere, sino que no llega a hacerlo dentro de esa ventana."),
        ("rotulo", "Por qué ahora abre el bloque en vez de cerrarlo"),
        ("nota", "En versiones anteriores esta diapositiva iba **antes** de la pregunta a sangre completa, y eso la dejaba huérfana: una diapositiva-pregunta a pantalla llena funciona como cartel de apertura, así que todo lo anterior se lee como del bloque previo. Ahora la pregunta abre y **la resiliencia contesta por qué la pregunta tiene sentido**."),
        ("nota", "📌 **El enganche verbal es lo que sostiene el cambio.** No entres presentando un hallazgo: entrá contestando. Algo como «*Y hay una razón fisiológica para pensar que se puede: el sistema tiene inercia*». Después vienen los números."),
        ("nota", "⚠ **Cuidá la palabra «memoria».** Remata esta diapositiva y también la siguiente, y además es el cierre de la última diapositiva de la tesis. **Usala acá, donde hace trabajo argumental** —conecta con *anticipar*—. Por eso la d27 remata con «reconoce el estado que lo precede» y no con «memoria»: si se dice tres veces, llega gastada al cierre de la d33, que es donde vive la última frase de la tesis."),
    ],
    13: [
        ("rotulo", "Por qué trayectoria y no promedio"),
        ("nota", "El argumento en una línea: **un promedio alcanza solo si el orden da igual.** Si los estados se sucedieran al azar, saber qué fracción de la noche pasó en cada uno sería toda la información disponible y la composición bastaría para describirla. La noche no tendría historia, tendría receta."),
        ("nota", "**Y no es el caso, por tres cosas que el promedio destruye.** Primero, **hay estados que atraen**: las matrices de transición —462.519 en la escala S, 45.900 en M, 7.196 en L— tienen atractores, S1, M0 y L3. La noche no deambula: tiende a caer en ciertos lugares y quedarse."),
        ("nota", "Segundo, **las transiciones son asimétricas**: hay un corredor de deterioro en la escala M que va de protector a moderado, a antesala, a severo, y el camino de vuelta no es el mismo al revés."),
        ("nota", "Tercero, **hay memoria**: después de un evento severo, la probabilidad de salir del estado patológico es 43 % a 30 s, 12 % a 5 min y 1 % a 30 min. Una vez que la noche entra en el estado más severo, rara vez sale dentro de esa misma noche."),
        ("nota", "Dirección, memoria y lugares de los que cuesta salir: **eso es lo que distingue una trayectoria de una secuencia**."),
        ("nota", "**Si lo tenés que decir**: «Hasta acá la noche era una composición: tanto por ciento del tiempo en un estado, tanto en otro. Si el orden fuera indistinto, con eso alcanzaría. Pero los estados no se suceden al azar: hay estados que atraen, transiciones que casi nunca ocurren, y una vez que la noche entra en el estado más severo rara vez vuelve atrás. Por eso deja de ser un promedio y pasa a ser una trayectoria.»"),
        ("nota", "⚠ **Para qué plantás la palabra acá.** Es la que vas a cobrar en la d26 con la resiliencia y sobre todo en el Bloque 7: **la predicción prospectiva funciona porque la noche tiene memoria**. Si fuera una sucesión azarosa de estados no habría nada que anticipar. «Trayectoria» en la d13 es la promesa que el Capítulo 8 cumple, y conviene decirla sabiendo eso."),
    ],
    19: [
        ("rotulo", "Qué mide el CI y qué no"),
        ("nota", "**El CI es una medida de distribución, no de duración ni de gravedad.** Dice qué fracción de los eventos severos de una noche cayó en estados patológicos. **No dice cuánto tiempo estuvo la noche comprometida** — eso son las fracciones de estado, que son otras variables. Si decís «pasó horas en estados vulnerables» estás afirmando algo que el índice no mide."),
        ("nota", "⚠ **Tampoco dice cuán grave fue la noche**, y hay un dato que lo descarta: `ci_s` correlaciona **−0,218** con el ODI3. Las noches con más eventos tienden a tener CI **más bajo**, no más alto — con muchísimos eventos, aparecen en todas partes, incluidos los tramos protegidos, y la concentración cae. Si el CI midiera gravedad, esa correlación sería positiva."),
        ("nota", "**El concepto es de coherencia**: CI alto significa que los eventos severos y el terreno comprometido coincidieron; CI bajo, que los eventos cayeron por fuera y el contexto no da cuenta de ellos."),
        ("nota", "⚠ **Evitá el verbo «anticipar» en esta diapositiva.** El estado de una ventana se calcula con los datos de esa misma ventana y el evento está adentro: es coincidencia, no anticipación. La anticipación llega en el Bloque 7 y conviene no gastar la palabra antes de tener con qué sostenerla."),
        ("rotulo", "Pantalla y voz no repiten lo mismo"),
        ("nota", "El cierre lleva los rótulos **(CI alto)** y **(CI bajo)** proyectados, aunque el bloque interpretativo ya los explicó. **No es redundancia**: el CI es un concepto nuevo y abstracto que el jurado conoció hace treinta segundos, y a diferencia del ODI3 o de los morfotipos no tiene ningún asidero previo. En pantalla, repetir es barato y ayuda."),
        ("nota", "**Al decirlo, en cambio, no los repitas.** La voz es lineal y no admite volver atrás; «CI alto» dos veces en diez segundos suena a relleno. Decir: «Con el mismo recuento, los eventos severos pueden coincidir con los tramos comprometidos de la noche, o quedar fuera de ellos.»"),
        ("nota", "📌 **El criterio vale para todo el mazo**: la pantalla puede repetir un concepto nuevo, la voz no."),
        ("rotulo", "Si preguntan qué discrimina el índice"),
        ("nota", "Es la pregunta honesta y conviene tenerla contestada. **Más de la mitad de las noches tienen CI = 1,00 exacto**: 54 % en S, 61 % en M, 30 % en L. Las medianas son 1,00 · 1,00 · 0,75. O sea que **la concentración es la norma y lo informativo es la excepción** — la noche en que los eventos severos cayeron por fuera del terreno comprometido."),
        ("nota", "⚠ **Y una atenuación por techo que conviene conocer.** El §6.3 justifica combinar las tres escalas con su independencia mutua, r(ci_s, ci_m) = 0,056. Excluyendo las noches en el techo quedan 93, y ahí las correlaciones suben a 0,341 · 0,598 · 0,128. **La afirmación de la tesis no es falsa** —la ausencia de multicolinealidad depende de las correlaciones observadas, que son las primeras— pero la lectura «cada una aporta información que las otras no contienen» es más matizada de lo que suena."),
        ("nota", "📌 Parte de por qué el CI vive en el techo: **S2 está clasificado como patológico y a la vez S1+S2 ocupan cerca del 60 % del tiempo**. Una porción grande de una noche típica transcurre en un estado etiquetado patológico."),
    ],
    18: [
        ("rotulo", "Cómo está organizada la diapositiva"),
        ("nota", "**No tiene subtítulo, y es deliberado.** No es un argumento con una glosa: son **dos análisis paralelos**, cada uno con su pregunta, su tabla y su conclusión. Un subtítulo global agregaba un tercer nivel de encabezado a un contenido de dos partes, y por eso se sentía redundante con la d17 aunque el texto fuera distinto."),
        ("nota", "La estructura la marcan **las dos preguntas**: si el estado anticipa la **forma** del evento —izquierda— y si anticipa su **severidad** —derecha—. Nombralas al pasar de una mitad a la otra — es lo que le dice al jurado que está viendo dos cosas y no una tabla partida."),
        ("nota", "**Enganche con la d17.** Allá preguntaste si la diferencia era solo visual o medible. Acá no contestás con una frase: **desdoblás esa pregunta en las dos que efectivamente se pueden medir**. Es una respuesta más precisa que cualquier declaración, y conviene decirlo así — «la pregunta de recién se abre en dos, y las dos tienen respuesta numérica». El recorrido va de izquierda a derecha: primero la forma, que da un resultado más débil y decreciente con la escala, y después la severidad, que es el resultado fuerte. Terminás la diapositiva por el lado que más pesa."),
        ("rotulo", "La V de Cramér, por si te la preguntan"),
        ("nota", "**Qué es**: una medida de asociación entre dos variables **categóricas**. Se deriva del chi-cuadrado y se normaliza para que quede entre 0 y 1, sin depender del tamaño de la muestra ni del tamaño de la tabla. Se lee como un coeficiente de correlación, pero para categorías: 0 es independencia, 1 es que una determina a la otra."),
    ("nota", "**Por qué esta y no una correlación**: ni el morfotipo ni el estado son números. C1 a C5 no están ordenados en una escala, y S0 a S6 tampoco. Con dos variables nominales no se puede calcular ni Pearson ni Spearman; lo que hay es una tabla de contingencia, y la V es la medida estándar para eso."),
    ("nota", "**Por qué un tamaño de efecto y no un p-valor**: con más de ochenta mil eventos, cualquier asociación por mínima que sea da significativa. El p-valor no informa nada a ese n. La V mide **cuánta** asociación hay, que es la pregunta que importa. Es el mismo criterio que la tesis aplica en todo el trabajo."),
    ("nota", "**Cómo leer los valores**: 0,356 en S es una asociación moderada; 0,231 y 0,196 son más débiles. Si te preguntan si 0,356 es alto, la respuesta honesta es que es moderado, y que **lo informativo no es el valor absoluto sino el ordenamiento entre escalas** — que cae de S a L, y que eso tiene una explicación física: cuanto más ancha la ventana, más heterogénea, y menos dice sobre un evento puntual."),
    ("nota", "⚠ **Su límite, y por eso están los riesgos relativos al lado**: la V dice **cuánta** asociación hay, no **dónde**. No indica qué estados concentran los eventos severos ni en qué dirección. Eso lo dicen los RR: S6 casi cinco veces la probabilidad base, M1 tres veces y media, L0 el doble. **La V mide la fuerza, los RR muestran el lugar.**"),
        ("nota", "Las dos conclusiones cierran cada mitad: *cuanto más patológico el estado, más probable que el evento sea severo* · *cuanto más ancha la ventana, menos dice sobre la morfología puntual de un evento específico*. La segunda es la que explica por qué la V de Cramér cae de S a L, y conviene decirla como explicación y no como disculpa."),
    ],
    16: [
        ("rotulo", "Ajuste de la versión heredada"),
        ("nota", "⚠ **La entrada de arriba viene de la v4 y termina preguntando «si se hablan entre sí». Sacá esa pregunta**: la d17 la formula mejor, con más precisión y con una imagen que la sostiene. Dicha dos veces en cuarenta segundos, la segunda pierde fuerza."),
        ("nota", "**Esta diapositiva se queda en la constatación, no en la pregunta.** Decir algo así: «Hasta acá construimos dos vocabularios por separado: los morfotipos, que describen el evento, y los estados, que describen el momento de la noche en que ocurre. Nunca los miramos juntos.» Y parar ahí — el «nunca los miramos juntos» deja la tensión abierta sin formularla."),
        ("nota", "**Por qué existe esta diapositiva**: es aire. Venís de cuatro diapositivas densas —vector, mapa de calor, tabla de correlaciones, resumen— y meter el acoplamiento sin respiro es pedirle al jurado que siga escalando. El valle es lo que hace que el pico siguiente se note."),
        ("nota", "⚠ **Vigilá la suma**: la d15 y la d16 son 0:40 cada una, o sea 1:20 seguidos de consolidación sin información nueva. Es el techo. Si al ensayar se estira, la que se recorta es **la d15** — el resumen se dice en veinte segundos y el aire visual no."),
    ],
    12: [
        ("rotulo", "Si preguntan por el vector de la ventana"),
        ("nota", "Son **24 variables**: 15 de señal (media, desvío, mínimo, máximo, p10 y p90 de SpO₂ y de FC; media, desvío y máximo de movimiento), 6 de eventos (total de EDOs, recuento por morfotipo escalar y ARI medio local) y 3 de composición de sueño (fracción de vigilia, sueño ligero y sueño profundo)."),
        ("nota", "**De dónde salen los morfotipos escalares.** Son un agrupamiento distinto del de la d8: K-means sobre diez variables escalares por evento —duración, profundidad de la caída, nadir, pendiente de bajada, pendiente de recuperación, área bajo la curva y los cuatro componentes de la respuesta— previa estandarización. Los C1–C5 de la d8 salen de la forma completa de la curva; estos, de descriptores numéricos."),
        ("nota", "⚠ **Si preguntan cuántos morfotipos escalares hay, son diez, no cuatro** (α a κ). El modelo de producción entrena con K = 10; el vector de ventana cuenta solo los cuatro primeros. Y δ tiene 151 eventos en todo el corpus, así que esa variable es prácticamente siempre cero."),
        ("nota", "⚠ **Discrepancia entre la tesis y el código.** El Cap. 5 describe esas densidades como «conteo de EDOs por tipo C1–C5»; la implementación cuenta morfotipos escalares α–δ. El mismo párrafo menciona «contexto temporal», que no existe en el vector. La diapositiva está a salvo porque dice «recuento y morfología de los eventos», cierto bajo cualquier lectura — pero **si contestás siguiendo la tesis vas a decir C1–C5 y el código dice α–δ**. Conviene saber cuál es cuál antes de que la pregunta llegue."),
        ("nota", "⚠ La etapa de sueño **sí está** en el vector, estimada a partir de las señales del dispositivo y no de una PSG. Se sacó de la diapositiva por decisión del autor; si preguntan, decilo con esa salvedad."),
    ],
    10: [
        ("rotulo", "Variabilidad real o error de medición"),
        ("nota", "**La curva no puede distinguirlas.** El bootstrap mide cuánto se aparta el promedio de k noches del promedio de largo plazo de ese paciente. Si esa dispersión viene de fisiología real —alcohol, postura, congestión, privación de sueño— o de error de estimación, **la curva se ve exactamente igual**."),
        ("nota", "**Y la variabilidad real existe, es medible y es grande.** Sobre la cohorte estricta, el 20 % de la varianza del ODI3 y el 26 % de la del ARI ocurren **dentro** del mismo paciente. En unidades interpretables: la desviación típica noche a noche de un paciente ronda los 4,1 ev/h de ODI3, franja suficiente para cruzar de leve a moderado sin que le pase nada distinto."),
        ("nota", "Para lo que la diapositiva afirma, el origen no cambia la conclusión: **si querés un descriptor estable del paciente, tenés que promediar la variación noche a noche sea cual sea su causa**. La pregunta «cuántas noches hacen falta» es indiferente a si la dispersión es fisiológica o instrumental."),
        ("nota", "⚠ **Tensión con la d3, y conviene tenerla resuelta.** Ahí proyectás «Variabilidad noche a noche = información, no ruido», y acá promediás esa misma variabilidad como si fuera dispersión a eliminar. No es contradicción, es cambio de nivel: **a nivel noche** la variabilidad es el objeto de estudio —que la misma persona tenga una noche protectora y otra de carga alta es lo que los Estados PAC y el Coupling Index describen— y **a nivel paciente** es lo que hay que promediar para obtener un rasgo longitudinal. El ICC lo formaliza: dice qué proporción de la varianza es entre pacientes y cuál es dentro."),
    ],
    9: [
        ("rotulo", "Qué significa un ARI alto o bajo"),
        ("nota", "Lo primero, porque de acá salen los malentendidos: **el ARI no mide más o menos actividad autonómica en términos absolutos, sino más o menos respuesta por unidad de estímulo**. Un paciente con eventos muy profundos puede tener un ΔFC grande y aun así un ARI bajo."),
        ("nota", "**ARI alto**: el organismo monta una respuesta cardíaca y motora amplia por cada punto que cae. Reactividad conservada, o umbral de microdespertar bajo — el paciente responde y despierta con facilidad, lo que tiende a cortar el evento temprano."),
        ("nota", "**ARI bajo**: poca respuesta por unidad de estímulo. Tres lecturas posibles y no excluyentes: reactividad autonómica disminuida, umbral de microdespertar alto —el paciente no se despierta y el evento corre largo— o habituación en pacientes con carga muy alta."),
        ("nota", "**El dato que mejor sostiene esto no necesita normalización.** El ΔFC absoluto sube de C1 a C4 (2,46 · 3,89 · 3,92 · 4,70 lpm) y **se cae en C5, a 2,88 lpm, justo donde el estímulo se duplica**: 24,4 pp de caída contra 2,84 en C1. Un estímulo 8,6 veces mayor produce una respuesta apenas 1,2 veces mayor. La hiporreactividad del C5 se ve en la señal cruda, antes de dividir por nada."),
        ("nota", "⚠ **No digas que un ARI alto es bueno y uno bajo es malo.** La tesis no muestra ningún desenlace, y la literatura de endotipos no es unívoca: un umbral de arousal bajo fragmenta el sueño y se considera un endotipo tratable, mientras que uno alto permite eventos largos pero también ventilación más estable. Lo defendible es que **en este corpus el ARI bajo se asocia al morfotipo más severo**, sin afirmar la dirección de la causalidad."),
        ("nota", "⚠ **Tené preparada la de los betabloqueantes.** Un paciente betabloqueado tiene el ΔFC embotado por farmacología, no por fisiología, y su ARI sale artificialmente bajo. Es un confusor real."),
        ("rotulo", "Qué aporta el ARI, conceptualmente"),
        ("nota", "**La ortogonalidad es de diseño, no un hallazgo.** El ARI divide el incremento de frecuencia cardíaca por la profundidad de la caída, así que remover la componente de severidad es consecuencia de la fórmula. Si alguien te lo señala, concedelo de entrada: pelear ese punto te hace perder el terreno donde sí estás fuerte."),
        ("nota", "**El hallazgo es que la ganancia residual tiene estructura de paciente.** Si el ΔFC fuera puramente proporcional a la caída, el cociente sería ruido constante y sin estructura. El ICC entre noches de 0,69 y 0,74 dice que hay variación sistemática y reproducible entre pacientes en cuánto reacciona cada organismo por unidad de estímulo. Eso no sale de la fórmula."),
        ("nota", "**Y se estabiliza desde la primera noche**: error de 0,026 contra un umbral de 0,05, mientras el ODI3 necesita cinco a siete. Caracterizás la reactividad autonómica de un paciente con una sola noche domiciliaria, algo que ningún índice de frecuencia permite."),
        ("nota", "**El gradiente inverso del C5 tampoco es artefacto.** Si fuera pura normalización, C5 caería en la media; cae al mínimo, 0,423. La hipótesis mecanística es que la respuesta autonómica es lo que termina el evento: responder poco por unidad de estímulo dejaría al evento sin cortar, y por eso se haría profundo. Bajo esa lectura **el ARI bajo no sería consecuencia de la severidad sino una de sus causas**. Es falsable, y es lo que convierte al ARI en algo más que una variable descriptiva."),
        ("nota", "**El 3,3 % de Gini de la ablación confirma en vez de refutar**: es exactamente lo esperable de una variable diseñada para ser independiente de la severidad."),
        ("nota", "⚠ **El límite, dicho por vos antes de que lo pregunten**: la tesis no muestra que el ARI prediga ningún desenlace. Muestra que es estable, que tiene estructura de paciente y que se comporta de forma no trivial en los eventos extremos. Que un ARI bajo implique peor evolución, distinta respuesta al tratamiento o más riesgo cardiovascular es lo que queda por probar, y es coherente con que el trabajo se posicione como generador de hipótesis."),
    ],
    8: [
        ("rotulo", "Cómo se lee la figura"),
        ("nota", "**El cero es el baseline local del propio evento**: la saturación que el paciente tenía justo antes de esa caída. Lo que está graficado no es SpO₂ absoluta sino ΔSpO₂, es decir SpO₂ menos ese baseline, en puntos porcentuales. Por eso las cinco curvas arrancan pegadas al cero."),
        ("nota", "El eje horizontal es **tiempo normalizado, de 0 a 100 % de la duración del evento**. Eso es lo que permite superponer un evento de 12 s con uno de 40 y compararlos por forma en vez de por duración."),
        ("nota", "Si preguntan por qué normalizar contra el baseline y no usar saturación absoluta: **sin restarlo, un paciente con hipoxemia basal crónica formaría su propio grupo por nivel y no por morfología**. La normalización es lo que hace que el agrupamiento sea de forma y no de gravedad de base."),
        ("nota", "⚠ Los cinco paneles inferiores **no comparten escala vertical**: cada uno autoescala a sus propios datos. C1 llega a −2 pp y C5 a −18,6, pero en pantalla se ven de profundidad parecida. Los nadires están en el título de cada panel. Si alguien compara profundidades a ojo, aclarálo antes de que saque una conclusión equivocada."),
        ("rotulo", "Si preguntan por C3 y C4"),
        ("nota", "Son el par que más se presta a pregunta: **misma profundidad, tiempos opuestos**. C3 cae 12,8 pp y C4 13,0 pp, con nadires de 82,0 % y 81,1 %. Pero C3 cae en 5 s y tarda 12 en recuperar, y C4 cae durante 17 s y se recupera en 8. Duración mediana: 15 s contra 27 s."),
        ("nota", "**Por eso C4 entra en los severos y C3 no: mismo pozo, casi el doble de tiempo.** Área media 231 contra 399 pp·s, y 17,9 % contra 8,8 % de la carga hipóxica del corpus, siendo C4 apenas 0,7 puntos más frecuente."),
        ("nota", "Lectura fisiológica: C4 parece un evento prolongado terminado de golpe por un microdespertar potente — es el morfotipo con mayor incremento de frecuencia cardíaca, 4,7 lpm. C3 sugiere reservas de oxígeno bajas: desaturación abrupta, pero de resolución más corta."),
        ("nota", "⚠ **No digas que C3 es benigno.** Es de menor carga, no inofensivo: una caída de casi 4 pp por segundo es en sí misma un marcador de reserva de oxígeno reducida. Lo defendible es que C4 concentra más carga hipóxica."),
    ],
}

PREGUNTA_VARIABILIDAD = (
    "Si el ODI3 varía tanto entre noches, ¿no será que el paciente tiene noches mejores y peores?",
    "Sí, y en buena medida es así. Al descomponer la varianza sobre la cohorte estricta, el "
    "20 % de la variabilidad del ODI3 ocurre dentro del mismo paciente, con una desviación "
    "típica noche a noche de unos cuatro eventos por hora: suficiente para que una misma "
    "persona cruce de leve a moderado sin que le pase nada distinto. Y quiero ser explícito en "
    "algo: el análisis de estabilización no puede distinguir esa variabilidad fisiológica del "
    "error de estimación, porque las dos producen exactamente la misma curva. Lo que sí puedo "
    "afirmar es que, cualquiera sea el origen, para obtener un descriptor estable del paciente "
    "hay que promediar varias noches. La pregunta que responde la figura es cuántas, y esa "
    "respuesta no depende de cuál de las dos fuentes domine.",
)

PREGUNTA_TENSION_VARIABILIDAD = (
    "En una diapositiva dicen que la variabilidad es información y en otra la promedian. ¿En qué quedamos?",
    "Las dos cosas, y depende del nivel de análisis. A nivel noche la variabilidad es el objeto "
    "de estudio: que un mismo paciente tenga una noche con trayectoria protectora y otra con "
    "carga alta es precisamente lo que los Estados PAC y el Coupling Index describen, y es "
    "información que un promedio destruiría. A nivel paciente, en cambio, esa misma variación "
    "es lo que hay que promediar para obtener un rasgo longitudinal estable. Es el mismo dato "
    "leído en dos de los tres niveles del trabajo, y el ICC lo formaliza: separa qué proporción "
    "de la varianza corresponde al rasgo del paciente y qué proporción a la variación entre sus "
    "noches.",
)

PREGUNTA_ARI_LECTURA = (
    "¿Qué significa un ARI alto y qué significa uno bajo?",
    "El ARI mide respuesta por unidad de estímulo, no actividad autonómica en términos "
    "absolutos, y esa distinción es la que evita el malentendido. Un ARI alto describe a un "
    "organismo que monta una respuesta cardíaca y motora amplia por cada punto de saturación "
    "que pierde: reactividad conservada, o un umbral de microdespertar bajo, que tiende a "
    "cortar el evento temprano. Un ARI bajo describe poca respuesta por unidad de estímulo, y "
    "admite al menos tres lecturas no excluyentes: reactividad disminuida, umbral de "
    "microdespertar alto —el paciente no se despierta y el evento corre largo— o habituación "
    "en pacientes con carga muy alta. Hay un dato que sostiene esto sin necesidad de "
    "normalizar: el incremento absoluto de frecuencia cardíaca sube de C1 a C4 y se cae en C5, "
    "de 4,7 a 2,9 latidos por minuto, justo donde la caída de saturación se duplica. Un "
    "estímulo casi nueve veces mayor produce una respuesta apenas un veinte por ciento mayor. "
    "Ahora, no afirmo que un ARI alto sea bueno y uno bajo malo: esta tesis no mide desenlaces, "
    "y la literatura de endotipos tampoco es unívoca en ese punto. Lo que sí sostengo es que "
    "en este corpus el ARI bajo se asocia al morfotipo más severo.",
)

PREGUNTA_BETABLOQ = (
    "Un betabloqueante embota la respuesta de frecuencia cardíaca. ¿Controlaron por medicación?",
    "No, y es una limitación que reconozco: la cohorte no tiene registro de medicación "
    "disponible para este análisis, así que un paciente betabloqueado tendría un ARI "
    "sistemáticamente bajo por farmacología y no por fisiología. Hay dos matices que acotan el "
    "problema sin resolverlo. El primero es que el efecto sería aproximadamente constante en "
    "ese paciente, con lo cual desplaza su nivel pero no explica las diferencias entre "
    "morfotipos dentro de sus propias noches, que es donde aparece el gradiente inverso. El "
    "segundo es que el capítulo 4 incluye un análisis dentro de estratos precisamente para "
    "separar el efecto de nivel del efecto de forma. Dicho eso, la solución correcta es "
    "registrar medicación en la cohorte externa, y está en la agenda de trabajo futuro.",
)

PREGUNTA_ARI_APORTE = (
    "Si el ARI es ortogonal a la severidad del evento, ¿cuál es su aporte?",
    "Empiezo por conceder lo que hay que conceder: la ortogonalidad es de diseño. El ARI "
    "divide el incremento de frecuencia cardíaca por la profundidad de la caída, así que "
    "remover la componente de severidad es consecuencia de la fórmula, no un descubrimiento. "
    "Lo que sí es hallazgo es que la ganancia que queda después de esa división tiene "
    "estructura de paciente: si el incremento de frecuencia fuera puramente proporcional a la "
    "caída, el cociente sería ruido constante, y en cambio el ICC entre noches es 0,69 y 0,74. "
    "Hay variación sistemática y reproducible entre pacientes en cuánto reacciona cada "
    "organismo por unidad de estímulo, y se estabiliza desde la primera noche, mientras el "
    "ODI3 necesita cinco a siete. Eso permite caracterizar la reactividad autonómica de un "
    "paciente con una sola noche domiciliaria. Y hay un segundo hallazgo que tampoco sale de "
    "la fórmula: el morfotipo más severo es el menos reactivo. Si fuera pura normalización "
    "caería en la media, y cae al mínimo. La lectura posible es que la respuesta autonómica "
    "sea lo que termina el evento, con lo cual una reactividad baja dejaría al evento sin "
    "cortar y el ARI bajo sería una causa de la severidad antes que su consecuencia. Lo que "
    "esta tesis no muestra, y lo digo con todas las letras, es que el ARI prediga algún "
    "desenlace clínico. Eso queda por probar.",
)

PREGUNTA_ARI_LITERATURA = (
    "¿Hay trabajos que midan la respuesta cardíaca desde oximetría? ¿En qué se diferencia el ARI?",
    "Sí, y es un frente activo. Hay trabajo reciente que propone la respuesta de frecuencia "
    "cardíaca derivada de oximetría como biomarcador de riesgo cardiovascular, y hay una línea "
    "de detección de microdespertares autonómicos desde el oxímetro orientada a endotipado, "
    "además de propuestas de endotipos basados en oxígeno que incluyen un umbral de arousal de "
    "SpO₂. La diferencia del ARI es de grano y de propósito: esos trabajos operan sobre "
    "agregados nocturnos o buscan detectar eventos de arousal, y el ARI se calcula por evento, "
    "normalizado por el estímulo, y se trata como un rasgo estable del paciente. La conexión "
    "que me parece más prometedora, y la enuncio como hipótesis, es que una reactividad baja "
    "medida así podría funcionar como estimador domiciliario del endotipo de umbral de "
    "arousal, que hoy requiere polisomnografía y modelado para estimarse.",
)

PREGUNTA_C3C4 = (
    "C3 y C4 tienen la misma profundidad. ¿Por qué C4 es severo y C3 no?",
    "Porque la severidad acá la define la carga hipóxica, no la profundidad. Los dos caen "
    "lo mismo, 12,8 y 13,0 puntos, pero son opuestos en el tiempo: C3 cae en cinco segundos "
    "y tarda doce en recuperar, con quince segundos de duración mediana; C4 cae durante "
    "diecisiete y se recupera en ocho, con veintisiete. Mismo pozo, casi el doble de tiempo. "
    "El área media es 231 contra 399 puntos por segundo, y C4 concentra el 17,9 % de la carga "
    "hipóxica del corpus contra el 8,8 % de C3, siendo apenas más frecuente. Fisiológicamente "
    "C4 se parece a un evento prolongado terminado de golpe por un microdespertar potente, y "
    "de hecho es el morfotipo con mayor incremento de frecuencia cardíaca; C3 sugiere reservas "
    "de oxígeno bajas, con una desaturación abrupta pero de resolución más corta. Quiero ser "
    "preciso en algo: C3 no es benigno, es de menor carga. Una desaturación de casi cuatro "
    "puntos por segundo es un marcador de reserva reducida, y la velocidad de resaturación "
    "tiene evidencia propia, asociada de forma independiente a somnolencia diurna excesiva.",
)

PREGUNTA_MEDALLION = (
    "Medallion tiene tres capas. ¿Por qué el pipeline tiene cuatro?",
    "Porque Medallion es un patrón de diseño, no un estándar cerrado, y admite que el "
    "número de capas varíe según el caso. Acá la cuarta capa marca un cambio de grano: "
    "Bronze y Silver operan sobre la señal muestreada a 1 Hz, y Events produce una entidad "
    "nueva, el evento de desaturación, con su morfología y su ARI. Meterla dentro de Silver "
    "habría mezclado control de calidad con lógica de dominio; meterla en Gold habría "
    "escondido el paso más revisable del pipeline, que es el criterio de detección. Y lo "
    "digo con todas las letras: esto no es un data warehouse, es un pipeline de "
    "investigación que toma el patrón para ordenar el procesamiento.",
)

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


# G34 · ficha de interpretación del Coupling Index (se agrega al final de la
# entrada de la d19, que ya tiene material propio).
EXTRAS[19] += [
    ("rotulo", "Con el mismo ODI3, ¿por qué un CI bajo y otro alto?"),
    ("nota", "Es la pregunta natural de la diapositiva. **El eje es la desaturación** — no solo su nivel sino su **dispersión**, porque el estado guarda desvío, p10 y p90 y por eso distingue una ventana con saturación baja y estable de otra que oscila. Ese es el mecanismo por el que M1 llega a ρ(T90) = 0,744. La frecuencia cardíaca, el movimiento y la etapa de sueño —estimada, no de PSG— son **contexto que la califica**, no el eje."),
    ("nota", "**La versión corta, para decir bajo presión**: «El estado resume una ventana entera: cuánto bajó la saturación y cuánto se sostuvo ahí, con la frecuencia cardíaca y el movimiento como contexto. Por eso puede distinguir si una desaturación cayó sobre una noche ya comprometida o sobre una recuperada — algo que el evento aislado no puede saber.»"),
    ("nota", "El vector de la ventana son **24 variables**: 6 de SpO₂, 6 de frecuencia cardíaca, 3 de movimiento, 6 de eventos y 3 de sueño."),
    ("nota", "⚠ **No lleves la interpretación hacia lo autonómico en la escala M.** La variable que la cargaría es `ird_mean_local`, que es el **IRD** —el índice descartado por el bug de escala, dominado por el movimiento crudo— y no el ARI. La reactividad autonómica vive en la escala S, en S5 (ρ ARI = 0,637), que no es la escala del ejemplo de la diapositiva. Queda consignado en el §44.b del CLAUDE.md."),
    ("nota", "⚠ **Registro asociativo.** Lo establecido es que los eventos severos **se distribuyen de manera no aleatoria** entre estados. El mecanismo fisiológico detrás de esa distribución no se demostró. Pasar de «se distribuyen distinto» a «la respuesta autonómica los hace distintos» es cruzar de asociación a causa sin datos que lo sostengan."),
    ("nota", "⚠ **Y el caveat de exposición**, que es la repregunta filosa: el CI **no está normalizado por el tiempo en estado patológico**. Si una noche pasó el 80 % del tiempo en estados patológicos, un CI de 0,75 está *por debajo* de lo esperable por azar. Es el mismo fenómeno del efecto techo — mediana 1,00 en S y en M. La respuesta honesta: en parte sí, y por eso el CI se lee junto con las fracciones de estado, no solo."),
]


# G35 · d27 · las doce variables y el flanco de window_position. Queda SOLO
# en el guion por decision del autor: la diapositiva no lo declara.
EXTRAS[27] = [
    ("rotulo", "Las doce variables, por si piden los nombres"),
    ("nota", "La tarjeta muestra los cinco grupos con su recuento; los nombres exactos son **`state_s_enc` · `state_m_enc` · `state_l_enc` · `window_position` · `n_ev_5min` · `n_severe_5min` · `frac_severe_10min` · `morph_mean_5min` · `time_since_last_ev` · `time_since_last_severe` · `n_severe_sofar` · `ci_sofar`**. Doce, en cinco grupos."),
    ("rotulo", "⚠ El flanco: window_position"),
    ("nota", "**Es la variable más importante del modelo a H = 2 min**, y está definida como `t_start_s / duración_total_de_la_noche` — o sea **normalizada por un dato que solo existe una vez que la noche terminó**. En tiempo real no se puede calcular: a las 3 de la mañana no sabés si el paciente se despierta a las 6 o a las 8."),
    ("nota", "**No es fuga de etiqueta**: no codifica el evento. Filtra la duración del registro. Por eso la línea de la tarjeta dice «ninguna variable conoce el evento futuro» y no «ninguna variable mira hacia adelante», que sería falso para ésta."),
    ("nota", "**Y la señal que aporta es fisiológica.** Prevalencia de evento severo en los próximos 5 minutos, por decil de la noche, sobre 464.651 ventanas de la cohorte estricta: **3,8 % en el primer decil · 8,4 % de media · 15,2 % en el último**. El riesgo sube hacia el final de la noche, que es lo esperable con más REM en la segunda mitad."),
    ("nota", "**Si preguntan, la respuesta completa**: «La posición en la noche está normalizada por la duración total del registro, así que en despliegue habría que reemplazarla por tiempo transcurrido desde el inicio del sueño, que sí se conoce en el momento. Es contexto temporal, no anticipación: la señal que aporta —que el riesgo sube hacia el final de la noche— se conserva con la versión desplegable.»"),
    ("nota", "⚠ **Decirlo antes de que lo pregunten.** Declarado por vos es una decisión de diseño; sacado bajo repregunta, con «ninguna variable conoce el evento futuro» proyectado al lado, es otra cosa."),
    ("nota", "📌 No está en las limitaciones del Cap. 8 (que hoy listan n = 8, heterogeneidad, circularidad PAC, calibración, `morph_mean_5min` ausente y falta de validación externa). Queda consignado para revisar al pasar a producción."),
    ("rotulo", "Los 30 s son cadencia, no alcance"),
    ("nota", "Si alguien pregunta cómo se predicen quince minutos con ventanas de treinta segundos: **la ventana es cada cuánto el modelo emite un riesgo, no lo que ve**. Las variables miran cinco a diez minutos hacia atrás y, en el caso de `ci_sofar` y `n_severe_sofar`, hasta el inicio de la noche. La tarjeta de la izquierda lo dice; la de la derecha da la cadencia."),
]


# G36–G38 · material de esta sesión para d18, d25 y d28.
EXTRAS[18] = EXTRAS.get(18, []) + [
    ("rotulo", "La tabla de riesgo relativo, y por qué dice «1 de cada N»"),
    ("nota", "La columna del medio no da porcentajes a propósito. Con la línea base (5,73 %) y los RR en la misma tabla, las tres columnas se pueden dividir y **no cierran**: 25 sobre 5,73 da 4,4×, no 4,9×. Los valores no están mal — **la diapositiva es fiel al consolidado**: el cuerpo dice «casi cinco veces (cerca de 1 de cada 4)» y la nota de la figura dice «4,9× … marginal 5,73 %»."),
    ("nota", "⚠ El propio documento usa **dos marginales para la misma cantidad**: 5,6 % en el cuerpo y 5,73 % en la nota de la figura. La tesis se salva porque nunca los pone juntos; una tabla sí los pone. Por eso la columna adopta el registro verbal del capítulo —«uno de cada 18», «cerca de 1 de cada 4»— que declara su propia aproximación."),
    ("nota", "**Si preguntan por qué no hay porcentajes**: «Los del capítulo son aproximaciones verbales, no mediciones al decimal; la tabla no las disfraza de precisión que no tienen.»"),
    ("nota", "📌 Para producción, no para la defensa: un recómputo directo desde el Gold da **21,3 % y RR 3,78×** para S6, con marginal 5,64 % sobre 83.029 eventos, contra los 80.345 y 5,73 % de NB05. Es una divergencia Gold ↔ tesis del mismo tipo que las del §44 del CLAUDE.md. **No afecta la defensa**: el corpus es coherente consigo mismo y es lo que el jurado leyó."),
]

EXTRAS[25] = [
    ("rotulo", "Esta diapositiva ahora ABRE el bloque"),
    ("nota", "Antes iba después de la resiliencia y quedaba huérfana: una pregunta a pantalla completa funciona como cartel de apertura, así que todo lo anterior se leía como del bloque previo. Ahora la pregunta abre y **la resiliencia contesta por qué la pregunta tiene sentido**."),
    ("nota", "**El contraste que la hace estallar viene de la d24**: la PAC App calcula el Risk Score PAC **al día siguiente**, sobre la noche ya procesada. Enganchá con eso: «Todo lo que vieron hasta acá se calcula a la mañana siguiente. ¿Y si pudiéramos hacerlo durante la noche?»"),
    ("rotulo", "El detalle de la imagen"),
    ("nota", "La pantalla del oxímetro de la foto marca **SpO₂ 86 % y PR 116 lpm** — una desaturación severa y una taquicardia. Es exactamente el acoplamiento caída-respuesta que define el ARI, así que la imagen dice la tesis sin proponérselo. Si el reloj lo permite: «*el oxímetro de la imagen marca 86 por ciento y 116 latidos: la caída y la respuesta, que es de lo que se trata todo esto*». **Cuesta cinco segundos y en este bloque no sobran** — es lo primero que se recorta."),
    ("nota", "⚠ Abajo del display se lee una marca, «Crestive Medical», que no es el SOMNI 6000. Mide menos de un centímetro proyectada. Si alguien pregunta: es una imagen ilustrativa, no el dispositivo del estudio."),
]

EXTRAS[28] = [
    ("rotulo", "Por qué H = 5 min y no 10 ni 15"),
    ("nota", "Es la pregunta que el gráfico invita, porque **la PPV mejora con el horizonte**: 20,3 % a 5 min contra 35,4 % a 15. La diapositiva ya lleva el criterio, pero conviene tenerlo dicho: **por debajo de 5 min la PPV cae a 9,6 %** —nueve de cada diez activaciones falsas— y **por encima la alarma gana precisión pero deja de decir cuándo**: avisa que habrá un evento en los próximos quince minutos, y el estimulador tendría que quedarse encendido todo ese lapso o disparar a ciegas."),
    ("nota", "El *ramp-up* no discrimina y no conviene usarlo como argumento: son 90 s, así que **H = 2 min también lo supera**. Lo que descarta H = 2 min es la PPV, no el ramp-up."),
    ("rotulo", "«Ranking», no «riesgo relativo»"),
    ("nota", "⚠ En la diapositiva del acoplamiento, «RR / riesgo relativo» es literalmente la razón de riesgos, con sus 4,9× · 3,3× · 2,0×. Acá querés decir otra cosa: que la salida **ordena** momentos por riesgo sin que el número sea una probabilidad. Decí **ranking de riesgo**, que es además la formulación de la d27."),
    ("nota", "Las cifras, al dígito: AUC **0,838 · 0,821 · 0,783 · 0,763** para H = 2, 5, 10 y 15 min. PPV **9,6 · 20,3 · 29,8 · 35,4 %**. En el umbral de Youden a H = 5 min: **sensibilidad 76 %, especificidad 74 %, PPV 20 %**, unas **20 alarmas por noche de las cuales ~4 corresponden a eventos reales**."),
]


# G39–G40 · d30 y d31. Consignado sin emitir.
EXTRAS[30] = [
    ("rotulo", "La tercera pregunta y el límite que el mazo ya declaró"),
    ("nota", "⚠ La d20 remata, en negrita, con «estos modelos anticipan cómo será el próximo evento, **no cuándo**». Diez diapositivas después esta tarjeta pregunta «¿cuándo va a ocurrir el próximo?». **La tarjeta declara el límite** —«PAC no dice cuándo exactamente, pero estima el riesgo a 5 minutos vista»— y conviene decirlo con esa misma precisión: el modelo no da un instante, da una **ventana**."),
    ("nota", "**El remate dice «el sistema PAC», no «el aprendizaje automático».** Es deliberado: después de treinta diapositivas construyendo PAC como el nombre de la representación, atribuirle la descripción a la herramienta en la última línea le devuelve el crédito al método en vez del aporte. El ML es cómo se obtuvo; PAC es qué se obtuvo."),
    ("nota", "Las tres cifras de la diapositiva: **6,0 % de eventos concentra 23,8 % de la carga hipóxica** · los índices clásicos **retienen la frecuencia y pierden el orden** · **AUC 0,821** a cinco minutos vista."),
]

EXTRAS[31] = [
    ("rotulo", "Las nueve limitaciones, y cuál falta si te la preguntan"),
    ("nota", "La diapositiva lista cinco de evidencia —tamaño muestral (12 pacientes, 8 en cohorte estricta), sesgo de selección con **11 de 12 varones**, ausencia de PSG simultánea, circularidad PAC y **falta de validación externa**— y cuatro traslacionales: probabilidades no calibradas, Risk Score y umbrales operativos y no validados clínicamente, heterogeneidad inter-paciente de **20×** en prevalencia prospectiva, y efecto terapéutico del estimulador no demostrado."),
    ("nota", "⚠ **Circularidad y validación externa no son lo mismo**, y conviene poder separarlas: la circularidad es que los *clusters* de Estados PAC se entrenaron sobre la misma cohorte que después alimentó los modelos; la validación externa es que **el sistema completo nunca se probó fuera de estos doce pacientes**. La primera se arregla reclusterizando dentro de cada *fold*; la segunda, solo con otra cohorte."),
    ("nota", "**Si preguntan por los estadios de sueño**: la diapositiva dice que sin PSG no hay comparación con AHI ni con estadios AASM, y sin embargo el vector de ventana **sí incluye etapas de sueño**. No es contradicción: son **estimaciones del propio dispositivo**, no estadificación polisomnográfica. Por eso sirven como contexto dentro del modelo y no sirven para validar contra el estándar."),
    ("nota", "📌 **No hay frase de cierre en esta diapositiva, y es deliberado.** La respuesta a estas limitaciones es la diapositiva siguiente: la agenda de trabajo futuro. Encadená sin pausa de remate — cualquier atenuante dicho acá trabaja en contra."),
]


# G41 · la frase final, que dejó de ser el remate de Conclusiones y pasó a
# tener diapositiva propia.
NUEVAS[34] = [
    ("rotulo", "Puntos de apoyo"),
    ("vineta", "Una sola frase en pantalla. **No la expliques**: es la última oración de la tesis y se sostiene sola."),
    ("vineta", "Es el último beat hablado de la defensa. Lo que sigue —la portada final— queda proyectado durante todo el turno de preguntas."),
    ("rotulo", "Qué decir"),
    ("prosa", "Una noche de sueño deja de ser un número: se convierte en una trayectoria con memoria."),
    ("prosa", "Gracias."),
    ("rotulo", "Énfasis y atención"),
    ("nota", "**Pausá antes de pasar la diapositiva.** Terminá la última viñeta de Conclusiones, callate, y recién ahí avanzá. La frase tiene que aparecer sobre silencio."),
    ("nota", "**Decila más lento de lo que venís hablando.** Apoyá **número** y apoyá **memoria**: son las dos mitades de la antítesis y el resto de la oración las une."),
    ("nota", "⚠ **Después de «memoria», dos segundos de silencio antes de «gracias».** Es la única pausa larga de toda la defensa y es la que hace que la frase quede sonando en vez de disolverse en el aplauso."),
    ("nota", "📌 **La palabra memoria se plantó en la d26** —«el sistema tiene memoria, y esa memoria es lo que hace posible anticipar»— y no se volvió a usar en veinte minutos. Por eso acá llega entera. Es la razón por la que la d27 remata con «reconoce el estado que lo precede»."),
    ("nota", "⚠ **No agregues nada.** Ni un agradecimiento largo, ni un «espero que haya quedado claro», ni un resumen. La tentación de tapar el silencio con una frase de más es fuerte y arruina el cierre."),
]


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
        ("referencia", "Sobre Tesis_PAC_presentacion_conceptual_Mac_editable_v17.pptx · "
                       f"35 diapositivas · {tot_txt}"),
        ("autor", "Roberto Inza · Universidad Austral · Agosto 2026"),
        ("h1", "Cómo usar este guion"),
        ("cuerpo", "Cada diapositiva tiene hasta cuatro bloques, siempre en el mismo orden."),
        ("vineta", "**Puntos de apoyo** es el esqueleto de la diapositiva. Sirve para engancharte si se corta el hilo y para repasar en los minutos previos."),
        ("vineta", "**Qué decir** es el texto hablado literal, escrito como se dice. Está medido: cada entrada respeta el tiempo asignado a esa diapositiva. Sirve para practicar con cronómetro, no para leer."),
        ("vineta", "**Cifras y apoyos** son los números exactos y el remate. Esto sí conviene tenerlo memorizado al dígito: un número dicho con precisión vale más que tres dichos con aproximación. Solo aparece donde hay números."),
        ("vineta", "**Énfasis y atención** es la puesta en escena: dónde marcar la voz, qué cuidar, cuándo callarse y qué mirar. Incluye el control de reloj de esa diapositiva."),
        ("cuerpo", "Las diapositivas 1, 2, 6, 10, 11 y 15 están escritas con este esquema completo. El resto conserva por ahora el desarrollo de la versión anterior, renumerado según el mazo v17, y se va reescribiendo diapositiva por diapositiva."),
        ("cuerpo", "Si un bloque se estira, recortar primero el Bloque 6 (la app) y después el Bloque 3 (construcción de los estados)."),
        ("h1", "Estructura y tiempos"),
    ]:
        g.add(rol, txt)

    for titulo, _, diapos in ORDEN:
        ini, fin = diapos[0][0], diapos[-1][0]
        seg = sum(int(t.split(":")[0]) * 60 + int(t.split(":")[1]) for _, _, t, _ in diapos)
        dur = f"{seg // 60} min" + (f" {seg % 60} s" if seg % 60 else "")
        rango = f"d{ini}" if ini == fin else f"d{ini} – d{fin}"
        g.add("bloque", f"{titulo}   {rango}   {dur}")

    for titulo, entradilla, diapos in ORDEN:
        g.add("h1", titulo)
        g.add("entradilla", entradilla)
        for num, nombre, tiempo, origen in diapos:
            g.add("diapo", f"Diapo {num}   {nombre}   ·   {tiempo}")
            bloques = list(NUEVAS[num] if num in NUEVAS else g.entradas[origen])
            for viejo, nuevo in REEMPLAZOS.get(num, []):
                bloques = [(r, t.replace(viejo, nuevo)) for r, t in bloques]
            bloques += EXTRAS.get(num, [])
            for rol, txt in bloques:
                g.add(rol, txt)

    for i, (rol, txt) in enumerate(g.cola):
        g.add(rol, txt)
        # la pregunta sobre Medallion cierra el bloque I
        if rol == "respuesta" and g.cola[i - 1][1].startswith("¿Por qué los pesos 0,6 y 0,4"):
            g.add("pregunta", PREGUNTA_ARI_LECTURA[0])
            g.add("respuesta", PREGUNTA_ARI_LECTURA[1])
            g.add("pregunta", PREGUNTA_ARI_APORTE[0])
            g.add("respuesta", PREGUNTA_ARI_APORTE[1])
            g.add("pregunta", PREGUNTA_BETABLOQ[0])
            g.add("respuesta", PREGUNTA_BETABLOQ[1])
            g.add("pregunta", PREGUNTA_VARIABILIDAD[0])
            g.add("respuesta", PREGUNTA_VARIABILIDAD[1])
            g.add("pregunta", PREGUNTA_TENSION_VARIABILIDAD[0])
            g.add("respuesta", PREGUNTA_TENSION_VARIABILIDAD[1])
            g.add("pregunta", PREGUNTA_C3C4[0])
            g.add("respuesta", PREGUNTA_C3C4[1])
        if rol == "respuesta" and g.cola[i - 1][1].startswith("¿Cuál es el aporte original frente a lo publicado"):
            g.add("pregunta", PREGUNTA_ARI_LITERATURA[0])
            g.add("respuesta", PREGUNTA_ARI_LITERATURA[1])
        if rol == "respuesta" and g.cola[i - 1][1].startswith("¿Cómo se decidió el número de estados"):
            g.add("pregunta", PREGUNTA_MEDALLION[0])
            g.add("respuesta", PREGUNTA_MEDALLION[1])
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
