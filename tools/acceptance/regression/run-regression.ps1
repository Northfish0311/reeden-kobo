# =====================================================================
# run-regression.ps1  --  QA offline regression driver
# Reeden-Kobo v0.7.9-community.4 acceptance package
#
# Runs Collect-Evidence.ps1 + Check-Evidence.ps1 against every synthetic
# fixture built by build_fixtures.py, then asserts the three-state results
# and exit codes. Pure PowerShell 5.1, 100% ASCII, no device required.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run-regression.ps1
# =====================================================================
[CmdletBinding()]
param(
    [string]$FixturesRoot = $PSScriptRoot,
    [string]$ScriptsDir = '',
    [string]$RunTag = '',
    [switch]$SelfCheckOnly
)

$ErrorActionPreference = 'Continue'
$script:Bad  = New-Object System.Collections.Generic.List[string]
$script:Note = New-Object System.Collections.Generic.List[string]
$psExe = Join-Path $PSHOME 'powershell.exe'

$pkg = Split-Path -Parent $FixturesRoot
$usingPreview = -not [string]::IsNullOrWhiteSpace($ScriptsDir)
# With no -ScriptsDir the driver MUST target the real delivered scripts\ dir,
# never the _patch_preview copy. Only an explicit -ScriptsDir switches source.
if (-not $usingPreview) { $ScriptsDir = Join-Path $pkg 'scripts' }
$suffix = ''
if (-not [string]::IsNullOrWhiteSpace($RunTag)) { $suffix = '-' + $RunTag }
$tagLabel = 'round1'
if (-not [string]::IsNullOrWhiteSpace($RunTag)) { $tagLabel = $RunTag }
$collect = Join-Path $ScriptsDir 'Collect-Evidence.ps1'
$check   = Join-Path $ScriptsDir 'Check-Evidence.ps1'
$cases   = Join-Path $FixturesRoot 'cases'
$outRoot = Join-Path $FixturesRoot 'out'
$resRoot = Join-Path $FixturesRoot 'results'

foreach ($d in @($outRoot, $resRoot)) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Note([string]$s) {
    $script:Note.Add($s)
    Write-Host $s
}
function Assert([bool]$cond, [string]$msg) {
    # Accumulate into $script:Note as well, so regression-report-<tag>.txt is
    # the COMPLETE log (no external Tee-Object / Out-File needed).
    if ($cond) {
        $line = '    [ok] ' + $msg
        $script:Note.Add($line)
        Write-Host $line
    } else {
        $line = '    [FAIL-ASSERT] ' + $msg
        $script:Bad.Add($msg)
        $script:Note.Add($line)
        Write-Host $line
    }
}

function Invoke-Script([string]$File, [string[]]$ArgList) {
    $raw = & $psExe -NoProfile -ExecutionPolicy Bypass -File $File @ArgList 2>$null
    return [pscustomobject]@{ Text = @($raw); Code = $LASTEXITCODE }
}

function Get-Statuses($Text) {
    $st = @{}
    $dups = @()
    $exit = -1
    foreach ($line in $Text) {
        if ($line -match '^\[(\d+\.\d+)\]\s+(PASS|FAIL|NEED-EVIDENCE)\s') {
            $id = $Matches[1]
            if ($st.ContainsKey($id)) { $dups += $id }
            $st[$id] = $Matches[2]
        }
        if ($line -match '^\s*Exit code:\s*(\d+)') { $exit = [int]$Matches[1] }
    }
    return [pscustomobject]@{
        Statuses    = $st
        Duplicates  = $dups
        ExitCode    = $exit
        Text        = $Text
    }
}

$AllIds = @('1.1','1.2','1.3','1.4','1.5',
            '2.1','2.2',
            '3.1','3.2','3.3',
            '4.1','4.2','4.3',
            '5.1','5.2','5.3','5.4',
            '6.1','6.2')
$ManualIds = @('3.3','5.4','6.2')

