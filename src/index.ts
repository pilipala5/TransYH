import { ProgressWindowHelper } from "zotero-plugin-toolkit";
import { Readers } from "./readers";
import { Store, Credentials, originalFor, translatedFor, stamp, importTranslation, pref, setPref } from "./storage";
import { Engine, WorkerRun } from "./engine";
import { canonicalBaseURL, normalizeBaseURL } from "./core";
import { TranslationProgress } from "./progress";

const store = new Store();
const credentials = new Credentials();
let rootURI = "";
let engine: Engine;
let readers: Readers;
const tasks = new Map<number, { run: WorkerRun; promise: Promise<any>; progress: TranslationProgress }>();
const highlightTasks = new Map<number, { run: WorkerRun; promise: Promise<any>; progress: TranslationProgress; committing: boolean }>();
const cleanups = new Map<any, () => void>();

function notify(message: string, fail = false): void {
  new ProgressWindowHelper("TransYH", { closeTime: fail ? 12000 : 5000 }).createLine({ text: message,
    icon: `chrome://zotero/skin/16/universal/${fail ? "cross" : "tick"}.svg` }).show();
}
function report(error: any): void { notify(error?.message || "操作失败，请重试。", true); }
export async function cancelTranslation(item: any): Promise<void> {
  const id = originalFor(item).id;
  await tasks.get(id)?.run.cancel();
  const highlight = highlightTasks.get(id);
  if (highlight && !highlight.committing) await highlight.run.cancel();
}
export function showTranslationProgress(item: any): void { (highlightTasks.get(originalFor(item).id) || tasks.get(originalFor(item).id))?.progress.show(); }
export function translationStatus(item: any) { return (highlightTasks.get(originalFor(item).id) || tasks.get(originalFor(item).id))?.progress.snapshot(); }
const highlightDirectory = () => PathUtils.join(Zotero.DataDirectory.dir, "transyh", "highlights");

async function highlightAttachment(attachment: any, config = engine.config()): Promise<any> {
  const source = originalFor(attachment);
  if (source.id === attachment.id) throw new Error("请选择已关联的中文译文；英文 PDF 不会被标注。");
  if (highlightTasks.has(source.id)) return highlightTasks.get(source.id)!.promise;
  const run = new WorkerRun(), progress = new TranslationProgress("highlight");
  const task = { run, progress, committing: false, promise: Promise.resolve<any>(undefined) };
  task.promise = (async () => {
    if (!attachment.isImportedAttachment?.() || !attachment.isEditable?.()) throw new Error("仅支持安全更新本地、可编辑的已导入中文附件。");
    const input = await attachment.getFilePathAsync();
    const protectedOriginal = await source.getFilePathAsync();
    if (!input || input === protectedOriginal) throw new Error("中文附件不可用，英文原件未修改。");
    const directory = highlightDirectory();
    const outputDir = PathUtils.join(directory, "staging", Services.uuid.generateUUID().toString().slice(1, -1));
    progress.update({ type: "progress", progress: 0, message: "读取中文 PDF，定位科研重点…" }); progress.show();
    try {
      const result = await engine.run("highlight", { ...config, highlightDensity: pref("highlightDensity", "smart"), input, protectedOriginal, outputDir,
        cacheDir: PathUtils.join(directory, "cache") }, event => progress.update(event), run);
      if (run.cancelled) throw new Error("AI 标注已取消，原译文保留。");
      if (!result.unchanged) {
        if (!result.path || !result.sourceFingerprint) throw new Error("AI 标注没有返回可安全保存的 PDF。");
        // Model work is cancellable; this short backup/atomic commit phase is
        // allowed to finish, including during orderly plugin shutdown.
        task.committing = true;
        const saved = await engine.run("installHighlights", { input, protectedOriginal, candidatePath: result.path,
          sourceFingerprint: result.sourceFingerprint, installDir: directory });
        result.backupPath = saved.backupPath;
        await IOUtils.remove(result.path, { ignoreAbsent: true }).catch(() => {});
        // Preserve the attachment ID and all Zotero annotation items.
        attachment.attachmentSyncState = Zotero.Sync.Storage.Local.SYNC_STATE_TO_UPLOAD;
        await attachment.saveTx();
        try { await readers.pdfUpdated(attachment); }
        catch { notify("重点标注已安全保存；阅读器刷新未完成，可重新打开中文附件。", true); }
      }
      progress.finish(false, result.highlightCount ? (result.unchanged ? `已复用 ${result.highlightCount} 处重点，未重复请求或叠加标注。`
        : `已标注 ${result.highlightCount} 处重点；原译文备份保留，请核对证据。`)
        : "没有充分证据可标注，原译文保持可读。");
      return result;
    } catch (error) { progress.close(); throw error; }
  })().finally(() => highlightTasks.delete(source.id));
  highlightTasks.set(source.id, task);
  return task.promise;
}

