# Run as Administrator: right-click PowerShell -> Run as administrator, then:
#   pwsh -NoProfile -File "H:\halek\ProfileFromC\Desktop\PropORACLE\scripts\disable_wifi_voicemeeter.ps1"
#Requires -RunAsAdministrator

$ErrorActionPreference = 'Stop'

Write-Host "Disabling Wi-Fi adapter..." -ForegroundColor Cyan
Disable-NetAdapter -Name 'Wi-Fi' -Confirm:$false
$wifi = Get-PnpDevice | Where-Object { $_.FriendlyName -match 'Intel\(R\) Wi-Fi 6 AX200' -and $_.Class -eq 'Net' }
if ($wifi) {
    Disable-PnpDevice -InstanceId $wifi.InstanceId -Confirm:$false
}
Get-NetAdapter -Name 'Wi-Fi' | Format-List Name, Status, AdminStatus

Write-Host "`nStopping VoiceMeeter (if running)..." -ForegroundColor Cyan
Get-Process | Where-Object { $_.ProcessName -match 'voicemeeter' } | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Disabling VB-Audio / VoiceMeeter devices..." -ForegroundColor Cyan
Get-PnpDevice | Where-Object {
    $_.FriendlyName -match 'VB-Audio VoiceMeeter|VB-Audio Virtual Cable' -and $_.InstanceId -match '^ROOT\\MEDIA'
} | ForEach-Object {
    Disable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false
    Write-Host "  Disabled: $($_.FriendlyName)" -ForegroundColor Green
}

Write-Host "`nDone. Discord hardware acceleration is already off in settings.json." -ForegroundColor Green
Write-Host "Restart Discord if it is open so settings take effect." -ForegroundColor Yellow
