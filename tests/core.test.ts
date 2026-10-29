import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeBaseURL, apiError, clampState } from "../src/core";

test("normalize roots, version roots, nested gateways, full endpoints", () => {
  for (const [input, output] of [
    ["https://provider.example", "https://provider.example/v1"],
    [" https://provider.example/v1/ ", "https://provider.example/v1"],
    ["https://provider.example/v1/chat/completions/", "https://provider.example/v1"],
    ["https://gateway.example/api/openai/v1", "https://gateway.example/api/openai/v1"],
    ["http://localhost:8080", "http://localhost:8080/v1"],
    ["http://[::1]:8080/chat/completions", "http://[::1]:8080/v1"],
  ]) assert.equal(normalizeBaseURL(input), output);
});
test("reject unsafe or invalid API addresses", () => {
  for (const url of ["", "provider.example", "file:///tmp/key", "http://provider.example/v1",
    "https://name:secret@provider.example/v1", "https://provider.example?key=secret", "https://provider.example/#secret"]) {
    assert.throws(() => normalizeBaseURL(url));
  }
});
test("remote HTTP authorization is bound to one normalized service address", () => {
  const allowed="http://example.internal:8317/v1";
  assert.equal(normalizeBaseURL(allowed+"/chat/completions",allowed),allowed);
  assert.throws(()=>normalizeBaseURL("http://other.internal:8317/v1",allowed));
  assert.throws(()=>normalizeBaseURL("http://example.internal:8317/other",allowed));
  assert.throws(()=>normalizeBaseURL("http://example.internal:8318/v1",allowed));
});
test("report authentication, quota, endpoint, and server failures", () => {
  assert.match(apiError(401), /鉴权/); assert.match(apiError(403), /权限/);
  assert.match(apiError(429), /限流/); assert.match(apiError(404), /不存在/);
  assert.match(apiError(503), /不可用/);
});
test("map page bounds without changing scale or PDF coordinates", () => {
  assert.deepEqual(clampState({ pageIndex: 9, scale: "page-width", top: 256, left: 12 }, 3),
    { pageIndex: 2, scale: "page-width", top: 256, left: 12 });
});

import { Store, importTranslation, originalFor, translatedFor } from "../src/storage";

test("reading persistence deduplicates idle polls, serializes writes, and survives reload", async () => {
  const runtime = globalThis as any;
  const previous = { Zotero: runtime.Zotero, IOUtils: runtime.IOUtils, PathUtils: runtime.PathUtils };
  let disk: any = {}, writes = 0, active = 0, peak = 0;
  const item = { libraryID: 1, key: "SOURCE" };
  runtime.Zotero = { DataDirectory: { dir: "/isolated" }, logError() {} };
  runtime.PathUtils = { join: (...args: string[]) => args.join("/") };
  runtime.IOUtils = { makeDirectory: async () => {}, readJSON: async () => structuredClone(disk),
    writeJSON: async (_path: string, value: any) => {
      active++; peak = Math.max(peak, active); writes++;
      await new Promise(resolve => setTimeout(resolve, 5)); disk = structuredClone(value); active--;
    } };
  try {
    const store = new Store(); await store.init();
    const reading = { language: "zh" as const, state: { pageIndex: 1, scale: 145, top: 540, left: -141 } };
    store.save(item, reading); await store.flush();
    for (let i = 0; i < 60; i++) { store.save(item, structuredClone(reading)); await store.flush(); }
    assert.equal(writes, 1, "60 unchanged polls must perform zero further writes");
    const first = store.flush();
    store.save(item, { language: "en", state: { pageIndex: 2, scale: "page-width", top: 610, left: 0 } });
    const second = store.flush();
    await Promise.all([first, second]);
    assert.equal(peak, 1, "atomic temp paths must never be written concurrently");
    const reopened = new Store(); await reopened.init();
    assert.deepEqual(reopened.get(item), { language: "en", state: { pageIndex: 2, scale: "page-width", top: 610, left: 0 } });
    const beforeCleanFlush = writes; await reopened.flush(); assert.equal(writes, beforeCleanFlush);
  } finally { Object.assign(runtime, previous); }
});

