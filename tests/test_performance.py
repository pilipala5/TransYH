"""Numerical accounting and privacy tests. No real API speed estimates."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import openai
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from api_client import APIResponseError, create_text
from performance import Performance, distribution, request_summary, union_seconds


def test_overlapping_request_times_and_percentiles():
    rows = [{"start_s": 0., "end_s": 4., "outcome": "success"},
            {"start_s": 1., "end_s": 3., "outcome": "failure", "http_status": 429},
            {"start_s": 4., "end_s": 5., "outcome": "success"}]
    stats = request_summary(rows, 6.)
    assert stats["attempts"] == 3
    assert stats["peak_concurrency"] == 2
    assert stats["active_request_seconds"] == 7
    assert stats["api_busy_wall_s"] == 5
    assert stats["http_429"] == 1
    assert stats["latency"]["p50_s"] == 2
    assert stats["latency"]["p95_s"] == pytest.approx(3.8)
    assert union_seconds([(1, 3), (2, 5)]) == 4
    assert distribution([])["mean_s"] is None


def test_running_request_and_cache_only_report_are_distinct(tmp_path):
    perf = Performance(tmp_path)
    perf.count("translation_cache_hits", 20)
    perf.phase("ai_translation")
    report = perf.snapshot()
    assert report["api"]["attempts"] == 0
    assert report["api"]["tokens_reported"] == {}
    assert report["counters"]["translation_cache_hits"] == 20
    trace = perf.begin_request("translation", "responses")
    perf.event(trace, "response.created")
    report = perf.snapshot()
    assert report["api"]["incomplete_attempts"] == 1
    assert report["active_requests"][0]["since_last_event_s"] >= 0
    perf.end_request(trace, RuntimeError("secret-provider-body"))
    perf.finish("failed")
    payload = (tmp_path / "performance.json").read_text()
    assert "secret-provider-body" not in payload
    assert (tmp_path / "performance.md").is_file()
    assert (tmp_path / "performance.json").stat().st_mode & 0o777 == 0o600
    assert sum(row["seconds"] for row in json.loads(payload)["phases"]) == pytest.approx(perf.finished_s)


@pytest.mark.parametrize("terminal", ["response.completed", "response.incomplete", "disconnect", "429"])
def test_instrumented_transport_counts_terminal_events_usage_and_errors(tmp_path, terminal):
    def respond(request):
        if terminal == "429":
            return httpx.Response(429, json={"error": {"message": "secret-provider-body", "type": "rate_limit"}})
        events = [{"type": "response.created"}, {"type": "response.output_text.delta", "delta": "private-model-text"}]
        if terminal != "disconnect":
            events.append({"type": terminal, "response": {
                "id": "fixture", "object": "response", "created_at": 1, "model": "fixture",
                "status": "completed" if terminal == "response.completed" else "incomplete", "error": None,
                "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "private-model-text", "annotations": []}]}],
                "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19,
                          "input_tokens_details": {"cached_tokens": 4}, "output_tokens_details": {"reasoning_tokens": 2}}}})
        content = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, content=content, headers={"Content-Type": "text/event-stream"})

    perf = Performance(tmp_path)
    with openai.OpenAI(base_url="http://fixture.invalid/v1", api_key="private-api-key", max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(respond))) as client:
        if terminal == "response.completed":
            assert create_text(client, model="fixture", messages=[{"role": "user", "content": "private-paper-text"}],
                               performance=perf).text == "private-model-text"
        else:
            with pytest.raises((APIResponseError, openai.RateLimitError)):
                create_text(client, model="fixture", messages=[{"role": "user", "content": "private-paper-text"}], performance=perf)
    perf.finish("completed" if terminal == "response.completed" else "failed")
    report = json.loads((tmp_path / "performance.json").read_text())
    stats = report["api"]
    assert stats["attempts"] == 1
    assert stats["successes"] == int(terminal == "response.completed")
    assert stats["failures"] == int(terminal != "response.completed")
    if terminal == "response.completed":
        assert stats["tokens_reported"] == {"input": 12, "output": 7, "total": 19, "cached_input": 4, "reasoning_output": 2}
        assert stats["first_event"]["count"] == stats["completed_event"]["count"] == 1
    serialized = json.dumps(report)
    for private in ("private-api-key", "private-model-text", "private-paper-text", "secret-provider-body", "fixture.invalid"):
        assert private not in serialized


def test_scoped_babeldoc_hooks_restore_after_failure():
    from babeldoc.format.pdf import high_level
    from babeldoc.translator import translator as translator_module
    from babeldoc.utils.priority_thread_pool_executor import PriorityThreadPoolExecutor
    from performance import observe_babeldoc

    cache = SimpleNamespace(get=lambda key: "cached" if key == "hit" else None, set=lambda key, value: None)
    translator = SimpleNamespace(cache=cache)
    originals = (cache.get, translator_module._translate_rate_limiter.wait,
                 PriorityThreadPoolExecutor.submit, high_level.ILTranslatorLLMOnly.translate)
    perf = Performance()
    with pytest.raises(RuntimeError):
        with observe_babeldoc(perf, high_level, translator):
            assert cache.get("hit") == "cached"
            assert cache.get("miss") is None
            with PriorityThreadPoolExecutor(max_workers=1) as pool:
                assert pool.submit(lambda: 42, priority=1).result() == 42
            raise RuntimeError("fixture")
    assert (cache.get, translator_module._translate_rate_limiter.wait,
            PriorityThreadPoolExecutor.submit, high_level.ILTranslatorLLMOnly.translate) == originals
    assert perf.counters["translation_cache_hits"] == 1
    assert perf.counters["translation_cache_misses"] == 1
    assert perf.snapshot()["waits"]["translation_executor_queue"]["count"] == 1


def test_pending_wait_is_visible_and_worker_error_retains_safe_report(tmp_path):
    import subprocess
    perf = Performance()
    waiting = perf.begin_wait("request_semaphore")
    assert perf.snapshot()["active_waits"][0]["kind"] == "request_semaphore"
    perf.end_wait(waiting)
    assert perf.snapshot()["active_waits"] == []
    payload = {"action": "translate", "apiKey": "private-key", "model": "fixture",
               "baseURL": "https://fixture.invalid/v1", "input": str(tmp_path / "private-paper.pdf"),
               "outputDir": str(tmp_path / "output")}
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "engine/worker.py")],
                            input=json.dumps(payload) + "\n", text=True, capture_output=True)
    assert result.returncode == 1
    report = (tmp_path / "output/performance.json").read_text()
    assert json.loads(report)["status"] == "failed"
    assert json.loads(report)["api"]["attempts"] == 0
    for value in ("private-key", "private-paper.pdf", "fixture.invalid"):
        assert value not in report + result.stdout
