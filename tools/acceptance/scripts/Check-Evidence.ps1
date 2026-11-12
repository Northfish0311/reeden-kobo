# =====================================================================
# Check-Evidence.ps1
# Reeden-Kobo v0.7.9-community.4 acceptance - three-state evidence checker
# Target: Windows PowerShell 5.1. This file is 100% ASCII by design.
#
# STATES: PASS / FAIL / NEED-EVIDENCE
#   Insufficient evidence is NEVER reported as FAIL. Only explicit
#   counter-evidence (mem returned=1, no first frame in 20s, brightness
#   update failed, display submission failed) produces FAIL.
#   Manual-only items (3.3, 5.4, 6.2) always report NEED-EVIDENCE.
#
# Device log timestamps are UTC, 8 hours behind China time (UTC+8).
# READ-ONLY: reads the local evidence dir, or the device when -AppDir is
# supplied. It never modifies the device or the evidence files.
#
# Check IDs match the numbered items in the acceptance checklist and the
# static review report (both are Markdown documents written in Chinese).
# EXIT CODES: 0 = all PASS, 1 = NEED-EVIDENCE only, 2 = any FAIL,
#             3 = no evidence source found
# =====================================================================
[CmdletBinding()]
param(
    [string]$EvidenceDir = '',
    [string]$AppDir      = ''
)

$ErrorActionPreference = 'Stop'
$PackageRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
    $EvidenceDir = Join-Path $PackageRoot 'evidence'
}

function Write-Info([string]$Text) { Write-Host $Text }
function Write-Rule([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 78)
    Write-Host $Title
    Write-Host ('=' * 78)
}

# ---------- 1. Build the evidence source map ----------
$useAppDir = -not [string]::IsNullOrWhiteSpace($AppDir)
$map = @{}
$sourceRoot = $EvidenceDir

if ($useAppDir) {
    if (-not (Test-Path -LiteralPath $AppDir -PathType Container)) {
        Write-Rule 'NO EVIDENCE SOURCE'
        Write-Info ('  AppDir not found: ' + $AppDir)
        Write-Info '  The Kobo USB volume is not mounted, or the fixture path is wrong.'
        Write-Info '  This is NOT a device failure. Run Collect-Evidence.ps1 after plugging in.'
        exit 3
    }
    $base      = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\', '/')
    $mountRoot = Split-Path -Parent (Split-Path -Parent $base)
    $map['launcher.log']             = Join-Path $base 'logs\launcher.log'
    $map['current.log']              = Join-Path $base 'logs\current.log'
    $map['previous.log']             = Join-Path $base 'logs\previous.log'
    $map['power.log']                = Join-Path $base 'logs\power.log'
    $map['install-verification.log'] = Join-Path $base 'install-verification.log'
    $map['frontlight.txt']           = Join-Path $mountRoot '.kobo\Kobo\Kobo eReader.conf'
    $sourceRoot = $base
} else {
    $base = [System.IO.Path]::GetFullPath($EvidenceDir).TrimEnd('\', '/')
    $map['launcher.log']             = Join-Path $base 'launcher.log'
    $map['current.log']              = Join-Path $base 'current.log'
    $map['previous.log']             = Join-Path $base 'previous.log'
    $map['power.log']                = Join-Path $base 'power.log'
    $map['install-verification.log'] = Join-Path $base 'install-verification.log'
    $map['frontlight.txt']           = Join-Path $base 'frontlight.txt'
    $sourceRoot = $base
}

function Get-Lines([string]$Key) {
    if (-not $script:map.ContainsKey($Key)) { return @() }
    $path = $script:map[$Key]
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return @() }
    try {
        return @([System.IO.File]::ReadAllLines($path))
    } catch {
        return @()
    }
}

# Both modes must expose the SAME lines: only FrontLight* inside [PowerOptions].
# Filtering responsibility is split by source:
# - -AppDir reads the RAW Kobo eReader.conf (INI with [Section] headers), so
#   Check filters it here with Get-FrontLightSection.
# - -EvidenceDir reads Collect's frontlight.txt, ALREADY section-filtered on
#   the Collect side into a flat list with no [Section] headers; read directly.
# Re-filtering that flat file here would drop every line (empty front group).
function Get-FrontLightSection([string]$Path) {
    $list = New-Object System.Collections.Generic.List[string]
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $list.ToArray() }
    $section = ''
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        $trimmed = $line.Trim()
        if ($trimmed.StartsWith('[') -and $trimmed.EndsWith(']')) {
            $section = $trimmed
            continue
        }
        if ($section -eq '[PowerOptions]' -and $trimmed -match '^FrontLight(Level|State)\s*=') {
            $list.Add($line)
        }
    }
    return $list.ToArray()
}

