"""Local numerical diagnostics. Never accept prompts, credentials or PDF text."""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time


PHASES = {
    "setup": "任务准备",
    "pdf_initialization": "PDF 初始化与依赖导入",
    "asset_initialization": "字体及模型资源初始化",
    "layout_model_loading": "版式模型加载",
    "pdf_parsing_layout": "PDF 解析与版式识别",
    "ai_translation": "AI 翻译",
    "pdf_typesetting_save": "PDF 排版与保存",
    "quality_check": "翻译质量检查",
    "highlight_preparation": "标注文字提取与上下文准备",
    "ai_highlights": "AI 重点识别与缓存",
    "highlight_selection": "候选核对与筛选",
    "pdf_highlight_write": "PDF 高亮生成与核验",
    "highlight_install": "PDF 高亮备份与原子提交",
    "cleanup": "任务收尾",
}


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0, "mean_s": None, "p50_s": None, "p95_s": None, "max_s": None}

    def percentile(fraction):
        index = (len(values) - 1) * fraction
        lower = int(index)
        upper = min(lower + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (index - lower)

    return {"count": len(values), "mean_s": sum(values) / len(values),
            "p50_s": percentile(.5), "p95_s": percentile(.95), "max_s": values[-1]}


def union_seconds(intervals):
    end = 0.0
    total = 0.0
    for start, finish in sorted(intervals):
        total += max(0.0, finish - max(start, end))
        end = max(end, finish)
    return total


def request_summary(rows, elapsed):
    completed = [row for row in rows if "end_s" in row]
    durations = [row["end_s"] - row["start_s"] for row in completed]
    intervals = [(row["start_s"], row.get("end_s", elapsed)) for row in rows]
    events = [(start, 1) for start, _ in intervals] + [(end, -1) for _, end in intervals]
    active = peak = 0
    for _, change in sorted(events):
        active += change
        peak = max(peak, active)
    span = max((end for _, end in intervals), default=0) - min((start for start, _ in intervals), default=0)
    tokens = Counter()
    for row in rows:
        tokens.update(row.get("tokens", {}))
    return {
        "attempts": len(rows), "successes": sum(row.get("outcome") == "success" for row in rows),
        "failures": sum(row.get("outcome") == "failure" for row in rows),
        "incomplete_attempts": len(rows) - len(completed),
        "http_429": sum(row.get("http_status") == 429 for row in rows),
        "latency": distribution(durations),
        "successful_latency": distribution([row["end_s"] - row["start_s"] for row in completed if row["outcome"] == "success"]),
        "first_event": distribution([row["first_event_s"] - row["start_s"] for row in rows if "first_event_s" in row]),
        "first_text_delta": distribution([row["first_text_s"] - row["start_s"] for row in rows if "first_text_s" in row]),
        "completed_event": distribution([row["completed_event_s"] - row["start_s"] for row in rows if "completed_event_s" in row]),
        "peak_concurrency": peak,
        "active_request_seconds": sum(end - start for start, end in intervals),
        "api_busy_wall_s": union_seconds(intervals),
        "request_window_s": span,
        "attempts_per_request_window_second": len(rows) / span if span else None,
        "successes_per_total_second": sum(row.get("outcome") == "success" for row in rows) / elapsed if elapsed else None,
        "tokens_reported": dict(tokens),
        "attempts_with_usage": sum("tokens" in row for row in rows),
    }


class Performance:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else None
        self.started = time.perf_counter()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.lock = threading.RLock()
        self.phase_name = "setup"
        self.phase_start = 0.0
        self.phases = []
        self.requests = []
        self.waits = []
        self.counters = Counter({name: 0 for name in (
            "translation_logical_calls", "translation_retries", "translation_cache_hits", "translation_cache_misses",
            "highlight_batches", "highlight_cache_hits", "highlight_cache_misses", "highlight_existing_layer_hits",
            "highlight_failed_batches", "report_write_errors")})
        self.settings = {}
        self.stage_starts = {}
        self.babel_stages = []
        self.stop = threading.Event()
        self.thread = None
        self.status = "running"
        self.finished_s = None

    def now(self):
        return time.perf_counter() - self.started

    def phase(self, name):
        if name not in PHASES:
            raise ValueError("Unknown performance phase")
        with self.lock:
            now = self.now()
            self.phases.append({"phase": self.phase_name, "start_s": self.phase_start, "end_s": now})
            self.phase_name, self.phase_start = name, now

    def count(self, name, value=1):
        # Names are internal call-site constants, values are numerical only.
        with self.lock:
            self.counters[name] += int(value)

    def wait(self, kind, start):
        with self.lock:
            self.waits.append({"kind": kind, "start_s": start, "end_s": self.now()})

    def begin_wait(self, kind):
        with self.lock:
            row = {"kind": kind, "start_s": self.now()}
            self.waits.append(row)
            return row

    def end_wait(self, row):
        with self.lock:
            row["end_s"] = self.now()

    def begin_request(self, category, mode):
        with self.lock:
            row = {"id": len(self.requests) + 1, "category": category, "api_mode": mode,
                   "start_s": self.now(), "events": 0, "max_event_gap_s": 0.0}
            self.requests.append(row)
            return row

    def event(self, row, kind):
        with self.lock:
            now = self.now()
            row.setdefault("first_event_s", now)
            row["max_event_gap_s"] = max(row["max_event_gap_s"], now - row.get("last_event_s", row["start_s"]))
            row["last_event_s"] = now
            row["events"] += 1
            if kind == "response.output_text.delta":
                row.setdefault("first_text_s", now)
            if kind == "response.completed":
                row["completed_event_s"] = now
            if kind in ("response.completed", "response.failed", "response.incomplete", "error"):
                row["terminal_event"] = kind

    def usage(self, row, usage, mode):
        if usage is None:
            return
        inputs = "input_tokens" if mode == "responses" else "prompt_tokens"
        outputs = "output_tokens" if mode == "responses" else "completion_tokens"
        tokens = {"input": getattr(usage, inputs, 0) or 0,
                  "output": getattr(usage, outputs, 0) or 0,
                  "total": getattr(usage, "total_tokens", 0) or 0,
                  "cached_input": getattr(getattr(usage, inputs + "_details", None), "cached_tokens", 0) or 0,
                  "reasoning_output": getattr(getattr(usage, outputs + "_details", None), "reasoning_tokens", 0) or 0}
        with self.lock:
            row["tokens"] = {key: int(value) for key, value in tokens.items() if isinstance(value, (int, float))}

    def end_request(self, row, error=None):
        with self.lock:
            row["end_s"] = self.now()
            row["outcome"] = "failure" if error else "success"
            status = getattr(error, "status_code", None)
            if isinstance(status, int):
                row["http_status"] = status
            if error:
                # Exception messages and provider error fields may contain text/secrets.
                row["error_kind"] = "timeout" if "Timeout" in type(error).__name__ else "http" if status else "connection_or_response"

    def babel_event(self, event):
        names = {
            "Parse PDF and Create Intermediate Representation": "parse_pdf",
            "Parse Page Layout": "page_layout", "Parse Paragraphs": "paragraphs",
            "Parse Formulas and Styles": "formulas_styles", "Parse Table": "tables",
            "Translate Paragraphs": "translation", "Typesetting": "typesetting",
            "Add Fonts": "fonts", "Generate drawing instructions": "drawing",
            "Remove Char Descent": "char_descent", "Save PDF": "save_pdf",
        }
        name = names.get(event.get("stage"))
        if name is None:
            return
        with self.lock:
            key = (name, event.get("part_index"))
            if event["type"] == "progress_start":
                self.stage_starts[key] = self.now()
            elif event["type"] == "progress_end" and key in self.stage_starts:
                self.babel_stages.append({"stage": name, "start_s": self.stage_starts.pop(key),
                                          "end_s": self.now(), "items": int(event.get("stage_total", 0))})

    def snapshot(self):
        with self.lock:
            elapsed = self.finished_s if self.finished_s is not None else self.now()
            rows = deepcopy(self.requests)
            phases = [*deepcopy(self.phases), {"phase": self.phase_name, "start_s": self.phase_start, "end_s": elapsed}]
            waits = deepcopy(self.waits)
            result = {"schema": 1, "status": self.status, "started_at_utc": self.started_at,
                      "elapsed_s": elapsed, "settings": dict(self.settings), "counters": dict(self.counters),
                      "phase_intervals": phases, "requests": rows, "wait_intervals": waits,
                      "babel_stages_event_receipt_time": deepcopy(self.babel_stages)}
        totals = Counter()
        for period in phases:
            totals[period["phase"]] += period["end_s"] - period["start_s"]
        result["phases"] = [{"phase": name, "seconds": seconds, "percent": 100 * seconds / elapsed}
                            for name, seconds in totals.most_common()]
        result["api"] = request_summary(rows, elapsed)
        result["api_by_category"] = {name: request_summary([row for row in rows if row["category"] == name], elapsed)
                                     for name in ("translation", "highlights")}
        api_intervals = [(row["start_s"], row.get("end_s", elapsed)) for row in rows]
        result["waits"] = {}
        result["active_waits"] = [{"kind": row["kind"], "age_s": elapsed - row["start_s"]}
                                  for row in waits if "end_s" not in row]
        for kind in sorted({row["kind"] for row in waits}):
            intervals = [(row["start_s"], row.get("end_s", elapsed)) for row in waits if row["kind"] == kind]
            result["waits"][kind] = {**distribution([end - start for start, end in intervals]),
                                      "sum_s": sum(end - start for start, end in intervals),
                                      "union_wall_s": union_seconds(intervals),
                                      "without_active_api_s": union_seconds(intervals + api_intervals) - union_seconds(api_intervals)}
        result["active_requests"] = [{"id": row["id"], "age_s": elapsed - row["start_s"],
                                      "since_last_event_s": elapsed - row.get("last_event_s", row["start_s"])}
                                     for row in rows if "end_s" not in row]
        return result

    def write(self, final=False):
        if self.directory is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            report = self.snapshot()
            contents = {"performance.json": json.dumps(report, ensure_ascii=False, indent=2)}
            if final:
                contents["performance.md"] = markdown(report)
            for name, content in contents.items():
                target = self.directory / name
                temporary = target.with_suffix(target.suffix + ".tmp")
                with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as stream:
                    stream.write(content)
                os.replace(temporary, target)
        except OSError:
            self.count("report_write_errors")

    def start_checkpoints(self):
        if self.directory is None:
            return

        def checkpoint():
            while not self.stop.wait(5):
                self.write()

        self.write()
        self.thread = threading.Thread(target=checkpoint, daemon=True)
        self.thread.start()

    def finish(self, status):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=2)
        with self.lock:
            self.status = status
            self.finished_s = self.now()
        self.write(final=True)


