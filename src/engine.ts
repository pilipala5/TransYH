import { normalizeBaseURL } from "./core";
import { Credentials, pref } from "./storage";

export type EngineEvent = { type: string; message?: string; progress?: number; path?: string; code?: string; version?: string; apiKey?: string;
  language?: "zh" | "unknown"; pages?: number;
  refreshToken?: string; taskVersion?: string; resumed?: boolean;
  unchanged?: boolean; installed?: boolean; highlightCount?: number; cachedBatches?: number;
  sourceFingerprint?: string; backupPath?: string; recoveredTransactions?: number;
  quality?: { status: "pass" | "suspect" | "structural_error"; issues: { code: string; page?: number; count: number }[] }; qualityReport?: string;
  requests?: number; completedRequests?: number; activeRequests?: number; cachedParagraphs?: number };
export class WorkerRun {
  private process: any;
  cancelled = false;
  async cancel(): Promise<void> { this.cancelled = true; try { if (this.process) await this.process.kill(1000); } catch { /* process already exited */ } }
  async execute(python: string, script: string, payload: any, update: (event: EngineEvent) => void): Promise<EngineEvent> {
    const { Subprocess } = ChromeUtils.importESModule("resource://gre/modules/Subprocess.sys.mjs");
    try {
      this.process = await Subprocess.call({ command: python, arguments: [script, "--stdio"],
        environmentAppend: true, environment: { PYTHONUNBUFFERED: "1", PYTHONUTF8: "1" }, stderr: "pipe" });
    } catch { throw new Error("无法启动本地 Python，请在 TransYH 设置中检查 Python 路径并安装 BabelDOC 引擎。"); }
    if (this.cancelled) { await this.process.kill(0); throw new Error("翻译已取消。"); }
    // Secrets cross an anonymous OS pipe. They never enter arguments, preferences, or a config file.
    await this.process.stdin.write(JSON.stringify(payload) + "\n");
    await this.process.stdin.close();
    // Drain stderr to avoid a full pipe blocking the child. Never log its content.
    const drain = (async () => { try { while (await this.process.stderr.readString()) { /* discard */ } } catch { /* exited */ } })();
    let buffer = "";
    let result: EngineEvent | undefined;
    try {
      while (true) {
        const chunk = await this.process.stdout.readString();
        if (!chunk) break;
        buffer += chunk;
        let end: number;
        while ((end = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, end); buffer = buffer.slice(end + 1);
          if (!line.trim()) continue;
          let event: EngineEvent;
          try { event = JSON.parse(line); } catch { continue; }
          if (event.type === "done" || event.type === "error") result = event;
          update(event);
        }
      }
      await this.process.wait(); await drain;
    } finally { if (this.cancelled) await this.process.kill(0); }
    if (this.cancelled) throw new Error("翻译已取消。已完成的段落缓存可在重试时复用。");
    if (result?.type === "error") throw new Error(result.message || "本地引擎执行失败。");
    if (!result) throw new Error("本地引擎意外退出，请检查 BabelDOC 安装或重新运行安装脚本。");
    return result;
  }
}

export class Engine {
  private script = "";
  constructor(private rootURI: string, private credentials: Credentials) {}
  async prepare(): Promise<void> {
    const dir = PathUtils.join(Zotero.DataDirectory.dir, "transyh", "engine-0.2.4");
    await IOUtils.makeDirectory(dir, { permissions: 0o700, ignoreExisting: true });
    this.script = PathUtils.join(dir, "worker.py");
    for (const name of ["worker.py", "api_client.py", "quality.py", "refresh_tasks.py", "highlight_pdf.py", "highlight_jobs.py", "highlight_install.py", "macos_keychain.py"]) {
      await IOUtils.writeUTF8(PathUtils.join(dir, name), Zotero.File.getContentsFromURL(this.rootURI + "engine/" + name), { permissions: 0o600 });
    }
  }
  async python(): Promise<string> {
    const configured = pref("pythonPath");
    if (configured) return configured;
    const home = Services.dirsvc.get("Home", Ci.nsIFile).path;
    const candidates = Zotero.isWin ? [PathUtils.join(home, "AppData", "Local", "TransYH", "engine", "Scripts", "python.exe")]
      : Zotero.isMac ? [PathUtils.join(home, "Library", "Application Support", "TransYH", "engine", "bin", "python")]
      : [PathUtils.join(home, ".local", "share", "TransYH", "engine", "bin", "python")];
    for (const path of candidates) if (await IOUtils.exists(path)) return path;
    throw new Error("未找到本地翻译引擎。请先运行安装包旁的 install-engine.command（macOS）或 install-engine.ps1（Windows），然后重试。");
  }
  config(): any {
    const allowedHTTPBase = pref("httpAllowedBase");
    const baseURL = normalizeBaseURL(pref("baseURL"), allowedHTTPBase);
    const model = pref("model").trim();
    if (!model) throw new Error("请先在 TransYH 设置中填写 Model。");
    const apiMode = pref("apiMode", "responses");
    if (!["responses", "chat_completions"].includes(apiMode)) throw new Error("请选择有效的 API 接口。");
    return { baseURL, model, apiMode, apiKey: this.credentials.get(baseURL), allowedHTTPBase, timeout: 120,
      concurrency: Number(pref("concurrency", "4")) };
  }
  async run(action: string, extra: any = {}, update = (_event: EngineEvent) => {}, run = new WorkerRun()): Promise<EngineEvent> {
    const config = ["check", "inspect", "readCredential", "installHighlights", "recoverHighlights"].includes(action) ? {} : this.config();
    return run.execute(await this.python(), this.script, { action, ...config, ...extra }, update);
  }
}
