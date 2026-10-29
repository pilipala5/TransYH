import { build } from 'esbuild';
import { mkdir, rm, cp, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
await rm(path.join(root, 'build'), { recursive: true, force: true });
await mkdir(path.join(root, 'build/content'), { recursive: true });
await cp(path.join(root, 'addon'), path.join(root, 'build'), { recursive: true });
await build({ entryPoints: [path.join(root, 'src/index.ts')], bundle: true, format: 'iife',
  globalName: 'TransYH', target: 'firefox128', outfile: path.join(root, 'build/content/transyh.js'),
  legalComments: 'eof' });
await mkdir(path.join(root, 'build/engine'), { recursive: true });
for (const name of ['worker.py', 'quality.py', 'refresh_tasks.py', 'highlight_pdf.py', 'highlight_jobs.py', 'highlight_install.py', 'macos_keychain.py', 'requirements.txt', 'requirements-macos.lock']) {
  await cp(path.join(root, 'engine', name), path.join(root, 'build/engine', name));
}
await cp(path.join(root, 'LICENSE'), path.join(root, 'build/LICENSE'));
await cp(path.join(root, 'THIRD_PARTY_NOTICES.md'), path.join(root, 'build/THIRD_PARTY_NOTICES.md'));
await mkdir(path.join(root, 'dist'), { recursive: true });
const { version } = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
const output = path.join(root, `dist/TransYH-${version}.xpi`);
await rm(output, { force: true });
execFileSync('python3', ['-c', 'import zipfile,sys,pathlib; root=pathlib.Path(sys.argv[1]); z=zipfile.ZipFile(sys.argv[2],"w",zipfile.ZIP_DEFLATED); [z.write(p,p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()]; z.close()', path.join(root, 'build'), output]);
console.log(output);