export async function highlightPDF(item: any): Promise<any> {
  const source = originalFor(item);
  if (tasks.has(source.id)) await tasks.get(source.id)!.promise;
  const attachment = await translatedFor(source);
  if (!attachment) throw new Error("尚无可用中文 PDF，请先翻译全文。");
  return highlightAttachment(attachment);
}
export async function retranslate(item: any): Promise<any> { return translate(item, { refresh: true }); }
export async function translate(item: any, options: { refresh?: boolean } = {}): Promise<any> {
  const source = originalFor(item);
  if (highlightTasks.has(source.id)) await highlightTasks.get(source.id)!.promise.catch(() => {});
  if (tasks.has(source.id)) { showTranslationProgress(source); return tasks.get(source.id)!.promise; }
  const run = new WorkerRun();
  const progress = new TranslationProgress();
  const promise = (async () => {
    progress.update({ type: "progress", message: "正在本地检查 PDF 语言…", progress: 0 });
    progress.show();
    try {
      const input = await source.getFilePathAsync();
      const inspected = await engine.run("inspect", { input }, undefined, run);
      if (inspected.language === "zh") {
        progress.finish(false, "原文已是中文，无需翻译。");
        return source;
      }
      const existing = await translatedFor(source);
      if (existing && !options.refresh) { progress.finish(false, "已复用现有中文附件。"); return existing; }
      const sourceState = await stamp(source);
      // Freeze the configuration for prepare, translate and completion, even if
      // the preferences change while the worker is running. Keys stay in pipes.
      const config = engine.config();
      const taskParams = { ...config, input, sourceID: `${source.libraryID}/${source.key}`,
        taskDir: PathUtils.join(Zotero.DataDirectory.dir, "transyh", "retranslation") };
      let task = options.refresh ? await engine.run("prepareRefresh", taskParams, undefined, run) : undefined;
      if (task?.resumed && await translatedFor(source, task.refreshToken)) {
        // Recover the narrow crash window after Zotero saved the attachment but
        // before the local task was marked completed. A new explicit refresh
        // must then start a fresh namespace instead of duplicating that import.
        await engine.run("completeRefresh", { ...taskParams, refreshToken: task.refreshToken }, undefined, run);
        task = await engine.run("prepareRefresh", taskParams, undefined, run);
      }
      const token = task?.refreshToken || Services.uuid.generateUUID().toString().slice(1, -1);
      // Cache identity survives retries; attachment ordering follows this attempt.
      // A task resumed after a newer configuration must become the latest version.
      const version = `${Date.now()}-${token}`;
      const outputDir = PathUtils.join(Zotero.DataDirectory.dir, "transyh", "jobs", `${source.libraryID}-${source.key}`, version);
      await IOUtils.makeDirectory(outputDir, { permissions: 0o700, ignoreExisting: true });
      progress.update({ type: "progress", message: "正在准备本地翻译引擎…", progress: 0 });
      const result = await engine.run("translate", { ...config, input, outputDir,
        ...(options.refresh ? { ...taskParams, refreshToken: token } : {}) }, event => {
        progress.update(event);
      }, run);
      if (!result.path) throw new Error("本地引擎没有返回中文 PDF。");
      if (result.quality?.status === "structural_error") throw new Error("译文存在结构性错误，未导入；已有译文保留。");
      const attachment = await importTranslation(source, result.path, sourceState, { refresh: options.refresh, version });
      if (options.refresh) {
        try { await engine.run("completeRefresh", { ...taskParams, refreshToken: token }, undefined, run); }
        catch { notify("新译文已保存；任务状态保存未完成，下次重译会核对已导入版本。", true); }
      }
      // Imported attachment owns its own copy; remove the generated duplicate.
      await IOUtils.remove(result.path, { ignoreAbsent: true }).catch(() => {});
      if (pref("autoHighlights") === "true" && !run.cancelled) {
        try { await highlightAttachment(attachment, config); }
        catch { notify("中文译文已保存；AI 重点标注未完成，原译文和批注保留，可稍后重试。", true); }
      }
      progress.finish(result.quality?.status === "suspect");
      if (options.refresh) {
        // A reader error does not roll back a valid, already imported PDF.
        try { await readers.translationUpdated(source, attachment); }
        catch { notify("新译文已保存；阅读器加载未完成，可再次点击“中文”。", true); }
      }
      return attachment;
    } catch (error) { progress.close(); throw error; }
  })().finally(() => tasks.delete(source.id));
  tasks.set(source.id, { run, promise, progress });
  return promise;
}

