const root = Zotero.Prefs.get('extensions.transyh.testRoot', true);
if (!root) throw new Error('Set the isolated testRoot preference before running this test');
const assert = (value, message) => { if (!value) throw new Error(message); };
const addon = Zotero.TransYH;
assert(addon, 'XPI did not initialize');
const parent = new Zotero.Item('journalArticle');
parent.setField('title', 'TransYH isolated single-tab evaluation');
await parent.saveTx();
const source = await Zotero.Attachments.importFromFile({ file: root + '/tests/fixtures/paper-english.pdf', parentItemID: parent.id });
const zh = await Zotero.Attachments.importFromFile({ file: root + '/tests/fixtures/switch-chinese.pdf', parentItemID: parent.id });
const fileInfo = await IOUtils.stat(await source.getFilePathAsync());
zh.addTag('TransYH:source:' + source.key, 1);
zh.addTag('TransYH:stamp:' + fileInfo.size + ':' + Math.trunc(fileInfo.lastModified), 1);
await zh.saveTx();
const reader = await Zotero.Reader.open(source.id);
await reader._initPromise;
const session = await addon.readers.attach(reader);
await session.host.ready();
const originalBrowser = session.host.browser;
const originalPDF = session.host.pdf.pdfDocument;
const tabID = reader.tabID;
const tabs = () => reader._window.Zotero_Tabs._tabs.filter(t => t.type === 'reader').length;
const count = tabs();
const controls = await (async () => { for (let i=0;i<50;i++) { const node=session.host.win.document.querySelector('.transyh-toggle'); if(node)return node; await Zotero.Promise.delay(100); } })();
assert(controls, 'Toolbar language buttons are missing');
await session.host.restore({ pageIndex: 1, scale: 145, top: 540, left: 0, scrollMode: 0, spreadMode: 0 });
const before = session.active.capture();
assert(before.pageIndex === 1 && before.scale === 145, 'Initial navigation did not settle');
await Promise.all([session.switchTo('zh'), session.switchTo('en'), session.switchTo('zh')]);
const after = session.active.capture();
assert(reader.tabID === tabID && tabs() === count, 'Switch opened another Zotero tab');
assert(session.host.browser === originalBrowser && session.host.pdf.pdfDocument === originalPDF, 'Original PDF was reloaded');
assert(after.pageIndex === before.pageIndex, 'Page was not preserved: ' + JSON.stringify({before,after}));
assert(after.scale === before.scale, 'Zoom was not preserved');
assert(Math.abs(after.top - before.top) <= 3, 'PDF page position differs');
assert(session.other.browser.isConnected && session.other.browser.style.visibility === 'visible' && session.host.browser.style.visibility === 'hidden', 'Visibility is incorrect');
const chineseText = session.active.internal._primaryView._iframeWindow.document.querySelector('.textLayer')?.textContent || '';
assert(chineseText.includes('中文'), 'Chinese PDF data was not loaded');
const translationPDF = session.other.pdf.pdfDocument;
const timing = [];
for (const language of ['en', 'zh', 'en', 'zh']) {
  const start = Date.now(); await session.switchTo(language); timing.push(Date.now()-start);
  const current = session.active.capture();
  assert(current.pageIndex === before.pageIndex && current.scale === before.scale && Math.abs(current.top-before.top) <= 3,
    'Reading position changed on repeated switch');
}
assert(session.other.pdf.pdfDocument === translationPDF && session.host.pdf.pdfDocument === originalPDF, 'Switch reloaded a PDF');
const rapidStart = Date.now();
await Promise.all(Array.from({length: 20}, (_, i) => session.switchTo(i % 2 ? 'zh' : 'en')));
assert(session.language === 'zh', 'Latest rapid-switch intent was lost');
assert(session.other.pdf.pdfDocument === translationPDF && session.host.pdf.pdfDocument === originalPDF, 'Rapid switching duplicated PDF instances');
assert(reader._tabContainer.querySelectorAll('.transyh-reader').length === 1, 'More than one secondary browser survived');
const rapidMilliseconds = Date.now() - rapidStart;
session.active.win.document.querySelector('[data-language="en"]').click();
session.active.win.document.querySelector('[data-language="zh"]').click();
await session.switchTo('zh');
assert(session.language === 'zh', 'Actual rapid toolbar clicks lost the final language');
session.save(); await addon.store.flush();
const saved = addon.store.get(source);
assert(saved.language === 'zh' && saved.state.pageIndex === 1 && saved.state.scale === 145, 'Reading state was not persisted');
await IOUtils.writeJSON(root + '/.test-runtime/items.json', { sourceID: source.id, sourceKey: source.key, zhID: zh.id, tabID });
return { version: Zotero.version, sourceID: source.id, zhID: zh.id, tabID, tabCountBefore: count, tabCountAfter: tabs(),
  sameOriginalPDF: session.host.pdf.pdfDocument === originalPDF, sameTranslationPDF: session.other.pdf.pdfDocument === translationPDF,
  before, after, cachedSwitchMilliseconds: timing, saved, toolbar: controls.textContent,
  rapidRequests: 20, rapidMilliseconds, rapidFinalLanguage: session.language,
  secondaryBrowsers: reader._tabContainer.querySelectorAll('.transyh-reader').length,
  menu: !!reader._window.document.getElementById('transyh-translate'), refreshMenu: !!reader._window.document.getElementById('transyh-retranslate') };
