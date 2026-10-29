"""Public, synthetic Chinese samples. Reference labels were user-confirmed."""
from pathlib import Path
import json
import textwrap
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

ROOT = Path(__file__).resolve().parent
GOLD = json.loads((ROOT/'fixtures/highlight-gold.json').read_text())['cases']
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))


def create(path):
    c=canvas.Canvas(str(path),pagesize=(612,792),invariant=1)
    c.setTitle('TransYH AI highlights - synthetic, user-reviewed reference statements')
    def title(text,y=744):
        c.setFont('STSong-Light',16);c.drawString(46,y,text)
    def paragraph(text,x,y,width=42):
        c.setFont('STSong-Light',11)
        for line in textwrap.wrap(text,width=width,break_long_words=True):
            c.drawString(x,y,line);y-=18
        return y-18
    filler='此处说明样本记录方式与数据整理流程。相关内容仅用于构造版式测试，不代表本文贡献，也不应因为包含一般技术描述而标记重点。'
    title('1 背景')
    paragraph(GOLD[3]['quote']+filler*2,46,706)
    title('2 方法',550)
    paragraph(GOLD[2]['quote'],46,512,30)
    paragraph(GOLD[4]['quote']+filler*3,46,420)
    c.showPage()
    title('3 结果')
    paragraph(GOLD[0]['quote'],46,696,22)
    paragraph(filler*2,46,560,22)
    paragraph(GOLD[1]['quote'],326,696,22)
    paragraph(filler*2,326,560,22)
    c.setFont('Times-Italic',20);c.drawString(230,215,'E = mc')
    c.setFont('Times-Roman',12);c.drawString(292,224,'2')
    c.setFillColorRGB(.9,.94,.97);c.rect(46,55,520,100,fill=1,stroke=0)
    c.setStrokeColorRGB(.15,.40,.7);c.line(60,70,530,130)
    c.setFillColorRGB(0,0,0);c.showPage()
    title('4 讨论')
    paragraph('仍需跨机构验证。现有测试不能证明因果关系，也不能据此宣称适用于全部应用场景。'+filler*2,46,696)
    title('参考文献',450)
    paragraph(GOLD[5]['quote']+filler,46,410)
    c.save()
    return Path(path)
