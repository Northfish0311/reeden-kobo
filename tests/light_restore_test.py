#!/usr/bin/env python3
"""Leaving the reader must not overwrite a brightness the user chose inside it.

recover.sh used to write the launch-time snapshot back unconditionally, so a level set
in the reader reverted the moment you returned to Nickel. Only our own dimming (0) is
undone now.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if not shutil.which('sh'):
    print('SKIP: needs a POSIX shell')
    raise SystemExit(0)


root = Path(__file__).resolve().parents[1]
text = (root / 'scripts/recover.sh').read_text()
start = text.index('restore_light() {')
end = text.index('\n}\n', start) + len('\n}\n')
function = text[start:end]

with tempfile.TemporaryDirectory(prefix='reeden-light-') as tmp:
    work = Path(tmp)
    (work / 'app/logs').mkdir(parents=True)
    (work / 'backlight').mkdir()
    (work / 'fn.sh').write_text(function)
    brightness = work / 'backlight/brightness'

    def restore(current: int, saved: str) -> str:
        brightness.write_text(f'{current}\n')
        # Hand the shell POSIX paths: Windows sh (Git bash) cannot open "C:\..." forms.
        script = (
            f'APP="{work.as_posix()}/app"\n'
            f'. "{work.as_posix()}/fn.sh"\n'
            f'restore_light "{brightness.as_posix()}" "{saved}" 100\n'
        )
        (work / 'run.sh').write_text(script)
        result = subprocess.run(['sh', (work / 'run.sh').as_posix()], capture_output=True, text=True)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        return brightness.read_text().strip()

    assert restore(0, '60') == '60', 'our own dimming must be undone'
    assert restore(30, '60') == '30', 'a level chosen in the reader must survive'
    assert restore(60, '60') == '60'
    assert restore(30, '') == '30', 'a missing snapshot must not touch the hardware'
    log = (work / 'app/logs/launcher.log').read_text()
    assert 'restored light' in log and 'kept reader light' in log, log

print('PASS: only dimming performed by the reader is reverted on exit')
