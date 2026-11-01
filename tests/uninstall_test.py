#!/usr/bin/env python3
"""USB removal: data preservation, bounded deletion, guards and failure recovery."""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install
import uninstall


class UninstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reeden-usb-remove-')
        self.addCleanup(self.tmp.cleanup)
        self.mount = (Path(self.tmp.name) / 'Kobo device').resolve()
        (self.mount / '.kobo').mkdir(parents=True)
        (self.mount / '.kobo/version').write_text('SN,4.9.77,4.46.23836,000-393\n')
        self.app = self.mount / '.adds/reeden-kobo'
        self.nm = self.mount / '.adds/nm'
        self.nm.mkdir(parents=True)
        self.app.mkdir()
        self.menu = self.nm / 'reeden-kobo'
        self.menu.write_bytes(b'menu_item:main:Reeden:test\n')
        (self.app / 'nickelmenu.conf').write_bytes(self.menu.read_bytes())
        for rel in ('userdata/notes', 'storage/book.epub', 'diagnostics/ssh/hostkey', 'runtime/program'):
            file = self.app / rel
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'private data: ' + rel.encode())
        self.expected = {p.relative_to(self.app): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}
        (self.nm / 'other-reader').write_bytes(b'other config')
        (self.mount / 'native.epub').write_bytes(b'native book')
        (self.mount / '.adds/reeden-kobo-backup-old').mkdir()

    def run_remove(self, purge=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return uninstall.uninstall_usb(self.mount, purge)

    def unaffected(self):
        self.assertEqual((self.nm / 'other-reader').read_bytes(), b'other config')
        self.assertEqual((self.mount / 'native.epub').read_bytes(), b'native book')
        self.assertTrue((self.mount / '.adds/reeden-kobo-backup-old').is_dir())

    def test_default_preserves_every_file_and_repeat_is_noop(self):
        backup = self.run_remove()
        self.assertFalse(self.app.exists())
        self.assertFalse(self.menu.exists())
        actual = {p.relative_to(backup): p.read_bytes() for p in backup.rglob('*') if p.is_file()}
        self.assertEqual(actual, self.expected)
        self.assertIsNone(self.run_remove())
        self.assertTrue(backup.exists())
        self.unaffected()

    def test_purge_bounded_to_current_app(self):
        backup = self.run_remove(purge=True)
        self.assertFalse(self.app.exists())
        self.assertFalse(backup.exists())
        self.assertFalse(self.menu.exists())
        self.unaffected()

    def test_active_and_wrong_device_refuse_without_change(self):
        (self.app / 'state/active').mkdir(parents=True)
        with self.assertRaises(RuntimeError):
            self.run_remove()
        (self.app / 'state/active').rmdir()
        (self.mount / '.kobo/version').write_text('SN,4.9.77,4.46.23836,000-390')
        with self.assertRaises(RuntimeError):
            self.run_remove(purge=True)
        self.assertTrue(self.app.exists())
        self.assertTrue(self.menu.exists())

    def test_custom_menu_retained_with_warning(self):
        original = b'custom reader commands, including another app\n'
        self.menu.write_bytes(original)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            uninstall.uninstall_usb(self.mount)
        self.assertEqual(self.menu.read_bytes(), original)
        self.assertIn('手动', output.getvalue())
        self.unaffected()

    def test_menu_failure_restores_app_and_data(self):
        real_unlink = Path.unlink
        def fail_menu(path, *args, **kwargs):
            if path == self.menu:
                raise OSError('simulated read-only menu')
            return real_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, 'unlink', fail_menu), self.assertRaises(RuntimeError):
            self.run_remove()
        self.assertTrue(self.menu.exists())
        self.assertEqual({p.relative_to(self.app): p.read_bytes() for p in self.app.rglob('*') if p.is_file()}, self.expected)
        self.assertFalse(list(self.app.parent.glob('reeden-kobo-uninstalled-*')))

    def test_purge_failure_reports_remaining_location(self):
        with mock.patch.object(uninstall.shutil, 'rmtree', side_effect=OSError('I/O error')):
            with self.assertRaisesRegex(RuntimeError, '剩余文件位于'):
                self.run_remove(purge=True)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.menu.exists())
        backup, = self.app.parent.glob('reeden-kobo-uninstalled-*')
        self.assertEqual((backup / 'userdata/notes').read_bytes(), self.expected[Path('userdata/notes')])

    @unittest.skipIf(os.name == 'nt', 'symlink privilege not assumed on Windows')
    def test_redirected_app_is_rejected(self):
        original = self.app.with_name('original')
        self.app.rename(original)
        self.app.symlink_to(original, target_is_directory=True)
        with self.assertRaises(RuntimeError):
            self.run_remove(purge=True)
        self.assertTrue((original / 'userdata/notes').is_file())
        self.assertTrue(self.menu.exists())

    def test_cli_requires_confirmation(self):
        command = [sys.executable, str(ROOT / 'uninstall.py'), '--kobo-mount', str(self.mount), '--purge']
        result = subprocess.run(command, input='', text=True, capture_output=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.app.exists())
        result = subprocess.run(command + ['--yes'], text=True, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.unaffected()

    def test_multiple_drives_never_pick_first(self):
        with self.assertRaises(RuntimeError):
            install.choose_kobo_usb_mount([self.mount, self.mount / 'another'])
        with self.assertRaises(RuntimeError):
            install.choose_kobo_usb_mount([])
        self.assertEqual(install.choose_kobo_usb_mount([self.mount]), self.mount)

    def test_interactive_purge_must_type_exact_confirmation(self):
        for answer in ('', 'yes'):
            with mock.patch.object(sys, 'argv', ['uninstall.py', '--kobo-mount', str(self.mount)]), \
                 mock.patch.object(sys.stdin, 'isatty', return_value=True), \
                 mock.patch('builtins.input', side_effect=['2', answer]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(uninstall.main(), 0)
            self.assertTrue(self.app.exists())


if __name__ == '__main__':
    unittest.main()
