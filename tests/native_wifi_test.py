#!/usr/bin/env python3
"""Test Nickel handoff requests with fake D-Bus and interface state, never hardware."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativeWifiTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='reeden-native-wifi-')
        self.addCleanup(tmp.cleanup)
        self.app = Path(tmp.name).resolve()
        (self.app / 'stubs').mkdir()
        (self.app / 'state').mkdir()
        (self.app / 'flags').write_text('0x1203\n')
        (self.app / 'nickel').touch()
        (self.app / 'session.sh').write_text(f'APP="{self.app}"\nSTATE="$APP/state"\n')
        source = (ROOT / 'scripts/native-session.sh').read_text()
        source = source.replace('/sys/class/net/wlan0/flags', str(self.app / 'flags'))
        source = source.replace('export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin',
                                f'export PATH="{self.app}/stubs:/usr/bin:/bin"')
        (self.app / 'native-session.sh').write_text(source)
        stub = '''#!/bin/sh
name=${0##*/}
case "$name" in
pidof) [ -f "$APP/nickel" ];;
timeout) shift; exec "$@";;
usleep) :;;
dbus-send)
    echo "$*" >> "$APP/calls"
    case "$*" in
    *NameHasOwner*)
        n=0; [ ! -f "$APP/owner-checks" ] || read -r n < "$APP/owner-checks"
        n=$((n+1)); echo "$n" > "$APP/owner-checks"
        if [ -f "$APP/no-service" ] || { [ -f "$APP/delayed" ] && [ "$n" -lt 3 ]; }; then
            echo 'boolean false'
        else echo 'boolean true'; fi;;
    *wfmSetAirplaneMode*)
        [ ! -f "$APP/method-fails" ] || exit 1
        [ ! -f "$APP/no-effect" ] || exit 0
        case "$*" in *string:disable*) echo 0x1202 > "$APP/flags";;
            *string:enable*) echo 0x1203 > "$APP/flags";; *) exit 64;; esac;;
    *wfmConnectWirelessSilently*) [ ! -f "$APP/method-fails" ];;
    *) exit 64;;
    esac;;
esac
'''
        for name in ('pidof', 'timeout', 'usleep', 'dbus-send'):
            path = self.app / 'stubs' / name
            path.write_text(stub)
            path.chmod(0o755)
        self.env = {**os.environ, 'APP': str(self.app),
                    'PATH': str(self.app / 'stubs') + os.pathsep + os.environ.get('PATH', '')}

    def call(self, mode):
        return subprocess.run(['sh', str(self.app / 'native-session.sh'), 'wifi-choice', mode],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_off_on_calls_native_manager_and_checks_actual_interface(self):
        self.assertEqual(self.call('0').returncode, 0)
        self.assertEqual((self.app / 'flags').read_text().strip(), '0x1202')
        self.assertEqual(self.call('1').returncode, 0)
        calls = (self.app / 'calls').read_text()
        self.assertIn('wfmSetAirplaneMode string:disable', calls)
        self.assertIn('wfmSetAirplaneMode string:enable', calls)
        self.assertIn('wfmConnectWirelessSilently', calls)
        self.assertEqual((self.app / 'flags').read_text().strip(), '0x1203')

    def test_delayed_plugin_readiness_is_bounded_and_retried(self):
        (self.app / 'delayed').touch()
        self.assertEqual(self.call('0').returncode, 0)
        self.assertEqual((self.app / 'owner-checks').read_text().strip(), '3')

    def test_missing_plugin_leaves_native_control_alone(self):
        (self.app / 'no-service').touch()
        self.assertEqual(self.call('0').returncode, 69)
        self.assertEqual((self.app / 'owner-checks').read_text().strip(), '5')
        self.assertNotIn('wfmSetAirplaneMode', (self.app / 'calls').read_text())
        self.assertEqual((self.app / 'flags').read_text().strip(), '0x1203')

    def test_method_error_or_unchanged_interface_is_not_success(self):
        for marker in ('method-fails', 'no-effect'):
            with self.subTest(marker=marker):
                (self.app / marker).touch()
                self.assertEqual(self.call('0').returncode, 1)
                (self.app / marker).unlink()

    def test_missing_nickel_never_starts_own_radio_services(self):
        (self.app / 'nickel').unlink()
        self.assertEqual(self.call('0').returncode, 69)
        self.assertFalse((self.app / 'calls').exists())


if __name__ == '__main__':
    unittest.main()
