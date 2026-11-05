// One bounded native acceptance of the final XPI and the first-switch call chain.
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile, open } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { host } from './host-command.mjs';

const root = path.resolve(import.meta.dirname, '..');
const { version } = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
const attempt = Number(process.env.TRANSYH_V025_ATTEMPT || 1);
assert.ok(Number.isSafeInteger(attempt) && attempt >= 1);
const suite = attempt === 1 ? 'v025' : `v025-${attempt}`;
const runtime = path.join(root, '.test-runtime', suite);
const profile = path.join(root, '.test-profile', suite);
const data = path.join(root, '.test-data', suite);
const output = path.join(root, 'tests/output', suite);
const python = path.join(root, '.venv/bin/python');
const binary = process.env.TRANSYH_ZOTERO || '/Applications/Zotero.app/Contents/MacOS/zotero';
const quote = JSON.stringify;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const results = { version, attempt, created: new Date().toISOString(),
  scope: 'Final XPI, isolated Zotero 10, authored English PDF, actual BabelDOC translation, loopback Mock, automatic highlights and completion' };
// Refuse to reuse a previous run or a daily profile, including after a timeout.
await mkdir(profile, { recursive: false });
for (const directory of [runtime, data, output, path.join(profile, 'extensions')]) {
  await mkdir(directory, { recursive: true });
}
async function invoke(code, timeout = 20000) {
  const response = await host(code, timeout, runtime);
  if (!response.ok) throw new Error(response.error + '\n' + response.stack);
  return response.result;
}
async function poll(get, accept, timeout, label) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const value = await get();
    if (accept(value)) return value;
    await delay(200);
  }
  throw new Error(label + ' timed out');
}
const prefs = {
  'extensions.zotero.useDataDir': true, 'extensions.zotero.dataDir': data,
  'extensions.zotero.firstRun.skipFirefoxProfileAccessCheck': true,
  'extensions.zotero.firstRun2': false, 'extensions.zotero.firstRunGuidance': false,
  'extensions.zotero.sync.autoSync': false, 'extensions.zotero.httpServer.enabled': false,
  'extensions.autoDisableScopes': 0, 'extensions.enabledScopes': 15,
  'extensions.startupScanScopes': 15, 'extensions.transyh.testRuntime': runtime,
  'extensions.transyh.testRoot': root, 'extensions.transyh.testSuite': suite,
  'app.update.auto': false, 'app.update.enabled': false,
};
await writeFile(path.join(profile, 'user.js'), Object.entries(prefs)
  .map(([key, value]) => `user_pref(${quote(key)}, ${quote(value)});`).join('\n'));
execFileSync(python, [path.join(root, 'tests/completion_fixture.py'), path.join(output, 'english.pdf')], { cwd: root });
execFileSync(python, ['-c', `import pathlib,zipfile,sys
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as archive:
 for entry in pathlib.Path(sys.argv[1]).iterdir():
  if entry.is_file():archive.write(entry,entry.name)
`, path.join(root, 'tests/host-addon'), path.join(profile, 'extensions/transyh-tests@local.xpi')]);

