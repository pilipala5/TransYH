import { spawn, execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile, rm, open } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { host } from './host-command.mjs';

const root = path.resolve(import.meta.dirname, '..');
const { version } = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
const runtime = path.join(root, '.test-runtime');
const profile = path.join(root, '.test-profile');
const data = path.join(root, '.test-data');
const output = path.join(root, 'tests/output');
const binary = process.env.TRANSYH_ZOTERO || '/Applications/Zotero.app/Contents/MacOS/zotero';
const python = path.join(root, '.venv', 'bin/python');
const delay = ms => new Promise(r => setTimeout(r, ms));
const quote = x => JSON.stringify(x);
for (const dir of [runtime, profile, data, output, path.join(profile, 'extensions')]) await mkdir(dir, { recursive: true });
async function invoke(code, timeout = 20000) {
  const r = await host(code, timeout);
  if (!r.ok) throw new Error(r.error);
  return r.result;
}
async function poll(get, predicate, timeout, label) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const result = await get();
    if (predicate(result)) return result;
    await delay(500);
  }
  throw new Error(label + ' timed out');
}
async function launch() {
  await rm(path.join(runtime, 'ready.json'), { force: true });
  const log = await open(path.join(runtime, 'zotero.log'), 'w');
  const child = spawn(binary, ['-no-remote', '-profile', profile, '-purgecaches'], { stdio: ['ignore', log.fd, log.fd], detached: true });
  child.unref(); await log.close();
  await poll(async () => { try { return JSON.parse(await readFile(path.join(runtime, 'ready.json'), 'utf8')); } catch { return null; } }, x => !!x, 60000, 'Zotero startup');
  return invoke(`for(let i=0;i<200&&!Zotero.TransYH;i++)await Zotero.Promise.delay(50);return {version:Zotero.version,pid:Services.appinfo.processID,profile:Zotero.Profile.dir,loaded:!!Zotero.TransYH};`);
}
async function quit() {
  const pid = await invoke(`Zotero.getMainWindow().setTimeout(()=>Services.startup.quit(Components.interfaces.nsIAppStartup.eAttemptQuit),250);return Services.appinfo.processID;`);
  await poll(async () => { try { process.kill(pid, 0); return false; } catch { return true; } }, x => x, 30000, 'Zotero shutdown');
}

const prefs = {
  'extensions.zotero.useDataDir': true, 'extensions.zotero.dataDir': data,
  'extensions.zotero.firstRun.skipFirefoxProfileAccessCheck': true,
  'extensions.zotero.firstRun2': false, 'extensions.zotero.firstRunGuidance': false,
  'extensions.zotero.sync.autoSync': false, 'extensions.zotero.httpServer.enabled': false,
  'extensions.autoDisableScopes': 0, 'extensions.enabledScopes': 15,
  'extensions.startupScanScopes': 15, 'extensions.transyh.testRuntime': runtime,
  'extensions.transyh.testRoot': root, 'app.update.auto': false, 'app.update.enabled': false,
};
await writeFile(path.join(profile, 'user.js'), Object.entries(prefs).map(([k,v])=>`user_pref(${quote(k)}, ${quote(v)});`).join('\n'));
execFileSync(python, [path.join(root, 'tests/make_fixtures.py')]);
execFileSync('python3', ['-c', 'import pathlib,zipfile,sys; d=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED); [z.write(p,p.name) for p in d.iterdir() if p.is_file()]; z.close()', path.join(root, 'tests/host-addon'), path.join(profile, 'extensions/transyh-tests@local.xpi')]);

let environment;
try { environment = await invoke('return {version:Zotero.version,pid:Services.appinfo.processID,profile:Zotero.Profile.dir,loaded:!!Zotero.TransYH};', 2000); }
catch { environment = await launch(); }
assert.equal(environment.profile, profile, 'Refusing to test against a non-isolated profile');
await invoke(`Zotero.Prefs.set('extensions.transyh.testRoot',${quote(root)},true);const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');await(await AddonManager.getInstallForFile(Zotero.File.pathToFile(${quote(path.join(root,`dist/TransYH-${version}.xpi`))}))).install();await Zotero.Promise.delay(700);return !!Zotero.TransYH;`);

