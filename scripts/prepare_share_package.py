#!/usr/bin/env python3
"""Backward-compatible wrapper around the unified root install.py builder."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    args = sys.argv[1:]
    if '--output' not in args and '--usb' not in args and '--ssh' not in args and '--kobo-mount' not in args:
        args = [*args, '--output', 'package']
    sys.exit(subprocess.call([sys.executable, str(ROOT / 'install.py'), *args]))
