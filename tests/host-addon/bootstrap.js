var timer;
var busy = false;
var runtime;
function startup() { initialize().catch(e => Zotero.logError(e)); }
async function initialize() {
  await Zotero.initializationPromise;
  runtime = Zotero.Prefs.get('extensions.transyh.testRuntime', true);
  if (!runtime) return;
  await IOUtils.makeDirectory(runtime, { ignoreExisting: true });
  await IOUtils.writeJSON(PathUtils.join(runtime, 'ready.json'), { version: Zotero.version, pid: Services.appinfo.processID, profile: Zotero.Profile.dir, data: Zotero.DataDirectory.dir });
  timer = setInterval(async () => {
    if (busy) return;
    const file = PathUtils.join(runtime, 'command.json');
    if (!await IOUtils.exists(file)) return;
    busy = true;
    let command;
    try {
      command = await IOUtils.readJSON(file);
      await IOUtils.remove(file);
      const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
      const fn = new AsyncFunction('Zotero', 'Services', 'ChromeUtils', 'Components', 'IOUtils', 'PathUtils', command.code);
      const result = await fn(Zotero, Services, ChromeUtils, Components, IOUtils, PathUtils);
      await IOUtils.writeJSON(PathUtils.join(runtime, 'result-' + command.id + '.json'), { ok: true, result });
    } catch (error) {
      await IOUtils.writeJSON(PathUtils.join(runtime, 'result-' + (command?.id || 'unknown') + '.json'), { ok: false, error: String(error), stack: error.stack });
    } finally { busy = false; }
  }, 200);
}
function shutdown() { clearInterval(timer); }
function install() {}
function uninstall() {}
