export type Language = "en" | "zh";
export type ViewState = {
  pageIndex: number; scale: number | string; top?: number; left?: number;
  scrollMode?: number; spreadMode?: number;
};

/** Accept a service root, version root, or full Chat Completions URL. */
export function canonicalBaseURL(value: string): string {
  const input = value.trim().replace(/\/+$/, "");
  let url: URL;
  try { url = new URL(input); } catch { throw new Error("API Base URL 格式不正确，请填写完整的 http(s) 地址。"); }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error("API 地址只支持 http(s)，且不能包含账号、密码、查询参数或锚点。");
  }
  url.pathname = url.pathname.replace(/\/(?:chat\/completions)\/?$/, "").replace(/\/+$/, "");
  if (!url.pathname || url.pathname === "/") url.pathname = "/v1";
  return url.toString().replace(/\/+$/, "");
}

export function normalizeBaseURL(value: string, allowedHTTPBase = ""): string {
  const base = canonicalBaseURL(value);
  const url = new URL(base);
  if (url.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
    && base !== allowedHTTPBase) {
    throw new Error("此 HTTP 地址尚未授权，请勾选“允许此地址使用 HTTP”后保存。");
  }
  return base;
}

export function apiError(status: number): string {
  if (status === 401 || status === 403) return `API 鉴权失败（${status}），请检查 API Key 和模型访问权限。`;
  if (status === 429) return "API 请求受到限流或额度不足（429），请稍后重试并检查服务商额度。";
  if (status === 404) return "API 接口或模型不存在（404），请检查 Base URL 和 Model。";
  if (status >= 500) return `API 服务暂时不可用（${status}），请稍后重试。`;
  return `API 请求失败（HTTP ${status}）。`;
}

export function clampState(state: ViewState, pages: number): ViewState {
  return { ...state, pageIndex: Math.min(Math.max(0, state.pageIndex || 0), Math.max(0, pages - 1)) };
}

export function sourceStamp(size: number, modified: number): string {
  return `${size}:${Math.trunc(modified)}`;
}
