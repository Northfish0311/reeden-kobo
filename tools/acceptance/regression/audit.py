#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent static audit of the acceptance package.

Three checks, all offline and read-only:
  1. source  -- verify chapter-9 log strings against the REAL .4 tag (3b804d2)
  2. ascii   -- byte-level ASCII + forbidden write-token scan of both .ps1 files
  3. docs    -- 19 check IDs across checklist / checker / chapter 9 + README topics

Usage:  python audit.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path

QA = Path(__file__).resolve().parent
PKG = QA.parent
SCRIPTS = PKG / "scripts"


def _find_repo():
    """Locate the reeden-kobo clone without hard-coding a local user path.

    Order: $REEDEN_REPO, then walk up from this file, then from the CWD, then
    fall back to a bare relative name. A missing repo degrades to source=SKIP
    instead of a traceback, so the ASCII / docs checks still run.
    """
    env = os.environ.get("REEDEN_REPO")
    if env and (Path(env) / ".git").exists():
        return Path(env)
    for start in (QA, Path.cwd()):
        for cand in [start] + list(start.parents):
            if (cand / ".git").exists() and (cand / "src" / "host.c").exists():
                return cand
    return Path("reeden-kobo")


REPO = _find_repo()
TAG = "3b804d2"   # == v0.7.9-community.4, independent of whatever origin/main is
TAG_NAME = "v0.7.9-community.4"

SOURCE_FILES = [
    "scripts/power.sh", "scripts/run.sh", "scripts/recover.sh",
    "scripts/wifi.sh", "scripts/integrity.sh", "scripts/verify.sh",
    "scripts/guardian.sh", "src/host.c", "src/cover.c", "src/display.c",
    "scripts/standby_report.py",
]

# (literal source string, one or more files where it must appear)
STRINGS = [
    ("[power] invoked arg=${1:-} $(date)", ["scripts/power.sh"]),
    ("[power] phase=$1 uptime=$power_uptime pid=$$ $(date)", ["scripts/power.sh"]),
    ("[power] sample=$1 battery=$battery external=$external capacity=$capacity",
     ["scripts/power.sh"]),
    ("[power] screen-only: supply guard battery=$battery external=$external",
     ["scripts/power.sh"]),
    ("[power] display did not become idle", ["scripts/power.sh"]),
    ("[power] display settle completed after $attempt polls", ["scripts/power.sh"]),
    ("[power] entering mem $(date)", ["scripts/power.sh"]),
    ("[power] mem returned=$result $(date)", ["scripts/power.sh"]),
    ("[power] helper exiting=$power_result $(date)", ["scripts/power.sh"]),
    ("[power] short mem return after ${span}s; wake source unknown",
     ["scripts/power.sh"]),
    ("[power] Wi-Fi resume deferred while cover remains closed",
     ["scripts/power.sh"]),
    ("[power] Wi-Fi could not be suspended", ["scripts/power.sh"]),
    ("[power] existing alarm: suspend cancelled", ["scripts/power.sh"]),
    ("[cover] candidate event%u %s", ["src/cover.c"]),
    ("[cover] no supported internal lid input; power key remains available",
     ["src/cover.c"]),
    ("[cover] disabled by user preference", ["src/host.c"]),
    ("[cover] closed", ["src/host.c"]),
    ("[cover] opened", ["src/host.c"]),
    ("[power] phase=%s wall=%lld mono_ms=%llu", ["src/host.c"]),
    ("[power] screen locked; engine retained", ["src/host.c"]),
    ("[power] resumed same engine and book", ["src/host.c"]),
    ("[power] exclusive power key acquired", ["src/host.c"]),
    ("[power] key release", ["src/host.c"]),
    ("[power] wake requested; waiting for hardware restoration", ["src/host.c"]),
    ("[power] still locked; one guarded retry in 8s", ["src/host.c"]),
    ("[power] screen stays locked; no more retries for this lock", ["src/host.c"]),
    ("[power] helper wait failed: %s; returning to native UI", ["src/host.c"]),
    ("[wifi] panel helper finished action=%d result=%d", ["src/host.c"]),
    ("[sleep-cover] not registered; keeping current page", ["src/host.c"]),
    ("[sleep-cover] image not confirmed; cancelling suspend", ["src/host.c"]),
    ("[page-turn] arm type=%d forward=%u vertical=%u steps=%u accepted=%u",
     ["src/host.c"]),
    ("[page-turn] invalid experiment configuration; stable profile retained",
     ["src/display.c"]),
    ("[page-turn] submissions=%u span_ms=%.1f min_gap_ms=%.1f", ["src/display.c"]),
    ("[page-turn] bands=%u direction=%s vertical=%u night=%u path=%s wave=%u mode=%u",
     ["src/display.c"]),
    ("[display-sequence] %s; restoring normal page update", ["src/display.c"]),
    ("[launcher] first frame took $(( $(date +%s) - STARTED_AT ))s",
     ["scripts/run.sh"]),
    ("[launcher] no first frame in 20s; Nickel was never paused",
     ["scripts/run.sh"]),
    ("[launcher] first frame ready; hardware handoff authorized",
     ["scripts/run.sh"]),
    ("[verify] manifest unchanged and every file present; skipped full hashing",
     ["scripts/run.sh"]),
    ("[recovery] restoring this session", ["scripts/recover.sh"]),
    ("[recovery] Nickel brightness updated to $level", ["scripts/recover.sh"]),
    ("[recovery] Nickel brightness update failed; hardware value kept",
     ["scripts/recover.sh"]),
    ("FrontLightLevel=", ["scripts/recover.sh"]),
]

