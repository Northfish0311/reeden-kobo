"""Exercise real guardian logic with fake clocks/processes and no hardware."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
for phase, expected_timeout in [('resuming 1 123', True), ('complete 1 123', True), ('preparing 1 123', True), ('suspended 1 123', False), ('resuming 99 123', False)]:
    with tempfile.TemporaryDirectory(prefix='reeden-wake-guard-') as tmp:
        app = Path(tmp)
        for name in ('state/active', 'logs'):
            (app / name).mkdir(parents=True)
        (app / 'state/owner').write_text('123 1\n')
        (app / 'state/asleep').touch()
        (app / 'state/power-phase').write_text(phase+'\n')
        (app / 'logs/current.log').write_text('FIRST_UPDATE_SUBMITTED\n')
        (app / 'uptime').write_text('100.12 50.00\n')
        (app / 'session.sh').write_text(f'''APP="{app}"
STATE="$APP/state"
same_process() {{ return 0; }}
owned_host() {{ HOST=123; return 0; }}
sleep() {{ echo yes > "$APP/slept"; rmdir "$STATE/active"; }}
''')
        recover=app / 'recover.sh'
        recover.write_text('#!/bin/sh\nexit 0\n');recover.chmod(0o700)
        guardian=app / 'guardian.sh'
        guardian.write_text((root / 'scripts/guardian.sh').read_text().replace('/proc/uptime', str(app / 'uptime')))
        subprocess.run(['sh',str(guardian)],timeout=5,check=True)
        log=(app / 'logs/launcher.log').read_text() if (app / 'logs/launcher.log').exists() else ''
        assert ('exceeded 45s' in log)==expected_timeout,(phase,log)
        assert (app / 'slept').exists()!=expected_timeout
print('PASS: overdue wake/preparation recovers, actual suspended time and recent wake retain grace')
