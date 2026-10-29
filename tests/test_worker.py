import importlib.util
from pathlib import Path
import json
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from http.server import ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
sys.path.insert(0,str(ROOT/'engine'))
from mock_api import Handler
spec=importlib.util.spec_from_file_location('worker',ROOT/'engine/worker.py')
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)

@pytest.fixture(scope='module')
def base():
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}/v1'
    server.shutdown()

def test_connection_success(base):
    assert '连接成功' in worker.test_connection({'baseURL':base,'model':'fixture','apiKey':'fixture-only-key'})['message']

@pytest.mark.parametrize('model,code',[('error-401','AUTH'),('error-403','AUTH'),('error-404','NOT_FOUND'),('error-429','RATE_LIMIT'),('error-500','API'),('invalid','RESPONSE'),('empty','RESPONSE'),('redirect','REDIRECT'),('slow','TIMEOUT')])
def test_actionable_errors_without_provider_body(base,model,code):
    with pytest.raises(worker.UserError) as caught:
        worker.test_connection({'baseURL':base,'model':model,'apiKey':'fixture-only-key','timeout':0.2})
    assert caught.value.code==code
    assert 'provider-error-body' not in str(caught.value)
    assert 'fixture-only-key' not in str(caught.value)

def test_subprocess_protocol_and_no_secret_in_errors(base):
    payload={'action':'test','baseURL':base,'model':'error-401','apiKey':'fixture-only-key'}
    process=subprocess.run([sys.executable,str(ROOT/'engine/worker.py'),'--stdio'],input=json.dumps(payload),text=True,capture_output=True)
    assert process.returncode==1
    event=json.loads(process.stdout)
    assert event['code']=='AUTH'
    assert 'fixture-only-key' not in process.stdout+process.stderr
    assert not process.stderr

def test_installed_engine():
    assert worker.check_engine()['version']=='0.6.4'

@pytest.mark.parametrize('value',[0,11,-1,1.5,True,None,'bad'])
def test_concurrency_rejects_invalid_values(value):
    with pytest.raises(worker.UserError) as caught:
        worker.request_concurrency({'concurrency':value})
    assert caught.value.code=='CONFIG'

def test_concurrency_default_and_provider_override():
    assert worker.request_concurrency({})==4
    assert worker.request_concurrency({'concurrency':1})==1
    assert worker.request_concurrency({'concurrency':'10'})==10

def test_global_request_limit_across_multiple_engine_pools(monkeypatch):
    events=[]
    monkeypatch.setattr(worker,'emit',lambda kind,**data:events.append((kind,data)))
    activity=worker.RequestActivity()
    slots=threading.BoundedSemaphore(4)
    def operation():
        time.sleep(0.03)
        return 'translated'
    with ThreadPoolExecutor(max_workers=16) as pool:
        results=list(pool.map(lambda _:worker.limited_request(slots,activity,operation),range(32)))
    assert results==['translated']*32
    assert max(e['activeRequests'] for kind,e in events)==4
    assert activity.snapshot()=={'requests':32,'completedRequests':32,'activeRequests':0,'cachedParagraphs':0}
    with pytest.raises(worker.UserError):worker.limited_request(slots,activity,lambda:'')
    assert activity.snapshot()['activeRequests']==0
    assert worker.limited_request(slots,activity,operation)=='translated'

@pytest.mark.parametrize('value',['https://host.example?api_key=x','https://x:y@host.example','http://remote.example','file:///tmp/x'])
def test_invalid_url(value):
    with pytest.raises(worker.UserError):worker.normalize_base(value)

def test_http_authorization_is_endpoint_specific():
    base='http://example.internal:8317/v1'
    assert worker.normalize_base(base+'/chat/completions',base)==base
    for other in ['http://other.internal:8317/v1','http://example.internal:8317/other','http://example.internal:8318/v1']:
        with pytest.raises(worker.UserError):worker.normalize_base(other,base)

# v0.1.4: deterministic, local quality rules and isolated refresh caches.
import pymupdf
from quality import QualityAudit, check_pdf, save_report, track_babeldoc
from quality import formula_fragments, math_signature

PROSE = ('The translation system should preserve the original document and its figures. '
         'We evaluate whether the paragraphs in this scientific paper are translated into the requested language. ')