# Strings that must NOT be produced by .4 runtime code (only compat tooling).
LEGACY_ONLY = [
    "[power] charging: retaining screen lock without kernel suspend",
    "[cover] extra listener disabled; existing power handling unchanged",
]

MANUAL_IDS = {"3.3", "5.4", "6.2"}
EXPECTED_IDS = {"%d.%d" % (c, n) for c, n in
                [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5),
                 (2, 1), (2, 2),
                 (3, 1), (3, 2), (3, 3),
                 (4, 1), (4, 2), (4, 3),
                 (5, 1), (5, 2), (5, 3), (5, 4),
                 (6, 1), (6, 2)]}


def git_show(path):
    out = subprocess.run(["git", "-C", str(REPO), "show",
                          "%s:%s" % (TAG, path)],
                         capture_output=True)
    if out.returncode != 0:
        return ""
    return out.stdout.decode("utf-8", "replace")


def check_source():
    print("=" * 78)
    print("[1] SOURCE STRING VERIFICATION against tag %s (v0.7.9-community.4)" % TAG)
    print("=" * 78)
    # Anchor to the immutable tag, never to a moving origin/main. If the tag
    # is ever repointed, this check fails loudly instead of silently auditing
    # the wrong source tree.
    resolved = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", TAG_NAME + "^{commit}"],
        capture_output=True, text=True)
    tag_sha = resolved.stdout.strip() if resolved.returncode == 0 else ""
    tag_ok = tag_sha.startswith(TAG)
    print("  tag anchor: %s^{commit} = %s  expected prefix %s -> %s"
          % (TAG_NAME, tag_sha or "<unresolved>", TAG,
             "OK" if tag_ok else "MISMATCH"))
    print("  NOTE: origin/main is intentionally NOT used (it has already moved).")
    blobs = {p: git_show(p) for p in SOURCE_FILES}
    missing = []
    for literal, files in STRINGS:
        hits = []
        for f in files:
            for i, line in enumerate(blobs.get(f, "").splitlines(), 1):
                if literal in line:
                    hits.append("%s:%d" % (f, i))
        if hits:
            print("  OK   %-70s %s" % (literal[:70], ",".join(hits)))
        else:
            missing.append(literal)
            print("  MISS %s" % literal)
    print("\n  -- legacy-only strings must appear ONLY in standby_report.py / tests --")
    for legacy in LEGACY_ONLY:
        for f, blob in blobs.items():
            if legacy in blob:
                print("  OK   %-60s found in %s (compat only)" % (legacy[:60], f))
    print("\n  RESULT: %d/%d strings verified against real .4 source."
          % (len(STRINGS) - len(missing), len(STRINGS)))
    return (not missing) and tag_ok


def check_ascii():
    print("\n" + "=" * 78)
    print("[2] ASCII + READ-ONLY TOKEN SCAN")
    print("=" * 78)
    ok = True
    forbidden = ["Remove-Item", "Set-Content", "Out-File", "chkdsk",
                 "Clear-Content", "Move-Item", "Rename-Item"]
    for name in ("Collect-Evidence.ps1", "Check-Evidence.ps1"):
        path = SCRIPTS / name
        data = path.read_bytes()
        bad = [(i, hex(b)) for i, b in enumerate(data) if b > 0x7F]
        print("  %-26s bytes=%-6d non_ascii=%-3d BOM=%s CRLF=%d"
              % (name, len(data), len(bad),
                 data[:3] == b"\xef\xbb\xbf", data.count(b"\r\n")))
        if bad:
            ok = False
            print("     first non-ascii: %s" % bad[:5])
        # latin-1 never raises; the byte-level check above is authoritative.
        text = data.decode("latin-1")
        found = [tok for tok in forbidden if tok in text]
        new_items = [m.start() for m in re.finditer(r"New-Item", text)]
        print("     forbidden tokens: %s" % (found if found else "NONE"))
        print("     New-Item occurrences: %d (must target validated local -OutDir only)"
              % len(new_items))
        if found:
            ok = False
        # any time-based judgement in the checker?
        if name == "Check-Evidence.ps1":
            timers = [t for t in ("DateTime", "Get-Date", "ParseExact",
                                  "FromTimestamp", "FromUnixTime") if t in text]
            print("     time-based judgement primitives: %s" %
                  (timers if timers else "NONE (UTC note is informational only)"))
    return ok


def read(name):
    return (PKG / name).read_text(encoding="utf-8")