test("translation versions retain legacy attachments and roll back only a failed new import", async () => {
  const runtime = globalThis as any;
  const previous = { Zotero: runtime.Zotero, IOUtils: runtime.IOUtils };
  const items = new Map<number, any>();
  const attachmentIDs: number[] = [];
  let nextID = 10, failSave = false, fileStamp = 2000;
  const source: any = { id: 1, key: "SOURCE", libraryID: 1, parentID: 2,
    parentItem: { getAttachments: () => [...attachmentIDs] }, getTags: () => [],
    getFilePathAsync: async () => "/isolated/original.pdf", getField: () => "Fixture" };
  items.set(1, source);
  const makeItem = () => {
    const tags: string[] = [];
    const item: any = { id: nextID++, key: `ZH${nextID}`, libraryID: 1, deleted: false,
      isPDFAttachment: () => true, fileExists: async () => !item.deleted,
      getTags: () => tags.map(tag => ({ tag })), setField() {}, addTag: (tag: string) => tags.push(tag),
      saveTx: async () => { if (failSave) throw new Error("simulated import transaction failure"); },
      eraseTx: async () => { item.deleted = true; }, annotations: ["user annotation remains"] };
    items.set(item.id, item); attachmentIDs.push(item.id); return item;
  };
  runtime.IOUtils = { exists: async () => true, stat: async () => ({ size: 1024, lastModified: fileStamp }) };
  runtime.Zotero = { Items: { getAsync: async (id: number) => items.get(id), getByLibraryAndKey: (_library: number, key: string) => key === source.key ? source : undefined },
    Attachments: { importFromFile: async () => makeItem() } };
  try {
    const legacy = makeItem(); legacy.addTag("TransYH:source:SOURCE"); legacy.addTag("TransYH:stamp:1024:2000");
    assert.equal(await translatedFor(source), legacy);
    assert.equal(originalFor(legacy), source);
    assert.equal(await importTranslation(source, "/isolated/generated.pdf", "1024:2000"), legacy);
    assert.equal(attachmentIDs.length, 1);
    const fresh = await importTranslation(source, "/isolated/new.pdf", "1024:2000", { refresh: true, version: "1793200000000-fixture" });
    assert.notEqual(fresh.id, legacy.id);
    assert.equal(await translatedFor(source), fresh);
    assert.deepEqual(legacy.annotations, ["user annotation remains"]);
    assert.equal(legacy.deleted, false);
    assert.deepEqual(fresh.getTags().map((x: any) => x.tag).sort(), ["TransYH:source:SOURCE", "TransYH:stamp:1024:2000", "TransYH:version:1793200000000-fixture"].sort());
    failSave = true;
    await assert.rejects(importTranslation(source, "/isolated/failure.pdf", "1024:2000", { refresh: true, version: "1793200000001-fixture" }));
    assert.equal(await translatedFor(source), fresh);
    assert.equal(items.get(nextID-1).deleted, true);
    assert.equal(legacy.deleted, false); assert.equal(fresh.deleted, false);
    failSave = false; fileStamp++;
    await assert.rejects(importTranslation(source, "/isolated/new.pdf", "1024:2000", { refresh: true }), /发生变化/);
    fileStamp--;
    await assert.rejects(importTranslation(source, "/isolated/original.pdf", "1024:2000", { refresh: true }), /英文原件/);
  } finally { Object.assign(runtime, previous); }
});

import { NativePane } from "../src/reader-compat";
import { ReadingSession } from "../src/readers";

test("native readiness waits for the initial view and PDF teardown is idempotent", async () => {
  const runtime = globalThis as any, previous = runtime.Zotero;
  runtime.Zotero = { Promise: { delay: (ms: number) => new Promise(r => setTimeout(r, ms)) } };
  let initialize!: () => void, ready = false, removed = 0, tasksDestroyed = 0, viewsDestroyed = 0;
  const native = { _primaryView: { initializedPromise: new Promise<void>(r => { initialize = r; }),
    _iframeWindow: { PDFViewerApplication: { pdfViewer: { pagesCount: 3, _location: {} },
      pdfLoadingTask: { destroy: () => { tasksDestroyed++; return Promise.resolve(); } } } },
    destroy: () => { viewsDestroyed++; } } };
  const pane = new NativePane({ remove: () => { removed++; } }, native);
  try {
    const loading = pane.ready().then(() => { ready = true; });
    await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal(ready, false, "Early PDF location must not bypass the native initial view");
    initialize(); await loading; assert.equal(ready, true);
    pane.destroy(); pane.destroy();
    assert.equal(tasksDestroyed, 1); assert.equal(viewsDestroyed, 1); assert.equal(removed, 1);
    assert.equal(pane.internal, undefined);
  } finally { runtime.Zotero = previous; }
});

test("unchanged tabs of the same source do not overwrite each other's saved state", () => {
  const runtime = globalThis as any, previous = runtime.Zotero;
  const source = { id: 1, key: "FIXTURE", getTags: () => [] };
  runtime.Zotero = { version: "10.0.6", Items: { get: () => source } };
  const saves: any[] = [];
  const store = { save: (_item: any, reading: any) => saves.push(reading) } as unknown as Store;
  const reader = (page: number) => ({ itemID: 1, _tabContainer: {}, _iframe: { isConnected: true },
    _internalReader: { _primaryView: { _iframeWindow: { PDFViewerApplication: { pdfViewer: {
      _location: { pageNumber: page, scale: 145, top: 540, left: -141 }, scrollMode: 0, spreadMode: 0,
    } } } } } });
  try {
    const first = new ReadingSession(reader(2), store, async () => undefined, () => {});
    const second = new ReadingSession(reader(3), store, async () => undefined, () => {});
    first.save(); second.save();
    for (let i = 0; i < 60; i++) { first.save(); second.save(); }
    assert.equal(saves.length, 2);
    first.active.pdf.pdfViewer._location.top = 600; first.save();
    assert.equal(saves.length, 3); assert.equal(saves[2].state.top, 600);
  } finally { runtime.Zotero = previous; }
});