def markdown(report):
    lines = ["# TransYH 性能记录", "", f"任务状态 `{report['status']}`，总耗时 {report['elapsed_s']:.3f} 秒。", "",
             "阶段为互斥墙钟时间。API 累计时长、线程等待及 BabelDOC 子阶段存在重叠。", "",
             "| 阶段 | 实测秒数 | 占总时间 |", "| --- | ---: | ---: |"]
    for row in report["phases"]:
        lines.append(f"| {PHASES[row['phase']]} | {row['seconds']:.3f} | {row['percent']:.2f}% |")
    lines.extend(["", "## API 请求", ""])
    for name, stats in report["api_by_category"].items():
        latency = stats["latency"]
        lines.append(f"- `{name}` 共 {stats['attempts']} 次，成功 {stats['successes']} 次，失败 {stats['failures']} 次，峰值并发 {stats['peak_concurrency']}。")
        if latency["count"]:
            lines.append(f"  平均 {latency['mean_s']:.3f} 秒，P50 {latency['p50_s']:.3f} 秒，P95 {latency['p95_s']:.3f} 秒。")
        lines.append(f"  收到用量的请求 {stats['attempts_with_usage']} 次，Token 汇总 `{json.dumps(stats['tokens_reported'])}`。")
    lines.extend(["", "## 计数", "", "```json", json.dumps(report["counters"], ensure_ascii=False, indent=2), "```", "",
                  "JSON 保留逐请求时序、首事件、首文本、完成事件、吞吐量、QPS 等待、信号量等待和队列等待。", "",
                  "缓存复用数量与真实 API 请求分别统计。未收到 usage 的请求用量未知。", "",
                  "服务端排队与模型推理的细分耗时需要服务端证据。客户端首事件时间无法直接区分两者。", ""])
    return "\n".join(lines)


