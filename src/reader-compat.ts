import { clampState, type ViewState } from "./core";

// The only module that reaches Zotero's private reader implementation.
// Runtime tested on Zotero 10.0.6; 9.0.6 source inspected. Probes fail closed.
export const unwrap = (x: any): any => x?.wrappedJSObject || x;
export const clone = (x: any, win: any): any => Cu.cloneInto(x, win, { cloneFunctions: true, wrapReflectors: true });

export async function until<T>(get: () => T | null | false | undefined, message: string, timeout = 20000,
  cancelled = () => false): Promise<T> {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (cancelled()) throw new Error("阅读标签已关闭。");
    const value = get();
    if (value) return value;
    await Zotero.Promise.delay(30);
  }
  throw new Error(message);
}

export class NativePane {
  private destroyed = false;
  constructor(public browser: any, public internal: any) {}
  get win(): any { return this.browser.contentWindow; }
  get pdf(): any {
    const view = unwrap(this.internal)?._primaryView;
    return unwrap(view?._iframeWindow || view?._iframe?.contentWindow)?.PDFViewerApplication;
  }
  async ready(cancelled = () => false): Promise<void> {
    const view = unwrap(this.internal)?._primaryView;
    let initialized = !view?.initializedPromise;
    let failed = false;
    view?.initializedPromise?.then(() => { initialized = true; }, () => { failed = true; });
    // pagesCount/_location can appear before Zotero applies its initial view.
    // Wait for that native work, otherwise it can overwrite our restored state.
    await until(() => this.pdf?.pdfViewer?.pagesCount && this.pdf?.pdfViewer?._location,
      "TransYH 无法访问原生 PDF 阅读器；当前 Zotero 版本可能不兼容。", 30000, cancelled);
    await until(() => { if (failed) throw new Error("原生 PDF 阅读器初始化失败。"); return initialized; },
      "原生 PDF 阅读器初始化超时。", 30000, cancelled);
  }
  capture(): ViewState {
    const viewer = this.pdf?.pdfViewer;
    if (!viewer) throw new Error("PDF 阅读器尚未就绪。");
    const loc = viewer._location;
    return {
      pageIndex: (loc?.pageNumber || viewer.currentPageNumber || 1) - 1,
      scale: loc?.scale ?? (viewer.currentScale * 100), top: loc?.top, left: loc?.left,
      scrollMode: viewer.scrollMode, spreadMode: viewer.spreadMode,
    };
  }
  async restore(value: ViewState): Promise<void> {
    const viewer = this.pdf.pdfViewer;
    const state = clampState(value, viewer.pagesCount);
    viewer.scrollMode = state.scrollMode ?? 0;
    viewer.spreadMode = state.spreadMode ?? 0;
    // Preserve scale mode (page-width/page-fit) as well as numeric percentages.
    const scale = typeof state.scale === "number" ? state.scale / 100 : state.scale;
    const dest = [null, { name: "XYZ" }, state.left ?? null, state.top ?? null, scale];
    viewer.scrollPageIntoView(clone({ pageNumber: state.pageIndex + 1, destArray: dest,
      allowNegativeOffset: true }, unwrap(this.internal)._primaryView._iframeWindow));
    // PDF.js normally updates _location in its scroll-rAF callback. A hidden
    // browser throttles that callback; force the native synchronous layout pass.
    viewer.update();
    // Hidden content documents throttle rAF to ~1 second. Use the chrome window
    // for layout frames, with a bounded fallback if the whole app is backgrounded.
    const chrome = this.browser.ownerGlobal || Zotero.getMainWindow();
    await Promise.race([
      new Promise<void>(resolve => chrome.requestAnimationFrame(() => chrome.requestAnimationFrame(() => resolve()))),
      Zotero.Promise.delay(50),
    ]);
    viewer.update();
  }
  focus(): void { this.win.focus(); this.internal.focus?.(); }
  destroy(): void {
    if (this.destroyed) return;
    this.destroyed = true;
    let loadingTask: any;
    try { loadingTask = this.pdf?.pdfLoadingTask; } catch { /* content realm already destroyed */ }
    try {
      // The secondary reader owns event listeners and PDF.js loading tasks as
      // well as its primary view. Prefer its complete native teardown.
      const result = typeof this.internal?.uninit === "function" ? this.internal.uninit()
        : typeof this.internal?.destroy === "function" ? this.internal.destroy() : this.internal?._primaryView?.destroy?.();
      result?.catch?.(() => {});
    } catch { /* realm may already be gone */ }
    try { loadingTask?.destroy()?.catch?.(() => {}); } catch { /* closed PDF worker */ }
    this.browser.remove();
    this.internal = undefined;
  }
}

