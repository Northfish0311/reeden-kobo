#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build synthetic Kobo device-layout fixtures for the acceptance QA regression.

Every fixture reproduces the real on-device layout:
    <case>/device/.adds/reeden-kobo/...        (APP root)
    <case>/device/.kobo/Kobo/Kobo eReader.conf (Nickel config, OUTSIDE .adds)

All log lines are ASCII and imitate the exact strings emitted by
tag v0.7.9-community.4 (3b804d2), verified separately by audit.py.

Usage:  python build_fixtures.py
Re-running is idempotent: the cases/ tree is rebuilt from scratch.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"

# ---------------------------------------------------------------------------
# Reusable synthetic log blocks (order follows the real source paths)
# ---------------------------------------------------------------------------

POWER_HAPPY = [
    "[power] invoked arg=suspend Mon Nov 12 04:13:02 UTC 2026",
    "[power] phase=preparing uptime=12340 pid=4711 Mon Nov 12 04:13:02 UTC 2026",
    "[power] preparing Mon Nov 12 04:13:02 UTC 2026",
    "[power] sample=prepare battery=Discharging external=off capacity=88",
    "[power] display settle completed after 3 polls",
    "[power] sample=before_mem battery=Discharging external=off capacity=88",
    "[power] entering mem Mon Nov 12 04:13:06 UTC 2026",
    "[power] phase=suspended uptime=12346 pid=4711 Mon Nov 12 04:13:06 UTC 2026",
    "[power] phase=resuming uptime=25206 pid=4711 Mon Nov 12 12:13:06 UTC 2026",
    "[power] mem returned=0 Mon Nov 12 12:13:06 UTC 2026",
    "[power] sample=after_mem battery=Discharging external=off capacity=87",
    "[power] Wi-Fi resume deferred while cover remains closed",
    "[power] phase=complete uptime=25208 pid=4711 Mon Nov 12 12:13:08 UTC 2026",
    "[power] helper exiting=0 Mon Nov 12 12:13:08 UTC 2026",
]

CURRENT_HAPPY = [
    "[display] FIRST_FRAME_RECEIVED",
    "[host] first frame ready; waiting for launcher handoff",
    "[power] exclusive power key acquired",
    "[cover] candidate event3 SW_LID",
    "[cover] closed",
    "[power] phase=cover-closed wall=1762927982 mono_ms=123456",
    "[power] phase=locking wall=1762927983 mono_ms=123556",
    "[power] screen locked; engine retained",
    "[sleep-cover] not registered; keeping current page",
    "[power] phase=starting-helper wall=1762927984 mono_ms=125056",
    "[cover] opened",
    "[power] phase=cover-opened wall=1762935182 mono_ms=7323456",
    "[power] wake requested; waiting for hardware restoration",
    "[power] phase=restoring-reader wall=1762935183 mono_ms=7323556",
    "[power] resumed same engine and book",
    "[power] phase=reader-resumed wall=1762935184 mono_ms=7323656",
    "[power] key release",
    "[page-turn] arm type=1 forward=1 vertical=0 steps=16 accepted=1",
    "[page-turn] bands=16 direction=next vertical=0 night=0 path=reagl wave=1 mode=2",
    "[page-turn] submissions=16 span_ms=310.4 min_gap_ms=18.2",
    "[wifi] panel helper finished action=1 result=11",
    "[wifi] panel helper finished action=2 result=0",
    "[wifi] panel helper finished action=3 result=0",
    "[display] FIRST_UPDATE_SUBMITTED marker=1",
]

LAUNCHER_HAPPY = [
    "[launcher] Mon Nov 12 04:12:58 UTC 2026",
    "[verify] manifest unchanged and every file present; skipped full hashing",
    "[launcher] first frame ready; hardware handoff authorized",
    "[launcher] first frame took 4s",
    "[launcher] host exit=0",
    "[recovery] restoring this session",
    "[recovery] Nickel brightness updated to 46",
    "[recovery] completed",
]

