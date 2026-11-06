#!/usr/bin/env python3
"""Synthetic recovery regressions: no official payloads, downloads or device I/O.

Run: python3 tests/resource_recovery_test.py
All fixture files, including shell scratch files, live in the session tmp/ tree.
"""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SESSION_TMP = ROOT.parent.parent / "tmp" / "resource-recovery-tests"
RESOURCE_SUFFIXES = (
    "lib/common/widgets/theme_effect/theme_scaffold_ripple.frag",
    "packages/flutter_math_fork/lib/katex_fonts/fonts/KaTeX_Script-Regular.ttf",
    "packages/liquid_glass_renderer/lib/assets/shaders/liquid_glass_final_render.frag",
)
RESOURCES = tuple(f"{base}/{suffix}" for base in
                  ("core/data/flutter_assets", "ui-assets")
                  for suffix in RESOURCE_SUFFIXES)
ARCHIVE = "integrity/resources.tar.gz"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_installer():
    spec = importlib.util.spec_from_file_location("resource_recovery_installer", ROOT / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResourceRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SESSION_TMP.mkdir(parents=True, exist_ok=True)
        cls.installer = load_installer()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="case-", dir=SESSION_TMP)
        self.addCleanup(self.temp.cleanup)
        self.app = Path(self.temp.name) / "synthetic-install"
        self.app.mkdir()
        self.env = dict(os.environ, LC_ALL="C", TMPDIR=str(self.app / "scratch"))
        self.write("scratch/.keep", b"")
        self.payloads = {rel: ("fixture: " + rel + "\n").encode() for rel in RESOURCES}
        # Distinct core and overlay bytes catch accidental cross-root restoration.
        self.payloads["core/data/icudtl.dat"] = b"synthetic ICU data\x00\xff"
        self.payloads["ui-assets/assets/fonts/KoboCJKMath-Regular.ttf"] = b"synthetic merged font"
        for rel, data in self.payloads.items():
            self.write(rel, data)
        self.write("core/lib/libapp.so", b"synthetic core binary; never recover")
        self.write("core/lib/libflutter_engine.so", b"synthetic engine; never recover")
        self.write("bin/reeden-kindle", b"synthetic host; never execute")
        self.write("userdata/notes.json", b'{"note":"keep me"}\n')
        self.write("storage/books/book.epub", b"user-owned book bytes")
        self.write("state/install-verified", b"historical successful install\n")
        self.write("build-info.json", json.dumps({
            "port_version": "9.8.7-recovery-fixture", "official_version": "fixture-core"
        }).encode())
        for name in ("integrity.sh", "precheck.sh"):
            text = (ROOT / "scripts" / name).read_text()
            if name == "precheck.sh":
                # Redirect hardware reads and scratch writes in the fixture only.
                for source, target in (
                    ("/mnt/onboard/.kobo/version", "device-version"),
                    ("/sys/class/backlight/mxc_msp430.0/brightness", "brightness"),
                    ("/sys/class/backlight/lm3630a_led/color", "warmth"),
                    ("/tmp/reeden-check-XXXXXX", "scratch/reeden-check-XXXXXX"),
                ):
                    text = text.replace(source, str(self.app / target))
            self.write(name, text.encode())
        self.write("device-version", b"SN,4.9.77,4.46.23836,000-393\n")
        self.write("brightness", b"20\n")
        self.write("warmth", b"5\n")
        self.script("bin/fb-guard", 'test "$1" = --inspect\n')
        self.script("runtime/reeden-kindle", 'test "$1" = --verify\n')
        self.installer.create_resource_recovery(self.app)
        self.manifest_paths = tuple(sorted(
            p.relative_to(self.app).as_posix() for p in self.app.rglob("*")
            if p.is_file() and p.relative_to(self.app).parts[0] not in
            {"userdata", "storage", "state", "scratch"}
        ))
        self.manifest_bytes = self.make_manifest()
        self.protected = {rel: (self.app / rel).read_bytes() for rel in (
            "userdata/notes.json", "storage/books/book.epub", "SHA256SUMS"
        )}

    def write(self, rel, data):
        path = self.app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def script(self, rel, text):
        path = self.write(rel, ("#!/bin/sh\n" + text).encode())
        path.chmod(0o755)
        return path

    def make_manifest(self):
        data = "".join(f"{digest((self.app / rel).read_bytes())}  {rel}\n"
                       for rel in self.manifest_paths).encode()
        self.write("SHA256SUMS", data)
        return data

    def run_shell(self, name, *args):
        result = subprocess.run(["sh", str(self.app / name), *args],
                                cwd=self.app, env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
        return result.returncode, result.stdout

    def remove_six(self):
        for rel in RESOURCES:
            (self.app / rel).unlink()

    def assert_missing_report(self, rel, output):
        # macOS sha256sum reports ENOENT; GNU/BusyBox also emit FAILED open/read.
        self.assertTrue(any(rel + ":" in line and
                            ("FAILED" in line or "No such file" in line)
                            for line in output.splitlines()), output)

    def assert_protected(self):
        for rel, data in self.protected.items():
            self.assertEqual((self.app / rel).read_bytes(), data, rel)
        self.assertEqual(list(self.app.rglob(".reeden-resource-*")), [], "staging files leaked")

    def assert_restored(self):
        for rel, data in self.payloads.items():
            self.assertEqual((self.app / rel).read_bytes(), data, rel)
        self.assert_protected()

    def rewrite_archive(self, changes=None, omit=(), extra=None):
        """Make an authenticated archive with invalid members; keep file digests original."""
        contents = dict(self.payloads)
        contents.update(changes or {})
        for rel in omit:
            contents.pop(rel)
        contents.update(extra or {})
        with tarfile.open(self.app / ARCHIVE, "w:gz") as archive:
            for rel, data in contents.items():
                member = tarfile.TarInfo(rel)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        lines = self.manifest_bytes.decode().splitlines()
        data = "\n".join(f"{digest((self.app / ARCHIVE).read_bytes())}  {ARCHIVE}"
                         if line.endswith("  " + ARCHIVE) else line
                         for line in lines) + "\n"
        self.write("SHA256SUMS", data.encode())
        self.protected["SHA256SUMS"] = data.encode()

    def test_archive_contains_all_resource_bytes_and_no_user_data_or_binaries(self):
        with tarfile.open(self.app / ARCHIVE) as archive:
            files = {member.name: archive.extractfile(member).read()
                     for member in archive.getmembers() if member.isfile()}
        self.assertEqual(files, self.payloads)
        self.assertIn(f"{digest((self.app / ARCHIVE).read_bytes())}  {ARCHIVE}\n".encode(),
                      self.manifest_bytes)
        self.assertEqual(self.run_shell("integrity.sh", "check")[0], 0)

    def test_real_assembly_includes_recovery_archive_in_final_sha_manifest(self):
        # Exercise the real assembly order; replace only download inputs with
        # synthetic local payloads, not the archive or manifest implementations.
        base = Path(self.temp.name) / "assembly"
        source, prebuilt, staging, dest = (base / name for name in
                                           ("source", "prebuilt", "staging", "package"))

        def put(path, data=b"synthetic assembly input"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        put(source / "vendor/debian-runtime-manifest.json", b"[]")
        put(source / "vendor/font-manifest.json", b'{"url":"fixture:font","sha256":"unused"}')
        put(source / "LICENSE")
        (source / "docs").mkdir()
        shutil.copytree(ROOT / "scripts", source / "scripts")
        core = base / "official"
        shutil.copytree(self.app / "core", core)
        put(core / "data/flutter_assets/FontManifest.json", b'[{"family":"NotoSansMath","fonts":[]}]')
        put(core / "lib/glibc/ld-linux-armhf.so.3")
        put(core / "licenses/LICENSE")
        put(core / "THIRD_PARTY_NOTICES.txt")
        for rel in ("fonts/KoboCJKMath-Regular.ttf", "bin/fb-guard", "bin/reeden-kindle",
                    "lib/libreeden_kobo_compat.so", "checks/synthetic-check"):
            put(prebuilt / rel)
        font = base / "local-font.otf"
        put(font)
        for stem in ("gio", "glib", "gobject", "gmodule", "gthread"):
            put(staging / f"debian-runtime/lib/arm-linux-gnueabihf/lib{stem}-2.0.so.0")
        for number in range(100):
            put(staging / f"debian-runtime/usr/share/ca-certificates/mozilla/{number}.crt")
        with mock.patch.object(self.installer, "ROOT", source), \
                mock.patch.object(self.installer, "download_verified", return_value=font) as download:
            count = self.installer.assemble_package(core, "synthetic-core", prebuilt, dest, staging)
        download.assert_called_once()
        entries = dict(line.split("  ", 1)[::-1] for line in
                       (dest / "SHA256SUMS").read_text().splitlines())
        self.assertEqual(count, len(entries))
        self.assertIn(ARCHIVE, entries)
        self.assertEqual(entries[ARCHIVE], digest((dest / ARCHIVE).read_bytes()))
        for rel, expected in entries.items():
            self.assertEqual(digest((dest / rel).read_bytes()), expected, rel)
        with tarfile.open(dest / ARCHIVE) as archive:
            names = set(archive.getnames())
            for rel in RESOURCES:
                self.assertIn(rel, names)
                with archive.extractfile(rel) as member:
                    self.assertEqual(member.read(), (dest / rel).read_bytes(), rel)
            self.assertNotIn("core/lib/libapp.so", names)

    def test_check_reports_all_six_missing_paths_without_repairing(self):
        self.remove_six()
        code, output = self.run_shell("integrity.sh", "check")
        self.assertNotEqual(code, 0, output)
        for rel in RESOURCES:
            self.assert_missing_report(rel, output)
            self.assertFalse((self.app / rel).exists())
        self.assert_protected()

    def test_repair_restores_six_files_then_passes_full_check_and_is_idempotent(self):
        self.remove_six()
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertEqual(code, 0, output)
        self.assert_restored()
        for rel in RESOURCES:
            self.assertIn("[RESTORED] " + rel, output)
        before = {rel: (self.app / rel).stat().st_mtime_ns for rel in self.payloads}
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertEqual(code, 0, output)
        self.assertNotIn("[RESTORED]", output)
        self.assertEqual(before, {rel: (self.app / rel).stat().st_mtime_ns for rel in self.payloads})
        self.assertEqual(self.run_shell("integrity.sh", "check")[0], 0)
        self.assert_restored()

    def test_damaged_archive_is_rejected_before_restoring_any_missing_file(self):
        self.remove_six()
        with (self.app / ARCHIVE).open("ab") as stream:
            stream.write(b"tampered archive bytes")
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertIn("checksum", output.lower())
        for rel in RESOURCES:
            self.assertFalse((self.app / rel).exists(), rel)
        self.assert_protected()

    def test_missing_archive_checksum_is_not_trusted(self):
        self.remove_six()
        data = b"".join(line for line in self.manifest_bytes.splitlines(keepends=True)
                        if not line.endswith(("  " + ARCHIVE + "\n").encode()))
        self.write("SHA256SUMS", data)
        self.protected["SHA256SUMS"] = data
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        for rel in RESOURCES:
            self.assertFalse((self.app / rel).exists(), rel)
        self.assert_protected()

    def test_existing_changed_resource_is_reported_and_never_overwritten(self):
        rel = RESOURCES[0]
        changed = b"existing custom or damaged data must survive"
        self.write(rel, changed)
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertIn(rel + ": FAILED", output)
        self.assertEqual((self.app / rel).read_bytes(), changed)
        self.assert_protected()

    def test_concurrent_creator_is_never_overwritten(self):
        rel = RESOURCES[0]
        target = self.app / rel
        target.unlink()
        real_chmod = shutil.which("chmod")
        self.script("tools/chmod", '''
case "$2" in
  */.reeden-resource-*) printf 'concurrent writer bytes' > "$RACE_TARGET";;
esac
exec "''' + real_chmod + '''" "$@"
''')
        self.env["RACE_TARGET"] = str(target)
        self.env["PATH"] = str(self.app / "tools") + os.pathsep + self.env.get("PATH", "")
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertEqual(target.read_bytes(), b"concurrent writer bytes")
        self.assertNotIn("[RESTORED] " + rel, output)
        self.assert_protected()

    def test_missing_binary_is_not_recovered_even_if_archive_contains_it(self):
        binary = "bin/reeden-kindle"
        self.rewrite_archive(extra={binary: (self.app / binary).read_bytes()})
        (self.app / binary).unlink()
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assert_missing_report(binary, output)
        self.assertFalse((self.app / binary).exists())
        self.assert_protected()

    def test_active_session_rejects_repair_before_any_write(self):
        self.remove_six()
        (self.app / "state/active").mkdir()
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertTrue("exit reeden" in output.lower() or "active" in output.lower(), output)
        for rel in RESOURCES:
            self.assertFalse((self.app / rel).exists(), rel)
        self.assertTrue((self.app / "state/active").is_dir())
        self.assert_protected()

    def test_authenticated_wrong_member_bytes_are_not_committed(self):
        rel = RESOURCES[0]
        self.rewrite_archive(changes={rel: b"wrong member bytes"})
        (self.app / rel).unlink()
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertIn(rel, output)
        self.assertFalse((self.app / rel).exists())
        self.assert_protected()

    def test_authenticated_archive_missing_member_leaves_target_absent(self):
        rel = RESOURCES[0]
        self.rewrite_archive(omit=(rel,))
        (self.app / rel).unlink()
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertIn(rel, output)
        self.assertFalse((self.app / rel).exists())
        self.assert_protected()

    def test_symlink_target_does_not_overwrite_user_data(self):
        rel = RESOURCES[0]
        (self.app / rel).unlink()
        (self.app / rel).symlink_to(self.app / "userdata/notes.json")
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertTrue((self.app / rel).is_symlink())
        self.assert_protected()

    def test_symlink_parent_does_not_write_outside_resource_tree(self):
        parent = (self.app / RESOURCES[0]).parent
        shutil.rmtree(parent)
        outside = self.app / "userdata/redirected"
        outside.mkdir()
        self.write("userdata/redirected/keep.txt", b"keep outside bytes")
        parent.symlink_to(outside, target_is_directory=True)
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assertEqual({p.name: p.read_bytes() for p in outside.iterdir()},
                         {"keep.txt": b"keep outside bytes"})
        self.assert_protected()

    def test_unsafe_manifest_path_cannot_overwrite_user_data(self):
        rel = "core/data/../../userdata/notes.json"
        data = (digest(b"replace note") + "  " + rel + "\n").encode() + self.manifest_bytes
        self.write("SHA256SUMS", data)
        self.protected["SHA256SUMS"] = data
        code, output = self.run_shell("integrity.sh", "repair")
        self.assertNotEqual(code, 0, output)
        self.assert_protected()

    def test_precheck_shows_actual_build_version_and_every_missing_resource(self):
        self.remove_six()
        self.write("install-verification.log", b"stale success: everything OK\n")
        code, output = self.run_shell("precheck.sh")
        self.assertEqual(code, 0, output)  # NickelMenu displays errors in its dialog.
        self.assertIn("9.8.7-recovery-fixture", output)
        self.assertIn("[FAIL] Package SHA-256", output)
        for rel in RESOURCES:
            self.assertIn(rel, output)
        for rel in RESOURCES:
            self.assertFalse((self.app / rel).exists())
        self.assert_protected()

    def prepare_launcher(self, recovery_body=None):
        # Stop at the loader verification boundary, before a session can own hardware.
        self.script("session.sh", '''
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE="$APP/state"
pidof() { [ "$1" = nickel ] && echo 999999; }
same_process() { return 1; }
''')
        self.script("runtime/reeden-kindle", 'exit 1\n')
        text = (ROOT / "scripts/run.sh").read_text().replace(
            "/mnt/onboard/.kobo/version", str(self.app / "device-version"))
        self.write("run.sh", text.encode())
        self.manifest_paths += ("session.sh", "run.sh")
        if recovery_body is not None:
            self.script("recover.sh", recovery_body)
            self.manifest_paths += ("recover.sh",)
        self.manifest_bytes = self.make_manifest()
        self.protected["SHA256SUMS"] = self.manifest_bytes

    def test_launch_rechecks_after_historical_install_verified_marker(self):
        self.prepare_launcher()
        self.remove_six()
        code, output = self.run_shell("run.sh")
        log = (self.app / "logs/launcher.log").read_text()
        self.assertEqual(code, 13, output + log)
        self.assert_restored()
        # A second disappearance must also be repaired despite the marker.
        (self.app / RESOURCES[-1]).unlink()
        code, output = self.run_shell("run.sh")
        self.assertEqual(code, 13, output + (self.app / "logs/launcher.log").read_text())
        self.assert_restored()
        self.assertFalse((self.app / "state/active").exists())

    def test_launch_repairs_resources_after_stale_session_recovery(self):
        self.prepare_launcher('''
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
rmdir "$APP/state/active" || exit 1
: > "$APP/recovery-ran"
''')
        self.write("state/owner", b"999999 1\n")
        (self.app / "state/active").mkdir()
        self.remove_six()
        code, output = self.run_shell("run.sh")
        self.assertEqual(code, 13, output + (self.app / "logs/launcher.log").read_text())
        self.assertTrue((self.app / "recovery-ran").is_file())
        self.assertFalse((self.app / "state/active").exists())
        self.assert_restored()

    def test_failed_or_busy_session_blocks_resource_repair(self):
        self.prepare_launcher('''
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
read -r status < "$APP/state/recovery-status" || exit 1
exit "$status"
''')
        self.write("state/owner", b"999999 1\n")
        (self.app / "state/active").mkdir()
        self.remove_six()
        for status in (1, 75):
            with self.subTest(recovery_status=status):
                self.write("state/recovery-status", f"{status}\n".encode())
                code, output = self.run_shell("run.sh")
                self.assertEqual(code, 14, output + (self.app / "logs/launcher.log").read_text())
                self.assertTrue((self.app / "state/active").exists())
                self.assertFalse((self.app / "install-verification.log").exists())
                for rel in RESOURCES:
                    self.assertFalse((self.app / rel).exists(), rel)
                self.assert_protected()


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    unittest.main(verbosity=2)
