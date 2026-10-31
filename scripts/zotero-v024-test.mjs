// Bounded pre-release acceptance of the final XPI; loopback Mock, no translation.
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile, rm, open } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { host } from './host-command.mjs';

const root = path.resolve(import.meta.dirname, '..');
const { version } = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
const runtime = path.join(root, '.test-runtime/v024');
const profile = path.join(root, '.test-profile/v024');
const data = path.join(root, '.test-data/v024');
const output = path.join(root, 'tests/output/v024');
const python = path.join(root, '.venv/bin/python');
const binary = process.env.TRANSYH_ZOTERO || '/Applications/Zotero.app/Contents/MacOS/zotero';
const quote = JSON.stringify;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const results = { version, created: new Date().toISOString(),
  scope: 'One isolated native XPI acceptance, Responses and Chat Completions, synthetic PDFs, no BabelDOC translation or real API' };
for (const directory of [runtime, profile, data, output, path.join(profile, 'extensions')]) {
  await mkdir(directory, { recursive: true });
}
async function invoke(code, timeout = 20000) {
  const response = await host(code, timeout, runtime);
  if (!response.ok) throw new Error(response.error);
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
  'extensions.transyh.testRoot': root, 'app.update.auto': false, 'app.update.enabled': false,
};
await writeFile(path.join(profile, 'user.js'), Object.entries(prefs)
  .map(([key, value]) => `user_pref(${quote(key)}, ${quote(value)});`).join('\n'));
execFileSync(python, ['-c', `import sys
from pathlib import Path
sys.path.insert(0,'tests')
from highlight_fixtures import create_recall
import pymupdf
source=create_recall(Path('tests/output/v024/recall-before.pdf'))
with pymupdf.open(source) as doc:
 doc[0].add_text_annot((30,30),'Existing embedded PDF annotation')
 doc.saveIncr()
`], { cwd: root });
execFileSync(python, ['-c', `import pathlib,zipfile,sys
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as archive:
 for entry in pathlib.Path(sys.argv[1]).iterdir():
  if entry.is_file():archive.write(entry,entry.name)
`, path.join(root, 'tests/host-addon'), path.join(profile, 'extensions/transyh-tests@local.xpi')]);

let launched = false, mock;
try {
  try { results.environment = await invoke('return {profile:Zotero.Profile.dir,version:Zotero.version,pid:Services.appinfo.processID};', 1500); }
  catch {
    await rm(path.join(runtime, 'command.json'), { force: true });
    await rm(path.join(runtime, 'ready.json'), { force: true });
    const log = await open(path.join(runtime, 'zotero.log'), 'w');
    const child = spawn(binary, ['-no-remote', '-profile', profile, '-purgecaches'],
      { stdio: ['ignore', log.fd, log.fd], detached: true });
    child.unref(); await log.close(); launched = true;
    await poll(async () => {
      try { return JSON.parse(await readFile(path.join(runtime, 'ready.json'), 'utf8')); }
      catch { return null; }
    }, value => !!value, 60000, 'Isolated Zotero startup');
    results.environment = await invoke('return {profile:Zotero.Profile.dir,version:Zotero.version,pid:Services.appinfo.processID};');
  }
  assert.equal(results.environment.profile, profile, 'Requires the dedicated isolated test profile');
  console.log('Installing the final v0.2.4 XPI in isolated Zotero');
  results.install = await invoke(`const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
    await(await AddonManager.getInstallForFile(Zotero.File.pathToFile(${quote(path.join(root, `dist/TransYH-${version}.xpi`))}))).install();
    for(let i=0;i<200&&!Zotero.TransYH;i++)await Zotero.Promise.delay(50);
    const addon=await AddonManager.getAddonByID('transyh@local');
    if(!Zotero.TransYH||!addon.isActive)throw new Error('XPI did not initialize');
    const equal=(x,y)=>x.length===y.length&&x.every((v,i)=>v===y[i]);
    const files=['worker.py','api_client.py','highlight_jobs.py','highlight_pdf.py'];
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
  await invoke(`const a=Zotero.TransYH,p='extensions.transyh.';
    Zotero.Prefs.set(p+'baseURL',${quote(base)},true);
    Zotero.Prefs.set(p+'testAPIBase',${quote(base)},true);
    Zotero.Prefs.set(p+'pythonPath',${quote(python)},true);
    Zotero.Prefs.set(p+'concurrency','10',true);
    Zotero.Prefs.set(p+'autoHighlights','false',true);
    Zotero.Prefs.set(p+'highlightDensity','smart',true);
    await a.credentials.set(${quote(base)},'fixture-only-key');return true;`);
  console.log('Checking contextual highlights, native switching, annotations, progress and toolbar cancellation in both API modes');
  results.native = await invoke(await readFile(path.join(root, 'tests/zotero-v024.js'), 'utf8'), 150000);
  results.api = await (await fetch(`http://127.0.0.1:${port}/stats`)).json();
  for (const test of results.native.modes) {
    const suffix = test.mode === 'responses' ? '/responses' : '/chat/completions';
    for (const model of [test.model, test.cancelModel]) {
      const metrics = results.api.models[model];
      assert.ok(metrics.calls > 0 && metrics.paths.every(endpoint => endpoint === '/v1' + suffix));
      assert.ok(metrics.peakConcurrent >= 2 && metrics.peakConcurrent <= 10);
    }
  }
  await writeFile(path.join(output, 'zotero-results.json'), JSON.stringify(results, null, 2));
  execFileSync(python, ['-c', `import json,sys
sys.path.insert(0,'engine')
from highlight_pdf import verify_preserved,metadata
import pymupdf
data=json.load(open(sys.argv[1]))
for row in data['native']['modes']:
 verify_preserved(row['backupPath'],row['path'])
 with pymupdf.open(row['path']) as doc:
  assert metadata(doc)['count']==4
  assert len(list(doc[0].annots()))==1
print('Native PDF verification passed: text, geometry, images, embedded annotation and four highlights in both modes')
`, path.join(output, 'zotero-results.json')], { cwd: root, stdio: 'inherit' });
  results.pdfVerified = true;
  results.passed = true;
  console.log(JSON.stringify({ version, installed: results.install.active, modes: results.native.modes.map(test => ({
    mode: test.mode, highlights: test.highlightCount, requests: test.requests,
    progress: test.progressVisible, toolbarCancel: test.cancelPreserved, bilingualSwitch: test.bilingualSwitch,
  })), chineseSkipsAPI: results.native.chineseSkipsAPI, pdfVerified: true, passed: true }, null, 2));
} catch (error) {
  results.error = String(error);
  throw error;
} finally {
  mock?.kill();
  if (launched && results.environment?.profile === profile) {
    try {
      await invoke('await Zotero.TransYH?.store.flush();Zotero.getMainWindow().setTimeout(()=>Services.startup.quit(Components.interfaces.nsIAppStartup.eAttemptQuit),200);return true;', 5000);
      await poll(async () => {
        try { process.kill(results.environment.pid, 0); return false; } catch { return true; }
      }, value => value, 20000, 'Isolated Zotero shutdown');
    } catch (error) { results.cleanupError = String(error); }
  }
  await writeFile(path.join(output, 'zotero-results.json'), JSON.stringify(results, null, 2));
}
