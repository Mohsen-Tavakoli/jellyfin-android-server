<#
.SYNOPSIS
    Health, USB-C PD power, and Android crash diagnostics for the Jellyfin Android Server.
.DESCRIPTION
    Checks:
      1. Service reachability (Jellyfin HTTP :8096, OpenSSH :8022).
      2. Remote storage & mount health over SSH (detects USB fallback mismatches).
      3. Battery, USB-C PD/PPS power telemetry, boot/shutdown reasons, dropbox watchdogs/panics,
         and Phantom Process Killer settings over ADB.
.EXAMPLE
    .\scripts\check-server-health.ps1
    .\scripts\check-server-health.ps1 -AdbPort 5555
#>

param(
    [string]$HostIp = "",
    [string]$SshUser = "",
    [int]$SshPort = 0,
    [int]$JellyfinPort = 0,
    [int]$AdbPort = 0
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir
if (Test-Path "$repoRoot\config.ps1") { . "$repoRoot\config.ps1" }

if (-not $HostIp)       { $HostIp       = if ($script:DefaultAndroidIp)    { $script:DefaultAndroidIp }    else { "192.168.1.100" } }
if (-not $SshUser)      { $SshUser      = if ($script:DefaultAndroidUser)  { $script:DefaultAndroidUser }  else { "u0_a300" } }
if ($SshPort -le 0)     { $SshPort      = if ($script:DefaultSshPort)      { $script:DefaultSshPort }      else { 8022 } }
if ($JellyfinPort -le 0){ $JellyfinPort = if ($script:DefaultJellyfinPort) { $script:DefaultJellyfinPort } else { 8096 } }

$adb = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.exe"
if (-not (Test-Path $adb)) { $adb = "adb" }

function Test-TcpPort([string]$ip, [int]$port, [int]$timeoutMs = 2000, [int]$retries = 1) {
    for ($attempt = 1; $attempt -le [math]::Max(1, $retries); $attempt++) {
        try {
            $c = [System.Net.Sockets.TcpClient]::new()
            $ar = $c.BeginConnect($ip, $port, $null, $null)
            if ($ar.AsyncWaitHandle.WaitOne($timeoutMs, $false)) {
                $c.EndConnect($ar)
                $c.Close()
                return $true
            }
            $c.Close()
        } catch {}
    }
    return $false
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Android 4K Media Server Health & Power Diagnostics" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

# 1. Service Reachability
$jfUp  = Test-TcpPort $HostIp $JellyfinPort 2000 2
$sshUp = Test-TcpPort $HostIp $SshPort 2000 2
Write-Host "[1/3] Services on ${HostIp}:" -ForegroundColor Cyan
Write-Host "      Jellyfin (:${JellyfinPort}) : $(if ($jfUp) { 'ONLINE' } else { 'OFFLINE' })" -ForegroundColor $(if ($jfUp) { 'Green' } else { 'Red' })
Write-Host "      OpenSSH  (:${SshPort}) : $(if ($sshUp) { 'ONLINE' } else { 'OFFLINE' })" -ForegroundColor $(if ($sshUp) { 'Green' } else { 'Red' })

# 2. SSH Storage & Process Check
Write-Host "`n[2/3] Storage & Process Check (SSH):" -ForegroundColor Cyan
if ($sshUp) {
    $sshScript = @'
echo "UPTIME=$(uptime)"
echo "MEDIA_TARGET=$(readlink -f ~/media 2>/dev/null || echo missing)"
echo "PREFER_USB=$([ -f ~/.prefer-usb-storage ] && echo 1 || echo 0)"
echo "USB_MOUNT=$(df 2>/dev/null | awk '/\/mnt\/media_rw\// {print $6; exit}')"
echo "JELLYFIN_PID=$(pgrep -f 'jellyfin --datadir' | head -n1)"
echo "DF_LINE=$(df -h ~/media 2>/dev/null | tail -n1)"
'@ -replace "`r`n", "`n"
    $out = $sshScript | ssh.exe -p $SshPort -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no "$SshUser@$HostIp" "bash -s"
    $kv = @{}
    foreach ($line in $out) {
        if ($line -match '^([^=]+)=(.*)$') { $kv[$Matches[1]] = $Matches[2] }
    }
    Write-Host "      Uptime       : $($kv['UPTIME'])"
    Write-Host "      Jellyfin PID : $(if ($kv['JELLYFIN_PID']) { $kv['JELLYFIN_PID'] } else { 'NOT RUNNING' })"
    Write-Host "      ~/media ->   : $($kv['MEDIA_TARGET'])"
    Write-Host "      Disk Usage   : $($kv['DF_LINE'])"
    if ($kv['PREFER_USB'] -eq '1' -and $kv['MEDIA_TARGET'] -like '/sdcard*') {
        Write-Host "      [!] WARNING: Server fell back to internal storage (/sdcard/Media) even though USB storage is preferred!" -ForegroundColor Yellow
        if ($kv['USB_MOUNT']) {
            Write-Host "          USB drive IS mounted at $($kv['USB_MOUNT']). Run '~/start-media-server.sh --restart' to bind it." -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "      Skipped (SSH unreachable)." -ForegroundColor Yellow
}

# 3. ADB Power, USB-PD & Crash Diagnostics
Write-Host "`n[3/3] Battery, USB-C PD Power & Crash Diagnostics (ADB):" -ForegroundColor Cyan
if ($AdbPort -le 0 -and (Test-TcpPort $HostIp 5555 1500 2)) { $AdbPort = 5555 }
if ($AdbPort -le 0) {
    Write-Host "      Skipped (ADB port 5555 closed; pass -AdbPort <PORT> to inspect USB-PD & crash logs).`n" -ForegroundColor Yellow
    exit 0
}

$target = "${HostIp}:${AdbPort}"
& $adb connect $target | Out-Null

$adbScript = @'
echo "===BATTERY==="
dumpsys battery | grep -E "powered:|level:|voltage:|temperature:|health:|status:"
echo "===USB_PD==="
for f in /sys/class/power_supply/usb/online /sys/class/power_supply/usb/voltage_now /sys/class/power_supply/usb/current_now /sys/class/power_supply/tcpm-source-psy-*/usb_type /sys/class/power_supply/battery/cycle_count /sys/class/power_supply/battery/charge_full /sys/class/power_supply/battery/charge_full_design; do
    if [ -e "$f" ]; then
        echo "$(basename "$(dirname "$f")")/$(basename "$f")=$(cat "$f" 2>/dev/null)"
    fi
done
echo "===PROPS==="
echo "last_boot_reason=$(getprop sys.boot.reason.last)"
echo "last_fatal_epoch=$(getprop persist.init.svc.last_fatal_reboot_epoch)"
echo "max_phantom=$(device_config get activity_manager max_phantom_processes 2>/dev/null)"
echo "monitor_phantom=$(settings get global settings_enable_monitor_phantom_procs 2>/dev/null)"
echo "===BOOT_HISTORY==="
getprop persist.sys.boot.reason.history
echo "===DROPBOX==="
dumpsys dropbox 2>/dev/null | grep -E "system_server_watchdog|SYSTEM_LAST_KMSG|SYSTEM_RESTART|SYSTEM_BOOT" | tail -n 10
'@ -replace "`r`n", "`n"

$raw = $adbScript | & $adb -s $target shell
$usbOnline = ""
$usbVolt = 0.0
$usbMa = 0.0
$level = -1

foreach ($line in $raw) {
    if ($line -match '^===') {
        Write-Host "      $line" -ForegroundColor Gray
    } else {
        Write-Host "      $line"
    }
    if ($line -match '^\s*level:\s*(\d+)') { $level = [int]$Matches[1] }
    if ($line -match 'usb/online=(\d+)') { $usbOnline = $Matches[1] }
    if ($line -match 'usb/voltage_now=(\d+)') { $usbVolt = [double]$Matches[1] / 1000000.0 }
    if ($line -match 'usb/current_now=(-?\d+)') { $usbMa = [double]$Matches[1] / 1000.0 }
}

if ($usbVolt -ge 4.5 -and ($usbOnline -eq "0" -or ([math]::Abs($usbMa) -lt 1 -and $level -ge 0 -and $level -lt 80))) {
    Write-Host "`n      [!] WARNING: USB-C PD CHARGING LOCKOUT DETECTED!" -ForegroundColor Red
    Write-Host "          VBUS has $([math]::Round($usbVolt, 2))V present, but the phone is drawing $([math]::Round($usbMa, 0)) mA (usb/online=$usbOnline, battery=$level%)." -ForegroundColor Yellow
    Write-Host "          Common cause: 30W PPS charger + USB-C PD hub + external HDD exceeding brick headroom." -ForegroundColor Yellow
    Write-Host "          Fix: Upgrade to a 45W-65W+ USB-C PD brick or use a self-powered USB hub." -ForegroundColor Yellow
}
Write-Host ""
