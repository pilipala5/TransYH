import { test } from "node:test";
import assert from "node:assert/strict";
import { ReadingSession } from "../src/readers";
import { TaskPerformance } from "../src/performance";

test("auto-highlights finish while the first Chinese switch awaits translation", async () => {
  // Exercise the real refresh entry point and the production promise order.
  const session = Object.create(ReadingSession.prototype) as any;
  session.hostItemID = 1;
  let translated = false;
  let finishTranslation!: () => void;
  const translation = new Promise<void>(resolve => { finishTranslation = resolve; });
  session.switching = translation.then(() => { translated = true; });
  let refreshed = false;
  const highlights = session.pdfUpdated({ id: 2 }).then(() => { refreshed = true; });
  await new Promise(resolve => setImmediate(resolve));
  try {
    assert.equal(refreshed, true, "an unloaded PDF must not await its own translation");
    assert.equal(translated, false);
  } finally {
    finishTranslation();
    await Promise.all([highlights, session.switching]);
  }
});

test("a loaded translated pane still waits for a previous switch and reloads", async () => {
  const session = Object.create(ReadingSession.prototype) as any;
  const calls: string[] = [];
  session.hostItemID = 1;
  session.otherItemID = 2;
  session.reader = { _iframe: { isConnected: true } };
  session.other = {
    capture: () => ({ pageIndex: 4, scale: 145 }),
    reloadFile: async () => { calls.push("reload"); },
    restore: async (state: any) => { assert.equal(state.pageIndex, 4); calls.push("restore"); },
  };
  session.forgetPane = () => {};
  session.addControls = () => {};
  session.refresh = () => {};
  session.save = () => {};
  session.drainSwitches = async () => {};
  let finishSwitch!: () => void;
  session.switching = new Promise<void>(resolve => { finishSwitch = resolve; });
  const refreshing = session.pdfUpdated({ id: 2 });
  assert.deepEqual(calls, []);
  finishSwitch();
  await refreshing;
  assert.deepEqual(calls, ["reload", "restore"]);
  assert.equal(session.switching, undefined);
  assert.equal(session.changing, false);
});

test("reader-refresh checkpoints contain only lifecycle values and tolerate IO failure", async () => {
  const runtime = globalThis as any;
  const previous = { IOUtils: runtime.IOUtils, PathUtils: runtime.PathUtils };
  const snapshots: any[] = [];
  runtime.PathUtils = { join: (...parts: string[]) => parts.join("/") };
  runtime.IOUtils = { writeJSON: async (_path: string, record: any) => { snapshots.push(structuredClone(record)); } };
  try {
    const performance = new TaskPerformance("/private-paper-directory", "highlight_worker");
    await performance.mark("reader_refresh");
    assert.equal(snapshots[0].currentPhase, "reader_refresh");
    assert.equal(snapshots[0].status, "running");
    await performance.finish("completed");
    assert.equal(snapshots.at(-1).status, "completed");
    assert.equal(JSON.stringify(snapshots).includes("private-paper"), false);
    runtime.IOUtils.writeJSON = async () => { throw new Error("disk full"); };
    await performance.finish("failed");
  } finally {
    Object.assign(runtime, previous);
  }
});
