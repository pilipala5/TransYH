"""Offline recall/observability regressions; no translation or real API."""
from pathlib import Path
import sqlite3
import sys

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'engine'), str(ROOT / 'tests')]
from highlight_pdf import (eligible, extract, heading, locate, paper_context,
                           render_layer, validate_candidates, verify_preserved)
from highlight_jobs import CACHE_TABLE, highlights
from highlight_fixtures import create_recall, RECALL_CASES
from test_highlights import highlight_base, config_for, candidate
from mock_api import Handler


def suggestions(paragraphs):
    return [{**candidate(p, case['quote'], case['type']), 'importance': case['importance']}
            for p in paragraphs for case in RECALL_CASES if case['quote'] in p['text']]


@pytest.mark.parametrize('text,role', [
    ('第二章 数据来源与研究设计', 'methods'), ('三、双分支交互机制', 'methods'),
    ('（四）稳健性与敏感性检验', 'results'), ('4.2 跨城市迁移与边界检验', 'results'),
    ('III. Results and Discussion', 'discussion'), ('A.1 补充验证', 'other'),
    ('附录 A 补充验证', 'appendix'), ('摘 要', 'abstract'),
    ('3.7 学术内容的自定义标题', 'other'),
    ('4.\x03结果与讨论', 'discussion'), ('3.1.\x03研究设计', 'methods'),
    ('xi 完整投诉数据集投诉类别列表时间窗口大小（天）', None),
    ('摘要：这是一段包含研究目标和主要贡献的摘要正文。', None),
    ('本方法能够解释异质变化。', None), ('两个分支分别对应不同机制。', None),
])
def test_multilingual_custom_headings_and_body_are_distinguished(text, role):
    assert heading(text) == role


def test_inline_abstract_and_chapter_structure_are_available_as_context(tmp_path):
    source = create_recall(tmp_path / 'recall.pdf')
    with pymupdf.open(source) as doc:
        paragraphs = extract(doc)
        context = paper_context(doc, paragraphs)
    assert context['title'] == '异质变化的互补表示研究'
    assert RECALL_CASES[4]['quote'] in context['abstract']
    assert any('数据来源' in row['title'] for row in context['sections'])
    assert any(row['section'] == 'appendix' for row in context['sections'])
    assert all(any(case['quote'] in p['text'] and eligible(p) for p in paragraphs) for case in RECALL_CASES)
    assert all(len(p['text']) == len(p['chars']) for p in paragraphs)


@pytest.mark.parametrize('mode,count', [('concise', 2), ('smart', 4), ('full', 5)])
def test_contextual_candidates_without_trigger_phrases_survive(tmp_path, mode, count):
    source = create_recall(tmp_path / 'recall.pdf')
    with pymupdf.open(source) as doc: paragraphs = extract(doc)
    records, rejected = validate_candidates(paragraphs, suggestions(paragraphs), density=mode)
    assert len(records) == count
    assert sum(rejected.values()) == 5 - count
    output = tmp_path / 'marked.pdf'
    render_layer(source, output, paragraphs, records, 'recall-fixture', 'synthetic', density=mode)
    verify_preserved(source, output)


def test_unknown_and_intro_sections_are_not_silent_semantic_filters(tmp_path):
    source = create_recall(tmp_path / 'recall.pdf')
    with pymupdf.open(source) as doc: paragraphs = extract(doc)
    row = suggestions(paragraphs)[0]
    p = next(p for p in paragraphs if p['paragraph_id'] == row['paragraph_id'])
    for section in ('unknown', 'background', 'methods', 'other', 'appendix'):
        p['section'] = section
        selected, rejected = validate_candidates([p], [row], density='full')
        assert len(selected) == 1 and not rejected


def assert_balanced(diagnostics):
    p = diagnostics['paragraphs']
    assert p['extracted'] == p['eligible'] + sum(p['excluded'].values())
    assert p['eligible'] == diagnostics['ai']['sentParagraphs'] + diagnostics['cache']['paragraphs']
    returned = sum(diagnostics[s]['returnedCandidates'] for s in ('ai', 'cache'))
    rejected = sum(sum(diagnostics[s]['rejected'].values()) for s in ('ai', 'cache'))
    assert returned == rejected + diagnostics['selection']['candidates']
    assert diagnostics['selection']['candidates'] == sum(diagnostics['selection']['rejected'].values()) + diagnostics['finalHighlights']


