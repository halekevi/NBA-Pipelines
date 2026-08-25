# Clean repair for corrupted / conflicting Corsair iCUE install.
# Run as Administrator: right-click PowerShell -> Run as administrator
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   & "H:\PropORACLE\scripts\repair_icue_clean.ps1"

$ErrorActionPreference = 'Stop'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Run PowerShell as Administrator (right-click -> Run as administrator)." -ForegroundColor Red
    exit 1
}

$backupRoot = Join-Path $env:USERPROFILE "Desktop\iCUE_backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

Write-Host "=== iCUE clean repair ===" -ForegroundColor Cyan
Write-Host "Backup folder: $backupRoot"
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

# 1. Stop processes
Write-Host "`n[1/6] Stopping Corsair/iCUE processes..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -match 'iCUE|Corsair|Cue|QmlRenderer' } | ForEach-Object {
    Write-Host "  Stopping $($_.ProcessName) (PID $($_.Id))"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# 2. Stop services
Write-Host "`n[2/6] Stopping Corsair services..." -ForegroundColor Yellow
$services = @('CorsairService','CorsairCpuIdService','CorsairDeviceControlService','CorsairDeviceListerService','iCUEDevicePluginHost','iCUEUpdateService')
foreach ($name in $services) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq 'Running') {
        Write-Host "  Stopping $name"
        Stop-Service -Name $name -Force -ErrorAction SilentlyContinue
    }
}

# 3. Backup profiles + config (keep these)
Write-Host "`n[3/6] Backing up profiles and config..." -ForegroundColor Yellow
$toBackup = @(
    "$env:APPDATA\Corsair\CUE5\profiles",
    "$env:APPDATA\Corsair\CUE5\config.cuecfg",
    "$env:APPDATA\Corsair\CUE5\hw_profiles"
)
foreach ($src in $toBackup) {
    if (Test-Path $src) {
        $dest = Join-Path $backupRoot (Split-Path $src -Leaf)
        Copy-Item -Path $src -Destination $dest -Recurse -Force
        Write-Host "  Backed up: $src"
    }
}

# 4. Clear corrupted cache / logs (safe to delete)
Write-Host "`n[4/6] Clearing cache and logs..." -ForegroundColor Yellow
$toClear = @(
    "$env:LOCALAPPDATA\Corsair\CUE5\cache",
    "$env:LOCALAPPDATA\Corsair\Logs",
    "$env:LOCALAPPDATA\Corsair\icue_streamdeck_plugin\logs",
    "$env:LOCALAPPDATA\Corsair\CORSAIR iCUE 4 Software",
    "$env:LOCALAPPDATA\Corsair\CUE4"
)
foreach ($path in $toClear) {
    if (Test-Path $path) {
        Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Cleared: $path"
    }
}

# 5. Disable MSI Mystic Light plugin (conflicts with MSI X570 board + iCUE)
Write-Host "`n[5/6] Disabling MSI Mystic Light iCUE plugin (known conflict)..." -ForegroundColor Yellow
$msiPlugin = 'C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI'
$msiDisabled = 'C:\Program Files\Corsair\Corsair iCUE5 Software\plugins\MSI.disabled'
try {
    if (Test-Path $msiDisabled) {
        Write-Host "  MSI plugin already disabled."
    } elseif (Test-Path $msiPlugin) {
        takeown /f $msiPlugin /r /d y | Out-Null
        icacls $msiPlugin /grant "${env:USERNAME}:(F)" /t /c | Out-Null
        icacls $msiPlugin /grant "Administrators:(F)" /t /c | Out-Null
        Rename-Item -Path $msiPlugin -NewName 'MSI.disabled' -Force
        Write-Host "  Renamed plugins\MSI -> MSI.disabled"
    } else {
        Write-Host "  MSI plugin folder not found (may already be disabled)."
    }
} catch {
    Write-Host "  WARNING: Could not rename MSI plugin: $_" -ForegroundColor Red
    Write-Host "  Run finish_icue_repair.ps1 from an elevated PowerShell window."
}

# 6. Repair CorsairService registration
Write-Host "`n[6/6] Resetting CorsairService to automatic..." -ForegroundColor Yellow
$svc = Get-Service -Name 'CorsairService' -ErrorAction SilentlyContinue
if ($svc) {
    Set-Service -Name 'CorsairService' -StartupType Automatic
    Start-Service -Name 'CorsairService' -ErrorAction SilentlyContinue
    Write-Host "  CorsairService: $($svc.Status)"
}

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host @"

Next steps:
  1. RESTART your PC
  2. Open iCUE from Start menu (fresh cache rebuild)
  3. In iCUE Settings -> disable 'Enable MSI Mystic Light' if it still appears
  4. Use STATIC lighting on RAM (not wave) for stability test
  5. If still crashing: uninstall iCUE from Settings -> Apps, reboot,
     download fresh installer from https://www.corsair.com/icue
     then reinstall (your profiles are backed up on Desktop)

Backup saved to: $backupRoot
"@
