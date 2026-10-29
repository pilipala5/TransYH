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
