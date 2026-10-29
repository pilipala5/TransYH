import json
from pathlib import Path
import sys

import pymupdf
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'));sys.path.insert(0,str(ROOT/'tests'))
from highlight_pdf import (COLORS, HighlightError, extract, eligible, fingerprint, heading,
    locate, metadata, render_layer, validate_candidates, verify_preserved)
from highlight_fixtures import create, GOLD


@pytest.fixture
def paper(tmp_path):return create(tmp_path/'reference.pdf')


def candidate(paragraph,quote,kind,confidence=.95):
    return {'paragraph_id':paragraph['paragraph_id'],'quote':quote,'type':kind,'confidence':confidence}


def rows(paragraphs):
    return [candidate(next(p for p in paragraphs if g['quote'] in p['text']),g['quote'],g['type'])
            for g in GOLD if g['type']]


def test_user_confirmed_spans_map_across_lines_and_columns_without_text_changes(paper,tmp_path):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,skipped=validate_candidates(paragraphs,rows(paragraphs))
    assert len(records)==3 and not skipped
    target=tmp_path/'marked.pdf'
    render_layer(paper,target,paragraphs,records,'fixture-model-prompt','fixture-document')
    verify_preserved(paper,target)
    with pymupdf.open(target) as pdf:
        assert metadata(pdf)['count']==3
        for row in records:
            p=next(p for p in paragraphs if p['paragraph_id']==row['paragraph_id'])
            mapping=locate(p,p['text'][row['start']:row['end']])
            assert len(mapping['boxes'])>=2 # Actual multi-line quotes.
            if row['type']=='finding':assert max(b[2] for b in mapping['boxes'])<310
            if row['type']=='data':assert min(b[0] for b in mapping['boxes'])>320


def test_user_confirmed_exclusions_do_not_become_highlights(paper):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    candidates=[candidate(next(p for p in paragraphs if g['quote'] in p['text']),g['quote'],
        'data' if g['id']=='prior_work' else 'innovation' if g['id']=='routine' else 'finding') for g in GOLD if not g['type']]
    accepted,skipped=validate_candidates(paragraphs,candidates)
    assert accepted==[] and sum(skipped.values())==3


@pytest.mark.parametrize('change',['wrong_number','paraphrase','bad_id','confidence','unknown_type','long_quote','duplicate'])
def test_invalid_candidates_do_not_guess_coordinates(paper,change):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    selected=rows(paragraphs)[1]
    if change=='wrong_number':selected['quote']=selected['quote'].replace('0.71','0.61')
    elif change=='paraphrase':selected['quote']='该模型取得了显著优于所有已有方法的实验效果。'
    elif change=='bad_id':selected['paragraph_id']='nonexistent'
    elif change=='confidence':selected['confidence']=True
    elif change=='unknown_type':selected['type']='summary'
    elif change=='long_quote':selected['quote']*=10
    candidates=[selected,selected] if change=='duplicate' else [selected]
    accepted,skipped=validate_candidates(paragraphs,candidates)
    assert len(accepted)==(1 if change=='duplicate' else 0)
    assert sum(skipped.values())==1


def test_repeated_quote_within_one_paragraph_is_ambiguous(paper):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    p=next(p for p in paragraphs if p['section']=='methods' and not p['heading'])
    quote=GOLD[2]['quote'];p['text']=quote+quote;p['chars']*=2
    assert locate(p,quote) is None


def test_old_graphics_layer_is_replaced_without_duplicate_marks(paper,tmp_path):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    first=tmp_path/'first.pdf';second=tmp_path/'second.pdf'
    render_layer(paper,first,paragraphs,records,'v1','fixture')
    with pymupdf.open(first) as pdf:paragraphs=extract(pdf)
    render_layer(first,second,paragraphs,records,'v2','fixture')
    with pymupdf.open(first) as a,pymupdf.open(second) as b:
        for x,y in zip(a,b):
            assert x.get_pixmap().samples==y.get_pixmap().samples
        assert metadata(b)['config_id']=='v2'


