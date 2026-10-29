// Actual Zotero attachment update, annotation retention and native canvas QA.
const root=Zotero.Prefs.get('extensions.transyh.testRoot',true);
if (Zotero.Profile.dir!==PathUtils.join(root,'.test-profile')) throw new Error('Requires isolated profile');
const base=Zotero.Prefs.get('extensions.transyh.testAPIBase',true);
if (!/^http:\/\/127\.0\.0\.1:\d+\/v1$/.test(base)) throw new Error('Requires local Mock');
const a=Zotero.TransYH;
const assert=(condition,message)=>{if(!condition)throw new Error(message);};
const delay=ms=>Zotero.Promise.delay(ms);
const originalRun=a.engine.run;
const previousModel=Zotero.Prefs.get('extensions.transyh.model',true);
const model=`fixture-highlight-native-${Date.now()}`;
const api=base.slice(0,-3);
const control=async (model,options)=>Zotero.HTTP.request('POST',api+'/control',{
  headers:{'Content-Type':'application/json'},body:JSON.stringify({model,...options})});
const counters=async model=>(await Zotero.HTTP.request('GET',api+'/stats',{responseType:'json'})).response.models[model];
const equalBytes=(x,y)=>x.length===y.length&&x.every((v,i)=>v===y[i]);
const released=task=>{try{return task.destroyed;}catch{return Components.utils.isDeadWrapper(task);}};
const opened=[];
async function capture(session,label) {
  const saved=session.active.capture();
  for (const pageNumber of [1,2]) {
    await session.active.restore({pageIndex:pageNumber-1,scale:100,top:792,left:0});
    let canvas;
    for(let i=0;i<300;i++) {
      const view=Components.utils.waiveXrays(session.active.pdf.pdfViewer.getPageView(pageNumber-1));
      if(view?.canvas&&view.renderingState===3){canvas=view.canvas;break;}
      await delay(50);
    }
    if(!canvas)throw new Error('Native page canvas did not finish rendering');
    const bytes=session.active.win.atob(canvas.toDataURL('image/png').split(',')[1]);
    await IOUtils.write(PathUtils.join(root,'tests','output',`native-highlights-${label}-page-${pageNumber}.png`),
      Uint8Array.from(bytes,x=>x.charCodeAt(0)));
  }
  await session.active.restore(saved);
}
async function newPair(title,withChinese=true) {
  const p=new Zotero.Item('journalArticle');p.setField('title',title);await p.saveTx();
  const source=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','fixtures','paper-english.pdf'),parentItemID:p.id});
  let chinese;
  if (withChinese) {
    const path=await source.getFilePathAsync(),info=await IOUtils.stat(path);
    chinese=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','output','highlights-before.pdf'),parentItemID:p.id});
    chinese.addTag('TransYH:source:'+source.key,1);chinese.addTag(`TransYH:stamp:${info.size}:${info.lastModified}`,1);
    await chinese.saveTx();
  }
  return {parent:p,source,chinese};
}
try {
  assert(typeof a.highlightPDF==='function','New XPI did not expose AI highlights');
  assert(Zotero.Prefs.get('extensions.transyh.autoHighlights',true)!==true&&Zotero.Prefs.get('extensions.transyh.autoHighlights',true)!=='true','Automatic highlights must default off');
  Zotero.Prefs.set('extensions.transyh.model',model,true);
  Zotero.Utilities.Internal.openPreferences('transyh-preferences');await delay(400);
  const settingsWindow=Services.wm.getMostRecentWindow('zotero:pref');
  const checkbox=settingsWindow.document.getElementById('transyh-auto-highlights');
  assert(checkbox&&!checkbox.checked,'New preference checkbox is missing or defaults on');
  for(const enabled of [true,false]) {
    checkbox.checked=enabled;settingsWindow.document.getElementById('transyh-save').click();
    for(let i=0;i<100&&Zotero.Prefs.get('extensions.transyh.autoHighlights',true)!==String(enabled);i++)await delay(50);
    assert(Zotero.Prefs.get('extensions.transyh.autoHighlights',true)===String(enabled),'New checkbox did not save its preference');
  }
  settingsWindow.close();
  const {parent,source,chinese}=await newPair('AI highlights user-reviewed synthetic sample');
  const originalBytes=await IOUtils.read(await chinese.getFilePathAsync());
  const englishBytes=await IOUtils.read(await source.getFilePathAsync());
  const count=parent.getAttachments().length;
  const note=new Zotero.Item('annotation');note.parentID=chinese.id;note.libraryID=chinese.libraryID;
  note.annotationType='note';note.annotationComment='Existing Zotero note must remain after AI highlights';
  note.annotationColor='#ffd400';note.annotationPageLabel='2';note.annotationSortIndex='00001|000000|00000';
  note.annotationPosition=JSON.stringify({pageIndex:1,rects:[[30,400,45,420]]});await note.saveTx();
  const reader=await Zotero.Reader.open(source.id);await reader._initPromise;opened.push(reader);
  await a.readers.attach(reader);await a.readers.showChinese(source);
  const session=[...a.readers.sessions.values()].find(s=>s.reader.tabID===reader.tabID);
  await session.active.restore({pageIndex:1,scale:145,top:540,left:0,scrollMode:0,spreadMode:0});
  const state=session.active.capture(),englishPDF=session.host.pdf.pdfDocument;
  const oldChinese=session.active.pdf.pdfDocument,oldTask=session.active.pdf.pdfLoadingTask;
  await capture(session,'before');
  // Also cover a native tab opened directly on the same Chinese attachment.
  const chineseReader=await Zotero.Reader.open(chinese.id);await chineseReader._initPromise;opened.push(chineseReader);
  const direct=await a.readers.attach(chineseReader);
  const nativeNote=note.key;
  assert(chineseReader._internalReader._state.annotations.some(x=>x.id===nativeNote),'Existing native annotation was not loaded');
  const tabsBefore=reader._window.Zotero_Tabs._tabs.filter(t=>t.type==='reader').length;
  const first=await a.highlightPDF(source);
  assert(first.highlightCount===3&&first.requests===3,'Expected three accepted highlights and three Mock page requests');
  assert(equalBytes(await IOUtils.read(first.backupPath),originalBytes),'Original Chinese backup is not exact');
  assert(equalBytes(await IOUtils.read(await source.getFilePathAsync()),englishBytes),'English original was changed');
  assert(parent.getAttachments().length===count,'AI highlights created a second Chinese attachment');
  assert(Zotero.Items.get(note.id).parentID===chinese.id&&!Zotero.Items.get(note.id).deleted,'Zotero annotation was lost');
  assert(chineseReader._internalReader._state.annotations.some(x=>x.id===nativeNote),'Reload lost the native annotation manager');
  assert(session.active.pdf.pdfDocument!==oldChinese&&released(oldTask),'Chinese PDF was not refreshed or old PDF task leaked');
  assert(session.host.pdf.pdfDocument===englishPDF,'Highlighting reloaded the English original');
  assert(session.active.capture().pageIndex===state.pageIndex&&session.active.capture().scale===state.scale,'Highlighting lost page or zoom');
  assert(Math.abs(session.active.capture().top-state.top)<4,'Highlighting lost reading position');
  assert(reader._window.Zotero_Tabs._tabs.filter(t=>t.type==='reader').length===tabsBefore,'Highlighting opened another tab');
  assert(reader._tabContainer.querySelectorAll('.transyh-reader').length===1,'Highlighting duplicated the secondary browser');
  await capture(session,'after');
  const marked=await IOUtils.read(await chinese.getFilePathAsync());
  const repeated=await a.highlightPDF(source);
  assert(repeated.unchanged&&repeated.requests===0&&repeated.highlightCount===3,'Repeated highlight did not reuse saved result');
  assert(equalBytes(marked,await IOUtils.read(await chinese.getFilePathAsync())),'Repeated highlight rewrote the PDF');
  // Actual right-click command must follow the same cached path.
  const beforeMenu=(await counters(model)).calls;
  await reader._window.ZoteroPane.selectItem(source.id);
  reader._window.document.getElementById('transyh-highlight').dispatchEvent(new reader._window.Event('command'));
  await delay(1500);
  assert((await counters(model)).calls===beforeMenu,'Right-click repeated model calls');
  await session.switchTo('en');await session.switchTo('zh');
  assert(session.host.pdf.pdfDocument===englishPDF&&session.language==='zh','Bilingual switch regressed after highlighting');

  Zotero.Prefs.set('extensions.transyh.model','error-401',true);
  let failure='';try{await a.highlightPDF(source);}catch(error){failure=error.message;}
  assert(failure.includes('401')&&equalBytes(marked,await IOUtils.read(await chinese.getFilePathAsync())),'Failed selection damaged the Chinese PDF');
  const cancelModel=`fixture-highlight-cancel-${Date.now()}`;
  Zotero.Prefs.set('extensions.transyh.model',cancelModel,true);await control(cancelModel,{delay:2});
  let cancellation='';const pending=a.highlightPDF(source).catch(error=>{cancellation=error.message;});
  for(let i=0;i<600;i++) {
    const status=await counters(cancelModel);
    if(status?.calls>=2&&status?.active>=1)break;
    await delay(50);
    if(i===599)throw new Error('No cancellable highlight request after the first completed batch');
  }
  await a.cancelTranslation(source);await pending;
  assert(cancellation.includes('取消')&&equalBytes(marked,await IOUtils.read(await chinese.getFilePathAsync())),'Cancelled selection modified the PDF');
  await control(cancelModel,{});
  const resumed=await a.highlightPDF(source);
  assert(resumed.highlightCount===3&&resumed.cachedBatches>=1&&resumed.requests<=2,'Cancelled AI selection did not reuse its completed page cache');
  assert(parent.getAttachments().length===count,'Resume duplicated a Chinese attachment');

  // Automatic post-translation integration: substitute only translation output
  // with the existing Chinese fixture; AI/backup/install/reader remain real.
  const automatic=await newPair('Automatic highlight integration fixture',false);
  let intercepted=0;
  a.engine.run=async function(action,extra={},update,run) {
    if(action==='translate') {
      intercepted++;
      const path=PathUtils.join(extra.outputDir,'fixture-translation.pdf');
      await IOUtils.copy(PathUtils.join(root,'tests','output','highlights-before.pdf'),path);
      return {type:'done',path,quality:{status:'pass',issues:[]}};
    }
    return originalRun.call(this,action,extra,update,run);
  };
  Zotero.Prefs.set('extensions.transyh.model',`fixture-highlight-auto-${Date.now()}`,true);
  Zotero.Prefs.set('extensions.transyh.autoHighlights','true',true);
  const autoChinese=await a.translate(automatic.source);
  a.engine.run=originalRun;
  assert(intercepted===1&&automatic.parent.getAttachments().length===2,'Automatic flow duplicated the current Chinese PDF');
  const autoAgain=await a.highlightPDF(automatic.source);
  assert(autoAgain.unchanged&&autoAgain.highlightCount===3&&autoAgain.requests===0,'New Chinese PDF did not contain automatic highlights');
  // Failure of optional automatic highlights must still return a valid PDF.
  const failedAuto=await newPair('Automatic highlight API failure fixture',false);
  a.engine.run=async function(action,extra={},update,run) {
    if(action==='translate') {
      const path=PathUtils.join(extra.outputDir,'fixture-translation.pdf');
      await IOUtils.copy(PathUtils.join(root,'tests','output','highlights-before.pdf'),path);
      return {type:'done',path,quality:{status:'pass',issues:[]}};
    }
    return originalRun.call(this,action,extra,update,run);
  };
  Zotero.Prefs.set('extensions.transyh.model','error-401',true);
  const usable=await a.translate(failedAuto.source);
  assert(await usable.fileExists()&&failedAuto.parent.getAttachments().length===2,'Optional highlight failure prevented delivery of the Chinese PDF');
  return {sourceID:source.id,chineseID:chinese.id,noteID:note.id,model:cancelModel,
    first:{requests:first.requests,count:first.highlightCount},repeated:{requests:repeated.requests,unchanged:repeated.unchanged},
    resumed:{requests:resumed.requests,cachedBatches:resumed.cachedBatches,count:resumed.highlightCount},
    sourceUnchanged:true,oneChineseAttachment:true,zoteroAnnotationPreserved:true,pdfReload:true,oldTaskReleased:true,
    bilingualSwitch:true,positionPreserved:true,rightClick:true,failurePreserved:true,cancelPreserved:true,
    automaticHighlights:true,automaticFailureStillDelivers:true,preferenceCheckbox:true,nativeCanvasCaptured:true};
} finally {
  a.engine.run=originalRun;
  Zotero.Prefs.set('extensions.transyh.autoHighlights','false',true);
  Zotero.Prefs.set('extensions.transyh.model',previousModel,true);
  for(const reader of opened)reader._window.Zotero_Tabs.close(reader.tabID);
  await delay(300);await a.store.flush();
}