let child, mock, mockBase;
try {
  const log = await open(path.join(runtime, 'zotero.log'), 'w');
  child = spawn(binary, ['-no-remote', '-profile', profile, '-purgecaches'],
    { stdio: ['ignore', log.fd, log.fd], detached: true });
  child.unref(); await log.close();
  results.environment = await poll(async () => {
    try { return JSON.parse(await readFile(path.join(runtime, 'ready.json'), 'utf8')); }
    catch { return null; }
  }, Boolean, 60000, 'Isolated Zotero startup');
  assert.equal(results.environment.profile, profile);
  assert.equal(results.environment.data, data);
  assert.match(results.environment.version, /^10\./);
  console.log('Installing the final v0.2.5 XPI in isolated Zotero ' + results.environment.version);
  results.install = await invoke(`const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
    await(await AddonManager.getInstallForFile(Zotero.File.pathToFile(${quote(path.join(root, `dist/TransYH-${version}.xpi`))}))).install();
    for(let i=0;i<200&&!Zotero.TransYH;i++)await Zotero.Promise.delay(50);
    const addon=await AddonManager.getAddonByID('transyh@local');
    if(!Zotero.TransYH||!addon.isActive)throw new Error('Final XPI did not initialize');
    const equal=(x,y)=>x.length===y.length&&x.every((v,i)=>v===y[i]);
    const files=['worker.py','api_client.py','performance.py','quality.py','refresh_tasks.py',
      'highlight_jobs.py','highlight_pdf.py','highlight_install.py','macos_keychain.py'];
    for(const file of files){
      const installed=await IOUtils.read(PathUtils.join(Zotero.DataDirectory.dir,'transyh','engine-${version}',file));
      const source=await IOUtils.read(PathUtils.join(${quote(root)},'engine',file));
      if(!equal(installed,source))throw new Error('Installed engine differs: '+file);
    }
    return {version:addon.version,active:addon.isActive,engineFilesMatch:files};`);
  assert.equal(results.install.version, version);
  mock = spawn(python, [path.join(root, 'tests/mock_api.py'), '--port', '0'], { stdio: ['ignore', 'pipe', 'pipe'] });
  const port = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Mock startup timed out')), 10000);
    mock.stdout.once('data', chunk => {
      clearTimeout(timer);
      const match = String(chunk).match(/:(\d+)/);
      match ? resolve(Number(match[1])) : reject(new Error('Mock failed to start'));
    });
    mock.once('error', error => { clearTimeout(timer); reject(error); });
  });
  const base = `http://127.0.0.1:${port}/v1`;
  mockBase = base;
  await invoke(`const p='extensions.transyh.';
    for(const [key,value] of Object.entries({baseURL:${quote(base)},testAPIBase:${quote(base)},
      httpAllowedBase:${quote(base)},pythonPath:${quote(python)},concurrency:'4',
      autoHighlights:'true',highlightDensity:'smart',apiMode:'responses',model:'fixture-completion-responses'}))
      Zotero.Prefs.set(p+key,value,true);
    await Zotero.TransYH.credentials.set(${quote(base)},'fixture-only-key');return true;`);
  console.log('Running first Chinese toolbar click -> translation -> automatic highlights -> reader completion');
  results.native = await invoke(await readFile(path.join(root, 'tests/zotero-v025.js'), 'utf8'), 180000);
  results.api = await (await fetch(`http://127.0.0.1:${port}/stats`)).json();
  assert.ok(results.api.models['fixture-completion-responses'].calls >= 2);
  assert.ok(results.api.models['fixture-completion-responses'].paths.every(p => p === '/v1/responses'));
  assert.ok(results.api.models['fixture-completion-chat'].paths.every(p => p === '/v1/chat/completions'));
  await writeFile(path.join(output, 'zotero-results.json'), JSON.stringify(results, null, 2));
  execFileSync(python, ['-c', `import json,sys
sys.path.insert(0,'engine')
from highlight_pdf import verify_preserved,metadata
import pymupdf
data=json.load(open(sys.argv[1]))['native']
verify_preserved(data['backupPath'],data['chinesePath'])
with pymupdf.open(data['chinesePath']) as doc:
 assert metadata(doc)['count']==3
 assert len(doc)==1
print('PDF verification passed: three marks, preserved text, geometry and graphics')
`, path.join(output, 'zotero-results.json')], { cwd: root, stdio: 'inherit' });
  results.passed = true;
  console.log(JSON.stringify({ version, installed: results.install.active, ...results.native, passed: true }, null, 2));
} catch (error) {
  results.error = String(error);
  process.exitCode = 1;
  console.error(String(error));
} finally {
  if (mockBase) {
    try {
      results.api = await (await fetch(mockBase.slice(0, -3) + '/stats', { signal: AbortSignal.timeout(2000) })).json();
    } catch { /* Native checkpoints and worker reports remain available on failure. */ }
  }
  mock?.kill();
  if (results.environment?.profile === profile) {
    try {
      await invoke('await Zotero.TransYH?.store.flush();Zotero.getMainWindow().setTimeout(()=>Services.startup.quit(Components.interfaces.nsIAppStartup.eAttemptQuit),200);return true;', 5000);
      await poll(async () => {
        try { process.kill(results.environment.pid, 0); return false; } catch { return true; }
      }, Boolean, 20000, 'Isolated Zotero shutdown');
      results.isolatedShutdown = true;
    } catch (error) {
      results.cleanupError = String(error); process.exitCode = 1;
      // Only the child launched with this isolated profile can be terminated.
      if (child.pid === results.environment.pid) child.kill('SIGTERM');
    }
  }
  await writeFile(path.join(output, 'zotero-results.json'), JSON.stringify(results, null, 2));
}
