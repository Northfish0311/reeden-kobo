"""Exercise the shipped power helper on synthetic inputs. No real hardware."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StandbyGuardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.app = app = Path(temp.name)
        for folder in ('state', 'logs', 'stubs', 'proc', 'sys/power',
                       'sys/class/power_supply/bd71827_bat', 'sys/class/power_supply/usb'):
            (app / folder).mkdir(parents=True, exist_ok=True)
        self.battery = app / 'sys/class/power_supply/bd71827_bat/status'
        self.battery.write_text('Discharging\n')
        (self.battery.parent / 'capacity').write_text('81\n')
        self.online = app / 'sys/class/power_supply/usb/online'
        self.online.write_text('0\n')
        (self.online.parent / 'type').write_text('USB\n')
        self.target = app / 'sys/power/state'
        self.target.write_text('untouched\n')
        (app / 'proc/uptime').write_text('123.4 0\n')
        (app / 'session.sh').write_text(f'APP="{app}"\nSTATE="$APP/state"\n')
        # Remap hardware reads, but keep the real null sink for stderr redirects.
        src = re.sub(r'/(sys|proc)/', lambda m: str(app) + m[0], (ROOT / 'scripts/power.sh').read_text())
        src = src.replace('export PATH=/usr/local/Kobo:/usr/sbin:/usr/bin:/sbin:/bin',
                          f'export PATH="{app}/stubs:/usr/bin:/bin"')
        (app / 'power.sh').write_text(src)
        for name, cmd in [('ifconfig', 'exit 1'), ('usleep', ':'), ('sleep', ':'), ('sync', ':')]:
            self.stub(name, cmd)

    def stub(self, name, cmd):
        p = self.app / 'stubs' / name
        p.write_text('#!/bin/sh\n' + cmd + '\n')
        p.chmod(0o755)

    def attempt(self):
        p = subprocess.run(['sh', str(self.app / 'power.sh'), 'suspend'], env=os.environ, timeout=5)
        return p.returncode, (self.app / 'logs/power.log').read_text()

    def test_unconfirmed_battery_and_online_supply_never_suspend(self):
        for level, online in [('Full', '0'), ('Unknown', '0'), ('Not charging', '0'),
                              ('Discharging', '1'), ('Discharging', '?')]:
            with self.subTest(level=level, online=online):
                self.battery.write_text(level + '\n')
                self.online.write_text(online + '\n')
                code, log = self.attempt()
                self.assertEqual(code, 3)
                self.assertIn('screen-only: supply guard', log)
                self.assertEqual(self.target.read_text(), 'untouched\n')

    def test_replug_and_key_cancel_at_last_boundary(self):
        for cmd, expected in [(f"echo 1 > '{self.online}'", 3), (f"touch '{self.app}/state/power-cancel'", 2)]:
            self.online.write_text('0\n')
            self.stub('sync', cmd)
            self.assertEqual(self.attempt()[0], expected)
            self.assertEqual(self.target.read_text(), 'untouched\n')

    def test_missing_debug_view_does_not_bypass_a_busy_timer(self):
        (self.app / 'proc/timer_list').write_text('_hrtint_xon_\n')
        code, log = self.attempt()
        self.assertEqual(code, 75, log)
        self.assertIn('display did not become idle', log)
        self.assertEqual(self.target.read_text(), 'untouched\n')

    def test_short_return_distinct_from_power_key_or_normal_resume(self):
        code, log = self.attempt()
        self.assertEqual(code, 76, log)
        self.assertEqual(self.target.read_text().strip(), 'mem')
        self.assertIn('short mem return after 0s; wake source unknown', log)
        self.assertIn('sample=after_mem battery=Discharging external=off capacity=81', log)

    def test_cover_fallback_keeps_lock_but_does_not_ignore_fatal_display_error(self):
        # Source-order guard only; device/main-loop integration remains untested.
        host = (ROOT / 'src/host.c').read_text(encoding='utf-8')
        block = host.split('if(acquired&&sleeping&&cover_at&&', 1)[1].split(
            'if(acquired&&sleeping&&radio_worker<0&&', 1)[0]
        self.assertIn('keeping current page, continuing to suspend', block)
        self.assertNotIn('set_sleep(&touch,false)', block)
        self.assertLess(block.index('if(app_quit)continue;'), block.index('display_wait(&screen)'))
        self.assertLess(block.index('display_wait(&screen)'), block.index('suspend_at=monotonic_ns()'))


if __name__ == '__main__':
    unittest.main()
