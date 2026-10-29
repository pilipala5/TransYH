// Runs only in the isolated client after the end-to-end Mock translation.
const root = Zotero.Prefs.get('extensions.transyh.testRoot', true);
if (Zotero.Profile.dir !== PathUtils.join(root, '.test-profile')) throw new Error('Requires isolated profile');
const assert = (value, message) => { if (!value) throw new Error(message); };
const releasedTask = task => { try { return task.destroyed; } catch { return Components.utils.isDeadWrapper(task); } };
const a = Zotero.TransYH;
const input = await IOUtils.readJSON(PathUtils.join(root, '.test-runtime', 'v014-items.json'));
const source = Zotero.Items.get(input.sourceID), oldZH = Zotero.Items.get(input.oldZHID);
const session = [...a.readers.sessions.values()].find(s => s.source.id === source.id);
assert(session, 'Missing live source session');
const tabID = session.reader.tabID, originalPDF = session.host.pdf.pdfDocument;
const oldBrowser = session.other.browser, oldTask = session.other.pdf.pdfLoadingTask;
const oldPath = await oldZH.getFilePathAsync(), oldInfo = await IOUtils.stat(oldPath);
// Put an actual user-style annotation on the superseded Chinese attachment.
const annotation = new Zotero.Item('annotation');
annotation.parentID = oldZH.id; annotation.libraryID = oldZH.libraryID;
annotation.annotationType = 'note'; annotation.annotationComment = 'TransYH fixture annotation must survive refresh';
annotation.annotationColor = '#ffd400'; annotation.annotationPageLabel = '1';
annotation.annotationSortIndex = '00000|000000|00000';
annotation.annotationPosition = JSON.stringify({ pageIndex: 0, rects: [[60,600,80,620]] });
await annotation.saveTx();
await session.active.restore({pageIndex:1, scale:145, top:540, left:0, scrollMode:0, spreadMode:0});
const before = session.active.capture();
const newZH = await a.retranslate(source);
assert(newZH.id !== oldZH.id, 'Refresh reused old attachment');
assert(session.language === 'zh' && session.reader.tabID === tabID, 'Refresh did not replace the active Chinese view in its tab');
assert(session.host.pdf.pdfDocument === originalPDF, 'Refresh reloaded the English PDF');
assert(session.other.browser !== oldBrowser && !oldBrowser.isConnected, 'Superseded PDF browser was not released');
assert(releasedTask(oldTask), 'Superseded PDF.js loading task was not destroyed');
assert(!oldZH.deleted && await oldZH.fileExists(), 'Refresh deleted the old translation');
assert(Zotero.Items.get(annotation.id)?.parentID === oldZH.id, 'Refresh removed old annotations');
assert((await IOUtils.stat(oldPath)).lastModified === oldInfo.lastModified, 'Old translation file was modified');
const after = session.active.capture();
assert(after.pageIndex === before.pageIndex && after.scale === before.scale && Math.abs(after.top-before.top)<=3, 'Refresh lost view state');
assert((await a.translate(source)).id === newZH.id, 'Ordinary translate did not select the latest version');
const tags = newZH.getTags().map(x=>x.tag);
assert(tags.every(t=>/^TransYH:(source|stamp|version):/.test(t)), 'Attachment contains unexpected metadata');
const jobRoot = PathUtils.join(Zotero.DataDirectory.dir,'transyh','jobs',`${source.libraryID}-${source.key}`);
const jobs = (await IOUtils.getChildren(jobRoot)).sort();
const quality = await IOUtils.readJSON(PathUtils.join(jobs[jobs.length-1], 'quality-report.json'));
assert(quality.trackingAvailable && quality.checkedParagraphs > 0, 'BabelDOC tracking was not audited');
assert(quality.status !== 'structural_error', 'Structural errors were delivered');
// No provider call here: a deterministic Mock authentication failure must keep
// both the latest attachment and the already loaded PDF usable.
const currentPDF = session.active.pdf.pdfDocument;
const oldModel = Zotero.Prefs.get('extensions.transyh.model', true);
Zotero.Prefs.set('extensions.transyh.model','error-401',true);
let failure = '';
try { await a.retranslate(source); } catch(e) { failure = e.message; }
finally { Zotero.Prefs.set('extensions.transyh.model',oldModel,true); }
assert(failure.includes('401'), 'Expected refresh failure was not reported');
assert(session.active.pdf.pdfDocument === currentPDF && session.language === 'zh', 'Failed refresh broke the readable PDF');
assert((await a.translate(source)).id === newZH.id, 'Failed refresh displaced the latest usable attachment');
assert(!newZH.deleted && await newZH.fileExists(), 'Failed refresh damaged the new attachment');
// Exercise a tab opened directly on a legacy Chinese attachment, then update it.
const zhReader = await Zotero.Reader.open(oldZH.id);
await zhReader._initPromise;
const zhSession = await a.readers.attach(zhReader);
await zhSession.useTranslation(newZH);
assert(zhSession.active !== zhSession.host && zhSession.language === 'zh', 'A Chinese-origin tab kept a stale version');
await zhSession.switchTo('en'); await zhSession.switchTo('zh');
assert(zhSession.language === 'zh', 'Chinese-origin tab could not switch after refresh');
await zhSession.switchTo('en');
// Measure real calls to the existing local writer during idle native reads.
await a.store.flush();
let idleWrites = 0, idleSaves = 0;
const readingPath = PathUtils.join(Zotero.DataDirectory.dir,'transyh','reading.json');
let lastModified = (await IOUtils.stat(readingPath)).lastModified;
const save = a.store.save;
a.store.save = function(...args) { idleSaves++; return save.apply(this,args); };
const idleStart = Date.now();
try {
  while(Date.now()-idleStart < 5500) {
    await Zotero.Promise.delay(100);
    const modified = (await IOUtils.stat(readingPath)).lastModified;
    if(modified !== lastModified) { idleWrites++; lastModified = modified; }
  }
} finally { a.store.save = save; }
assert(idleWrites === 0, 'Idle PDF readers still write reading.json repeatedly');
assert(idleSaves === 0, 'Unchanged sessions still submit reading state repeatedly');
// Close several real, bilingual native tabs. Measure owned resources separately
// from process RSS, whose allocator/PDF caches need not immediately shrink.
const sessions = [...a.readers.sessions.values()].filter(s=>s.source.id!==source.id && s.reader._iframe?.isConnected);
sessions.push(zhSession);
const unique = [...new Set(sessions)];
const extra = unique.map(s=>s.other).filter(Boolean);
const tasks = extra.map(p=>p.pdf.pdfLoadingTask);
const manager = Components.classes['@mozilla.org/memory-reporter-manager;1'].getService(Components.interfaces.nsIMemoryReporterManager);
const residentBefore = manager.resident;
for (const s of unique) s.reader._window.Zotero_Tabs.close(s.reader.tabID);
for (let i=0;i<100 && unique.some(s=>a.readers.sessions.has(s.reader.tabID));i++) await Zotero.Promise.delay(50);
assert(unique.every(s=>!a.readers.sessions.has(s.reader.tabID)), 'Closed tab sessions remain registered');
assert(extra.every(p=>!p.browser.isConnected && !p.internal), 'Closed secondary readers retain native realms');
assert(tasks.every(releasedTask), 'Closed PDF loading tasks were not destroyed');
assert(unique.every(s=>s.paneCleanups.size===0 && !s.requested), 'Closed readers retain observers or queued switches');
Components.utils.forceGC();
await Zotero.Promise.delay(300);
const residentAfter = manager.resident;
// Close a tab while its first auxiliary PDF browser is being initialized.
const closingSource = unique.find(s=>s.source.id!==source.id)?.source;
assert(closingSource, 'Need another source for close-during-load test');
a.store.save(closingSource,{language:'en',state:{pageIndex:1,scale:125,top:500,left:0}});
const closingReader = await Zotero.Reader.open(closingSource.id);
await closingReader._initPromise;
const closingSession = await a.readers.attach(closingReader);
const loading = closingSession.switchTo('zh');
for(let i=0;i<100&&!closingReader._tabContainer.querySelector('.transyh-reader');i++) await Zotero.Promise.delay(10);
const pendingBrowser = closingReader._tabContainer.querySelector('.transyh-reader');
assert(pendingBrowser, 'Auxiliary load never started');
closingReader._window.Zotero_Tabs.close(closingReader.tabID);
await loading.catch(()=>{});
for(let i=0;i<60&&a.readers.sessions.has(closingReader.tabID);i++) await Zotero.Promise.delay(50);
assert(!a.readers.sessions.has(closingReader.tabID) && !pendingBrowser.isConnected && !closingSession.other,
  'Closing during PDF initialization leaked a pane or session');
return {newZHID:newZH.id, oldZHID:oldZH.id, annotationPreserved:!Zotero.Items.get(annotation.id).deleted,
  refreshSameTab:session.reader.tabID===tabID, englishPDFReused:session.host.pdf.pdfDocument===originalPDF,
  before,after,quality:{status:quality.status,trackingAvailable:quality.trackingAvailable,paragraphs:quality.checkedParagraphs,issues:quality.issues},
  failurePreservesLatest:true, chineseOriginTab:true, idleSeconds:5.5,idleStateWrites:idleWrites,idleSaveCalls:idleSaves,
  closedTabs:unique.length,releasedPDFTasks:tasks.length,remainingClosedSessions:0,residentBefore,residentAfter,closeDuringLoad:true};
