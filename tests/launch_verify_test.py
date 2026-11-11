#!/usr/bin/env python3
"""The launch-time verification cache must skip hashing only when it is safe.

A full SHA-256 pass over the installed package costs seconds on the device, so the
launcher caches the manifest hash and the fact that every listed file exists. This
test pins the four cases that decide between cached and full verification.
"""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
text = (root / 'scripts/run.sh').read_text()
start = text.index('# Recheck on every launch')
end = text.index(': > "$STATE/install-verified"') + len(': > "$STATE/install-verified"')
block = text[start:end] + '\n'


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(prefix='reeden-verify-') as tmp:
    app = Path(tmp) / 'app'
    state = Path(tmp) / 'state'
    app.mkdir()
    state.mkdir()
    (app / 'one.txt').write_text('one\n')
    (app / 'two.txt').write_text('two\n')
    (app / 'integrity.sh').write_text(
        '#!/bin/sh\n'
        'echo run >> "$APP/integrity-calls"\n'
        '[ -f "$APP/two.txt" ] || echo two > "$APP/two.txt"\n'
    )
    (app / 'integrity.sh').chmod(0o755)
    lines = [f'{digest(app / name)}  {name}' for name in ('one.txt', 'two.txt', 'integrity.sh')]
    (app / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')
    (Path(tmp) / 'block.sh').write_text(block)

    # The block runs under sh, so hand it POSIX-style paths on every platform.
    env = dict(os.environ, APP=app.as_posix(), STATE=state.as_posix())

    def run():
        result = subprocess.run(['sh', (Path(tmp) / 'block.sh').as_posix()], cwd=str(app),
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
        return result.stdout + result.stderr

    def calls() -> int:
        counter = app / 'integrity-calls'
        return len(counter.read_text().splitlines()) if counter.exists() else 0

    run()
    assert calls() == 1, 'first launch must run the full verification'

    output = run()
    assert calls() == 1, 'unchanged manifest must not re-hash every launch'
    assert 'skipped full hashing' in output, output

    (app / 'two.txt').unlink()
    run()
    assert calls() == 2, 'a missing file must trigger the repair path'
    assert (app / 'two.txt').exists(), 'the repair helper restores the missing file'

    stamp = (state / 'verify-stamp').read_text().split()
    (state / 'verify-stamp').write_text(f'{stamp[0]} {int(stamp[1]) - 691200}\n')
    run()
    assert calls() == 3, 'an expired stamp must force a full verification again'

print('PASS: verification cache skips only when the manifest and every file check out')