async function selectedPDFs(win: any): Promise<any[]> {
  const result = new Map<number, any>();
  for (const item of win.ZoteroPane.getSelectedItems()) {
    const pdf = item.isPDFAttachment() ? item : await item.getBestAttachment?.();
    if (pdf?.isPDFAttachment()) { const source = originalFor(pdf); result.set(source.id, source); }
  }
  return [...result.values()];
}
export function onMainWindowLoad(win: any): void {
  if (cleanups.has(win)) return;
  const doc = win.document;
  const menu = doc.getElementById("zotero-itemmenu");
  if (!menu) return;
  const translateMenu = doc.createXULElement("menuitem");
  translateMenu.id = "transyh-translate";
  translateMenu.setAttribute("label", "翻译全文 · TransYH");
  translateMenu.addEventListener("command", async () => {
    for (const pdf of await selectedPDFs(win)) {
      if (tasks.has(pdf.id)) { showTranslationProgress(pdf); continue; }
      try { await translate(pdf); await readers.showChinese(pdf); } catch (e) { report(e); }
    }
  });
  const refreshMenu = doc.createXULElement("menuitem");
  refreshMenu.id = "transyh-retranslate";
  refreshMenu.setAttribute("label", "重新翻译 · TransYH");
  refreshMenu.addEventListener("command", async () => {
    for (const pdf of await selectedPDFs(win)) {
      if (tasks.has(pdf.id)) { showTranslationProgress(pdf); continue; }
      try { await retranslate(pdf); await readers.showChinese(pdf); } catch (e) { report(e); }
    }
  });
  const cancel = doc.createXULElement("menuitem");
  cancel.id = "transyh-cancel"; cancel.setAttribute("label", "取消全文翻译 · TransYH");
  cancel.addEventListener("command", async () => { for (const pdf of await selectedPDFs(win)) await cancelTranslation(pdf); });
  const highlight = doc.createXULElement("menuitem");
  highlight.id = "transyh-highlight"; highlight.setAttribute("label", "AI 标注重点");
  highlight.addEventListener("command", async () => {
    for (const pdf of await selectedPDFs(win)) {
      try { await highlightPDF(pdf); await readers.showChinese(pdf); } catch (error) { report(error); }
    }
  });
  const settings = doc.createXULElement("menuitem");
  settings.setAttribute("label", "TransYH 设置…");
  settings.addEventListener("command", () => Zotero.Utilities.Internal.openPreferences("transyh-preferences"));
  const update = async () => {
    const pdfs = await selectedPDFs(win);
    const busy = (p: any) => tasks.has(p.id) || highlightTasks.has(p.id);
    translateMenu.hidden = !pdfs.length; cancel.hidden = !pdfs.some(busy);
    cancel.setAttribute("label", pdfs.some(p => highlightTasks.has(p.id)) ? "取消 AI 标注 · TransYH" : "取消全文翻译 · TransYH");
    translateMenu.setAttribute("label", pdfs.some(p => tasks.has(p.id)) ? "查看翻译进度 · TransYH" : "翻译全文 · TransYH");
    refreshMenu.hidden = !pdfs.length || !(await Promise.all(pdfs.map(p => translatedFor(p).catch(() => undefined)))).some(Boolean);
    refreshMenu.disabled = pdfs.some(busy);
    highlight.hidden = refreshMenu.hidden; highlight.disabled = pdfs.some(busy);
  };
  menu.append(translateMenu, refreshMenu, highlight, cancel, settings); menu.addEventListener("popupshowing", update);
  cleanups.set(win, () => { menu.removeEventListener("popupshowing", update); translateMenu.remove(); refreshMenu.remove(); highlight.remove(); cancel.remove(); settings.remove(); });
}
export function onMainWindowUnload(win: any): void { cleanups.get(win)?.(); cleanups.delete(win); }

