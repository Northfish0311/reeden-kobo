#!/usr/bin/env python3
"""Execute the device uninstaller in a mapped filesystem, with command failures."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(os.name == 'nt' or not shutil.which('sh'), 'POSIX device shell')
class DeviceUninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reeden-device-remove-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.onboard = self.base / 'onboard'
        self.adds = self.onboard / '.adds'
        self.app = self.adds / 'reeden-kobo'
        self.app.mkdir(parents=True)
        self.entry = self.adds / 'nm/reeden-kobo'
        self.entry.parent.mkdir()
        self.entry.write_text('owned menu\n')
        (self.app / 'nickelmenu.conf').write_bytes(self.entry.read_bytes())
        (self.app / 'reading-data').write_bytes(b'books-and-notes')
        script = (ROOT / 'scripts/uninstall.sh').read_text().replace('/mnt/onboard', str(self.onboard))
        (self.app / 'uninstall.sh').write_text(script)
        self.env = os.environ.copy()
        self.shims = self.base / 'bin'
        self.shims.mkdir()
        self.env['PATH'] = str(self.shims) + os.pathsep + self.env['PATH']

    def fail_command(self, command):
        p = self.shims / command
        p.write_text('#!/bin/sh\nexit 1\n')
        p.chmod(0o755)

    def run_uninstall(self):
        return subprocess.run(['sh', str(self.app / 'uninstall.sh')], env=self.env,
                              text=True, capture_output=True)

    def backups(self):
        return list(self.adds.glob('reeden-kobo-uninstalled-*'))

    def test_move_failure_preserves_menu_and_data(self):
        self.fail_command('mv')
        result = self.run_uninstall()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.entry.is_file())
        self.assertEqual((self.app / 'reading-data').read_bytes(), b'books-and-notes')
        self.assertEqual(self.backups(), [])

    def test_success_removes_owned_menu_only_after_preserving_data(self):
        result = self.run_uninstall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.entry.exists())
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual((self.backups()[0] / 'reading-data').read_bytes(), b'books-and-notes')

    def test_menu_failure_reports_preserved_directory(self):
        self.fail_command('rm')
        result = self.run_uninstall()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.entry.is_file())
        self.assertFalse(self.app.exists())
        self.assertEqual(len(self.backups()), 1)
        self.assertIn(str(self.backups()[0]), result.stdout)
        self.assertEqual((self.backups()[0] / 'reading-data').read_bytes(), b'books-and-notes')

    def test_comparison_errors_preserve_menu_and_report_failure(self):
        for status in (2, 127):
            with self.subTest(status=status):
                command = self.shims / 'cmp'
                command.write_text(f'#!/bin/sh\nexit {status}\n')
                command.chmod(0o755)
                result = self.run_uninstall()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.entry.read_text(), 'owned menu\n')
                self.assertNotIn('Menu entry was edited', result.stdout)
                self.assertIn(f'cmp status {status}', result.stdout)
                self.assertEqual(len(self.backups()), 1)
                backup = self.backups()[0]
                self.assertIn(str(backup), result.stdout)
                self.assertEqual((backup / 'reading-data').read_bytes(), b'books-and-notes')
                backup.rename(self.app)

    def test_missing_comparison_source_reports_failure(self):
        (self.app / 'nickelmenu.conf').unlink()
        result = self.run_uninstall()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.entry.is_file())
        self.assertNotIn('Menu entry was edited', result.stdout)
        self.assertEqual(len(self.backups()), 1)
        self.assertIn(str(self.backups()[0]), result.stdout)

    def test_edited_menu_is_preserved(self):
        self.entry.write_text('custom user menu\n')
        result = self.run_uninstall()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.entry.read_text(), 'custom user menu\n')
        self.assertFalse(self.app.exists())

    def test_active_session_refuses_without_changes(self):
        (self.app / 'state/active').mkdir(parents=True)
        result = self.run_uninstall()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.entry.is_file())
        self.assertTrue(self.app.exists())
        self.assertEqual(self.backups(), [])

    def test_backup_collision_does_not_nest_or_move_app(self):
        p = self.shims / 'date'
        p.write_text('#!/bin/sh\nprintf fixed\n')
        p.chmod(0o755)
        # Create the destination using the actual shell PID immediately before
        # exec, so the collision check is exercised without a production hook.
        wrapper = self.base / 'collision.sh'
        wrapper.write_text('#!/bin/sh\nmkdir "' + str(self.adds) + '/reeden-kobo-uninstalled-fixed-$$"\n'
                           'exec sh "' + str(self.app / 'uninstall.sh') + '"\n')
        result = subprocess.run(['sh', str(wrapper)], env=self.env, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.app.exists())
        self.assertTrue(self.entry.exists())
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(list(self.backups()[0].iterdir()), [])


if __name__ == '__main__':
    unittest.main()