INSTALL_VERIFICATION = [
    "core/data/flutter_assets/fonts/NotoSans-Regular.ttf: OK",
    "ui-assets/sleep-cover.png: OK",
]

KOBO_CONF_HAPPY = [
    "[PowerOptions]",
    "FrontLightLevel=46",
    "FrontLightState=1",
    "[Reading]",
    "FontScale=1.0",
]

WIFI_LOG = [
    "[wifi] request=probe Mon Nov 12 05:01:00 UTC 2026",
    "[wifi] radio off",
    "[wifi] request=on Mon Nov 12 05:01:20 UTC 2026",
    "[wifi] association/DHCP started; connection is not yet assumed",
]

# guardian.sh appends to launcher.log, but run.sh rotates a dedicated
# logs/guardian.log too; keep a realistic one for the overnight fixture.
GUARDIAN_LOG = [
    "[guardian] power phase suspended exceeded 45s; recovering native UI Mon Nov 12 12:13:06 UTC 2026",
    "[guardian] heartbeat timeout",
]


def app_rel(*parts):
    return str(Path("device/.adds/reeden-kobo", *parts))


def log_rel(name):
    return app_rel("logs", name)


def base_files(power=None, current=None, launcher=None, previous=None,
               conf=None, install=None, wifi_log=None, power_log_1=None,
               guardian_log=None):
    """Return the standard device file map, with optional overrides."""
    files = {
        log_rel("launcher.log"): LAUNCHER_HAPPY if launcher is None else launcher,
        log_rel("current.log"): CURRENT_HAPPY if current is None else current,
        log_rel("power.log"): POWER_HAPPY if power is None else power,
        app_rel("install-verification.log"): (
            INSTALL_VERIFICATION if install is None else install),
        "device/.kobo/Kobo/Kobo eReader.conf": (
            KOBO_CONF_HAPPY if conf is None else conf),
        app_rel("userdata/turn-profile"): ["stable"],
        app_rel("userdata/wifi-handoff"): ["default"],
    }
    if previous is not None:
        files[log_rel("previous.log")] = previous
    if wifi_log is not None:
        files[log_rel("wifi.log")] = wifi_log
    if power_log_1 is not None:
        files[log_rel("power.log.1")] = power_log_1
    if guardian_log is not None:
        files[log_rel("guardian.log")] = guardian_log
    return files


# ---------------------------------------------------------------------------
# Case definitions
# ---------------------------------------------------------------------------

CASES_DEF = {}

# 1. Full success: every non-manual item should PASS.
CASES_DEF["happy"] = base_files(previous=[])

# 2. Explicit counter-evidence: kernel suspend returned non-zero.
CASES_DEF["fail-mem-returned1"] = base_files(
    power=[line.replace("mem returned=0", "mem returned=1")
           .replace("helper exiting=0", "helper exiting=1")
           for line in POWER_HAPPY])

# 3. Explicit counter-evidence: first frame never arrived.
CASES_DEF["fail-no-first-frame"] = base_files(
    launcher=[line for line in LAUNCHER_HAPPY
              if "first frame took" not in line] +
             ["[launcher] no first frame in 20s; Nickel was never paused"])

# 4. Explicit counter-evidence: Nickel brightness write failed.
CASES_DEF["fail-brightness"] = base_files(
    launcher=[("[recovery] Nickel brightness update failed; hardware value kept"
               if "Nickel brightness updated to" in line else line)
              for line in LAUNCHER_HAPPY])

# 5. Designed guard: supply protection (exit 3). No entering mem / mem returned.
CASES_DEF["guard-supply-only"] = base_files(
    power=[
        "[power] invoked arg=suspend Mon Nov 12 04:13:02 UTC 2026",
        "[power] phase=preparing uptime=12340 pid=4711 Mon Nov 12 04:13:02 UTC 2026",
        "[power] sample=prepare battery=Full external=on capacity=100",
        "[power] screen-only: supply guard battery=Full external=on",
        "[power] phase=complete uptime=12341 pid=4711 Mon Nov 12 04:13:03 UTC 2026",
        "[power] helper exiting=3 Mon Nov 12 04:13:03 UTC 2026",
    ],
    current=[], launcher=[])

