#requires -Version 5.1
<#
.SYNOPSIS
  Post-5AM / post-daily health stamp. Fails if today's board was not published.

.DESCRIPTION
  Reads slate_display_date, pipeline_slate_status, and tickets_latest from RepoRoot.
  Writes logs/LAST_5AM_STATUS.json (and mirrors into sibling PropORACLE* worktrees
  so a feature-branch Cursor workspace still shows the scheduled-run result).

  Exit 0 = healthy (slate date == today and at least one tickets_latest exists).
  Exit 2 = unhealthy (scheduler should show LastTaskResult != 0).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,
    [string]$Label = "5AM",
    [string]$ExpectDate = "",
    [switch]$RequireTickets
)

$ErrorActionPreference = "Continue"
$RepoRoot = $RepoRoot.TrimEnd('\')
if (-not $ExpectDate) {
    $ExpectDate = (Get-Date).ToString("yyyy-MM-dd")
}

$logsDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

function Read-JsonFile([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        return (Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json)
    }
    catch {
        return $null
    }
}

$displayCandidates = @(
    (Join-Path $RepoRoot "ui_runner\runtime\slate_display_date.json"),
    (Join-Path $RepoRoot "ui_runner\templates\slate_display_date.json"),
    (Join-Path $RepoRoot "mobile\www\slate_display_date.json")
)
$displayPath = $null
$display = $null
foreach ($d in $displayCandidates) {
    $display = Read-JsonFile $d
    if ($display -and $display.date) {
        $displayPath = $d
        break
    }
}
$pipePath = Join-Path $RepoRoot "outputs\$ExpectDate\pipeline_slate_status.json"
$ticketCandidates = @(
    (Join-Path $RepoRoot "ui_runner\runtime\tickets_latest.json"),
    (Join-Path $RepoRoot "ui_runner\templates\tickets_latest.json"),
    (Join-Path $RepoRoot "ui_runner\data\tickets_latest.json"),
    (Join-Path $RepoRoot "mobile\www\tickets_latest.json")
)
$slateDate = if ($display -and $display.date) { [string]$display.date } else { "" }
$pipe = Read-JsonFile $pipePath
$sports = @{}
if ($pipe -and $pipe.sports) {
    $pipe.sports.PSObject.Properties | ForEach-Object { $sports[$_.Name] = [string]$_.Value }
}

$ticketPath = $null
$ticketBytes = 0
$ticketMtime = $null
foreach ($c in $ticketCandidates) {
    if (Test-Path -LiteralPath $c) {
        $ti = Get-Item -LiteralPath $c
        if ($ti.Length -gt $ticketBytes) {
            $ticketPath = $c
            $ticketBytes = [int]$ti.Length
            $ticketMtime = $ti.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
        }
    }
}

$mobileTicketsMissing = -not (Test-Path -LiteralPath (Join-Path $RepoRoot "mobile\www\tickets_latest.json"))
$completeSports = @($sports.GetEnumerator() | Where-Object { $_.Value -eq "complete" } | ForEach-Object { $_.Name })
$failedSports = @($sports.GetEnumerator() | Where-Object { $_.Value -eq "failed" } | ForEach-Object { $_.Name })

$okDate = ($slateDate -eq $ExpectDate)
$okTickets = ($ticketBytes -gt 1000)
if ($RequireTickets) {
    $healthy = $okDate -and $okTickets
}
else {
    # Allow thin days (e.g. tennis-only) if display date is today and status file exists.
    $healthy = $okDate -and ($okTickets -or ($completeSports.Count -gt 0))
}

$status = [ordered]@{
    generated_at           = (Get-Date).ToString("o")
    label                  = $Label
    repo_root              = $RepoRoot
    expect_date            = $ExpectDate
    slate_display_date     = $slateDate
    slate_date_ok          = $okDate
    tickets_path           = $ticketPath
    tickets_bytes          = $ticketBytes
    tickets_mtime          = $ticketMtime
    mobile_tickets_missing = $mobileTicketsMissing
    sports                 = $sports
    complete_sports        = $completeSports
    failed_sports          = $failedSports
    healthy                = $healthy
    message                = if ($healthy) {
        "OK: board date $slateDate; tickets=$ticketBytes bytes; complete=[$($completeSports -join ',')]"
    }
    else {
        "BAD: expect $ExpectDate got slate_display='$slateDate'; tickets_bytes=$ticketBytes; mobile_tickets_missing=$mobileTicketsMissing"
    }
}

$outPath = Join-Path $logsDir "LAST_5AM_STATUS.json"
($status | ConvertTo-Json -Depth 6) | Set-Content -LiteralPath $outPath -Encoding utf8
$txtPath = Join-Path $logsDir "LAST_5AM_STATUS.txt"
@(
    "PropOracle $Label health — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    $status.message
    "repo: $RepoRoot"
    "complete: $($completeSports -join ', ')"
    "failed: $($failedSports -join ', ')"
    "tickets: $ticketPath ($ticketBytes bytes)"
) | Set-Content -LiteralPath $txtPath -Encoding utf8

# Mirror into sibling Desktop PropORACLE* clones so feature-branch Cursor chats see it.
$desktop = Split-Path $RepoRoot -Parent
if (Test-Path -LiteralPath $desktop) {
    Get-ChildItem -LiteralPath $desktop -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "PropORACLE*" -and $_.FullName -ne $RepoRoot } |
        ForEach-Object {
            $peerLogs = Join-Path $_.FullName "logs"
            try {
                if (-not (Test-Path -LiteralPath $peerLogs)) {
                    New-Item -ItemType Directory -Path $peerLogs -Force | Out-Null
                }
                Copy-Item -LiteralPath $outPath -Destination (Join-Path $peerLogs "LAST_5AM_STATUS.json") -Force
                Copy-Item -LiteralPath $txtPath -Destination (Join-Path $peerLogs "LAST_5AM_STATUS.txt") -Force
            }
            catch { }
        }
}

Write-Host "[$Label HEALTH] $($status.message)" -ForegroundColor $(if ($healthy) { "Green" } else { "Red" })
Write-Host "[$Label HEALTH] Wrote $outPath" -ForegroundColor DarkGray

if (-not $healthy) {
    exit 2
}
exit 0
