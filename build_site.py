"""Build a public-only static artifact; no downloads, deployment or device access."""
from pathlib import Path
import hashlib
import json
import runpy
import shutil

ROOT = Path(__file__).resolve().parent


def build():
    runpy.run_path(str(ROOT/'tools/build_guides.py'), run_name='__main__')
    manifest = json.loads((ROOT/'install/firmware/stick-vario.release.json').read_text())
    app = (ROOT/'install/firmware/stick_vario_ram.py').read_bytes()
    assert manifest['kind'] == 'micropython-app' and manifest['board'] == 'M5StickS3'
    assert len(app) == manifest['app']['bytes']
    assert hashlib.sha256(app).hexdigest() == manifest['app']['sha256']
    files = ['index.html', 'style.css', 'app.js', 'engine.js', 'tone-worklet.js',
             '.nojekyll', 'data/demo.js', 'LICENSE', 'NOTICE.md']
    for folder in ('i18n', 'config', 'install'):
        files += [str(p.relative_to(ROOT)).replace('\\', '/')
                  for p in (ROOT/folder).iterdir()
                  if p.is_file() and p.suffix in ('.html', '.css', '.js', '.mjs')
                  and '.test.' not in p.name]
    files += ['install/firmware/stick_vario_ram.py',
              'install/firmware/stick-vario.release.json']
    files += [str(p.relative_to(ROOT)).replace('\\', '/')
              for p in (ROOT/'guide').rglob('*') if p.is_file()]
    for name in files:
        assert (ROOT/name).is_file(), name
    output = ROOT/'_site'
    assert not output.is_symlink() and output.resolve().parent == ROOT.resolve()
    if output.exists():
        # This directory is generated output. Resolve every file before removing
        # it, and reject symlinks so pruning cannot leave the intended build root.
        existing = list(output.rglob('*'))
        for path in existing:
            assert not path.is_symlink() and path.resolve().is_relative_to(output.resolve())
        for path in existing:
            if path.is_file():
                path.unlink()
    output.mkdir(exist_ok=True)
    for name in files:
        dest = output/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/name, dest)
    print(f'Built {len(files)} public files; bundled firmware {manifest["version"]}.')
    return output


if __name__ == '__main__':
    build()