ZH = '科研论文的翻译应保留原始文档、图片与数学公式。此处用确定性的中文段落检验软件的完整性与排版，不评价真实模型的语言准确性。'


def make_quality_pdf(path, text=ZH, *, pages=1, width=400, formula=True, images=True, overlap=False, outside=False):
    from PIL import Image
    import io
    pdf = pymupdf.open()
    for _ in range(pages):
        page = pdf.new_page(width=width, height=500)
        if text:
            page.insert_textbox((25, 30, width-25, 145), text, fontname='china-s' if text==ZH else 'helv', fontsize=10)
        if formula:
            page.insert_text((80, 175), 'E = mc2', fontsize=12)
        if images:
            buffer=io.BytesIO();Image.new('RGB',(30,30),'blue').save(buffer,format='PNG')
            xref=page.insert_image((30,200,80,250),stream=buffer.getvalue())
            page.insert_image((120,200,170,250),xref=xref)
        if overlap:
            for dy, line in enumerate(['Overlapping alpha paragraph', 'Overlapping beta paragraph', 'Overlapping gamma paragraph']):
                page.insert_text((30,310+dy),line,fontsize=12)
        if outside:
            page.insert_text((width-30,360),'Text visibly outside page boundary',fontsize=12)
    pdf.save(path);pdf.close()
    return path


def codes(report):
    return {issue['code'] for issue in report['issues']}


def test_quality_normal_pdf_passes_with_formula_and_reused_image(tmp_path):
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=make_quality_pdf(tmp_path/'translated.pdf')
    report=check_pdf(src,dst)
    assert report['status']=='pass',report
    assert report['pages']==1
    with pymupdf.open(src) as pdf:
        assert len(pdf[0].get_image_info())==2
        assert len({i[0] for i in pdf[0].get_images()})==1


def test_quality_unchanged_body_is_only_suspect(tmp_path):
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    report=check_pdf(src,src)
    assert report['status']=='suspect'
    assert 'pdf_unchanged_english_body' in codes(report)


def test_quality_tracker_failures_empty_and_truncated_without_text_in_report(tmp_path):
    audit=QualityAudit()
    rows=[{'input':PROSE,'output':PROSE,'llm_translate_trackers':[{'has_error':True}]},
          {'input':PROSE,'output':'   '}, {'input':PROSE*5,'output':'简短'},
          {'input':PROSE,'output':None,'llm_translate_trackers':[{'has_error':True}]}]
    audit.tracking_data({'page':[{'paragraph':rows}]})
    report=audit.report()
    assert {'failed_retained_english','empty_translation','possible_truncation','paragraph_fallback'}<=codes(report)
    assert report['status']=='suspect'
    path=Path(save_report(report,tmp_path))
    assert PROSE not in path.read_text() and ZH not in path.read_text()
    assert path.stat().st_mode & 0o777==0o600


def test_quality_recovered_fallback_and_technical_terms_are_not_false_failures(tmp_path):
    technical='OpenAI BabelDOC PyMuPDF CNN RNN SVM API PDF DOI LLM GPU CPU '+ ' '.join(['AlphaEarth','XGBoost','SHAP']*20)
    audit=QualityAudit()
    rows=[{'input':technical,'output':technical}, {'input':'E = mc2; x y z DOI 10.1234/example','output':''},
          {'input':PROSE,'output':ZH,'llm_translate_trackers':[{'has_error':True},{'has_error':False}]}]
    audit.tracking_data({'page':[{'paragraph':rows}]})
    assert audit.report()['status']=='pass'
    src=make_quality_pdf(tmp_path/'source.pdf',technical)
    assert check_pdf(src,src)['status']=='pass'


def test_quality_references_continue_onto_next_page():
    audit=QualityAudit()
    audit.tracking_data({'page':[{'paragraph':[{'input':'References','output':'References'}]},
                                 {'paragraph':[{'input':PROSE,'output':PROSE}]}]})
    assert audit.report()['status']=='pass'


