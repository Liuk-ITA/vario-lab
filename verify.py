"""Run offline Node/Python checks; no browser hardware or network access."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    env = os.environ.copy()
    node = shutil.which('node')
    if not node:
        candidate = Path(os.environ.get('LOCALAPPDATA', ''))/'Programs/Microsoft VS Code/Code.exe'
        if not candidate.exists():
            raise SystemExit('Node.js 20+ is required for host checks, not for using the site.')
        node = str(candidate)
        env['ELECTRON_RUN_AS_NODE'] = '1'
    def run(command):
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        if result.stdout.strip():print(result.stdout.strip())
        if result.returncode:
            print(result.stderr)
            raise SystemExit(result.returncode)
    for folder in ('', 'i18n', 'config', 'install'):
        for path in (ROOT/folder).iterdir():
            if path.suffix in ('.js', '.mjs'):
                run([node, '--check', str(path)])
    suites = ['tests/engine.test.cjs', 'tests/app.test.cjs', 'tests/profiles.test.cjs',
              'tests/i18n.test.cjs', 'config/protocol.test.mjs', 'config/ui.test.mjs',
              'install/installer.test.mjs', 'install/install-plan.test.mjs', 'install/ui.test.mjs']
    for suite in suites:run([node, str(ROOT/suite)])
    run([sys.executable, '-m', 'unittest', 'discover', '-s', 'install', '-p', 'test_*.py'])
    run([sys.executable, 'build_site.py'])
    run([sys.executable, 'tools/check_public.py'])
    report = {'status':'PASS', 'node_suites':suites,
              'browser_hardware':'Not exercised; host/API doubles only'}
    (ROOT/'tests/results.json').write_text(json.dumps(report, indent=2))
    print('All offline checks passed.')


if __name__ == '__main__':
    main()
