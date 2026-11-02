#!/usr/bin/env python3
"""A native restart must discard only the stale Kobo WPA/DHCP bridge."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='reeden-native-bridge-') as tmp:
    app = Path(tmp)
    for name in ('state', 'logs', 'tmp', 'stubs', 'proc/111', 'proc/222', 'proc/333'):
        (app / name).mkdir(parents=True)
    (app / 'state/native-restart').touch()
    (app / 'state/native-env').write_text('INTERFACE=wlan0\n')
    for pid in (111, 222, 333):
        (app / f'proc/{pid}/alive').touch()
        (app / f'proc/{pid}/stat').write_text(f'{pid} (bridge) S 0\n')
    (app / 'session.sh').write_text(f'''APP="{app}"
STATE="$APP/state"
token() {{ echo 1; }}
same_process() {{ [ "$1" != 333 ] && [ -f "$APP/proc/$1/alive" ]; }}
pidof() {{
  case "$1" in
  dhcpcd-dbus) echo '111 222 333';;
  nickel) [ -f "$APP/started" ] && echo 444;;
  esac
}}
readlink() {{
  case "$1" in
  */111/exe|*/333/exe) echo /libexec/dhcpcd-dbus;;
  */222/exe) echo /some/unrelated-program;;
  esac
}}
kill() {{
  echo "signal $*" >> "$APP/events"
  rm -f "$APP/proc/$2/alive"
}}
usleep() {{ :; }}
''')
    for name, body in {
        'nickel': f'echo nickel-start >> "{app}/events"; touch "{app}/started"',
        'hindenburg': ':',
        'udevadm': ':',
    }.items():
        path = app / 'stubs' / name
        path.write_text('#!/bin/sh\n' + body + '\n'); path.chmod(0o755)
    source = (ROOT / 'scripts/native-session.sh').read_text()
    source = source.replace('/proc/', str(app / 'proc') + '/')
    source = source.replace('/tmp/nickel-hardware-status', str(app / 'tmp/hardware-status'))
    for name in ('nickel', 'hindenburg'):
        source = source.replace('/usr/local/Kobo/' + name, str(app / 'stubs' / name))
    source = source.replace('/sbin/udevadm', str(app / 'stubs/udevadm'))
    script = app / 'native-session.sh'; script.write_text(source)
    subprocess.run(['sh', str(script), 'start'], check=True, timeout=5)
    assert (app / 'events').read_text().splitlines() == ['signal -TERM 111', 'nickel-start']
    assert not (app / 'proc/111/alive').exists()
    assert (app / 'proc/222/alive').exists(), 'Unrelated executable was signalled'
    assert (app / 'proc/333/alive').exists(), 'Stale process token was ignored'
    # Already running Nickel must not have its live bridge reset.
    subprocess.run(['sh', str(script), 'start'], check=True, timeout=5)
    assert len((app / 'events').read_text().splitlines()) == 2
    print('PASS: native restart resets exact stale network bridge before Nickel; unrelated/reused PIDs and live native session untouched')
