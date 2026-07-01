$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== iCUE CORRUPTION / HEALTH CHECK ==='
Write-Output "Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Output ''

# Install paths
$icueRoot = 'C:\Program Files\Corsair\Corsair iCUE5 Software'
$icueExe = Join-Path $icueRoot 'iCUE.exe'
$settingsPath = "$env:APPDATA\Corsair\CUE4\settings.json"
$logsDir = "$env:LOCALAPPDATA\Corsair\Logs"

Write-Output '=== INSTALL FILES ==='
if (Test-Path $icueExe) {
    $exe = Get-Item $icueExe
    $v = $exe.VersionInfo
    Write-Output "iCUE.exe: $($exe.FullName)"
    Write-Output "  Version: $($v.ProductVersion) | Size: $([math]::Round($exe.Length/1MB,2)) MB | Modified: $($exe.LastWriteTime)"
} else {
    Write-Output 'WARNING: iCUE.exe missing from expected path.'
}

$coreDlls = @('Corsair.Service.exe', 'CUEProfileManager.exe', 'CrashData.exe')
foreach ($dll in $coreDlls) {
    $p = Join-Path $icueRoot $dll
    if (Test-Path $p) {
        $f = Get-Item $p
        Write-Output "  OK: $dll ($([math]::Round($f.Length/1KB,0)) KB)"
    } else {
        Write-Output "  MISSING: $dll"
    }
}

Write-Output ''
Write-Output '=== SETTINGS / CONFIG ==='
if (Test-Path $settingsPath) {
    $s = Get-Item $settingsPath
    Write-Output "settings.json: $($s.Length) bytes | Modified: $($s.LastWriteTime)"
    try {
        $null = Get-Content $settingsPath -Raw | ConvertFrom-Json
        Write-Output '  JSON parse: OK'
    } catch {
        Write-Output "  JSON parse: CORRUPT - $($_.Exception.Message)"
    }
} else {
    Write-Output 'settings.json: not found'
}

$cue4 = "$env:APPDATA\Corsair\CUE4"
if (Test-Path $cue4) {
    $sizeMB = [math]::Round((Get-ChildItem $cue4 -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
    Write-Output "CUE4 appdata folder: ${sizeMB} MB"
}

Write-Output ''
Write-Output '=== LOGS (recent errors) ==='
if (Test-Path $logsDir) {
    $logs = Get-ChildItem $logsDir -Recurse -File -Include *.log,*.txt -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 8
    foreach ($log in $logs) {
        Write-Output "$($log.Name) | $([math]::Round($log.Length/1KB,0)) KB | $($log.LastWriteTime)"
        $hits = Select-String -Path $log.FullName -Pattern 'error|exception|crash|fail|corrupt' -SimpleMatch:$false -ErrorAction SilentlyContinue |
            Select-Object -Last 3
        foreach ($h in $hits) {
            Write-Output "  >> $($h.Line.Trim().Substring(0, [Math]::Min(120, $h.Line.Trim().Length)))"
        }
    }
} else {
    Write-Output 'No Corsair Logs folder found.'
}

Write-Output ''
Write-Output '=== SERVICES ==='
$svcNames = @('CorsairService','CorsairCpuIdService','CorsairDeviceControlService','CorsairDeviceListerService','iCUEDevicePluginHost','iCUEUpdateService')
foreach ($name in $svcNames) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Output "$($svc.Name) | $($svc.Status) | $($svc.StartType)"
    }
}

Write-Output ''
Write-Output '=== EVENT LOG (Corsair/iCUE errors, last 7 days) ==='
$start = (Get-Date).AddDays(-7)
$events = Get-WinEvent -FilterHashtable @{
    LogName = 'Application','System'
    StartTime = $start
} -ErrorAction SilentlyContinue | Where-Object {
    $_.ProviderName -match 'Corsair|iCUE' -or $_.Message -match 'Corsair|iCUE'
} | Select-Object -First 15

if ($events) {
    foreach ($e in $events) {
        $msg = ($e.Message -replace '\s+', ' ').Substring(0, [Math]::Min(100, ($e.Message -replace '\s+', ' ').Length))
        Write-Output "$($e.TimeCreated.ToString('MM/dd HH:mm')) | $($e.LevelDisplayName) | $($e.ProviderName) | $msg"
    }
} else {
    Write-Output 'No Corsair/iCUE events in last 7 days.'
}

Write-Output ''
Write-Output '=== PNP DEVICES (problem status) ==='
Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Corsair|iCUE' } | ForEach-Object {
    Write-Output "$($_.FriendlyName) | $($_.Status) | $($_.InstanceId)"
}

Write-Output ''
Write-Output '=== DRIVER FILES (Corsair) ==='
Get-ChildItem 'C:\Windows\System32\drivers' -Filter '*corsair*' -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Output "$($_.Name) | $([math]::Round($_.Length/1KB,0)) KB | $($_.LastWriteTime)"
}
if (-not (Get-ChildItem 'C:\Windows\System32\drivers' -Filter '*corsair*' -ErrorAction SilentlyContinue)) {
    Write-Output '(no corsair*.sys in drivers folder)'
}

Write-Output ''
Write-Output '=== RUNNING PROCESSES ==='
Get-Process | Where-Object { $_.ProcessName -match 'iCUE|Corsair|Cue' } | ForEach-Object {
    Write-Output "$($_.ProcessName) PID $($_.Id) | $([math]::Round($_.WorkingSet64/1MB,1)) MB"
}
