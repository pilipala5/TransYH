// Real Zotero + real BabelDOC, with only the model replaced by a loopback Mock.
const root = Zotero.Prefs.get('extensions.transyh.testRoot', true);
if (Zotero.Profile.dir !== PathUtils.join(root, '.test-profile')) throw new Error('Requires isolated profile');
const base = Zotero.Prefs.get('extensions.transyh.testAPIBase', true);
if (!/^http:\/\/127\.0\.0\.1:\d+\/v1$/.test(base)) throw new Error('Requires loopback Mock');
const assert = (value,message) => { if (!value) throw new Error(message); };
const api = base.slice(0,-3);
const a = Zotero.TransYH;
const ids = await IOUtils.readJSON(PathUtils.join(root,'.test-runtime','v014-items.json'));
const source = Zotero.Items.get(ids.sourceID);
const oldIDs = source.parentItem.getAttachments();
const sourcePath = await source.getFilePathAsync(), sourceInfo = await IOUtils.stat(sourcePath);
const annotations = oldIDs.flatMap(id=>Zotero.Items.get(id)?.getAnnotations?.() || []).map(x=>x.id || x);
const model = `fixture-resume-${Date.now()}`;
const oldModel = Zotero.Prefs.get('extensions.transyh.model',true);
const oldConcurrency = Zotero.Prefs.get('extensions.transyh.concurrency',true);
const originalRun = a.engine.run;
let failCompletion = false;
const attempts = [];
const control = async options => Zotero.HTTP.request('POST',api+'/control',{
  body:JSON.stringify({model,...options}),headers:{'Content-Type':'application/json'}});