$anySource = $false
foreach ($k in $map.Keys) {
    if (Test-Path -LiteralPath $map[$k] -PathType Leaf) { $anySource = $true }
}
if (-not $anySource) {
    Write-Rule 'NO EVIDENCE SOURCE FOUND'
    Write-Info ('  Looked in: ' + $sourceRoot)
    Write-Info '  Run Collect-Evidence.ps1 first, or pass -AppDir / -EvidenceDir.'
    Write-Info '  This is NOT a device failure; it only means no logs were collected yet.'
    exit 3
}

# ---------- 2. Match helpers ----------
function Find-Matches([string[]]$Lines, [string[]]$Patterns, [string]$Label) {
    $out = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Patterns -or $Patterns.Count -eq 0) { return $out.ToArray() }
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        $line = $Lines[$i]
        foreach ($pat in $Patterns) {
            if ([string]::IsNullOrEmpty($pat)) { continue }
            if ($line -match $pat) {
                $out.Add(($Label + ':L' + ($i + 1) + ': ' + $line))
                break
            }
        }
    }
    return $out.ToArray()
}

function Invoke-Check {
    param(
        [string]$Id,
        [string]$Name,
        $Groups,
        [string[]]$NegPatterns      = @(),
        [string[]]$PosPatterns      = @(),
        [string[]]$FallbackPatterns = @(),
        [bool]$RequireAll           = $false,
        [bool]$Manual               = $false,
        [string]$Hint               = ''
    )
    $negEv = @()
    $posEv = @()
    $fbEv  = @()
    $hit   = @()
    for ($p = 0; $p -lt $PosPatterns.Count; $p++) { $hit += $false }

    foreach ($g in $Groups) {
        $lines = @($g.Lines)
        $label = $g.Label
        $negEv += @(Find-Matches $lines $NegPatterns $label)
        $fbEv  += @(Find-Matches $lines $FallbackPatterns $label)
        for ($p = 0; $p -lt $PosPatterns.Count; $p++) {
            $m = @(Find-Matches $lines @($PosPatterns[$p]) $label)
            if ($m.Count -gt 0) {
                $hit[$p] = $true
                $posEv += $m
            }
        }
    }

    $allHit = ($PosPatterns.Count -gt 0)
    foreach ($h in $hit) { if (-not $h) { $allHit = $false } }
    $pass = $false
    if ($RequireAll) { $pass = $allHit } else { $pass = ($posEv.Count -gt 0) }

    $status = 'NEED-EVIDENCE'
    $detail = 'No matching log lines found.'
    $ev     = @()
    if ($Manual) {
        $status = 'NEED-EVIDENCE'
        $detail = 'MANUAL item: requires on-device observation; never auto-judged.'
        if ($negEv.Count -gt 0) { $ev = $negEv }
        elseif ($fbEv.Count -gt 0) { $ev = $fbEv }
        elseif ($posEv.Count -gt 0) { $ev = $posEv }
    } elseif ($negEv.Count -gt 0) {
        $status = 'FAIL'
        $detail = 'Explicit failure marker found.'
        $ev = $negEv
    } elseif ($pass) {
        $status = 'PASS'
        if ($RequireAll) { $detail = 'All required log markers found.' }
        else { $detail = 'Required log marker(s) found.' }
        $ev = $posEv
    } elseif ($fbEv.Count -gt 0) {
        $status = 'NEED-EVIDENCE'
        $detail = 'Only guard / supporting lines found; required confirmation is missing (not a failure).'
        $ev = $fbEv
    } elseif ($posEv.Count -gt 0) {
        $status = 'NEED-EVIDENCE'
        $detail = 'Only partial markers found; the required sequence is incomplete.'
        $ev = $posEv
    }

    return [pscustomobject]@{
        Id       = $Id
        Name     = $Name
        Status   = $status
        Detail   = $detail
        Evidence = @($ev)
        Hint     = $Hint
    }
}

