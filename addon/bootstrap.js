var scope;
function startup(data) {
  // Zotero awaits plugin startup while resolving initializationPromise. Return
  // synchronously to avoid waiting on our own host initialization.
  initialize(data).catch(() => Zotero.logError('TransYH initialization failed'));
}
async function initialize(data) {
  await Zotero.initializationPromise;
  scope = { Zotero, Services, ChromeUtils, Components, IOUtils, PathUtils,
    Cc: Components.classes, Ci: Components.interfaces, Cu: Components.utils,
    setTimeout, clearTimeout, setInterval, clearInterval,
    URL: Zotero.getMainWindow().URL };
  Services.scriptloader.loadSubScript(data.rootURI + 'content/transyh.js', scope);
  await scope.TransYH.startup(data.rootURI);
}
async function shutdown(data, reason) {
  if (scope) await scope.TransYH.shutdown();
  scope = undefined;
}
function install() {}
function uninstall() {}
function onMainWindowLoad({ window }) { scope?.TransYH.onMainWindowLoad(window); }
function onMainWindowUnload({ window }) { scope?.TransYH.onMainWindowUnload(window); }
