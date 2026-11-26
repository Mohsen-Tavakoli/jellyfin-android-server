#!/usr/bin/env python3
"""
Cross-Platform Android 4K Jellyfin Media Server Host Provisioner (macOS / Linux / Windows)

1. Connects via USB ADB or Wireless ADB (--pair / --connect).
2. Disables the Android 12-16+ Phantom Process Killer (max_phantom_processes = 2147483647)
   so Android never terminates Jellyfin or OpenSSH in the background.
3. Whitelists Termux from Doze / battery restrictions and grants full external storage access.
4. Installs Termux ARM64 / Termux:Boot / Termux:API APKs if placed in the `apks/` folder.
5. Pushes `device/android-jellyfin-setup.sh` to `/sdcard/Download/` and prepares USB-C storage.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Core packages that must NEVER be disabled by --debloat-server
PROTECTED_PACKAGES = {
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
    "com.google.android.permissioncontroller", "com.google.android.packageinstaller",
}

# Safe consumer, AI, Android Auto, camera, wallpaper & telemetry packages for headless servers
HEADLESS_DEBLOAT_PACKAGES = [
    "com.google.android.googlequicksearchbox",
    "com.google.android.youtube",
    "com.google.android.apps.youtube.music",
    "com.google.android.videos",
    "com.google.android.gm",
    "com.google.android.apps.photos",
    "com.google.android.apps.maps",
    "com.google.android.apps.docs",
    "com.google.android.calendar",
    "com.android.providers.calendar",
    "com.google.android.apps.messaging",
    "com.google.android.contacts",
    "com.android.providers.contacts",
    "com.google.android.apps.weather",
    "com.google.android.apps.recorder",
    "com.google.android.apps.nbu.files",
    "com.android.chrome",
    "com.google.android.projection.gearhead",
    "com.google.android.as",
    "com.google.android.as.oss",
    "com.google.android.aicore",
    "com.google.android.GoogleCamera",
    "com.google.android.apps.camera.services",
    "com.google.pixel.camera.services",
    "com.google.ar.core",
    "com.google.android.apps.wellbeing",
    "com.google.android.apps.tips",
    "com.google.android.apps.pixel.support",
    "com.google.android.apps.safetyhub",
    "com.google.android.apps.dreamliner",
    "com.google.android.dreamlinerupdater",
    "com.google.android.apps.privacy.wildlife",
    "com.google.android.apps.healthdata",
    "com.google.android.healthconnect.controller",
    "com.google.android.apps.pixel.nowplaying",
    "com.google.android.apps.pixel.creativeassistant",
    "com.google.android.apps.pixel.relationships",
    "com.google.android.apps.emojiwallpaper",
    "com.google.pixel.livewallpaper",
    "com.google.android.wallpaper.effects",
    "com.android.dreams.basic",
    "com.android.wallpaperbackup",
    "com.google.android.feedback",
    "com.google.android.partnersetup",
    "com.google.android.apps.diagnosticstool",
    "com.google.android.marvin.talkback",
    "com.google.android.accessibility.switchaccess",
    "com.google.android.tts",
    "com.android.printspooler",
    "com.google.android.printservice.recommendation",
    "com.google.android.apps.restore",
    "com.google.android.apps.setupwizard.searchselector",
    "com.google.android.ondevicepersonalization.services",
]


def find_adb() -> str:
    adb_in_path = shutil.which("adb")
    if adb_in_path:
        return adb_in_path
    candidates = [
        Path.home() / "Library/Android/sdk/platform-tools/adb",  # macOS
        Path("/opt/homebrew/bin/adb"),                           # macOS Apple Silicon Homebrew
        Path("/usr/local/bin/adb"),                              # macOS Intel / Linux
        Path.home() / "Android/Sdk/platform-tools/adb",          # Linux
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/WinGet/Packages/Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe/platform-tools/adb.exe",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return "adb"


def run_adb(adb: str, args: list[str], check: bool = False) -> str:
    res = subprocess.run([adb, *args], capture_output=True, text=True)
    if check and res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return (res.stdout or "").strip()


def adb_shell(adb: str, cmd: str) -> str:
    return run_adb(adb, ["shell", cmd])


def main():
    parser = argparse.ArgumentParser(
        description="Provision an Android phone as a 24/7 4K Jellyfin Media Server via ADB."
    )
    parser.add_argument("--connect", help="Wireless ADB IP:Port to connect (e.g. 192.168.1.100:5555)")
    parser.add_argument("--pair", help="Wireless ADB IP:Port for initial pairing")
    parser.add_argument("--pair-code", help="6-digit Wireless Debugging pairing code")
    parser.add_argument("--debloat-server", action="store_true", help="Back up packages and safely disable unused consumer/AI/car/camera apps for headless server RAM savings")
    parser.add_argument("--restore-server", action="store_true", help="Re-enable all packages saved in backups/baseline/packages-enabled.txt and restore radio/animation defaults")
    args = parser.parse_args()

    adb = find_adb()

    print("\n========================================================")
    print("  Android 4K Jellyfin Media Server Host Provisioner")
    print("========================================================\n")

    if args.pair and args.pair_code:
        print(f"[*] Pairing Wireless ADB at {args.pair}...")
        print(run_adb(adb, ["pair", args.pair, args.pair_code]))

    if args.connect:
        print(f"[*] Connecting to Wireless ADB at {args.connect}...")
        print(run_adb(adb, ["connect", args.connect]))

    devices_out = run_adb(adb, ["devices"])
    active = [
        line
        for line in devices_out.splitlines()[1:]
        if re.search(r"\b(device|unauthorized|offline)\b", line)
    ]
    if not active:
        print("[!] No Android device detected over ADB.")
        print("    Connect via USB-C OR pass --connect '<ip>:<port>' for Wireless Debugging.")
        sys.exit(1)

    model = adb_shell(adb, "getprop ro.product.model")
    device_code = adb_shell(adb, "getprop ro.product.device")
    android_ver = adb_shell(adb, "getprop ro.build.version.release")
    sdk_ver = adb_shell(adb, "getprop ro.build.version.sdk")
    wlan_ip = adb_shell(adb, "ip -4 addr show wlan0 | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1")

    print(f"[+] Connected to: {model} ({device_code}) - Android {android_ver} (API {sdk_ver})")
    print(f"    LAN Wi-Fi IP: {wlan_ip}\n")

    backup_dir = REPO_ROOT / "backups" / "baseline"
    if args.restore_server:
        base_file = backup_dir / "packages-enabled.txt"
        if not base_file.is_file():
            print(f"[!] Baseline backup not found at {base_file}")
            sys.exit(1)
        baseline_enabled = {
            line.replace("package:", "").strip()
            for line in base_file.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("package:")
        }
        curr_disabled = {
            line.replace("package:", "").strip()
            for line in adb_shell(adb, "pm list packages -d --user 0").splitlines()
            if line.strip().startswith("package:")
        }
        to_restore = sorted(baseline_enabled & curr_disabled)
        print(f"[*] Restoring {len(to_restore)} package(s) from baseline...")
        for pkg in to_restore:
            adb_shell(adb, f"pm enable --user 0 {pkg}")
            print(f"  [+] Enabled {pkg}")
        for cmd in (
            "settings put global window_animation_scale 1.0",
            "settings put global transition_animation_scale 1.0",
            "settings put global animator_duration_scale 1.0",
            "svc bluetooth enable",
            "svc nfc enable",
        ):
            adb_shell(adb, cmd)
        print("[+] Server baseline restore complete!")
        return

    # 1. Disable Phantom Process Killer & apply Android 10/11+ Wi-Fi keep-alives
    print("[1/5] Disabling Android Phantom Process Killer & configuring 24/7 Wi-Fi keep-alives...")
    adb_shell(adb, "/system/bin/device_config set_sync_disabled_for_tests persistent")
    adb_shell(adb, "/system/bin/device_config put activity_manager max_phantom_processes 2147483647")
    adb_shell(adb, "settings put global settings_enable_monitor_phantom_procs false")
    adb_shell(adb, "settings put global wifi_sleep_policy 2")
    print("      -> max_phantom_processes unlimited & wifi_sleep_policy=2 (Never sleep Wi-Fi).")

    # 2. Optional APKs in apks/
    print("[2/5] Checking for Termux ARM64, Termux:Boot, and Termux:API APKs...")
    apks = [
        ("termux-arm64-v8a.apk", "com.termux"),
        ("termux-boot.apk", "com.termux.boot"),
        ("termux-api.apk", "com.termux.api"),
    ]
    installed = adb_shell(adb, "pm list packages")
    orig_verify = adb_shell(adb, "settings get global verifier_verify_adb_installs")
    adb_shell(adb, "settings put global verifier_verify_adb_installs 0")
    for filename, pkg in apks:
        apk_path = REPO_ROOT / "apks" / filename
        if apk_path.is_file():
            if f"package:{pkg}" not in installed.splitlines():
                print(f"      -> Installing {filename}...")
                run_adb(adb, ["install", "-r", "-g", "--bypass-low-target-sdk-block", str(apk_path)])
            else:
                print(f"      -> {pkg} is already installed.")
    if orig_verify != "0":
        adb_shell(adb, "settings put global verifier_verify_adb_installs 1")

    # 3. Grant Storage & Battery Whitelist Permissions
    print("[3/5] Whitelisting Termux suite from Doze Battery Optimization & granting storage access...")
    for pkg in ("com.termux", "com.termux.boot", "com.termux.api"):
        adb_shell(adb, f"dumpsys deviceidle whitelist +{pkg}")
        adb_shell(adb, f"cmd appops set {pkg} RUN_IN_BACKGROUND allow")
        adb_shell(adb, f"cmd appops set {pkg} RUN_ANY_IN_BACKGROUND allow")
        adb_shell(adb, f"cmd appops set {pkg} WAKE_LOCK allow")
        adb_shell(adb, f"am set-standby-bucket {pkg} active")
    adb_shell(adb, "cmd appops set com.termux MANAGE_EXTERNAL_STORAGE allow")
    adb_shell(adb, "pm grant com.termux android.permission.READ_EXTERNAL_STORAGE")
    adb_shell(adb, "pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE")

    if args.debloat_server:
        print("\n[Optional] Running Headless Server Debloat (saving pre-change baseline first)...")
        if not (backup_dir / "packages-enabled.txt").is_file():
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / "packages-enabled.txt").write_text(
                adb_shell(adb, "pm list packages -e --user 0 | sort"), encoding="utf-8"
            )
            (backup_dir / "packages-disabled.txt").write_text(
                adb_shell(adb, "pm list packages -d --user 0 | sort"), encoding="utf-8"
            )
            (backup_dir / "settings-global.txt").write_text(
                adb_shell(adb, "settings list global | sort"), encoding="utf-8"
            )
            print(f"      -> Baseline saved to {backup_dir}")
        else:
            print(f"      -> Preserving existing baseline at {backup_dir}")

        disabled_count = 0
        for pkg in HEADLESS_DEBLOAT_PACKAGES:
            if pkg in PROTECTED_PACKAGES:
                continue
            out = adb_shell(adb, f"pm disable-user --user 0 {pkg}")
            if "disabled-user" in out:
                disabled_count += 1
        for cmd in (
            "svc bluetooth disable",
            "svc nfc disable",
            "settings put global window_animation_scale 0.5",
            "settings put global transition_animation_scale 0.5",
            "settings put global animator_duration_scale 0.5",
            "settings put global send_action_app_error 0",
            "settings put secure send_action_app_error 0",
            "pm trim-caches 999G",
        ):
            adb_shell(adb, cmd)
        print(f"      -> Disabled {disabled_count} unused packages, turned off BT/NFC, set 0.5x animations & trimmed caches.")
        print("      -> Roll back anytime with: python3 scripts/setup_android_host.py --restore-server")

    # 4. Inspect mounted storage / External USB Drive
    print("[4/5] Checking mounted storage volumes (/storage)...")
    volumes = [v.strip() for v in adb_shell(adb, "ls -1 /storage").splitlines() if v.strip()]
    print(f"      Mounted volumes: {', '.join(volumes)}")
    for v in volumes:
        if v not in ("emulated", "self"):
            ext_media = f"/storage/{v}/Android/data/com.termux/files/Media"
            print(f"      -> Detected External USB Drive ({v})! Creating {ext_media}/{{Movies,Series,Audiobooks}}...")
            adb_shell(adb, f"mkdir -p '{ext_media}/Movies' '{ext_media}/Series' '{ext_media}/Audiobooks'")

    # 5. Push Termux bootstrap script (normalize CRLF -> LF)
    print("[5/5] Pushing android-jellyfin-setup.sh to /sdcard/Download/android-jellyfin-setup.sh...")
    local_sh = REPO_ROOT / "device" / "android-jellyfin-setup.sh"
    temp_lf = REPO_ROOT / "device" / "android-jellyfin-setup.lf.sh"
    content = local_sh.read_text(encoding="utf-8").replace("\r\n", "\n")
    temp_lf.write_text(content, encoding="utf-8", newline="\n")
    try:
        run_adb(adb, ["push", str(temp_lf), "/sdcard/Download/android-jellyfin-setup.sh"], check=True)
    finally:
        temp_lf.unlink(missing_ok=True)

    adb_shell(adb, "am start -n com.termux/.app.TermuxActivity")

    print("\n========================================================")
    print("  HOST PROVISIONING COMPLETE!")
    print("  Inside Termux on the Android device, run:")
    print("    bash /sdcard/Download/android-jellyfin-setup.sh")
    print("========================================================\n")


if __name__ == "__main__":
    main()
