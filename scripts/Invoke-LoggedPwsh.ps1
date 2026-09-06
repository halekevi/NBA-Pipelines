#requires -Version 5.1
<#
.SYNOPSIS
  Run a pwsh -File child and capture stdout/stderr to a log (and the host).

.DESCRIPTION
  Start-Transcript on scheduled wrappers does not capture nested `pwsh -File`
  output. 1AM/5AM then looked like 16-second no-ops when run_daily aborted
  before writing run_daily_<date>.log. This helper keeps the child exit code
  and a on-disk log even when the parent transcript is empty.
#>
function Invoke-LoggedPwsh {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$ArgumentList = @(),
        [Parameter(Mandatory = $true)][string]$LogPath,
        [string]$WorkingDirectory = ""
    )

    $pwsh = $null
    foreach ($cand in @(
        (Get-Command pwsh.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        "$env:ProgramFiles\PowerShell\7\pwsh.exe",
        (Get-Command powershell.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
    )) {
        if ($cand -and (Test-Path -LiteralPath $cand)) { $pwsh = $cand; break }
    }
    if (-not $pwsh) {
        Write-Error "pwsh.exe/powershell.exe not found"
        return 1
    }
    if (-not (Test-Path -LiteralPath $File)) {
        Write-Error "Script not found: $File"
        return 1
    }

    $wd = if ($WorkingDirectory.Trim()) { $WorkingDirectory.Trim() } else { (Get-Location).Path }
    $logDir = Split-Path -Parent $LogPath
    if ($logDir -and -not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    $outLog = "$LogPath.stdout.tmp"
    $errLog = "$LogPath.stderr.tmp"
    foreach ($tmp in @($outLog, $errLog, $LogPath)) {
        if (Test-Path -LiteralPath $tmp) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
    New-Item -ItemType File -Path $outLog -Force | Out-Null
    New-Item -ItemType File -Path $errLog -Force | Out-Null

    # Single argument string so paths with spaces survive Start-Process.
    $extra = @($ArgumentList | Where-Object { $_ -ne $null -and "$_" -ne "" }) -join " "
    $argStr = "-NoProfile -ExecutionPolicy Bypass -File `"$File`""
    if ($extra) { $argStr = "$argStr $extra" }

    Write-Host ("[logged] {0} {1}" -f $pwsh, $argStr) -ForegroundColor DarkGray
    Write-Host ("[logged] child log -> {0}" -f $LogPath) -ForegroundColor DarkGray

    $proc = Start-Process -FilePath $pwsh `
        -ArgumentList $argStr `
        -WorkingDirectory $wd `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -Wait -PassThru -NoNewWindow

    $chunks = @()
    foreach ($f in @($outLog, $errLog)) {
        if (Test-Path -LiteralPath $f) {
            $chunks += @(Get-Content -LiteralPath $f -ErrorAction SilentlyContinue)
        }
    }
    $header = @(
        ("# Invoke-LoggedPwsh  {0:yyyy-MM-dd HH:mm:ss}" -f (Get-Date)),
        ("# file: {0}" -f $File),
        ("# args: {0}" -f $extra),
        ("# exit: {0}" -f [int]$proc.ExitCode),
        ""
    )
    ($header + $chunks) | Set-Content -LiteralPath $LogPath -Encoding utf8
    foreach ($line in $chunks) { Write-Host $line }

    Remove-Item -LiteralPath $outLog, $errLog -Force -ErrorAction SilentlyContinue
    return [int]$proc.ExitCode
}
