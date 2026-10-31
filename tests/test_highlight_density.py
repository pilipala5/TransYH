"""Focused density regressions; no translation pipeline or client restart."""
from collections import Counter
from pathlib import Path
import sys

import pymupdf
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'engine'),str(ROOT/'tests')]
from highlight_pdf import HighlightError,extract,metadata,render_layer,validate_candidates,verify_preserved
from highlight_jobs import candidate_identity,config_identity,highlights
from highlight_fixtures import create_density,DENSITY_CASES,GOLD
from test_highlights import highlight_base,config_for


def suggestions(paragraphs):
    return [{'paragraph_id':p['paragraph_id'],'quote':row['quote'],'type':row['type'],
             'confidence':.95,'importance':row['importance']}
            for p in paragraphs for row in DENSITY_CASES if row['quote'] in p['text']]


@pytest.mark.parametrize('mode,expected',[
    ('concise',[0,1,1,1]),('smart',[0,1,3,3]),('full',[0,1,3,5])])
def test_density_filters_importance_without_page_quotas(tmp_path,mode,expected):
    source=create_density(tmp_path/'source.pdf')
    with pymupdf.open(source) as pdf:paragraphs=extract(pdf)
    selected,_=validate_candidates(paragraphs,suggestions(paragraphs),density=mode)
    by_id={p['paragraph_id']:p for p in paragraphs}
    counts=Counter(by_id[row['paragraph_id']]['page'] for row in selected)
    assert [counts[p] for p in range(1,5)]==expected


@pytest.mark.parametrize('mode',['concise','smart','full'])
def test_five_core_spans_survive_even_concise_mode(tmp_path,mode):
    source=create_density(tmp_path/'source.pdf',counts=(5,))
    with pymupdf.open(source) as pdf:paragraphs=extract(pdf)
    candidates=suggestions(paragraphs)
    for row in candidates:row['importance']='core'
    selected,skipped=validate_candidates(paragraphs,candidates,density=mode)
    assert len(selected)==5 and not skipped


def test_zero_one_three_five_render_reopen_repeat_and_keep_annotations(tmp_path):
    source=create_density(tmp_path/'source.pdf')
    with pymupdf.open(source) as pdf:
        pdf[3].add_text_annot((25,25),'User PDF note remains');pdf.saveIncr()
    with pymupdf.open(source) as pdf:paragraphs=extract(pdf)
    selected,_=validate_candidates(paragraphs,suggestions(paragraphs),density='full')
    assert len(selected)==9 # Exceeds the former 4 pages * 2 metadata ceiling.
    first=tmp_path/'marked.pdf';again=tmp_path/'again.pdf'
    render_layer(source,first,paragraphs,selected,'full-v2','fixture',density='full')
    verify_preserved(source,first)
    with pymupdf.open(first) as pdf:
        assert metadata(pdf)['count']==9
        assert metadata(pdf)['density']=='full'
        assert sum(1 for _ in pdf[3].annots())==1
        for page in pdf:assert page.get_pixmap().samples
        paragraphs=extract(pdf)
    render_layer(first,again,paragraphs,selected,'full-v2','fixture',density='full')
    verify_preserved(first,again)
    with pymupdf.open(first) as a,pymupdf.open(again) as b:
        assert metadata(b)['count']==9
        assert all(p.get_pixmap().samples==q.get_pixmap().samples for p,q in zip(a,b))


def test_duplicate_overlap_and_evidence_guards_survive_all_modes(tmp_path):
    source=create_density(tmp_path/'source.pdf',counts=(5,))
    with pymupdf.open(source) as pdf:paragraphs=extract(pdf)
    candidates=suggestions(paragraphs)
    # Full mode must not admit a fabricated number or a missing caveat.
    wrong={**candidates[2],'quote':candidates[2]['quote'].replace('0.71','0.61')}
    clipped={**candidates[1],'quote':candidates[1]['quote'].split('，但')[0]}
    bad_importance={**candidates[0],'importance':'unverified'}
    for mode in ['concise','smart','full']:
        selected,rejected=validate_candidates(paragraphs,[wrong,clipped,bad_importance]+candidates+candidates,density=mode)
        assert len(selected)=={'concise':1,'smart':3,'full':5}[mode]
        assert rejected['omitted_qualifier']>=1 and rejected['unmatched_or_ambiguous']==1
        assert rejected['duplicate_or_overlap']>=1


def test_candidate_identity_is_shared_but_render_identity_tracks_density():
    config={'baseURL':'http://127.0.0.1:9/v1','model':'fixture'}
    assert len({candidate_identity({**config,'highlightDensity':m}) for m in ['concise','smart','full']})==1
    assert len({config_identity({**config,'highlightDensity':m}) for m in ['concise','smart','full']})==3
    assert config_identity(config)==config_identity({**config,'highlightDensity':'smart'})


def test_switching_modes_reuses_full_candidate_pool_and_changes_pdf(tmp_path,highlight_base):
    source=create_density(tmp_path/'source.pdf')
    config=config_for(source,tmp_path,highlight_base)
    config['model']='fixture-density-cache'
    # Start in concise: supporting candidates must still be cached.
    result=highlights({**config,'highlightDensity':'concise'})
    assert result['requests']==4 and result['highlightCount']==3
    for mode,count in [('smart',7),('full',9),('concise',3),('full',9)]:
        result=highlights({**config,'input':result['path'],'highlightDensity':mode})
        assert result['requests']==0 and result['cachedBatches']==4
        assert result['highlightCount']==count
        with pymupdf.open(result['path']) as pdf:assert metadata(pdf)['density']==mode
    repeated=highlights({**config,'input':result['path'],'highlightDensity':'full'})
    assert repeated['unchanged'] and repeated['requests']==0 and repeated['highlightCount']==9


def test_invalid_density_fails_before_api(tmp_path,highlight_base):
    source=create_density(tmp_path/'source.pdf')
    with pytest.raises(HighlightError):highlights({**config_for(source,tmp_path,highlight_base),'highlightDensity':'invalid'})