export function originalPane(reader: any): NativePane {
  if (!["9", "10"].includes(String(Zotero.version).split(".")[0]) || !reader._iframe || !reader._internalReader || !reader._tabContainer) {
    throw new Error("TransYH 单标签切换目前支持 Zotero 9–10，当前阅读器接口不可用。");
  }
  return new NativePane(reader._iframe, unwrap(reader._internalReader));
}

export async function createPane(reader: any, item: any, initial: ViewState, onState: (state: ViewState) => void,
  cancelled = () => false): Promise<NativePane> {
  const doc = reader._window.document;
  const browser = doc.createXULElement("browser");
  browser.setAttribute("type", "content");
  browser.setAttribute("transparent", "true");
  browser.setAttribute("flex", "1");
  browser.classList.add("transyh-reader");
  // Keep it laid out at full size during first paint without covering the original.
  browser.style.cssText = "position:absolute;inset:0;width:100%;height:100%;visibility:visible;opacity:0;pointer-events:none;";
  reader._tabContainer.style.position = "relative";
  reader._tabContainer.appendChild(browser);
  browser.setAttribute("src", "resource://zotero/reader/reader.html");
  let pane: NativePane | undefined;
  try {
    const raw = await until(() => {
      const w = unwrap(browser.contentWindow);
      return typeof w?.createReader === "function" ? w : null;
    }, "中文阅读器加载超时。", 20000, cancelled);
    const ftl: string[] = [];
    for (const locale of [...new Set(["en-US", Zotero.locale])]) {
      for (const name of ["branding/brand.ftl", "zotero.ftl", "reader.ftl"]) {
        try { ftl.push(Zotero.File.getContentsFromURL(`resource://app/localization/${locale}/${name}`)); } catch { /* optional locale */ }
      }
    }
    const noop = () => {};
    const config = {
      type: "pdf", data: { url: `zotero://attachment/${Zotero.API.getLibraryPrefix(item.libraryID)}/items/${item.key}/` },
      annotations: [], readOnly: true, ftl, primaryViewState: initial,
      sidebarOpen: false, sidebarWidth: 240, showContextPaneToggle: false, enableReadAloud: false,
      fontSize: Zotero.Prefs.get("fontSize"), rtl: Zotero.rtl,
      lightTheme: Zotero.Prefs.get("reader.lightTheme"), darkTheme: Zotero.Prefs.get("reader.darkTheme"),
      customThemes: Zotero.SyncedSettings.get(Zotero.Libraries.userLibraryID, "readerCustomThemes") || [],
      onChangeViewState: (state: any, primary: boolean) => { if (primary) onState(JSON.parse(JSON.stringify(state))); },
      onSaveAnnotations: (_a: any, done: () => void) => done(), onDeleteAnnotations: noop,
      onToggleSidebar: noop, onChangeSidebarWidth: noop, onChangeSidebarView: noop,
      onOpenContextMenu: (params: any) => {
        // Ask the native reader to render its own menu inside this document.
        // These menu callbacks already originate in this reader's content
        // realm. Re-cloning their Xray view strips function-valued properties.
        raw._reader?.openContextMenu(unwrap(params));
      },
      onOpenLink: (url: string) => Zotero.launchURL(url), onConfirm: () => false,
      onSetZoom: noop, onBringReaderToFront: noop, onToolbarShiftTab: noop, onIframeTab: noop,
      onSetLightTheme: noop, onSetDarkTheme: noop, onSaveCustomThemes: noop,
    };
    const internal = raw.createReader(clone(config, browser.contentWindow));
    pane = new NativePane(browser, unwrap(internal));
    await pane.ready(cancelled);
    await Promise.race([pane.pdf.pdfViewer.pagesPromise, Zotero.Promise.delay(5000)]);
    return pane;
  } catch (error) { if (pane) pane.destroy(); else browser.remove(); throw error; }
}