function Test-Common($p, [string]$name, [hashtable]$spec) {
    Assert ($p.Duplicates.Count -eq 0) ("$name : no duplicate check IDs")
    Assert ($p.Statuses.Count -eq 19) ("$name : exactly 19 IDs (actual $($p.Statuses.Count))")
    $missing = @()
    foreach ($id in $AllIds) { if (-not $p.Statuses.ContainsKey($id)) { $missing += $id } }
    Assert ($missing.Count -eq 0) ("$name : every expected ID present (missing: $($missing -join ','))")
    Assert ($p.ExitCode -eq $spec.Exit) ("$name : exit=$($spec.Exit) (actual $($p.ExitCode))")

    $failIds = @()
    foreach ($id in $AllIds) {
        if ($p.Statuses.ContainsKey($id) -and $p.Statuses[$id] -eq 'FAIL') { $failIds += $id }
    }
    $expFail = @($spec.Fail)
    $same = (($failIds -join ',') -eq ($expFail -join ','))
    Assert $same ("$name : FAIL set = [$($expFail -join ',')] (actual [$($failIds -join ',')])")

    foreach ($id in $ManualIds) {
        if ($p.Statuses.ContainsKey($id)) {
            Assert ($p.Statuses[$id] -eq 'NEED-EVIDENCE') ("$name : manual $id is NEED-EVIDENCE")
        }
    }
    if ($spec.ContainsKey('AllNonManualPass') -and $spec.AllNonManualPass) {
        foreach ($id in $AllIds) {
            if ($ManualIds -notcontains $id) {
                Assert ($p.Statuses[$id] -eq 'PASS') ("$name : $id is PASS (actual $($p.Statuses[$id]))")
            }
        }
    }
    if ($spec.ContainsKey('AllNeed') -and $spec.AllNeed) {
        foreach ($id in $AllIds) {
            Assert ($p.Statuses[$id] -eq 'NEED-EVIDENCE') ("$name : $id is NEED-EVIDENCE (actual $($p.Statuses[$id]))")
        }
    }
    foreach ($key in $spec.Status.Keys) {
        Assert ($p.Statuses.ContainsKey($key) -and $p.Statuses[$key] -eq $spec.Status[$key]) `
            ("$name : $key = $($spec.Status[$key]) (actual $($p.Statuses[$key]))")
    }
}

function Run-Case([string]$name, [hashtable]$spec) {
    Note ''
    Note ('CASE ' + $name)
    $app = Join-Path $cases (Join-Path $name 'device\.adds\reeden-kobo')
    $out = Join-Path $outRoot $name
    # Collect overwrites every output file with -Force, so no bulk cleanup is
    # needed. Avoid Remove-Item -Recurse entirely: it is both unnecessary and
    # trips the environment bulk-delete guard on repeated runs.
    if (-not (Test-Path -LiteralPath $out)) {
        New-Item -ItemType Directory -Path $out -Force | Out-Null
    }

    $c = Invoke-Script $collect @('-AppDir', $app, '-OutDir', $out)
    Assert ($c.Code -eq 0) ("$name : Collect exit 0 (actual $($c.Code))")

    # L3: Collect must retain the extra rotated / wifi / guardian evidence
    # copies. Check's judgement logic is intentionally left unchanged, so the
    # three-state expectations for these cases stay NEED-EVIDENCE.
    if ($spec.ContainsKey('OutFilePatterns')) {
        $names = @(Get-ChildItem -LiteralPath $out -File -ErrorAction SilentlyContinue |
                   ForEach-Object { $_.Name })
        foreach ($pat in $spec.OutFilePatterns) {
            $hit = @($names | Where-Object { $_ -match $pat })
            Assert ($hit.Count -gt 0) ("$name : evidence copy retained matching /$pat/ (out files: " +
                                       ($names -join ',') + ")")
        }
    }

    $r = Invoke-Script $check @('-EvidenceDir', $out)
    $p = Get-Statuses $r.Text
    [System.IO.File]::WriteAllLines((Join-Path $resRoot ($name + $suffix + '-check.txt')), $r.Text)
    [System.IO.File]::WriteAllLines((Join-Path $resRoot ($name + $suffix + '-collect.txt')), $c.Text)
    Assert ($r.Code -eq $p.ExitCode) ("$name : printed exit code matches process exit code")
    Test-Common $p $name $spec
    return $p
}

Note '======================================================================'
Note ('Reeden-Kobo .4 acceptance package - QA offline regression (RunTag=' + $tagLabel + ')')
Note '======================================================================'

# ---------- source resolution self-check ----------
Note ''
Note ('SCRIPTS: ' + $ScriptsDir + '  [usingPreview=' + $usingPreview + ']')
if (-not $usingPreview) {
    Assert ($ScriptsDir -ieq (Join-Path $pkg 'scripts')) 'driver default -ScriptsDir resolves to the REAL delivered scripts\ folder'
    Assert (-not $ScriptsDir.Contains('_patch_preview')) 'driver default does NOT point at _patch_preview'
    Assert (Test-Path -LiteralPath $collect) 'default Collect-Evidence.ps1 exists'
    Assert (Test-Path -LiteralPath $check) 'default Check-Evidence.ps1 exists'
}

# ---------- syntax check (requirement 7) ----------
Note ''
Note 'SYNTAX: Parser::ParseFile on both .ps1'
foreach ($f in @($collect, $check)) {
    $tok = $null; $err = $null
    [System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$tok, [ref]$err) | Out-Null
    Assert ($err.Count -eq 0) ((Split-Path -Leaf $f) + ' : 0 syntax errors (actual ' + $err.Count + ')')
}

# -SelfCheckOnly lets QA prove the driver is self-consistent WITHOUT running
# the suite (useful while the engineer is still editing the delivered scripts).
if ($SelfCheckOnly) {
    Note ''
    Note 'SELF-CHECK ONLY: script source resolution + ParseFile verified; full regression SKIPPED.'
    Note ('  assertions_failed = ' + $script:Bad.Count)
    [System.IO.File]::WriteAllLines(
        (Join-Path $resRoot ('selfcheck' + $suffix + '.txt')), $script:Note.ToArray())
    exit ([int]($script:Bad.Count -gt 0))
}

# ---------- standard cases ----------
$specs = @(
    @{ Name='happy'; Exit=1; Fail=@(); AllNonManualPass=$true; Status=@{} },
    # 4.3 now requires real mem evidence, so mem returned=1 is an explicit failure for it too.
    @{ Name='fail-mem-returned1'; Exit=2; Fail=@('1.4','4.3','6.1'); Status=@{} },
    @{ Name='fail-no-first-frame'; Exit=2; Fail=@('4.1'); Status=@{} },
    @{ Name='fail-brightness'; Exit=2; Fail=@('4.2'); Status=@{} },
    @{ Name='guard-supply-only'; Exit=1; Fail=@();
       Status=@{'1.4'='NEED-EVIDENCE'; '6.1'='NEED-EVIDENCE'; '4.3'='NEED-EVIDENCE'} },
    @{ Name='guard-display-busy'; Exit=1; Fail=@();
       Status=@{'1.4'='NEED-EVIDENCE'; '6.1'='NEED-EVIDENCE'; '4.3'='NEED-EVIDENCE'} },
    # L2 fix: 2.1 / 5.1 / 5.2 / 5.3 gain the 'previous' group, so a log
    # rotation must no longer lose their evidence. Derived from each check's
    # real Pos/Neg rules against this fixture (previous.log == CURRENT_HAPPY,
    # power.log == POWER_HAPPY):
    #   2.1  Pos = key release (previous) + invoked arg=suspend (power), RequireAll -> PASS
    #   5.1  Pos = panel helper finished action=1 (previous)                -> PASS
    #   5.2  Pos = action=2/3 result=0 (previous), Neg result=[1-9] absent  -> PASS
    #   5.3  Pos = screen locked (previous) + invoked arg=suspend (power),
    #        RequireAll                                                     -> PASS
    # Hence all 16 non-manual items are PASS after the fix.
    @{ Name='rotated-previous-only'; Exit=1; Fail=@(); AllNonManualPass=$true;
       Status=@{'2.1'='PASS';'5.1'='PASS';'5.2'='PASS';'5.3'='PASS'} },
    @{ Name='missing-previous'; Exit=1; Fail=@(); AllNonManualPass=$true; Status=@{} },
    @{ Name='empty-logs'; Exit=1; Fail=@(); AllNeed=$true; Status=@{} },
    @{ Name='accepted-only'; Exit=1; Fail=@();
       Status=@{'3.1'='PASS';'3.2'='NEED-EVIDENCE'} },
    @{ Name='frontlight-other-section'; Exit=1; Fail=@();
       Status=@{'4.2'='NEED-EVIDENCE'} },
    # L3 fix: three-state stays NEED-EVIDENCE (Check logic unchanged), but the
    # extra evidence copies must now be present in -OutDir.
    @{ Name='powerlog-rotated'; Exit=1; Fail=@();
       OutFilePatterns=@('power\.log\.1', 'guardian');
       Status=@{'1.4'='NEED-EVIDENCE';'6.1'='NEED-EVIDENCE';'4.3'='NEED-EVIDENCE'} },
    @{ Name='wifi-only'; Exit=1; Fail=@();
       OutFilePatterns=@('wifi');
       Status=@{'5.1'='NEED-EVIDENCE';'5.2'='NEED-EVIDENCE'} }
)

$parsed = @{}
foreach ($s in $specs) { $parsed[$s.Name] = Run-Case $s.Name $s }

# ---------- special scenarios ----------
Note ''
Note 'SCENARIO: device not mounted / no evidence source'
$absent = Join-Path $cases 'device-absent\device\.adds\reeden-kobo'
$absentOut = Join-Path $outRoot 'device-absent'
$cAbs = Invoke-Script $collect @('-AppDir', $absent, '-OutDir', $absentOut)
Assert ($cAbs.Code -eq 0) ("device-absent : Collect exit 0 (actual $($cAbs.Code))")
Assert (($cAbs.Text -join "`n") -match 'DEVICE NOT AVAILABLE - no evidence collected') 'device-absent : prints DEVICE NOT AVAILABLE'
Assert (($cAbs.Text -join "`n") -match 'This is NOT an error') 'device-absent : prints "This is NOT an error."'
Assert (-not (Test-Path -LiteralPath $absentOut)) 'device-absent : no output directory created'
$chAbs = Invoke-Script $check @('-AppDir', $absent)
Assert ($chAbs.Code -eq 3) ("device-absent : Check -AppDir exit 3 (actual $($chAbs.Code))")
$chNo = Invoke-Script $check @('-EvidenceDir', (Join-Path $outRoot 'no-such-dir'))
Assert ($chNo.Code -eq 3) ("no-source : Check -EvidenceDir exit 3 (actual $($chNo.Code))")

Note ''
Note 'SCENARIO: -OutDir safety (read-only contract)'
$appInside = Join-Path $cases 'outdir-inside-appdir\device\.adds\reeden-kobo'
$cIn = Invoke-Script $collect @('-AppDir', $appInside, '-OutDir', (Join-Path $appInside 'evidence'))
Assert ($cIn.Code -eq 3) ("outdir-inside-appdir : rejected exit 3 (actual $($cIn.Code))")
Assert (($cIn.Text -join "`n") -match 'OutDir must not be inside AppDir') 'outdir-inside-appdir : correct rejection message'

$appEq = Join-Path $cases 'outdir-equals-appdir\device\.adds\reeden-kobo'
$cEq = Invoke-Script $collect @('-AppDir', $appEq, '-OutDir', $appEq)
$eqWritten = @(Get-ChildItem -LiteralPath $appEq -File -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -in @('launcher.log','current.log','power.log',
                                            'frontlight.txt','userdata.txt','manifest.json') })
Note ("  [OBS] -OutDir == -AppDir : Collect exit=" + $cEq.Code +
      " ; evidence files written into AppDir=" + $eqWritten.Count +
      " (" + (($eqWritten | ForEach-Object { $_.Name }) -join ',') + ")")
Assert ($cEq.Code -eq 3) ("outdir-equals-appdir : should be rejected (actual exit $($cEq.Code))")
Assert ($eqWritten.Count -eq 0) ("outdir-equals-appdir : ZERO evidence files written into AppDir (actual $($eqWritten.Count))")

$devRoot = Join-Path $cases 'outdir-mountroot\device'
$appRoot = Join-Path $devRoot '.adds\reeden-kobo'
$cMr = Invoke-Script $collect @('-AppDir', $appRoot, '-OutDir', $devRoot)
$mrWritten = @(Get-ChildItem -LiteralPath $devRoot -File -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -in @('manifest.json','frontlight.txt','userdata.txt') })
Note ("  [OBS] -OutDir == mountRoot : Collect exit=" + $cMr.Code +
      " ; evidence files written into mountRoot=" + $mrWritten.Count)
