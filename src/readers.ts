import { NativePane, createPane, originalPane, until } from "./reader-compat";
import { Store, originalFor, translatedFor } from "./storage";
import type { Language, ViewState } from "./core";

export class ReadingSession {
  public source: any;
  public host: NativePane;
  public other?: NativePane;
  public language: Language;
  private hostLanguage: Language;
  private switching?: Promise<void>;
  private disposed = false;
  private observers: any[] = [];
  private controls: HTMLElement[] = [];
  private saveTimer: any;
  private cleanupTimer: any;
  constructor(public reader: any, private store: Store, private translate: (item: any) => Promise<any>, private report: (e: any) => void) {
    const item = Zotero.Items.get(reader.itemID);
    this.source = originalFor(item);
    this.hostLanguage = this.source.id === item.id ? "en" : "zh";
    this.language = this.hostLanguage;
    this.host = originalPane(reader);
  }
  get active(): NativePane { return this.language === this.hostLanguage ? this.host : this.other!; }
  async init(): Promise<void> {
    await this.host.ready();
    this.addControls(this.host);
    const saved = this.store.get(this.source);
    if (saved) {
      if (saved.language !== this.language && await translatedFor(this.source)) await this.switchTo(saved.language, saved.state);
      else if (saved.language === this.language) await this.host.restore(saved.state);
    }
    this.saveTimer = setInterval(() => this.save(), 1000);
    this.cleanupTimer = setInterval(() => { if (!this.reader._iframe?.isConnected) void this.dispose(); }, 1500);
  }
  switchTo(language: Language, restore?: ViewState): Promise<void> {
    if (this.switching) return this.switching;
    this.switching = this.performSwitch(language, restore).finally(() => { this.switching = undefined; this.refresh(); });
    return this.switching;
  }
  private async performSwitch(language: Language, saved?: ViewState): Promise<void> {
    if (this.disposed || language === this.language) return;
    this.refresh(true);
    let state = saved || this.active.capture();
    if (!this.other) {
      let target = this.hostLanguage === "en" ? await translatedFor(this.source) : this.source;
      if (!target) target = await this.translate(this.source);
      if (!target) return; // cancelled
      if (this.disposed) return;
      this.other = await createPane(this.reader, target, state, () => this.save());
      this.addControls(this.other);
      // Preserve the position at the click. Adding a native content browser can
      // issue a source resize; its transient page-zero state is not a user move.
    }
    const next = language === this.hostLanguage ? this.host : this.other;
    const previous = this.active;
    // The target stays in memory. Switch only visibility, never a tab or PDF URL.
    next.browser.hidden = false;
    next.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:visible;opacity:0;pointer-events:none;";
    await next.restore(state);
    // Keep both viewport dimensions intact. display:none/hidden collapses the
    // PDF.js viewport and can reset its reported page to the first page.
    previous.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:hidden;pointer-events:none;";
    previous.browser.setAttribute("aria-hidden", "true");
    next.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:visible;";
    next.browser.removeAttribute("aria-hidden");
    next.pdf.pdfViewer.update();
    this.language = language;
    next.focus();
    this.save();
  }
  private addControls(pane: NativePane): void {
    const doc = pane.win.document;
    const mount = () => {
      if (doc.querySelector(".transyh-toggle")) return;
      const toolbar = doc.querySelector(".toolbar .end, .toolbar .end-container, #toolbar .end") || doc.querySelector(".toolbar");
      if (!toolbar) return;
      const box = doc.createElement("span");
      box.className = "transyh-toggle";
      box.setAttribute("role", "group"); box.setAttribute("aria-label", "TransYH 阅读语言");
      box.style.cssText = "display:inline-flex;align-items:center;gap:2px;flex-shrink:0;margin:0 7px;font:12px system-ui;";
      for (const lang of ["zh", "en"] as Language[]) {
        const button = doc.createElement("button");
        button.type = "button"; button.dataset.language = lang;
        button.textContent = lang === "zh" ? "中文" : "EN";
        button.title = lang === "zh" ? "切换中文；尚无译文时翻译全文" : "切换英文原文";
        button.style.cssText = "font:inherit;border:0;border-radius:4px;padding:4px 6px;cursor:pointer;background:transparent;color:inherit;";
        button.addEventListener("click", () => this.switchTo(lang).catch(this.report));
        box.appendChild(button);
        if (lang === "zh") { const sep = doc.createElement("span"); sep.textContent = "|"; sep.style.opacity = ".4"; box.appendChild(sep); }
      }
      toolbar.appendChild(box);
      this.controls.push(box);
      this.refresh();
    };
    const observer = new pane.win.MutationObserver(mount);
    observer.observe(doc.getElementById("reader-ui") || doc.body, { childList: true, subtree: true });
    this.observers.push(observer);
    mount();
  }
  private refresh(busy = false): void {
    for (const box of this.controls) {
      for (const element of box.querySelectorAll("button")) {
        const button = element as HTMLButtonElement;
        button.disabled = busy;
        button.setAttribute("aria-pressed", String(button.dataset.language === this.language));
        button.style.fontWeight = button.dataset.language === this.language ? "700" : "400";
        button.style.background = button.dataset.language === this.language ? "rgba(70,120,200,.18)" : "transparent";
      }
    }
  }
  save(): void {
    if (this.disposed || !this.active || !this.reader._iframe?.isConnected) return;
    try { this.store.save(this.source, { language: this.language, state: this.active.capture() }); } catch { /* loading */ }
  }
  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.save(); this.disposed = true;
    clearInterval(this.saveTimer); clearInterval(this.cleanupTimer);
    for (const observer of this.observers) observer.disconnect();
    for (const box of this.controls) box.remove();
    if (this.other) this.other.destroy();
    if (this.host.browser?.isConnected) { this.host.browser.hidden = false; this.host.browser.style.cssText = ""; this.host.browser.removeAttribute("aria-hidden"); }
    await this.store.flush();
  }
}

