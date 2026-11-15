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

    # 1. Disable Phantom Process Killer
    print("[1/5] Disabling Android Phantom Process Killer for 24/7 background servers...")
    adb_shell(adb, "/system/bin/device_config set_sync_disabled_for_tests persistent")
    adb_shell(adb, "/system/bin/device_config put activity_manager max_phantom_processes 2147483647")
    adb_shell(adb, "settings put global settings_enable_monitor_phantom_procs false")
    print("      -> max_phantom_processes set to unlimited (2147483647).")

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
    adb_shell(adb, "cmd appops set com.termux MANAGE_EXTERNAL_STORAGE allow")
    adb_shell(adb, "pm grant com.termux android.permission.READ_EXTERNAL_STORAGE")
    adb_shell(adb, "pm grant com.termux android.permission.WRITE_EXTERNAL_STORAGE")

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