Assert ($cMr.Code -eq 3) ("outdir-mountroot : should be rejected (actual exit $($cMr.Code))")
Assert ($mrWritten.Count -eq 0) ("outdir-mountroot : ZERO evidence files written into mountRoot (actual $($mrWritten.Count))")

Note ''
Note 'SCENARIO: Check -AppDir direct mode (skip Collect)'
$happyApp = Join-Path $cases 'happy\device\.adds\reeden-kobo'
$rDirect = Invoke-Script $check @('-AppDir', $happyApp)
$pDirect = Get-Statuses $rDirect.Text
[System.IO.File]::WriteAllLines((Join-Path $resRoot ('direct-appdir-happy' + $suffix + '.txt')), $rDirect.Text)
Assert ($rDirect.Code -eq 1) ("direct -AppDir happy : exit 1 (actual $($rDirect.Code))")
Test-Common $pDirect 'direct-appdir-happy' `
    @{ Exit=1; Fail=@(); AllNonManualPass=$true; Status=@{} }

Note ''
Note 'SCENARIO: FrontLightLevel section boundary (EvidenceDir vs AppDir)'
$secApp = Join-Path $cases 'frontlight-other-section\device\.adds\reeden-kobo'
$rSec = Invoke-Script $check @('-AppDir', $secApp)
$pSec = Get-Statuses $rSec.Text
$secEvidence = $parsed['frontlight-other-section'].Statuses['4.2']
$secDirect   = $pSec.Statuses['4.2']
Note ("  [OBS] 4.2 via -EvidenceDir (Collect-filtered) = " + $secEvidence +
      " ; via -AppDir (direct) = " + $secDirect)
# L4 fix: -AppDir direct mode must also honour [PowerOptions], so BOTH modes
# must reach the SAME conclusion. A FrontLightLevel outside [PowerOptions]
# must not be accepted, and neither mode may judge FAIL.
Assert ($secEvidence -eq $secDirect) 'frontlight-other-section : -EvidenceDir and -AppDir give the SAME 4.2 conclusion'
Assert ($secEvidence -eq 'NEED-EVIDENCE' -and $secDirect -eq 'NEED-EVIDENCE') `
    'frontlight-other-section : FrontLightLevel outside [PowerOptions] not accepted (both NEED-EVIDENCE)'
