<#
.SYNOPSIS
    Self-healing launcher for an Android 4K Jellyfin Media Server.
.DESCRIPTION
    Automates all recovery levels:
    - Level 1: Checks if Jellyfin is already running (Port 8096).
    - Level 2: Checks if OpenSSH is running (Port 8022) and launches Jellyfin remotely.
    - Level 3: If SSH is down, connects via ADB (Port 5555 or auto-discovered Wireless Debugging port),
               wakes the screen, brings Termux to focus, starts sshd, and launches Jellyfin.
    - Level 4: Polls port 8096 until the Jellyfin web dashboard is live.
.EXAMPLE
    .\scripts\start-media-server.ps1
    .\scripts\start-media-server.ps1 -HostIp "192.168.1.100" -SshUser "u0_a300"
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

Add-Type -TypeDefinition @"
using System;
using System.Net.Sockets;
using System.Threading.Tasks;
using System.Collections.Concurrent;

public class FastPortScanner {
    public static int Scan(string ip, int startPort, int endPort, int timeoutMs) {
        var found = new ConcurrentBag<int>();
        Parallel.For(startPort, endPort + 1, new ParallelOptions { MaxDegreeOfParallelism = 120 }, (port, state) => {
            if (!found.IsEmpty) state.Stop();
            try {
                using (var client = new TcpClient()) {
                    var task = client.ConnectAsync(ip, port);
                    if (task.Wait(timeoutMs) && client.Connected) {
                        found.Add(port);
                        state.Stop();
                    }
                }
            } catch {}
        });
        int result;
        return found.TryPeek(out result) ? result : 0;
    }

    public static bool TestSingle(string ip, int port, int timeoutMs) {
        try {
            using (var client = new TcpClient()) {
                var task = client.ConnectAsync(ip, port);
                return task.Wait(timeoutMs) && client.Connected;
            }
        } catch {
            return false;
        }
    }
}
"@ -ErrorAction SilentlyContinue

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Android 4K Media Server Self-Healing Launcher" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

# LEVEL 1: Is Jellyfin already running?
Write-Host "[Level 1] Checking if Jellyfin (port $JellyfinPort) is already active on $HostIp..." -ForegroundColor Cyan
if ([FastPortScanner]::TestSingle($HostIp, $JellyfinPort, 1000)) {
    Write-Host "[+] Jellyfin is ALREADY LIVE and running smoothly!" -ForegroundColor Green
    Write-Host "    Web / TV Dashboard: http://${HostIp}:${JellyfinPort}`n" -ForegroundColor White
    exit 0
}

# LEVEL 2: Is SSH running?
Write-Host "[Level 2] Checking SSH daemon (port $SshPort)..." -ForegroundColor Cyan
if ([FastPortScanner]::TestSingle($HostIp, $SshPort, 1000)) {
    Write-Host "[+] SSH is up! Starting Jellyfin via SSH..." -ForegroundColor Green
    ssh.exe -p $SshPort -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$SshUser@$HostIp" "nohup ~/start-media-server.sh > ~/media-server.log 2>&1 &"
} else {
    # LEVEL 3: Wake & recover via ADB
    Write-Host "[-] SSH is not listening. Initiating ADB auto-recovery..." -ForegroundColor Yellow

    if ($AdbPort -le 0) {
        if ([FastPortScanner]::TestSingle($HostIp, 5555, 800)) {
            $AdbPort = 5555
        } else {
            Write-Host "[*] Scanning Android Wireless Debugging range (30000-49999) on $HostIp..." -ForegroundColor Cyan
            $AdbPort = [FastPortScanner]::Scan($HostIp, 30000, 49999, 250)
        }
    }

    if ($AdbPort -le 0) {
        Write-Host "`n[!] Could not reach SSH ($SshPort) or ADB on $HostIp." -ForegroundColor Red
        Write-Host "    Open Termux once on the phone screen OR enable Wireless Debugging in Developer Options.`n" -ForegroundColor Yellow
        exit 1
    }

    Write-Host "[+] Connecting via ADB on ${HostIp}:${AdbPort}..." -ForegroundColor Green
    & $adb connect "${HostIp}:${AdbPort}" | Out-Null

    Write-Host "[*] Waking device and launching Termux + sshd + Jellyfin..." -ForegroundColor Cyan
    & $adb shell "input keyevent KEYCODE_WAKEUP" | Out-Null
    & $adb shell "am start -n com.termux/.app.TermuxActivity" | Out-Null
    Start-Sleep -Seconds 1
    & $adb shell "input keyevent 66" | Out-Null
    & $adb shell "input text 'sshd'" | Out-Null
    & $adb shell "input keyevent 66" | Out-Null
    Start-Sleep -Milliseconds 600
    & $adb tcpip 5555 2>$null | Out-Null
    & $adb shell "input text 'nohup ~/start-media-server.sh > ~/media-server.log 2>&1 &'" | Out-Null
    & $adb shell "input keyevent 66" | Out-Null
}

# LEVEL 4: Health poll
Write-Host "`n[*] Waiting for Jellyfin to come online (polling port $JellyfinPort)..." -ForegroundColor Cyan
$started = $false
for ($i = 1; $i -le 15; $i++) {
    Write-Host "    Checking status ($i/15)..." -NoNewline
    if ([FastPortScanner]::TestSingle($HostIp, $JellyfinPort, 1500)) {
        Write-Host " UP!" -ForegroundColor Green
        $started = $true
        break
    } else {
        Write-Host " starting..." -ForegroundColor Gray
        Start-Sleep -Seconds 1
    }
}

if ($started) {
    Write-Host "`n========================================================" -ForegroundColor Green
    Write-Host "  SUCCESS: Android 4K Media Server is ONLINE!" -ForegroundColor Green
    Write-Host "  Jellyfin Dashboard : http://${HostIp}:${JellyfinPort}" -ForegroundColor White
    Write-Host "  SSH Daemon ($SshPort)  : active (ready for media uploads)" -ForegroundColor White
    Write-Host "========================================================`n" -ForegroundColor Green
} else {
    Write-Host "`n[!] Server process dispatched. Still initializing database/transcoder." -ForegroundColor Yellow
    Write-Host "    Check dashboard shortly at: http://${HostIp}:${JellyfinPort}`n"
}