def test_quality_large_untranslated_body_and_formula_placeholder_loss():
    audit=QualityAudit()
    rows=[{'input':PROSE,'output':PROSE} for _ in range(3)]
    rows.append({'input':PROSE,'output':ZH,'placeholders':[{'type':'formula','placeholder':'{v1}'}]})
    audit.tracking_data({'page':[{'paragraph':rows}]})
    assert {'large_untranslated_body','possible_formula_loss'}<=codes(audit.report())


@pytest.mark.parametrize('kind',['pages','dimensions','corrupt'])
def test_quality_blocks_incompatible_pdf_structure(tmp_path,kind):
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=tmp_path/'translated.pdf'
    if kind=='corrupt':dst.write_bytes(b'not a PDF')
    else:make_quality_pdf(dst,pages=2 if kind=='pages' else 1,width=450 if kind=='dimensions' else 400)
    report=check_pdf(src,dst)
    assert report['status']=='structural_error'
    assert {'page_count_mismatch','page_geometry_mismatch','pdf_unreadable'} & codes(report)


def test_quality_bounds_overlap_missing_text_formula_and_images(tmp_path):
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=make_quality_pdf(tmp_path/'translated.pdf',overlap=True,outside=True,formula=False,images=False)
    report=check_pdf(src,dst)
    assert report['status']=='suspect'
    assert {'text_outside_page','severe_text_overlap','possible_image_loss','possible_formula_loss'}<=codes(report),report
    empty=make_quality_pdf(tmp_path/'empty.pdf',text='',formula=False,images=False)
    assert 'page_text_missing' in codes(check_pdf(src,empty))


def test_quality_image_encoding_and_object_count_do_not_determine_loss(tmp_path):
    from PIL import Image
    import io
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=make_quality_pdf(tmp_path/'translated.pdf',images=False)
    with pymupdf.open(dst) as pdf:
        for rect,color in [((30,200,80,250),'blue'),((120,200,170,250),'navy')]:
            buffer=io.BytesIO();Image.new('RGB',(30,30),color).save(buffer,format='JPEG')
            pdf[0].insert_image(rect,stream=buffer.getvalue())
        pdf.saveIncr()
    report=check_pdf(src,dst)
    assert 'possible_image_loss' not in codes(report)
    assert report['status']=='pass'


def test_refresh_cache_isolation_preserves_legacy_and_other_papers():
    from babeldoc.translator.translator import OpenAITranslator
    import uuid
    base='http://127.0.0.1:9/v1'
    ordinary=OpenAITranslator('en','zh','fixture-quality-cache',base_url=base,api_key='fixture-only-key')
    refresh=OpenAITranslator('en','zh','fixture-quality-cache',base_url=base,api_key='fixture-only-key')
    try:
        worker.configure_cache(ordinary,base)
        text='fixture-'+str(uuid.uuid4())
        other=text+'-other-paper'
        ordinary.cache.set(text,'old translation');ordinary.cache.set(other,'other translation')
        worker.configure_cache(refresh,base,str(uuid.uuid4()))
        assert refresh.cache.get(text) is None
        refresh.cache.set(text,'new translation')
        assert refresh.cache.get(text)=='new translation'
        assert ordinary.cache.get(text)=='old translation'
        assert ordinary.cache.get(other)=='other translation'
    finally:
        ordinary.client.close();refresh.client.close()


def test_tracker_wrapper_reads_existing_tracking_then_restores_module(tmp_path):
    from types import SimpleNamespace
    class Translator:
        def __init__(self):
            self.translation_config=SimpleNamespace(get_working_file_path=lambda _:tmp_path/'translate_tracking.json')
        def translate(self,docs):
            (tmp_path/'translate_tracking.json').write_text(json.dumps({'page':[{'paragraph':[{'input':PROSE,'output':''}]}]}))
    high=SimpleNamespace(ILTranslator=Translator,ILTranslatorLLMOnly=Translator)
    audit=QualityAudit()
    with track_babeldoc(high,audit):
        high.ILTranslatorLLMOnly().translate(SimpleNamespace(page=[SimpleNamespace(page_number=3)]))
    assert high.ILTranslatorLLMOnly is Translator
    assert audit.report()['trackingAvailable']
    assert audit.report()['issues'][0]['page']==4
    assert 'empty_translation' in codes(audit.report())

