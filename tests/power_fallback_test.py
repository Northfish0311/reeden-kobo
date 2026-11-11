#!/usr/bin/env python3
"""Without the debugfs wake-lock view the helper must still suspend.

Refusing to sleep because one diagnostic file is unreadable keeps the radio and
CPU awake all night, which costs far more than a fixed settle delay.
"""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/power.sh').read_text()

with tempfile.TemporaryDirectory(prefix='reeden-power-fallback-') as tmp:
    app = Path(tmp)
    for directory in ('state', 'logs', 'sys/class/power_supply/bd71827_bat', 'sys/power', 'proc', 'dev'):
        (app / directory).mkdir(parents=True, exist_ok=True)
    (app / 'sys/class/power_supply/bd71827_bat/status').write_text('Discharging\n')
    (app / 'sys/power/state-extended').write_text('1\n')
    (app / 'sys/power/state').write_text('untouched\n')
    (app / 'proc/uptime').write_text('100.10 50.0\n')
    (app / 'session.sh').write_text(f'APP="{app}"\nSTATE="$APP/state"\n')
    # sys/kernel/debug is deliberately absent: this is the unreadable case.
    for prefix in ('/sys/', '/proc/', '/dev/', '/etc/'):
        source = source.replace(prefix, str(app) + prefix)
    script = app / 'power.sh'
    script.write_text(source)

    result = subprocess.run(['sh', str(script), 'suspend'], check=False)
    log = (app / 'logs/power.log').read_text()

    # The synthetic clock never advances: one request happened, but the host
    # must not mistake this immediate return for a user asking to resume.
    assert result.returncode == 76, (result.returncode, log)
    assert (app / 'sys/power/state').read_text().strip() == 'mem', log
    assert 'wakeup_sources unreadable' in log, log
    assert 'display did not become idle' not in log, log
    print('PASS: missing wakeup_sources still suspends after a fixed settle')
