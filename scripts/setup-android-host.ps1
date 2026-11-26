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
    [string]$PairCode = "",
    [switch]$DebloatServer,
    [switch]$RestoreServer
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot  = Split-Path -Parent $scriptDir

$ProtectedPackages = @(
    "com.termux", "com.termux.boot", "com.termux.api", "org.jellyfin.mobile",
    "org.jellyfin.mobile.debug", "com.android.externalstorage",
    "com.android.providers.media", "com.android.providers.media.module",
    "com.android.documentsui", "com.android.systemui", "com.android.settings",
    "com.android.shell", "com.android.phone", "com.android.vending",
    "com.google.android.gms", "com.google.android.gsf", "com.google.android.webview",
    "com.google.android.inputmethod.latin", "com.google.android.apps.nexuslauncher",
    "com.google.android.apps.turbo", "com.google.android.pixelsystemservice",
    "com.google.android.connectivitythermalpowermanager",
    "com.android.networkstack.process", "com.android.networkstack.inprocess",
    "com.google.android.permissioncontroller", "com.google.android.packageinstaller"
)

$HeadlessDebloatPackages = @(
    "com.google.android.googlequicksearchbox", "com.google.android.youtube",
    "com.google.android.apps.youtube.music", "com.google.android.videos",
    "com.google.android.gm", "com.google.android.apps.photos",
    "com.google.android.apps.maps", "com.google.android.apps.docs",
    "com.google.android.calendar", "com.android.providers.calendar",
    "com.google.android.apps.messaging", "com.google.android.contacts",
    "com.android.providers.contacts", "com.google.android.apps.weather",
    "com.google.android.apps.recorder", "com.google.android.apps.nbu.files",
    "com.android.chrome", "com.google.android.projection.gearhead",
    "com.google.android.as", "com.google.android.as.oss",
    "com.google.android.aicore", "com.google.android.GoogleCamera",
    "com.google.android.apps.camera.services", "com.google.pixel.camera.services",
    "com.google.ar.core", "com.google.android.apps.wellbeing",
    "com.google.android.apps.tips", "com.google.android.apps.pixel.support",
    "com.google.android.apps.safetyhub", "com.google.android.apps.dreamliner",
    "com.google.android.dreamlinerupdater", "com.google.android.apps.privacy.wildlife",
    "com.google.android.apps.healthdata", "com.google.android.healthconnect.controller",
    "com.google.android.apps.pixel.nowplaying", "com.google.android.apps.pixel.creativeassistant",
    "com.google.android.apps.pixel.relationships", "com.google.android.apps.emojiwallpaper",
    "com.google.pixel.livewallpaper", "com.google.android.wallpaper.effects",
    "com.android.dreams.basic", "com.android.wallpaperbackup",
    "com.google.android.feedback", "com.google.android.partnersetup",
    "com.google.android.apps.diagnosticstool", "com.google.android.marvin.talkback",
    "com.google.android.accessibility.switchaccess", "com.google.android.tts",
    "com.android.printspooler", "com.google.android.printservice.recommendation",
    "com.google.android.apps.restore", "com.google.android.apps.setupwizard.searchselector",
    "com.google.android.ondevicepersonalization.services"
)

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

$backupDir = Join-Path $repoRoot "backups\baseline"
if ($RestoreServer) {
    $baseFile = Join-Path $backupDir "packages-enabled.txt"
    if (-not (Test-Path $baseFile)) {
        Write-Error "Baseline backup not found: $baseFile"
        exit 1
    }
    $baselineEnabled = Get-Content $baseFile | ForEach-Object { ($_ -replace '^package:', '').Trim() } | Where-Object { $_ -ne '' }
    $currDisabled = (Invoke-AdbShell "pm list packages -d --user 0") -split '\r?\n' | ForEach-Object { ($_ -replace '^package:', '').Trim() } | Where-Object { $_ -ne '' }
    $toRestore = $currDisabled | Where-Object { $baselineEnabled -contains $_ }
    Write-Host "[*] Restoring $($toRestore.Count) package(s) from baseline..." -ForegroundColor Yellow
    foreach ($pkg in $toRestore) {
        Invoke-AdbShell "pm enable --user 0 $pkg" | Out-Null
        Write-Host "  [+] Enabled $pkg"
    }
    @(
        "settings put global window_animation_scale 1.0",
        "settings put global transition_animation_scale 1.0",
        "settings put global animator_duration_scale 1.0",
        "svc bluetooth enable",
        "svc nfc enable"
    ) | ForEach-Object { Invoke-AdbShell $_ | Out-Null }
    Write-Host "[+] Server baseline restore complete!" -ForegroundColor Green
    exit 0
}

