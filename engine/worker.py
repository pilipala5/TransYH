"""TransYH worker. One JSON request on stdin; safe NDJSON events on stdout.

No credentials on disk, in argv, or in errors. BabelDOC stays a local library.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from urllib import parse

PROTOCOL = sys.stdout
PROTOCOL_LOCK = threading.Lock()


class UserError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def emit(kind: str, **data):
    with PROTOCOL_LOCK:
        PROTOCOL.write(json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n")
        PROTOCOL.flush()


def request_concurrency(config: dict) -> int:
    value = config.get("concurrency", 4)
    try:
        result = int(value)
        if isinstance(value, bool) or float(value) != result or not 1 <= result <= 8:
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise UserError("CONFIG", "并发请求数应为 1–8 的整数。") from None


class RequestActivity:
    """Only counts/timing cross the progress pipe; never request content."""
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.requests = self.completed = self.active = 0
        self.translator = None

    def snapshot(self):
        with self.lock:
            return {"requests": self.requests, "completedRequests": self.completed,
                    "activeRequests": self.active,
                    "cachedParagraphs": getattr(self.translator, "translate_cache_call_count", 0)}

    def begin(self):
        with self.lock:
            self.requests += 1
            self.active += 1
        emit("activity", **self.snapshot())

    def end(self, success):
        with self.lock:
            self.active -= 1
            self.completed += int(success)
        emit("activity", **self.snapshot())

    def heartbeat(self):
        while not self.stop_event.wait(2):
            emit("activity", **self.snapshot())


def limited_request(slots, activity, operation):
    # BabelDOC uses several priority pools. Enforce one API-wide limit rather
    # than assuming pool_max_workers caps their combined in-flight requests.
    with slots:
        success = False
        activity.begin()
        try:
            result = operation()
            if not result or not result.strip():
                raise UserError("RESPONSE", "API 返回空译文，请检查模型。")
            success = True
            return result
        finally:
            activity.end(success)


def stage_message(event):
    labels = {
        "Parse PDF and Create Intermediate Representation": "解析 PDF 文字与页面",
        "Parse Page Layout": "识别页面版式", "Parse Paragraphs": "识别段落",
        "Parse Formulas and Styles": "保护公式与文字样式", "Parse Table": "识别表格",
        "Translate Paragraphs": "翻译段落", "Typesetting": "排版中文页面",
        "Add Fonts": "嵌入字体", "Generate drawing instructions": "生成中文 PDF",
        "Remove Char Descent": "调整文字位置", "DetectScannedFile": "检查 PDF 文字",
    }
    label = labels.get(event.get("stage"), "处理 PDF")
    return f"{label}（{event.get('stage_current', 0)} / {event.get('stage_total', 0)}）"


def normalize_base(value: str, allowed_http_base: str = "") -> str:
    parts = parse.urlsplit(value.strip().rstrip("/"))
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise UserError("CONFIG", "API Base URL 格式不正确。")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    base = parse.urlunsplit((parts.scheme, parts.netloc, path or "/v1", "", ""))
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1") and base != allowed_http_base:
        raise UserError("CONFIG", "此 HTTP 地址尚未授权，请在设置中允许当前地址使用 HTTP。")
    return base


def status_error(status: int) -> UserError:
    if 300 <= status < 400:
        return UserError("REDIRECT", "API 返回重定向，请将 Base URL 改为服务商的最终 API 地址。")
    if status in (401, 403):
        return UserError("AUTH", f"API 鉴权失败（{status}），请检查 API Key 和模型权限。")
    if status == 429:
        return UserError("RATE_LIMIT", "API 限流或额度不足（429），请稍后重试并检查服务商额度。")
    if status == 404:
        return UserError("NOT_FOUND", "API 接口或模型不存在（404），请检查 Base URL 和 Model。")
    return UserError("API", f"API 请求失败（HTTP {status}），请检查服务商状态后重试。")


def test_connection(config: dict):
    import httpx
    import openai
    base = normalize_base(config.get("baseURL", ""), config.get("allowedHTTPBase", ""))
    model = config.get("model", "").strip()
    if not model:
        raise UserError("CONFIG", "请填写 Model。")
    try:
        # Use the same SDK and request shape as actual translations. Some
        # gateways treat a separate urllib/explicit-stream=False client differently.
        with openai.OpenAI(base_url=base,api_key=config.get("apiKey") or "local-no-key",max_retries=0,
            http_client=httpx.Client(timeout=min(float(config.get("timeout",120)),30),follow_redirects=False)) as client:
            response=client.chat.completions.create(model=model,messages=[{"role":"user","content":"Reply with OK."}])
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError
    except openai.APIStatusError as exc:
        raise status_error(exc.status_code) from None
    except openai.APITimeoutError:
        raise UserError("TIMEOUT", "API 连接超时，请检查网络或稍后重试。") from None
    except openai.APIConnectionError:
        raise UserError("NETWORK", "无法连接 API，请检查地址、网络和 TLS 证书。") from None
    except (ValueError, KeyError, IndexError, TypeError, AttributeError, openai.APIResponseValidationError):
        raise UserError("RESPONSE", "API 返回格式不符合 Chat Completions 协议，或返回了空内容。") from None
    return {"message": "连接成功，模型已返回有效响应。此测试会产生一次最小 API 调用。"}


def check_engine():
    try:
        version = importlib.metadata.version("babeldoc")
        import pymupdf
        from babeldoc.format.pdf import high_level
    except ImportError:
        raise UserError("ENGINE_MISSING", "未安装 BabelDOC 引擎或依赖不完整，请运行本地引擎安装脚本。") from None
    if version != "0.6.4":
        raise UserError("ENGINE_VERSION", f"检测到 BabelDOC {version}；当前 TransYH 需要 0.6.4，请运行安装脚本。")
    return {"version": version, "message": f"本地 BabelDOC {version} 可用。模型和字体会在首次翻译时自动下载。"}


def configure_cache(translator, base, refresh_token=None):
    translator.add_cache_impact_parameters("base_url", base)
    translator.add_cache_impact_parameters("transyh_protocol", "1")
    if refresh_token:
        try:
            token = str(uuid.UUID(refresh_token))
        except (ValueError, TypeError, AttributeError):
            raise UserError("CONFIG", "重新翻译标识无效，请重试。") from None
        # One isolated run, including retries/fallback, shares a namespace.
        # Ordinary v0.1.3 caches and other papers are neither read nor cleared.
        translator.add_cache_impact_parameters("transyh_refresh", token)


def refresh_task(action, config):
    from refresh_tasks import prepare, complete, validate
    try:
        base = normalize_base(config.get("baseURL", ""), config.get("allowedHTTPBase", ""))
        if not config.get("model", "").strip():
            raise ValueError
        return {"prepareRefresh": prepare, "completeRefresh": complete, "validateRefresh": validate}[action](config, base)
    except Exception:
        raise UserError("TASK_STATE", "本地重译任务记录无法读写，或原 PDF / API 配置已变化。已有译文和缓存保留，请检查后重试。") from None


async def translate(config: dict):
    concurrency = request_concurrency(config)
    check_engine()
    import httpx
    import openai
    import pymupdf
    from babeldoc.docvision.base_doclayout import DocLayoutModel
    from babeldoc.format.pdf import high_level
    from babeldoc.format.pdf.translation_config import TranslationConfig, WatermarkOutputMode
    from babeldoc.translator.translator import OpenAITranslator, set_translate_rate_limiter
    from quality import QualityAudit, check_pdf, save_report, track_babeldoc

    base = normalize_base(config.get("baseURL", ""), config.get("allowedHTTPBase", ""))
    model = config.get("model", "").strip()
    if not model:
        raise UserError("CONFIG", "请填写 Model。")
    source = Path(config["input"]).resolve()
    output = Path(config["outputDir"]).resolve()
    if not source.is_file():
        raise UserError("INPUT", "原始 PDF 文件不存在。")
    refresh_identity = refresh_task("validateRefresh", config) if config.get("refreshToken") else None
    with pymupdf.open(source) as pdf:
        if pdf.needs_pass:
            raise UserError("PASSWORD", "请先提供已解密的 PDF。")
        page_count = len(pdf)
        if not page_count:
            raise UserError("INPUT", "PDF 不包含可阅读的页面。")
        if not any(page.get_text().strip() for page in pdf):
            raise UserError("SCANNED", "该 PDF 没有可提取文字。第一版不包含 OCR，请先在外部完成 OCR。")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    problems: list[UserError] = []
    activity = RequestActivity()
    request_slots = threading.BoundedSemaphore(concurrency)

    class BoundedTranslator(OpenAITranslator):
        name = "transyh-openai"

        def _request(self, fn, *args):
            if problems:
                raise problems[0]
            for attempt in range(3):
                try:
                    def operation():
                        if problems:
                            raise problems[0]
                        return fn(self, *args)
                    return limited_request(request_slots, activity, operation)
                except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError, openai.APITimeoutError) as exc:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                        continue
                    issue = (UserError("TIMEOUT", "API 请求超时，已完成的段落缓存可供重试复用。")
                             if isinstance(exc, openai.APITimeoutError) else
                             status_error(exc.status_code) if getattr(exc, "status_code", None) else
                             UserError("NETWORK", "API 连接失败，请检查网络后重试。"))
                except openai.APIStatusError as exc:
                    issue = status_error(exc.status_code)
                except UserError as exc:
                    issue = exc
                except Exception:
                    issue = UserError("RESPONSE", "API 响应无法解析，请检查模型和接口兼容性。")
                problems.append(issue)
                raise issue from None

        def do_translate(self, text, rate_limit_params=None):
            return self._request(OpenAITranslator.do_translate.__wrapped__, text, rate_limit_params)

        def do_llm_translate(self, text, rate_limit_params=None):
            if text is None:
                return None  # BabelDOC probes LLM support with None.
            return self._request(OpenAITranslator.do_llm_translate.__wrapped__, text, rate_limit_params)

    emit("progress", progress=0, message="加载开源版式模型和中文字体；首次使用可能需要下载…")
    high_level.init()
    translator = BoundedTranslator("en", "zh", model, base_url=base, api_key=config.get("apiKey") or "local-no-key",
                                  send_temperature=False, enable_json_mode_if_requested=False)
    # Bound SDK retries/timeouts and disable redirects (including redirects of secrets).
    translator.client.close()
    translator.client = openai.OpenAI(base_url=base, api_key=config.get("apiKey") or "local-no-key", max_retries=0,
        http_client=httpx.Client(timeout=float(config.get("timeout", 120)), follow_redirects=False))
    configure_cache(translator, base, config.get("refreshToken"))
    # Concurrency changes scheduling only. Keep the existing cache identity so
    # upgrades/retries reuse completed paragraphs without paying for them again.
    activity.translator = translator
    set_translate_rate_limiter(min(concurrency, 2))
    layout_model = await asyncio.to_thread(DocLayoutModel.load_available)
    cfg = TranslationConfig(translator=translator, input_file=source, lang_in="en", lang_out="zh",
        doc_layout_model=layout_model, output_dir=output, no_dual=True, no_mono=False,
        watermark_output_mode=WatermarkOutputMode.NoWatermark, use_rich_pbar=False,
        qps=min(concurrency, 2), pool_max_workers=concurrency, auto_extract_glossary=False, save_auto_extracted_glossary=False,
        skip_scanned_detection=True, report_interval=0.2)
    result = None
    audit = QualityAudit()
    heartbeat = threading.Thread(target=activity.heartbeat, daemon=True)
    heartbeat.start()
    try:
        with track_babeldoc(high_level, audit):
            async for event in high_level.async_translate(cfg):
                if event["type"] in ("progress_start", "progress_update", "progress_end"):
                    emit("progress", progress=round(float(event.get("overall_progress", 0)), 1),
                         message=stage_message(event), **activity.snapshot())
                elif event["type"] == "finish":
                    result = event["translate_result"]
                    # Stop at finish: 0.6.4 can otherwise wait on an empty queue.
                    break
                elif event["type"] == "error":
                    if problems:
                        raise problems[0]
                    raise UserError("LAYOUT", "BabelDOC 无法处理该 PDF 的结构或排版，请检查文件后重试。")
        path = Path(result.mono_pdf_path) if result and result.mono_pdf_path else None
        if not path or not path.is_file():
            raise UserError("OUTPUT", "BabelDOC 未生成中文 PDF。")
        emit("progress", progress=99, message="检查翻译完整性与 PDF 排版…", **activity.snapshot())
        quality = check_pdf(source, path, audit)
        if not audit.tracking:
            audit.add("paragraph_tracking_unavailable")
            quality = audit.report()
        report_path = save_report(quality, output)
        if quality["status"] == "structural_error":
            raise UserError("PDF_STRUCTURE", "译文 PDF 损坏、页数或页面尺寸不匹配，未导入；已有译文保留。详见本地质量报告。")
        if problems:
            raise problems[0]
        if refresh_identity is not None and refresh_task("validateRefresh", config) != refresh_identity:
            raise UserError("INPUT", "翻译期间原 PDF 已发生变化，未导入；已有译文保留。")
        return {"path": str(path), "message": "中文 PDF 已生成。", "pages": page_count,
                "cachedParagraphs": translator.translate_cache_call_count,
                "quality": quality, "qualityReport": report_path}
    finally:
        activity.stop_event.set()
        heartbeat.join(timeout=3)
        translator.client.close()


def main():
    # Third-party loggers can include provider error bodies. Suppress them, along
    # with accidental prints; stdout is exclusively the structured safe protocol.
    logging.disable(logging.CRITICAL)
    config = json.loads(sys.stdin.readline())
    with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        action = config.get("action")
        if action == "check":
            result = check_engine()
        elif action == "readCredential":
            from macos_keychain import get_api_key
            result = {"apiKey": get_api_key(config["baseURL"])}
        elif action == "test":
            result = test_connection(config)
        elif action == "translate":
            result = asyncio.run(translate(config))
        elif action in ("prepareRefresh", "completeRefresh"):
            result = refresh_task(action, config)
        else:
            raise UserError("PROTOCOL", "未知引擎操作。")
    emit("done", **result)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        emit("error", code="CANCELLED", message="翻译已取消。")
        sys.exit(2)
    except UserError as exc:
        emit("error", code=exc.code, message=str(exc))
        sys.exit(1)
    except Exception:
        # Do not expose exception strings: upstream errors may contain secrets.
        emit("error", code="ENGINE", message="本地引擎执行失败，请检查依赖版本、模型下载网络和 PDF 文件。")
        sys.exit(1)
