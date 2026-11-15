<#
.SYNOPSIS
    Smart differential media uploader from PC to Android 4K Jellyfin Media Server.
.DESCRIPTION
    1. Resolves local files, folders, or space/dot-insensitive wildcards.
    2. Checks what files already exist on the server.
    3. Skips already-uploaded files (saves bandwidth & time).
    4. Uploads only missing/new files over SSH (port 8022) or ADB.
.EXAMPLE
    .\scripts\push-media.ps1 -Path "C:\Media\Sample Show S01*" -Category Series -ShowName "Sample Show"
    .\scripts\push-media.ps1 -Category Movies -Path "C:\Media\Big Buck Bunny (2008).mkv"
    .\scripts\push-media.ps1 -Category Audiobooks -BookName "Sample Audiobook" -Path "C:\Media\Sample Audiobook*"
#>

param(
    [Parameter(Mandatory = $true, Position = 0, ValueFromPipeline = $true, ValueFromPipelineByPropertyName = $true)]
    [Alias("FullName")]
    [string[]]$Path,

    [ValidateSet("Movies", "Series", "Audiobooks")]
    [string]$Category = "Series",

    [Alias("BookName")]
    [string]$ShowName = "",

    [string]$HostIp = "",
    [string]$SshUser = "",
    [int]$SshPort = 0,
    [switch]$UseAdb,
    [switch]$Force
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
if (Test-Path "$repoRoot\config.ps1") { . "$repoRoot\config.ps1" }

if (-not $HostIp)   { $HostIp  = if ($script:DefaultAndroidIp)   { $script:DefaultAndroidIp }   else { "192.168.1.100" } }
if (-not $SshUser)  { $SshUser = if ($script:DefaultAndroidUser) { $script:DefaultAndroidUser } else { "u0_a300" } }
if ($SshPort -le 0) { $SshPort = if ($script:DefaultSshPort)     { $script:DefaultSshPort }     else { 8022 } }

# Resolve one or more literal paths, directories, or wildcards
$localFiles = @()
foreach ($p in $Path) {
    if (Test-Path -LiteralPath $p -PathType Container) {
        $localFiles += Get-ChildItem -LiteralPath $p -File -Recurse
    } elseif (Test-Path -LiteralPath $p -PathType Leaf) {
        $localFiles += Get-Item -LiteralPath $p
    } else {
        $parentDir = Split-Path -Path $p -Parent
        $leafPattern = Split-Path -Path $p -Leaf
        $flexibleLeaf = ($leafPattern -replace '[\s\.]+', '*')
        $flexiblePath = if ($parentDir) { Join-Path $parentDir $flexibleLeaf } else { $flexibleLeaf }

        $matched = @(Get-ChildItem -Path $p -ErrorAction SilentlyContinue)
        if ($flexiblePath -ne $p) {
            $matched += @(Get-ChildItem -Path $flexiblePath -ErrorAction SilentlyContinue)
        }
        $matched = $matched | Sort-Object FullName -Unique

        foreach ($m in $matched) {
            if ($m.PSIsContainer) {
                $localFiles += Get-ChildItem -LiteralPath $m.FullName -File -Recurse
            } else {
                $localFiles += $m
            }
        }
    }
}

if (-not $localFiles -or $localFiles.Count -eq 0) {
    Write-Error "No matching files found for: $($Path -join ', ')"
    exit 1
}

$remoteDir = if ($ShowName) {
    if ($Category -eq "Audiobooks") { "media/Audiobooks/$ShowName" } else { "media/Series/$ShowName" }
} else {
    "media/$Category"
}
$remoteDirQuoted = "'" + ($remoteDir -replace "'", "'\\''") + "'"
$target = if ($SshUser) { "$SshUser@$HostIp" } else { $HostIp }

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Android Media Server Smart Differential Sync" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

# 1. Ensure remote directory exists and fetch existing files list for differential skip
$remoteExistingFiles = @()
if (-not $UseAdb) {
    ssh.exe -p $SshPort -o StrictHostKeyChecking=no "$target" "mkdir -p $remoteDirQuoted" 2>$null | Out-Null
    if (-not $Force) {
        Write-Host "[*] Checking existing files on server in ~/$remoteDir..." -ForegroundColor Cyan
        $remoteListRaw = (ssh.exe -p $SshPort -o StrictHostKeyChecking=no "$target" "ls -1 $remoteDirQuoted" 2>$null | Out-String)
        if ($remoteListRaw) {
            $remoteExistingFiles = $remoteListRaw -split '\r?\n' | ForEach-Object { $_.Trim() } | Where-Object { $_ }
        }
    }
}

$uploadedCount = 0
$skippedCount = 0

foreach ($file in $localFiles) {
    $fn = $file.Name
    $sizeMB = [math]::Round($file.Length / 1MB, 1)

    if ($remoteExistingFiles -contains $fn -and -not $Force) {
        Write-Host "  [-] Skipping '$fn' ($sizeMB MB) - already on server!" -ForegroundColor Yellow
        $skippedCount++
        continue
    }

    Write-Host "`n[*] Uploading '$fn' ($sizeMB MB) -> ~/$remoteDir/..." -ForegroundColor Cyan
    if ($UseAdb) {
        $adb = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.exe"
        if (-not (Test-Path $adb)) { $adb = "adb" }
        $usbPath = (& $adb shell "df 2>/dev/null | awk '/\/mnt\/media_rw\// {print `$6; exit}'" 2>&1 | Out-String).Trim()
        $adbDest = if ($usbPath) { "$usbPath/Media/Series/$ShowName/" } else { "/sdcard/Media/Series/$ShowName/" }
        & $adb push $file.FullName $adbDest
    } else {
        scp.exe -O -P $SshPort -o ServerAliveInterval=15 -o ServerAliveCountMax=6 -o TCPKeepAlive=yes -o StrictHostKeyChecking=no "$($file.FullName)" "${target}:${remoteDirQuoted}/"
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [+] Uploaded '$fn' successfully!" -ForegroundColor Green
        $uploadedCount++
    } else {
        Write-Host "  [!] Failed uploading '$fn'" -ForegroundColor Red
    }
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Summary: $uploadedCount uploaded, $skippedCount skipped (already present)." -ForegroundColor Green
Write-Host "========================================================`n" -ForegroundColor Cyan