@pytest.mark.parametrize('kind',['corrupt','pages','good'])
def test_worker_quality_gate_before_delivery(tmp_path,monkeypatch,kind):
    from types import SimpleNamespace
    from babeldoc.format.pdf import high_level
    from babeldoc.docvision.base_doclayout import DocLayoutModel
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=tmp_path/'result.pdf'
    if kind=='corrupt':dst.write_bytes(b'broken PDF')
    else:make_quality_pdf(dst,pages=2 if kind=='pages' else 1)
    async def pipeline(config):
        yield {'type':'finish','translate_result':SimpleNamespace(mono_pdf_path=dst)}
    monkeypatch.setattr(high_level,'init',lambda:None)
    monkeypatch.setattr(high_level,'async_translate',pipeline)
    monkeypatch.setattr(DocLayoutModel,'load_available',lambda:object())
    monkeypatch.setattr(worker,'emit',lambda *args,**kwargs:None)
    config={'input':str(src),'outputDir':str(tmp_path/'job'),'baseURL':'http://127.0.0.1:9/v1','model':'fixture'}
    import asyncio
    if kind=='good':
        result=asyncio.run(worker.translate(config))
        # The PDF remains readable, but missing paragraph evidence is disclosed.
        assert result['quality']['status']=='suspect'
        assert 'paragraph_tracking_unavailable' in codes(result['quality'])
    else:
        with pytest.raises(worker.UserError) as caught:
            asyncio.run(worker.translate(config))
        assert caught.value.code=='PDF_STRUCTURE'
    report=json.loads((tmp_path/'job/quality-report.json').read_text())
    assert report['status']==('suspect' if kind=='good' else 'structural_error')


def test_quality_unreadable_page_is_structural_even_when_document_opens(tmp_path,monkeypatch):
    import quality
    src=make_quality_pdf(tmp_path/'source.pdf',PROSE)
    dst=make_quality_pdf(tmp_path/'translated.pdf')
    open_pdf=pymupdf.open
    class BrokenPageDocument:
        def __init__(self,doc):self.doc=doc
        def __getattr__(self,name):return getattr(self.doc,name)
        def __len__(self):return len(self.doc)
        def __enter__(self):return self
        def __exit__(self,*args):self.doc.close()
        def __getitem__(self,index):raise RuntimeError('invalid page object')
    def open_document(path):
        doc=open_pdf(path)
        return BrokenPageDocument(doc) if Path(path)==dst else doc
    monkeypatch.setattr(quality.pymupdf,'open',open_document)
    report=check_pdf(src,dst)
    assert report['status']=='structural_error'
    assert 'page_unreadable' in codes(report)


def equation_pdf(path, text, *, split=False, chinese=False):
    with pymupdf.open() as pdf:
        page=pdf.new_page(width=500,height=300)
        if split:
            page.insert_text((35,70),'The loss function is' if not chinese else '损失函数为',fontname='china-s' if chinese else 'helv',fontsize=11)
            for x,y,value,size in [(160,70,'L',11),(174,70,'=',11),(188,70,'0.5 * (y - yhat)',11),(267,63,'2',7)]:
                page.insert_text((x,y),value,fontsize=size)
        else:
            if chinese and re.search(r'[A-Za-z]',text):
                prefix,formula=re.split(r'(?=[A-Za-z])',text,maxsplit=1)
                page.insert_text((25,70),prefix,fontname='china-s',fontsize=11)
                page.insert_text((25+11*len(prefix),70),formula,fontsize=11)
            else:
                page.insert_text((25,70),text,fontname='china-s' if chinese else 'helv',fontsize=11)
        pdf.save(path)
    return path


@pytest.mark.parametrize('source,target,chinese',[
    ('The loss function is L = 0.5 * (y - yhat)^2.','损失函数为 L = 0.5 * (y - yhat)^2.',True),
    ('E = mc2','E = mc2',False),
    ('E = mc^2','E = mc²',False),
    ('The value is x_i^2 = y + 1.','数值为 x_i² = y + 1.',True),
])
def test_formula_prose_translation_and_typography_are_preserved(tmp_path,source,target,chinese):
    src=equation_pdf(tmp_path/'source.pdf',source)
    dst=equation_pdf(tmp_path/'target.pdf',target,chinese=chinese)
    assert 'possible_formula_loss' not in codes(check_pdf(src,dst))


