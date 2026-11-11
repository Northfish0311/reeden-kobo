#!/usr/bin/env python3
"""Confirmed choices survive normal exit; crash/lock values use the snapshot."""
from pathlib import Path
import shutil
import subprocess
import tempfile

if not shutil.which('sh'):
    print('SKIP: needs a POSIX shell')
    raise SystemExit(0)

root = Path(__file__).resolve().parents[1]
text = (root / 'scripts/recover.sh').read_text()
start = text.index('valid_level() {')
end = text.index('\nif owned_host;', start)
function = text[start:end]

with tempfile.TemporaryDirectory(prefix='reeden-light-') as tmp:
    work = Path(tmp)
    (work / 'state').mkdir()
    brightness, warmth = work / 'brightness', work / 'warmth'
    function = function.replace('/sys/class/backlight/mxc_msp430.0/brightness', brightness.as_posix())
    function = function.replace('/sys/class/backlight/lm3630a_led/color', warmth.as_posix())
    (work / 'fn.sh').write_text(function)
    (work / 'state/light').write_text('60 8\n')
    for light, warm, expected in [('-1', '-1', ('60', '8')), ('30', '2', ('30', '2')),
                                  ('0', '0', ('0', '0')), ('101', 'bad', ('60', '8'))]:
        brightness.write_text('0\n')
        warmth.write_text('0\n')
        (work / 'run.sh').write_text(
            f'STATE="{work.as_posix()}/state"\nchoice_light="{light}"; choice_warm="{warm}"\n'
            f'. "{work.as_posix()}/fn.sh"\nrestore_lights\n')
        r = subprocess.run(['sh', (work / 'run.sh').as_posix()], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert (brightness.read_text().strip(), warmth.read_text().strip()) == expected

print('PASS: explicit normal-exit light choices and crash snapshots are separate')
