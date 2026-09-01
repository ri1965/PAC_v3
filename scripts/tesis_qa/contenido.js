module.exports=({P,H1,H2,SL,ROT,SAY,BUL,NUM,QA,Paragraph,TextRun,AlignmentType,BorderStyle,F,AZ,GR,NA,OR})=>{
const c=[];
const add=(...x)=>x.forEach(y=>Array.isArray(y)?c.push(...y):c.push(y));

// ── PORTADA ──
add(new Paragraph({spacing:{before:600,after:80},alignment:AlignmentType.CENTER,
  children:[new TextRun({text:"Guión de defensa oral",font:F,size:52,bold:true,color:AZ})]}));
add(new Paragraph({spacing:{after:60},alignment:AlignmentType.CENTER,
  children:[new TextRun({text:"Proyecto PAC — Perfilamiento y Análisis Continuo",font:F,size:26,color:NA})]}));
add(new Paragraph({spacing:{after:400},alignment:AlignmentType.CENTER,
  children:[new TextRun({text:"Sobre Tesis_PAC_presentacion_conceptual_Mac_editable_v6.pptx · 32 diapositivas · 45 minutos",font:F,size:19,color:GR,italics:true})]}));
add(new Paragraph({spacing:{after:400},alignment:AlignmentType.CENTER,
  children:[new TextRun({text:"Roberto Inza · Universidad Austral · Agosto 2026",font:F,size:20,color:GR})]}));

// ── CÓMO USAR ──
add(H1("Cómo usar este guión"));
add(P("Cada diapositiva tiene dos bloques. QUÉ DECIR es prosa hablada, escrita como se dice: sirve para practicar con cronómetro y para engancharse si se corta el hilo. No está para leerse — la rúbrica de Austral evalúa explícitamente que no se lea ni se recite."));
add(P("CIFRAS Y APOYOS son los números exactos y el remate de la diapositiva. Eso sí conviene tenerlo memorizado al dígito: un número dicho con precisión vale más que tres párrafos bien redactados."));
add(P("En las diapositivas de transición y en los separadores de nivel, el bloque de prosa se reemplaza por puntos de apoyo: ahí no hay que decir mucho, hay que respirar y dejar que la idea se asiente."));
add(P("Los tiempos por diapositiva suman 45 minutos con un margen de dos. Si un bloque se estira, recortar primero el Bloque 6 (la app) y después el Bloque 3 (construcción de estados); nunca el Bloque 5 (modelos) ni el 8 (cierre).", {b:false}));

// ── TIMING ──
add(H1("Estructura y tiempos"));
[["Bloque 1 · Apertura y método","d1 – d5","6 min"],
 ["Bloque 2 · Nivel evento","d6 – d10","7 min"],
 ["Bloque 3 · Estados PAC","d11 – d14","5 min"],
 ["Bloque 4 · Acoplamiento y dinámica","d15 – d18","6 min"],
 ["Bloque 5 · Modelos y Risk Score","d19 – d22","7 min"],
 ["Bloque 6 · App clínica","d23","2 min"],
 ["Bloque 7 · Predicción prospectiva","d24 – d27","7 min"],
 ["Bloque 8 · Cierre","d28 – d32","5 min"]].forEach(([a,b,t])=>
  add(new Paragraph({spacing:{after:70},children:[
    new TextRun({text:a,font:F,size:21,bold:true,color:NA}),
    new TextRun({text:`   ${b}   `,font:F,size:20,color:GR}),
    new TextRun({text:t,font:F,size:20,bold:true,color:OR})]})));

// ── BLOQUE 1 ──
add(H1("Bloque 1 · Apertura y método"),P("Seis minutos. Acá el jurado forma la primera impresión y decide con qué actitud escucha el resto.",{i:true,c:GR}));

add(SL(1,"Portada","0:40"));
add(ROT("Puntos de apoyo"));
add(BUL("Presentarse y nombrar el título completo una vez: Perfilamiento y Análisis Continuo de la fisiología nocturna del SAOS."));
add(BUL("Agradecer al jurado y al director en una línea. No más."));
add(BUL("Anunciar el arco: evento, noche, paciente, y una extensión prospectiva."));
add(NUM("No arranques disculpándote por nada. El primer minuto define el tono."));

add(SL(2,"Problema clínico y analítico","1:20"));
add(ROT("Qué decir"));
add(SAY("El SAOS se diagnostica y se sigue con índices que cuentan eventos por hora: el AHI y el ODI3. Son útiles y están validados, pero comprimen toda una noche en un solo número, y en esa compresión se pierde la estructura fisiológica: cómo fue cada evento, cómo respondió el organismo, en qué orden ocurrieron."));
add(SAY("Al mismo tiempo, la oximetría domiciliaria ofrece algo que la polisomnografía no da: muchas noches reales del mismo paciente, con tres señales a un hercio. Esa variabilidad noche a noche se suele tratar como ruido. La hipótesis de este trabajo es que es información."));
add(ROT("Cifras y apoyos"));
add(NUM("Pregunta guía de la diapositiva: ¿puede un único sensor revelar la estructura dinámica del SAOS? Dejala dicha en voz alta, es el hilo de las próximas 30 diapositivas."));

add(SL(3,"Tesis central","1:20"));
add(ROT("Puntos de apoyo"));
add(BUL("La tesis en una oración: la fisiología nocturna del SAOS puede representarse como un sistema dinámico en tres niveles."));
add(BUL("Evento: el EDO con su morfotipo y su ARI. Noche: los Estados PAC en tres escalas más el acoplamiento. Paciente: fenotipo longitudinal y riesgo."));
add(BUL("Y una extensión: predicción prospectiva a cinco minutos, que abre la puerta a una intervención."));
add(NUM("Este esquema es el mapa. Volvé a él mentalmente cada vez que cambies de bloque."));

add(SL(4,"Diseño del estudio y corpus","1:40"));
add(ROT("Qué decir"));
add(SAY("El corpus son doce pacientes y quinientas sesenta noches de calidad, con 85.277 eventos de desaturación caracterizados. Para todo lo que sea modelo supervisado se usa una cohorte estricta de ocho pacientes y quinientas cuarenta noches."));
add(SAY("La validación es leave-one-patient-out: cada partición deja afuera un paciente completo, con todas sus noches. Esto es deliberado y quiero subrayarlo, porque es donde muchos trabajos con señales fisiológicas se equivocan: si uno parte por noche, noches del mismo paciente quedan de los dos lados y el modelo aprende al paciente, no al fenómeno. El n efectivo de este trabajo son ocho pacientes, no quinientas cuarenta noches."));
add(ROT("Cifras y apoyos"));
add(NUM("12 pacientes · 560 noches · 85.277 EDOs · cohorte estricta 8 pacientes y 540 noches."));
add(NUM("Remate: el valor no está en una noche perfecta sino en muchas noches reales."));

add(SL(5,"Pipeline PAC_v3","1:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Arquitectura Medallion: Bronze, Silver, Events, Gold. Del Excel crudo del oxímetro a cinco tablas analíticas."));
add(BUL("Dos decisiones que conviene nombrar: Silver marca la calidad pero no excluye noches — delega la decisión a Gold. Y Events detecta con umbral permisivo de 2 puntos porcentuales."));
add(BUL("Si preguntan por el umbral, la respuesta corta: el 3 % del ODI3 es una convención diagnóstica, no una frontera fisiológica, y acá el objetivo es caracterizar, no diagnosticar."));
add(NUM("Trazabilidad: cada noche tiene un identificador derivado por hash del archivo y del timestamp de inicio."));

// ── BLOQUE 2 ──
add(H1("Bloque 2 · Nivel evento"),P("Siete minutos. Primer bloque de resultados propios: bajá el ritmo y dejá que las cifras respiren.",{i:true,c:GR}));

add(SL(6,"El EDO como unidad fisiológica","1:20"));
add(ROT("Puntos de apoyo"));
add(BUL("El EDO es la unidad mínima de análisis: una caída de saturación con su recuperación."));
add(BUL("La pregunta cambia: no cuántas caídas hubo, sino cómo cayó y cómo volvió."));
add(BUL("La curva se normaliza para poder comparar eventos de duraciones distintas: esa curva normalizada es la materia prima del agrupamiento."));

add(SL(7,"Morfotipos C1–C5","1:40"));
add(ROT("Qué decir"));
add(SAY("Sobre las 85.277 curvas normalizadas hicimos componentes principales y después K-medias. Con cinco grupos aparecen cinco morfologías distintas, de la caída sutil y breve a la caída profunda y progresiva."));
add(SAY("El resultado que me interesa mostrar es este: los dos morfotipos severos, C4 y C5, son el seis por ciento de los eventos, y concentran casi el veinticuatro por ciento de la carga hipóxica total. Un índice que cuenta eventos les da a los dos el mismo peso que a los otros noventa y cuatro."));
add(ROT("Cifras y apoyos"));
add(NUM("C4+C5 = 6,0 % de los eventos · 23,8 % de la carga hipóxica · K = 5 con Silhouette 0,432."));
add(NUM("Si preguntan por qué K = 5: el Silhouette decrece desde K = 2; K = 5 es el último antes de la caída en K = 6, y el primero que separa C4 de C5."));

add(SL(8,"ARI · reactividad autonómica","1:40"));
add(ROT("Qué decir"));
add(SAY("El ARI es la contribución más original de la tesis. No mide el golpe: mide la respuesta al golpe. Es cuánta reacción cardíaca y motora genera el organismo por cada punto de caída de saturación."));
add(SAY("Y el hallazgo es contraintuitivo. El ARI resulta prácticamente ortogonal a la profundidad de la caída, con una correlación de 0,035. Es decir, saber qué tan grave fue el evento no dice casi nada sobre cuánto reaccionó el paciente. Más aún: el morfotipo más severo, C5, tiene el ARI más bajo del corpus. Los eventos peores generan menos respuesta relativa, no más."));
add(ROT("Cifras y apoyos"));
add(NUM("ρ(ARI, profundidad de caída) = 0,035 · ARI de C5 = 0,423 ± 0,104 · ICC entre noches = 0,69 y 0,74."));
add(NUM("Fórmula, si la piden: 0,6 por el rango percentil de la ganancia de frecuencia cardíaca más 0,4 por el de movimiento."));
add(NUM("⚠ En la diapositiva sólo va el 0,035, que es contra la profundidad de la caída. Si preguntan por la independencia respecto del ODI3, el valor a nivel de noche es −0,245, y la tesis lo llama asociación débil, no independencia. Son dos afirmaciones distintas: no las presentes como la misma."));

add(SL(9,"Reproducibilidad multinoche","1:20"));
add(ROT("Qué decir"));
add(SAY("Una pregunta obligada antes de subir de nivel: ¿la medida nocturna es confiable? Con una sola noche el error del ODI3 supera los cinco eventos por hora. Recién con cinco a siete noches baja de dos."));
add(SAY("Esto es exactamente lo que habilita el monitoreo domiciliario y lo que la polisomnografía de una noche no puede dar. Una noche puede diagnosticar; varias noches caracterizan."));
add(ROT("Cifras y apoyos"));
add(NUM("Error del ODI3: 4,8 ev/h con una noche · 2,7 con tres · 1,7 con siete · 1,2 con catorce."));
add(NUM("El ARI, en cambio, es estable desde la primera noche."));

add(SL(10,"Separador · Nivel Evento","1:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Leé el remate y dejá dos segundos de silencio. Es una diapositiva para cerrar, no para explicar."));
add(BUL("El ODI3 cuenta eventos; el morfotipo y el ARI los caracterizan."));

// ── BLOQUE 3 ──
add(H1("Bloque 3 · Estados PAC"),P("Cinco minutos. Es el bloque más conceptual: no te demores en la mecánica del clustering.",{i:true,c:GR}));

add(SL(11,"Construcción del vocabulario multiescala","1:20"));
add(ROT("Puntos de apoyo"));
add(BUL("La noche se corta en ventanas y cada ventana se resume en un vector fisiológico: nivel y variabilidad de saturación y frecuencia cardíaca, movimiento, estadísticos de eventos, etapa de sueño, y el ARI."));
add(BUL("El mismo insumo se agrupa a tres resoluciones: 30 segundos, 5 minutos y 30 minutos."));
add(BUL("Siete estados en la escala corta, cinco en la media, cuatro en la larga. Cada escala se calibró por separado."));
add(NUM("La metáfora que funciona: letras de 30 segundos, palabras de 5 minutos, frases de 30."));

add(SL(12,"Una noche, tres escalas","1:20"));
add(ROT("Puntos de apoyo"));
add(BUL("Acá se ve el cambio de objeto: la noche deja de ser un promedio y pasa a ser una trayectoria."));
add(BUL("Mostrá con el dedo cómo la misma noche se lee distinto según la resolución."));
add(BUL("No hace falta nombrar cada estado. La idea es que hay una secuencia, no una media."));

add(SL(13,"Especialización funcional","1:40"));
add(ROT("Qué decir"));
add(SAY("Este es el hallazgo central del capítulo, y no lo buscamos: emergió. Cada escala temporal termina especializándose en una dimensión distinta de la severidad."));
add(SAY("La frecuencia de eventos se predice mejor desde la microdinámica de treinta segundos. La carga hipóxica aparece recién en la escala de cinco minutos. La reactividad autonómica vuelve a los treinta segundos, pero con otro estado. Y la arquitectura global de la noche necesita la ventana de treinta minutos. Escalas distintas capturan dimensiones distintas de la severidad."));
add(ROT("Cifras y apoyos"));
add(NUM("S4 con ODI3: +0,690 · M1 con T90: +0,744 · S5 con ARI: +0,637 · L0 con arquitectura: +0,683."));

add(SL(14,"Transición · dos vocabularios","0:40"));
add(ROT("Puntos de apoyo"));
add(BUL("Hasta acá construimos dos vocabularios por separado: morfotipos de evento y estados de noche."));
add(BUL("La pregunta que sigue es si se hablan entre sí."));

// ── BLOQUE 4 ──
add(H1("Bloque 4 · Acoplamiento y dinámica"),P("Seis minutos.",{i:true,c:GR}));

add(SL(15,"Acoplamiento · el contexto cambia el riesgo","1:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Planteá la pregunta y no la contestes todavía: ¿el estado fisiológico activo tiene relación con el tipo de evento que ocurre dentro de él?"));
add(BUL("Por construcción todo evento ocurre dentro de algún estado. La pregunta no es si se superponen, sino si esa superposición tiene estructura."));

add(SL(16,"El estado no es fondo, es terreno medible","1:40"));
add(ROT("Qué decir"));
add(SAY("La respuesta es que sí, y se puede medir. La asociación es más fuerte en la escala corta y se debilita a medida que la ventana se agranda, lo cual tiene sentido: cuanto más ancha la ventana, menos dice sobre la morfología puntual de un evento específico."));
add(SAY("Y en términos de riesgo el efecto es grande. La probabilidad base de que un evento sea severo es del cinco coma siete por ciento, uno de cada dieciocho. Dentro del estado más patológico de la escala corta, esa probabilidad sube a uno de cada cuatro. Casi cinco veces."));
add(ROT("Cifras y apoyos"));
add(NUM("V de Cramér: 0,356 en S · 0,231 en M · 0,196 en L."));
add(NUM("Riesgo relativo: S6 = 4,9× · M1 = 3,3× · L0 = 2,0× · M0 protector < 0,4×."));

add(SL(17,"Coupling Index","1:40"));
add(ROT("Qué decir"));
add(SAY("El Coupling Index resume eso en un número por noche: qué fracción de los eventos severos ocurrió dentro de un estado patológico, calculado por separado en cada escala."));
add(SAY("Y acá está el ejemplo que mejor resume toda la tesis. Estas dos noches tienen el mismo ODI3, catorce eventos por hora, y por lo tanto la misma categoría clínica. Pero una tiene Coupling Index de 0,12 y la otra de 0,75. Los eventos son los mismos; el terreno en que ocurrieron es opuesto."));
add(ROT("Cifras y apoyos"));
add(NUM("Correlación entre escalas: 0,056 entre S y M · 0,364 entre M y L. Son en buena medida independientes, por eso conviene combinarlas."));

add(SL(18,"Resiliencia e inercia","1:40"));
add(ROT("Qué decir"));
add(SAY("La última pieza de la dinámica es qué pasa después de un evento severo. En la escala de treinta segundos el sistema vuelve a un estado protector el cuarenta y tres por ciento de las veces. En la de cinco minutos, doce. En la de treinta, apenas uno."));
add(SAY("Dicho de otro modo: el sistema tiene memoria. Una vez que entra en el estado más severo, rara vez vuelve atrás dentro de la misma noche. Esa inercia es lo que va a hacer posible la predicción del último bloque."));
add(ROT("Cifras y apoyos"));
add(NUM("Retorno protector: 43,3 % en S · 12,3 % en M · 1,3 % en L."));
add(NUM("Corredor de deterioro en la escala M: de protector a moderado, a antesala, a severo."));

// ── BLOQUE 5 ──
add(H1("Bloque 5 · Modelos y Risk Score"),P("Siete minutos. El bloque de mayor densidad y del que más van a salir preguntas.",{i:true,c:GR}));

add(SL(19,"Dos modelos de riesgo","2:00"));
add(ROT("Qué decir"));
add(SAY("Hay dos tareas distintas y conviene no confundirlas. La primera predice, para cada evento, qué tan severo va a ser, sin ver el evento en curso: un LightGBM con área bajo la curva de 0,882. La segunda clasifica la noche completa como moderada o severa, ya terminada: una regresión logística con 0,905."));
add(SAY("Y del análisis de contribución sale el resultado que más me importa: los Estados PAC concentran el cuarenta y cinco por ciento de la importancia, muy por encima de las variables clínicas convencionales. El ARI casi no aporta a predecir severidad, y eso no es un fracaso: es la confirmación de que mide otra cosa."));
add(ROT("Cifras y apoyos"));
add(NUM("Evento: AUC 0,882 · AP 0,264. Noche: AUC 0,905 · AP 0,834. Todo con LOPO-CV."));
add(NUM("Importancia Gini: Estados PAC 44,8 % · morfotipos 20,6 % · dinámica 14,7 % · clínicas 10,1 % · ARI 3,3 %."));
add(NUM("Remate: el modelo no inventa la fisiología, descubre la trayectoria que ya estaba escrita en la noche."));

add(SL(20,"De dos modelos a dos scores","1:40"));
add(ROT("Qué decir"));
add(SAY("Cada modelo produce un score. El de evento acumula las predicciones a lo largo de la noche: cuantas más predicciones altas, más alto queda. El de noche mide cuánto tiempo pasó la noche en estados patológicos."));
add(SAY("Los valores que se ven acá son ilustrativos, no corresponden a una noche real del corpus."));
add(ROT("Cifras y apoyos"));
add(NUM("Decilo explícitamente: el score de evento es una señal de alerta, no un diagnóstico."));

add(SL(21,"Risk Score PAC","2:20"));
add(ROT("Qué decir"));
add(SAY("Los dos scores se combinan en un índice de cero a cien: cuarenta por ciento el de evento, sesenta el de noche. Es una ponderación heurística, elegida para que el resultado sea interpretable, no para maximizar una métrica."));
add(SAY("Las medianas por categoría clínica separan bien: veintiocho en normales, veintinueve en leves, setenta y tres en moderadas, ochenta y uno en severas. Con corte en sesenta se capturan todas las noches severas y tres de cada cuatro moderadas."));
add(SAY("Pero el valor clínico no está en el acuerdo: está en la discordancia. Un paciente con ODI3 moderado y Risk Score alto es una noche con riesgo oculto que el índice clásico no marca."));
add(ROT("Cifras y apoyos"));
add(NUM("Medianas: 28,2 · 29,3 · 73,1 · 81,3. Umbral 60: 100 % de severas y 77,6 % de moderadas."));
add(NUM("Bandas: bajo por debajo de 30, intermedio entre 30 y 60, alto por encima de 60."));
add(NUM("⚠ Decilo antes de que te lo pregunten, y con estas palabras: no es una probabilidad calibrada, es un número que resume lo retrospectivo de una noche."));

add(SL(22,"Separador · Nivel Noche","1:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Cerrá el bloque y hacé una pausa. Dos noches con el mismo ODI3 pueden ser fisiológicamente opuestas."));

// ── BLOQUE 6 ──
add(H1("Bloque 6 · App clínica"),P("Dos minutos. No es el foco evaluativo: es evidencia de que el pipeline es utilizable.",{i:true,c:GR}));
add(SL(23,"PAC App","2:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Se sube el Excel crudo del oxímetro y sale el Risk Score con todo el análisis detrás."));
add(BUL("Usa los mismos módulos que el pipeline de investigación: no hay divergencia entre el cuaderno y la aplicación."));
add(BUL("Decí en voz alta que es un prototipo de investigación, no un dispositivo médico autorizado."));
add(NUM("Si el tiempo apremia, este es el primer bloque a recortar."));

// ── BLOQUE 7 ──
add(H1("Bloque 7 · Predicción prospectiva"),P("Siete minutos. Es el bloque mejor calificado en las revisiones internas: mostralo con confianza.",{i:true,c:GR}));

add(SL(24,"Gancho","0:40"));
add(ROT("Puntos de apoyo"));
add(BUL("Leé la pregunta y hacé silencio. No la contestes acá."));
add(BUL("Cuidá el condicional: “si pudiéramos”. Lo terapéutico es una hipótesis, no un resultado."));

add(SL(25,"Cómo está construido el modelo","2:00"));
add(ROT("Qué decir"));
add(SAY("Cambia la pregunta: ya no es qué tan severo es este evento, sino si va a haber uno severo en los próximos H minutos, cuando todavía no hay ningún evento a la vista."));
add(SAY("La noche se corta en ventanas de treinta segundos sin solapamiento: cuatrocientas cincuenta y dos mil novecientas cincuenta y cinco en total. Los horizontes se fijaron antes de mirar los datos: dos, cinco, diez y quince minutos. Y todas las variables miran hacia atrás; ninguna usa información posterior al cierre de la ventana."));
add(SAY("Dejo dichas las limitaciones antes de mostrar el resultado: la salida es un ranking de riesgo y no una probabilidad calibrada, la prevalencia varía veinte veces entre pacientes, los estados se entrenaron sobre esta misma cohorte, y no hay validación externa."));
add(ROT("Cifras y apoyos"));
add(NUM("452.955 ventanas · 8 pacientes · 540 noches · H ∈ {2, 5, 10, 15} min · LightGBM de 300 árboles."));
add(NUM("Remate: el modelo no ve el evento; la noche tiene memoria."));

add(SL(26,"Resultado","3:00"));
add(ROT("Qué decir"));
add(SAY("A cinco minutos vista, el área bajo la curva es de 0,821. La discriminación baja suavemente al alejar el horizonte, de 0,838 a dos minutos hasta 0,763 a quince, y esa pendiente moderada es en sí misma el resultado: la información fisiológica no se apaga de golpe."));
add(SAY("Ahora, ¿por qué cinco y no dos, si a dos discrimina mejor? Porque el valor predictivo positivo a dos minutos es del diez por ciento: nueve de cada diez alarmas serían falsas. A cinco minutos duplica, y además supera con holgura los noventa segundos que el estimulador necesita para llegar a su efecto."));
add(SAY("El costo operacional es concreto y prefiero decirlo yo: unas veinte alarmas por noche, de las cuales unas cuatro corresponderían a eventos reales. Ese es el límite de precisión que el diseño del dispositivo y la tolerancia del paciente tendrían que absorber."));
add(SAY("Esa relación de una alarma útil cada cinco es gruesa, y depende de dos cosas que hoy no están resueltas: la prevalencia de cada paciente, que varía veinte veces entre el más y el menos afectado, y el umbral, que acá es único para toda la cohorte. Con calibración individual y una cohorte más amplia y variada, ese cociente debería mejorar."));
add(ROT("Cifras y apoyos"));
add(NUM("AUC: 0,838 · 0,821 · 0,783 · 0,763. PPV: 9,6 % · 20,3 % · 29,8 % · 35,4 %."));
add(NUM("A H = 5 min: sensibilidad 76 %, especificidad 74 %, PPV 20 %."));
add(NUM("Remate: anticipar es factible; que la estimulación evite el evento, todavía no está demostrado."));

add(SL(27,"Separador · Nivel Prospectivo","1:20"));
add(ROT("Puntos de apoyo"));
add(BUL("Anticipar no requirió una señal nueva: la historia que la noche venía acumulando fue suficiente."));
add(BUL("Es el momento de cerrar el arco: todo lo que mostraste antes es lo que hace posible esto."));

// ── BLOQUE 8 ──
add(H1("Bloque 8 · Cierre"),P("Cinco minutos. Define la impresión final: sostené el tono condicional hasta el último renglón.",{i:true,c:GR}));

add(SL(28,"Tres preguntas que los índices clásicos no responden","1:30"));
add(ROT("Qué decir"));
add(SAY("Si tuviera que resumir el aporte en tres preguntas, serían estas. ¿Todos los eventos pesan lo mismo? No: el seis por ciento más severo concentra casi un cuarto de la carga. ¿Alcanza con contarlos? No: los índices retienen la frecuencia y pierden el orden. ¿Cuándo va a ocurrir el próximo? El índice no lo dice; el modelo estima el riesgo a cinco minutos."));
add(SAY("Y quiero ser claro en esto: no vengo a reemplazar al ODI3 ni al AHI. Son convenciones validadas y siguen siendo el estándar. Lo que muestro es dónde pierden estructura y qué se puede recuperar ahí."));

add(SL(29,"Limitaciones","1:10"));
add(ROT("Puntos de apoyo"));
add(BUL("Decilas vos, sin apuro y sin justificarlas. El jurado las va a valorar más que cualquier resultado."));
add(BUL("De evidencia: n = 12 y 8 en cohorte estricta, sesgo de selección y predominio masculino, ausencia de polisomnografía simultánea, y circularidad de los clusters."));
add(BUL("Traslacionales: probabilidades sin calibrar, umbrales operativos y no clínicos, heterogeneidad de veinte veces entre pacientes, y efecto terapéutico no demostrado."));
add(NUM("La circularidad es la que más peso tiene técnicamente: reconocela sin rodeos y pasá a cómo se resuelve."));

add(SL(30,"Agenda de trabajo futuro","1:00"));
add(ROT("Puntos de apoyo"));
add(BUL("Cada punto responde a una limitación de la diapositiva anterior. Decilo así, es la mejor manera de presentarla."));
add(BUL("Cohorte externa con polisomnografía · reagrupamiento dentro de cada partición · calibración · umbral individual con rodaje · ensayo controlado."));
add(NUM("Ensayo: 30 a 50 pacientes, rodaje de 7 a 14 noches, estímulo activo contra placebo."));

add(SL(31,"Conclusiones","1:00"));
add(ROT("Qué decir"));
add(SAY("Cuatro cosas. Un único sensor domiciliario permite reconstruir la fisiología de la noche, no solo contar sus eventos. Ni los eventos son equivalentes ni la noche es homogénea. Esa estructura anticipa: lo que la noche acumuló permite estimar el riesgo con minutos de margen. Y el Proyecto PAC es un trabajo de generación de hipótesis: define qué se debería probar y con qué diseño."));
add(ROT("Cifras y apoyos"));
add(NUM("Cerrá con la frase de la diapositiva y hacé silencio antes de pasar. Es la última línea de la tesis."));

add(SL(32,"Gracias","0:20"));
add(ROT("Puntos de apoyo"));
add(BUL("Agradecé y abrí el turno de preguntas mirando al jurado, no a la pantalla."));

// ── PREGUNTAS ──
add(new Paragraph({children:[new TextRun("")],pageBreakBefore:true}));
add(H1("Preguntas anticipadas del jurado"));
add(P("Responder en treinta a cuarenta y cinco segundos, con una cifra concreta y, cuando corresponda, reconociendo la limitación de frente. La honestidad metodológica puntúa más que la defensa a ultranza.",{i:true,c:GR}));

add(H2("I · Diseño y validación"));
add(QA("¿Por qué el n efectivo es 8 pacientes y no 12?",
"Los modelos supervisados requieren cohorte estricta: pacientes con completitud suficiente para que el LOPO-CV sea estable. Los análisis descriptivos de los capítulos 4 y 5 sí usan los 12 pacientes y las 560 noches; la restricción a 8 aplica sólo donde se entrena y valida un modelo."));
add(QA("¿Por qué el umbral de detección es 2 pp si el ODI3 clínico usa 3 pp?",
"El 3 % es una convención diagnóstica, no una frontera fisiológica. El objetivo no es diagnosticar sino caracterizar morfológicamente: una caída de 2,5 pp tiene forma y respuesta autonómica igual de informativas que una de 3,2. El umbral permisivo maximiza el corpus sin perder compatibilidad, porque el ODI3 se calcula como subconjunto."));
add(QA("Los clusters se entrenaron sobre la misma cohorte que después se usa para modelar. ¿No hay circularidad?",
"Sí, y está reconocida explícitamente en el capítulo 8 y en la agenda del 10. El agrupamiento no se re-entrena dentro de cada partición, lo que podría introducir un sesgo optimista. La solución es reagrupar within-fold o validar sobre cohorte externa. No está resuelta en esta tesis, y lo digo con esa claridad."));
add(QA("¿Por qué K = 5 si el Silhouette no es máximo ahí?",
"El Silhouette decrece de forma monótona desde K = 2. K = 5 es el último valor antes de la caída abrupta en K = 6, y es el primero que separa dos morfotipos severos clínicamente distintos, C4 y C5, que un K menor colapsa. Combina un criterio estadístico con uno de interpretabilidad."));
add(QA("¿Cómo se decidió el número de estados por escala?",
"Cada escala se calibró de forma independiente porque representa una resolución temporal distinta con dinámicas propias. El criterio combinó codo y Silhouette con interpretabilidad fisiológica en cada una."));

add(H2("II · Índices y modelos"));
add(QA("¿Por qué los pesos 0,6 y 0,4 del ARI?",
"Reflejan la mayor confiabilidad de la señal cardíaca frente al sensor de movimiento. Es una decisión de diseño, no derivada analíticamente. El análisis de sensibilidad muestra que el gradiente inverso del C5 se sostiene en todo el rango donde la señal cardíaca pesa más, y que el ICC entre noches se maximiza justamente en 0,6. La ortogonalidad, en cambio, sí depende de la ponderación, y eso está declarado en el capítulo 4."));
add(QA("El Risk Score combina 40 y 60 de forma heurística. ¿Por qué no aprender los pesos?",
"Porque el objetivo es que sea interpretable, no que maximice una métrica. Es explícitamente una función de ranking sobre probabilidades no calibradas, y los cortes en 30 y 60 salen de la distribución empírica de las 494 noches, no de una optimización."));
add(QA("El modelo prospectivo sobreestima unas cuatro veces la probabilidad. ¿Cómo afecta eso a la propuesta del estimulador?",
"Se entrenó con pesos de clase uniformes, lo que produce una sobreestimación sistemática. El umbral de Youden absorbe ese corrimiento a los fines del ranking, pero el número no debe leerse como probabilidad clínica. Para uso real haría falta calibración por Platt scaling o regresión isotónica, y está identificado como paso pendiente."));
add(QA("¿Por qué LightGBM y no una red neuronal?",
"Buen desempeño sobre variables tabulares con un número de pacientes chico para entrenar arquitecturas profundas, y permite interpretabilidad directa vía SHAP, que es central para un trabajo que busca explicar y no sólo predecir. Para horizontes cortos, donde la forma de la señal previa importa más, el trabajo futuro propone explorar modelos secuenciales."));

add(H2("III · Validez externa"));
add(QA("¿Esto generaliza a otras cohortes o sólo a estos 12 pacientes?",
"Todavía no puede afirmarse, y es la limitación más importante. La arquitectura del pipeline es transferible, pero los parámetros específicos — los K de cada agrupamiento, los pesos del ARI, los umbrales del Risk Score — se ajustaron sobre esta cohorte y requieren validación externa con polisomnografía simultánea. Es la primera línea de la agenda."));
add(QA("¿Por qué no compararon contra el AHI, que es el estándar?",
"Porque la cohorte no tiene polisomnografía simultánea: es monitoreo domiciliario exclusivamente. Se usa el ODI3 como referencia clínica accesible, y el trabajo se posiciona como complementario a la polisomnografía, no como su reemplazo."));

add(H2("IV · Clínica y ética"));
add(QA("¿Es aceptable activar un estimulador con un ranking no calibrado?",
"Esta tesis no propone el despliegue clínico. Establece la condición algorítmica mínima: que la información predictiva existe, es consistente entre pacientes y llega con horizonte suficiente para superar los noventa segundos de rodaje del estímulo. La eficacia y la seguridad requieren un ensayo controlado, que está descrito como próximo paso."));
add(QA("¿Qué resguardos éticos tuvo el estudio?",
"El protocolo siguió estándares ICH GCP y regulaciones FDA y ANMAT, con consentimiento informado y anonimización. El dispositivo está aprobado por ANMAT."));

add(H2("V · Contribución"));
add(QA("¿Cuál es el aporte original frente a lo publicado?",
"Tres cosas que no aparecen descriptas conjuntamente en la literatura revisada. El ARI como dimensión de reactividad autonómica ortogonal a la severidad, sin equivalente publicado. La especialización funcional emergente de los estados, que escalas distintas predicen dimensiones distintas de severidad. Y la variabilidad intraindividual tratada como señal y no como ruido."));
add(QA("¿Qué aporta a la ciencia de datos, más allá del caso clínico?",
"La contribución es representacional: proponer un nivel intermedio entre el índice escalar y la señal cruda, donde conviven interpretabilidad y capacidad predictiva. La arquitectura Medallion con control de calidad no destructivo, la validación por paciente y el uso de SHAP son transferibles a cualquier dominio de señales fisiológicas continuas."));

add(H2("VI · Próximos pasos"));
add(QA("¿Qué hace falta para llegar a una aplicación terapéutica real?",
"Un ensayo controlado: 30 a 50 pacientes con SAOS moderado a severo confirmado por polisomnografía, rodaje de 7 a 14 noches sin estimulación para calibrar el umbral individual, y asignación aleatoria a estímulo activo o placebo durante 4 a 8 semanas, con ODI3, T90 y carga hipóxica como desenlaces."));

// ── CHECKLIST ──
add(H1("Checklist antes de la defensa"));
["Ensayar completo con cronómetro al menos tres veces; grabarse una y revisar mirada, muletillas y tiempos.",
 "No leer las diapositivas. El texto proyectado es apoyo, no libreto.",
 "Pasear la mirada por todo el jurado desde la primera diapositiva.",
 "Manos visibles; evitar bolsillos y apoyarse en la mesa.",
 "Tener a mano las tablas de respuesta a objetivos y de publicaciones, por si las piden con precisión.",
 "Repasar en voz alta las respuestas de la sección anterior: no memorizarlas, sino tener clara la estructura de cada una — cifra, matiz, límite.",
 "Revisar el entorno de proyección antes de empezar: contraste, tamaño, y que la fuente Aptos esté en la máquina.",
 "Confirmar con el director si el jurado pregunta al final o puede interrumpir."].forEach(t=>add(BUL(t)));

return c;
};
