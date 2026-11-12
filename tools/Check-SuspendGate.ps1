<#
.SYNOPSIS
  Reeden on Kobo community.4 -- 深睡四联判据自动判定（只读）。

.DESCRIPTION
  替代旧的「power.log 出现 invoked arg=suspend 即通过」假阳性门禁。
  scripts/power.sh:7 在脚本入口无条件打印该行；:89 的 on_battery prepare
  在 USB 充电 / 非 Discharging / external=on 时打印 screen-only 后 exit 3，
  设备只锁屏、根本没进内核深睡。而验收恰恰要插 USB 才能读到 power.log，
  于是旧门禁在插线场景下必然 PASS。

  本脚本与仓库 scripts/standby_report.py 同源：按 phase=preparing + pid
  配成一次 Attempt，只看 entering mem / mem returned / screen-only /
  helper exiting / phase=suspended->resuming，入口行只计数、不计分。

  通过判据（四联，缺一不可）：
    1. [power] entering mem
    2. [power] mem returned=0
    3. phase=suspended -> phase=resuming，两行 uptime 相减 > 5 秒
    4. 无 screen-only / 无其它准备阶段 reason，且 helper exiting=0

  取证顺序铁律：合盖 / 短按电源键必须在【拔线 + 电池供电】下做，保持拔线
  直到唤醒，一轮结束后先退出 Reeden 回 Nickel 主页，再插 USB 读日志。
  插线会话一律 NOT_APPLICABLE，既不算 PASS 也不算 FAIL。

.PARAMETER LogPath
  power.log 路径，默认 E:\.adds\reeden-kobo\logs\power.log。
  也可先把日志复制到电脑再用 -- 本脚本不写设备任何文件。

.PARAMETER SelfTest
  用内建合成日志自测判定逻辑，不需要设备；断言失败时退出码 1。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\Check-SuspendGate.ps1 -SelfTest
  powershell -ExecutionPolicy Bypass -File .\Check-SuspendGate.ps1 -LogPath 'E:\.adds\reeden-kobo\logs\power.log'