export class Readers {
  sessions = new Map<string, ReadingSession>();
  private registering = new Set<string>();
  private handler: any;
  private timer: any;
  constructor(private store: Store, private translate: (item: any) => Promise<any>, private report: (e: any) => void) {}
  async attach(reader: any): Promise<ReadingSession | undefined> {
    if (!reader.tabID || reader.type !== "pdf") return;
    if (this.sessions.has(reader.tabID)) return this.sessions.get(reader.tabID);
    if (this.registering.has(reader.tabID)) {
      return until(() => this.sessions.get(reader.tabID), "阅读器初始化超时。");
    }
    this.registering.add(reader.tabID);
    try {
      await reader._initPromise;
      const session = new ReadingSession(reader, this.store, this.translate, this.report);
      this.sessions.set(reader.tabID, session);
      try { await session.init(); } catch (e) { this.sessions.delete(reader.tabID); await session.dispose(); throw e; }
      return session;
    } finally { this.registering.delete(reader.tabID); }
  }
  start(): void {
    this.handler = ({ reader }: any) => { this.attach(reader).catch(this.report); };
    Zotero.Reader.registerEventListener("renderToolbar", this.handler, "transyh@local");
    const scan = () => {
      for (const reader of Zotero.Reader._readers) {
        if (!this.sessions.has(reader.tabID)) this.attach(reader).catch(this.report);
      }
      for (const [id, session] of this.sessions) {
        if (!session.reader._iframe?.isConnected) { void session.dispose(); this.sessions.delete(id); }
      }
    };
    this.timer = setInterval(scan, 2000); scan();
  }
  async showChinese(source: any): Promise<void> {
    const session = [...this.sessions.values()].find(s => s.source.id === source.id && s.reader._iframe?.isConnected);
    if (session) { session.reader._window.Zotero_Tabs.select(session.reader.tabID); await session.switchTo("zh"); return; }
    const reader = await Zotero.Reader.open(source.id);
    if (reader) { const s = await this.attach(reader); await s?.switchTo("zh"); }
  }
  async stop(): Promise<void> {
    clearInterval(this.timer);
    Zotero.Reader.unregisterEventListener("renderToolbar", this.handler);
    await Promise.all([...this.sessions.values()].map(s => s.dispose()));
    this.sessions.clear();
  }
}