def test_mock_gets_full_context_and_cache_keeps_loss_counters(tmp_path, highlight_base):
    source = create_recall(tmp_path / 'recall.pdf')
    config = config_for(source, tmp_path, highlight_base)
    config['model'] = 'fixture-recall-context'
    capture = []
    Handler.controls[config['model']] = {'requireContext': True, 'capture': capture}
    first = highlights(config)
    assert first['highlightCount'] == 4
    assert_balanced(first['diagnostics'])
    assert all(batch['paper_context']['title'] == '异质变化的互补表示研究' for batch in capture)
    assert all(batch['paper_context']['abstract'] for batch in capture)
    cached = highlights(config)
    assert cached['requests'] == 0 and cached['diagnostics']['ai']['returnedCandidates'] == 0
    assert cached['diagnostics']['cache']['returnedCandidates'] == 5
    assert cached['diagnostics']['selection']['rejected'] == {'density': 1}
    assert_balanced(cached['diagnostics'])
    full = highlights({**config, 'input': first['path'], 'highlightDensity': 'full'})
    assert full['requests'] == 0 and full['highlightCount'] == 5
    assert_balanced(full['diagnostics'])
    reused = highlights({**config, 'input': full['path'], 'highlightDensity': 'full'})
    assert reused['diagnostics']['reusedExistingLayer']
    assert reused['diagnostics']['finalHighlights'] == 5 and reused['requests'] == 0


def test_every_returned_candidate_is_counted_including_outside_batch_ids(tmp_path, highlight_base):
    source = create_recall(tmp_path / 'recall.pdf')
    with pymupdf.open(source) as doc: paragraphs = extract(doc)
    row = next(row for row in suggestions(paragraphs) if row['type'] == 'data')
    config = config_for(source, tmp_path, highlight_base)
    Handler.controls[config['model']] = {'candidates': [
        row, row, {**row, 'paragraph_id': 'outside-request'}, None,
        {**row, 'quote': row['quote'].replace('2,481', '2,482')},
    ]}
    first = highlights(config)
    d = first['diagnostics']
    assert d['ai']['returnedCandidates'] == first['requests'] * 5
    assert d['ai']['rejected']['unknown_paragraph'] >= 2
    assert d['ai']['rejected']['schema'] == first['requests']
    assert d['ai']['rejected']['unmatched_or_ambiguous'] == 1
    assert d['ai']['rejected']['duplicate_or_overlap'] == 1
    assert_balanced(d)
    again = highlights(config)
    assert again['requests'] == 0
    assert again['diagnostics']['cache']['rejected'] == d['ai']['rejected']
    assert_balanced(again['diagnostics'])


def test_old_v023_cache_table_cannot_supply_new_candidate_pools(tmp_path, highlight_base):
    source = create_recall(tmp_path / 'recall.pdf')
    config = config_for(source, tmp_path, highlight_base)
    config['model'] = 'fixture-recall-old-cache'
    cache = tmp_path / 'cache'; cache.mkdir()
    with sqlite3.connect(cache / 'highlight-cache.sqlite3') as db:
        db.execute('CREATE TABLE selections (identity TEXT PRIMARY KEY, offsets TEXT NOT NULL)')
        db.execute('INSERT INTO selections VALUES (?,?)', ('v023-empty-pool', '[]'))
    result = highlights(config)
    assert result['requests'] == 2 and result['cachedBatches'] == 0 and result['highlightCount'] == 4
    with sqlite3.connect(cache / 'highlight-cache.sqlite3') as db:
        assert db.execute('SELECT offsets FROM selections').fetchone() == ('[]',)
        assert db.execute(f'SELECT COUNT(*) FROM {CACHE_TABLE}').fetchone()[0] == 2


def test_long_qualified_quotes_are_exact_and_not_cut_to_old_180_limit(tmp_path):
    import textwrap
    from reportlab.pdfgen import canvas
    source = tmp_path / 'long.pdf'
    text = '在固定采样条件下，' + '互补结构在多次独立测量中保持一致，' * 12 + '但这一关系仅在本实验范围内成立，不能据此推断因果关系。'
    c = canvas.Canvas(str(source)); c.setFont('STSong-Light', 11)
    for line, y in zip(textwrap.wrap(text, width=35), range(740, 100, -18)): c.drawString(46, y, line)
    c.save()
    with pymupdf.open(source) as doc: paragraphs = extract(doc)
    p = next(p for p in paragraphs if text in p['text'])
    row = candidate(p, text, 'finding')
    selected, rejected = validate_candidates(paragraphs, [row])
    assert len(text) > 180 and len(selected) == 1 and not rejected
    assert locate(p, text)
    clipped = {**row, 'quote': text.split('但')[0]}
    assert validate_candidates(paragraphs, [clipped])[1] == {'omitted_qualifier': 1}


