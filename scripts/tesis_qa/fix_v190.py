# -*- coding: utf-8 -*-
"""v189 -> v190
   1. Figura 8.4: reemplaza media/image18.png (eje Y 0-1 + basal de prevalencia),
      elimina el recorte srcRect (el suptitle ya no existe) y conserva la caja.
   2. Cuatro alt-text (descr/name) que quedaron en la numeracion vieja.
   Idempotente. Uso: fix_v190.py <origen> <destino> <png>"""
import sys, shutil, zipfile
from docx import Document
from docx.oxml.ns import qn

SRC, DST, PNG = sys.argv[1], sys.argv[2], sys.argv[3]
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
WPD = '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}'
PIC = '{http://schemas.openxmlformats.org/drawingml/2006/picture}'

sys.path.insert(0, '/sessions/dreamy-focused-thompson/mnt/PAC_v2/scripts/tesis_qa')
from lib_docx import para_replace

doc = Document(SRC); P = doc.paragraphs
n = {'srcRect': 0, 'descr': 0, 'nota': 0}

# --- 1. quitar el recorte de la Figura 8.4 (p611) -------------------------
for sr in P[611]._p.findall('.//' + A + 'srcRect'):
    sr.getparent().remove(sr); n['srcRect'] += 1

# --- 2. alt-text: descr = epigrafe completo; name = figura correcta -------
ALT = {496: ('Fig611', 495), 600: ('Fig82', 599), 604: ('Fig83', 603), 611: ('Fig84', 610)}
for pi, (name, cap_i) in ALT.items():
    cap = P[cap_i].text.strip()
    for tag in (WPD + 'docPr', PIC + 'cNvPr'):
        for el in P[pi]._p.findall('.//' + tag):
            if el.get('descr') != cap or el.get('name') != name:
                el.set('name', name)
                if tag.endswith('docPr'):
                    el.set('descr', cap)
                n['descr'] += 1

# --- 3. Nota de la Figura 8.4: declara las dos basales --------------------
OLD = ('Panel izquierdo: AUC-ROC y AP por horizonte. H = 2 min presenta el AUC más '
       'alto (0,838); H = 5 min es el horizonte operacional óptimo por balance entre '
       'AUC y PPV (Tabla 8.5).')
NEW = ('Panel izquierdo: AUC y AP por horizonte, cada uno con su basal (0,50 y la '
       'prevalencia); los múltiplos son la mejora del AP (Tabla 8.4). H = 5 min es el '
       'horizonte operacional óptimo (Tabla 8.5).')
if OLD in P[612].text:
    n['nota'] += para_replace(P[612], OLD, NEW)

doc.save('/tmp/_tmp190.docx')

# --- 4. reemplazo del binario de la imagen --------------------------------
blob = open(PNG, 'rb').read()
zin = zipfile.ZipFile('/tmp/_tmp190.docx')
with zipfile.ZipFile(DST, 'w', zipfile.ZIP_DEFLATED) as zout:
    for it in zin.infolist():
        data = blob if it.filename == 'word/media/image18.png' else zin.read(it.filename)
        zout.writestr(it, data)
zin.close()
print('srcRect eliminados :', n['srcRect'])
print('alt-text corregidos:', n['descr'])
print('nota actualizada   :', n['nota'])
