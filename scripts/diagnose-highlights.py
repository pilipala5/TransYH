"""Read-only PDF eligibility/cache diagnosis. No API client or PDF writer is called.

Optional baseline is trusted source from this repository, e.g. --baseline-ref
origin/main. Old caches contain only validated offsets, so original AI return
counts and rejection reasons cannot be recovered from them.
"""
from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import types

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
import highlight_pdf as current


def from_revision(ref, path):
    source = subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True)
    module = types.ModuleType('diagnosis_' + Path(path).stem)
    exec(compile(source, f'{ref}:{path}', 'exec'), module.__dict__)
    return module


def old_exclusion(p):
    """Reasons for the v0.2.3 eligibility function, not semantic AI decisions."""
    if p['heading']: return 'heading'
    if (p['section'] not in {'methods', 'results', 'discussion', 'conclusion', 'abstract'}
            and not (p['section'] == 'unknown' and re.search(
                r'结果表明|实验表明|我们发现|所提方法|本文提出|本研究提出|我们提出', p['text']))):
        return 'section_or_unknown_keyword'
    if len(p['text']) != len(p['chars']): return 'unmapped_text'
    if len(re.findall(r'[\u3400-\u9fff]', p['text'])) < 8: return 'insufficient_chinese'
    if len(p['text']) > 5000: return 'paragraph_too_long'
    if re.search(r'\ufffd|\(cid:\d+\)', p['text']): return 'invalid_encoding'
    return 'other'


def summarize(paragraphs, module, include_text=False):
    reasons, sections, pages = Counter(), {}, {}
    for p in paragraphs:
        ok = module.eligible(p)
        if not ok:
            reason = current.exclusion_reason(p) if module is current else old_exclusion(p)
            reasons[reason] += 1
        for key, mapping in ((p['section'], sections), (p['page'], pages)):
            row = mapping.setdefault(key, {'extracted': 0, 'eligible': 0})
            row['extracted'] += 1; row['eligible'] += int(ok)
    return {'extracted': len(paragraphs), 'eligible': sum(module.eligible(p) for p in paragraphs),
            'excluded': dict(reasons), 'sections': sections, 'pages': pages,
            'headings': [{'page': p['page'], 'section': p['section'],
                          **({'text': p['text']} if include_text else {})}
                         for p in paragraphs if p['heading']]}


def batches(paragraphs, module):
    selected = [p for p in paragraphs if module.eligible(p)]
    for page in sorted({p['page'] for p in selected}):
        packet, length = [], 0
        for p in (p for p in selected if p['page'] == page):
            if packet and length + len(p['text']) > 10000:
                yield packet; packet, length = [], 0
            packet.append(p); length += len(p['text'])
        if packet: yield packet


def cache_summary(path, marker, paragraphs, pdf_module, jobs_module, config):
    if not marker: return {'available': False, 'reason': 'no_existing_layer_identity'}
    text_id = pdf_module.text_identity(paragraphs)
    config = {**config, 'highlightDensity': marker.get('density', 'smart')}
    identity_matches = (text_id == marker['text_id'] and jobs_module.config_identity(config) == marker['config_id'])
    candidate_id = jobs_module.candidate_identity(config)
    records, hits, misses = [], 0, 0
    # URI read-only mode: do not instantiate the normal write-capable cache.
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        for batch in batches(paragraphs, pdf_module):
            ids = [p['paragraph_id'] for p in batch]
            # Reproduce production cache identities to associate this document;
            # this is a lookup, not a file-hash integrity test.
            key = hashlib.sha256(json.dumps([marker['base_id'], text_id, candidate_id, ids],
                                           separators=(',', ':')).encode()).hexdigest()
            row = db.execute('SELECT offsets FROM selections WHERE identity=?', (key,)).fetchone()
            if row:
                hits += 1; records.extend(json.loads(row[0]))
            else: misses += 1
    by_id = {p['paragraph_id']: p for p in paragraphs}
    candidates = [{'paragraph_id': r['paragraph_id'], 'quote': by_id[r['paragraph_id']]['text'][r['start']:r['end']],
                   'type': r['type'], 'confidence': .95, 'importance': r.get('importance', 'important')}
                  for r in records]
    selected, rejected = pdf_module.validate_candidates(paragraphs, candidates, config['highlightDensity'])
    return {'available': True, 'layerIdentityMatches': identity_matches, 'matchedBatches': hits,
            'missingBatches': misses, 'validatedPool': len(records), 'selectionRejections': rejected,
            'selected': len(selected), 'rawAiReturnedCandidates': None, 'originalRejectionReasons': None,
            'records': [{'page': by_id[r['paragraph_id']]['page'], 'paragraph_id': r['paragraph_id'],
                         'type': r['type'], 'importance': r.get('importance', 'important'),
                         'start': r['start'], 'end': r['end']} for r in records]}


