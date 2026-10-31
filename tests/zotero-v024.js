// Executed by the isolated Zotero host against the final installed XPI.
const root=Zotero.Prefs.get('extensions.transyh.testRoot',true);
if(Zotero.Profile.dir!==PathUtils.join(root,'.test-profile','v024'))throw new Error('Requires dedicated isolated profile');
const base=Zotero.Prefs.get('extensions.transyh.testAPIBase',true);
if(!/^http:\/\/127\.0\.0\.1:\d+\/v1$/.test(base))throw new Error('Requires loopback Mock');
const a=Zotero.TransYH, prefix='extensions.transyh.';
const assert=(value,message)=>{if(!value)throw new Error(message);};
const equal=(x,y)=>x.length===y.length&&x.every((v,i)=>v===y[i]);
const delay=ms=>Zotero.Promise.delay(ms);
async function poll(get,accept,label,timeout=20000){
  const end=Date.now()+timeout;
  while(Date.now()<end){const value=await get();if(accept(value))return value;await delay(100);}
  throw new Error(label+' timed out');
}
const stats=async()=>(await Zotero.HTTP.request('GET',base.slice(0,-3)+'/stats',{responseType:'json'})).response;
const control=async(model,options)=>Zotero.HTTP.request('POST',base.slice(0,-3)+'/control',{
  headers:{'Content-Type':'application/json'},body:JSON.stringify({model,...options})});
