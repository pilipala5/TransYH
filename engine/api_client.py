"""One text API path for translation, highlights and connection checks."""
from __future__ import annotations

from dataclasses import dataclass


class APIResponseError(ValueError):
    """Safe local error; never includes provider bodies or request content."""


def api_mode(config):
    mode = config.get("apiMode", "responses")
    if mode not in ("responses", "chat_completions"):
        raise ValueError("请选择 Responses 或 Chat Completions 接口。")
    return mode


@dataclass(frozen=True)
class TextResult:
    text: str
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


def create_text(client, *, model, messages, mode="responses", temperature=None,
                max_tokens=None, json_mode=False, extra_body=None, extra_headers=None):
    options = {"model": model}
    if temperature is not None:
        options["temperature"] = temperature
    if extra_body:
        options["extra_body"] = extra_body
    if extra_headers:
        options["extra_headers"] = extra_headers
    if mode == "responses":
        # Each paragraph/batch is independent. Streaming follows the same
        # gateway path as Codex and keeps long generations connected.
        options.update(input=messages, stream=True, store=False)
        if json_mode:
            options["text"] = {"format": {"type": "json_object"}}
        # Chat's max_tokens excludes reasoning. Do not carry its 2048-token
        # cap into Responses, where it could truncate the translated batch.
        response = None
        with client.responses.create(**options) as events:
            for event in events:
                if event.type in ("error", "response.failed", "response.incomplete"):
                    raise APIResponseError("Responses 请求失败或输出未完成，已完成的缓存保留，请稍后重试。")
                if event.type == "response.completed":
                    response = event.response
                    break
        if response is None or response.status != "completed" or response.error:
            raise APIResponseError("Responses 未返回完整结果，已完成的缓存保留，请稍后重试。")
        content = response.output_text
        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        details = getattr(usage, "input_tokens_details", None)
    elif mode == "chat_completions":
        options["messages"] = messages
        if max_tokens is not None:
            options["max_tokens"] = max_tokens
        if json_mode:
            options["response_format"] = {"type": "json_object"}
        response = client.chat.completions.create(**options)
        choice = response.choices[0]
        if choice.finish_reason != "stop":
            raise APIResponseError("Chat Completions 未返回完整结果，请检查模型后重试。")
        content = choice.message.content
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
    else:
        raise ValueError("请选择 Responses 或 Chat Completions 接口。")
    if not isinstance(content, str) or not content.strip():
        raise APIResponseError("API 返回空内容，请检查模型和接口设置。")
    return TextResult(content.strip(), getattr(usage, "total_tokens", 0) or 0,
                      input_tokens, output_tokens,
                      getattr(details, "cached_tokens", 0) or 0)


class APITranslatorMixin:
    """Keep BabelDOC's prompts, placeholders and paragraph caches unchanged."""
    api_mode = "responses"

    def _api_text(self, messages, *, max_tokens=None, json_mode=False):
        headers = ({"X-DashScope-DataInspection": '{"input": "disable", "output": "disable"}'}
                   if self.send_dashscope_header else None)
        result = create_text(self.client, model=self.model, messages=messages, mode=self.api_mode,
                             temperature=self.options["temperature"] if self.send_temperature else None,
                             max_tokens=max_tokens, json_mode=json_mode,
                             extra_body=self.extra_body, extra_headers=headers)
        for counter, value in ((self.token_count, result.total_tokens),
                               (self.prompt_token_count, result.input_tokens),
                               (self.completion_token_count, result.output_tokens),
                               (self.cache_hit_prompt_token_count, result.cached_tokens)):
            if value:
                counter.inc(value)
        return result.text

    def do_translate(self, text, rate_limit_params=None):
        return self._api_text(self.prompt(text))

    def do_llm_translate(self, text, rate_limit_params=None):
        if text is None:
            return None
        return self._api_text([{"role": "user", "content": text}], max_tokens=2048,
                              json_mode=self.enable_json_mode_if_requested
                              and bool((rate_limit_params or {}).get("request_json_mode")))
