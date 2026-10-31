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
IMPORTANCE = {"core": 2, "important": 1, "supporting": 0}
DENSITIES = {"concise": {"core"}, "smart": {"core", "important"}, "full": set(IMPORTANCE)}
EXTRACTION_VERSION = "contextual-sections-v1"
MAX_PARAGRAPH = 5000
MAX_QUOTE = 600
SECTIONS = {
    "background": r"引言|绪论|导论|研究概述|研究背景|背景|相关工作|文献综述|introduction|background|related work|literature review",
    "methods": r"方法|研究方法|材料与方法|方法创新|模型方法|模型设计|研究设计|实验设置|实验配置|实验设计|实现细节|method|methods|methodology|materials and methods|proposed method|experimental setup|implementation details",
    "results": r"结果|实验|实验评估|实验结果|实验与结果|结果分析|主要结果|消融实验|消融分析|对比实验|定量结果|定量分析|性能比较|实验结果与分析|results|experimental results|experiments|ablation study|evaluation",
    "discussion": r"讨论|分析与讨论|结果与讨论|实验结果与讨论|results and discussion|discussion",
    "conclusion": r"结论|结论与展望|总结|总结与展望|结语|conclusion|conclusions",
    "abstract": r"摘要|abstract",
    "references": r"参考文献|引用文献|references|bibliography",
}
# Roles are context hints, never a whitelist of where research can occur.
SECTION_HINTS = {
    "discussion": r"讨论|局限|局限性|展望|discussion|limitations?",
    "conclusion": r"结论|总结|conclusions?",
    "background": r"背景|相关工作|文献综述|研究概述|related work|background",
    "methods": r"方法|框架|架构|机制|模型|研究设计|实验设置|数据集|数据来源|数据收集|数据划分|嵌入表示|多标签求解|样本|预处理|研究区|评估协议|materials?|methods?|framework|architecture|datasets?|experimental setup",
    "results": r"结果|实验|评估|消融|性能|稳健性|敏感性|迁移|检验|results?|experiments?|evaluation|ablation|robustness",
}
HEADING_PREFIX = re.compile(
    r"^(?:第\s*[一二三四五六七八九十百零〇两\d]+\s*[章节篇部]\s*|"
    r"[一二三四五六七八九十百]+[、.．]\s*|[（(][一二三四五六七八九十\d]+[）)]\s*|"
    r"\d+(?:[.．]\d+)*(?:[.．、]\s*|\s+)(?=[A-Za-z\u3400-\u9fff])|"
    r"(?-i:[IVX]+)[.．]?\s+(?=[A-Za-z\u3400-\u9fff])|"
    r"[A-Z](?:\.\d+)+(?:\s+|[.、]\s*)|[A-Z][.、]\s+)", re.I)
INLINE_ABSTRACT = re.compile(r"^\s*(?:摘\s*要|abstract)\s*[:：.。]\s*", re.I)
HEADING_CONTROLS = re.compile(r"[\x00-\x1f\x7f]")
QUALIFIERS = re.compile(
    r"但|然而|不过|仅|只在|只限|可能|不能|不代表|尚需|尚未|未能|不声称|"
    r"置信区间|±|相关而非因果|不构成因果|不意味着|不适用|不一定|"
    r"在[^。！？；;]{1,40}(?:条件下|范围内|前提下)|"
    r"\b(?:but|however|only|may|might|unless|except|not necessarily|confidence interval)\b", re.I)


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
                or type(data["count"]) is not int or data["count"] < 0
                or any(not isinstance(data.get(k),str) for k in ('base_id','text_id','config_id'))):
            raise ValueError
        # A PDF editor may remove/rewrite streams without updating our marker.
        # Never claim an existing highlight is present without checking it.
        for page_number,references in data['streams'].items():
            page_index=int(page_number)
            if not 0<=page_index<len(doc) or not isinstance(references,list):raise ValueError
            contents=doc[page_index].get_contents()
            if any(type(r) is not int or r not in contents or not doc.xref_stream(r).startswith(PREFIX) for r in references):raise ValueError
        # Each highlight must own at least one painted line, irrespective of
        # how many highlights a page contains. This is structural validation.
        if data['count'] > sum(len(refs) for refs in data['streams'].values()):raise ValueError
        return data
    except (ValueError, KeyError, TypeError, RuntimeError):
        raise HighlightError("已有 AI 标注层记录无法识别，未修改 PDF。") from None


