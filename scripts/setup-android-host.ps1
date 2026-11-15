<#
.SYNOPSIS
    Provisions a retired Android phone (e.g. Pixel / Galaxy / OnePlus) as a 24/7 4K Jellyfin Media Server.
.DESCRIPTION
    1. Connects via USB ADB or Wireless ADB (-PairIpPort / -ConnectIpPort).
    2. Disables the Android 12-16 Phantom Process Killer (max_phantom_processes = 2147483647)
       so Android never terminates Jellyfin or OpenSSH in the background.
    3. Whitelists Termux from Doze / battery restrictions and grants full external storage access.
    4. Installs Termux ARM64 / Termux:Boot / Termux:API APKs if placed in the `apks/` folder.
    5. Pushes `device/android-jellyfin-setup.sh` to the phone and prepares any attached USB-C drive.
.EXAMPLE
    .\scripts\setup-android-host.ps1
    .\scripts\setup-android-host.ps1 -ConnectIpPort "192.168.1.100:5555"
#>

param(
    [string]$ConnectIpPort = "",
    [string]$PairIpPort = "",
    [string]$PairCode = ""
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

$adb = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe\platform-tools\adb.exe"
if (-not (Test-Path $adb)) {
    $adb = "adb"
}

Write-Host "`n========================================================" -ForegroundColor Cyan
Write-Host "  Android 4K Jellyfin Media Server Host Provisioner" -ForegroundColor Cyan
Write-Host "========================================================`n" -ForegroundColor Cyan

if ($PairIpPort -and $PairCode) {
    Write-Host "[*] Pairing Wireless ADB at $PairIpPort..." -ForegroundColor Cyan
    & $adb pair $PairIpPort $PairCode
}

if ($ConnectIpPort) {
    Write-Host "[*] Connecting to Wireless ADB at $ConnectIpPort..." -ForegroundColor Cyan
    & $adb connect $ConnectIpPort
}

$devicesRaw = & $adb devices
$deviceLines = $devicesRaw | Select-String -Pattern "^\S+\s+(device|unauthorized|offline)"
if (-not $deviceLines) {
    Write-Host "[!] No Android device detected over ADB." -ForegroundColor Yellow
    Write-Host "    Connect via USB-C OR pass -ConnectIpPort '<ip>:<port>' for Wireless Debugging."
    exit 1
}

function Invoke-AdbShell([string]$cmd) {
    return (& $adb shell $cmd 2>&1 | Out-String).Trim()
}

$model      = Invoke-AdbShell "getprop ro.product.model"
$deviceCode = Invoke-AdbShell "getprop ro.product.device"
$androidVer = Invoke-AdbShell "getprop ro.build.version.release"
$sdkVer     = Invoke-AdbShell "getprop ro.build.version.sdk"
$wlanIp     = Invoke-AdbShell "ip -4 addr show wlan0 | grep 'inet ' | awk '{print `$2}' | cut -d/ -f1"

Write-Host "[+] Connected to: $model ($deviceCode) - Android $androidVer (API $sdkVer)" -ForegroundColor Green
Write-Host "    LAN Wi-Fi IP: $wlanIp`n" -ForegroundColor Green

# 1. Disable Android 12-16 Phantom Process Killer (Critical for Jellyfin & SSH!)
Write-Host "[1/5] Disabling Android Phantom Process Killer for 24/7 background servers..." -ForegroundColor Cyan
Invoke-AdbShell "/system/bin/device_config set_sync_disabled_for_tests persistent" | Out-Null
Invoke-AdbShell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647" | Out-Null
Invoke-AdbShell "settings put global settings_enable_monitor_phantom_procs false" | Out-Null
Write-Host "      -> max_phantom_processes set to unlimited (2147483647)." -ForegroundColor Green

# 2. Install optional Termux ARM64 + Add-on APKs if present in apks/
Write-Host "[2/5] Checking for Termux ARM64, Termux:Boot, and Termux:API APKs..." -ForegroundColor Cyan
$apkList = @(
    @{ File = "termux-arm64-v8a.apk"; Pkg = "com.termux" },
    @{ File = "termux-boot.apk";      Pkg = "com.termux.boot" },
    @{ File = "termux-api.apk";       Pkg = "com.termux.api" }
)
$installedList = Invoke-AdbShell "pm list packages"
$origVerify = Invoke-AdbShell "settings get global verifier_verify_adb_installs"
Invoke-AdbShell "settings put global verifier_verify_adb_installs 0" | Out-Null
foreach ($item in $apkList) {
    $fullApk = Join-Path $repoRoot "apks\$($item.File)"
    if (Test-Path $fullApk) {
        if ($installedList -notmatch "package:$($item.Pkg)\b") {
            Write-Host "      -> Installing $($item.File)..." -ForegroundColor Cyan
            & $adb install -r -g --bypass-low-target-sdk-block $fullApk
        } else {
            Write-Host "      -> $($item.Pkg) is already installed." -ForegroundColor Green
        }
    }
}
if ($origVerify -ne "0") {
    Invoke-AdbShell "settings put global verifier_verify_adb_installs 1" | Out-Null
}

# 3. Grant Storage & Battery Whitelist Permissions to Termux & Add-ons
Write-Host "[3/5] Whitelisting Termux suite from Doze Battery Optimization & granting storage access..." -ForegroundColor Cyan
foreach ($pkg in @("com.termux", "com.termux.boot", "com.termux.api")) {
    Invoke-AdbShell "dumpsys deviceidle whitelist +$pkg" 2>$null | Out-Null
    Invoke-AdbShell "cmd appops set $pkg RUN_IN_BACKGROUND allow" 2>$null | Out-Null
    Invoke-AdbShell "cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow" 2>$null | Out-Null
}
Invoke-AdbShell "cmd appops set com.termux MANAGE_EXTERNAL_STORAGE allow" | Out-Null
Invoke-AdbShell "pm grant com.termux android.permission.READ_EXTERNAL_STORAGE" 2>$null | Out-Null
Invoke-AdbShell "pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE" 2>$null | Out-Null

# 4. Inspect mounted storage / External USB Drive
Write-Host "[4/5] Checking mounted storage volumes (/storage)..." -ForegroundColor Cyan
$volumes = Invoke-AdbShell "ls -1 /storage"
Write-Host "      Mounted volumes: $($volumes -replace '\r?\n', ', ')"
foreach ($v in ($volumes -split '\r?\n')) {
    $v = $v.Trim()
    if ($v -and $v -ne "emulated" -and $v -ne "self") {
        $extMedia = "/storage/$v/Android/data/com.termux/files/Media"
        Write-Host "      -> Detected External USB Drive ($v)! Creating $extMedia/{Movies,Series,Audiobooks}..." -ForegroundColor Green
        Invoke-AdbShell "mkdir -p '$extMedia/Movies' '$extMedia/Series' '$extMedia/Audiobooks'" | Out-Null
    }
}

# 5. Push Termux Jellyfin Bootstrap Script (normalize CRLF -> LF for bash)
Write-Host "[5/5] Pushing android-jellyfin-setup.sh to /sdcard/Download/android-jellyfin-setup.sh..." -ForegroundColor Cyan
$localSh = Join-Path $repoRoot "device\android-jellyfin-setup.sh"
$tempLf  = Join-Path $repoRoot "device\android-jellyfin-setup.lf.sh"
$rawText = [System.IO.File]::ReadAllText($localSh) -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($tempLf, $rawText, (New-Object System.Text.UTF8Encoding($false)))
& $adb push $tempLf /sdcard/Download/android-jellyfin-setup.sh | Out-Null
Remove-Item $tempLf -Force -ErrorAction SilentlyContinue

# Launch Termux on the phone screen
Invoke-AdbShell "am start -n com.termux/.app.TermuxActivity" | Out-Null

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "  HOST PROVISIONING COMPLETE!" -ForegroundColor Green
Write-Host "  Inside Termux on the Android device, run:" -ForegroundColor White
Write-Host "    bash /sdcard/Download/android-jellyfin-setup.sh" -ForegroundColor Yellow
Write-Host "========================================================`n" -ForegroundColor Green
