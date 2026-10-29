"""Synthetic, original test paper. No copyrighted or private user PDFs."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.utils import ImageReader
from PIL import Image, ImageDraw
import textwrap

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "fixtures"
OUT.mkdir(exist_ok=True)
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def paragraph(c, text, x, y, width=85, size=11):
    c.setFont("Times-Roman", size)
    for line in textwrap.wrap(text, width=width):
        c.drawString(x, y, line)
        y -= 16
    return y - 12


def create(chinese=False):
    target = OUT / ("switch-chinese.pdf" if chinese else "paper-english.pdf")
    c = canvas.Canvas(str(target), pagesize=(612, 792), invariant=1)
    c.setTitle("TransYH synthetic research paper" if not chinese else "TransYH 中文测试论文")
    for p in range(1, 4):
        c.setFont("STSong-Light" if chinese else "Times-Bold", 19)
        titles = ["Layout-Preserving Scientific Translation", "Mathematical Model and Visual Evidence", "Two-Column Results and Discussion"]
        zh = ["保留版式的科研论文翻译", "数学模型与可视化证据", "双栏结果与讨论"]
        c.drawString(48, 735, zh[p-1] if chinese else titles[p-1])
        if chinese:
            c.setFont("STSong-Light", 12)
            for i in range(15):
                c.drawString(48, 685-i*30, "中文阅读器测试：页码、滚动位置和缩放比例应在切换时保持。")
        elif p == 1:
            c.setFont("Times-Italic", 11); c.drawString(48, 707, "TransYH Development Team | Synthetic Evaluation Paper")
            paragraph(c, "Abstract. Scientific papers contain text, mathematical equations, images, and tables. This synthetic document evaluates whether a local PDF translation system can preserve the geometry of these elements while replacing English prose with Chinese. It is an engineering fixture, and its numerical values are illustrative.", 48, 668)
            c.setFont("Times-Bold", 14); c.drawString(48, 547, "1. Introduction")
            paragraph(c, "Researchers need to read scientific literature in their preferred language. A useful translation workflow should preserve the original document and save the translation as a separate attachment. Readers should switch between documents in one tab without losing their reading position or changing the zoom level.", 48, 519)
            c.setFont("Times-Bold", 14); c.drawString(48, 396, "2. Experimental Setting")
            paragraph(c, "We use an original three-page document with a fixed page size. The first page contains ordinary English prose. The second page combines a mathematical equation, an embedded image, and a table. The final page uses two columns. All text and graphics were created specifically for this test.", 48, 368)
        elif p == 2:
            paragraph(c, "The following equation describes a simple relationship between mass and energy. Mathematical symbols should remain unchanged during translation. The figure and table are placed at fixed coordinates to assess layout preservation.", 48, 686)
            c.setFont("Times-Italic", 22); c.drawString(220, 575, "E = mc")
            c.setFont("Times-Roman", 13); c.drawString(285, 586, "2")
            c.setFont("Times-Roman", 11); c.drawString(520, 575, "(1)")
            img = Image.new("RGB", (640, 260), "#edf3f7"); d=ImageDraw.Draw(img)
            d.line([(50,220),(590,220)],fill="#364552",width=3);d.line([(50,220),(50,25)],fill="#364552",width=3)
            d.line([(60,207),(150,180),(240,158),(330,110),(420,87),(570,40)],fill="#286ca8",width=6)
            d.ellipse((325,105,335,115),fill="#c34924")
            c.drawImage(ImageReader(img), 90, 355, 430, 175)
            c.setFont("Times-Roman", 10);c.drawString(90, 335, "Figure 1. A synthetic trend used only for image preservation testing.")
            c.setFont("Times-Bold", 12);c.drawString(90, 290, "Table 1. Illustrative measurements")
            for y in [272,248,222,196]:c.line(90,y,520,y)
            for x in [90,250,390,520]:c.line(x,196,x,272)
            c.setFont("Times-Roman", 11)
            for y,values in [(256,["Method","Precision","Recall"]),(230,["Baseline","0.81","0.78"]),(204,["Proposed","0.87","0.84"])]:
                for x,v in zip([100,260,400],values):c.drawString(x,y,v)
        else:
            text = "The translation system must treat the two columns as separate reading regions. Each translated paragraph should fit its original region without covering the adjacent column. Keeping the page dimensions and page count unchanged allows reliable navigation between the original paper and its translation. This experiment measures software behavior and does not establish the linguistic quality of a real language model."
            for x in [48,322]:
                y=686
                for _ in range(3):y=paragraph(c,text,x,y,width=44,size=10)
        c.setFont("Times-Roman", 10);c.drawCentredString(306, 30, str(p));c.showPage()
    c.save()
    return target


if __name__ == "__main__":
    print(create());print(create(True))