@contextmanager
def observe_babeldoc(performance, high_level, translator):
    """Scoped hooks for the pinned BabelDOC worker process. Restore every hook."""
    from babeldoc.translator import translator as translator_module
    from babeldoc.utils.priority_thread_pool_executor import PriorityThreadPoolExecutor

    patches = []

    def patch(owner, name, replacement):
        original = getattr(owner, name)
        patches.append((owner, name, original))
        setattr(owner, name, replacement(original))

    def measured_wait(original):
        def call(*args, **kwargs):
            waiting = performance.begin_wait("qps_limiter")
            try:
                return original(*args, **kwargs)
            finally:
                performance.end_wait(waiting)
        return call

    def measured_cache_write(original):
        def call(*args, **kwargs):
            start = performance.now()
            try:
                return original(*args, **kwargs)
            finally:
                performance.wait("translation_cache_write", start)
        return call

    def measured_cache(original):
        def call(*args, **kwargs):
            start = performance.now()
            try:
                result = original(*args, **kwargs)
                performance.count("translation_cache_hits" if result is not None else "translation_cache_misses")
                return result
            finally:
                performance.wait("translation_cache_read", start)
        return call

    def measured_submit(original):
        def call(pool, fn, *args, **kwargs):
            waiting = performance.begin_wait("translation_executor_queue")

            def execute(*values, **options):
                performance.end_wait(waiting)
                return fn(*values, **options)

            try:
                return original(pool, execute, *args, **kwargs)
            except BaseException:
                performance.end_wait(waiting)
                raise
        return call

    def measured_translation(original):
        def call(*args, **kwargs):
            performance.phase("ai_translation")
            try:
                return original(*args, **kwargs)
            finally:
                if hasattr(args[0], "fallback_count"):
                    performance.count("babel_fallback_paragraphs", args[0].fallback_count)
                performance.phase("pdf_typesetting_save")
        return call

    try:
        patch(translator_module._translate_rate_limiter, "wait", measured_wait)
        patch(translator.cache, "get", measured_cache)
        patch(translator.cache, "set", measured_cache_write)
        patch(PriorityThreadPoolExecutor, "submit", measured_submit)
        patch(high_level.ILTranslatorLLMOnly, "translate", measured_translation)
        patch(high_level.ILTranslator, "translate", measured_translation)
        yield
    finally:
        for owner, name, original in reversed(patches):
            setattr(owner, name, original)