def heading(text, title_like=False):
    # Some translated PDFs encode layout separators as U+0003. Normalize only
    # the heading classifier; the quotable text and its character map stay exact.
    candidate = HEADING_CONTROLS.sub(" ", text).strip()
    # Inline abstracts contain evidence, not just a section label.
    inline = INLINE_ABSTRACT.match(candidate)
    if inline and candidate[inline.end():].strip():
        return None
    candidate = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", candidate)
    numbered = bool(HEADING_PREFIX.match(candidate))
    candidate = HEADING_PREFIX.sub("", candidate, count=1).strip().rstrip(":：.。")
    if not candidate or len(candidate) > 90 or re.search(r"[。！？；;!?，,]", candidate):
        return None
    label = re.split(r'[:：]', candidate, maxsplit=1)[0].strip()
    for section, pattern in SECTIONS.items():
        if re.fullmatch(pattern, label, re.I):
            return section
    if re.search(r"[。！？!?]", text):
        return None
    if re.match(r"^(?:附录|附章|appendix|appendices)(?:\s|[A-Z一二三\d]|$)", candidate, re.I):
        return "appendix"
    # A custom numbered heading must end the previous section too, notably
    # when an appendix follows References. Its unknown role remains eligible.
    if numbered or title_like:
        for section, pattern in SECTION_HINTS.items():
            if re.search(pattern, candidate, re.I):
                return section
    if numbered or title_like:
        return "other"
    return None