const calls = async () => (await Zotero.HTTP.request('GET',api+'/stats',{responseType:'json'})).response.models[model]?.calls || 0;
const beforeTask = async () => ({index:attempts.length,calls:await calls()});
const outcome = async before => {
  const attempt=attempts[before.index];
  assert(attempt,'Missing persisted task observation');
  return {...attempt,apiCalls:(await calls())-before.calls};
};
a.engine.run = async function(action,extra={},update=()=>{},run) {
  if (action==='completeRefresh' && failCompletion) { failCompletion=false; throw new Error('simulated completion interruption'); }
  if (action==='translate' && attempts.length) attempts[attempts.length-1].version=PathUtils.filename(extra.outputDir);
  const result = await originalRun.call(this,action,extra,event=>{
    if (action==='translate' && attempts.length) {
      const entry=attempts[attempts.length-1];
      for (const key of ['cachedParagraphs','completedRequests','requests']) if (event[key]!==undefined) entry[key]=event[key];
    }
    update(event);
  },run);
  if (action==='prepareRefresh') attempts.push({token:result.refreshToken,version:result.taskVersion,resumed:result.resumed});
  if (action==='completeRefresh') attempts[attempts.length-1].completed=true;
  return result;
};
try {
  Zotero.Prefs.set('extensions.transyh.model',model,true);
  Zotero.Prefs.set('extensions.transyh.concurrency','1',true);
  const previous = await a.translate(source);
  const session=[...a.readers.sessions.values()].find(x=>x.source.id===source.id);
  const readable=session.active.pdf.pdfDocument;
  await control({failAfter:3});
  let before=await beforeTask(), failure='';
  try { await a.retranslate(source); } catch(error) { failure=error.message; }
  assert(failure.includes('401'),'Partial failure was not reported');
  const partial=await outcome(before);
  assert(partial.completedRequests===3 && partial.apiCalls===4,'Expected exactly 3 successful requests followed by Mock 401');
  assert((await a.translate(source)).id===previous.id && session.active.pdf.pdfDocument===readable,'Failed refresh changed the readable attachment');

  // Another configuration can finish while the original task remains pending.
  // Returning to the original configuration must resume that task, then make
  // its newly imported PDF the latest attachment (rather than sorting by the
  // older task creation time).
  Zotero.Prefs.set('extensions.transyh.model',model+'-other',true);
  const alternate=await a.retranslate(source);
  const isolated={...attempts[attempts.length-1]};
  assert(isolated.token!==partial.token && isolated.cachedParagraphs===0 && isolated.completed,
    'Changed model reused an incompatible pending task');
  Zotero.Prefs.set('extensions.transyh.model',model,true);
  await control({});
  before=await beforeTask();
  const recovered=await a.retranslate(source);
  const resumed=await outcome(before);
  assert(resumed.resumed && resumed.token===partial.token,'Retry did not restore persisted task identity');
  assert(resumed.cachedParagraphs>=3 && resumed.completed,'Retry did not reuse actual BabelDOC paragraph caches');
  assert(recovered.id!==previous.id,'Recovered task did not import a new PDF');
  assert((await a.translate(source)).id===recovered.id && recovered.id!==alternate.id,
    'Recovered older task did not become the latest usable attachment');

  before=await beforeTask();
  const fresh=await a.retranslate(source);
  const renewed=await outcome(before);
  assert(!renewed.resumed && renewed.token!==resumed.token && renewed.cachedParagraphs===0,'Completed refresh reused its namespace');
  assert(renewed.apiCalls>resumed.apiCalls && fresh.id!==recovered.id,'New explicit refresh did not call the model for the full task');

  await control({delay:0.7});
  before=await beforeTask();
  let cancelError='';
  const pending=a.retranslate(source).catch(error=>{cancelError=error.message;});
  for (let i=0;i<1200;i++) {
    const status=a.translationStatus(source);
    if (status?.completedRequests>=2 && status?.activeRequests>=1) break;
    await Zotero.Promise.delay(50);
    if (i===1199) throw new Error('Timed out waiting for completed paragraph caches before cancellation');
  }
  await a.cancelTranslation(source);await pending;
  const cancelled=await outcome(before);
  assert(cancelError.includes('取消'),'Cancellation was not reported');
  assert((await a.translate(source)).id===fresh.id,'Cancellation displaced the last valid PDF');
  await control({});
  before=await beforeTask();
  const afterCancel=await a.retranslate(source);
  const cancelResumed=await outcome(before);
  assert(cancelResumed.resumed && cancelResumed.token===cancelled.token && cancelResumed.cachedParagraphs>=2,
    'Cancelled worker did not restore its paragraph cache');

  // Simulate process interruption between safe attachment import and task ack.
  failCompletion=true;
  before=await beforeTask();
  const unacknowledged=await a.retranslate(source);
  const unacknowledgedTask=await outcome(before);
  assert(!unacknowledgedTask.completed && await unacknowledged.fileExists(),'Expected safe import before interrupted acknowledgement');
  before=await beforeTask();
  const final=await a.retranslate(source);
  const crashRecovery=attempts.slice(before.index);
  assert(crashRecovery.length===2 && crashRecovery[0].resumed && crashRecovery[0].completed,
    'Imported version was not reconciled with its pending task');
  assert(!crashRecovery[1].resumed && crashRecovery[1].token!==unacknowledgedTask.token && crashRecovery[1].cachedParagraphs===0,
    'Explicit refresh after interrupted completion did not start a new task');
  assert(final.id!==unacknowledged.id,'Crash recovery reused an already imported version');
  assert((await IOUtils.stat(sourcePath)).lastModified===sourceInfo.lastModified &&
    (await IOUtils.stat(sourcePath)).size===sourceInfo.size,'Original PDF changed');
  for (const id of oldIDs) {
    const item=Zotero.Items.get(id);
    assert(item && !item.deleted && await item.fileExists(),'Old attachment was removed');
  }
  assert(annotations.every(id=>!Zotero.Items.get(id).deleted),'Old annotations were removed');
  return {partial,isolated,resumed,renewed,cancelled,cancelResumed,unacknowledgedTask,crashRecovery,
    newZHID:final.id,oldAttachmentsPreserved:oldIDs.length,annotationsPreserved:annotations.length};
} finally {
  a.engine.run=originalRun;
  Zotero.Prefs.set('extensions.transyh.model',oldModel,true);
  Zotero.Prefs.set('extensions.transyh.concurrency',oldConcurrency || '4',true);
}