def test_formula_inline_loss_is_still_reported(tmp_path):
    src=equation_pdf(tmp_path/'source.pdf','The loss function is L = 0.5 * (y - yhat)^2.')
    dst=equation_pdf(tmp_path/'target.pdf','损失函数已经计算。',chinese=True)
    report=check_pdf(src,dst)
    assert report['status']=='suspect'
    assert 'possible_formula_loss' in codes(report)


@pytest.mark.parametrize('source_split,target_split',[(True,False),(False,True),(True,True)])
def test_formula_split_pdf_text_objects_and_superscripts(tmp_path,source_split,target_split):
    src=equation_pdf(tmp_path/'source.pdf','The loss function is L = 0.5 * (y - yhat)^2.',split=source_split)
    dst=equation_pdf(tmp_path/'target.pdf','损失函数为 L = 0.5 * (y - yhat)^2.',split=target_split,chinese=True)
    report=check_pdf(src,dst)
    assert 'possible_formula_loss' not in codes(report),report
    empty=equation_pdf(tmp_path/'empty.pdf','损失函数已经计算。',chinese=True)
    assert 'possible_formula_loss' in codes(check_pdf(src,empty))


def test_formula_symbols_scripts_ambiguous_fonts_and_tracking():
    line=lambda text:[(pymupdf.Rect(20,20,450,35),text)]
    assert formula_fragments(line('The value is α_i² = β − 1.'))==[(math_signature('α_i²'),math_signature('α_i² = β − 1'))]
    for text in ['The value is unknown_function(x) = difficult_expression(x).','(cid:23) = y + 1','x = (y + 1','https://example.test/?a=b','x == y']:
        assert formula_fragments(line(text))==[]
    for output,expected in [('损失为 {v1}。',False),('损失已经计算。',True),(None,False)]:
        audit=QualityAudit()
        audit.tracking_data({'page':[{'paragraph':[{'input':'The loss is {v1}.','output':output,
            'placeholders':[{'type':'formula','placeholder':'{v1}','formula_chars':'L = 0.5 * (y - yhat)^2'}]}]}]})
        assert ('possible_formula_loss' in codes(audit.report()))==expected


def test_retained_placeholder_does_not_hide_formula_missing_from_final_pdf(tmp_path):
    audit=QualityAudit()
    audit.tracking_data({'page':[{'paragraph':[{'input':'The loss is {v1}.','output':'损失为 {v1}。',
        'placeholders':[{'type':'formula','placeholder':'{v1}','formula_chars':'E = mc2'}]}]}]})
    src=equation_pdf(tmp_path/'source.pdf','E = mc2')
    dst=equation_pdf(tmp_path/'target.pdf','损失已经计算。',chinese=True)
    assert 'possible_formula_loss' in codes(check_pdf(src,dst,audit))


def refresh_config(tmp_path,base):
    source=tmp_path/'source.pdf'
    source.write_bytes(b'original PDF bytes')
    return {'input':str(source),'sourceID':'1/FIXTURE','taskDir':str(tmp_path/'tasks'),
            'baseURL':base,'model':'fixture-resume','apiKey':'fixture-only-key'}


def test_refresh_pending_survives_reload_and_completion_starts_new_task(tmp_path,base):
    config=refresh_config(tmp_path,base)
    first=worker.refresh_task('prepareRefresh',config)
    assert first['resumed'] is False
    # Each CLI invocation creates a fresh process, as Zotero does on retry.
    command=[sys.executable,str(ROOT/'engine/worker.py'),'--stdio']
    retried=subprocess.run(command,input=json.dumps({**config,'action':'prepareRefresh'}),text=True,capture_output=True,check=True)
    resumed=json.loads(retried.stdout)
    assert resumed['resumed'] and resumed['refreshToken']==first['refreshToken']
    worker.refresh_task('completeRefresh',{**config,**first})
    worker.refresh_task('completeRefresh',{**config,**first}) # idempotent acknowledgement
    fresh=worker.refresh_task('prepareRefresh',config)
    assert not fresh['resumed'] and fresh['refreshToken']!=first['refreshToken']
    with pytest.raises(worker.UserError):worker.refresh_task('validateRefresh',{**config,**first})
    data=(tmp_path/'tasks/refresh-tasks.sqlite3').read_bytes()
    for sensitive in [b'fixture-only-key',b'original PDF bytes',base.encode(),b'fixture-resume',b'FIXTURE']:
        assert sensitive not in data
    assert (tmp_path/'tasks/refresh-tasks.sqlite3').stat().st_mode & 0o777==0o600