export async function initPreferences(win: any): Promise<void> {
  const doc = win.document;
  const get = (id: string): any => doc.getElementById("transyh-" + id);
  if (!get("base") || get("base").dataset.transyhInitialized) return;
  get("base").dataset.transyhInitialized = "true";
  get("base").value = pref("baseURL"); get("model").value = pref("model"); get("python").value = pref("pythonPath");
  get("concurrency").value = pref("concurrency", "4");
  get("auto-highlights").checked = pref("autoHighlights") === "true";
  const density = pref("highlightDensity", "smart");
  get("highlight-density").value = ["concise", "smart", "full"].includes(density) ? density : "smart";
  get("http").checked = !!pref("httpAllowedBase") && pref("httpAllowedBase") === pref("baseURL");
  const status = (message: string) => { get("status").textContent = message; };
  let oldBase = pref("baseURL");
  try { if (oldBase) get("key").value = credentials.get(normalizeBaseURL(oldBase, pref("httpAllowedBase"))); } catch { status("读取凭据失败，请重新填写 API Key。"); }
  const save = async () => {
    const candidate = canonicalBaseURL(get("base").value);
    const allowedHTTPBase = get("http").checked ? candidate : "";
    const base = normalizeBaseURL(candidate, allowedHTTPBase);
    if (!get("model").value.trim()) throw new Error("请填写 Model。");
    const concurrency = Number(get("concurrency").value);
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 8) throw new Error("并发请求数应为 1–8 的整数。");
    const density = get("highlight-density").value;
    if (!["concise", "smart", "full"].includes(density)) throw new Error("请选择有效的标注密度。");
    await credentials.set(base, get("key").value.trim());
    setPref("httpAllowedBase", allowedHTTPBase);
    setPref("baseURL", base); setPref("model", get("model").value.trim()); setPref("pythonPath", get("python").value.trim());
    setPref("concurrency", String(concurrency));
    setPref("autoHighlights", String(get("auto-highlights").checked));
    setPref("highlightDensity", density);
    oldBase = base; get("base").value = base;
  };
  get("save").addEventListener("click", async () => { try { await save(); status("已保存。API Key 保存在本地凭据管理器。"); } catch (e: any) { status(e.message); } });
  get("test").addEventListener("click", async () => {
    get("test").disabled = true; status("正在测试连接…");
    try { await save(); const r = await engine.run("test"); status(r.message || "连接成功。"); } catch (e: any) { status(e.message); }
    finally { get("test").disabled = false; }
  });
  get("detect").addEventListener("click", async () => {
    setPref("pythonPath", get("python").value.trim()); status("正在检测引擎…");
    try { const r = await engine.run("check"); status(r.message || "引擎可用。"); } catch (e: any) { status(e.message); }
  });
  get("base").addEventListener("change", () => {
    try { const base = canonicalBaseURL(get("base").value); get("http").checked = pref("httpAllowedBase") === base;
      if (base !== oldBase) get("key").value = credentials.get(base); } catch { /* validate on save */ }
  });
}

