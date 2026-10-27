"""Render the progress report and six vector figures. Requires reportlab, markdown-it-py, pypdf, pypdfium2.

Run from the checkout: python scripts/render_progress_report.py [--deps PATH]
--deps can point to an isolated ReportLab installation without changing the runtime lock.
"""
from pathlib import Path
from copy import deepcopy
from html import escape
import argparse
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--deps', type=Path)
args = parser.parse_args()
if args.deps:
    sys.path.append(str(args.deps.resolve()))

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, LongTable, TableStyle, Flowable
from reportlab.graphics.shapes import Drawing, Rect, Line, Polygon, String
from reportlab.graphics import renderSVG, renderPDF
from markdown_it import MarkdownIt
from pypdf import PdfReader
import pypdfium2 as pdfium

SOURCE = ROOT/'docs/reports/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.md'
OUTPUT = ROOT/'output/pdf/KNOWLEDGE_GRAPH_BUILDER_PROGRESS_2026-10-27.pdf'
ASSETS = SOURCE.parent/'figures'
QA = ROOT/'tmp/report-qa'
ASSETS.mkdir(parents=True, exist_ok=True)
QA.mkdir(parents=True, exist_ok=True)
for name, filename in [('Arial','arial.ttf'),('Arial-Bold','arialbd.ttf'),('Arial-Italic','ariali.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts')/filename)))
pdfmetrics.registerFontFamily('Arial', normal='Arial', bold='Arial-Bold', italic='Arial-Italic', boldItalic='Arial-Bold')

BLUE='#27445c'; GREEN='#28776a'; AMBER='#ad7132'; INK='#243746'; GRAY='#dfe5e9'; PALE='#f2f5f7'
W=509
def color(value): return colors.HexColor(value)
def label(d,x,y,text,size=9,bold=False,fill=INK,anchor='start'):
    d.add(String(x,y,text,fontName='Arial-Bold' if bold else 'Arial',fontSize=size,fillColor=color(fill),textAnchor=anchor))
def node(d,x,y,w,h,lines,fill=PALE,stroke=BLUE,dashed=False):
    d.add(Rect(x,y,w,h,rx=4,ry=4,fillColor=color(fill),strokeColor=color(stroke),strokeWidth=.8,
               strokeDashArray=[4,3] if dashed else None))
    for i,text in enumerate(lines):
        label(d,x+w/2,y+h/2+(len(lines)-1)*6-i*12-3,text,9,i==0,anchor='middle')
def arrow(d,x1,y1,x2,y2,fill=BLUE,dashed=False):
    from math import atan2,cos,sin,pi
    d.add(Line(x1,y1,x2,y2,strokeColor=color(fill),strokeWidth=1,strokeDashArray=[3,3] if dashed else None))
    a=atan2(y2-y1,x2-x1); size=5
    d.add(Polygon([x2,y2,x2-size*cos(a-pi/6),y2-size*sin(a-pi/6),x2-size*cos(a+pi/6),y2-size*sin(a+pi/6)],
                  fillColor=color(fill),strokeColor=color(fill)))
def bar(d,x,y,w,h,fraction,fill=BLUE):
    d.add(Rect(x,y,w,h,fillColor=color(GRAY),strokeColor=None))
    d.add(Rect(x,y,w*fraction,h,fillColor=color(fill),strokeColor=None))

figures={}
d=Drawing(W,176)
node(d,0,115,103,38,['Reports / scans','GDR, AK-3'])
node(d,132,115,159,38,['Corpus pipeline','chunks / tables / quality'])
node(d,322,115,187,38,['AK-3 prototype','ontology file → extract → review → QA'])
arrow(d,103,134,132,134);arrow(d,291,134,322,134,AMBER,True)
label(d,323,159,'Integration pending',8,fill=AMBER)
node(d,0,60,103,38,['BSEE files','3 regions'])
node(d,132,60,159,38,['Mapping-driven import','typed records + row evidence'])
node(d,322,60,187,38,['Linked graph + entity registry','57,453 wellbores / 39,518 wells'])
arrow(d,103,79,132,79);arrow(d,291,79,322,79)
node(d,0,3,509,38,['DONE: validated releases + shared evidence / claim / entity contracts','PLANNED: admin console (ontology, review, curation); prototype on corpus releases; access control later'],fill='#fff8ee',stroke=AMBER,dashed=True)
label(d,0,166,'IMPLEMENTED',8,True,fill=GREEN)
figures['01-current-paths']=d