function Show-Check($r) {
    Write-Host ''
    Write-Host ('[' + $r.Id + '] ' + $r.Status.PadRight(14) + ' ' + $r.Name)
    Write-Host ('       detail  : ' + $r.Detail)
    $n = [Math]::Min(3, $r.Evidence.Count)
    for ($i = 0; $i -lt $n; $i++) {
        Write-Host ('       evidence: ' + $r.Evidence[$i])
    }
    if ($r.Evidence.Count -eq 0) { Write-Host '       evidence: (none)' }
    if (-not [string]::IsNullOrWhiteSpace($r.Hint)) {
        Write-Host ('       hint    : ' + $r.Hint)
    }
}

# ---------- 3. Log groups ----------
$grpLauncher = [pscustomobject]@{ Label = 'launcher.log'; Lines = @(Get-Lines 'launcher.log') }
$grpCurrent  = [pscustomobject]@{ Label = 'current.log';  Lines = @(Get-Lines 'current.log') }
$grpPrevious = [pscustomobject]@{ Label = 'previous.log'; Lines = @(Get-Lines 'previous.log') }
$grpPower    = [pscustomobject]@{ Label = 'power.log';    Lines = @(Get-Lines 'power.log') }
# -AppDir reads raw Kobo eReader.conf -> filter to [PowerOptions] here.
# -EvidenceDir reads Collect's frontlight.txt -> already section-filtered.
if ($useAppDir) {
    $frontEvidence = @(Get-FrontLightSection $map['frontlight.txt'])
} else {
    $frontEvidence = @(Get-Lines 'frontlight.txt')
}
$grpFront = [pscustomobject]@{ Label = 'frontlight'; Lines = $frontEvidence }

$groupsByKey = @{
    launcher = $grpLauncher
    current  = $grpCurrent
    previous = $grpPrevious
    power    = $grpPower
    front    = $grpFront
}

