"""Exact, conservative Chinese PDF span mapping and isolated graphic overlays.

No OCR, fuzzy searching, font regeneration, annotation import, or network here.
Only line wrapping is joined; every selected character retains its PDF box.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

import pymupdf

COLORS = {"finding": (0.16, 0.43, 0.95), "data": (1.0, 0.52, 0.08), "innovation": (0.60, 0.28, 0.84)}
MARKER = "TransYHHighlights"
PREFIX = b"% TransYHHighlight-v1 "
SECTIONS = {
    "background": r"引言|绪论|研究背景|背景|相关工作|文献综述|introduction|background|related work|literature review",
    "methods": r"方法|研究方法|材料与方法|方法创新|模型方法|模型设计|研究设计|实验设置|实验配置|实验设计|实现细节|method|methods|methodology|materials and methods|proposed method|experimental setup|implementation details",
    "results": r"结果|实验|实验评估|实验结果|实验与结果|结果分析|主要结果|消融实验|消融分析|对比实验|定量结果|定量分析|性能比较|实验结果与分析|results|experimental results|experiments|ablation study|evaluation",
    "discussion": r"讨论|分析与讨论|结果与讨论|实验结果与讨论|results and discussion|discussion",
    "conclusion": r"结论|结论与展望|总结|总结与展望|结语|conclusion|conclusions",
    "abstract": r"摘要|abstract",
    "references": r"参考文献|引用文献|references|bibliography",
}


class HighlightError(Exception):
    """Only authored, non-sensitive messages are allowed across the UI pipe."""


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def metadata(doc):
    kind, value = doc.xref_get_key(doc.pdf_catalog(), MARKER)
    if kind == "null":
        return None
    try:
        data = json.loads(value)
        if (data["schema"] != 1 or not isinstance(data["streams"], dict)
                or type(data["count"]) is not int or not 0 <= data["count"] <= len(doc)*2
                or any(not isinstance(data.get(k),str) for k in ('base_id','text_id','config_id'))):
            raise ValueError
        # A PDF editor may remove/rewrite streams without updating our marker.
        # Never claim an existing highlight is present without checking it.
        for page_number,references in data['streams'].items():
            page_index=int(page_number)
            if not 0<=page_index<len(doc) or not isinstance(references,list):raise ValueError
            contents=doc[page_index].get_contents()
            if any(type(r) is not int or r not in contents or not doc.xref_stream(r).startswith(PREFIX) for r in references):raise ValueError
        if data['count'] and not any(data['streams'].values()):raise ValueError
        return data
    except (ValueError, KeyError, TypeError, RuntimeError):
        raise HighlightError("已有 AI 标注层记录无法识别，未修改 PDF。") from None


def heading(text):
    candidate = re.sub(r"^\s*\d+(?:\.\d+)*[.、]?\s*", "", text).strip()
    candidate = re.split(r'[:：]',candidate,maxsplit=1)[0].strip()
    if len(candidate) > 45:
        return None
    for section, pattern in SECTIONS.items():
        if re.fullmatch(pattern, candidate, re.I):
            return section
    return None


def extract(doc):
    """Map chars in geometric reading runs; never join columns or paragraph gaps."""
    paragraphs = []
    section = "unknown"
    for page_index, page in enumerate(doc):
        if page.rotation:
            continue # No inferred rotation mapping; other pages can still be checked.
        raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
        for block_index, block in enumerate(raw["blocks"]):
            if block["type"] != 0:
                continue
            groups = []
            for line_index, line in enumerate(block["lines"]):
                if abs(line["dir"][0] - 1) > 0.01 or abs(line["dir"][1]) > 0.01:
                    continue  # Rotated/vertical text is outside the mapper.
                parts, part = [], []
                for span in line["spans"]:
                    for char in span["chars"]:
                        box = pymupdf.Rect(char["bbox"])
                        if part and box.x0 - part[-1]["box"][2] > max(18, span["size"] * 3):
                            parts.append(part); part = []
                        part.append({"c": char["c"], "box": tuple(box), "line": f"{block_index}:{line_index}",
                                     "size": span["size"]})
                if part:
                    parts.append(part)
                for part in parts:
                    box = pymupdf.Rect(part[0]["box"])
                    for char in part[1:]: box.include_rect(char["box"])
                    size = max(c["size"] for c in part)
                    previous = next((g for g in reversed(groups)
                        if abs(g["last"].x0 - box.x0) <= size * 2
                        and -size * .25 <= box.y0 - g["last"].y1 <= size * 1.2
                        and .8 <= size / g["size"] <= 1.25), None)
                    if heading(''.join(c['c'] for c in part)) or (previous and heading(''.join(c['c'] for line in previous['lines'] for c in line))):
                        previous=None
                    if previous is None:
                        groups.append({"lines": [part], "last": box, "size": size})
                    else:
                        previous["lines"].append(part); previous["last"] = box
            for group_index, group in enumerate(groups):
                chars = []
                for line in group["lines"]:
                    if chars and (re.match(r"[A-Za-z0-9]", chars[-1]["c"]) or re.match(r"[A-Za-z0-9]", line[0]["c"])):
                        chars.append({"c": " ", "box": None, "line": -1, "size": 0})
                    chars.extend(line)
                while chars and chars[0]["c"].isspace(): chars.pop(0)
                while chars and chars[-1]["c"].isspace(): chars.pop()
                if not chars:
                    continue
                text = "".join(c["c"] for c in chars)
                detected = heading(text)
                if detected: section = detected
                previous = paragraphs[-1] if paragraphs else None
                # Some producers place every wrapped line in its own PDF block.
                # Join only consecutive aligned, same-font continuation lines,
                # without sentence endings or a paragraph-sized vertical gap.
                if previous and not detected and not previous["heading"] and previous["page"] == page_index + 1:
                    last = next(c for c in reversed(previous["chars"]) if c["box"])
                    first = next(c for c in chars if c["box"])
                    left = next(c for c in previous["chars"] if c["box"])
                    size = first["size"]
                    if (not re.search(r"[。！？；.!?;:]$", previous["text"])
                            and abs(left["box"][0] - first["box"][0]) < size * .25
                            and 0 <= first["box"][1] - last["box"][3] <= size
                            and .9 <= size / last["size"] <= 1.1):
                        separator = " " if re.match(r"[A-Za-z0-9]", last["c"]) or re.match(r"[A-Za-z0-9]", first["c"]) else ""
                        if separator: previous["chars"].append({"c":" ","box":None,"line":-1,"size":0})
                        previous["chars"].extend(chars)
                        previous["text"] += separator + text
                        continue
                paragraphs.append({"paragraph_id": f"p{page_index + 1}b{block_index}g{group_index}",
                    "page": page_index + 1, "section": section, "text": text, "heading": bool(detected),
                    "chars": chars})
    return paragraphs


def text_identity(paragraphs):
    payload = [(p["paragraph_id"], p["text"], [c["box"] for c in p["chars"]]) for p in paragraphs]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def eligible(paragraph):
    section = paragraph["section"]
    explicit_report = bool(re.search(r'结果表明|实验表明|我们发现|所提方法|本文提出|本研究提出|我们提出',paragraph['text']))
    return (not paragraph["heading"] and (section in {"methods", "results", "discussion", "conclusion", "abstract"}
                or (section == 'unknown' and explicit_report))
            and len(paragraph['text']) == len(paragraph['chars'])
            and len(re.findall(r"[\u3400-\u9fff]", paragraph["text"])) >= 8
            and len(paragraph["text"]) <= 5000
            and not re.search(r"\ufffd|\(cid:\d+\)", paragraph["text"]))


def local_evidence(paragraph, quote, category):
    text = paragraph["text"]
    # Exact matching alone cannot detect a quote that drops a nearby caveat.
    # Keep the entire containing sentence when its unselected portion qualifies
    # the claim. This is deliberately conservative, not a semantic proof.
    start = text.find(quote)
    if start >= 0:
        left = max(text.rfind(mark,0,start) for mark in '。！？') + 1
        endings = [text.find(mark,start+len(quote)) for mark in '。！？']
        right = min((i for i in endings if i>=0),default=len(text))
        omitted = text[left:start] + text[start+len(quote):right]
        if re.search(r'但|仅|可能|不能|不代表|尚需|未能|不声称|置信区间|相关而非因果',omitted):
            return False
    if category == "innovation":
        return bool(re.search(r"本文提出|本研究提出|我们提出|首次|创新|不同于|提出了|设计了", text))
    if paragraph["section"] == "methods":
        return False  # Routine experimental settings are not reported results.
    if re.search(r"既有研究|已有研究|前人研究|文献报道|不是本文|并非本文", quote):
        return False
    if category == "data":
        return bool(re.search(r"\d", quote) and re.search(
            r"MAE|RMSE|MSE|F1|AUC|准确率|精度|误差|召回率|耗时|延迟|吞吐|提高|降低|降至|增长|相比|相较|基线|对照|百分点|毫秒|秒|千米|公里|厘米|mm|mg|km", quote, re.I))
    return bool(re.search(r"结果|发现|表明|观察到|所提方法|证实|证明了|降低|下降|提升|优于|相关性|呈.+相关", quote))


def locate(paragraph, quote):
    start = paragraph["text"].find(quote)
    if start < 0 or paragraph["text"].find(quote, start + 1) >= 0:
        return None  # Never choose the first of multiple possible positions.
    selected = paragraph["chars"][start:start + len(quote)]
    boxes = []
    for line in dict.fromkeys(c["line"] for c in selected if c["box"] and not c["c"].isspace()):
        chars = [c for c in selected if c["line"] == line and c["box"] and not c["c"].isspace()]
        if not chars: continue
        box = pymupdf.Rect(chars[0]["box"])
        for previous, char in zip(chars, chars[1:]):
            if char["box"][0] - previous["box"][2] > max(18, char["size"] * 3):
                return None
            box.include_rect(char["box"])
        if box.is_empty or not all(math.isfinite(x) for x in box): return None
        boxes.append(tuple(box))
    return {"start": start, "end": start + len(quote), "boxes": boxes} if boxes else None


def validate_candidates(paragraphs, candidates):
    by_id = {p["paragraph_id"]: p for p in paragraphs}
    accepted, skipped, occupied, counts, lengths = [], Counter(), {}, Counter(), Counter()
    total_chars = Counter()
    for p in paragraphs: total_chars[p["page"]] += len(re.sub(r"\s", "", p["text"]))
    if not isinstance(candidates, list):
        raise HighlightError("AI 标注响应格式无效，原译文未修改。")
    if len(candidates) > 200:
        raise HighlightError("AI 标注候选过多，原译文未修改。")
    for row in candidates:
        if not isinstance(row, dict) or set(row) != {"paragraph_id", "quote", "type", "confidence"}:
            skipped["schema"] += 1; continue
        paragraph = by_id.get(row["paragraph_id"]) if isinstance(row["paragraph_id"], str) else None
        quote, category, confidence = row["quote"], row["type"], row["confidence"]
        if not paragraph or not eligible(paragraph): skipped["section"] += 1; continue
        if (not isinstance(category, str) or category not in COLORS or not isinstance(quote, str)
                or not 12 <= len(quote) <= 180 or len(re.findall(r"[。！？]", quote)) > 2
                or isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not .8 <= confidence <= 1):
            skipped["policy"] += 1; continue
        if not local_evidence(paragraph, quote, category): skipped["evidence"] += 1; continue
        mapped = locate(paragraph, quote)
        if not mapped: skipped["unmatched_or_ambiguous"] += 1; continue
        page = paragraph["page"]
        quote_length = len(re.sub(r"\s", "", quote))
        if counts[page] >= 2 or lengths[page] + quote_length > max(40, min(240, int(total_chars[page] * .25))):
            skipped["density"] += 1; continue
        rects = [pymupdf.Rect(b) for b in mapped["boxes"]]
        if any((rect & previous).get_area() > 0 for rect in rects for previous in occupied.get(page, [])):
            skipped["duplicate_or_overlap"] += 1; continue
        occupied.setdefault(page, []).extend(rects)
        counts[page] += 1; lengths[page] += quote_length
        # Cache offsets and category only, never paper text or self-confidence.
        accepted.append({"paragraph_id": paragraph["paragraph_id"], "type": category,
                         "start": mapped["start"], "end": mapped["end"]})
    return accepted, dict(skipped)


def strip_layer(doc, marker):
    if not marker: return
    for page_number, references in marker["streams"].items():
        page = doc[int(page_number)]
        current = page.get_contents()
        if not isinstance(references, list) or any(x not in current or not doc.xref_stream(x).startswith(PREFIX) for x in references):
            raise HighlightError("已有 AI 标注层无法安全更新，未修改 PDF。")
        doc.xref_set_key(page.xref, "Contents", "[" + " ".join(f"{x} 0 R" for x in current if x not in references) + "]")


def preservation_snapshot(doc):
    return ((tuple(p.rect), p.rotation, tuple(p.cropbox), p.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT),
             [(a.type, a.rect, dict(a.info), a.vertices) for a in p.annots() or []],
             [{k:v for k,v in image.items() if k!='size'} for image in p.get_image_info()]) for p in doc)


def verify_preserved(before, after):
    with pymupdf.open(before) as a, pymupdf.open(after) as b:
        if (not b.is_pdf or b.is_repaired or b.needs_pass or len(a)!=len(b)
                or any(x!=y for x,y in zip(preservation_snapshot(a),preservation_snapshot(b)))):
            raise HighlightError("标注后 PDF 完整性核验失败，原译文未修改。")


def render_layer(source, destination, paragraphs, records, config_id, base_id):
    by_id = {p["paragraph_id"]: p for p in paragraphs}
    with pymupdf.open(source) as doc:
        if doc.needs_pass or doc.is_repaired or not doc.is_pdf or doc.get_sigflags() > 0:
            raise HighlightError("加密、损坏或签名 PDF 不支持安全标注，原译文未修改。")
        strip_layer(doc, metadata(doc))
        group = doc.add_ocg("TransYH 科研重点", on=True)
        streams = {}
        for row in records:
            paragraph = by_id.get(row["paragraph_id"])
            if not paragraph or not 0 <= row["start"] < row["end"] <= len(paragraph["text"]):
                raise HighlightError("标注缓存与 PDF 文本不匹配，原译文未修改。")
            quote = paragraph["text"][row["start"]:row["end"]]
            mapping = locate(paragraph, quote)
            if not mapping or row["type"] not in COLORS:
                raise HighlightError("标注定位不唯一，原译文未修改。")
            page = doc[paragraph["page"]-1]
            before = set(page.get_contents())
            for box in mapping["boxes"]:
                rect = pymupdf.Rect(box)
                if not page.rect.contains(rect):
                    raise HighlightError("标注坐标超出页面，原译文未修改。")
                page.draw_rect(rect, color=None, fill=COLORS[row["type"]], fill_opacity=.20, overlay=True, oc=group)
            added = set(page.get_contents()) - before
            for reference in added: doc.update_stream(reference, PREFIX + b"\n" + doc.xref_stream(reference))
            streams.setdefault(str(page.number), []).extend(sorted(added))
        value = {"schema": 1, "base_id": base_id, "text_id": text_identity(paragraphs),
                 "config_id": config_id, "count": len(records), "streams": streams}
        doc.xref_set_key(doc.pdf_catalog(), MARKER, pymupdf.get_pdf_str(json.dumps(value)))
        doc.save(destination, deflate=True)
    verify_preserved(source, destination)