def test_pdf_annotations_and_copied_text_survive(paper,tmp_path):
    with pymupdf.open(paper) as pdf:
        note=pdf[0].add_text_annot((30,30),'existing user PDF note')
        note.set_info(title='User note');pdf.saveIncr()
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    render_layer(paper,tmp_path/'marked.pdf',paragraphs,records,'v1','fixture')
    verify_preserved(paper,tmp_path/'marked.pdf')


def test_existing_three_page_chinese_fixture_is_not_overmarked():
    with pymupdf.open(ROOT/'tests/fixtures/switch-chinese.pdf') as pdf:
        assert not any(eligible(p) for p in extract(pdf))


@pytest.mark.parametrize('text,section',[
    ('4 实验','results'),('4.1 实验设置','methods'),('4.2 主要结果：骨干网络与基准测试','results'),
    ('5 消融实验','results'),('6 总结与展望','conclusion'),('结果表明模型取得改进。',None)])
def test_common_translated_headings_and_body_sentences_are_distinguished(text,section):
    assert heading(text)==section


def test_missing_layer_stream_is_not_mistaken_for_a_cached_highlight(paper,tmp_path):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    marked=tmp_path/'marked.pdf';render_layer(paper,marked,paragraphs,records,'v1','fixture')
    with pymupdf.open(marked) as pdf:
        marker=metadata(pdf)
        page=pdf[0];owned=marker['streams']['0']
        pdf.xref_set_key(page.xref,'Contents','['+' '.join(f'{r} 0 R' for r in page.get_contents() if r not in owned)+']')
        pdf.saveIncr()
    with pymupdf.open(marked) as pdf:
        with pytest.raises(HighlightError):metadata(pdf)


def test_quote_may_not_drop_the_containing_sentences_critical_limitation(paper):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    row=rows(paragraphs)[0]
    row['quote']=row['quote'].split('，但')[0]
    accepted,skipped=validate_candidates(paragraphs,[row])
    assert not accepted and skipped=={'evidence':1}


def test_rotated_pages_are_skipped_instead_of_inventing_coordinates(paper):
    with pymupdf.open(paper) as pdf:
        pdf[1].set_rotation(90);pdf.saveIncr()
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    assert not any(p['page']==2 for p in paragraphs)


def test_ordinary_description_in_results_is_not_a_finding(paper):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    p=next(p for p in paragraphs if p['section']=='results' and p['text'].startswith('此处说明'))
    quote='此处说明样本记录方式与数据整理流程。'
    accepted,skipped=validate_candidates(paragraphs,[candidate(p,quote,'finding')])
    assert not accepted and skipped=={'evidence':1}


def test_duplicate_and_page_budget_are_enforced(paper):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    candidates=rows(paragraphs)
    accepted,skipped=validate_candidates(paragraphs,candidates+candidates)
    assert len(accepted)==3 and sum(skipped.values())==3
    assert max(__import__('collections').Counter(next(p for p in paragraphs if p['paragraph_id']==r['paragraph_id'])['page'] for r in accepted).values())==2


def test_raster_image_objects_and_placements_survive(paper,tmp_path):
    with pymupdf.open(ROOT/'tests/fixtures/paper-english.pdf') as source:
        image=source.extract_image(source[1].get_images()[0][0])['image']
    with pymupdf.open(paper) as pdf:
        pdf[1].insert_image((46,637,566,737),stream=image);pdf.saveIncr()
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    after=tmp_path/'marked.pdf';render_layer(paper,after,paragraphs,records,'v1','fixture')
    verify_preserved(paper,after)
    with pymupdf.open(after) as pdf:assert len(pdf[1].get_image_info())==1
    with pymupdf.open(paper) as before,pymupdf.open(after) as marked:
        assert before[1].get_pixmap(clip=(46,637,566,737)).samples==marked[1].get_pixmap(clip=(46,637,566,737)).samples


