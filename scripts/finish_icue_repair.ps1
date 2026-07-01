# Finish iCUE repair steps 5-6 (MSI plugin + CorsairService).
# MUST run in elevated PowerShell: right-click -> Run as administrator

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Not running as Administrator." -ForegroundColor Red
    Write-Host "Close this window. Right-click PowerShell -> Run as administrator, then run this script again."
    exit 1
}

Write-Host "=== Finish iCUE repair (steps 5-6) ===" -ForegroundColor Cyan

# Stop anything that might lock the plugin folder
Get-Process | Where-Object { $_.ProcessName -match 'iCUE|Corsair|Cue|QmlRenderer' } | Stop-Process -Force -ErrorAction SilentlyContinue
foreach ($name in @('CorsairService','iCUEDevicePluginHost','CorsairCpuIdService')) {
    Stop-Service -Name $name -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# Step 5: Disable MSI plugin
Write-Host "`n[5/6] Disabling MSI Mystic Light plugin..." -ForegroundColor Yellow
$msiPlugin = 'C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI'
$msiDisabled = 'C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI.disabled'

if (Test-Path $msiDisabled) {
    Write-Host "  Already disabled (MSI.disabled exists)."
} elseif (Test-Path $msiPlugin) {
    takeown /f $msiPlugin /r /d y | Out-Null
    icacls $msiPlugin /grant "${env:USERNAME}:(F)" /t /c | Out-Null
    icacls $msiPlugin /grant "Administrators:(F)" /t /c | Out-Null
    Rename-Item -Path $msiPlugin -NewName 'MSI.disabled' -Force
    Write-Host "  OK: Renamed plugins\MSI -> MSI.disabled" -ForegroundColor Green
} else {
    Write-Host "  MSI plugin folder not found."
}

# Step 6: CorsairService
Write-Host "`n[6/6] Resetting CorsairService..." -ForegroundColor Yellow
$svc = Get-Service -Name 'CorsairService' -ErrorAction SilentlyContinue
if ($svc) {
    Set-Service -Name 'CorsairService' -StartupType Automatic
    if ($svc.Status -ne 'Running') {
        Start-Service -Name 'CorsairService' -ErrorAction SilentlyContinue
    }
    $svc = Get-Service -Name 'CorsairService'
    Write-Host "  CorsairService status: $($svc.Status)" -ForegroundColor Green
} else {
    Write-Host "  CorsairService not installed."
}

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "Restart your PC, then open iCUE and test with static RAM lighting."