d=Drawing(W,197)
node(d,0,155,112,35,['Admin console','ontology / review / curation'])
node(d,183,155,190,35,['FastAPI','workflows / profiles / bounded queries'])
arrow(d,112,172,183,172)
node(d,390,155,119,35,['Ontology file (user)','oil_wells = test profile'],fill='#eaf4f0',stroke=GREEN)
arrow(d,390,172,373,172,GREEN)
node(d,0,78,151,43,['PostgreSQL','entities / revisions / reviews'])
node(d,179,78,151,43,['Artifact store','originals / versioned evidence'])
node(d,358,78,151,43,['Neo4j','completed graph projection'])
arrow(d,254,155,254,121)
d.add(Line(75,137,434,137,strokeColor=color(BLUE),strokeWidth=1))
d.add(Line(254,155,254,137,strokeColor=color(BLUE),strokeWidth=1))
arrow(d,75,137,75,121);arrow(d,434,137,434,121)
node(d,0,7,151,39,['Worker','profile-driven processing'])
node(d,179,7,151,39,['Local model','llama.cpp / schema output'])
arrow(d,151,27,179,27);arrow(d,75,46,75,78)
d.add(Line(75,59,434,59,strokeColor=color(BLUE),strokeWidth=1))
arrow(d,254,59,254,78);arrow(d,434,59,434,78)
label(d,347,10,'All inside approved boundary',8,fill=AMBER)
label(d,347,23,'TARGET — integration plan',8,True,fill=AMBER)
figures['02-target-architecture']=d

d=Drawing(W,180)
label(d,0,164,'EXTRACTION / REVIEW',9,True)
label(d,0,138,'Gold facts recovered',9)
bar(d,167,131,270,13,30/41,GREEN);label(d,447,133,'30 / 41',9,True)
label(d,167,117,'Recall 0.73; 11 gold facts missed (E4: 28 / 41)',8,fill=AMBER)
label(d,0,94,'Correct validated claims',9)
bar(d,167,87,270,13,30/31,GREEN);label(d,447,89,'30 / 31',9,True)
label(d,167,73,'Precision 0.97; oracle rejects 1 wrong candidate',8)
label(d,0,51,'QUESTION ANSWERING',9,True)
label(d,0,29,'End-to-end correct',9)
bar(d,167,23,270,11,23/31);label(d,447,24,'23 / 31',9,True)
label(d,0,9,'QA-layer correct',9)
bar(d,167,2,270,11,1);label(d,447,3,'31 / 31',9,True)
figures['03-ak3-results']=d

d=Drawing(W,217)
label(d,0,203,'Engine / language',9,True)
label(d,117,203,'CER ↓  (0–0.25)',8.5,True)
label(d,280,203,'WER',8.5,True)
label(d,330,203,'Word recall ↑ (0–1)',8.5,True)
label(d,480,203,'s/page',8.5,True)
ocr=[('EasyOCR / VI',.240,.294,.859,41),('RapidOCR / VI',.141,.562,.440,28),('VietOCR / VI',.052,.082,.945,48),
     ('RapidOCR / EN',.021,.044,.998,13),('VietOCR / EN',.028,.059,.985,26)]
for i,(name,cer,wer,recall,sec) in enumerate(ocr):
    y=171-i*34
    label(d,0,y,name,9,bold=name.startswith('VietOCR'))
    bar(d,117,y-3,109,11,cer/.25,AMBER);label(d,235,y,f'{cer:.3f}',8.5)
    label(d,280,y,f'{wer:.3f}',8.5)
    bar(d,330,y-3,96,11,recall,GREEN);label(d,435,y,f'{recall:.3f}',8.5)
    label(d,488,y,str(sec),8.5)
label(d,0,9,'VI: 8 pages   |   EN: 3 pages   |   scan200 only   |   E5 synthetic scans',8,fill=INK)
figures['04-ocr-comparison']=d