# ---------- 4. Check definitions (IDs == checklist numbers) ----------
$checkDefs = @(
    @{ Id = '1.1'; Name = 'Cover sensor recognized / enabled'; Groups = @('current', 'previous');
       Pos = @('\[cover\] candidate event[0-9]+ (SW_LID|internal KEY_F1)', '\[cover\] disabled by user preference');
       Neg = @(); Fallback = @('\[cover\] no supported internal lid input'); RequireAll = $false;
       Hint = 'disabled by user preference means userdata/no-sleep-cover exists; 1.2-1.5 not applicable.' },

    @{ Id = '1.2'; Name = 'Cover close edge recorded'; Groups = @('current', 'previous');
       Pos = @('\[cover\] closed', '\[power\] phase=cover-closed wall=');
       Neg = @(); Fallback = @(); RequireAll = $false;
       Hint = 'Cover edges live in current.log / previous.log, not in power.log.' },

    @{ Id = '1.3'; Name = 'Screen locked, front light off, engine retained'; Groups = @('current', 'previous');
       Pos = @('\[power\] screen locked; engine retained', '\[power\] phase=locking wall=');
       Neg = @(); Fallback = @('\[power\] phase=starting-helper wall='); RequireAll = $false;
       Hint = 'set_sleep(true) waits 1.4s before writing backlight 0.' },

    @{ Id = '1.4'; Name = 'Kernel suspend request and return'; Groups = @('power');
       Pos = @('\[power\] invoked arg=suspend', '\[power\] entering mem ', '\[power\] mem returned=0(\s|$)');
       Neg = @('\[power\] mem returned=[1-9][0-9]*(\s|$)');
       Fallback = @('\[power\] screen-only: supply guard', '\[power\] display did not become idle',
                    '\[power\] existing alarm: suspend cancelled', '\[power\] Wi-Fi could not be suspended',
                    '\[power\] short mem return after', '\[power\] helper exiting=[1-9]');
       RequireAll = $true;
       Hint = 'Fallback lines are designed guards (charging / busy display / cancel), NOT failures.' },

    @{ Id = '1.5'; Name = 'Cover open restores reader'; Groups = @('current', 'previous');
       Pos = @('\[cover\] opened', '\[power\] phase=cover-opened wall=', '\[power\] resumed same engine and book');
       Neg = @(); Fallback = @('\[power\] wake requested'); RequireAll = $false;
       Hint = 'Open edge uses wall=<UTC epoch>; add 8 hours for China time.' },

    @{ Id = '2.1'; Name = 'Power key short press locks and calls power.sh suspend'; Groups = @('power', 'current', 'previous');
       Pos = @('\[power\] key release', '\[power\] invoked arg=suspend');
       Neg = @(); Fallback = @('\[power\] exclusive power key acquired'); RequireAll = $true;
       Hint = 'Only invoked arg=suspend counts; =restore and =native are other calls.' },

    @{ Id = '2.2'; Name = 'Power key second press wakes reader'; Groups = @('current', 'power');
       Pos = @('\[power\] wake requested', '\[power\] resumed same engine and book', '\[power\] mem returned=0(\s|$)');
       Neg = @(); Fallback = @('\[power\] screen stays locked; no more retries'); RequireAll = $false;
       Hint = 'One guarded 8s retry is allowed per lock; user wake has priority.' },

    @{ Id = '3.1'; Name = 'armPageTurn request reached adapter'; Groups = @('current', 'previous');
       Pos = @('\[page-turn\] arm .*accepted=1(\s|$)'); Neg = @();
       Fallback = @('\[page-turn\] arm .*accepted=0'); RequireAll = $false;
       Hint = 'No arm line = Reeden settings combination issue, not an adapter defect (see 3.3).' },

    @{ Id = '3.2'; Name = 'Water-ripple animation actually submitted'; Groups = @('current', 'previous');
       Pos = @('\[page-turn\] bands=', '\[page-turn\] submissions=', '\[color-turn\] bands=[2-8] .*path=cfa wave=11 mode=1');
       Neg = @('\[display-sequence\] (cancelled|submission failed)', '\[color-turn\] incomplete;');
       Fallback = @('\[page-turn\] invalid experiment configuration; stable profile retained');
       RequireAll = $false;
       Hint = 'accepted=1 alone is NOT proof of animation. Colour needs the opt-in .5 color profile; off and cleans skip sweeps. Logs do not prove optical quality.' },

    @{ Id = '3.3'; Name = 'Ripple settings combination (manual)'; Groups = @();
       Pos = @(); Neg = @(); Fallback = @(); RequireAll = $false; Manual = $true;
       Hint = 'MANUAL: confirm page-turn animation=NONE, water-ripple=ON, and armPageTurn was emitted.' },

    @{ Id = '4.1'; Name = 'First frame timing in launcher.log'; Groups = @('launcher');
       Pos = @('\[launcher\] first frame took [0-9]+s');
       Neg = @('\[launcher\] no first frame in 20s; Nickel was never paused');
       Fallback = @('\[verify\] manifest unchanged and every file present; skipped full hashing');
       RequireAll = $false;
       Hint = 'A full weekly SHA-256 pass is slower than a cached verify; compare with a stopwatch.' },

    @{ Id = '4.2'; Name = 'Native FrontLightLevel handoff'; Groups = @('front', 'launcher');
       Pos = @('^\s*FrontLightLevel\s*=', '\[recovery\] Nickel brightness updated to [0-9]+');
       Neg = @('\[recovery\] Nickel brightness update failed; hardware value kept');
       Fallback = @('\[recovery\] restoring this session'); RequireAll = $true;
       Hint = 'Perceptual vs hardware scale differ; judge by on-screen look, not the number.' },

    # NOTE: the entry line is deliberately NOT a pass criterion. power.sh:7 prints
    # "[power] invoked arg=suspend" unconditionally on entry, and power.sh:89
    # (on_battery prepare) prints screen-only: supply guard then exits 3 on USB
    # power / charging, so the device only locks the screen and never reaches the
    # kernel. Because reading power.log requires USB, an entry-line gate is a
    # guaranteed false positive. Deep sleep needs real mem evidence.
    @{ Id = '4.3'; Name = 'Deep sleep reached kernel mem (four-fold; tools/Check-SuspendGate.ps1)'; Groups = @('power');
       Pos = @('\[power\] entering mem ', '\[power\] mem returned=0(\s|$)');
       Neg = @('\[power\] mem returned=[1-9][0-9]*(\s|$)', '\[power\] short mem return after');
       Fallback = @('\[power\] screen-only: supply guard', '\[power\] display did not become idle',
                    '\[power\] existing alarm: suspend cancelled', '\[power\] Wi-Fi could not be suspended',
                    '\[power\] invoked arg=suspend');
       RequireAll = $true;
       Hint = 'Entry line is NOT a pass criterion (power.sh:7 prints it unconditionally; charging exits 3 after screen-only). USB-attached sessions are NOT_APPLICABLE. Full gate incl. suspended->resuming span >5s: tools/Check-SuspendGate.ps1.' },

    @{ Id = '5.1'; Name = 'Control panel opened and Wi-Fi probed'; Groups = @('current', 'previous');
       Pos = @('\[wifi\] panel helper finished action=1 '); Neg = @(); Fallback = @(); RequireAll = $false;
       Hint = 'action 1 = PANEL_PROBE; wifi.sh probe returns 10/11/12 for OFF/ON/CONNECTED.' },

    @{ Id = '5.2'; Name = 'Wi-Fi real toggle executed'; Groups = @('current', 'previous');
       Pos = @('\[wifi\] panel helper finished action=[23] result=0(\s|$)');
       Neg = @('\[wifi\] panel helper finished action=[23] result=[1-9][0-9]*(\s|$)');
       Fallback = @(); RequireAll = $false;
       Hint = 'result=0 proves the command ran; real radio/AP state still needs manual confirmation.' },

    @{ Id = '5.3'; Name = 'Panel Lock Now triggers suspend path'; Groups = @('current', 'previous', 'power');
       Pos = @('\[power\] screen locked; engine retained', '\[power\] invoked arg=suspend');
       Neg = @(); Fallback = @(); RequireAll = $true;
       Hint = 'PANEL_LOCK calls set_sleep(true), the same path as power key / cover.' },

    @{ Id = '5.4'; Name = 'Return to reading restores latest page (manual)'; Groups = @();
       Pos = @(); Neg = @(); Fallback = @(); RequireAll = $false; Manual = $true;
       Hint = 'MANUAL: closing the panel emits no action/log; confirm no stale screenshot is pasted back.' },

    @{ Id = '6.1'; Name = 'Overnight suspend phase chain recorded'; Groups = @('power');
       Pos = @('\[power\] phase=preparing uptime=', '\[power\] phase=suspended uptime=',
               '\[power\] entering mem ', '\[power\] phase=resuming uptime=',
               '\[power\] mem returned=0(\s|$)');
       Neg = @('\[power\] mem returned=[1-9][0-9]*(\s|$)');
       Fallback = @('\[power\] screen-only: supply guard', '\[power\] helper exiting=[1-9]');
       RequireAll = $true;
       Hint = 'A successful mem return or a multi-hour gap is NOT proof of true low power.' },

    @{ Id = '6.2'; Name = 'Overnight battery readings (manual)'; Groups = @('power');
       Pos = @(); Neg = @();
       Fallback = @('\[power\] sample=(before_mem|after_mem) battery=.*capacity=');
       RequireAll = $false; Manual = $true;
       Hint = 'MANUAL: read battery percent on the device before/after; these sample lines are script readings only.' }
)

