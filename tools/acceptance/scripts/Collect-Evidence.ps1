# =====================================================================
# Collect-Evidence.ps1
# Reeden-Kobo v0.7.9-community.4 acceptance - READ-ONLY evidence collector
# Target: Windows PowerShell 5.1. This file is 100% ASCII by design.
#
# SAFETY CONTRACT:
#   * This script NEVER writes to the device volume. Device access is
#     Test-Path / Copy-Item (read) / File.ReadAllLines / File.ReadAllText.
#   * No deletions, no disk checks, no checksum recompute, no binary edits.
#   * All output goes to -OutDir, validated to be OFF the device volume.
#   * userdata/no-sleep-cover is a MANUAL fallback. This script never
#     creates it, and never creates any file under -AppDir.
#   * Device log timestamps are UTC, 8 hours behind China time (UTC+8).
#
# EXIT CODES: 0 = ok (including "device not mounted"), 3 = bad OutDir
# =====================================================================
[CmdletBinding()]
param(
    [string]$AppDir   = 'E:\.adds\reeden-kobo',
    [string]$OutDir   = '',
    [string]$KoboConf = ''
)

$ErrorActionPreference = 'Stop'

$ScriptDir   = $PSScriptRoot
$PackageRoot = Split-Path -Parent $ScriptDir
if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $OutDir = Join-Path $PackageRoot 'evidence'
}

function Write-Info([string]$Text) { Write-Host $Text }
function Write-Rule([string]$Title) {
    Write-Host ''
    Write-Host ('=' * 72)
    Write-Host $Title
    Write-Host ('=' * 72)
}

# ---------- 0. Safety banner ----------
Write-Rule 'Reeden-Kobo v0.7.9-community.4 - READ-ONLY evidence collector'
Write-Info 'SAFETY / HANDLING NOTES:'
Write-Info '  1. READ-ONLY: this script never writes to the device volume.'
Write-Info '  2. BEFORE connecting USB: exit Reeden, return to the native home screen.'
Write-Info '  3. BEFORE unplugging: wait for the OS "Safely Remove Hardware" notice.'
Write-Info '     Repeated unplugging under power has corrupted FAT32 in the past.'
Write-Info '  4. Device log timestamps are UTC, 8 hours behind China time (UTC+8).'
Write-Info '  5. userdata/no-sleep-cover is a MANUAL fallback. Never auto-created.'

# ---------- 1. Device availability (graceful, non-error exit) ----------
if (-not (Test-Path -LiteralPath $AppDir -PathType Container)) {
    Write-Info ''
    Write-Info 'DEVICE NOT AVAILABLE - no evidence collected.'
    Write-Info ('  AppDir not found: ' + $AppDir)
    Write-Info '  The Kobo USB volume is not mounted (expected before plugging in).'
    Write-Info '  This is NOT an error. Exit Reeden on the Kobo, plug in USB, run again.'
    Write-Info '  No output directory was created and no manifest was written.'
    exit 0
}

