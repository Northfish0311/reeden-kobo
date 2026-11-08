#!/usr/bin/env python3
"""Leaving the reader must tell Nickel which brightness to apply on its next start.

Nickel re-applies the level stored in Kobo eReader.conf, so the hardware value alone
was overwritten on exit. A zero reading means the reader dimmed the panel on its way
out and must never reach Nickel, otherwise the next start is black.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

if not shutil.which('sh'):
    print('SKIP: needs a POSIX shell')
    raise SystemExit(0)

root = Path(__file__).resolve().parents[1]
text = (root / 'scripts/recover.sh').read_text()
start = text.index('sync_nickel_light() {')
end = text.index('\n}\n', start) + len('\n}\n')
function = text[start:end]

CONFIG = """[General]
FrontLightLevel=99
[ApplicationPreferences]
LastFTEStep=CHECK_UPDATE
[PowerOptions]
FrontLightLevel=40
FrontLightState=true
ColorSetting=3200
[Other]
FrontLightLevel=77
"""

with tempfile.TemporaryDirectory(prefix='reeden-nickel-light-') as tmp:
    work = Path(tmp)
    (work / 'app/logs').mkdir(parents=True)
    (work / 'kobo').mkdir()
    conf = work / 'kobo/conf'
    brightness = work / 'brightness'
    (work / 'fn.sh').write_text(function)
    runner = work / 'run.sh'
    runner.write_text(
        f'APP="{work.as_posix()}/app"\n'
        f'NICKEL_CONF="{conf.as_posix()}"\n'
        f'LIGHT_PATH="{brightness.as_posix()}"\n'
        f'. "{(work / "fn.sh").as_posix()}"\n'
        'sync_nickel_light\n'
        'sync_nickel_light\n'
    )
    log = work / 'app/logs/launcher.log'

    def run(level: str):
        conf.write_text(CONFIG)
        brightness.write_text(level + '\n')
        log.unlink(missing_ok=True)
        result = subprocess.run(['sh', (work / 'run.sh').as_posix()], capture_output=True, text=True)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        return conf.read_text(), log.read_text() if log.exists() else ''

    data, log_text = run('12')
    assert '[PowerOptions]\nFrontLightLevel=12\nFrontLightState=true\n' in data, data
    assert data.count('FrontLightLevel=12') == 1, 'the level must be written exactly once'
    assert 'FrontLightLevel=99' in data and 'FrontLightLevel=77' in data, 'other sections untouched'
    assert 'ColorSetting=3200' in data, 'warmth left alone'
    assert log_text.count('Nickel brightness updated to 12') == 1, log_text

    data, log_text = run('0')
    assert data == CONFIG, 'a zero reading must be ignored'
    assert log_text == '', 'nothing to log when the reading is ignored'

    assert not list((work / 'kobo').glob('*.reeden-new')), 'no temporary file left behind'

print('PASS: recover.sh publishes the reader brightness to Nickel, ignoring zero')
