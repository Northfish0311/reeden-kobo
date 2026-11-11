#!/usr/bin/env python3
"""Exercise real shell network/LIPC code with synthetic interfaces and daemons."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WifiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reeden-wifi-')
        self.addCleanup(self.tmp.cleanup)
        self.app = Path(self.tmp.name).resolve()
        for folder in ['state', 'logs', 'stubs', 'tmp', 'dev', 'proc/driver', 'proc/123',
                       'sys/class/net/wlan0', 'etc', 'mnt/onboard/.kobo', 'bin']:
            (self.app / folder).mkdir(parents=True)
        (self.app / 'mnt/onboard/.kobo/version').write_text('SN,FW,000-393\n')
        (self.app / 'sys/class/net/wlan0/flags').write_text('0x1203\n')
        (self.app / 'dev/wmtWifi').write_text('1\n')
        for marker in ['state/handoff', 'owned', 'control', 'connected', 'ip']:
            (self.app / marker).touch()
        (self.app / 'etc/resolv.conf').write_text('nameserver 192.0.2.1\n')
        (self.app / 'proc/123/comm').write_text('wpa_supplicant\n')
        (self.app / 'proc/123/cmdline').write_bytes(b'wpa_supplicant\0-i\0wlan0\0')
        (self.app / 'proc/123/stat').write_text('123 (wpa_supplicant) S 0\n')
        (self.app / 'session.sh').write_text(f'''APP="{self.app}"
STATE="$APP/state"
token() {{ echo 1; }}
owned_host() {{ HOST=456; HOST_TOKEN=789; [ -f "$APP/owned" ]; }}
same_process() {{
  if [ "$1" = 123 ]; then [ -f "$APP/alive" ]; else command kill -0 "$1" 2>/dev/null; fi
}}
kill() {{
  if [ "${{2:-}}" = 123 ]; then echo "kill $*" >> "$APP/commands"; rm -f "$APP/alive"; else command kill "$@"; fi
}}
''')
        source = (ROOT / 'scripts/wifi.sh').read_text()
        # Rewrite once so an injected /tmp fixture path is not rewritten again.
        source = re.sub(r'/(?:sys|proc|dev|etc|tmp|mnt/onboard)/',
                        lambda match: str(self.app) + match.group(), source)
        source = source.replace('export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin',
                                f'export PATH="{self.app}/stubs:/usr/bin:/bin"')
        script = self.app / 'wifi.sh'; script.write_text(source); script.chmod(0o755)
        for name in ['lipc-get-prop', 'lipc-set-prop']:
            path = self.app / 'bin' / name
            path.write_text((ROOT / 'scripts' / name).read_text()); path.chmod(0o755)
        stub = '''#!/bin/sh
name=${0##*/}
echo "$name $*" >> "$APP/commands"
case "$name" in
timeout) shift; exec "$@";;
sleep|usleep) :;;
pidof) [ ! -f "$APP/alive" ] || echo 123;;
ifconfig)
  case "${2:-}" in
  up) echo 0x1203 > "$APP/sys/class/net/wlan0/flags";;
  down) echo 0x1202 > "$APP/sys/class/net/wlan0/flags"; rm -f "$APP/ip";;
  *) [ ! -f "$APP/ip" ] || echo ' inet addr:192.0.2.10 Bcast:192.0.2.255';;
  esac;;
wpa_cli)
  for arg in "$@"; do action=$arg; done
  case "$action" in
  ping) [ -f "$APP/control" ] || exit 1; echo PONG;;
  status) [ -f "$APP/control" ] || exit 1; if [ -f "$APP/connected" ]; then echo wpa_state=COMPLETED; else echo wpa_state=SCANNING; fi;;
  signal_poll) echo RSSI=-61;;
  terminate) [ -f "$APP/control" ] || exit 1; rm -f "$APP/control" "$APP/alive";;
  reconnect) echo OK;;
  esac;;
wpa_supplicant) : > "$APP/control";;
dhcpcd)
  case "$*" in
  *' -k '*) : > "$APP/etc/resolv.conf"; rm -f "$APP/ip";;
  *) [ ! -f "$APP/no-association" ] || exit 0; : > "$APP/ip"; : > "$APP/connected";;
  esac;;
esac
'''
        for name in ['timeout', 'sleep', 'usleep', 'pidof', 'ifconfig', 'wpa_cli', 'wpa_supplicant', 'dhcpcd']:
            path = self.app / 'stubs' / name; path.write_text(stub); path.chmod(0o755)
        self.env = {**os.environ, 'APP': str(self.app), 'REEDEN_KOBO_DIR': str(self.app)}

    def call(self, *args):
        return subprocess.run(['sh', str(self.app / 'wifi.sh'), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def test_status_requires_up_association_and_ip(self):
        self.assertEqual(self.call('probe').returncode, 12)
        self.assertEqual(self.call('status').stdout.strip(), 'CONNECTED')
        for marker in ['connected', 'ip']:
            (self.app / marker).unlink()
            self.assertEqual(self.call('status').stdout.strip(), 'NA')
            self.assertEqual(self.call('probe').returncode, 11)
            (self.app / marker).touch()
        (self.app / 'sys/class/net/wlan0/flags').write_text('0x1202\n')
        self.assertEqual(self.call('status').stdout.strip(), 'NA')
        self.assertEqual(self.call('enabled').stdout.strip(), '0')
        self.assertEqual(self.call('probe').returncode, 10)

    def test_lipc_signals_and_wifi_properties(self):
        for property, expected in [('cmState', 'CONNECTED'), ('signalStrength', '4/5'), ('enable', '1')]:
            r = subprocess.run(['sh', str(self.app / 'bin/lipc-get-prop'), '-s', 'com.lab126.wifid', property],
                               env=self.env, text=True, capture_output=True)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, expected))
        for service, prop in [('com.lab126.wifid', 'enable'), ('com.lab126.cmd', 'wirelessEnable')]:
            r = subprocess.run(['sh', str(self.app / 'bin/lipc-set-prop'), '-i', service, prop, '0'], env=self.env)
            self.assertEqual(r.returncode, 0)
        self.assertEqual((self.app / 'dev/wmtWifi').read_text().strip(), '0')
        self.assertEqual((self.app / 'etc/resolv.conf').read_text(), 'nameserver 192.0.2.1\n')

    def test_duplicate_enable_does_not_interrupt_healthy_connection(self):
        self.assertEqual(self.call('on').returncode, 0)
        self.assertEqual(self.call('on').returncode, 0)
        commands = (self.app / 'commands').read_text()
        self.assertNotIn(' terminate', commands)
        self.assertNotIn('dhcpcd', commands)

    def test_only_reader_toggles_record_native_intent(self):
        choices = self.app / 'choices'
        choices.mkdir()
        self.env['REEDEN_CHOICES'] = str(choices)
        self.assertEqual(self.call('on').returncode, 0)
        self.assertEqual((choices / 'wifi').read_text(), '1\n')
        self.assertEqual((self.app / 'state/wifi-choice').read_text(), '456 789 1\n')
        self.assertEqual(self.call('suspend').returncode, 0)
        self.assertEqual((choices / 'wifi').read_text(), '1\n')
        self.assertEqual((self.app / 'state/wifi-choice').read_text(), '456 789 1\n')
        self.assertEqual(self.call('off').returncode, 0)
        self.assertEqual((choices / 'wifi').read_text(), '0\n')
        self.assertEqual((self.app / 'state/wifi-choice').read_text(), '456 789 0\n')

    def test_off_on_reconnects_using_saved_profile(self):
        self.assertEqual(self.call('off').returncode, 0)
        self.assertEqual(self.call('on').returncode, 0)
        self.assertEqual(self.call('status').stdout.strip(), 'CONNECTED')
        commands = (self.app / 'commands').read_text()
        self.assertIn('dhcpcd -d -b -t 15 wlan0', commands)
        self.assertIn('wpa_supplicant -D nl80211', commands)

    def test_existing_process_with_dead_control_socket_is_replaced(self):
        (self.app / 'control').unlink(); (self.app / 'alive').touch()
        r = self.call('on')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('kill -TERM 123', (self.app / 'commands').read_text())
        self.assertEqual(self.call('status').stdout.strip(), 'CONNECTED')

    def test_request_accepted_is_not_a_connected_result(self):
        (self.app / 'no-association').touch(); (self.app / 'connected').unlink()
        self.assertEqual(self.call('on').returncode, 0)
        self.assertEqual(self.call('enabled').stdout.strip(), '1')
        self.assertEqual(self.call('status').stdout.strip(), 'NA')

    def test_warmup_sleep_or_recovery_rejects_user_changes(self):
        for marker, is_dir in [('state/handoff', False), ('state/asleep', False), ('state/recovering', True)]:
            path = self.app / marker
            if marker.endswith('handoff'): path.unlink()
            elif is_dir: path.mkdir()
            else: path.touch()
            self.assertEqual(self.call('on').returncode, 69)
            if marker.endswith('handoff'): path.touch()
            elif is_dir: path.rmdir()
            else: path.unlink()
        (self.app / 'state/recovering').mkdir()
        self.assertEqual(self.call('resume').returncode, 69)

    def test_stale_lock_is_recovered(self):
        lock = self.app / 'tmp/reeden-kobo-wifi.lock'; lock.mkdir()
        (lock / 'owner').write_text('999999 1\n')
        self.assertEqual(self.call('on').returncode, 0)
        self.assertFalse(lock.exists())


if __name__ == '__main__':
    unittest.main()