def diagnose(path, baseline_ref=None, legacy_cache=None, legacy_config=None, include_text=False):
    path = Path(path).resolve()
    before = path.stat()
    with pymupdf.open(path) as doc:
        stats = {}
        paragraphs = current.extract(doc, stats)
        context = current.paper_context(doc, paragraphs)
        marker = current.metadata(doc)
        report = {'schema': 1, 'input': str(path), 'readOnly': True, 'apiRequests': 0,
            'extraction': stats, 'current': summarize(paragraphs, current, include_text),
            'context': {'titleAvailable': bool(context['title']), 'abstractChars': len(context['abstract']),
                        'sections': len(context['sections']), 'truncated': context['truncated'],
                        **({'paper': context} if include_text else {})},
            'existingLayer': {'count': marker['count'], 'density': marker.get('density'),
                              'pages': sorted(int(p) + 1 for p in marker['streams'])} if marker else None,
            'interpretation': 'Eligibility is AI reachability, not an AI decision or measured semantic recall. No new candidates were generated.'}
        if baseline_ref:
            baseline = from_revision(baseline_ref, 'engine/highlight_pdf.py')
            old = baseline.extract(doc)
            report['baseline'] = summarize(old, baseline, include_text)
            report['baseline']['ref'] = baseline_ref
            glyphs = {(p['page'], tuple(c['box']), c['c']) for p in old if baseline.eligible(p)
                      for c in p['chars'] if c['box'] and not c['c'].isspace()}
            newly_reachable = []
            for p in paragraphs:
                if not current.eligible(p): continue
                chars = [c for c in p['chars'] if c['box'] and not c['c'].isspace()]
                covered = sum((p['page'], tuple(c['box']), c['c']) in glyphs for c in chars)
                if covered < len(chars):
                    newly_reachable.append({'page': p['page'], 'paragraph_id': p['paragraph_id'],
                        'section': p['section'], 'legacyEligibleGlyphs': covered, 'mappedGlyphs': len(chars),
                        **({'text': p['text'][:600]} if include_text else {})})
            report['newlyReachable'] = newly_reachable
            if legacy_cache and legacy_config:
                jobs = from_revision(baseline_ref, 'engine/highlight_jobs.py')
                report['legacyCache'] = cache_summary(legacy_cache, marker, old, baseline, jobs, legacy_config)
    after = path.stat()
    report['sourceStatUnchanged'] = ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                                    == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--baseline-ref')
    parser.add_argument('--legacy-cache', type=Path)
    parser.add_argument('--legacy-config-stdin', action='store_true',
                        help='Read only baseURL/model from stdin for a legacy cache lookup; no API key is needed.')
    parser.add_argument('--include-text', action='store_true', help='Include excerpts in the local report; treat it as private.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output:
        protected = [args.input] + ([args.legacy_cache] if args.legacy_cache else [])
        if any(args.output.resolve() == p.resolve() or
               (args.output.exists() and p.exists() and os.path.samefile(args.output, p)) for p in protected):
            parser.error('诊断报告不能覆盖输入 PDF 或旧缓存，包括符号链接和硬链接。')
    config = json.loads(sys.stdin.readline()) if args.legacy_config_stdin else None
    report = diagnose(args.input, args.baseline_ref, args.legacy_cache, config, args.include_text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
        print(json.dumps({'pages': report['extraction']['pages'],
                          'baselineEligible': report.get('baseline', {}).get('eligible'),
                          'currentEligible': report['current']['eligible'],
                          'apiRequests': 0, 'sourceStatUnchanged': report['sourceStatUnchanged']}))
    else: print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
