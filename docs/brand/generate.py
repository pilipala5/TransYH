#!/usr/bin/env python3
"""Rebuild documentation artwork from unmodified, real Zotero screenshots.

Requires Pillow. No network, model, PDF processing, add-on build or XPI writes.
Run from any directory: python3 docs/brand/generate.py
Optional font overrides: TRANSYH_FONT_REGULAR, TRANSYH_FONT_BOLD,
TRANSYH_FONT_INDEX (for a TTC collection), TRANSYH_FONT_LATIN.
Screenshot rectangles are (left, top, right, bottom), in original pixels.
"""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent / "demo"
NAVY = "#17243D"
BLUE = "#4378D8"
ORANGE = "#EF8A48"
PURPLE = "#8B65CF"
MUTED = "#637087"
PALE = "#F3F5F8"
BORDER = "#DDE3EC"
WHITE = "#FFFFFF"
CREDIT = "Guo et al. (2025) · doi:10.1371/journal.pone.0338809 · CC BY 4.0 · 中文翻译 / AI 标注衍生展示"


def default_font(bold=False):
    candidates = (["/System/Library/Fonts/STHeiti Medium.ttc"] if bold else
                  ["/System/Library/Fonts/STHeiti Light.ttc"]) + [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    return next((p for p in candidates if Path(p).is_file()), None)


def font(size, bold=False, latin=False):
    key = "TRANSYH_FONT_BOLD" if bold else "TRANSYH_FONT_REGULAR"
    path = os.environ.get(key) or default_font(bold)
    index = int(os.environ.get("TRANSYH_FONT_INDEX", "1" if path and "STHeiti" in path else "0"))
    if latin:
        path = os.environ.get("TRANSYH_FONT_LATIN") or "/System/Library/Fonts/Avenir Next.ttc"
        if not Path(path).is_file():
            path = os.environ.get(key) or default_font(bold)
        index = 0
    if not path:
        raise SystemExit("Set TRANSYH_FONT_REGULAR and TRANSYH_FONT_BOLD to Chinese-capable fonts.")
    return ImageFont.truetype(path, size, index=index)


def label(im, xy, value, size=28, color=NAVY, bold=False, latin=False):
    ImageDraw.Draw(im).text(xy, value, font=font(size, bold, latin), fill=color)


def rect(im, box, fill=WHITE, radius=16, outline=None):
    ImageDraw.Draw(im).rounded_rectangle(box, radius, fill=fill, outline=outline, width=2)


def source(name):
    return Image.open(DEMO / name).convert("RGB")


def crop(im, name, box, xy, width):
    """Only crop and uniformly resize. Never retouch screenshot contents."""
    cut = source(name).crop(box)
    height = round(cut.height * width / cut.width)
    cut = cut.resize((width, height), Image.Resampling.LANCZOS)
    im.paste(cut, xy)
    return height


def save(im, name):
    # A nondithered palette keeps text crisp and limits README download size.
    if im.mode == "RGB":
        im = im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    im.save(HERE / name, optimize=True)
    print(f"{name}: {im.width}×{im.height}, {(HERE / name).stat().st_size / 1024:.0f} KiB")


def logo():
    # Two interlocking reading corners: two languages, one reading position.
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96" role="img" aria-labelledby="title desc">
  <title id="title">TransYH</title>
  <desc id="desc">Two interlocking reading corners and a focused line of text, on a navy tile.</desc>
  <rect width="96" height="96" rx="24" fill="#17243D"/>
  <g fill="none" stroke-width="8" stroke-linecap="round" stroke-linejoin="round">
    <path d="M28 54V28H58" stroke="#FFFFFF"/>
    <path d="M68 42V68H38" stroke="#4378D8"/>
    <path d="M42 45H54" stroke="#FFFFFF"/>
  </g>
</svg>
'''
    (HERE / "logo.svg").write_text(svg, encoding="utf-8")
    scale = 8
    im = Image.new("RGBA", (96 * scale, 96 * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, 96 * scale - 1, 96 * scale - 1), 24 * scale, fill=NAVY)
    for points, color in [([(28, 54), (28, 28), (58, 28)], WHITE),
                          ([(68, 42), (68, 68), (38, 68)], BLUE),
                          ([(42, 45), (54, 45)], WHITE)]:
        pts = [(x * scale, y * scale) for x, y in points]
        d.line(pts, fill=color, width=8 * scale, joint="curve")
        for x, y in pts:
            d.ellipse((x - 4 * scale, y - 4 * scale, x + 4 * scale, y + 4 * scale), fill=color)
    im = im.resize((512, 512), Image.Resampling.LANCZOS)
    save(im, "logo.png")
    return im


def hero():
    im = Image.new("RGB", (1600, 920), NAVY)
    label(im, (64, 40), "科研重点，就在论文里。", 48, WHITE, True)
    label(im, (66, 112), "中文阅读  /  原文随时可见  /  AI 重点标注", 25, "#B9C8E0")
    # The REAL v0.2.0 toolbar, enlarged as a separately labelled detail.
    rect(im, (1140, 36, 1536, 116), radius=12)
    crop(im, "highlights-after.png", (922, 0, 1120, 40), (1140, 36), 396)
    label(im, (1140, 133), "真实控件 · 局部放大", 21, "#B9C8E0")
    rect(im, (64, 194, 1536, 850), radius=16)
    crop(im, "highlights-after.png", (241, 299, 881, 485), (110, 214), 1380)
    label(im, (110, 636), "同页表格 · 独立局部放大", 20, MUTED)
    crop(im, "highlights-after.png", (241, 675, 881, 749), (110, 674), 1380)
    label(im, (66, 866), "真实 Zotero 截图 · v0.2.0 · 正文与同页表格节选", 20, "#B9C8E0")
    label(im, (1100, 866), "蓝：核心发现   橙：关键数据", 20, "#B9C8E0")
    label(im, (66, 899), CREDIT, 12, "#B9C8E0")
    save(im, "hero.png")


def comparison():
    im = Image.new("RGB", (1440, 1176), PALE)
    label(im, (60, 35), "EN", 32, BLUE, True, True)
    label(im, (126, 39), "英文原文", 28, NAVY, True)
    rect(im, (40, 100, 1400, 568), outline=BORDER)
    crop(im, "reader-english.png", (246, 301, 877, 506), (60, 120), 1320)
    label(im, (60, 601), "中文", 30, BLUE, True)
    label(im, (150, 603), "同页译文 · AI 标注前", 28, NAVY, True)
    rect(im, (40, 664, 1400, 1083), outline=BORDER)
    crop(im, "reader-chinese.png", (246, 301, 877, 482), (60, 684), 1320)
    label(im, (60, 1105), "同一论文、同一页的真实阅读画面 · 上下排布仅用于展示，并非产品分屏", 21, MUTED)
    label(im, (60, 1147), CREDIT, 14, MUTED)
    save(im, "comparison.png")


def switching():
    im = Image.new("RGB", (1440, 410), PALE)
    for y, name, text in [(30, "reader-english.png", "EN · 阅读原文"),
                          (218, "reader-chinese.png", "中文 · 阅读译文")]:
        rect(im, (40, y, 1400, y + 160), outline=BORDER)
        label(im, (76, y + 55), text, 30, NAVY, True)
        # Contiguous original toolbar area, preserving both buttons.
        crop(im, name, (1000, 0, 1120, 40), (868, y + 20), 360)
    label(im, (60, 390), CREDIT, 12, MUTED)
    save(im, "switching.png")


def highlights():
    im = Image.new("RGB", (1440, 658), PALE)
    for y, name, text in [(34, "highlights-before.png", "标注前 · 中文译文"),
                          (330, "highlights-after.png", "标注后 · AI 自动标注")]:
        label(im, (60, y), text, 30, NAVY, True)
        rect(im, (40, y + 64, 1400, y + 246), outline=BORDER)
        crop(im, name, (247, 408, 876, 483), (60, y + 76), 1320)
    label(im, (60, 615), "中文 PDF · 智能密度 · 真实标注结果局部", 22, MUTED)
    label(im, (60, 645), CREDIT, 10, MUTED)
    save(im, "highlights.png")


def social(mark):
    im = Image.new("RGB", (1200, 630), PALE)
    icon = mark.resize((72, 72), Image.Resampling.LANCZOS)
    im.paste(icon, (48, 48), icon)
    label(im, (140, 54), "TransYH", 48, NAVY, True, True)
    label(im, (50, 199), "让科研阅读", 46, NAVY, True)
    label(im, (50, 270), "回归阅读本身", 46, NAVY, True)
    label(im, (52, 365), "开源科研阅读工具", 24, MUTED)
    label(im, (52, 407), "使用你自己的 API", 24, MUTED)
    rect(im, (556, 46, 1152, 510), outline=BORDER)
    label(im, (578, 66), "真实 Zotero 画面 · v0.2.0", 20, MUTED)
    crop(im, "highlights-after.png", (241, 299, 881, 485), (574, 135), 560)
    label(im, (580, 324), "同页表格 · 独立局部", 18, MUTED)
    crop(im, "highlights-after.png", (241, 675, 881, 749), (574, 365), 560)
    label(im, (580, 466), "蓝色发现 · 橙色数据", 22, MUTED)
    ImageDraw.Draw(im).line((48, 548, 1152, 548), fill=BORDER, width=2)
    label(im, (50, 575), "Zotero 全文翻译 · 双语切换 · AI 重点标注", 24, NAVY, True)
    label(im, (890, 581), "github.com/pilipala5/TransYH", 16, MUTED)
    label(im, (50, 612), CREDIT, 12, MUTED)
    save(im, "social-cover.png")


if __name__ == "__main__":
    mark = logo()
    hero()
    comparison()
    switching()
    highlights()
    social(mark)