def test_highlights_only_change_pixels_inside_the_selected_line_boxes(paper,tmp_path):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    after=tmp_path/'marked.pdf';render_layer(paper,after,paragraphs,records,'v1','fixture')
    import numpy as np
    with pymupdf.open(paper) as a,pymupdf.open(after) as b:
        for page, (old,new) in enumerate(zip(a,b),1):
            old_image=old.get_pixmap();new_image=new.get_pixmap()
            pixels=np.frombuffer(old_image.samples,dtype=np.uint8).reshape(old_image.height,old_image.width,3)
            changed=np.any(pixels!=np.frombuffer(new_image.samples,dtype=np.uint8).reshape(pixels.shape),axis=2)
            allowed=np.zeros(changed.shape,dtype=bool)
            for row in records:
                p=next(p for p in paragraphs if p['paragraph_id']==row['paragraph_id'])
                if p['page']!=page:continue
                for box in locate(p,p['text'][row['start']:row['end']])['boxes']:
                    r=(pymupdf.Rect(box)+(-2,-2,2,2)).irect
                    allowed[r.y0:r.y1,r.x0:r.x1]=True
            assert not np.any(changed & ~allowed)


@pytest.fixture(scope='module')
def highlight_base():
    import threading
    from http.server import ThreadingHTTPServer
    from mock_api import Handler
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}/v1'
    server.shutdown()


def config_for(paper,tmp_path,base):
    import uuid
    return {'input':str(paper),'outputDir':str(tmp_path/'output'),'cacheDir':str(tmp_path/'cache'),
        'baseURL':base,'model':'fixture-highlight-'+str(uuid.uuid4()),'apiKey':'fixture-only-key'}


def test_mock_api_selects_valid_spans_and_repeated_calls_use_offset_cache(paper,tmp_path,highlight_base):
    from highlight_jobs import highlights
    from mock_api import Handler
    config=config_for(paper,tmp_path,highlight_base)
    first=highlights(config)
    assert first['highlightCount']==3 and first['requests']==3
    again=highlights(config)
    assert again['highlightCount']==3 and again['requests']==0 and again['cachedBatches']==3
    on_marked=highlights({**config,'input':first['path']})
    assert on_marked['unchanged'] and on_marked['requests']==0
    assert Handler.metrics[config['model']]['calls']==3
    contents=(tmp_path/'cache/highlight-cache.sqlite3').read_bytes()
    for secret in [b'fixture-only-key',highlight_base.encode(),* [g['quote'].encode() for g in GOLD]]:
        assert secret not in contents


def test_partial_ai_failure_preserves_input_and_resumes_completed_batch(paper,tmp_path,highlight_base):
    from highlight_jobs import highlights
    from mock_api import Handler
    import openai
    config=config_for(paper,tmp_path,highlight_base)
    before=paper.read_bytes()
    Handler.controls[config['model']]={'failAfter':1}
    with pytest.raises(openai.AuthenticationError):highlights(config)
    assert paper.read_bytes()==before
    Handler.controls[config['model']]={}
    resumed=highlights(config)
    assert resumed['cachedBatches']==1 and resumed['requests']==2
    assert paper.read_bytes()==before


@pytest.mark.parametrize('changed',['model','baseURL','prompt'])
def test_highlight_cache_is_isolated_by_model_service_and_prompt(paper,tmp_path,highlight_base,changed,monkeypatch):
    import highlight_jobs as jobs
    config=config_for(paper,tmp_path,highlight_base)
    first=jobs.highlights(config)
    other={**config,'input':first['path']}
    if changed=='prompt':monkeypatch.setattr(jobs,'PROMPT_VERSION','explicitly-new-test-prompt')
    else:other[changed]+='-different'
    fresh=jobs.highlights(other)
    assert fresh['requests']==3 and fresh['highlightCount']==3 and fresh['cachedBatches']==0
    with pymupdf.open(first['path']) as a,pymupdf.open(fresh['path']) as b:
        assert all(x.get_pixmap().samples==y.get_pixmap().samples for x,y in zip(a,b))


def test_invalid_model_json_does_not_change_existing_pdf(paper,tmp_path,highlight_base):
    from highlight_jobs import highlights
    config=config_for(paper,tmp_path,highlight_base);config['model']='fixture-highlight-invalid'
    before=paper.read_bytes()
    with pytest.raises(HighlightError):highlights(config)
    assert paper.read_bytes()==before


