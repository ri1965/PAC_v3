# -*- coding: utf-8 -*-
"""v4 -> v5 (mazo conceptual, bloque Cap. 08)
   1 · card: espacios duros + bullet de costo operativo
   6 · figura con eje derecho de PPV en %
   7 · diapo nueva de formulacion, antes de la de resultado
   8 · diapo de respaldo con las curvas ROC, al final
   9 · texto suelto dentro del rectangulo de fondo (diapos 15, 16, 19)"""
import copy, sys
from pptx import Presentation
from pptx.util import Emu, Pt, Cm
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

SRC='tesis_cap/Tesis_PAC_presentacion_conceptual_Mac_editable_v4.pptx'
DST='/tmp/Tesis_PAC_presentacion_conceptual_Mac_editable_v5.pptx'
FIG='/sessions/dreamy-focused-thompson/mnt/outputs/slide_fig_V1_auc_vs_ppv.png'
ROC='/sessions/dreamy-focused-thompson/mnt/outputs/roc_respaldo.png'
NB=chr(0x00A0)   # espacio duro

NAVY=RGBColor(0x0F,0x2E,0x4E); BLUE=RGBColor(0x00,0x70,0xC0); INK=RGBColor(0x1E,0x25,0x2D)
WHITE=RGBColor(0xFF,0xFF,0xFF); CARDBG=RGBColor(0xF5,0xF8,0xFA); CARDLN=RGBColor(0xDF,0xE7,0xED)
ROW1=RGBColor(0xFA,0xFC,0xFD); ROW2=RGBColor(0xEE,0xF4,0xF8); BORDE=RGBColor(0x00,0x20,0x60)
F='Aptos'

p=Presentation(SRC)
IDX_RES=24                                  # diapo 25 = resultado prospectivo
res=p.slides[IDX_RES]
log={}

# ── 1 · card ────────────────────────────────────────────────────────────
BULLETS=[f'H = 5{NB}min supera el ramp-up del estimulador (>{NB}90{NB}s).',
         f'Sensibilidad 76{NB}%, especificidad 74{NB}%, PPV 20{NB}%.',
         f'~20 alarmas por noche; ~4 corresponden a eventos reales.',
         f'Predice riesgo relativo, no probabilidad clínica calibrada.']
tb=[sh for sh in res.shapes if sh.name=='TextBox 7'][0]
paras=list(tb.text_frame.paragraphs)
for para,nuevo in zip(paras[1:], BULLETS):
    runs=list(para.runs)
    runs[0].text='• '+nuevo
    for r in runs[1:]: r.text=''
log['card']=len(BULLETS)

# ── 6 · figura ──────────────────────────────────────────────────────────
old=[sh for sh in res.shapes if sh.shape_type==13][0]
L,T,W,H=old.left,old.top,old.width,old.height
old._element.getparent().remove(old._element)
res.shapes.add_picture(FIG,L,T,W,H)
log['figura']=1

# ── 9 · texto suelto en el rectangulo de fondo ──────────────────────────
n=0
for sl in p.slides:
    for sh in sl.shapes:
        if sh.name.startswith('Rectangle 1') and sh.has_text_frame and sh.text_frame.text.strip():
            for para in list(sh.text_frame.paragraphs):
                for r in list(para.runs): r.text=''
            n+=1
log['texto_suelto']=n

# ── plantilla para las diapos nuevas ────────────────────────────────────
LAYOUT=res.slide_layout
PLANTILLA=[sh for sh in res.shapes if sh.name in ('Rectangle 1','Rectangle 2','TextBox 3','TextBox 4')]

def nueva(titulo):
    s=p.slides.add_slide(LAYOUT)
    for sh in PLANTILLA:
        s.shapes._spTree.append(copy.deepcopy(sh._element))
    t=[sh for sh in s.shapes if sh.name=='TextBox 4'][0]
    pr=list(t.text_frame.paragraphs)[0]; runs=list(pr.runs)
    runs[0].text=titulo
    for r in runs[1:]: r.text=''
    return s

def card(s,l,t,w,h,titulo,bullets,sz=13.2):
    c=s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,Cm(l),Cm(t),Cm(w),Cm(h))
    c.fill.solid(); c.fill.fore_color.rgb=CARDBG
    c.line.color.rgb=CARDLN; c.line.width=Pt(1); c.shadow.inherit=False
    tx=s.shapes.add_textbox(Cm(l+0.64),Cm(t+0.32),Cm(w-1.27),Cm(h-0.7))
    tf=tx.text_frame; tf.word_wrap=True
    pr=tf.paragraphs[0]; r=pr.add_run(); r.text=titulo
    r.font.size=Pt(15); r.font.bold=True; r.font.name=F; r.font.color.rgb=BLUE
    for b in bullets:
        pr=tf.add_paragraph(); pr.space_before=Pt(9)
        r=pr.add_run(); r.text='• '+b
        r.font.size=Pt(sz); r.font.name=F; r.font.color.rgb=INK