const mock = spawn(python, [path.join(root, 'tests/mock_api.py'), '--port', '0'], { stdio: ['ignore','pipe','pipe'] });
const mockPort = await new Promise((resolve,reject) => {
  mock.stdout.once('data', data => { const m=String(data).match(/:(\d+)/);m?resolve(Number(m[1])):reject(new Error('Mock failed to start')); });
  mock.once('error',reject);
});
const baseURL = `http://127.0.0.1:${mockPort}/v1`;
const stats = async () => (await (await fetch(`http://127.0.0.1:${mockPort}/stats`)).json()).calls;
const results = { environment, created: new Date().toISOString() };
try {
  console.log('Testing installed XPI: API, encrypted credentials, preference pane');
  results.settings = await invoke(`const a=Zotero.TransYH;Zotero.Prefs.set('extensions.transyh.baseURL',${quote(baseURL)},true);Zotero.Prefs.set('extensions.transyh.model','fixture-connection',true);Zotero.Prefs.set('extensions.transyh.pythonPath',${quote(python)},true);await a.credentials.set(${quote(baseURL)},'fixture-only-key');const connection=await a.engine.run('test');const check=await a.engine.run('check');Zotero.Utilities.Internal.openPreferences('transyh-preferences');await Zotero.Promise.delay(400);const w=Services.wm.getMostRecentWindow('zotero:pref');const ok=!!w.document.getElementById('transyh-test');w.close();return {connection:connection.type,engine:check.version,credentials:a.credentials.get(${quote(baseURL)})==='fixture-only-key',pane:ok};`);
  assert.equal(results.settings.pane,true);assert.equal(results.settings.credentials,true);
  console.log('Testing single-tab native PDF switching');
  results.switching = await invoke(await readFile(path.join(root,'tests/zotero-phase-a.js'),'utf8'),60000);
  assert.ok(results.switching.cachedSwitchMilliseconds.every(ms=>ms<500));
  await invoke(`Zotero.Prefs.set('extensions.transyh.testAPIBase',${quote(baseURL)},true);return true;`);
  results.nativeUI = await invoke(await readFile(path.join(root,'tests/zotero-ui.js'),'utf8'),30000);

  const source = await invoke(`const p=new Zotero.Item('journalArticle');p.setField('title','TransYH end-to-end test');await p.saveTx();const s=await Zotero.Attachments.importFromFile({file:${quote(path.join(root,'tests/fixtures/paper-english.pdf'))},parentItemID:p.id});return {id:s.id,key:s.key,parentID:p.id,info:await IOUtils.stat(await s.getFilePathAsync())};`);
  results.source = { id:source.id, key:source.key };
  console.log('Testing cancellation and retry');
  await invoke(`Zotero.Prefs.set('extensions.transyh.model','slow',true);Zotero.__transyhStatus={status:'running'};Zotero.TransYH.translate(Zotero.Items.get(${source.id})).then(()=>Zotero.__transyhStatus={status:'unexpected-done'}).catch(e=>Zotero.__transyhStatus={status:'cancelled',message:e.message});return true;`);
  await delay(700);
  await invoke(`await Zotero.TransYH.cancelTranslation(Zotero.Items.get(${source.id}));return true;`);
  results.cancellation = await poll(()=>invoke('return Zotero.__transyhStatus;'),r=>r.status!=='running',15000,'Cancellation');
  assert.equal(results.cancellation.status,'cancelled');assert.match(results.cancellation.message,/取消/);

  const before = await stats();
  const model = `fixture-e2e-${Date.now()}`;
  console.log('Testing real BabelDOC pipeline against Mock API');
  await invoke(`const a=Zotero.TransYH,s=Zotero.Items.get(${source.id});Zotero.Prefs.set('extensions.transyh.model',${quote(model)},true);const reader=await Zotero.Reader.open(s.id);await reader._initPromise;await a.readers.attach(reader);Zotero.__transyhStatus={status:'running'};a.translate(s).then(async zh=>{await a.readers.showChinese(s);const session=[...a.readers.sessions.values()].find(x=>x.source.id===s.id);Zotero.__transyhStatus={status:'done',zhID:zh.id,path:await zh.getFilePathAsync(),tabID:session.reader.tabID,language:session.language};}).catch(e=>Zotero.__transyhStatus={status:'error',message:e.message});return true;`);
  results.progress = await poll(()=>invoke(`return Zotero.TransYH.translationStatus(Zotero.Items.get(${source.id}));`),r=>r?.activeRequests>=2,60000,'Concurrent translation requests');
  results.progress.reopened = await invoke(`const a=Zotero.TransYH;for(const w of Services.wm.getEnumerator(null)){if(w.location.href==='chrome://zotero/content/progressWindow.xhtml'&&w.document.documentElement.textContent.includes('已耗时'))w.close();}a.showTranslationProgress(Zotero.Items.get(${source.id}));await Zotero.Promise.delay(200);return [...Services.wm.getEnumerator(null)].some(w=>w.location.href==='chrome://zotero/content/progressWindow.xhtml'&&w.document.documentElement.textContent.includes('已耗时'));`);
  assert.equal(results.progress.reopened,true);
  results.translation = await poll(()=>invoke('return Zotero.__transyhStatus;'),r=>r.status!=='running',600000,'Full translation');
  assert.equal(results.translation.status,'done');assert.equal(results.translation.language,'zh');
  results.translation.apiCalls = await stats()-before;
  const modelStats=(await(await fetch(`http://127.0.0.1:${mockPort}/stats`)).json()).models[model];
  results.translation.peakConcurrent=modelStats.peakConcurrent;
  assert.ok(modelStats.peakConcurrent>=2&&modelStats.peakConcurrent<=4);
  assert.ok(results.translation.apiCalls>0);
  await invoke(`await IOUtils.copy(${quote(results.translation.path)},${quote(path.join(output,'paper-chinese-mock.pdf'))});return true;`);
  const beforeReuse = await stats();
  const reused = await invoke(`const source=Zotero.Items.get(${source.id}),zh=await Zotero.TransYH.translate(source);return {id:zh.id,info:await IOUtils.stat(await source.getFilePathAsync())};`);
  assert.equal(reused.id,results.translation.zhID);assert.equal(await stats(),beforeReuse);
  assert.equal(reused.info.size,source.info.size);assert.equal(reused.info.lastModified,source.info.lastModified);
  results.reuse = { sameAttachment:true, additionalAPICalls:0, originalSizeAndTimeUnchanged:true };

  const beforeParagraphCache=await stats();
  const cached=await invoke(`return await Zotero.TransYH.engine.run('translate',{input:${quote(path.join(root,'tests/fixtures/paper-english.pdf'))},outputDir:${quote(path.join(runtime,'cached-worker-output'))},concurrency:2});`,60000);
  assert.equal(await stats(),beforeParagraphCache);assert.ok(cached.cachedParagraphs>0);
  results.paragraphCache={cachedParagraphs:cached.cachedParagraphs,additionalAPICalls:0,concurrencyChanged:4+' -> '+2};

  console.log('Testing v0.1.4 refresh, quality tracking, idle writes and tab teardown');
  await writeFile(path.join(runtime,'v014-items.json'),JSON.stringify({sourceID:source.id,oldZHID:results.translation.zhID}));
  const beforeRefresh=(await(await fetch(`http://127.0.0.1:${mockPort}/stats`)).json()).models[model].calls;
  results.v014=await invoke(await readFile(path.join(root,'tests/zotero-v014.js'),'utf8'),600000);
  const afterRefresh=(await(await fetch(`http://127.0.0.1:${mockPort}/stats`)).json()).models[model].calls;
  results.v014.refreshAPICalls=afterRefresh-beforeRefresh;
  assert.ok(results.v014.refreshAPICalls>0,'Refresh must bypass the already warm paragraph cache');
  assert.equal(results.v014.idleStateWrites,0);
  assert.ok(results.v014.closedTabs>=2);
  const expectedZHID=results.v014.newZHID;

  console.log('Testing restart persistence');
  results.beforeRestart = await invoke(`const a=Zotero.TransYH;await a.readers.showChinese(Zotero.Items.get(${source.id}));const s=[...a.readers.sessions.values()].find(x=>x.source.id===${source.id});await s.active.restore({pageIndex:1,scale:133,top:555,left:0,scrollMode:0,spreadMode:0});s.save();await a.store.flush();s.reader._window.Zotero_Tabs.select(s.reader.tabID);return {state:s.active.capture(),language:s.language};`);
  await quit();
  results.restartedEnvironment = await launch();
  results.restart = await poll(()=>invoke(`const a=Zotero.TransYH;const s=[...a.readers.sessions.values()].find(x=>x.source.id===${source.id});return s?{language:s.language,state:s.active.capture(),sourceID:s.source.id,credentialRestored:a.credentials.get(${quote(baseURL)})==='fixture-only-key'}:null;`),r=>r?.language==='zh',60000,'Restored reader');
  assert.equal(results.restart.state.pageIndex,1);assert.equal(results.restart.state.scale,133);
  assert.ok(Math.abs(results.restart.state.top-results.beforeRestart.state.top)<4);
  assert.equal(results.restart.credentialRestored,true);
  const finalCalls = await stats();
  const reopened = await invoke(`const z=await Zotero.TransYH.translate(Zotero.Items.get(${source.id}));return z.id;`);
  assert.equal(reopened,expectedZHID);assert.equal(await stats(),finalCalls);
  results.restart.reusedAttachmentWithoutAPICall=true;
  results.passed=true;
  console.log('Zotero integration checks passed');
} finally {
  await writeFile(path.join(output,'zotero-results.json'),JSON.stringify(results,null,2));
  mock.kill();
}
