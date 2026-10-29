import { ProgressWindowHelper } from "zotero-plugin-toolkit";
import type { EngineEvent } from "./engine";

export class TranslationProgress {
  private popup?: ProgressWindowHelper;
  private timer: any;
  private startedAt = Date.now();
  private message = "正在准备本地翻译引擎…";
  private percent = 0;
  private requests = 0;
  private completedRequests = 0;
  private activeRequests = 0;
  private cachedParagraphs = 0;

  show(): void {
    // Recreate a dismissed popup from current state; native progress windows
    // cannot reliably reattach their old ItemProgress objects after closing.
    this.popup?.close();
    this.popup = new ProgressWindowHelper("TransYH · 翻译全文", {
      window: Zotero.getMainWindow(), closeOnClick: false, closeTime: -1,
    }).createLine({ text: this.message, progress: this.percent })
      .createLine({ text: this.details(), progress: 100 }).show(-1);
    this.popup.win.addDescription('可在条目右键菜单中选择“查看翻译进度”或“取消全文翻译”。');
    if (!this.timer) this.timer = setInterval(() => this.render(), 1000);
  }

  update(event: EngineEvent): void {
    if (event.type === "progress") {
      if (event.message) this.message = event.message;
      if (typeof event.progress === "number") this.percent = event.progress;
    }
    if (typeof event.requests === "number") this.requests = event.requests;
    if (typeof event.completedRequests === "number") this.completedRequests = event.completedRequests;
    if (typeof event.activeRequests === "number") this.activeRequests = event.activeRequests;
    if (typeof event.cachedParagraphs === "number") this.cachedParagraphs = event.cachedParagraphs;
    this.render();
  }

  snapshot() {
    return { message: this.message, progress: this.percent, elapsedSeconds: Math.floor((Date.now() - this.startedAt) / 1000),
      requests: this.requests, completedRequests: this.completedRequests, activeRequests: this.activeRequests,
      cachedParagraphs: this.cachedParagraphs };
  }

  private details(): string {
    const elapsed = this.snapshot().elapsedSeconds;
    const time = elapsed < 60 ? `${elapsed} 秒` : `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`;
    let text = `已耗时 ${time}`;
    if (this.requests) text += ` · API 已完成 ${this.completedRequests} 次`;
    if (this.activeRequests) text += ` · 等待模型 ${this.activeRequests} 个请求`;
    if (this.cachedParagraphs) text += ` · 缓存命中 ${this.cachedParagraphs} 次`;
    return text;
  }

  private render(): void {
    this.popup?.changeLine({ text: this.message, progress: this.percent });
    this.popup?.changeLine({ idx: 1, text: this.details() });
  }

  finish(suspect = false): void {
    clearInterval(this.timer); this.timer = undefined;
    this.message = suspect ? "译文已保存，存在疑似问题，请核对。质量报告保存在本地。"
      : "翻译完成，中文 PDF 已保存为附件。"; this.percent = 100;
    this.render();
    this.popup?.changeLine({ icon: "chrome://zotero/skin/16/universal/tick.svg", progress: 100 });
    this.popup?.startCloseTimer(suspect ? 12000 : 5000);
  }

  close(): void { clearInterval(this.timer); this.timer = undefined; this.popup?.close(); }
}
