import { NativePane, createPane, originalPane } from "./reader-compat";
import { Store, originalFor, translatedFor, type SavedReading } from "./storage";
import type { Language, ViewState } from "./core";

export class ReadingSession {
  public source: any;
  public host: NativePane;
  public other?: NativePane;
  public language: Language;
  private current: NativePane;
  private hostItemID: number;
  private otherItemID?: number;
  private translation?: any;
  private switching?: Promise<void>;
  private requested?: { language: Language; state?: ViewState; refresh?: boolean };
  private changing = false;
  private disposed = false;
  private disposal?: Promise<void>;
  private controls: HTMLElement[] = [];
  private paneCleanups = new Map<NativePane, () => void>();
  private saveTimer: any;
  private lastReading?: SavedReading;
  constructor(public reader: any, private store: Store, private translate: (item: any) => Promise<any>, private report: (e: any) => void) {
    const item = Zotero.Items.get(reader.itemID);
    this.source = originalFor(item);
    this.hostItemID = item.id;
    this.language = this.source.id === item.id ? "en" : "zh";
    this.current = this.host = originalPane(reader);
  }
  get active(): NativePane { return this.current; }
  async init(): Promise<void> {
    await this.host.ready(() => this.disposed || !this.reader._iframe?.isConnected);
    if (this.disposed) return;
    this.addControls(this.host);
    const saved = this.store.get(this.source);
    if (saved) {
      if (saved.language !== this.language && await translatedFor(this.source)) await this.switchTo(saved.language, saved.state);
      else if (saved.language === this.language) await this.host.restore(saved.state);
    }
    if (this.disposed) return;
    this.save();
    // Native view events save changes promptly. This cheap fallback covers
    // Zotero versions that do not expose those events; Store deduplicates it.
    this.saveTimer = setInterval(() => this.save(), 1000);
  }
  switchTo(language: Language, restore?: ViewState, refresh = false): Promise<void> {
    if (this.disposed) return Promise.resolve();
    this.requested = { language, state: restore, refresh };
    if (this.switching) return this.switching;
    this.changing = true;
    this.switching = this.drainSwitches().finally(() => {
      this.switching = undefined; this.changing = false;
      this.refresh(); this.save();
    });
    return this.switching;
  }
  private async drainSwitches(): Promise<void> {
    try {
      while (this.requested && !this.disposed) {
        const request = this.requested; this.requested = undefined;
        await this.performSwitch(request.language, request.state, request.refresh);
      }
    } catch (error) { this.requested = undefined; if (!this.disposed) throw error; }
  }
  async useTranslation(item: any): Promise<void> {
    this.translation = item;
    if (this.changing || this.language === "zh" || this.requested?.language === "zh") await this.switchTo("zh", undefined, true);
    else if (this.other && this.otherItemID !== this.source.id && this.otherItemID !== item.id) {
      // Inactive superseded translations need not remain in memory.
      this.forgetPane(this.other); this.other.destroy(); this.other = undefined; this.otherItemID = undefined;
    }
  }
  private async performSwitch(language: Language, saved?: ViewState, refresh = false): Promise<void> {
    if (this.disposed || (language === this.language && !refresh && !saved)) return;
    this.refresh(true);
    const state = saved || this.active.capture();
    let target = language === "en" ? this.source : this.translation || await translatedFor(this.source);
    if (!target) target = await this.translate(this.source);
    if (!target || this.disposed) return;
    if (language === "zh") this.translation = target;
    const previous = this.active;
    const oldOther = this.other;
    let next: NativePane | undefined;
    let created = false;
    try {
      if (target.id === this.hostItemID) next = this.host;
      else if (this.other && this.otherItemID === target.id) next = this.other;
      else {
        next = await createPane(this.reader, target, state, () => this.save(), () => this.disposed || !this.reader._iframe?.isConnected);
        created = true;
      }
      if (this.disposed) return;
      if (next === previous && !saved) return;
      next.browser.hidden = false;
      if (next !== previous) next.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:visible;opacity:0;pointer-events:none;";
      await next.restore(state);
      if (this.disposed) return;
      // The previous pane stays readable until the new PDF has loaded and its
      // position is restored. Never collapse either viewport with display:none.
      if (previous !== next) {
        previous.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:hidden;pointer-events:none;";
        previous.browser.setAttribute("aria-hidden", "true");
      }
      next.browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:visible;";
      next.browser.removeAttribute("aria-hidden");
      next.pdf.pdfViewer.update();
      if (created) {
        this.other = next; this.otherItemID = target.id;
        this.addControls(next);
        if (oldOther) { this.forgetPane(oldOther); oldOther.destroy(); }
      }
      this.current = next; this.language = language;
      created = false;
      next.focus();
    } finally {
      if (created && next) next.destroy();
    }
  }
  private addControls(pane: NativePane): void {
    const doc = pane.win.document;
    let box: HTMLElement | undefined;
    const mount = () => {
      if (this.disposed || doc.querySelector(".transyh-toggle")) return;
      const toolbar = doc.querySelector(".toolbar .end, .toolbar .end-container, #toolbar .end") || doc.querySelector(".toolbar");
      if (!toolbar) return;
      box = doc.createElement("span");
      box!.className = "transyh-toggle";
      box!.setAttribute("role", "group"); box!.setAttribute("aria-label", "TransYH 阅读语言");
      box!.style.cssText = "display:inline-flex;align-items:center;gap:2px;flex-shrink:0;margin:0 7px;font:12px system-ui;";
      for (const lang of ["zh", "en"] as Language[]) {
        const button = doc.createElement("button");
        button.type = "button"; button.dataset.language = lang;
        button.textContent = lang === "zh" ? "中文" : "EN";
        button.title = lang === "zh" ? "切换中文；尚无译文时翻译全文" : "切换英文原文";
        button.style.cssText = "font:inherit;border:0;border-radius:4px;padding:4px 6px;cursor:pointer;background:transparent;color:inherit;";
        button.addEventListener("click", () => this.switchTo(lang).catch(this.report));
        box!.appendChild(button);
        if (lang === "zh") { const sep = doc.createElement("span"); sep.textContent = "|"; sep.style.opacity = ".4"; box!.appendChild(sep); }
      }
      toolbar.appendChild(box);
      this.controls.push(box!); this.refresh(this.changing);
    };
    const observer = new pane.win.MutationObserver(mount);
    observer.observe(doc.getElementById("reader-ui") || doc.body, { childList: true, subtree: true });
    const changed = () => this.save();
    const bus = pane.pdf?.eventBus;
    bus?.on?.("updateviewarea", changed);
    // Capture the last view before the native content realm is torn down.
    const closing = () => { if (pane === this.host) void this.dispose().catch(this.report); };
    pane.win.addEventListener("pagehide", closing);
    this.paneCleanups.set(pane, () => {
      try { observer.disconnect(); } catch { /* closed content realm */ }
      try { bus?.off?.("updateviewarea", changed); pane.win?.removeEventListener("pagehide", closing); } catch { /* closed realm */ }
      if (box) { try { box.remove(); } catch { /* closed content realm */ } this.controls = this.controls.filter(x => x !== box); }
    });
    mount();
  }
  private forgetPane(pane: NativePane): void { this.paneCleanups.get(pane)?.(); this.paneCleanups.delete(pane); }
  private refresh(busy = false): void {
    for (const box of this.controls) for (const element of box.querySelectorAll("button")) {
      const button = element as HTMLButtonElement;
      // Accept a newer intent while loading; one serial switch loop applies it.
      button.setAttribute("aria-busy", String(busy));
      button.setAttribute("aria-pressed", String(button.dataset.language === this.language));
      button.style.fontWeight = button.dataset.language === this.language ? "700" : "400";
      button.style.background = button.dataset.language === this.language ? "rgba(70,120,200,.18)" : "transparent";
    }
  }
  save(): void {
    if (this.disposed || this.changing) return;
    try {
      const reading = { language: this.language, state: this.active.capture() };
      // Sessions for two tabs of the same source must not repeatedly overwrite
      // each other's unchanged views in the source-keyed persistent store.
      if (JSON.stringify(reading) === JSON.stringify(this.lastReading)) return;
      this.lastReading = reading;
      this.store.save(this.source, this.lastReading);
    } catch { /* loading or closed: retain the last stable event/timer state */ }
  }
  dispose(): Promise<void> {
    if (this.disposal) return this.disposal;
    this.save();
    this.disposed = true; this.requested = undefined;
    clearInterval(this.saveTimer);
    for (const pane of this.paneCleanups.keys()) this.forgetPane(pane);
    this.other?.destroy(); this.other = undefined; this.otherItemID = undefined;
    if (this.host.browser?.isConnected) { this.host.browser.hidden = false; this.host.browser.style.cssText = ""; this.host.browser.removeAttribute("aria-hidden"); }
    // A pending model request belongs to the translation task, not the tab.
    // Closing the tab must flush now, even if that request is still running.
    this.disposal = this.store.flush();
    return this.disposal;
  }
}