d=Drawing(W,144)
label(d,0,128,'WebNLG-10 — strict F1',10,True)
label(d,272,128,'2Wiki-10 — QA token F1',10,True)
for x,rows in [(0,[('Baseline',.736),('+ canonicalization',.843)]),(272,[('Text retrieval QA',.736),('Graph QA A4',.676)])]:
    for i,(name,value) in enumerate(rows):
        y=99-i*46
        label(d,x,y,name,9)
        bar(d,x,y-19,182,12,value,GREEN if x==0 else BLUE)
        label(d,x+191,y-17,f'{value:.3f}',9,True)
    label(d,x,7,'0                          score (0–1)                       1',8)
d.add(Line(252,6,252,139,strokeColor=color(GRAY),strokeWidth=1))
figures['05-research-comparisons']=d

d=Drawing(W,101)
steps=[['1  Ontology file','loader / validation'],['2  Extraction','references / evidence'],['3  Identity + review','duplicates / HITL'],['4  Publish + QA','exact graph / citations']]
for i,lines in enumerate(steps):
    x=i*131
    node(d,x,45,116,49,lines,fill=PALE)
    if i<3:arrow(d,x+116,69,x+131,69)
label(d,0,24,'NEXT MILESTONE — builder slice: ontology file → reviewed graph → cited answer',9,True)
label(d,0,7,'Ontology loader done in the prototype (E10)  •  interruption-safe replacement  •  source withdrawal',9)
figures['06-next-milestone']=d

for name,drawing in figures.items():
    renderSVG.drawToFile(drawing,str(ASSETS/f'{name}.svg'))
    svg=ASSETS/f'{name}.svg'; svg.write_bytes(svg.read_bytes().replace(b'\r\n',b'\n'))  # repository text is LF
    renderPDF.drawToFile(drawing,str(QA/f'{name}.pdf'))
    with pdfium.PdfDocument(QA/f'{name}.pdf') as pdf:
        pdf[0].render(scale=2).to_pil().save(QA/f'{name}.png')

body=ParagraphStyle('body',fontName='Arial',fontSize=10,leading=14.1,spaceAfter=6,allowWidows=0,allowOrphans=0)
title=ParagraphStyle('title',parent=body,fontName='Arial-Bold',fontSize=22,leading=27,spaceAfter=9,keepWithNext=True)
h2=ParagraphStyle('h2',parent=body,fontName='Arial-Bold',fontSize=13,leading=17,spaceBefore=11,spaceAfter=6,keepWithNext=True)
h3=ParagraphStyle('h3',parent=body,fontName='Arial-Bold',fontSize=10.7,leading=14.5,spaceBefore=8,spaceAfter=5,keepWithNext=True)
cell=ParagraphStyle('cell',parent=body,fontSize=8.8,leading=12.1,spaceAfter=0)
head=ParagraphStyle('head',parent=cell,fontName='Arial-Bold',textColor=colors.white)
caption=ParagraphStyle('caption',parent=body,fontSize=8.4,leading=11.3,textColor=color('#495b66'),spaceAfter=9)
bullet=ParagraphStyle('bullet',parent=body,leftIndent=12,firstLineIndent=-9)
md='\n'.join(line for line in SOURCE.read_text(encoding='utf-8').splitlines() if not line.startswith('[Bản PDF]('))
tokens=MarkdownIt('commonmark').enable('table').parse(md)
def inline(token):
    out=[]
    for c in token.children or []:
        if c.type in ('text','code_inline'):out.append(escape(c.content))
        elif c.type=='strong_open':out.append('<b>')
        elif c.type=='strong_close':out.append('</b>')
        elif c.type=='em_open':out.append('<i>')
        elif c.type=='em_close':out.append('</i>')
        elif c.type in ('softbreak','hardbreak'):out.append('<br/>' if c.type=='hardbreak' else ' ')
    return ''.join(out)
story=[]; i=0; stack=[]; prefix=None; width=A4[0]-86
class Figure(Flowable):
    keepWithNext=True
    def __init__(self,drawing):
        super().__init__()
        self.drawing=drawing;self.width=drawing.width;self.height=drawing.height
    def draw(self):renderPDF.draw(self.drawing,self.canv,0,0)

