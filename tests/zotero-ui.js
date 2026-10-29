const root = Zotero.Prefs.get('extensions.transyh.testRoot', true);
const ids = await IOUtils.readJSON(PathUtils.join(root, '.test-runtime', 'items.json'));
const apiBase = Zotero.Prefs.get('extensions.transyh.testAPIBase', true);
const assert = (ok, text) => { if (!ok) throw new Error(text); };
const a = Zotero.TransYH;
const s = [...a.readers.sessions.values()].find(x => x.source.id === ids.sourceID);
await s.switchTo('en');
const tab = s.reader.tabID, original = s.host.pdf.pdfDocument;
await s.reader._window.ZoteroPane.selectItem(ids.sourceID);
s.reader._window.document.getElementById('transyh-translate').dispatchEvent(new s.reader._window.Event('command'));
for (let i=0;i<100 && s.language!=='zh';i++) await Zotero.Promise.delay(50);
assert(s.language==='zh' && s.reader.tabID===tab, 'Actual menu command did not reuse the same tab');
Zotero.__transyhContextTest=false;
const params=Components.utils.waiveXrays(Components.utils.cloneInto({x:100,y:100,itemGroups:[[{label:'TransYH callback check',onCommand:()=>{Zotero.__transyhContextTest=true;}}]]},s.active.win,{cloneFunctions:true}));
s.active.internal._onOpenContextMenu(params);
const menu=Components.utils.waiveXrays(s.active.internal._state.contextMenu);
menu?.itemGroups?.[0]?.[0]?.onCommand?.();
s.active.internal.closeContextMenu();
assert(Zotero.__transyhContextTest, 'Native context-menu callback was lost');
Zotero.Utilities.Internal.openPreferences('transyh-preferences');
await Zotero.Promise.delay(400);
const w=Services.wm.getMostRecentWindow('zotero:pref'),d=w.document;
d.getElementById('transyh-base').value=apiBase;
d.getElementById('transyh-key').value='fixture-only-key';
async function clickTest(model) {
  d.getElementById('transyh-model').value=model;
  d.getElementById('transyh-test').click();
  for(let i=0;i<200&&d.getElementById('transyh-test').disabled;i++) await Zotero.Promise.delay(50);
  return d.getElementById('transyh-status').textContent;
}
const rateLimit=await clickTest('error-429');
const connection=await clickTest('fixture-connection');
w.close();
assert(rateLimit.includes('429') && connection.includes('连接成功'), 'Connection button did not report results');
const result={version:Zotero.version,rightClickCommand:true,sameTab:true,sameOriginalPDF:s.host.pdf.pdfDocument===original,
  nativeContextMenuCallback:true,apiButtonRateLimit:true,apiButtonConnection:true};
await IOUtils.writeJSON(PathUtils.join(root,'tests','output','native-ui-results.json'),result);
return result;