#>
param(
    [string]$LogPath = 'E:\.adds\reeden-kobo\logs\power.log',
    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'

function Get-SuspendAttempts {
    param([string[]]$Lines)

    $attempts = New-Object System.Collections.ArrayList
    $current = $null
    $entryLines = 0
    $entryArgs = @{}

    foreach ($line in $Lines) {
        if ($line -match '^\[power\] invoked arg=(\S*)') {
            $entryLines++
            $a = $Matches[1]
            if (-not $entryArgs.ContainsKey($a)) { $entryArgs[$a] = 0 }
            $entryArgs[$a]++
            continue   # 入口行只计数，绝不作为判据
        }

        $m = [regex]::Match($line, '^\[power\] phase=(\w+) uptime=(\d+) pid=(\d+)')
        if ($m.Success) {
            $phase = $m.Groups[1].Value
            $up = [int]$m.Groups[2].Value
            $pidNum = [int]$m.Groups[3].Value
            if ($phase -eq 'preparing') {
                $current = [pscustomobject]@{
                    Pid          = $pidNum
                    EnteringMem  = $false
                    MemReturned  = $null
                    Suspended    = $null
                    Resuming     = $null
                    ScreenOnly   = $false
                    HelperExit   = $null
                    Reasons      = New-Object System.Collections.ArrayList
                }
                [void]$attempts.Add($current)
            }
            elseif ($null -ne $current -and $current.Pid -eq $pidNum) {
                if ($phase -eq 'suspended') { $current.Suspended = $up }
                elseif ($phase -eq 'resuming') { $current.Resuming = $up }
            }
            continue
        }

        if ($null -eq $current) { continue }

        if ($line.StartsWith('[power] entering mem ')) {
            $current.EnteringMem = $true
        }
        elseif ($line -match '^\[power\] mem returned=(\d+)') {
            $current.MemReturned = [int]$Matches[1]
        }
        elseif ($line -match '^\[power\] screen-only: supply guard') {
            $current.ScreenOnly = $true
        }
        elseif ($line -match '^\[power\] (charging: retaining|display did not become idle|existing alarm:|Wi-Fi could not be suspended|Wi-Fi restore failed)') {
            [void]$current.Reasons.Add($Matches[1])
        }
        elseif ($line -match '^\[power\] helper exiting=(\d+)') {
            $current.HelperExit = [int]$Matches[1]
            $current = $null
        }
    }

    return [pscustomobject]@{ Attempts = $attempts; EntryLines = $entryLines; EntryArgs = $entryArgs }
}

function Test-SuspendAttempt {
    param($A)

    $span = $null
    if ($null -ne $A.Suspended -and $null -ne $A.Resuming) {
        $span = $A.Resuming - $A.Suspended
    }

    # 只有「供电保护，代码有意跳过深睡」才叫样本不适用；其余准备阶段失败是真问题，判 FAIL
    if ($A.ScreenOnly) {
        return [pscustomobject]@{ Verdict = 'NOT_APPLICABLE'; Span = $span; Detail = 'screen-only: supply guard (USB / charging)' }
    }
    if ($A.Reasons.Count -gt 0) {
        return [pscustomobject]@{ Verdict = 'FAIL'; Span = $span; Detail = 'prepare-stage failure: ' + ($A.Reasons -join ', ') }
    }

    $missing = New-Object System.Collections.ArrayList
    if (-not $A.EnteringMem) { [void]$missing.Add('1:entering mem') }
    if ($null -eq $A.MemReturned -or $A.MemReturned -ne 0) { [void]$missing.Add('2:mem returned=0') }
    if ($null -eq $span -or $span -le 5) { [void]$missing.Add('3:phase suspended->resuming span >5s') }
    if ($null -eq $A.HelperExit -or $A.HelperExit -ne 0) { [void]$missing.Add('4:helper exiting=0') }

    if ($missing.Count -eq 0) {
        return [pscustomobject]@{ Verdict = 'PASS'; Span = $span; Detail = 'four-fold gate satisfied' }
    }
    if (-not $A.EnteringMem -and $null -eq $A.MemReturned -and $null -eq $span -and $A.HelperExit -eq 0) {
        return [pscustomobject]@{ Verdict = 'INVALID_ENTRY_ONLY'; Span = $span; Detail = 'only entry/phase markers, no mem evidence' }
    }
    return [pscustomobject]@{ Verdict = 'FAIL'; Span = $span; Detail = 'missing: ' + ($missing -join ' | ') }
}

function Show-Report {
    param($Parsed, [string]$Source)

    $rows = New-Object System.Collections.ArrayList
    foreach ($a in $Parsed.Attempts) {
        $r = Test-SuspendAttempt $a
        # PowerShell 5.1 不允许把 if/else 语句直接作为 hashtable 的值，先算成变量
        $memRet = '-'; if ($null -ne $a.MemReturned) { $memRet = $a.MemReturned }
        $susp   = '-'; if ($null -ne $a.Suspended)   { $susp   = $a.Suspended }
        $resum  = '-'; if ($null -ne $a.Resuming)    { $resum  = $a.Resuming }
        $span   = '-'; if ($null -ne $r.Span)        { $span   = $r.Span }
        $helper = '-'; if ($null -ne $a.HelperExit)  { $helper = $a.HelperExit }
        [void]$rows.Add([pscustomobject]@{
            Pid         = $a.Pid
            EnteringMem = $a.EnteringMem
            MemReturned = $memRet
            Suspended   = $susp
            Resuming    = $resum
            Span        = $span
            ScreenOnly  = $a.ScreenOnly
            HelperExit  = $helper
            Verdict     = $r.Verdict
            Detail      = $r.Detail
        })
    }

    Write-Host ''
    Write-Host "=== Suspend gate report: $Source ===" -ForegroundColor Cyan
    if ($rows.Count -gt 0) { $rows | Format-Table -AutoSize | Out-Host }

    $pass = @($rows | Where-Object { $_.Verdict -eq 'PASS' }).Count
    $na   = @($rows | Where-Object { $_.Verdict -eq 'NOT_APPLICABLE' }).Count
    $inv  = @($rows | Where-Object { $_.Verdict -eq 'INVALID_ENTRY_ONLY' }).Count
    $fail = @($rows | Where-Object { $_.Verdict -eq 'FAIL' }).Count
    $entry = $Parsed.EntryLines
    $argsText = (($Parsed.EntryArgs.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ')

    Write-Host "invoked arg= lines : $entry  ($argsText)  -> scored 0, NOT a pass criterion"
    Write-Host "PASS=$pass  NOT_APPLICABLE=$na  INVALID_ENTRY_ONLY=$inv  FAIL=$fail  (attempts=$($rows.Count))"
    if ($entry -gt 0 -and $pass -eq 0) {
        Write-Host "WARNING: $entry entry lines but 0 PASS -- the old 'invoked arg=suspend' gate would have FALSELY reported PASS here." -ForegroundColor Yellow
    }
    Write-Host 'NOTE: PASS only counts sessions taken with USB unplugged / battery Discharging. USB-attached sessions must be marked NOT_APPLICABLE.' -ForegroundColor DarkGray

    return [pscustomobject]@{ Pass = $pass; NA = $na; Invalid = $inv; Fail = $fail; Entry = $entry; Rows = $rows }
}

if ($SelfTest) {
    # 三段合成会话：① 充电态只锁屏（旧门禁会误判 PASS）② 真深睡 ③ 准备阶段失败
    $sample = @(
        '[power] invoked arg=suspend Thu Nov 12 06:00:00 UTC 2026',
        '[power] phase=preparing uptime=1000 pid=111 Thu Nov 12 06:00:00 UTC 2026',
        '[power] sample=prepare battery=Charging external=on capacity=80',
        '[power] screen-only: supply guard battery=Charging external=on',
        '[power] phase=complete uptime=1000 pid=111 Thu Nov 12 06:00:01 UTC 2026',
        '[power] helper exiting=3 Thu Nov 12 06:00:01 UTC 2026',
        '[power] invoked arg=suspend Thu Nov 12 06:10:00 UTC 2026',
        '[power] phase=preparing uptime=2000 pid=222 Thu Nov 12 06:10:00 UTC 2026',
        '[power] entering mem Thu Nov 12 06:10:04 UTC 2026',
        '[power] phase=suspended uptime=2005 pid=222 Thu Nov 12 06:10:05 UTC 2026',
        '[power] phase=resuming uptime=2040 pid=222 Thu Nov 12 06:10:40 UTC 2026',
        '[power] mem returned=0 Thu Nov 12 06:10:40 UTC 2026',
        '[power] phase=complete uptime=2040 pid=222 Thu Nov 12 06:10:41 UTC 2026',
        '[power] helper exiting=0 Thu Nov 12 06:10:41 UTC 2026',
        '[power] invoked arg=suspend Thu Nov 12 06:20:00 UTC 2026',
        '[power] phase=preparing uptime=3000 pid=333 Thu Nov 12 06:20:00 UTC 2026',
        '[power] display did not become idle',
        '[power] phase=complete uptime=3000 pid=333 Thu Nov 12 06:20:01 UTC 2026',
        '[power] helper exiting=75 Thu Nov 12 06:20:01 UTC 2026'
    )
    $result = Show-Report (Get-SuspendAttempts $sample) 'SELFTEST (synthetic log)'
    if ($result.Entry -ne 3 -or $result.Pass -ne 1 -or $result.NA -ne 1 -or $result.Fail -ne 1) {
        Write-Host 'SELFTEST: FAILED (unexpected verdicts)' -ForegroundColor Red
        exit 1
    }
    Write-Host 'SELFTEST: PASS -- charging / entry-only sessions are NOT counted as deep sleep.' -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $LogPath)) {
    Write-Host "power.log not found: $LogPath" -ForegroundColor Yellow
    Write-Host 'DEVICE_NOT_CONNECTED or log missing. Plug in Kobo only AFTER exiting Reeden to Nickel home, then re-run.'
    exit 2
}
$lines = Get-Content -LiteralPath $LogPath -Encoding UTF8
$result = Show-Report (Get-SuspendAttempts $lines) $LogPath
if ($result.Pass -eq 0) { exit 3 }
exit 0