while i<len(tokens):
    t=tokens[i]
    if t.type=='heading_open':
        story.append(Paragraph(inline(tokens[i+1]),{1:title,2:h2,3:h3}.get(int(t.tag[1]),h3)));i+=3;continue
    if t.type in ('bullet_list_open','ordered_list_open'):stack.append(1 if t.type=='ordered_list_open' else None)
    elif t.type in ('bullet_list_close','ordered_list_close'):stack.pop()
    elif t.type=='list_item_open':
        prefix='• ' if stack[-1] is None else f'{stack[-1]}. '
        if stack[-1] is not None:stack[-1]+=1
    elif t.type=='paragraph_open':
        children=tokens[i+1].children or []
        images=[c for c in children if c.type=='image']
        if images:
            for im in images:
                story.append(Figure(deepcopy(figures[Path(im.attrGet('src')).stem])))
        else:
            content=inline(tokens[i+1]);style=caption if tokens[i+1].content.startswith('*Hình ') else bullet if prefix else body
            story.append(Paragraph(escape(prefix or '')+content,style))
        prefix=None;i+=3;continue
    elif t.type=='table_open':
        rows=[];row=[];i+=1
        while tokens[i].type!='table_close':
            t=tokens[i]
            if t.type=='tr_open':row=[]
            elif t.type=='inline':row.append(inline(t))
            elif t.type=='tr_close':rows.append(row)
            i+=1
        n=len(rows[0]);ratios={2:[.24,.76],3:[.20,.48,.32],4:[.36,.36,.14,.14],5:[.40,.12,.12,.15,.21]}.get(n,[1/n]*n)
        data=[[Paragraph(text,head if r==0 else cell) for text in row] for r,row in enumerate(rows)]
        table=LongTable(data,colWidths=[width*v for v in ratios],repeatRows=1,hAlign='LEFT',spaceBefore=4,spaceAfter=9)
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),color(BLUE)),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,color('#f5f7f9')]),
            ('GRID',(0,0),(-1,-1),.4,color('#d9d9d9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),
            ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        story.append(table)
    i+=1
TOTAL=None
def furniture(c,doc):
    c.saveState();c.setFont('Helvetica',8);c.setFillColor(color('#424242'))
    c.drawString(43,A4[1]-27,'Capstone / Knowledge Graph Builder');c.drawRightString(A4[0]-43,A4[1]-27,'27 October 2026')
    c.drawString(43,25,'Technical progress & experimental findings');c.drawRightString(A4[0]-43,25,f'{doc.page}/{TOTAL or ""}');c.restoreState()
def document():
    return SimpleDocTemplate(str(OUTPUT),pagesize=A4,rightMargin=43,leftMargin=43,topMargin=43,bottomMargin=43,
        title='Knowledge Graph Builder - Báo cáo tiến độ 27 October 2026',author='Knowledge Graph Builder')
document().build(deepcopy(story),onFirstPage=furniture,onLaterPages=furniture)
TOTAL=len(PdfReader(OUTPUT).pages)
document().build(story,onFirstPage=furniture,onLaterPages=furniture)
reader=PdfReader(OUTPUT)
pdftext=' '.join(' '.join(line.split()) for p in reader.pages for line in p.extract_text().splitlines()
                 if not line.startswith(('Capstone / Knowledge Graph Builder','27 October 2026','Technical progress & experimental findings'))
                 and not re.fullmatch(r'\d+/\d+',line.strip()))
blocks=[]
for t in tokens:
    if t.type=='inline' and not any(c.type=='image' for c in t.children or []):
        text=''.join(c.content if c.type in ('text','code_inline') else ' ' if c.type in ('softbreak','hardbreak') else '' for c in t.children or [])
        blocks.append(' '.join(text.split()))
assert not [b for b in blocks if b not in pdftext], [b[:90] for b in blocks if b not in pdftext]
with pdfium.PdfDocument(OUTPUT) as pdf:
    for index,page in enumerate(pdf):page.render(scale=1.5).to_pil().save(QA/f'page-{index+1:02}.png')
print({'pages':len(reader.pages),'figures':len(figures),'verified_text_blocks':len(blocks),'output':str(OUTPUT)})