def banner(s,texto):
    b=s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,Cm(3.17),Cm(13.84),Cm(27.43),Cm(1.65))
    b.fill.background(); b.line.color.rgb=BORDE; b.line.width=Pt(1.25); b.shadow.inherit=False
    tx=s.shapes.add_textbox(Cm(3.73),Cm(13.90),Cm(26.31),Cm(1.53))
    tf=tx.text_frame; tf.word_wrap=True
    tf.vertical_anchor=MSO_ANCHOR.MIDDLE
    pr=tf.paragraphs[0]; pr.alignment=PP_ALIGN.CENTER
    r=pr.add_run(); r.text=texto
    r.font.size=Pt(18); r.font.bold=True; r.font.name=F; r.font.color.rgb=BLUE

# ── 7 · formulacion ─────────────────────────────────────────────────────
s=nueva('Clasificar lo que ocurre no es lo mismo que anticiparlo')
filas=[('Aspecto','Cap. 6 — clasificación condicional','Cap. 8 — predicción prospectiva'),
       ('Pregunta','¿Es severo este evento en curso?',f'¿Habrá un EDO severo en los próximos H{NB}min?'),
       ('Condición','El evento ya ocurrió y es observable','No hay señal de evento en curso'),
       ('Unidad de análisis','76.053 eventos',f'452.955 ventanas de 30{NB}s'),
       ('AUC (LOPO-CV)','0,882 evento · 0,905 noche',f'0,821 (H = 5{NB}min)'),
       ('Acción que habilita','Clasificar la severidad','Activar el estimulador')]
gf=s.shapes.add_table(len(filas),3,Cm(1.91),Cm(3.05),Cm(16.64),Cm(8.51))
t=gf.table; t.first_row=True; t.horz_banding=True
for w,c in zip((3.70,6.47,6.47),t.columns): c.width=Cm(w)
for ri,fila in enumerate(filas):
    t.rows[ri].height=Cm(8.51/len(filas))
    for ci,val in enumerate(fila):
        cel=t.cell(ri,ci); cel.margin_left=Emu(54864); cel.margin_right=Emu(54864)
        cel.vertical_anchor=MSO_ANCHOR.MIDDLE
        cel.fill.solid(); cel.fill.fore_color.rgb=NAVY if ri==0 else (ROW1 if ri%2 else ROW2)
        pr=cel.text_frame.paragraphs[0]; r=pr.add_run(); r.text=val
        r.font.size=Pt(10.8); r.font.name=F; r.font.bold=(ri==0)
        r.font.color.rgb=WHITE if ri==0 else INK
card(s,19.68,3.05,11.81,8.51,'Diseño del análisis',
     ['Cohorte estricta: 8 pacientes, 540 noches.',
      f'Ventanas de 30{NB}s contiguas, sin solapamiento.',
      f'Horizontes H ∈ {{2, 5, 10, 15}}{NB}min, fijados de antemano.',
      'Variables sólo hacia atrás, sin información posterior al cierre.',
      'LOPO-CV: el paciente entero fuera del entrenamiento.'],sz=12.5)
banner(s,'Los 8 puntos de AUC son el costo de predecir sin el evento delante.')
FORM=s

# ── 8 · respaldo ROC ────────────────────────────────────────────────────
s=nueva('Respaldo: curvas ROC por horizonte')
s.shapes.add_picture(ROC,Cm(11.60),Cm(2.90),Cm(14.90),Cm(13.90))
card(s,1.40,2.90,8.20,13.90,'Para preguntas',
     ['Las cuatro curvas quedan claramente por encima de la diagonal.',
      'El orden entre horizontes se conserva en todo el rango.',
      'La separación se diluye de forma gradual, no abrupta.',
      f'Agrupado sobre los 8 pacientes (LOPO-CV), 452.955 ventanas.'])
RESP=s

# ── reordenar: formulacion antes del resultado; respaldo al final ───────
lst=p.slides._sldIdLst
def id_of(slide):
    for e in list(lst):
        if p.slides.get(int(e.get('id')))==slide: return e
    return None
e_form=id_of(FORM); e_resp=id_of(RESP)
lst.remove(e_form); lst.remove(e_resp)
lst.insert(IDX_RES, e_form)      # queda como diapo 25, el resultado pasa a 26
lst.append(e_resp)
p.save(DST)

q=Presentation(DST)
print('slides:',len(q.slides),'| cambios:',log)
for i,s in enumerate(q.slides,1):
    if i>=24:
        ts=[sh.text_frame.text.split('\n')[0] for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip() and 'Proyecto PAC · Tesis' not in sh.text_frame.text]
        print(f'  {i:2d} {ts[0][:62] if ts else "(sin texto)"}')