def test_a_complete_sentence_does_not_inherit_next_sentences_unrelated_caveat(tmp_path):
    source = create_recall(tmp_path / 'recall.pdf')
    with pymupdf.open(source) as doc: paragraphs = extract(doc)
    row = suggestions(paragraphs)[0]
    p = next(p for p in paragraphs if p['paragraph_id'] == row['paragraph_id'])
    p['text'] += '但另一项实验仍需额外验证。'
    p['chars'] += [{'c': c, 'box': None, 'line': -1, 'size': 0} for c in '但另一项实验仍需额外验证。']
    selected, rejected = validate_candidates([p], [row], density='full')
    assert len(selected) == 1 and not rejected


def test_a_directly_referring_next_sentence_caveat_cannot_be_dropped(tmp_path):
    from reportlab.pdfgen import canvas
    source = tmp_path / 'qualified.pdf'
    claim = '各个城市的季节结构在独立观测中保持一致。'
    text = claim + '但该结果仅适用于本实验的密集采样条件。'
    c = canvas.Canvas(str(source)); c.setFont('STSong-Light', 11)
    c.drawString(46, 740, text); c.save()
    with pymupdf.open(source) as doc: ps = extract(doc)
    p = next(p for p in ps if text in p['text'])
    assert validate_candidates(ps, [candidate(p, claim, 'finding')])[1] == {'omitted_qualifier': 1}
    selected, rejected = validate_candidates(ps, [candidate(p, text, 'finding')])
    assert len(selected) == 1 and not rejected


def test_translated_heading_controls_and_small_table_labels_do_not_reset_sections(tmp_path):
    from reportlab.pdfgen import canvas
    source = tmp_path / 'table-headings.pdf'
    c = canvas.Canvas(str(source))
    c.setFont('STSong-Light', 20); c.drawString(46, 770, '面向复杂城市系统的数据建模框架')
    c.setFont('STSong-Light', 16); c.drawString(46, 710, '4 结果与讨论')
    c.setFont('STSong-Light', 11)
    c.drawString(46, 670, RECALL_CASES[2]['quote'])
    c.setFont('STSong-Light', 8); c.drawString(46, 610, '方法')
    c.drawString(150, 610, '模型')
    c.setFont('STSong-Light', 11); c.drawString(46, 550, RECALL_CASES[3]['quote'])
    c.save()
    with pymupdf.open(source) as doc:
        ps = extract(doc); context = paper_context(doc, ps)
    assert context['title'] == '面向复杂城市系统的数据建模框架'
    assert all(p['section'] == 'discussion' and not p['heading'] for p in ps if p['text'] in ('方法', '模型'))
    assert next(p for p in ps if RECALL_CASES[3]['quote'] in p['text'])['section'] == 'discussion'


def test_diagnostic_is_readonly_and_never_opens_a_network_connection(tmp_path, monkeypatch):
    import importlib.util
    import socket
    source = create_recall(tmp_path / 'recall.pdf')
    before = source.read_bytes()
    spec = importlib.util.spec_from_file_location('diagnose_highlights', ROOT / 'scripts/diagnose-highlights.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    def forbidden(*args, **kwargs): raise AssertionError('read-only diagnosis attempted network or PDF write')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(pymupdf.Document, 'save', forbidden)
    monkeypatch.setattr(pymupdf.Document, 'saveIncr', forbidden)
    report = module.diagnose(source)
    assert report['apiRequests'] == 0 and report['sourceStatUnchanged']
    assert report['context']['titleAvailable'] and report['context']['abstractChars'] > 0
    assert source.read_bytes() == before


def test_diagnostic_report_cannot_overwrite_input_through_a_hardlink(tmp_path):
    import os
    import subprocess
    source = create_recall(tmp_path / 'recall.pdf')
    before = source.read_bytes()
    alias = tmp_path / 'report.json'; os.link(source, alias)
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/diagnose-highlights.py'),
                             str(source), '--output', str(alias)], capture_output=True)
    assert result.returncode != 0 and source.read_bytes() == before
