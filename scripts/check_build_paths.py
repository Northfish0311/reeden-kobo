#!/usr/bin/env python3
"""Fail if an ARM build product contains a build-machine path."""
from pathlib import Path
import re
import sys

leak = re.compile(rb'(?:[a-z]:[/\\]users[/\\]|/(?:Users|home|private)/|zig-(?:macos|linux|windows)-|lib[/\\]libc[/\\]musl|[/\\]lib[/\\]std[/\\])', re.I)
for name in sys.argv[1:]:
    if leak.search(Path(name).read_bytes()):
        raise SystemExit(f'Build-machine path found in {Path(name).name}')
