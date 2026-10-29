"""Conservative, local-only PDF checks. Reports contain codes/counts, never text.

These rules find engineering defects, not translation accuracy. All content and
layout heuristics are suspicions; only unreadable PDFs and incompatible page
geometry block delivery. No network, OCR, or extra model calls are used.
"""
from __future__ import annotations

from collections import Counter
import contextlib
import json
import math
import os
from pathlib import Path
import re
import time

import pymupdf

WORDS = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")
FUNCTION_WORDS = set("the a an is are was were be been this that these those we our they their of in on for with to and or by from as which can should not into between during while whether without".split())


def plain(text):
    text = re.sub(r"<code\b[^>]*>.*?</code>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"https?://\S+|\bdoi\s*:\s*\S+|\b10\.\d{4,9}/\S+", " ", text, flags=re.I)
    return re.sub(r"<[^>]+>|\{v\d+\}|\[\[.*?\]\]", " ", text)


def is_prose(text):
    """Require sentence-like English, not an acronym/term/formula list."""
    text = plain(text)
    if re.match(r"^\s*(?:\[\d+\]|\d+\.)\s+.*(?:\b(?:19|20)\d{2}\b|doi)", text, re.I | re.S):
        return False
    words = WORDS.findall(text)
    lower = [w.lower() for w in words]
    return (len(words) >= 18 and sum(w in FUNCTION_WORDS for w in lower) >= 4
            and sum(w.isupper() for w in words) < len(words) / 2
            and bool(re.search(r"[.!?;,:]", text)))


def normalized(text):
    return re.sub(r"\s+", "", plain(text)).casefold()


class QualityAudit:
    def __init__(self):
        self.issues = Counter()
        self.paragraphs = 0
        self.prose = 0
        self.unchanged = 0
        self.tracking = False
        self.structural = False
        self.pages = 0

    def add(self, code, page=None, count=1, structural=False):
        self.issues[(code, page)] += count
        self.structural |= structural

    def tracking_data(self, data, page_numbers=None):
        self.tracking = True
        for group in ("page", "cross_page", "cross_column"):
            references = False
            for index, page in enumerate(data.get(group, [])):
                number = (page_numbers[index] if page_numbers and index < len(page_numbers) else index + 1) if group == "page" else None
                for row in page.get("paragraph", []):
                    src = row.get("input") or row.get("pdf_unicode") or ""
                    if re.match(r"^\s*(?:references|bibliography)\s*$", plain(src), re.I):
                        references = True
                    self.paragraphs += 1
                    # Reference lists, short labels and formula-only fragments
                    # are not evidence of untranslated English body prose.
                    if references or not is_prose(src):
                        continue
                    self.prose += 1
                    dst = row.get("output")
                    attempts = row.get("llm_translate_trackers", [])
                    failed = any(t.get("has_error") for t in attempts)
                    if dst is None:
                        # An absent final output after an attempted translation
                        # means BabelDOC may have retained the source paragraph.
                        self.add("paragraph_fallback" if attempts else "paragraph_unconfirmed", number)
                    elif not plain(dst).strip():
                        self.add("empty_translation", number)
                    elif normalized(src) == normalized(dst):
                        self.unchanged += 1
                        self.add("failed_retained_english" if failed else "unchanged_english_prose", number)
                    elif len(normalized(dst)) < len(normalized(src)) * 0.12:
                        self.add("possible_truncation", number)
                    for placeholder in row.get("placeholders", []):
                        if placeholder.get("type") == "formula" and dst is not None:
                            token = placeholder.get("placeholder")
                            if token and token not in dst:
                                self.add("possible_formula_loss", number)
        if self.prose >= 3 and self.unchanged / self.prose >= 0.3:
            self.add("large_untranslated_body")

    def report(self):
        return {"schema": 1, "status": "structural_error" if self.structural else "suspect" if self.issues else "pass",
                "pages": self.pages, "trackingAvailable": self.tracking,
                "checkedParagraphs": self.paragraphs, "englishBodyParagraphs": self.prose,
                "issues": [{"code": code, "page": page, "count": count}
                           for (code, page), count in self.issues.items()]}


@contextlib.contextmanager
def track_babeldoc(high_level, audit):
    """Read 0.6.4's existing tracker immediately before its temp dir is cleaned.

    Only the single-job worker's module references are wrapped. The installed
    BabelDOC package is never edited. Full paragraph data stays temporary/local.
    """
    originals = {name: getattr(high_level, name) for name in ("ILTranslator", "ILTranslatorLLMOnly")}
    def wrap(base):
        class Tracked(base):
            def translate(self, docs):
                super().translate(docs)
                try:
                    path = self.translation_config.get_working_file_path("translate_tracking.json")
                    data = json.loads(Path(path).read_text(encoding="utf-8"))
                    audit.tracking_data(data, [int(p.page_number) + 1 for p in docs.page])
                except Exception:
                    audit.add("paragraph_tracking_unavailable")
        return Tracked
    try:
        for name, base in originals.items():
            setattr(high_level, name, wrap(base))
        yield
    finally:
        for name, base in originals.items():
            setattr(high_level, name, base)


def text_lines(page):
    data = page.get_text("dict", clip=pymupdf.INFINITE_RECT(), flags=pymupdf.TEXTFLAGS_TEXT)
    return [(pymupdf.Rect(line["bbox"]), "".join(s["text"] for s in line["spans"]))
            for block in data["blocks"] if block["type"] == 0 for line in block["lines"]
            if any(s["text"].strip() for s in line["spans"])]


def overlap_count(lines):
    # A sweep over text lines, not quadratic comparisons of all page blocks.
    active = []
    count = 0
    for box, text in sorted(lines, key=lambda row: row[0].y0):
        active = [(b, t) for b, t in active if b.y1 > box.y0]
        if len(text.strip()) < 8 or box.get_area() <= 0:
            continue
        for other, other_text in active:
            if len(other_text.strip()) < 8:
                continue
            intersection = box & other
            # Font ascenders, superscripts and slight line touching do not count.
            if (intersection.get_area() > 0.65 * min(box.get_area(), other.get_area())
                    and intersection.width > 25 and text.strip() != other_text.strip()):
                count += 1
        active.append((box, text))
    return count


def image_placements(page):
    # get_image_info describes displayed occurrences, including inline images
    # and repeated uses of one xref. Never compare PDF object counts or hashes.
    return [pymupdf.Rect(i["bbox"]) for i in page.get_image_info()
            if pymupdf.Rect(i["bbox"]).get_area() >= 400]


def check_pdf(source, translated, audit=None):
    audit = audit or QualityAudit()
    try:
        src = pymupdf.open(source)
        dst = pymupdf.open(translated)
    except Exception:
        if "src" in locals():
            src.close()
        audit.add("pdf_unreadable", structural=True)
        return audit.report()
    with src, dst:
        audit.pages = len(src)
        if not src.is_pdf or not dst.is_pdf or src.needs_pass or dst.needs_pass or dst.is_repaired:
            audit.add("pdf_damaged_or_locked", structural=True)
            return audit.report()
        if len(src) != len(dst) or not len(dst):
            audit.add("page_count_mismatch", structural=True)
            return audit.report()
        references = False
        for index in range(len(src)):
            number = index + 1
            try:
                a, b = src[index], dst[index]
                geometry = (*a.rect, a.rotation, *a.cropbox)
                output_geometry = (*b.rect, b.rotation, *b.cropbox)
                if (not all(math.isfinite(x) for x in output_geometry)
                        or b.rect.is_empty or any(abs(x-y) > 1 for x, y in zip(geometry, output_geometry))):
                    audit.add("page_geometry_mismatch", number, structural=True)
            except Exception:
                audit.add("page_unreadable", number, structural=True)
                continue
            try:
                source_lines, target_lines = text_lines(a), text_lines(b)
            except Exception:
                audit.add("page_extraction_failed", number)
                continue
            original_text = "\n".join(t for _, t in source_lines)
            text = "\n".join(t for _, t in target_lines)
            if len(original_text.strip()) >= 80 and not text.strip():
                audit.add("page_text_missing", number)
            elif len(normalized(original_text)) >= 300 and len(normalized(text)) < len(normalized(original_text)) * 0.12:
                audit.add("page_text_truncated", number)
            bad = text.count("\ufffd") + len(re.findall(r"\(cid:\d+\)", text))
            old_bad = original_text.count("\ufffd") + len(re.findall(r"\(cid:\d+\)", original_text))
            if bad > old_bad + 2:
                audit.add("replacement_characters", number, bad-old_bad)
            bounds = pymupdf.Rect(0, 0, b.cropbox.width, b.cropbox.height) + (-3, -3, 3, 3)
            old_out = sum(not (pymupdf.Rect(0, 0, a.cropbox.width, a.cropbox.height) + (-3, -3, 3, 3)).contains(r) for r, _ in source_lines)
            outside = sum(not bounds.contains(r) for r, _ in target_lines)
            if outside > old_out:
                audit.add("text_outside_page", number, outside-old_out)
            overlaps = overlap_count(target_lines) - overlap_count(source_lines)
            if overlaps >= 2:
                audit.add("severe_text_overlap", number, overlaps)
            # Aggregate lines into extraction blocks to detect substantial
            # unchanged body prose even when the paragraph tracker is absent.
            try:
                blocks = b.get_text("blocks")
            except Exception:
                audit.add("page_extraction_failed", number)
                blocks = []
            for block in blocks:
                if block[6] != 0:
                    continue
                candidate = block[4]
                if re.match(r"^\s*(?:references|bibliography)\b", candidate, re.I):
                    references = True
                if not references and is_prose(candidate) and normalized(candidate) in normalized(original_text):
                    audit.add("pdf_unchanged_english_body", number)
            try:
                before, after = image_placements(a), image_placements(b)
                for rect in before:
                    if not any((rect & r).get_area() >= rect.get_area() * 0.8 for r in after):
                        # A renderer may replace an image with vector graphics.
                        # This is only a suspicion, never a structural failure.
                        audit.add("possible_image_loss", number)
                # Only short, explicit equation lines. Complex/vector equations
                # remain outside this lightweight check's coverage.
                compact = re.sub(r"\s+", "", text)
                for _, line in source_lines:
                    if re.search(r"[=∑∫]", line) and 3 <= len(line.strip()) <= 80 and len(WORDS.findall(line)) <= 8:
                        if re.sub(r"\s+", "", line) not in compact:
                            audit.add("possible_formula_loss", number)
            except Exception:
                audit.add("graphics_check_unavailable", number)
    return audit.report()


def save_report(report, output_dir):
    path = Path(output_dir) / "quality-report.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as stream:
        json.dump({**report, "checkedAt": int(time.time())}, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return str(path)
