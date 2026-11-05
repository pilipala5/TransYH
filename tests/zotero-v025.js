// Run only by the dedicated native host after installing the final XPI.
const root = Zotero.Prefs.get('extensions.transyh.testRoot', true);
const suite = Zotero.Prefs.get('extensions.transyh.testSuite', true);
if (!/^v025(?:-\d+)?$/.test(suite) || Zotero.Profile.dir !== PathUtils.join(root, '.test-profile', suite)) throw new Error('Requires isolated v025 profile');
const base = Zotero.Prefs.get('extensions.transyh.testAPIBase', true);
if (!/^http:\/\/127\.0\.0\.1:\d+\/v1$/.test(base)) throw new Error('Requires loopback Mock');
const a = Zotero.TransYH, prefix = 'extensions.transyh.';
const output = PathUtils.join(root, 'tests', 'output', suite);
const result = { actions: [], refreshes: [], progress: {}, checkpoints: [] };
const assert = (value, message) => { if (!value) throw new Error(message); };
const equal = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);
const delay = ms => Zotero.Promise.delay(ms);
async function bounded(promise, label, timeout = 20000) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      timer = Zotero.getMainWindow().setTimeout(() => reject(new Error(label + ' timed out')), timeout);
    })]);
  } finally { Zotero.getMainWindow().clearTimeout(timer); }
}
async function poll(get, accept, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await get();
    if (accept(value)) return value;
    await delay(100);
  }
  throw new Error(label + ' timed out');
}
async function checkpoint(phase) {
  result.checkpoints.push({ phase, at: Date.now() });
  await IOUtils.writeJSON(PathUtils.join(output, 'native-diagnostics.json'), result);
}
const stats = async () => (await Zotero.HTTP.request('GET', base.slice(0, -3) + '/stats', { responseType: 'json' })).response;
const control = async (model, options) => Zotero.HTTP.request('POST', base.slice(0, -3) + '/control', {
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model, ...options }),
});
async function filesBelow(directory, name) {
  if (!await IOUtils.exists(directory)) return [];
  const files = [];
  for (const path of await IOUtils.getChildren(directory)) {
    if ((await IOUtils.stat(path)).type === 'directory') files.push(...await filesBelow(path, name));
    else if (PathUtils.filename(path) === name) files.push(path);
  }
  return files;
}
let source, reader, session, monitor;
const originalRun = a.engine.run;
const originalRefresh = a.readers.pdfUpdated;
const NativeProgressWindow = Zotero.ProgressWindow;
// Observe real native progress bars without changing task decisions or promises.
Zotero.ProgressWindow = new Proxy(NativeProgressWindow, {
  construct(target, args) {
    const win = Reflect.construct(target, args);
    const headline = win.changeHeadline;
    let title = '', index = 0;
    win.changeHeadline = function (...values) { title = values[0]; return headline.apply(this, values); };
    const NativeItem = win.ItemProgress;
    win.ItemProgress = function (...values) {
      const item = new NativeItem(...values), first = index++ === 0;
      const setProgress = item.setProgress;
      item.setProgress = function (percent) {
        if (first && title.startsWith('TransYH')) {
          const kind = title.includes('AI') ? 'highlight' : 'translation';
          result.progress[kind] = Math.max(result.progress[kind] || 0, percent);
        }
        return setProgress.call(this, percent);
      };
      return item;
    };
    return win;
  },
});
try {
  assert(Zotero.Prefs.get(prefix + 'autoHighlights', true) === 'true', 'Automatic highlights must be enabled');
  const parent = new Zotero.Item('journalArticle');
  parent.setField('title', 'TransYH v0.2.5 authored first-switch acceptance'); await parent.saveTx();
  source = await Zotero.Attachments.importFromFile({ file: PathUtils.join(output, 'english.pdf'), parentItemID: parent.id });
  const english = await IOUtils.read(await source.getFilePathAsync());
  const annotation = async (item, comment) => {
    const note = new Zotero.Item('annotation'); note.parentID = item.id; note.libraryID = item.libraryID;
    note.annotationType = 'note'; note.annotationComment = comment; note.annotationColor = '#ffd400';
    note.annotationPageLabel = '1'; note.annotationSortIndex = '00000|000000|00000';
    note.annotationPosition = JSON.stringify({ pageIndex: 0, rects: [[25, 390, 40, 410]] });
    await note.saveTx(); return note;
  };
  const englishNote = await annotation(source, 'Existing English annotation');
  assert(parent.getAttachments().length === 1, 'The first click requires an untranslated English attachment');
  reader = await Zotero.Reader.open(source.id); await reader._initPromise;
  session = await a.readers.attach(reader); await session.host.ready();
  assert(session.language === 'en' && !session.other, 'Chinese pane must not be preloaded');
  const originalPDF = session.host.pdf.pdfDocument, tabID = reader.tabID;
  a.engine.run = async function (action, ...args) {
    result.actions.push({ action, event: 'start', at: Date.now() });
    if (action === 'highlight' && !result.automaticOrderVerified) {
      result.automaticOrderVerified = !!session.switching && !session.other
        && a.translationStatus(source)?.kind === 'highlight';
    }
    try {
      const value = await originalRun.call(this, action, ...args);
      result.actions.push({ action, event: 'end', at: Date.now() });
      return value;
    } catch (error) {
      result.actions.push({ action, event: 'failed', at: Date.now() }); throw error;
    }
  };
  a.readers.pdfUpdated = async function (item) {
    result.refreshes.push({ loaded: session.hostItemID === item.id || session.otherItemID === item.id,
      switching: !!session.switching, at: Date.now() });
    return originalRefresh.call(this, item);
  };
  monitor = Zotero.getMainWindow().setInterval(() => {
    const task = a.translationStatus(source);
    if (task) result.progress[task.kind + 'Visible'] = true;
  }, 50);
  await control('fixture-completion-responses', { delay: 0.6 });
  await checkpoint('before_first_chinese_click');
  const started = Date.now();
  session.host.win.document.querySelector('[data-language="zh"]').click();
  assert(session.switching, 'The toolbar click did not start the switch');
  await bounded(session.switching, 'First translation and automatic-highlight completion', 120000);
  result.firstSwitchMilliseconds = Date.now() - started;
  const idle = async () => poll(() => {
    const doc = session.active.win.document;
    return !session.switching && !a.translationStatus(source)
      && doc.querySelector('.transyh-status')?.hidden && doc.querySelector('.transyh-cancel')?.hidden;
  }, Boolean, 'Task maps, progress and cancel cleanup');
  await idle();
  assert(session.language === 'zh' && reader.tabID === tabID, 'First click did not finish in Chinese in the same tab');
  assert(result.progress.translation === 100 && result.progress.highlight === 100, 'Both native task progress bars must reach 100');
  assert(result.automaticOrderVerified && result.refreshes[0]?.switching && !result.refreshes[0]?.loaded,
    'The original cyclic call order was not exercised');
  const chinese = Zotero.Items.get(parent.getAttachments().find(id => id !== source.id));
  assert(chinese && parent.getAttachments().length === 2, 'Translation did not import exactly one new attachment');
  const chinesePath = await chinese.getFilePathAsync();
  await poll(() => session.active.internal._primaryView._iframeWindow.document.querySelector('.textLayer')?.textContent,
    text => text?.includes('合成'), 'The translated PDF text layer');
  assert(equal(english, await IOUtils.read(await source.getFilePathAsync())) && !englishNote.deleted,
    'The English PDF or its annotation changed');
  const transactionPaths = await IOUtils.getChildren(PathUtils.join(Zotero.DataDirectory.dir, 'transyh', 'highlights', 'transactions'));
  const transaction = await IOUtils.readJSON(transactionPaths.find(p => p.endsWith('.json')));
  assert(transaction.status === 'committed' && await IOUtils.exists(transaction.backup), 'Highlight safe commit or backup missing');
  result.backupPath = transaction.backup;
  const performancePaths = await filesBelow(PathUtils.join(Zotero.DataDirectory.dir, 'transyh'), 'task-performance.json');
  result.completedTasks = [];
  for (const path of performancePaths) {
    const record = await IOUtils.readJSON(path);
    assert(record.status === 'completed' && record.currentPhase === 'cleanup', 'A task remained in reader_refresh');
    result.completedTasks.push({ status: record.status, phase: record.currentPhase, stages: record.stages });
  }
  assert(result.completedTasks.length === 2, 'Expected translation and automatic-highlight lifecycle records');
  result.firstSwitchCompleted = true;
  await checkpoint('first_switch_and_both_tasks_completed');

  const chineseNote = await annotation(chinese, 'Existing Chinese annotation before refreshing highlights');
  await session.active.restore({ pageIndex: 0, scale: 125, top: 792, left: 0 });
  const position = session.active.capture(), previousPDF = session.active.pdf.pdfDocument;
  Zotero.Prefs.set(prefix + 'apiMode', 'chat_completions', true);
  Zotero.Prefs.set(prefix + 'model', 'fixture-completion-chat', true);
  await control('fixture-completion-chat', { delay: 0.6, requireContext: true });
  const highlightsStarted = result.actions.filter(row => row.action === 'highlight' && row.event === 'start').length;
  session.active.win.document.querySelector('.transyh-highlight').click();
  await poll(() => result.actions.filter(row => row.action === 'highlight' && row.event === 'start').length,
    n => n > highlightsStarted, 'Loaded Chinese re-annotation started');
  await idle();
  assert(session.active.pdf.pdfDocument !== previousPDF && session.host.pdf.pdfDocument === originalPDF,
    'The loaded Chinese pane must reload while the English PDF instance is preserved');
  assert(session.active.capture().scale === position.scale && !chineseNote.deleted && chineseNote.parentID === chinese.id,
    'Re-annotation lost reading position or the Chinese annotation');
  assert(result.refreshes.some(row => row.loaded), 'Loaded-pane refresh was not reached');
  result.loadedChineseRefresh = true;

  const marked = await IOUtils.read(chinesePath), calls = (await stats()).calls;
  const cached = await bounded(a.highlightPDF(source), 'Cached highlight');
  assert(cached.unchanged && cached.requests === 0 && cached.highlightCount === 3, 'Highlight cache did not reuse all marks');
  assert((await stats()).calls === calls && equal(marked, await IOUtils.read(chinesePath)), 'Cache reuse changed the PDF or called the API');
  result.cacheReused = true;

  Zotero.Prefs.set(prefix + 'model', 'error-401', true);
  let failure = '';
  try { await bounded(a.highlightPDF(source), 'Controlled failure'); } catch (error) { failure = String(error); }
  assert(failure.includes('401') || failure.includes('认证') || failure.includes('Key'), 'Controlled API failure was not returned');
  await idle();
  assert(equal(marked, await IOUtils.read(chinesePath)), 'API failure damaged the Chinese PDF');
  result.failurePreserved = true;

  Zotero.Prefs.set(prefix + 'model', 'fixture-completion-cancel', true);
  await control('fixture-completion-cancel', { delay: 8 });
  session.active.win.document.querySelector('.transyh-highlight').click();
  await poll(async () => {
    const cancel = session.active.win.document.querySelector('.transyh-cancel');
    return (await stats()).models['fixture-completion-cancel']?.active >= 1 && cancel && !cancel.hidden && !cancel.disabled;
  }, Boolean, 'In-flight toolbar cancellation');
  session.active.win.document.querySelector('.transyh-cancel').click();
  await idle();
  assert(equal(marked, await IOUtils.read(chinesePath)) && !chineseNote.deleted, 'Cancellation damaged the Chinese PDF or annotation');
  result.cancelPreserved = true;
  for (const language of ['en', 'zh']) {
    session.active.win.document.querySelector(`[data-language="${language}"]`).click();
    await bounded(session.switching || Promise.resolve(), 'Repeated language switch');
    assert(session.language === language && reader.tabID === tabID, 'Repeated native language switch failed');
  }
  assert(equal(english, await IOUtils.read(await source.getFilePathAsync())) && !englishNote.deleted, 'Original changed after failure or cancellation');
  assert(parent.getAttachments().length === 2 && !chinese.deleted && !chineseNote.deleted, 'Attachments or annotations were lost');
  result.sourcePreserved = result.annotationsPreserved = result.bilingualSwitch = true;
  result.chinesePath = chinesePath;

  await session.active.restore({ pageIndex: 0, scale: 100, top: 792, left: 0 });
  const canvas = await poll(() => {
    const view = Components.utils.waiveXrays(session.active.pdf.pdfViewer.getPageView(0));
    return view?.renderingState === 3 ? view.canvas : null;
  }, Boolean, 'Native Chinese PDF render');
  const bytes = session.active.win.atob(canvas.toDataURL('image/png').split(',')[1]);
  await IOUtils.write(PathUtils.join(output, 'native-completed.png'), Uint8Array.from(bytes, c => c.charCodeAt(0)));
  reader._window.Zotero_Tabs.close(tabID);
  await poll(() => !a.readers.sessions.has(tabID) && session.disposed && !session.other && session.paneCleanups.size === 0,
    Boolean, 'Tab close resource disposal');
  result.tabResourcesReleased = true;
  await checkpoint('all_native_checks_completed');
  return result;
} catch (error) {
  result.error = String(error);
  result.pendingTask = source ? a.translationStatus(source) : null;
  result.pendingSwitch = !!session?.switching;
  await checkpoint('failed');
  throw error;
} finally {
  Zotero.getMainWindow().clearInterval(monitor);
  a.engine.run = originalRun; a.readers.pdfUpdated = originalRefresh;
  Zotero.ProgressWindow = NativeProgressWindow;
  if (reader?._iframe?.isConnected) reader._window.Zotero_Tabs.close(reader.tabID);
  await a.store.flush();
}