# 6. Designed guard: busy display (exit 75).
CASES_DEF["guard-display-busy"] = base_files(
    power=[
        "[power] invoked arg=suspend Mon Nov 12 04:13:02 UTC 2026",
        "[power] phase=preparing uptime=12340 pid=4711 Mon Nov 12 04:13:02 UTC 2026",
        "[power] sample=prepare battery=Discharging external=off capacity=70",
        "[power] display did not become idle",
        "[power] phase=complete uptime=12364 pid=4711 Mon Nov 12 04:13:15 UTC 2026",
        "[power] helper exiting=75 Mon Nov 12 04:13:15 UTC 2026",
    ],
    current=[], launcher=[])

# 7. Rotation: this round's evidence lives only in previous.log.
CASES_DEF["rotated-previous-only"] = base_files(current=[], previous=CURRENT_HAPPY)

# 8. No previous.log at all: current.log has everything.
CASES_DEF["missing-previous"] = base_files()

# 9. Every log exists but is empty; conf has no FrontLightLevel.
CASES_DEF["empty-logs"] = base_files(
    power=[], current=[], launcher=[], previous=[],
    conf=["[PowerOptions]", "FrontLightState=1"])

# 10. arm accepted=1 only, no bands= / submissions= -> animation NOT confirmed.
CASES_DEF["accepted-only"] = base_files(
    current=[
        "[display] FIRST_FRAME_RECEIVED",
        "[page-turn] arm type=1 forward=1 vertical=0 steps=16 accepted=1",
    ],
    power=[], launcher=[], previous=[])

# 11. -OutDir safety tests reuse a normal device layout.
CASES_DEF["outdir-inside-appdir"] = base_files()
CASES_DEF["outdir-equals-appdir"] = base_files()
CASES_DEF["outdir-mountroot"] = base_files()

# 12. FrontLightLevel outside [PowerOptions]: Collect filters it, -AppDir does not.
CASES_DEF["frontlight-other-section"] = base_files(
    conf=["[SomeOtherSection]", "FrontLightLevel=46", "[PowerOptions]",
          "FrontLightState=1"])

# 13. power.log rotated to power.log.1; Collect does not copy the .1 file.
CASES_DEF["powerlog-rotated"] = base_files(
    power=[], power_log_1=POWER_HAPPY, guardian_log=GUARDIAN_LOG,
    current=[], launcher=[])

# 14. Wi-Fi evidence only in logs/wifi.log; Collect does not copy that file.
CASES_DEF["wifi-only"] = base_files(current=[], wifi_log=WIFI_LOG, power=[],
                                     launcher=[])

# 15. -KoboConf override: config lives at a custom location.
CASES_DEF["koboconf-override"] = base_files(conf=[])

# 16. Device absent: deliberately NOT built (path must not exist).
ABSENT_CASE = "device-absent"


def write_text(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "w", encoding="ascii", newline="\n") as handle:
        if lines:
            handle.write("\n".join(lines) + "\n")


def build():
    if CASES.exists():
        import shutil
        shutil.rmtree(str(CASES))
    for name, files in CASES_DEF.items():
        for rel, lines in files.items():
            write_text(CASES / name / rel, lines)
        # Guarantee the standard directory skeleton even for empty cases.
        for d in ("logs", "userdata", "state"):
            (CASES / name / app_rel(d)).mkdir(parents=True, exist_ok=True)
    # Custom KoboConf for the override case.
    write_text(CASES / "koboconf-override" / "custom" / "Kobo eReader.conf",
               KOBO_CONF_HAPPY)
    print("Built %d fixture cases (+ '%s' intentionally absent) under %s"
          % (len(CASES_DEF), ABSENT_CASE, CASES))


if __name__ == "__main__":
    build()