# ---------- 2. Resolve paths; refuse any OutDir on the device ----------
$appFull   = [System.IO.Path]::GetFullPath($AppDir).TrimEnd('\', '/')
$mountRoot = Split-Path -Parent (Split-Path -Parent $appFull)
$driveRoot = [System.IO.Path]::GetPathRoot($appFull)
$mountIsDriveRoot = ($mountRoot.TrimEnd('\', '/') -ieq $driveRoot.TrimEnd('\', '/'))
$outFull   = [System.IO.Path]::GetFullPath($OutDir).TrimEnd('\', '/')

if ($outFull -ieq $appFull -or $outFull.StartsWith($appFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Info 'ERROR: OutDir must not be inside AppDir (device volume).'
    Write-Info ('  OutDir: ' + $outFull)
    Write-Info ('  AppDir: ' + $appFull)
    exit 3
}
$mountRootNorm = $mountRoot.TrimEnd('\', '/')
if ($outFull -ieq $mountRootNorm -or
    $outFull.StartsWith($mountRootNorm + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
    ($mountIsDriveRoot -and $outFull.StartsWith($driveRoot, [System.StringComparison]::OrdinalIgnoreCase))) {
    Write-Info 'ERROR: OutDir must not be on the device volume.'
    Write-Info ('  OutDir    : ' + $outFull)
    Write-Info ('  MountRoot : ' + $mountRootNorm)
    exit 3
}

if (-not (Test-Path -LiteralPath $outFull -PathType Container)) {
    New-Item -ItemType Directory -Path $outFull -Force | Out-Null
}

# UTF-8 WITH BOM: Windows PowerShell 5.1 Get-Content then decodes the
# non-ASCII characters in local paths correctly instead of showing mojibake.
# The .ps1 file itself stays 100% ASCII; only generated files use UTF-8.
$enc = [System.Text.Encoding]::UTF8

Write-Info ''
Write-Info ('  AppDir    : ' + $appFull)
Write-Info ('  MountRoot : ' + $mountRoot)
Write-Info ('  OutDir    : ' + $outFull)
Write-Info ''
Write-Info 'Copying device logs (read-only) ...'

# ---------- 3. Copy logs (device is source only) ----------
$copyPlan = @(
    @{ Name = 'launcher.log';             Rel = 'logs\launcher.log' },
    @{ Name = 'current.log';              Rel = 'logs\current.log' },
    @{ Name = 'power.log';                Rel = 'logs\power.log' },
    @{ Name = 'install-verification.log'; Rel = 'install-verification.log' },
    @{ Name = 'previous.log';             Rel = 'logs\previous.log' },
    @{ Name = 'wifi.log';                 Rel = 'logs\wifi.log' },
    @{ Name = 'power.log.1';              Rel = 'logs\power.log.1' },
    @{ Name = 'guardian.log';             Rel = 'logs\guardian.log' }
)
$fileReport = @()
foreach ($item in $copyPlan) {
    $src   = Join-Path $appFull $item.Rel
    $dst   = Join-Path $outFull $item.Name
    $found = $false
    $bytes = [int64]0
    if (Test-Path -LiteralPath $src -PathType Leaf) {
        Copy-Item -LiteralPath $src -Destination $dst -Force
        $fi    = Get-Item -LiteralPath $dst
        $found = $true
        $bytes = [int64]$fi.Length
        Write-Info ('  [OK]   ' + $item.Rel + ' -> ' + $item.Name + ' (' + $bytes + ' bytes)')
    } else {
        Write-Info ('  [MISS] ' + $item.Rel)
    }
    $fileReport += [pscustomobject]@{
        name   = $item.Name
        source = $src
        found  = $found
        bytes  = $bytes
    }
}

# ---------- 4. FrontLightLevel (only inside [PowerOptions]) ----------
function Get-FrontLightLines([string]$Path) {
    $list = New-Object System.Collections.Generic.List[string]
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $list.ToArray()
    }
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

$confCandidates = @()
if (-not [string]::IsNullOrWhiteSpace($KoboConf)) {
    $confCandidates += $KoboConf
}
# Source: recover.sh uses /mnt/onboard/.kobo/Kobo/Kobo eReader.conf.
$confCandidates += (Join-Path $mountRoot '.kobo\Kobo\Kobo eReader.conf')
# Lenient fallback for people who copied the config into the app dir.
$confCandidates += (Join-Path $appFull 'Kobo eReader.conf')

$confPath  = ''
$confFound = $false
foreach ($cand in $confCandidates) {
    if (Test-Path -LiteralPath $cand -PathType Leaf) {
        $confPath  = $cand
        $confFound = $true
        break
    }
}
$frontLines = @()
if ($confFound) {
    $frontLines = @(Get-FrontLightLines $confPath)
    Write-Info ('  [OK]   Kobo eReader.conf: ' + $confPath)
} else {
    Write-Info '  [MISS] Kobo eReader.conf (mount root and AppDir checked)'
}

$confLabel = 'not found'
if ($confFound) { $confLabel = $confPath }
$frontOut = New-Object System.Collections.Generic.List[string]
$frontOut.Add('# source: ' + $confLabel)
$frontOut.Add('# section: [PowerOptions]; value is a hardware-scale level.')
foreach ($fl in $frontLines) { $frontOut.Add($fl) }
$frontOutPath = Join-Path $outFull 'frontlight.txt'
[System.IO.File]::WriteAllLines($frontOutPath, $frontOut.ToArray(), $enc)

# ---------- 5. userdata markers (never created, only inspected) ----------
function Get-UserDataMarker([string]$Base, [string]$Name, [bool]$ReadValue) {
    $path  = Join-Path $Base ('userdata\' + $Name)
    $found = Test-Path -LiteralPath $path -PathType Leaf
    $value = ''
    if ($found -and $ReadValue) {
        $raw   = [System.IO.File]::ReadAllText($path)
        $value = $raw -replace '\s', ''
        if ($value.Length -gt 64) { $value = $value.Substring(0, 64) }
    }
    return [pscustomobject]@{ name = $Name; found = $found; value = $value }
}
function Format-Marker([bool]$Found, [string]$Value) {
    if (-not $Found) { return '<absent>' }
    if ([string]::IsNullOrEmpty($Value)) { return '<empty>' }
    return $Value
}

$tp = Get-UserDataMarker $appFull 'turn-profile'   $true
$wh = Get-UserDataMarker $appFull 'wifi-handoff'   $true
$nc = Get-UserDataMarker $appFull 'no-sleep-cover' $false

$udLines = New-Object System.Collections.Generic.List[string]
$udLines.Add('turn-profile='   + (Format-Marker $tp.found $tp.value))
$udLines.Add('wifi-handoff='   + (Format-Marker $wh.found $wh.value))
$ncText = '<absent>'
if ($nc.found) { $ncText = 'present' }
$udLines.Add('no-sleep-cover=' + $ncText)
$udOutPath = Join-Path $outFull 'userdata.txt'
[System.IO.File]::WriteAllLines($udOutPath, $udLines.ToArray(), $enc)

# Informational only: these state flags change suspend behaviour.
$stateFlags = @()
foreach ($flag in @('power-screen-only', 'power-test')) {
    $flagPath = Join-Path $appFull ('state\' + $flag)
    $stateFlags += [pscustomobject]@{
        name  = $flag
        found = (Test-Path -LiteralPath $flagPath)
    }
}

# ---------- 6. Manifest ----------
$manifest = [ordered]@{
    schema          = 'reeden-kobo-acceptance/1'
    collectedAtUtc  = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
    appDir          = $appFull
    mountRoot       = $mountRoot
    koboConf        = $confLabel
    koboConfFound   = $confFound
    frontLightLines = @($frontLines)
    files           = @($fileReport)
    userdata        = [ordered]@{
        turnProfile  = [ordered]@{ found = $tp.found; value = $tp.value }
        wifiHandoff  = [ordered]@{ found = $wh.found; value = $wh.value }
        noSleepCover = [ordered]@{ found = $nc.found; value = '' }
    }
    stateFlags      = @($stateFlags)
    notes           = @(
        'Device log timestamps are UTC, 8 hours behind China Standard Time (UTC+8).',
        'READ-ONLY collector. It never writes to the device volume.',
        'userdata/no-sleep-cover is a MANUAL fallback; this script never creates it.',
        'install-verification.log lives in the app root, not under logs/.',
        'current.log is rotated to previous.log on every Reeden launch.',
        'Kobo eReader.conf is at <mount>/.kobo/Kobo/, not under .adds/.'
    )
}
$json         = $manifest | ConvertTo-Json -Depth 6
$manifestPath = Join-Path $outFull 'manifest.json'
[System.IO.File]::WriteAllText($manifestPath, $json, $enc)

# ---------- 7. Summary ----------
$copiedCount = @($fileReport | Where-Object { $_.found }).Count
Write-Rule 'DONE - evidence collected (device volume untouched)'
Write-Info ('  Evidence dir  : ' + $outFull)
Write-Info ('  Manifest      : ' + $manifestPath)
Write-Info ('  Copied files  : ' + $copiedCount + ' of ' + $fileReport.Count)
Write-Info ('  FrontLight    : ' + $frontLines.Count + ' line(s) in [PowerOptions]')
Write-Info ('  no-sleep-cover: ' + $ncText + ' (manual fallback, never auto-created)')
Write-Info ''
Write-Info 'NEXT: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Check-Evidence.ps1 -EvidenceDir .\evidence'
Write-Info 'REMINDER: device logs use UTC (8 hours behind UTC+8).'
exit 0
