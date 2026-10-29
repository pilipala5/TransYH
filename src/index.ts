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
const cleanups = new Map<any, () => void>();

function notify(message: string, fail = false): void {
  new ProgressWindowHelper("TransYH", { closeTime: fail ? 12000 : 5000 }).createLine({ text: message,
    icon: `chrome://zotero/skin/16/universal/${fail ? "cross" : "tick"}.svg` }).show();
}
function report(error: any): void { notify(error?.message || "操作失败，请重试。", true); }
export async function cancelTranslation(item: any): Promise<void> {
  await tasks.get(originalFor(item).id)?.run.cancel();
}
export function showTranslationProgress(item: any): void { tasks.get(originalFor(item).id)?.progress.show(); }
export function translationStatus(item: any) { return tasks.get(originalFor(item).id)?.progress.snapshot(); }
export async function retranslate(item: any): Promise<any> { return translate(item, { refresh: true }); }
export async function translate(item: any, options: { refresh?: boolean } = {}): Promise<any> {
  const source = originalFor(item);
  if (tasks.has(source.id)) { showTranslationProgress(source); return tasks.get(source.id)!.promise; }
  const run = new WorkerRun();
  const progress = new TranslationProgress();
  const promise = (async () => {
    const existing = await translatedFor(source);
    if (existing && !options.refresh) { notify("已复用现有中文附件，未调用 API。"); return existing; }
    const sourceState = await stamp(source);
    const input = await source.getFilePathAsync();
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
    progress.show();
    try {
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
  const settings = doc.createXULElement("menuitem");
  settings.setAttribute("label", "TransYH 设置…");
  settings.addEventListener("command", () => Zotero.Utilities.Internal.openPreferences("transyh-preferences"));
  const update = async () => {
    const pdfs = await selectedPDFs(win);
    translateMenu.hidden = !pdfs.length; cancel.hidden = !pdfs.some(p => tasks.has(p.id));
    translateMenu.setAttribute("label", pdfs.some(p => tasks.has(p.id)) ? "查看翻译进度 · TransYH" : "翻译全文 · TransYH");
    refreshMenu.hidden = !pdfs.length || !(await Promise.all(pdfs.map(p => translatedFor(p).catch(() => undefined)))).some(Boolean);
    refreshMenu.disabled = pdfs.some(p => tasks.has(p.id));
  };
  menu.append(translateMenu, refreshMenu, cancel, settings); menu.addEventListener("popupshowing", update);
  cleanups.set(win, () => { menu.removeEventListener("popupshowing", update); translateMenu.remove(); refreshMenu.remove(); cancel.remove(); settings.remove(); });
}
export function onMainWindowUnload(win: any): void { cleanups.get(win)?.(); cleanups.delete(win); }

export async function initPreferences(win: any): Promise<void> {
  const doc = win.document;
  const get = (id: string): any => doc.getElementById("transyh-" + id);
  if (!get("base") || get("base").dataset.transyhInitialized) return;
  get("base").dataset.transyhInitialized = "true";
  get("base").value = pref("baseURL"); get("model").value = pref("model"); get("python").value = pref("pythonPath");
  get("concurrency").value = pref("concurrency", "4");
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
    await credentials.set(base, get("key").value.trim());
    setPref("httpAllowedBase", allowedHTTPBase);
    setPref("baseURL", base); setPref("model", get("model").value.trim()); setPref("pythonPath", get("python").value.trim());
    setPref("concurrency", String(concurrency));
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
      { ok: true, baseURL: base, model: setup.model, credentialsStored: true, version: "0.1.4" }, { permissions: 0o600 });
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
  await applyPendingSetup();
  readers = new Readers(store, translate, report); readers.start();
  Zotero.TransYH = { translate, retranslate, cancelTranslation, showTranslationProgress, translationStatus, readers, store, engine, credentials, initPreferences, report };
  await Zotero.PreferencePanes.register({ pluginID: "transyh@local", id: "transyh-preferences", label: "TransYH",
    src: rootURI + "content/preferences.xhtml", scripts: [rootURI + "content/preferences.js"] });
  for (const win of Zotero.getMainWindows()) onMainWindowLoad(win);
}
export async function shutdown(): Promise<void> {
  for (const task of tasks.values()) await task.run.cancel();
  await Promise.allSettled([...tasks.values()].map(task => task.promise));
  await readers?.stop(); await store.flush();
  for (const cleanup of cleanups.values()) cleanup(); cleanups.clear();
  delete Zotero.TransYH;
}
