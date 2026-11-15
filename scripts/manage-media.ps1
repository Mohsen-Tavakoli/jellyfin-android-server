<#
.SYNOPSIS
    Storage manager for Android Jellyfin Media Server (list files, check free space, delete media).
.EXAMPLE
    .\scripts\manage-media.ps1 -Action List
    .\scripts\manage-media.ps1 -Action List -Filter "Sample Show"
    .\scripts\manage-media.ps1 -Action Space
    .\scripts\manage-media.ps1 -Action Remove -Target "Sample Show S01E01"
#>

param(
    [ValidateSet("List", "Space", "Remove")]
    [string]$Action = "List",

    [string]$Filter = "",
    [string]$Target = "",

    [string]$HostIp = "",
    [string]$SshUser = "",
    [int]$SshPort = 0,
    [switch]$Force
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
if (Test-Path "$repoRoot\config.ps1") { . "$repoRoot\config.ps1" }

if (-not $HostIp)   { $HostIp  = if ($script:DefaultAndroidIp)   { $script:DefaultAndroidIp }   else { "192.168.1.100" } }
if (-not $SshUser)  { $SshUser = if ($script:DefaultAndroidUser) { $script:DefaultAndroidUser } else { "u0_a300" } }
if ($SshPort -le 0) { $SshPort = if ($script:DefaultSshPort)     { $script:DefaultSshPort }     else { 8022 } }

$sshTarget = "$SshUser@$HostIp"

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Android Media Storage Manager ($Action)" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

if ($Action -eq "Space") {
    Write-Host "[*] Checking storage capacity on Android host..." -ForegroundColor Cyan
    ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget "df -h ~/media; echo ''; du -sh ~/media/* ~/media/Series/* ~/media/Audiobooks/* 2>/dev/null"
    exit 0
}

if ($Action -eq "List") {
    $cmd = "cd ~/media && find Movies Series Audiobooks -type f 2>/dev/null | sort"
    $raw = (ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget $cmd | Out-String)
    $lines = $raw -split '\r?\n' | Where-Object { $_.Trim() -ne "" }

    if ($Filter) {
        $flexPattern = ($Filter -replace '[\s\.]+', '.*')
        $lines = $lines | Where-Object { $_ -match $flexPattern }
    }

    if (-not $lines -or $lines.Count -eq 0) {
        Write-Host "  No matching media files found on server." -ForegroundColor Yellow
    } else {
        foreach ($line in $lines) {
            if ($line -like "Movies/*") {
                Write-Host "  [Movie]     $line" -ForegroundColor Green
            } elseif ($line -like "Audiobooks/*") {
                Write-Host "  [Audiobook] $line" -ForegroundColor Magenta
            } else {
                Write-Host "  [Series]    $line" -ForegroundColor White
            }
        }
        Write-Host "`n  Total files matched: $($lines.Count)" -ForegroundColor Cyan
    }
    Write-Host "`n[*] Folder sizes:" -ForegroundColor Cyan
    ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget "du -sh ~/media/Movies ~/media/Series/* ~/media/Audiobooks/* 2>/dev/null"
    exit 0
}

if ($Action -eq "Remove") {
    if (-not $Target) {
        Write-Error "Please specify -Target (e.g. -Target 'Sample Show*S01E01*' or -Target 'Big Buck Bunny*')"
        exit 1
    }

    $flexPattern = ($Target -replace '[\s\.\*]+', '.*')
    $cmd = "cd ~/media && find Movies Series Audiobooks -type f 2>/dev/null | sort"
    $raw = (ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget $cmd | Out-String)
    $matches = $raw -split '\r?\n' | Where-Object { $_.Trim() -ne "" -and $_ -match $flexPattern }

    if (-not $matches -or $matches.Count -eq 0) {
        Write-Host "  [!] No files on server matched '$Target'." -ForegroundColor Yellow
        exit 0
    }

    Write-Host "The following file(s) on the server matched '$Target':" -ForegroundColor Yellow
    foreach ($m in $matches) {
        Write-Host "  - $m" -ForegroundColor Red
    }

    if (-not $Force) {
        $confirm = Read-Host "`nAre you sure you want to PERMANENTLY delete these $($matches.Count) file(s)? (y/N)"
        if ($confirm -notmatch '^[yY]') {
            Write-Host "Aborted." -ForegroundColor Gray
            exit 0
        }
    }

    foreach ($m in $matches) {
        $singleQuoted = "'" + ("media/$m" -replace "'", "'\\''") + "'"
        ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget "rm -f $singleQuoted"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  [+] Deleted: $m" -ForegroundColor Green
        } else {
            Write-Host "  [!] Failed to delete: $m" -ForegroundColor Red
        }
    }
    ssh.exe -p $SshPort -o StrictHostKeyChecking=no $sshTarget "find media/Series -mindepth 1 -type d -empty -delete 2>/dev/null"
}