# 1. Disable Android 12-16+ Phantom Process Killer & apply Android 10/11+ Wi-Fi keep-alives
Write-Host "[1/5] Disabling Android Phantom Process Killer & configuring 24/7 Wi-Fi keep-alives..." -ForegroundColor Cyan
Invoke-AdbShell "/system/bin/device_config set_sync_disabled_for_tests persistent" | Out-Null
Invoke-AdbShell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647" | Out-Null
Invoke-AdbShell "settings put global settings_enable_monitor_phantom_procs false" | Out-Null
Invoke-AdbShell "settings put global wifi_sleep_policy 2" | Out-Null
Write-Host "      -> max_phantom_processes unlimited & wifi_sleep_policy=2 (Never sleep Wi-Fi)." -ForegroundColor Green

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
    Invoke-AdbShell "cmd appops set $pkg WAKE_LOCK allow" 2>$null | Out-Null
    Invoke-AdbShell "am set-standby-bucket $pkg active" 2>$null | Out-Null
}
Invoke-AdbShell "cmd appops set com.termux MANAGE_EXTERNAL_STORAGE allow" | Out-Null
Invoke-AdbShell "pm grant com.termux android.permission.READ_EXTERNAL_STORAGE" 2>$null | Out-Null
Invoke-AdbShell "pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE" 2>$null | Out-Null

if ($DebloatServer) {
    Write-Host "`n[Optional] Running Headless Server Debloat (saving pre-change baseline first)..." -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $backupDir "packages-enabled.txt"))) {
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        Invoke-AdbShell "pm list packages -e --user 0 | sort" | Set-Content (Join-Path $backupDir "packages-enabled.txt") -Encoding UTF8
        Invoke-AdbShell "pm list packages -d --user 0 | sort" | Set-Content (Join-Path $backupDir "packages-disabled.txt") -Encoding UTF8
        Invoke-AdbShell "settings list global | sort" | Set-Content (Join-Path $backupDir "settings-global.txt") -Encoding UTF8
        Write-Host "      -> Baseline saved to $backupDir" -ForegroundColor Green
    } else {
        Write-Host "      -> Preserving existing baseline at $backupDir" -ForegroundColor Gray
    }
    $disabledCount = 0
    foreach ($pkg in $HeadlessDebloatPackages) {
        if ($ProtectedPackages -contains $pkg) { continue }
        $out = Invoke-AdbShell "pm disable-user --user 0 $pkg"
        if ($out -match "disabled-user") { $disabledCount++ }
    }
    @(
        "svc bluetooth disable",
        "svc nfc disable",
        "settings put global window_animation_scale 0.5",
        "settings put global transition_animation_scale 0.5",
        "settings put global animator_duration_scale 0.5",
        "settings put global send_action_app_error 0",
        "settings put secure send_action_app_error 0",
        "pm trim-caches 999G"
    ) | ForEach-Object { Invoke-AdbShell $_ | Out-Null }
    Write-Host "      -> Disabled $disabledCount unused packages, turned off BT/NFC, set 0.5x animations & trimmed caches." -ForegroundColor Green
    Write-Host "      -> Roll back anytime with: .\scripts\setup-android-host.ps1 -RestoreServer" -ForegroundColor Yellow
}

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
