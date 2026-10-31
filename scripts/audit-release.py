"""Audit distributable contents without printing any matched secret material."""
from pathlib import Path
import io
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = json.loads((ROOT/'package.json').read_text())['version']
XPI_FILES = {'manifest.json','bootstrap.js','content/transyh.js','content/preferences.js','content/preferences.xhtml',
             'engine/worker.py','engine/api_client.py','engine/quality.py','engine/refresh_tasks.py','engine/macos_keychain.py','engine/requirements.txt',
             'engine/highlight_pdf.py','engine/highlight_jobs.py','engine/highlight_install.py',
             'engine/requirements-macos.lock','LICENSE','THIRD_PARTY_NOTICES.md'}
FIXTURES = {'tests/fixtures/paper-english.pdf','tests/fixtures/switch-chinese.pdf'}
FORBIDDEN = {'.test-profile','.test-data','.test-runtime','.research','.venv','node_modules','__pycache__',
             '.pytest_cache','output','jobs','cache','retranslation','transactions','backups','highlight-cache.sqlite3','refresh-tasks.sqlite3','logins.json','key4.db','cert9.db','reading.json','quality-report.json'}
SECRET = re.compile(rb'sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
errors = []

# Current product version only; historical release notes and fixtures retain
# their original dates/versions. No checksum generation is needed for equality.
lock = json.loads((ROOT/'package-lock.json').read_text())
manifest = json.loads((ROOT/'addon/manifest.json').read_text())
if any(version != VERSION for version in (lock['version'], lock['packages']['']['version'], manifest['version'])):
    errors.append('source: current package/lock/manifest versions differ')
engine_versions = re.findall(r'engine-(\d+\.\d+\.\d+)', (ROOT/'src/engine.ts').read_text())
setup_versions = re.findall(r'version: "(\d+\.\d+\.\d+)"', (ROOT/'src/index.ts').read_text())
if engine_versions != [VERSION] or setup_versions != [VERSION]:
    errors.append('source: current runtime/setup versions differ')
readme = (ROOT/'README.md').read_text()
downloads = re.findall(r'dist/TransYH-([\d.]+)(?:-source\.zip|\.xpi)', readme)
if not downloads or set(downloads) != {VERSION}:
    errors.append('source: README downloads do not all target current version')


def check_entry(name, data, label):
    parts = Path(name).parts
    if any(p in FORBIDDEN or p.startswith('.env') for p in parts) or name.endswith(('.log','.pyc','.pem','.key','.sqlite3','.sqlite3-journal','.sqlite3-wal','.sqlite3-shm')):
        errors.append(f'{label}: forbidden file {name}')
    if name.lower().endswith('.pdf') and name not in FIXTURES:
        errors.append(f'{label}: non-fixture PDF {name}')
    if SECRET.search(data):
        errors.append(f'{label}: credential pattern in {name} (content suppressed)')


def check_xpi(data, label):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        if names != XPI_FILES or len(archive.namelist()) != len(names):
            errors.append(f'{label}: package file allowlist mismatch')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest['version'] != VERSION:
            errors.append(f'{label}: manifest version mismatch')
        for name in names:
            check_entry(name,archive.read(name),label)
            local = ROOT/'build'/name
            if not local.is_file() or archive.read(name) != local.read_bytes():
                errors.append(f'{label}: build differs from archive: {name}')


tracked = set(subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode().split('\0'))
source_count = 0
for name in filter(None,tracked):
    if name.startswith('dist/'):
        continue
    path = ROOT/name
    if path.is_file():
        check_entry(name,path.read_bytes(),'source');source_count+=1
xpi = ROOT/'dist'/f'TransYH-{VERSION}.xpi'
check_xpi(xpi.read_bytes(),'XPI')
for name in XPI_FILES:
    check_entry(name,(ROOT/'build'/name).read_bytes(),'build')
    source = ROOT/('addon/'+name if name in {'manifest.json','bootstrap.js'} or name.startswith('content/') else name)
    if name != 'content/transyh.js' and (ROOT/'build'/name).read_bytes() != source.read_bytes():
        errors.append(f'build: source differs from build: {name}')
archive_path = ROOT/'dist'/f'TransYH-{VERSION}-source.zip'
archive_count = 0
if archive_path.exists():
    with zipfile.ZipFile(archive_path) as archive:
        prefix = f'TransYH-{VERSION}/'
        archived = {entry.removeprefix(prefix) for entry in archive.namelist()}
        required = {name for name in tracked if name and not name.startswith('dist/') and (ROOT/name).is_file()}
        required.add(f'dist/TransYH-{VERSION}.xpi')
        if archived != required or len(archive.namelist()) != len(archived):
            errors.append('source ZIP: source file coverage mismatch')
        for name in ('tests/test_highlight_recall.py', 'tests/test_responses.py', 'scripts/diagnose-highlights.py',
                     'scripts/zotero-v024-test.mjs', 'tests/zotero-v024.js', 'V024_TEST_RESULTS.md'):
            if name not in archived:
                errors.append(f'source ZIP: missing acceptance/diagnostic file: {name}')
        for entry in archive.namelist():
            if not entry.startswith(prefix):
                errors.append('source ZIP: invalid root directory')
                continue
            name = entry.removeprefix(prefix)
            data = archive.read(entry)
            check_entry(name,data,'source ZIP');archive_count+=1
            if data != (ROOT/name).read_bytes():
                errors.append(f'source ZIP: local source differs: {name}')
            if name.endswith('.xpi'):
                check_xpi(data,'source ZIP embedded XPI')
else:
    errors.append('source ZIP: current source archive is missing')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'Release audit passed: {source_count} source files, {len(XPI_FILES)} XPI/build files, {archive_count} source ZIP entries; no credentials or runtime data found by the allowlist/pattern checks.')