Assert ($secEvidence -ne 'FAIL' -and $secDirect -ne 'FAIL') 'frontlight-other-section : neither mode judges FAIL'

Note ''
Note 'SCENARIO: -KoboConf override'
$koApp = Join-Path $cases 'koboconf-override\device\.adds\reeden-kobo'
$koConf = Join-Path $cases 'koboconf-override\custom\Kobo eReader.conf'
$koOut = Join-Path $outRoot 'koboconf-override'
if (-not (Test-Path -LiteralPath $koOut)) {
    New-Item -ItemType Directory -Path $koOut -Force | Out-Null
}
$cKo = Invoke-Script $collect @('-AppDir', $koApp, '-OutDir', $koOut, '-KoboConf', $koConf)
Assert ($cKo.Code -eq 0) ("koboconf-override : Collect exit 0 (actual $($cKo.Code))")
$rKo = Invoke-Script $check @('-EvidenceDir', $koOut)
$pKo = Get-Statuses $rKo.Text
Assert ($pKo.Statuses['4.2'] -eq 'PASS') 'koboconf-override : -KoboConf feeds FrontLightLevel (4.2 PASS)'
Assert ($rKo.Code -eq 1) ("koboconf-override : exit 1 (actual $($rKo.Code))")

# ---------- final ----------
Note ''
Note '======================================================================'
Note ('REGRESSION RESULT : assertions_failed = ' + $script:Bad.Count)
Note '======================================================================'
if ($script:Bad.Count -gt 0) {
    foreach ($b in $script:Bad) { Note ('  - ' + $b) }
} else {
    Note '  All assertions passed.'
}
[System.IO.File]::WriteAllLines((Join-Path $resRoot ('regression-report' + $suffix + '.txt')), $script:Note.ToArray())
exit ([int]($script:Bad.Count -gt 0))
