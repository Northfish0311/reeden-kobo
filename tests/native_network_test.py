#!/usr/bin/env python3
"""Exercise native handoff without network access or hardware writes."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'scripts/power.sh').read_text()
with tempfile.TemporaryDirectory(prefix='reeden-native-network-') as tmp:
    app = Path(tmp)
    for directory in ('state', 'logs', 'sys/power', 'sys/class/rtc/rtc0',
                      'proc', 'dev', 'etc', 'stubs', 'tmp', 'sys/class/net/wlan0', 'mnt/onboard/.kobo'):
        (app / directory).mkdir(parents=True, exist_ok=True)
    (app / 'session.sh').write_text(f'APP="{app}"\nSTATE="$APP/state"\ntoken() {{ echo 1; }}\n')
    (app / 'mnt/onboard/.kobo/version').write_text('SN,FW,000-393\n')
    (app / 'sys/class/net/wlan0/flags').write_text('0x1203\n')
    (app / 'sys/power/state-extended').write_text('1\n')
    (app / 'sys/power/state').write_text('untouched\n')
    (app / 'sys/class/rtc/rtc0/wakealarm').write_text('1234\n')
    (app / 'state/power-alarm').touch()
    (app / 'state/wifi-restore').touch()
    dns = 'nameserver 192.0.2.1\n'
    (app / 'etc/resolv.conf').write_text(dns)
    for prefix in ('/sys/', '/proc/', '/dev/', '/etc/'):
        source = source.replace(prefix, str(app) + prefix)
    source = source.replace(
        'export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin',
        f'export PATH="{app}/stubs:/usr/bin:/bin"')
    wifi = (root / 'scripts/wifi.sh').read_text()
    for prefix in ('/sys/', '/proc/', '/dev/', '/etc/', '/tmp/', '/mnt/onboard/'):
        wifi = wifi.replace(prefix, str(app) + prefix)
    wifi = wifi.replace('export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin',
                        f'export PATH="{app}/stubs:/usr/bin:/bin"')
    (app / 'wifi.sh').write_text(wifi)
    (app / 'wifi.sh').chmod(0o755)
    stub = '''#!/bin/sh
name=${0##*/}
echo "$name $*" >> "$APP/commands"
case "$name" in
timeout) shift; exec "$@";;
dhcpcd) : > "$APP/etc/resolv.conf";;
pidof) exit 1;;
esac
'''
    for name in ('timeout', 'dhcpcd', 'wpa_cli', 'pidof', 'ifconfig', 'sleep'):
        path = app / 'stubs' / name
        path.write_text(stub)
        path.chmod(0o755)
    script = app / 'power.sh'
    script.write_text(source)
    result = subprocess.run(['sh', str(script), 'native'],
                            env={**os.environ, 'APP': str(app)}, check=False)
    assert result.returncode == 0, result.returncode
    assert (app / 'sys/power/state-extended').read_text().strip() == '0'
    assert (app / 'sys/power/state').read_text() == 'untouched\n'
    assert (app / 'sys/class/rtc/rtc0/wakealarm').read_text().strip() == '0'
    assert (app / 'dev/wmtWifi').read_text().strip() == '0'
    assert (app / 'etc/resolv.conf').read_text() == dns
    for name in ('wifi-restore', 'power-alarm', 'power-resolv'):
        assert not (app / 'state' / name).exists(), name
    commands = (app / 'commands').read_text().splitlines()
    assert 'dhcpcd -d -k wlan0' in commands
    assert 'wpa_cli -p /var/run/wpa_supplicant -i wlan0 terminate' in commands
    assert 'ifconfig wlan0 down' in commands
    assert not any('wlan0 up' in line or ' -z ' in line for line in commands)
    assert 'radio and network services restarted' not in (app / 'logs/power.log').read_text()
    print('PASS: native handoff powers Wi-Fi down, preserves DNS, clears owned alarm, and never suspends or reconnects')