# ---------- 5. Run ----------
Write-Rule 'Reeden-Kobo community.4 / community.5 - three-state evidence checker'
Write-Info ('  Source : ' + $sourceRoot)
Write-Info '  States : PASS / FAIL / NEED-EVIDENCE. Insufficient evidence is never FAIL.'
Write-Info '  Time   : device log timestamps are UTC, 8 hours behind China time (UTC+8).'
Write-Info '  Access : read-only. The device and the evidence files are never modified.'

$results = @()
foreach ($d in $checkDefs) {
    $gs = @()
    foreach ($key in $d.Groups) { $gs += $groupsByKey[$key] }
    $results += Invoke-Check -Id $d.Id -Name $d.Name -Groups $gs -PosPatterns $d.Pos -NegPatterns $d.Neg -FallbackPatterns $d.Fallback -RequireAll $d.RequireAll -Manual ([bool]$d.Manual) -Hint $d.Hint
}

foreach ($r in $results) { Show-Check $r }

$passCount = @($results | Where-Object { $_.Status -eq 'PASS' }).Count
$failCount = @($results | Where-Object { $_.Status -eq 'FAIL' }).Count
$needCount = @($results | Where-Object { $_.Status -eq 'NEED-EVIDENCE' }).Count

Write-Rule 'SUMMARY'
Write-Info ('  PASS=' + $passCount + '  FAIL=' + $failCount + '  NEED-EVIDENCE=' + $needCount + '  TOTAL=' + $results.Count)
Write-Info '  NEED-EVIDENCE means evidence is insufficient; it is never a FAIL.'
Write-Info '  Manual-only items 3.3, 5.4, 6.2 always report NEED-EVIDENCE by design.'
Write-Info '  Device log timestamps are UTC (8 hours behind UTC+8).'
$code = 0
if ($failCount -gt 0) { $code = 2 }
elseif ($needCount -gt 0) { $code = 1 }
Write-Info ('  Exit code: ' + $code)
exit $code
