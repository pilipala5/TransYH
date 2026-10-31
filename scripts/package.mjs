import { execFileSync } from 'node:child_process';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const { version } = JSON.parse(await readFile(path.join(root, 'package.json'), 'utf8'));
await mkdir(path.join(root, 'dist'), { recursive: true });
const target = path.join(root, `dist/TransYH-${version}-source.zip`);
// Explicit allowlist: never include profiles, credentials, virtual environments,
// downloaded research repos, local logs or node_modules in the source release.
execFileSync('python3', ['-c', `
import pathlib,zipfile,sys
root=pathlib.Path(sys.argv[1]);target=pathlib.Path(sys.argv[2]);version=sys.argv[3]
files=['package.json','package-lock.json','tsconfig.json','.gitignore','README.md','CHANGELOG.md','TEST_RESULTS.md','V014_TEST_RESULTS.md','V020_TEST_RESULTS.md','V024_TEST_RESULTS.md','REAL_API_TEST_20261029.md','PERFORMANCE_FIX_20261029.md','THIRD_PARTY_NOTICES.md','LICENSE','install-engine.command','install-engine.ps1']
for name in ['addon','src','engine','scripts','tests','docs']:
 for p in (root/name).rglob('*'):
  if p.is_file() and '__pycache__' not in p.parts and 'output' not in p.relative_to(root).parts:
   files.append(str(p.relative_to(root)))
files.append('dist/TransYH-'+version+'.xpi')
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
 for name in sorted(set(files)):
  z.write(root/name,'TransYH-'+version+'/'+name)
`, root, target, version]);
console.log(target);