async function applyPendingSetup(): Promise<void> {
  const setupFile = PathUtils.join(Zotero.Profile.dir, "transyh-setup.json");
  if (!await IOUtils.exists(setupFile)) return;
  try {
    const setup = await IOUtils.readJSON(setupFile);
    const base = canonicalBaseURL(setup.baseURL);
    const allowedHTTPBase = setup.allowHTTP === true ? base : "";
    normalizeBaseURL(base, allowedHTTPBase);
    if (!setup.model || !Zotero.isMac) throw new Error("自动配置内容无效或平台不支持。");
    // Keychain -> anonymous child-process pipe -> encrypted Gecko Login Manager.
    // The setup file and distributable never contain the API key.
    const credential = await engine.run("readCredential", { baseURL: base });
    if (!credential.apiKey) throw new Error("本机 Keychain 中没有找到此服务的凭据。");
    await credentials.set(base, credential.apiKey);
    credential.apiKey = undefined;
    setPref("baseURL", base); setPref("model", setup.model); setPref("httpAllowedBase", allowedHTTPBase);
    setPref("pythonPath", setup.pythonPath || "");
    await IOUtils.writeJSON(PathUtils.join(Zotero.Profile.dir, "transyh-setup-result.json"),
      { ok: true, baseURL: base, model: setup.model, credentialsStored: true, version: "0.2.2" }, { permissions: 0o600 });
    await IOUtils.remove(setupFile);
  } catch {
    await IOUtils.writeJSON(PathUtils.join(Zotero.Profile.dir, "transyh-setup-result.json"),
      { ok: false, message: "TransYH 自动配置未完成，请在设置中检查本地引擎和 Keychain 凭据。" }, { permissions: 0o600 });
  }
}

export async function startup(uri: string): Promise<void> {
  rootURI = uri;
  await store.init();
  engine = new Engine(rootURI, credentials); await engine.prepare();
  try { await engine.run("recoverHighlights", { installDir: highlightDirectory() }); }
  catch { notify("部分 AI 标注保存记录需要检查；已有 PDF 和备份保留。", true); }
  await applyPendingSetup();
  readers = new Readers(store, translate, report, {
    status: translationStatus, show: showTranslationProgress, cancel: cancelTranslation,
  }); readers.start();
  Zotero.TransYH = { translate, retranslate, highlightPDF, cancelTranslation, showTranslationProgress, translationStatus, readers, store, engine, credentials, initPreferences, report };
  await Zotero.PreferencePanes.register({ pluginID: "transyh@local", id: "transyh-preferences", label: "TransYH",
    src: rootURI + "content/preferences.xhtml", scripts: [rootURI + "content/preferences.js"] });
  for (const win of Zotero.getMainWindows()) onMainWindowLoad(win);
}
export async function shutdown(): Promise<void> {
  for (const task of tasks.values()) await task.run.cancel();
  for (const task of highlightTasks.values()) if (!task.committing) await task.run.cancel();
  await Promise.allSettled([...highlightTasks.values()].map(task => task.promise));
  await Promise.allSettled([...tasks.values()].map(task => task.promise));
  await readers?.stop(); await store.flush();
  for (const cleanup of cleanups.values()) cleanup(); cleanups.clear();
  delete Zotero.TransYH;
}
