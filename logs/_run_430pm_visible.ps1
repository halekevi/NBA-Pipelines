#requires -Version 5.1
$ErrorActionPreference = "Continue"
try { $Host.UI.RawUI.WindowTitle = "PropOracle - Refresh 430PM (Fri 2026-09-04)" } catch {}
$Root = "H:\PropORACLE_main_cp"
Set-Location $Root
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PROPORACLE_SKIP_ALT_BOOKS = "1"
$env:PROPORACLE_BET_WINDOW = "430PM"
$LogsDir = Join-Path $Root "logs"
$LockFile = Join-Path $Root "data\cache\refresh.lock"
$D = "2026-09-04"
$log = Join-Path $LogsDir ("task_refresh_430PM_{0:yyyy-MM-dd_HHmmss}.log" -f (Get-Date))
try { Start-Transcript -Path $log -Append | Out-Null } catch {}
Write-Host "LOG=$log" -ForegroundColor DarkGray
Write-Host "==== Visible 430PM continue: Friday $D PrizePicks fetch ====" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path (Split-Path $LockFile) | Out-Null
Set-Content -LiteralPath $LockFile -Value ("430PM | PID $PID | {0:yyyy-MM-dd HH:mm:ss}" -f (Get-Date))
Write-Host "[REFRESH 430PM] Lock acquired: $(Get-Content $LockFile)" -ForegroundColor DarkGray
$exit = 0
try {
    & pwsh -NoProfile -File "$Root\scripts\run_nba_late_fetch.ps1" -Date $D -RunLabel "430PM" -SkipPayout
    $exit = $LASTEXITCODE
    Write-Host "[LATE_FETCH] exit $exit" -ForegroundColor Yellow
    if ($exit -ne 0) {
        Write-Host "==== Combined fallback (SkipAltBooks) ====" -ForegroundColor Cyan
        & pwsh -NoProfile -File "$Root\run_pipeline.ps1" -Date $D -CombinedOnly -SkipLivePayoutCapture -SkipAltBooks -TicketGenStarts 16
        Write-Host "[CombinedOnly] exit $LASTEXITCODE"
        & py -3.14 "$Root\scripts\build_goblin70_tickets.py" --date $D --write-web
        Write-Host "[Goblin-70] exit $LASTEXITCODE"
    }
    $publish = Join-Path $Root "scripts\Publish-LiveSite.ps1"
    if (Test-Path $publish) {
        Write-Host "==== Publish-LiveSite ====" -ForegroundColor Cyan
        & pwsh -NoProfile -File $publish -RepoRoot $Root -CommitMessage "chore: live tickets/slate $D 430PM"
        Write-Host "[Publish] exit $LASTEXITCODE"
    }
}
finally {
    if (Test-Path $LockFile) {
        $cur = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ("$cur" -like "*PID $PID*") {
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
            Write-Host "[REFRESH 430PM] Lock released" -ForegroundColor DarkGray
        }
    }
    try { Stop-Transcript | Out-Null } catch {}
}
Write-Host "==== DONE 430PM continue  exit=$exit ====" -ForegroundColor Green
Write-Host "This window stays open. You can close it when you are done reading."
