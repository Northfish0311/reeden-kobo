#!/usr/bin/env python3
"""Exercise recovery with synthetic child processes, never hardware or Reeden."""
from pathlib import Path
import hashlib, os, shutil, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="reeden-launcher-") as temp:
    app = Path(temp)
    for directory in ("bin", "runtime", "core", "state", "logs"):
        (app / directory).mkdir()
    for name in ("run.sh", "recover.sh"):
        shutil.copy2(ROOT / "scripts" / name, app / name)
        (app / name).chmod(0o755)
    (app / "version").write_text("SN,4.9.77,4.46.23836,000-393\n")
    (app / "brightness").write_text("12\n")
    (app / "warmth").write_text("5\n")
    for name in ("run.sh", "recover.sh"):
        path = app / name
        text = path.read_text().replace("/mnt/onboard/.kobo/version", str(app / "version")).replace("/sys/class/backlight/mxc_msp430.0/brightness", str(app / "brightness")).replace("/sys/class/backlight/lm3630a_led/color", str(app / "warmth"))
        path.write_text(text)
    def script(path, text):
        path.write_text("#!/bin/sh\n" + text)
        path.chmod(0o755)
    script(app / "guardian.sh", "exit 0\n")
    # Only the synthetic app child may be terminated. Any Nickel STOP/CONT is
    # recorded, so the warmup failure path can assert that neither occurred.
    script(app / "session.sh", '''
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STATE="$APP/state"
token() { echo 1; }
same_process() { /bin/kill -0 "$1" 2>/dev/null; }
owned_host() {
  [ -f "$STATE/host" ] || return 1
  read -r HOST HOST_TOKEN < "$STATE/host"
  /bin/kill -0 "$HOST" 2>/dev/null
}
pidof() { [ "$1" = nickel ] && echo 999999; }
sleep() { /bin/sleep 0.02; }
kill() {
  case "$1" in -STOP|-CONT) echo "$*" >> "$APP/signals";;
  *) /bin/kill "$@";; esac
}
''')
    script(app / "bin/fb-guard", '''
if [ "$1" = --recover-session ]; then exec /bin/sh "$2/recover.sh" --locked "$3"; fi
echo "$*" >> "$(dirname "$0")/../framebuffer-calls"
[ "$1" = --inspect ]
''')
    script(app / "runtime/reeden-kindle", '''
[ "$1" = --verify ] && exit 0
printf '%s\\n' "${REEDEN_TURN_PROFILE-unset}" "${REEDEN_TEXT_BAND_PATH-unset}" "${REEDEN_TEXT_QUALITY_AFTER_TURN-unset}" > "$REEDEN_KOBO_DIR/host-env"
exec /bin/sleep 5
''')
    (app / "version").write_text("SN,4.9.77,4.46.23836,000-391\n")
    wrong = subprocess.run(["sh", str(app / "run.sh")], capture_output=True, timeout=10)
    assert wrong.returncode == 12 and not (app / "framebuffer-calls").exists()
    (app / "version").write_text("SN,4.9.77,4.46.23836,000-393\n")
    files = sorted(path for path in app.rglob('*') if path.is_file())
    (app / "SHA256SUMS").write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(app).as_posix()}\n'
        for path in files))
    keys = ("REEDEN_TURN_PROFILE", "REEDEN_TEXT_BAND_PATH", "REEDEN_TEXT_QUALITY_AFTER_TURN")
    env = {k: v for k, v in os.environ.items() if k not in keys}
    p = subprocess.run(["sh", str(app / "run.sh")], timeout=10, env=env)
    log = (app / "logs/launcher.log").read_text()
    assert p.returncode == 20, (p.returncode, log)
    assert "Nickel was never paused" in log, log
    assert "[recovery] completed" in log, log
    assert not (app / "signals").exists(), "Nickel received a signal during failed warmup"
    assert (app / "framebuffer-calls").read_text().strip() == "--inspect"
    assert not (app / "state/active").exists(), "Session lock leaked"
    assert not (app / "state/handoff").exists(), "Hardware handoff leaked"

    host_env = app / "host-env"
    assert host_env.read_text().splitlines() == ["unset"] * 3
    inherited = dict(zip(keys, ("timed", "reagl", "1")))
    for profile, expected in {
        "stable": ["stable", "unset", "unset"],
        "off": ["off", "unset", "unset"],
        "timed": ["timed", "unset", "unset"],
        "reagl": ["stable", "reagl", "unset"],
        "clean": ["stable", "unset", "1"],
        "invalid": list(inherited.values()),
    }.items():
        host_env.unlink()
        (app / "userdata/turn-profile").write_bytes((profile + "\r\n").encode())
        p = subprocess.run(["sh", str(app / "run.sh")], timeout=10, env={**env, **inherited})
        assert p.returncode == 20, (profile, p.returncode, (app / "logs/launcher.log").read_text())
        assert host_env.read_text().splitlines() == expected, profile
    print("PASS: device profiles survive launch verification and select independent refresh modes")
    print("PASS: missing first frame exits 20; no Nickel signals, framebuffer writes or input grabs; owned child recovered")
