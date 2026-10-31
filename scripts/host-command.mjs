import { readFile, writeFile, rename, access } from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
export async function host(code, timeout = 60000, runtime = path.join(root, '.test-runtime')) {
  const id = `${Date.now()}-${Math.floor(Math.random() * 10000)}`;
  const dir = runtime;
  await writeFile(path.join(dir, 'command.tmp'), JSON.stringify({ id, code }));
  await rename(path.join(dir, 'command.tmp'), path.join(dir, 'command.json'));
  const start = Date.now();
  while (Date.now() - start < timeout) {
    try {
      const raw = await readFile(path.join(dir, `result-${id}.json`), 'utf8');
      return JSON.parse(raw);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    await new Promise(r => setTimeout(r, 200));
  }
  throw new Error(`Zotero command timed out (${timeout}ms)`);
}
if (process.argv[1] === import.meta.filename) {
  const code = await readFile(process.argv[2], 'utf8');
  console.log(JSON.stringify(await host(code, Number(process.argv[3]) || 60000), null, 2));
}