def staged(paper,tmp_path):
    with pymupdf.open(paper) as pdf:paragraphs=extract(pdf)
    records,_=validate_candidates(paragraphs,rows(paragraphs))
    target=tmp_path/'candidate.pdf';render_layer(paper,target,paragraphs,records,'v1','fixture')
    return {'input':str(paper),'candidatePath':str(target),'sourceFingerprint':fingerprint(paper),
        'installDir':str(tmp_path/'install')}


def test_safe_install_retains_exact_original_backup_and_annotation_coordinates(paper,tmp_path):
    from highlight_install import install,recover
    config=staged(paper,tmp_path);original=paper.read_bytes()
    result=install(config)
    assert Path(result['backupPath']).read_bytes()==original
    assert paper.read_bytes()==Path(config['candidatePath']).read_bytes()
    verify_preserved(result['backupPath'],paper)
    assert recover(config['installDir'])['recoveredTransactions']==0
    assert Path(result['backupPath']).stat().st_mode & 0o777==0o600


def test_changed_or_invalid_candidate_is_not_installed(paper,tmp_path):
    from highlight_install import install
    config=staged(paper,tmp_path);before=paper.read_bytes()
    Path(config['candidatePath']).write_bytes(b'not a PDF')
    with pytest.raises(Exception):install(config)
    assert paper.read_bytes()==before
    config=staged(paper,tmp_path);config['sourceFingerprint']='wrong original'
    with pytest.raises(HighlightError):install(config)
    assert paper.read_bytes()==before


@pytest.mark.parametrize('alias',['same_path','symlink','hardlink'])
def test_original_pdf_is_protected_even_through_file_aliases(paper,tmp_path,highlight_base,alias):
    import os
    from highlight_jobs import highlights
    from highlight_install import install
    config=staged(paper,tmp_path)
    original=paper.read_bytes()
    target=paper
    if alias!='same_path':
        target=tmp_path/'alias.pdf'
        if alias=='symlink':target.symlink_to(paper)
        else:os.link(paper,target)
    config.update(input=str(target),protectedOriginal=str(paper))
    with pytest.raises(HighlightError):install(config)
    api=config_for(target,tmp_path,highlight_base);api['protectedOriginal']=str(paper)
    with pytest.raises(HighlightError):highlights(api)
    assert paper.read_bytes()==original


@pytest.mark.parametrize('point',['before_replace','after_replace'])
def test_killed_install_process_recovers_original_and_retains_backup(paper,tmp_path,point):
    import subprocess
    from highlight_install import recover
    config=staged(paper,tmp_path);before=paper.read_bytes()
    code='''import os,sys,json
sys.path.insert(0,sys.argv[1])
import highlight_install as h
replace=h.os.replace
target=json.loads(sys.argv[2])['input']
def interrupted(source,destination):
 if str(destination)==target:
  if sys.argv[3]=='after_replace':replace(source,destination)
  os._exit(19)
 return replace(source,destination)
h.os.replace=interrupted
h.install(json.loads(sys.argv[2]))
'''
    process=subprocess.run([sys.executable,'-c',code,str(ROOT/'engine'),json.dumps(config),point])
    assert process.returncode==19
    assert recover(config['installDir'])['recoveredTransactions']==1
    assert paper.read_bytes()==before
    assert any(p.read_bytes()==before for p in (tmp_path/'install/backups').glob('*.pdf'))


def test_recovery_does_not_overwrite_external_edits(paper,tmp_path,monkeypatch):
    import highlight_install as h
    config=staged(paper,tmp_path)
    actual_replace=h.os.replace
    def stop(source,target):
        if str(target)==str(paper):raise KeyboardInterrupt
        return actual_replace(source,target)
    monkeypatch.setattr(h.os,'replace',stop)
    with pytest.raises(KeyboardInterrupt):h.install(config)
    paper.write_bytes(b'external file edit must remain')
    with pytest.raises(HighlightError):h.recover(config['installDir'])
    assert paper.read_bytes()==b'external file edit must remain'
