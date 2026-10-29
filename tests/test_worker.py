import importlib.util
from pathlib import Path
import json
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

@pytest.mark.parametrize('value',[0,9,-1,1.5,True,None,'bad'])
def test_concurrency_rejects_invalid_values(value):
    with pytest.raises(worker.UserError) as caught:
        worker.request_concurrency({'concurrency':value})
    assert caught.value.code=='CONFIG'

def test_concurrency_default_and_provider_override():
    assert worker.request_concurrency({})==4
    assert worker.request_concurrency({'concurrency':1})==1
    assert worker.request_concurrency({'concurrency':'8'})==8

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
