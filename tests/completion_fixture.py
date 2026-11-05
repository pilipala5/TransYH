"""Authored English input and deterministic translations for native completion QA."""
from pathlib import Path
import textwrap

from reportlab.pdfgen import canvas
from highlight_fixtures import GOLD


TRANSLATIONS = {
    "Synthetic Completion Study": "合成任务收尾研究",
    "Abstract": "摘要",
    "Methods": "方法",
    "Results": "结果",
    "This synthetic study checks a complete translation and annotation workflow. "
    "The document was authored only to verify software completion and file safety.":
        "本文使用合成论文检查全文翻译、自动标注和阅读器切换的完整流程。所有材料用于验证软件收尾与文件安全。",
    "Unlike a shared residual correction, this study proposes two correction channels "
    "that separately estimate the trend component and the residual component.": GOLD[2]["quote"],
    "Across three test datasets, the proposed method reduces prediction errors. "
    "This finding supports effectiveness only within the scope of these experiments.": GOLD[0]["quote"],
    "On dataset A, the mean absolute error decreases from 0.84 to 0.71, "
    "which corresponds to a reduction of 15.5 percent.": GOLD[1]["quote"],
}
PARAGRAPHS = list(TRANSLATIONS)[4:]


def create(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=(612, 792), invariant=1)
    pdf.setTitle("TransYH authored completion fixture")
    pdf.setFont("Times-Bold", 20)
    pdf.drawString(48, 740, "Synthetic Completion Study")
    y = 690
    for heading, paragraphs in [
        ("Abstract", PARAGRAPHS[:1]),
        ("Methods", PARAGRAPHS[1:2]),
        ("Results", PARAGRAPHS[2:]),
    ]:
        pdf.setFont("Times-Bold", 14)
        pdf.drawString(48, y, heading)
        y -= 30
        pdf.setFont("Times-Roman", 11)
        for paragraph in paragraphs:
            for line in textwrap.wrap(paragraph, width=85):
                pdf.drawString(48, y, line)
                y -= 18
            y -= 24
    pdf.save()
    return path


if __name__ == "__main__":
    import sys
    create(Path(sys.argv[1]))
