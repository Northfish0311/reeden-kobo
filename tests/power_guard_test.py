#!/usr/bin/env python3
"""The MTK charging guard must skip radio shutdown and kernel suspend."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/power.sh').read_text()
with tempfile.TemporaryDirectory(prefix='reeden-power-guard-') as tmp:
    app = Path(tmp)
    for directory in ('state', 'logs', 'sys/class/power_supply/bd71827_bat', 'sys/power', 'proc', 'dev'):
        (app / directory).mkdir(parents=True, exist_ok=True)
    (app / 'sys/class/power_supply/bd71827_bat/status').write_text('Charging\n')
    (app / 'sys/power/state-extended').write_text('1\n')
    (app / 'sys/power/state').write_text('untouched\n')
    (app / 'proc/uptime').write_text('100.10 50.0\n')
    (app / 'session.sh').write_text(f'APP="{app}"\nSTATE="$APP/state"\n')
    # Redirect every hardware path, including paths the guard must never reach.
    for prefix in ('/sys/', '/proc/', '/dev/', '/etc/'):
        source = source.replace(prefix, str(app) + prefix)
    script = app / 'power.sh'
    script.write_text(source)
    result = subprocess.run(['sh', str(script), 'suspend'], check=False)
    assert result.returncode == 3, result.returncode
    assert (app / 'sys/power/state-extended').read_text().strip() == '0'
    assert (app / 'sys/power/state').read_text() == 'untouched\n'
    assert not (app / 'state/wifi-restore').exists()
    assert not (app / 'state/power-alarm').exists()
    print('PASS: charging skips radio shutdown and kernel suspend; extended flag restored')
