"""Protocol regressions against a loopback fixture; no real model calls."""
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import httpx
import openai
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
sys.path.insert(0, str(ROOT / 'tests'))
from api_client import APIResponseError, APITranslatorMixin, create_text
from mock_api import Handler
import worker


@pytest.fixture
def service():
    calls = []

    class RecordingHandler(Handler):
        def handle_request(self, data, model):
            calls.append((self.path, data))
            if model.startswith('stream-'):
                events = [{'type': 'response.output_text.delta', 'delta': 'partial-provider-body-must-not-leak'}]
                terminal = model.removeprefix('stream-')
                if terminal != 'disconnected':
                    events.append({'type': terminal})
                self.reply_events(events)
                return
            super().handle_request(data, model)

    server = ThreadingHTTPServer(('127.0.0.1', 0), RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize('mode,suffix', [(None, '/responses'), ('responses', '/responses'),
                                        ('chat_completions', '/chat/completions')])
def test_connection_uses_selected_endpoint_without_changing_base(service, mode, suffix):
    base, calls = service
    config = {'baseURL': base + '/responses', 'model': 'fixture', 'apiKey': 'fixture-only-key'}
    if mode:
        config['apiMode'] = mode
    result = worker.test_connection(config)
    assert '连接成功' in result['message']
    assert len(calls) == 1 and calls[0][0] == '/v1' + suffix
    body = calls[0][1]
    if suffix == '/responses':
        assert body['store'] is False and body['stream'] is True
        assert 'messages' not in body and body['input'][0]['content'] == 'Reply with OK.'


def test_both_babeldoc_translation_methods_use_responses_and_count_usage(service):
    from babeldoc.translator.translator import OpenAITranslator

    class Translator(APITranslatorMixin, OpenAITranslator):
        pass

    base, calls = service
    translator = Translator('en', 'zh', 'fixture', base_url=base, api_key='fixture-only-key',
                            send_temperature=False)
    translator.client.max_retries = 0
    try:
        assert translator.do_translate('Introduction') == '引言'
        assert translator.do_llm_translate('Reply with OK.') == 'OK'
        assert translator.do_llm_translate(None) is None
        assert len(calls) == 2 and all(path == '/v1/responses' for path, _ in calls)
        assert calls[0][1]['input'] == translator.prompt('Introduction')
        assert calls[1][1]['input'] == [{'role': 'user', 'content': 'Reply with OK.'}]
        assert all('max_tokens' not in body and 'max_output_tokens' not in body for _, body in calls)
        assert translator.token_count.value == 40
        assert translator.prompt_token_count.value == 20
        assert translator.completion_token_count.value == 20
        assert translator.cache_hit_prompt_token_count.value == 8
    finally:
        translator.client.close()


@pytest.mark.parametrize('status', [401, 403, 404, 429, 503])
def test_responses_errors_never_fall_back_to_chat_completions(service, status):
    base, calls = service
    with pytest.raises(worker.UserError):
        worker.test_connection({'baseURL': base, 'model': f'error-{status}', 'apiKey': 'fixture-only-key'})
    assert len(calls) == 1 and calls[0][0] == '/v1/responses'


@pytest.mark.parametrize('terminal', ['error', 'response.failed', 'response.incomplete', 'disconnected'])
def test_partial_stream_is_never_accepted_as_a_translation(service, terminal):
    base, calls = service
    with openai.OpenAI(base_url=base, api_key='fixture-only-key', max_retries=0,
                      http_client=httpx.Client(timeout=2, follow_redirects=False)) as client:
        with pytest.raises(APIResponseError) as caught:
            create_text(client, model='stream-' + terminal, messages=[{'role': 'user', 'content': 'Translate.'}])
    assert 'partial-provider-body' not in str(caught.value)
    assert len(calls) == 1 and calls[0][0] == '/v1/responses'


def test_invalid_api_mode_is_rejected_before_any_request(service):
    base, calls = service
    with pytest.raises(worker.UserError) as caught:
        worker.test_connection({'baseURL': base, 'model': 'fixture', 'apiMode': 'typo'})
    assert caught.value.code == 'CONFIG' and calls == []


@pytest.mark.parametrize('mode,suffix', [('responses', '/responses'),
                                      ('chat_completions', '/chat/completions')])
def test_contextual_highlights_use_shared_adapter_in_both_protocols(service, tmp_path, mode, suffix):
    import json
    from highlight_fixtures import create_recall, RECALL_CASES
    from highlight_jobs import highlights
    from highlight_pdf import verify_preserved

    base, calls = service
    source = create_recall(tmp_path / 'recall.pdf')
    original = source.read_bytes()
    model = 'fixture-recall-protocol-' + mode
    Handler.controls[model] = {'requireContext': True}
    config = {'baseURL': base, 'model': model, 'apiKey': 'fixture-only-key', 'apiMode': mode,
              'input': str(source), 'outputDir': str(tmp_path / 'output'),
              'cacheDir': str(tmp_path / 'cache'), 'concurrency': 10}
    try:
        result = highlights(config)
        assert result['highlightCount'] == 4 and result['requests'] == 2
        assert source.read_bytes() == original
        verify_preserved(source, result['path'])
        assert len(calls) == 2 and all(path == '/v1' + suffix for path, _ in calls)
        sent = []
        for _, body in calls:
            messages = body['input' if mode == 'responses' else 'messages']
            payload = json.loads(messages[-1]['content'])
            assert payload['paper_context']['title'] == '异质变化的互补表示研究'
            assert payload['paper_context']['abstract'] and payload['paper_context']['sections']
            assert all('section_title' in p for p in payload['paragraphs'])
            sent.extend(p['text'] for p in payload['paragraphs'])
            if mode == 'responses':
                assert body['stream'] is True and body['store'] is False
        assert all(any(case['quote'] in text for text in sent) for case in RECALL_CASES)
        assert result['diagnostics']['ai']['returnedCandidates'] == 5
        assert result['diagnostics']['selection']['rejected'] == {'density': 1}
        full = highlights({**config, 'input': result['path'], 'highlightDensity': 'full'})
        assert full['requests'] == 0 and full['highlightCount'] == 5 and len(calls) == 2
    finally:
        Handler.controls.pop(model, None)
