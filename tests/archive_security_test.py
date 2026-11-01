#!/usr/bin/env python3
"""Host writes/reads must stay within archive roots on Unix and Windows."""
import io
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install


def deb_bytes(members):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:gz') as tf:
        for name, kind, value in members:
            entry = tarfile.TarInfo(name)
            if kind == 'file':
                entry.size = len(value)
                tf.addfile(entry, io.BytesIO(value))
            else:
                entry.type = {'sym': tarfile.SYMTYPE, 'hard': tarfile.LNKTYPE, 'fifo': tarfile.FIFOTYPE}[kind]
                entry.linkname = value
                tf.addfile(entry)
    data = payload.getvalue()
    header = b'data.tar.gz/'.ljust(16) + b'0           0     0     100644  ' + str(len(data)).encode().ljust(10) + b'`\n'
    assert len(header) == 60
    return b'!<arch>\n' + header + data + (b'\n' if len(data) % 2 else b'')


class ArchiveSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='reeden-archive-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.dest = self.base / 'extract'
        self.outside = self.base / 'private'
        self.outside.write_bytes(b'HOST-SECRET-MUST-NOT-BE-READ-OR-OVERWRITTEN')

    def extract_deb(self, members):
        archive = self.base / 'test.deb'
        archive.write_bytes(deb_bytes(members))
        install.extract_deb_pure(archive, self.dest)

    def extract_zip(self, names):
        archive = self.base / 'test.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            for name in names:
                if isinstance(name, zipfile.ZipInfo):
                    z.writestr(name, b'link target')
                else:
                    z.writestr(name, b'payload')
        install.extract_official_zip(archive, self.dest)

    def assert_clean(self):
        self.assertEqual(self.outside.read_bytes(), b'HOST-SECRET-MUST-NOT-BE-READ-OR-OVERWRITTEN')
        self.assertFalse(self.dest.exists(), 'all member paths must be checked before writing')

    def test_zip_and_deb_reject_unsafe_paths_before_writing(self):
        paths = ['../private', str(self.outside), '/tmp/escape', 'C:/escape', r'C:\escape',
                 r'..\private', r'\\server\share\file', 'file:stream', 'CON', 'NUL.txt',
                 'COM¹.txt', 'trailing.', 'space ', 'a/../../private', 'bad?name']
        for path in paths:
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.extract_zip(['first-safe-file', path])
                self.assert_clean()
                with self.assertRaises(ValueError):
                    self.extract_deb([('first-safe-file', 'file', b'safe'), (path, 'file', b'attack')])
                self.assert_clean()

    def test_deb_rejects_outside_link_reads_and_linked_parent(self):
        for kind in ('sym', 'hard'):
            for target in ('../../private', str(self.outside), r'..\private', 'C:/private'):
                with self.subTest(kind=kind, target=target), self.assertRaises(ValueError):
                    self.extract_deb([('first', 'file', b'safe'), ('link', kind, target)])
                self.assert_clean()
        with self.assertRaises(ValueError):
            self.extract_deb([('parent', 'sym', 'directory'), ('parent/child', 'file', b'attack')])
        self.assert_clean()

    def test_special_files_and_case_collisions_rejected(self):
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with self.assertRaises(ValueError):
            self.extract_zip(['first', info])
        self.assert_clean()
        with self.assertRaises(ValueError):
            self.extract_deb([('first', 'file', b'safe'), ('pipe', 'fifo', '')])
        self.assert_clean()
        for names in (['File', 'file'], ['A/first', 'a/second'], ['parent', 'parent/child']):
            with self.assertRaises(ValueError):
                self.extract_zip(names)
            self.assert_clean()
            with self.assertRaises(ValueError):
                self.extract_deb([(name, 'file', b'safe') for name in names])
            self.assert_clean()

    @unittest.skipIf(os.name == 'nt', 'symlink privilege not assumed')
    def test_existing_destination_symlink_cannot_redirect(self):
        self.dest.mkdir()
        external = self.base / 'outside-dir'
        external.mkdir()
        (self.dest / 'redirect').symlink_to(external, target_is_directory=True)
        for extract in (lambda: self.extract_zip(['redirect/file']),
                        lambda: self.extract_deb([('redirect/file', 'file', b'attack')])):
            with self.assertRaises(ValueError):
                extract()
            self.assertFalse((external / 'file').exists())

    @unittest.skipIf(os.name == 'nt', 'symlink privilege not assumed')
    def test_expanded_official_tree_rejects_private_file_link(self):
        core = self.base / 'core'
        (core / 'lib').mkdir(parents=True)
        for name in ('libflutter_engine.so', 'libapp.so'):
            (core / 'lib' / name).write_bytes(b'placeholder')
        (core / 'private-link').symlink_to(self.outside)
        with self.assertRaisesRegex(ValueError, '链接'):
            install.resolve_official_core(str(core), self.base / 'temporary')
        self.assertEqual(self.outside.read_bytes(), b'HOST-SECRET-MUST-NOT-BE-READ-OR-OVERWRITTEN')

    def test_valid_links_are_copies_and_long_chains_resolve(self):
        members = [('./lib/real', 'file', b'library'), ('./usr/alias', 'sym', '../lib/real'),
                   ('./hard', 'hard', './lib/real')]
        members += [(f'chain{i}', 'sym', f'chain{i+1}') for i in range(8)]
        members += [('chain8', 'sym', 'lib/real')]
        self.extract_deb(members)
        for name in ('usr/alias', 'hard', 'chain0'):
            self.assertEqual((self.dest / name).read_bytes(), b'library')
            self.assertFalse((self.dest / name).is_symlink())

    def test_existing_hardlink_cannot_read_or_overwrite_host_file(self):
        self.dest.mkdir()
        os.link(self.outside, self.dest / 'host-link')
        with self.assertRaises(ValueError):
            self.extract_zip(['host-link'])
        with self.assertRaises(ValueError):
            self.extract_deb([('copy', 'sym', 'host-link')])
        self.assertFalse((self.dest / 'copy').exists())
        self.assertEqual(self.outside.read_bytes(), b'HOST-SECRET-MUST-NOT-BE-READ-OR-OVERWRITTEN')

    def test_invalid_ar_lengths_and_truncation_rejected(self):
        good = deb_bytes([('safe', 'file', b'file')])
        bad_length = good[:56] + b'-1'.ljust(10) + good[66:]
        for bad in (good[:20], good[:-10], bad_length, good + b'extra', good + good[8:]):
            archive = self.base / 'bad.deb'
            archive.write_bytes(bad)
            with self.assertRaises(ValueError):
                install.extract_deb_pure(archive, self.dest)
            self.assert_clean()


if __name__ == '__main__':
    unittest.main()