const result={modes:[]},opened=[];
try{
  for(const mode of ['responses','chat_completions']){
    const model=`fixture-recall-native-${mode}-${Date.now()}`;
    Zotero.Prefs.set(prefix+'apiMode',mode,true);Zotero.Prefs.set(prefix+'model',model,true);
    await control(model,{requireContext:true,delay:1.5});
    const parent=new Zotero.Item('journalArticle');parent.setField('title','v0.2.4 contextual native acceptance '+mode);await parent.saveTx();
    const source=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','fixtures','paper-english.pdf'),parentItemID:parent.id});
    const english=await IOUtils.read(await source.getFilePathAsync()),info=await IOUtils.stat(await source.getFilePathAsync());
    const chinese=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','output','v024','recall-before.pdf'),parentItemID:parent.id});
    chinese.addTag('TransYH:source:'+source.key,1);chinese.addTag(`TransYH:stamp:${info.size}:${info.lastModified}`,1);await chinese.saveTx();
    const note=new Zotero.Item('annotation');note.parentID=chinese.id;note.libraryID=chinese.libraryID;
    note.annotationType='note';note.annotationComment='Existing Zotero annotation survives v0.2.4';note.annotationColor='#ffd400';
    note.annotationPageLabel='1';note.annotationSortIndex='00000|000000|00000';
    note.annotationPosition=JSON.stringify({pageIndex:0,rects:[[25,390,40,410]]});await note.saveTx();
    const reader=await Zotero.Reader.open(source.id);await reader._initPromise;opened.push(reader);
    const session=await a.readers.attach(reader);await a.readers.showChinese(source);
    await session.active.restore({pageIndex:1,scale:125,top:540,left:0,scrollMode:0,spreadMode:0});
    const position=session.active.capture(),originalPDF=session.host.pdf.pdfDocument,tab=reader.tabID;
    const before=await IOUtils.read(await chinese.getFilePathAsync());
    const pending=a.highlightPDF(source);
    const progress=await poll(()=>{
      const task=a.translationStatus(source),doc=session.active.win.document;
      const status=doc.querySelector('.transyh-status'),cancel=doc.querySelector('.transyh-cancel');
      return task?.activeRequests>=1&&status&&!status.hidden&&status.textContent.includes('%')&&cancel&&!cancel.hidden
        ?{kind:task.kind,activeRequests:task.activeRequests,text:status.textContent}:null;
    },Boolean,'Native highlight progress');
    const first=await pending;
    assert(first.highlightCount===4&&first.requests===2,'Expected full contextual recall through selected API');
    assert(first.diagnostics.promptVersion==='transyh-ai-highlights-v3-contextual-recall','Old highlight code installed');
    assert(first.diagnostics.ai.returnedCandidates===5&&first.diagnostics.selection.rejected.density===1,'Stage diagnostics missing');
    assert(equal(before,await IOUtils.read(first.backupPath)),'Original Chinese PDF backup differs');
    assert(equal(english,await IOUtils.read(await source.getFilePathAsync())),'English original changed');
    assert(parent.getAttachments().length===2&&!note.deleted&&note.parentID===chinese.id,'Attachment or annotation was lost');
    assert(session.active.capture().pageIndex===position.pageIndex&&session.active.capture().scale===position.scale,'Highlight lost reading position');
    assert(session.host.pdf.pdfDocument===originalPDF&&reader.tabID===tab,'English PDF or reader tab replaced');

    // The actual toolbar highlight button must use the cached result.
    await delay(1100);
    const button=session.active.win.document.querySelector('.transyh-highlight');
    assert(button&&!button.hidden&&!button.disabled,'Reader highlight button missing');
    const marked=await IOUtils.read(await chinese.getFilePathAsync()),calls=(await stats()).calls;
    button.click();await delay(1200);
    assert((await stats()).calls===calls&&equal(marked,await IOUtils.read(await chinese.getFilePathAsync())),'Toolbar repeated requests or marks');
    const repeated=await a.highlightPDF(source);
    assert(repeated.unchanged&&repeated.requests===0&&repeated.highlightCount===4,'Existing v3 layer not reused');
    await session.switchTo('en');await session.switchTo('zh');
    assert(session.language==='zh'&&reader.tabID===tab&&session.host.pdf.pdfDocument===originalPDF,'Chinese/EN switch regressed');

    // Cancel a real in-flight worker using the native toolbar cancel button.
    const cancelModel=`fixture-recall-cancel-${mode}-${Date.now()}`;
    Zotero.Prefs.set(prefix+'model',cancelModel,true);await control(cancelModel,{requireContext:true,delay:4});
    let settled=false,cancelError='';
    const cancellable=a.highlightPDF(source).then(()=>{settled=true;},error=>{cancelError=error.message;settled=true;});
    await poll(async()=>{
      const task=a.translationStatus(source),doc=session.active.win.document,cancel=doc.querySelector('.transyh-cancel');
      const metrics=(await stats()).models[cancelModel];
      return metrics?.active>=1&&task?.activeRequests>=1&&cancel&&!cancel.hidden&&!cancel.disabled;
    },Boolean,'Cancellable native worker');
    session.active.win.document.querySelector('.transyh-cancel').click();
    await poll(()=>settled,Boolean,'Native cancellation');await cancellable;
    assert(cancelError.includes('取消')&&equal(marked,await IOUtils.read(await chinese.getFilePathAsync())),'Cancelled highlight changed the PDF');
    await delay(1100);
    assert(!a.translationStatus(source)&&session.active.win.document.querySelector('.transyh-cancel').hidden,'Progress did not clear after cancellation');
    assert(!note.deleted&&equal(english,await IOUtils.read(await source.getFilePathAsync())),'Cancel lost annotation or English original');

    // Capture the actual native rendering for visual QA, outside distributables.
    await session.active.restore({pageIndex:0,scale:100,top:792,left:0});
    const canvas=await poll(()=>{
      const view=Components.utils.waiveXrays(session.active.pdf.pdfViewer.getPageView(0));
      return view?.renderingState===3?view.canvas:null;
    },Boolean,'Native PDF render');
    const bytes=session.active.win.atob(canvas.toDataURL('image/png').split(',')[1]);
    await IOUtils.write(PathUtils.join(root,'tests','output','v024',`native-${mode}.png`),Uint8Array.from(bytes,c=>c.charCodeAt(0)));
    result.modes.push({mode,model,cancelModel,highlightCount:first.highlightCount,requests:first.requests,
      path:await chinese.getFilePathAsync(),backupPath:first.backupPath,diagnostics:first.diagnostics,
      progressVisible:true,progress,cancelPreserved:true,bilingualSwitch:true,toolbarHighlight:true,
      cacheReused:true,sourcePreserved:true,annotationPreserved:true,positionPreserved:true});
  }
  // A Chinese original must be read directly, without a model call or new PDF.
  const parent=new Zotero.Item('journalArticle');parent.setField('title','Chinese original no-translation acceptance');await parent.saveTx();
  const source=await Zotero.Attachments.importFromFile({file:PathUtils.join(root,'tests','output','v024','recall-before.pdf'),parentItemID:parent.id});
  const original=await IOUtils.read(await source.getFilePathAsync()),calls=(await stats()).calls;
  const reader=await Zotero.Reader.open(source.id);await reader._initPromise;opened.push(reader);
  const session=await a.readers.attach(reader);await a.readers.showChinese(source);
  assert((await a.translate(source)).id===source.id,'Chinese original was translated');
  assert((await stats()).calls===calls&&parent.getAttachments().length===1,'Chinese original called API or duplicated attachment');
  assert(session.language==='zh'&&equal(original,await IOUtils.read(await source.getFilePathAsync())),'Chinese original was changed');
  result.chineseSkipsAPI=true;
  return result;
}finally{
  for(const reader of opened)reader._window.Zotero_Tabs.close(reader.tabID);
  await a.store.flush();
}
