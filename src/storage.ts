import { sourceStamp, type Language, type ViewState } from "./core";
export const PREFIX = "extensions.transyh.";
export const pref = (key: string, fallback = ""): string => String(Zotero.Prefs.get(PREFIX + key, true) ?? fallback);
export const setPref = (key: string, value: string): void => Zotero.Prefs.set(PREFIX + key, value, true);
const TAG = "TransYH:source:";
const STAMP = "TransYH:stamp:";
const VERSION = "TransYH:version:";
export type SavedReading = { language: Language; state: ViewState };

export class Store {
  private readings: Record<string, SavedReading> = {};
  private timer: any;
  private file = "";
  private revision = 0;
  private writtenRevision = 0;
  private writing: Promise<void> = Promise.resolve();
  async init(): Promise<void> {
    const dir = PathUtils.join(Zotero.DataDirectory.dir, "transyh");
    await IOUtils.makeDirectory(dir, { permissions: 0o700, ignoreExisting: true });
    this.file = PathUtils.join(dir, "reading.json");
    try { this.readings = await IOUtils.readJSON(this.file); } catch { this.readings = {}; }
  }
  id(item: any): string { return `${item.libraryID}/${item.key}`; }
  get(item: any): SavedReading | undefined { return this.readings[this.id(item)]; }
  save(item: any, reading: SavedReading): void {
    if (JSON.stringify(this.readings[this.id(item)]) === JSON.stringify(reading)) return;
    this.readings[this.id(item)] = JSON.parse(JSON.stringify(reading));
    this.revision++;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { void this.flush().catch(() => Zotero.logError(new Error("TransYH 阅读状态保存失败。"))); }, 700);
  }
  async flush(): Promise<void> {
    clearTimeout(this.timer);
    // Serialize writes sharing one atomic temp file. A save that arrives during
    // an IO operation remains dirty and is included by the next flush.
    this.writing = this.writing.catch(() => {}).then(async () => {
      if (!this.file || this.writtenRevision === this.revision) return;
      const revision = this.revision;
      const snapshot = JSON.parse(JSON.stringify(this.readings));
      await IOUtils.writeJSON(this.file, snapshot, { tmpPath: this.file + ".tmp", permissions: 0o600 });
      this.writtenRevision = revision;
    });
    await this.writing;
  }
}

export function originalFor(item: any): any {
  const tag = item.getTags().find((t: any) => t.tag.startsWith(TAG));
  if (!tag) return item;
  const source = Zotero.Items.getByLibraryAndKey(item.libraryID, tag.tag.slice(TAG.length));
  return source && !source.deleted ? source : item;
}
export async function stamp(item: any): Promise<string> {
  const path = await item.getFilePathAsync();
  if (!path || !await IOUtils.exists(path)) throw new Error("原始 PDF 文件不存在，请先下载附件。");
  const info = await IOUtils.stat(path);
  return sourceStamp(info.size, info.lastModified);
}
export async function translatedFor(source: any, taskToken?: string): Promise<any | undefined> {
  const expectedStamp = await stamp(source);
  let ids: number[];
  if (source.parentItem) ids = source.parentItem.getAttachments();
  else {
    const search = new Zotero.Search();
    search.libraryID = source.libraryID;
    search.addCondition("tag", "is", TAG + source.key);
    ids = await search.search();
  }
  const candidates = [];
  for (const id of ids) {
    const item = await Zotero.Items.getAsync(id);
    if (!item || item.deleted || !item.isPDFAttachment()) continue;
    const tags = item.getTags().map((t: any) => t.tag);
    if (tags.includes(TAG + source.key) && tags.includes(STAMP + expectedStamp)
      && (!taskToken || tags.some((tag: string) => tag.startsWith(VERSION) && tag.endsWith("-" + taskToken)))
      && await item.fileExists()) candidates.push(item);
  }
  // v0.1.3 attachments have no version tag and remain valid fallbacks.
  const version = (item: any): string => item.getTags().find((t: any) => t.tag.startsWith(VERSION))?.tag.slice(VERSION.length) || "";
  candidates.sort((a, b) => version(b).localeCompare(version(a)) || b.id - a.id);
  return candidates[0];
}
export async function importTranslation(source: any, output: string, expectedStamp: string,
  options: { refresh?: boolean; version?: string } = {}): Promise<any> {
  if (await stamp(source) !== expectedStamp) throw new Error("翻译期间原 PDF 已发生变化。译文未关联，请重试。");
  if (output === await source.getFilePathAsync()) throw new Error("译文路径不能是英文原件。");
  const existing = await translatedFor(source);
  if (existing && !options.refresh) return existing;
  const item = await Zotero.Attachments.importFromFile({ file: output, libraryID: source.libraryID,
    parentItemID: source.parentID || undefined });
  try {
    item.setField("title", `${source.getField("title") || "论文"} · 中文 (TransYH)`);
    item.addTag(TAG + source.key, 1);
    item.addTag(STAMP + expectedStamp, 1);
    if (options.version) item.addTag(VERSION + options.version, 1);
    await item.saveTx();
    if (!await item.fileExists()) throw new Error("新译文附件文件不可用，已有译文保留。");
  } catch (error) {
    // Only the new, unexposed import is rolled back. Existing files and user
    // annotations are never removed or edited by translation/retranslation.
    await item.eraseTx();
    throw error;
  }
  return item;
}

// Gecko Login Manager encrypts login records in the Zotero profile (NSS).
// The API key is deliberately never written to Zotero preferences.
export class Credentials {
  private origin(base: string): string { return "chrome://transyh"; }
  get(base: string): string {
    const logins = Services.logins.findLogins(this.origin(base), null, "TransYH API");
    return logins.find((x: any) => x.username === base)?.password || "";
  }
  async set(base: string, key: string): Promise<void> {
    const existing = Services.logins.findLogins(this.origin(base), null, "TransYH API")
      .filter((x: any) => x.username === base);
    if (!key) { for (const login of existing) Services.logins.removeLogin(login); return; }
    const login = Cc["@mozilla.org/login-manager/loginInfo;1"].createInstance(Ci.nsILoginInfo);
    login.init(this.origin(base), null, "TransYH API", base, key, "", "");
    if (existing.length) Services.logins.modifyLogin(existing[0], login);
    else if (typeof Services.logins.addLoginAsync === "function") await Services.logins.addLoginAsync(login);
    else Services.logins.addLogin(login);
  }
}