def extract(doc, diagnostics=None):
    """Map chars in geometric reading runs; never join columns or paragraph gaps."""
    paragraphs = []
    section = "unknown"
    section_title = ""
    if diagnostics is not None:
        diagnostics.update(pages=len(doc), rotatedPages=0, unmappedLines=0)
    # Table-heavy pages can have a much smaller dominant font than the prose.
    # Use the document's Chinese prose size so table cells cannot become fake
    # chapters and reset the section for all subsequent pages.
    sizes = Counter()
    for page in doc:
        raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
        for block in raw["blocks"]:
            if block["type"] != 0: continue
            for line in block["lines"]:
                for span in line["spans"]:
                    sizes[round(span["size"], 1)] += sum(bool(re.match(r"[\u3400-\u9fff]", c["c"])) for c in span["chars"])
    body_size = sizes.most_common(1)[0][0] if sizes and max(sizes.values()) else 12
    for page_index, page in enumerate(doc):
        if page.rotation:
            if diagnostics is not None: diagnostics["rotatedPages"] += 1
            continue # No inferred rotation mapping; other pages can still be checked.
        raw = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
        def detect(chars):
            # Keyword fragments in a wrapped body line are not headings.
            large = max((c["size"] for c in chars), default=0) >= body_size * 1.18
            text = ''.join(c['c'] for c in chars)
            role = heading(text, title_like=large)
            numbered = HEADING_PREFIX.match(HEADING_CONTROLS.sub(" ", text).strip())
            if role and not (numbered or large or role in {"abstract", "references"}):
                return None
            return role
        for block_index, block in enumerate(raw["blocks"]):
            if block["type"] != 0:
                continue
            groups = []
            for line_index, line in enumerate(block["lines"]):
                if abs(line["dir"][0] - 1) > 0.01 or abs(line["dir"][1]) > 0.01:
                    if diagnostics is not None: diagnostics["unmappedLines"] += 1
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
                    if detect(part) or (previous and detect([c for line in previous['lines'] for c in line])):
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
                inline = INLINE_ABSTRACT.match(text)
                if inline and text[inline.end():].strip():
                    section, section_title = "abstract", text[:inline.end()].strip()
                    chars = chars[inline.end():]
                    text = text[inline.end():]
                    detected = None
                else:
                    inline = None
                    detected = detect(chars)
                    if detected: section, section_title = detected, text
                previous = paragraphs[-1] if paragraphs else None
                # Some producers place every wrapped line in its own PDF block.
                # Join only consecutive aligned, same-font continuation lines,
                # without sentence endings or a paragraph-sized vertical gap.
                if previous and not detected and not inline and not previous["heading"] and previous["page"] == page_index + 1:
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
                    "section_title": section_title, "inline_heading": bool(inline), "chars": chars})
    # Long, valid text must not disappear at the request-size boundary. Split
    # by character offsets without changing a glyph, box or reading order.
    chunks = []
    for paragraph in paragraphs:
        start = 0
        while len(paragraph["text"]) - start > MAX_PARAGRAPH:
            end = start + MAX_PARAGRAPH
            boundary = max(paragraph["text"].rfind(mark, start + MAX_PARAGRAPH // 2, end)
                           for mark in "。！？；;\n ")
            if boundary >= 0: end = boundary + 1
            chunks.append({**paragraph, "paragraph_id": paragraph["paragraph_id"] + f"s{start}",
                           "text": paragraph["text"][start:end], "chars": paragraph["chars"][start:end]})
            start = end
        chunks.append({**paragraph, "paragraph_id": paragraph["paragraph_id"] + (f"s{start}" if start else ""),
                       "text": paragraph["text"][start:], "chars": paragraph["chars"][start:]})
    return chunks


def text_identity(paragraphs):
    payload = [(p["paragraph_id"], p["text"], [c["box"] for c in p["chars"]]) for p in paragraphs]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def exclusion_reason(paragraph):
    if paragraph["heading"]: return "heading"
    if paragraph["section"] == "references": return "references"
    if len(paragraph["text"]) != len(paragraph["chars"]): return "unmapped_text"
    if re.search(r"\ufffd|\(cid:\d+\)", paragraph["text"]): return "invalid_encoding"
    if len(re.findall(r"[\u3400-\u9fff]", paragraph["text"])) < 8: return "insufficient_chinese"
    if len(paragraph["text"]) > MAX_PARAGRAPH: return "paragraph_too_long"
    return None


def eligible(paragraph):
    return exclusion_reason(paragraph) is None


def paragraph_diagnostics(paragraphs):
    excluded, sections = Counter(), {}
    for paragraph in paragraphs:
        reason = exclusion_reason(paragraph)
        counts = sections.setdefault(paragraph["section"], {"extracted": 0, "eligible": 0})
        counts["extracted"] += 1
        if reason: excluded[reason] += 1
        else: counts["eligible"] += 1
    return {"extracted": len(paragraphs), "eligible": len(paragraphs) - sum(excluded.values()),
            "excluded": dict(excluded), "sections": sections}


def paper_context(doc, paragraphs):
    """Bounded background for every batch; only current-batch text is quotable."""
    first = [p for p in paragraphs if p["page"] == 1 and p["section"] != "abstract"
             and 6 <= len(p["text"]) <= 400]
    title = max(first, key=lambda p: max(c["size"] for c in p["chars"]), default=None)
    title_paragraph = title
    title = HEADING_CONTROLS.sub(" ", title["text"] if title else (doc.metadata or {}).get("title", "")).strip()
    abstract = "\n".join(p["text"] for p in paragraphs if p["section"] == "abstract" and not p["heading"])
    outline, seen = [], set()
    for p in paragraphs:
        if not (p["heading"] or p.get("inline_heading")): continue
        if p is title_paragraph: continue
        label = HEADING_CONTROLS.sub(" ", p.get("section_title", p["text"])).strip()
        if (label, p["section"]) in seen: continue
        seen.add((label, p["section"]))
        outline.append({"page": p["page"], "section": p["section"], "title": label[:150]})
    return {"title": title[:400], "abstract": abstract[:6000], "sections": outline[:120],
            "truncated": {"abstract": len(abstract) > 6000, "sections": len(outline) > 120}}


def local_evidence(paragraph, quote, category):
    text = paragraph["text"]
    # Exact matching alone cannot detect a quote that drops a nearby caveat.
    # Keep the entire containing sentence when its unselected portion qualifies
    # the claim. This is deliberately conservative, not a semantic proof.
    start = text.find(quote)
    if start >= 0:
        left = max(text.rfind(mark,0,start) for mark in '。！？!?') + 1
        end = start + len(quote)
        endings = [text.find(mark,end) for mark in '。！？!?']
        right = end if quote.endswith(tuple('。！？!?')) else min((i for i in endings if i>=0),default=len(text))
        omitted = text[left:start] + text[start+len(quote):right]
        if QUALIFIERS.search(omitted):
            return False
    # Authorship, novelty and academic significance require semantic judgment.
    # Do not veto an exact, qualified AI selection by vocabulary or section.
    return True


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


def density_mode(value="smart"):
    if not isinstance(value, str) or value not in DENSITIES:
        raise HighlightError("标注密度无效，请选择精简、智能或充分。")
    return value


def validate_candidates(paragraphs, candidates, density="smart"):
    allowed = DENSITIES[density_mode(density)]
    by_id = {p["paragraph_id"]: p for p in paragraphs}
    accepted, skipped, occupied = [], Counter(), {}
    if not isinstance(candidates, list):
        raise HighlightError("AI 标注响应格式无效，原译文未修改。")
    def rank(row):
        value = row.get("importance", "important") if isinstance(row, dict) else None
        return IMPORTANCE.get(value, -1) if isinstance(value, str) else -1
    # Resolve overlapping suggestions in favour of their academic importance,
    # never by a fixed page quota or a model's self-reported confidence.
    for row in sorted(candidates, key=rank, reverse=True):
        required = {"paragraph_id", "quote", "type", "confidence"}
        if not isinstance(row, dict) or set(row) not in (required, required | {"importance"}):
            skipped["schema"] += 1; continue
        paragraph = by_id.get(row["paragraph_id"]) if isinstance(row["paragraph_id"], str) else None
        quote, category, confidence = row["quote"], row["type"], row["confidence"]
        if not paragraph: skipped["unknown_paragraph"] += 1; continue
        reason = exclusion_reason(paragraph)
        if reason: skipped["ineligible_" + reason] += 1; continue
        if not isinstance(category, str) or category not in COLORS:
            skipped["category"] += 1; continue
        if not isinstance(quote, str) or not 12 <= len(quote) <= MAX_QUOTE:
            skipped["quote_length"] += 1; continue
        if (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            skipped["confidence"] += 1; continue
        if not local_evidence(paragraph, quote, category): skipped["omitted_qualifier"] += 1; continue
        mapped = locate(paragraph, quote)
        if not mapped: skipped["unmatched_or_ambiguous"] += 1; continue
        importance = row.get("importance", "important")
        if not isinstance(importance, str) or importance not in IMPORTANCE:
            skipped["importance"] += 1; continue
        if importance not in allowed: skipped["density"] += 1; continue
        page = paragraph["page"]
        rects = [pymupdf.Rect(b) for b in mapped["boxes"]]
        if any((rect & previous).get_area() > 0 for rect in rects for previous in occupied.get(page, [])):
            skipped["duplicate_or_overlap"] += 1; continue
        occupied.setdefault(page, []).extend(rects)
        # Cache offsets and category only, never paper text or self-confidence.
        accepted.append({"paragraph_id": paragraph["paragraph_id"], "type": category,
                         "start": mapped["start"], "end": mapped["end"], "importance": importance})
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


def render_layer(source, destination, paragraphs, records, config_id, base_id, density="smart"):
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
                 "config_id": config_id, "density": density_mode(density), "count": len(records), "streams": streams}
        doc.xref_set_key(doc.pdf_catalog(), MARKER, pymupdf.get_pdf_str(json.dumps(value)))
        doc.save(destination, deflate=True)
    verify_preserved(source, destination)
