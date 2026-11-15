<#
.SYNOPSIS
    Mounts the Android Media Server's storage to a Windows Explorer drive letter
    via a localhost-bound WebDAV server tunneled securely over SSH.
.EXAMPLE
    .\scripts\mount-media-drive.ps1 -DriveLetter Z
    .\scripts\mount-media-drive.ps1 -Unmount -DriveLetter Z
#>

param(
    [string]$DriveLetter = "",
    [string]$HostIp = "",
    [string]$SshUser = "",
    [int]$SshPort = 0,
    [switch]$Unmount
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
if (Test-Path "$repoRoot\config.ps1") { . "$repoRoot\config.ps1" }

if (-not $DriveLetter) { $DriveLetter = if ($script:DefaultDriveLetter) { $script:DefaultDriveLetter } else { "Z" } }
if (-not $HostIp)      { $HostIp      = if ($script:DefaultAndroidIp)   { $script:DefaultAndroidIp }   else { "192.168.1.100" } }
if (-not $SshUser)     { $SshUser     = if ($script:DefaultAndroidUser) { $script:DefaultAndroidUser } else { "u0_a300" } }
if ($SshPort -le 0)    { $SshPort     = if ($script:DefaultSshPort)     { $script:DefaultSshPort }     else { 8022 } }

$drive = "$($DriveLetter.TrimEnd(':')):"

if ($Unmount) {
    Write-Host "[*] Unmounting $drive and stopping WebDAV server on Android host..." -ForegroundColor Cyan
    net use $drive /delete /y 2>$null | Out-Null
    ssh.exe -p $SshPort "$SshUser@$HostIp" "pkill -f 'rclone serve webdav' 2>/dev/null || true"
    Write-Host "[+] Unmounted $drive cleanly." -ForegroundColor Green
    exit 0
}

Write-Host "[1/2] Starting localhost-bound WebDAV server on Android host (tunneled over SSH)..." -ForegroundColor Cyan
ssh.exe -p $SshPort "$SshUser@$HostIp" "pkill -f 'rclone serve webdav' 2>/dev/null || true; nohup rclone serve webdav ~/media/ --addr 127.0.0.1:8081 >/dev/null 2>&1 &"

Start-Process -WindowStyle Hidden -FilePath "ssh.exe" -ArgumentList "-N -L 127.0.0.1:8081:127.0.0.1:8081 -p $SshPort -o ServerAliveInterval=15 $SshUser@$HostIp"
Start-Sleep -Seconds 2

Write-Host "[2/2] Mapping http://127.0.0.1:8081 to Windows Explorer drive $drive..." -ForegroundColor Cyan
net use $drive /delete /y 2>$null | Out-Null
net use $drive "http://127.0.0.1:8081" /persistent:no

if ($LASTEXITCODE -eq 0) {
    Write-Host "[+] Android Media Drive is now mounted at $drive in Windows File Explorer!" -ForegroundColor Green
    explorer.exe $drive
} else {
    Write-Host "[i] WebDAV tunnel is active at http://127.0.0.1:8081 (open in browser or WinSCP)." -ForegroundColor Yellow
}
