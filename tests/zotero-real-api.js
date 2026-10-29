// Uses only the configured credentials held by Zotero's Login Manager.
const a=Zotero.TransYH;
const root=Zotero.Prefs.get('extensions.transyh.testRoot',true);
const model=Zotero.Prefs.get('extensions.transyh.model',true);
if(Zotero.Profile.dir!==PathUtils.join(root,'.test-profile')) throw new Error('Real API sample test requires the isolated profile');
const parent=new Zotero.Item('journalArticle');
parent.setField('title',`TransYH ${model} 真实 API 验证 2026-10-29`);
await parent.saveTx();
const source=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','fixtures','paper-english.pdf'),parentItemID:parent.id});
const reader=await Zotero.Reader.open(source.id);await reader._initPromise;await a.readers.attach(reader);
const initialTab=Zotero.getMainWindow().Zotero_Tabs._tabs.filter(x=>x.type==='reader').length;
Zotero.__transyhRealStatus={status:'running',sourceID:source.id,model};
const originalRun=a.engine.run.bind(a.engine);
a.engine.run=async(action,extra={},update=()=>{},run)=>originalRun(action,extra,event=>{
  if(action==='translate'&&event.type==='progress')Zotero.__transyhRealStatus={status:'running',sourceID:source.id,model,progress:event.progress,stage:event.message};
  update(event);
},run);
a.translate(source).then(async zh=>{
  await a.readers.showChinese(source);
  const s=[...a.readers.sessions.values()].find(x=>x.source.id===source.id);
  const initialPDF=s.host.pdf.pdfDocument;
  await s.active.restore({pageIndex:1,scale:145,top:540,left:0,scrollMode:0,spreadMode:0});
  const before=s.active.capture();
  await s.switchTo('en');await s.switchTo('zh');
  const after=s.active.capture();
  const reused=await a.translate(source);
  await IOUtils.copy(await zh.getFilePathAsync(),PathUtils.join(root,'tests','output','paper-chinese-group-api.pdf'));
  const result={status:'done',date:'2026-10-29',baseURL:Zotero.Prefs.get('extensions.transyh.baseURL',true),model,
    sourceID:source.id,translationID:zh.id,parentID:zh.parentID,tabID:s.reader.tabID,language:s.language,
    sameOriginalPDF:s.host.pdf.pdfDocument===initialPDF,tabCountBefore:initialTab,
    tabCountAfter:s.reader._window.Zotero_Tabs._tabs.filter(x=>x.type==='reader').length,
    reusedSameAttachment:reused.id===zh.id,before,after,path:await zh.getFilePathAsync()};
  await IOUtils.writeJSON(PathUtils.join(root,'tests','output','group-api-results.json'),result);
  Zotero.__transyhRealStatus=result;
}).catch(async e=>{
  const result={status:'error',model,message:e.message};
  await IOUtils.writeJSON(PathUtils.join(root,'tests','output','group-api-results.json'),result);
  Zotero.__transyhRealStatus=result;
});
return {started:true,sourceID:source.id,model};