@pytest.mark.parametrize('changed',['model','baseURL','apiKey','sourceID','input'])
def test_refresh_identity_rejects_changed_pdf_or_api_configuration(tmp_path,base,changed):
    import os
    config=refresh_config(tmp_path,base)
    first=worker.refresh_task('prepareRefresh',config)
    other=dict(config)
    if changed=='input':
        source=Path(config['input']);info=source.stat()
        source.write_bytes(b'replaced PDF bytes')
        os.utime(source,ns=(info.st_atime_ns,info.st_mtime_ns))
        assert source.stat().st_size==info.st_size
    else:other[changed]+='-changed'
    second=worker.refresh_task('prepareRefresh',other)
    assert second['refreshToken']!=first['refreshToken'] and not second['resumed']
    with pytest.raises(worker.UserError):worker.refresh_task('validateRefresh',{**other,**first})
    if changed!='input':
        assert worker.refresh_task('prepareRefresh',config)['refreshToken']==first['refreshToken']


def test_refresh_atomic_transaction_recovers_after_abrupt_worker_exit(tmp_path,base):
    config=refresh_config(tmp_path,base)
    first=worker.refresh_task('prepareRefresh',config)
    code='import os,sys;sys.path.insert(0,sys.argv[1]);from refresh_tasks import database\nwith database(sys.argv[2]) as db:\n db.execute("UPDATE tasks SET status=\'completed\'");os._exit(17)'
    stopped=subprocess.run([sys.executable,'-c',code,str(ROOT/'engine'),config['taskDir']])
    assert stopped.returncode==17
    resumed=worker.refresh_task('prepareRefresh',config)
    assert resumed['resumed'] and resumed['refreshToken']==first['refreshToken']


def test_refresh_mock_actual_cache_hits_after_partial_failure_and_new_calls_after_completion(tmp_path,base):
    import openai
    import uuid
    from babeldoc.translator.translator import OpenAITranslator
    config=refresh_config(tmp_path,base)
    config['model']='fixture-resume-'+str(uuid.uuid4())
    first=worker.refresh_task('prepareRefresh',config)
    texts=[f'The scientific paragraph number {i} should be translated into Chinese.' for i in range(5)]
    def translator(token=None):
        tr=OpenAITranslator('en','zh',config['model'],base_url=base,api_key=config['apiKey'])
        tr.client.max_retries=0
        worker.configure_cache(tr,base,token)
        return tr
    ordinary=translator()
    ordinary.cache.set(texts[0],'old translation');ordinary.cache.set('another paper','other translation')
    tr=translator(first['refreshToken'])
    Handler.controls[config['model']]={'failAfter':2}
    try:
        assert tr.translate(texts[0]);assert tr.translate(texts[1])
        with pytest.raises(openai.AuthenticationError):tr.translate(texts[2])
    finally:tr.client.close()
    assert Handler.metrics[config['model']]['calls']==3
    resumed=worker.refresh_task('prepareRefresh',config)
    assert resumed['refreshToken']==first['refreshToken'] and resumed['resumed']
    Handler.controls[config['model']]={}
    tr=translator(resumed['refreshToken'])
    try:
        for text in texts:assert tr.translate(text)
        assert tr.translate_cache_call_count==2
        assert Handler.metrics[config['model']]['calls']==6 # retry: 2 hits + 3 requests
    finally:tr.client.close()
    worker.refresh_task('completeRefresh',{**config,**resumed})
    fresh=worker.refresh_task('prepareRefresh',config)
    tr=translator(fresh['refreshToken'])
    try:
        for text in texts:assert tr.translate(text)
        assert tr.translate_cache_call_count==0
        assert Handler.metrics[config['model']]['calls']==11 # new task: all 5 requests
        assert ordinary.cache.get(texts[0])=='old translation'
        assert ordinary.cache.get('another paper')=='other translation'
    finally:tr.client.close();ordinary.client.close()