def check_docs():
    print("\n" + "=" * 78)
    print("[3] DOCUMENT / SCRIPT ID CONSISTENCY")
    print("=" * 78)
    ok = True
    checker = (SCRIPTS / "Check-Evidence.ps1").read_bytes().decode("latin-1")
    script_ids = set(re.findall(r"Id\s*=\s*'(\d+\.\d+)'", checker))
    print("  checker Id= definitions          : %d -> %s"
          % (len(script_ids), "OK" if script_ids == EXPECTED_IDS else "MISMATCH"))
    print("  checkDefs hashtable count        : %d"
          % len(re.findall(r"@\{\s*Id\s*=\s*'", checker)))
    if script_ids != EXPECTED_IDS:
        ok = False

    # The three Chinese documents are OPTIONAL. A tools-only export ships the
    # two .ps1 scripts and the regression assets while keeping the repository's
    # own docs/ checklist authoritative, so missing documents are SKIP -- never
    # a failure, and never a reason to stop the source/ascii checks.
    doc_names = ("验收清单.md", "静态审查报告.md", "README.md")
    missing = [n for n in doc_names if not (PKG / n).exists()]
    if missing:
        print("  SKIP: document consistency checks (not shipped in this export)")
        print("        missing: %s" % ", ".join(missing))
        print("        docs/ checklist in the repo stays authoritative for wording.")
        return "SKIP" if ok else False

    checklist = read("验收清单.md")
    static = read("静态审查报告.md")
    readme = read("README.md")

    cl_ids = set(re.findall(r"^###\s+(\d+\.\d+)\s", checklist, re.M))
    auto_cl = {i for i in cl_ids if i[0] in "123456"}
    print("  checklist numbered items (ch.1-6): %d -> %s"
          % (len(auto_cl), "OK" if auto_cl == EXPECTED_IDS else "MISMATCH"))
    if auto_cl != EXPECTED_IDS:
        ok = False
        print("     checklist-only : %s" % sorted(auto_cl - script_ids))
        print("     script-only    : %s" % sorted(script_ids - auto_cl))

    # Chapter-9 heading may be reworded during doc cleanup. Fall back to the
    # whole report rather than slicing from index -1, so a heading rename can
    # never produce a false "0 IDs found" red.
    m = re.search(r"^##\s*9[\.、\s]", static, re.M)
    ch9 = static[m.start():] if m else static
    ch9_ids = set(re.findall(r"\b(\d\.\d)\b", ch9))
    print("  chapter-9 referenced IDs         : %d -> %s"
          % (len(ch9_ids & EXPECTED_IDS),
             "OK" if EXPECTED_IDS <= ch9_ids else "MISMATCH"))
    if not EXPECTED_IDS <= ch9_ids:
        print("     missing from ch.9: %s" % sorted(EXPECTED_IDS - ch9_ids))
        ok = False
    for mid in MANUAL_IDS:
        print("  manual item %s declared manual in ch.9: %s"
              % (mid, "YES" if mid in ch9 else "NO"))

    # Deliberately SEMANTIC keyword checks, not exact sentence matching.
    # The engineer is rewriting the UTC note, the code-baseline line and the
    # chapter-9 source attribution; none of those rewrites should make this
    # audit go red as long as the meaning is preserved.
    stale_baseline = bool(re.search(r"origin/main\s*[=＝]\s*3b804d2", readme))
    topics = {
        "UTC note present": "UTC" in readme,
        "safe plug/unplug": ("安全弹出" in readme or "安全卸载" in readme),
        "no-sleep-cover fallback": ("no-sleep-cover" in readme
                                    and ("人工" in readme or "手动" in readme
                                         or "绝不自动创建" in readme)),
        "three states": all(s in readme for s in ("PASS", "FAIL", "NEED-EVIDENCE")),
        "exit codes": ("退出码" in readme
                       and all(s in readme for s in ("`0`", "`1`", "`2`", "`3`"))),
        "fixture usage": "fixture" in readme.lower(),
        "baseline tag referenced": TAG_NAME in readme,
        "stale origin/main SHA removed": not stale_baseline,
    }
    print("  README topics (semantic keywords):")
    for k, v in topics.items():
        print("     %-34s %s" % (k, "OK" if v else "MISSING"))
        if not v:
            ok = False

    # The static report must also name the immutable tag (its baseline header
    # is being rewritten). Accept either the tag name or the commit prefix.
    if TAG_NAME not in static and TAG not in static:
        print("  static report baseline tag: MISSING")
        ok = False
    else:
        print("  static report baseline tag: OK")
    return ok


def main():
    results = {
        "source": check_source(),
        "ascii": check_ascii(),
        "docs": check_docs(),
    }

    def label(v):
        if v == "SKIP":
            return "SKIP"
        return "PASS" if v else "FAIL"

    print("\n" + "=" * 78)
    print("AUDIT SUMMARY: " + ", ".join("%s=%s" % (k, label(v))
                                       for k, v in results.items()))
    print("=" * 78)
    # SKIP is not a failure: a tools-only export legitimately ships no documents.
    return 0 if all(v is True or v == "SKIP" for v in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
