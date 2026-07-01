$ErrorActionPreference = 'SilentlyContinue'

Write-Output '=== SYSTEM MEMORY ==='
$os = Get-CimInstance Win32_OperatingSystem
$totalGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$usedGB = $totalGB - $freeGB
$pct = [math]::Round(100 * $usedGB / $totalGB, 1)
Write-Output "Total: $totalGB GB | Free: $freeGB GB | Used: $usedGB GB ($pct%)"

Write-Output ''
Write-Output '=== PAGE FILE ==='
Get-CimInstance Win32_PageFileUsage | ForEach-Object {
    Write-Output "File: $($_.Name)"
    Write-Output "  Allocated MB: $($_.AllocatedBaseSize) | Current MB: $($_.CurrentUsage) | Peak MB: $($_.PeakUsage)"
}

Write-Output ''
Write-Output '=== CORSAIR / iCUE PROCESSES ==='
$procs = Get-Process | Where-Object { $_.ProcessName -match 'iCUE|Corsair|Cue|iCue' }
if (-not $procs) {
    Write-Output 'No Corsair/iCUE processes running.'
} else {
    $procs | Sort-Object WorkingSet64 -Descending | ForEach-Object {
        $ramMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
        $cpu = [math]::Round($_.CPU, 1)
        Write-Output "$($_.ProcessName) (PID $($_.Id)) | RAM ${ramMB} MB | CPU ${cpu}s | Threads $($_.Threads.Count)"
    }
    $sumMB = [math]::Round(($procs | Measure-Object WorkingSet64 -Sum).Sum / 1MB, 1)
    Write-Output "TOTAL Corsair/iCUE RAM: ${sumMB} MB"
}

Write-Output ''
Write-Output '=== iCUE INSTALL ==='
$icuePaths = @(
    'C:\Program Files\Corsair\Corsair iCUE5 Software\iCUE.exe',
    'C:\Program Files\Corsair\Corsair iCUE4 Software\iCUE.exe',
    'C:\Program Files (x86)\Corsair\CORSAIR iCUE Software\iCUE.exe'
)
$found = $false
foreach ($p in $icuePaths) {
    if (Test-Path $p) {
        $found = $true
        $v = (Get-Item $p).VersionInfo
        Write-Output $p
        Write-Output "  FileVersion: $($v.FileVersion)"
        Write-Output "  ProductVersion: $($v.ProductVersion)"
    }
}
if (-not $found) { Write-Output 'iCUE.exe not found in standard paths.' }

Write-Output ''
Write-Output '=== CORSAIR SERVICES ==='
Get-Service | Where-Object { $_.DisplayName -match 'Corsair|iCUE' -or $_.Name -match 'Corsair|iCUE' } | ForEach-Object {
    Write-Output "$($_.Name) | $($_.DisplayName) | $($_.Status) | $($_.StartType)"
}

Write-Output ''
Write-Output '=== CORSAIR DEVICES ==='
Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Corsair|iCUE' } | ForEach-Object {
    Write-Output "$($_.FriendlyName) | $($_.Status) | $($_.Class)"
}

Write-Output ''
Write-Output '=== TOP 15 RAM PROCESSES ==='
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 | ForEach-Object {
    $ramMB = [math]::Round($_.WorkingSet64 / 1MB, 1)
    Write-Output "$($_.ProcessName) | ${ramMB} MB"
}
