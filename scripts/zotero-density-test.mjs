// One focused density scenario in the existing isolated Zotero client.
import { spawn,execFileSync } from 'node:child_process';
import { mkdir,readFile,writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { host } from './host-command.mjs';

const root=path.resolve(import.meta.dirname,'..');
const profile=path.join(root,'.test-profile'),output=path.join(root,'tests/output');
const python=path.join(root,'.venv/bin/python');
const quote=JSON.stringify;
await mkdir(output,{recursive:true});
async function invoke(code,timeout=20000) {
  const response=await host(code,timeout);
  if(!response.ok)throw new Error(response.error);
  return response.result;
}
// No full client launch/restart or translation run in this focused check.
const environment=await invoke('return {profile:Zotero.Profile.dir,version:Zotero.version,pid:Services.appinfo.processID};',3000);
assert.equal(environment.profile,profile,'Requires the existing isolated test client');
execFileSync(python,['-c',`import sys;sys.path.insert(0,'tests');from highlight_fixtures import create_density
import pymupdf
create_density('tests/output/density-chinese.pdf')
with pymupdf.open() as pdf:
 for i in range(4):
  page=pdf.new_page(width=612,height=792);page.insert_text((46,80),'Synthetic density reference page '+str(i+1))
 pdf.save('tests/output/density-english.pdf')
`],{cwd:root});
await invoke(`const {AddonManager}=ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs');
 await(await AddonManager.getInstallForFile(Zotero.File.pathToFile(${quote(path.join(root,'dist/TransYH-0.2.0.xpi'))}))).install();
 await Zotero.Promise.delay(700);return !!Zotero.TransYH;`);
const mock=spawn(python,[path.join(root,'tests/mock_api.py'),'--port','0'],{stdio:['ignore','pipe','pipe']});
const port=await new Promise((resolve,reject)=>{
  mock.stdout.once('data',data=>{const match=String(data).match(/:(\d+)/);match?resolve(Number(match[1])):reject(new Error('Mock did not start'));});
  mock.once('error',reject);
});
const base=`http://127.0.0.1:${port}/v1`,model=`fixture-density-native-${Date.now()}`;
const results={environment,scope:'One density smoke scenario; no full regression or client restart'};
try {
  results.density=await invoke(`
const a=Zotero.TransYH,assert=(value,message)=>{if(!value)throw new Error(message);};
const prefix='extensions.transyh.';
const previous=Object.fromEntries(['baseURL','model','pythonPath','autoHighlights','highlightDensity'].map(key=>[key,Zotero.Prefs.get(prefix+key,true)]));
let reader,settings;
try {
 Zotero.Prefs.set(prefix+'baseURL',${quote(base)},true);
 Zotero.Prefs.set(prefix+'model',${quote(model)},true);
 Zotero.Prefs.set(prefix+'pythonPath',${quote(python)},true);
 await a.credentials.set(${quote(base)},'fixture-only-key');
 Zotero.Utilities.Internal.openPreferences('transyh-preferences');await Zotero.Promise.delay(400);
 settings=Services.wm.getMostRecentWindow('zotero:pref');
 const select=settings.document.getElementById('transyh-highlight-density');
 assert(select&&select.options.length===3,'Density setting is missing');
 assert(select.value==='smart','Fresh density must default to smart');
 async function choose(mode) {
  select.value=mode;settings.document.getElementById('transyh-save').click();
  for(let i=0;i<100&&Zotero.Prefs.get(prefix+'highlightDensity',true)!==mode;i++)await Zotero.Promise.delay(30);
  assert(Zotero.Prefs.get(prefix+'highlightDensity',true)===mode,'Density setting did not save');
 }
 await choose('full');
 const parent=new Zotero.Item('journalArticle');parent.setField('title','Density 0/1/3/5 synthetic smoke');await parent.saveTx();
 const source=await Zotero.Attachments.importFromFile({file:${quote(path.join(output,'density-english.pdf'))},parentItemID:parent.id});
 const original=await IOUtils.read(await source.getFilePathAsync()),info=await IOUtils.stat(await source.getFilePathAsync());
 const chinese=await Zotero.Attachments.importFromFile({file:${quote(path.join(output,'density-chinese.pdf'))},parentItemID:parent.id});
 chinese.addTag('TransYH:source:'+source.key,1);chinese.addTag('TransYH:stamp:'+info.size+':'+info.lastModified,1);await chinese.saveTx();
 const note=new Zotero.Item('annotation');note.parentID=chinese.id;note.libraryID=chinese.libraryID;
 note.annotationType='note';note.annotationComment='Existing note survives density updates';note.annotationColor='#ffd400';
 note.annotationPageLabel='1';note.annotationSortIndex='00000|000000|00000';
 note.annotationPosition=JSON.stringify({pageIndex:0,rects:[[20,200,30,220]]});await note.saveTx();
 reader=await Zotero.Reader.open(source.id);await reader._initPromise;await a.readers.attach(reader);await a.readers.showChinese(source);
 const session=[...a.readers.sessions.values()].find(s=>s.reader.tabID===reader.tabID);
 const englishPDF=session.host.pdf.pdfDocument;
 const first=await a.highlightPDF(source);
 assert(first.highlightCount===9&&first.requests===4,'Four pages must allow 0/1/3/5 highlights');
 const switches=[];
 for(const [mode,expected] of [['concise',3],['smart',7],['full',9]]) {
  await choose(mode);const result=await a.highlightPDF(source);
  assert(result.highlightCount===expected&&result.requests===0&&result.cachedBatches===4,'Density change must reuse the complete candidate pool');
  switches.push({mode,highlightCount:result.highlightCount,requests:result.requests,cachedBatches:result.cachedBatches});
 }
 const repeated=await a.highlightPDF(source);
 assert(repeated.unchanged&&repeated.highlightCount===9&&repeated.requests===0,'Repeat must not add marks or calls');
 await session.active.restore({pageIndex:3,scale:100,top:792,left:0});
 let canvas;
 for(let i=0;i<300;i++) {
  const view=Components.utils.waiveXrays(session.active.pdf.pdfViewer.getPageView(3));
  if(view?.canvas&&view.renderingState===3){canvas=view.canvas;break;}
  await Zotero.Promise.delay(30);
 }
 assert(canvas,'Native page did not render');
 const pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
 const colors={blue:0,orange:0,purple:0};
 for(let i=0;i<pixels.length;i+=4) {
  const r=pixels[i],g=pixels[i+1],b=pixels[i+2];
  if(r<180||g<180||b<180)continue;
  if(b>r+15&&g>r+4)colors.blue++;
  if(r>b+15&&g>b+4)colors.orange++;
  if(r>g+8&&b>g+12)colors.purple++;
 }
 assert(Object.values(colors).every(n=>n>0),'All three highlight colors must render in the native PDF');
 assert(parent.getAttachments().length===2,'Density update duplicated the Chinese attachment');
 assert(!note.deleted&&note.parentID===chinese.id&&note.annotationComment==='Existing note survives density updates','Density update lost a Zotero annotation');
 const after=await IOUtils.read(await source.getFilePathAsync());
 assert(original.length===after.length&&original.every((x,i)=>x===after[i]),'English original changed');
 assert(session.host.pdf.pdfDocument===englishPDF,'English PDF instance was replaced');
 return {defaultDensity:'smart',first:{highlightCount:first.highlightCount,requests:first.requests},switches,
  repeated:{unchanged:repeated.unchanged,requests:repeated.requests},renderedColors:colors,
  oneChineseAttachment:true,annotationPreserved:true,englishPreserved:true,pid:Services.appinfo.processID};
} finally {
 settings?.close();
 if(reader)reader._window.Zotero_Tabs.close(reader.tabID);
 for(const [key,value] of Object.entries(previous)) {
  if(value===undefined)Zotero.Prefs.clear(prefix+key,true);
  else Zotero.Prefs.set(prefix+key,value,true);
 }
 await a.store.flush();
}
`,120000);
  assert.equal(results.density.pid,environment.pid,'The focused smoke must not restart Zotero');
  results.apiCalls=(await(await fetch(`http://127.0.0.1:${port}/stats`)).json()).calls;
  assert.equal(results.apiCalls,4);
  results.passed=true;
  console.log(JSON.stringify(results,null,2));
} finally {
  await writeFile(path.join(output,'zotero-density-results.json'),JSON.stringify(results,null,2));
  mock.kill();
}