export class Readers {
  sessions = new Map<string, ReadingSession>();
  private registering = new Map<string, Promise<ReadingSession | undefined>>();
  private handler: any;
  private timer: any;
  private stopped = false;
  constructor(private store: Store, private translate: (item: any) => Promise<any>, private report: (e: any) => void) {}
  attach(reader: any): Promise<ReadingSession | undefined> {
    if (this.stopped || !reader.tabID || reader.type !== "pdf") return Promise.resolve(undefined);
    const pending = this.registering.get(reader.tabID);
    if (pending) return pending;
    if (this.sessions.has(reader.tabID)) return Promise.resolve(this.sessions.get(reader.tabID));
    const promise = (async () => {
      await reader._initPromise;
      if (this.stopped || !reader._iframe?.isConnected) return;
      const session = new ReadingSession(reader, this.store, this.translate, this.report);
      this.sessions.set(reader.tabID, session);
      try { await session.init(); } catch (e) {
        this.sessions.delete(reader.tabID); await session.dispose();
        if (this.stopped || !reader._iframe?.isConnected) return;
        throw e;
      }
      return session;
    })().finally(() => this.registering.delete(reader.tabID));
    this.registering.set(reader.tabID, promise);
    return promise;
  }
  start(): void {
    this.stopped = false;
    this.handler = ({ reader }: any) => { this.attach(reader).catch(this.report); };
    Zotero.Reader.registerEventListener("renderToolbar", this.handler, "transyh@local");
    const scan = () => {
      for (const reader of Zotero.Reader._readers) {
        if (!this.sessions.has(reader.tabID) && !this.registering.has(reader.tabID)) this.attach(reader).catch(this.report);
      }
      for (const [id, session] of this.sessions) {
        if (!session.reader._iframe?.isConnected) { void session.dispose().catch(this.report); this.sessions.delete(id); }
      }
    };
    this.timer = setInterval(scan, 2000); scan();
  }
  async translationUpdated(source: any, item: any): Promise<void> {
    await Promise.all([...this.sessions.values()].filter(s => s.source.id === source.id && s.reader._iframe?.isConnected)
      .map(s => s.useTranslation(item)));
  }
  async showChinese(source: any): Promise<void> {
    const session = [...this.sessions.values()].find(s => s.source.id === source.id && s.reader._iframe?.isConnected);
    if (session) { session.reader._window.Zotero_Tabs.select(session.reader.tabID); await session.switchTo("zh"); return; }
    const reader = await Zotero.Reader.open(source.id);
    if (reader) { const s = await this.attach(reader); await s?.switchTo("zh"); }
  }
  async stop(): Promise<void> {
    this.stopped = true; clearInterval(this.timer);
    Zotero.Reader.unregisterEventListener("renderToolbar", this.handler);
    const disposals = [...this.sessions.values()].map(s => s.dispose());
    await Promise.allSettled([...disposals, ...this.registering.values()]);
    this.sessions.clear(); this.registering.clear();
  }
}
