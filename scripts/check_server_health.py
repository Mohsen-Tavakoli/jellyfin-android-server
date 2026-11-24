#!/usr/bin/env python3
"""
Cross-Platform Health, USB-PD Power & Crash Diagnostics for Android Jellyfin Server
(macOS / Linux / Windows — zero external dependencies)

Checks:
  1. Service reachability (Jellyfin HTTP :8096, OpenSSH :8022).
  2. Remote storage & mount health over SSH (detects USB fallback mismatches).
  3. Battery, USB-C PD/PPS power telemetry, boot/shutdown reasons, dropbox watchdogs/panics,
     and Phantom Process Killer settings over ADB.
"""

import argparse
import concurrent.futures
import datetime
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    cfg = {
        "ANDROID_HOST_IP": os.environ.get("ANDROID_HOST_IP", "192.168.1.100"),
        "ANDROID_SSH_USER": os.environ.get("ANDROID_SSH_USER", "u0_a300"),
        "ANDROID_SSH_PORT": os.environ.get("ANDROID_SSH_PORT", "8022"),
        "JELLYFIN_PORT": os.environ.get("JELLYFIN_PORT", "8096"),
    }
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


def test_port(ip: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def scan_adb_port(ip: str, start_port: int = 30000, end_port: int = 49999, timeout: float = 0.25) -> int:
    def probe(p: int) -> int:
        return p if test_port(ip, p, timeout) else 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=120) as pool:
        futures = [pool.submit(probe, p) for p in range(start_port, end_port + 1)]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res > 0:
                pool.shutdown(wait=False, cancel_futures=True)
                return res
    return 0


def run_ssh(user: str, ip: str, port: int, remote_script: str) -> str:
    res = subprocess.run(
        [
            "ssh",
            "-p",
            str(port),
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
            f"{user}@{ip}",
            "bash -s",
        ],
        input=remote_script,
        text=True,
        capture_output=True,
    )
    return (res.stdout or "").strip()


def run_adb_shell(adb: str, target: str, remote_script: str) -> str:
    res = subprocess.run(
        [adb, "-s", target, "shell"],
        input=remote_script,
        text=True,
        capture_output=True,
    )
    return (res.stdout or "").strip()


def format_epoch(epoch_str: str) -> str:
    try:
        ts = int(epoch_str.strip())
        dt = datetime.datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, OSError):
        return epoch_str


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Health, USB-PD power, and crash diagnostics for Android Jellyfin server.")
    parser.add_argument("--host-ip", default=cfg["ANDROID_HOST_IP"], help="Android host LAN IP")
    parser.add_argument("--ssh-user", default=cfg["ANDROID_SSH_USER"], help="Termux SSH username")
    parser.add_argument("--ssh-port", type=int, default=int(cfg["ANDROID_SSH_PORT"]), help="Termux SSH port (default: 8022)")
    parser.add_argument("--jellyfin-port", type=int, default=int(cfg["JELLYFIN_PORT"]), help="Jellyfin HTTP port (default: 8096)")
    parser.add_argument("--adb-port", type=int, default=0, help="Explicit ADB TCP port (default: try 5555)")
    parser.add_argument("--scan-adb", action="store_true", help="Scan Wireless Debugging ports (30000-49999) if 5555 is closed")
    args = parser.parse_args()

    print("\n========================================================")
    print("  Android 4K Media Server Health & Power Diagnostics")
    print("========================================================\n")

    # 1. Service Reachability
    jf_up = test_port(args.host_ip, args.jellyfin_port, 1.0)
    ssh_up = test_port(args.host_ip, args.ssh_port, 1.0)
    print(f"[1/3] Services on {args.host_ip}:")
    print(f"      Jellyfin (:{args.jellyfin_port}) : {'ONLINE' if jf_up else 'OFFLINE'}")
    print(f"      OpenSSH  (:{args.ssh_port}) : {'ONLINE' if ssh_up else 'OFFLINE'}")

    # 2. SSH Storage & Process Check
    print("\n[2/3] Storage & Process Check (SSH):")
    if ssh_up:
        ssh_script = (
            'echo "UPTIME=$(uptime)"\n'
            'echo "MEDIA_TARGET=$(readlink -f ~/media 2>/dev/null || echo missing)"\n'
            'echo "PREFER_USB=$([ -f ~/.prefer-usb-storage ] && echo 1 || echo 0)"\n'
            'echo "USB_MOUNT=$(df 2>/dev/null | awk \'/\\/mnt\\/media_rw\\// {print $6; exit}\')"\n'
            'echo "JELLYFIN_PID=$(pgrep -f \'jellyfin\\.dll\' | head -n1)"\n'
            'echo "DF_LINE=$(df -h ~/media 2>/dev/null | tail -n1)"\n'
        )
        out = run_ssh(args.ssh_user, args.host_ip, args.ssh_port, ssh_script)
        kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        print(f"      Uptime       : {kv.get('UPTIME', 'unknown')}")
        print(f"      Jellyfin PID : {kv.get('JELLYFIN_PID') or 'NOT RUNNING'}")
        print(f"      ~/media ->   : {kv.get('MEDIA_TARGET', 'unknown')}")
        print(f"      Disk Usage   : {kv.get('DF_LINE', 'unknown')}")
        if kv.get("PREFER_USB") == "1" and kv.get("MEDIA_TARGET", "").startswith("/sdcard"):
            usb_mnt = kv.get("USB_MOUNT")
            print("      [!] WARNING: Server fell back to internal storage (/sdcard/Media) even though USB storage is preferred!")
            if usb_mnt:
                print(f"          USB drive IS mounted at {usb_mnt}. Run '~/start-media-server.sh --restart' to bind it.")
    else:
        print("      Skipped (SSH unreachable).")

    # 3. ADB Power, USB-PD & Crash Diagnostics
    print("\n[3/3] Battery, USB-C PD Power & Crash Diagnostics (ADB):")
    adb = shutil.which("adb")
    if not adb:
        print("      Skipped ('adb' not found in PATH).")
        return

    adb_port = args.adb_port
    if adb_port <= 0:
        if test_port(args.host_ip, 5555, 0.8):
            adb_port = 5555
        elif args.scan_adb:
            print(f"      Scanning Wireless Debugging ports (30000-49999) on {args.host_ip}...")
            adb_port = scan_adb_port(args.host_ip)

    if adb_port <= 0:
        print("      Skipped (ADB port 5555 closed; pass --adb-port <PORT> or --scan-adb to inspect USB-PD & crash logs).")
        return

    target = f"{args.host_ip}:{adb_port}"
    subprocess.run([adb, "connect", target], capture_output=True, text=True)

    adb_script = """
echo "===BATTERY==="
dumpsys battery
echo "===BATT_SYSFS==="
for f in cycle_count charge_full charge_full_design health; do
    v=$(cat "/sys/class/power_supply/battery/$f" 2>/dev/null)
    [ -n "$v" ] && echo "$f=$v"
done
echo "===USB_PD==="
for f in /sys/class/power_supply/usb/online /sys/class/power_supply/usb/voltage_now /sys/class/power_supply/usb/current_now /sys/class/power_supply/usb/current_max /sys/class/power_supply/tcpm-source-psy-*/online /sys/class/power_supply/tcpm-source-psy-*/usb_type /sys/class/power_supply/tcpm-source-psy-*/voltage_max /sys/class/power_supply/tcpm-source-psy-*/current_max; do
    if [ -e "$f" ]; then
        echo "$(basename "$(dirname "$f")")/$(basename "$f")=$(cat "$f" 2>/dev/null)"
    fi
done
echo "===PROPS==="
echo "last_boot_reason=$(getprop sys.boot.reason.last)"
echo "last_fatal_epoch=$(getprop persist.init.svc.last_fatal_reboot_epoch)"
echo "max_phantom=$(device_config get activity_manager max_phantom_processes 2>/dev/null)"
echo "monitor_phantom=$(settings get global settings_enable_monitor_phantom_procs 2>/dev/null)"
echo "===REASON_HISTORY==="
getprop persist.sys.boot.reason.history
echo "===DROPBOX==="
dumpsys dropbox 2>/dev/null | grep -E "system_server_watchdog|SYSTEM_LAST_KMSG|SYSTEM_RESTART|SYSTEM_BOOT" | tail -n 12
"""
    raw = run_adb_shell(adb, target, adb_script)
    if not raw:
        print(f"      [!] Could not query ADB target {target}.")
        return

    sections: dict[str, list[str]] = {}
    current = ""
    for line in raw.splitlines():
        m = re.match(r"^===([A-Z_]+)===$", line.strip())
        if m:
            current = m.group(1)
            sections[current] = []
        elif current:
            sections[current].append(line)

    # Parse Battery
    batt = {}
    for line in sections.get("BATTERY", []):
        if ":" in line:
            k, v = line.split(":", 1)
            batt[k.strip()] = v.strip()
    batt_sys = dict(l.split("=", 1) for l in sections.get("BATT_SYSFS", []) if "=" in l)
    level = int(batt.get("level", "-1")) if batt.get("level", "").isdigit() else -1
    temp_c = int(batt.get("temperature", "0")) / 10.0 if batt.get("temperature", "").lstrip("-").isdigit() else 0.0
    ac_on = batt.get("AC powered") == "true"
    usb_on = batt.get("USB powered") == "true"
    wl_on = batt.get("Wireless powered") == "true"
    powered_str = ", ".join(p for p, ok in [("AC", ac_on), ("USB", usb_on), ("Wireless", wl_on)] if ok) or "NONE (Discharging)"

    print(f"      Battery      : {level}% | Power: {powered_str} | Temp: {temp_c:.1f} C | Voltage: {batt.get('voltage', '?')} mV")
    if batt_sys.get("cycle_count") or batt_sys.get("charge_full"):
        cap_pct = ""
        if batt_sys.get("charge_full", "").isdigit() and batt_sys.get("charge_full_design", "").isdigit():
            pct = 100.0 * int(batt_sys["charge_full"]) / max(1, int(batt_sys["charge_full_design"]))
            cap_pct = f" ({pct:.1f}% design capacity)"
        print(f"      Health       : {batt_sys.get('health', 'unknown')} | Cycles: {batt_sys.get('cycle_count', '?')}{cap_pct}")

    # Parse USB-PD
    usb_pd = dict(l.split("=", 1) for l in sections.get("USB_PD", []) if "=" in l)
    usb_online = usb_pd.get("usb/online", "")
    usb_v = int(usb_pd.get("usb/voltage_now", "0")) / 1_000_000.0 if usb_pd.get("usb/voltage_now", "").isdigit() else 0.0
    usb_ma = int(usb_pd.get("usb/current_now", "0")) / 1_000.0 if usb_pd.get("usb/current_now", "").lstrip("-").isdigit() else 0.0
    tcpm_type = next((v for k, v in usb_pd.items() if k.endswith("/usb_type")), "unknown")
    if usb_pd:
        print(f"      USB-C PD     : online={usb_online or '?'} | type={tcpm_type} | VBUS={usb_v:.2f}V | current={usb_ma:.0f} mA")
        if usb_v >= 4.5 and (usb_online == "0" or (abs(usb_ma) < 1 and 0 <= level < 80)):
            print("      [!] WARNING: USB-C PD CHARGING LOCKOUT DETECTED!")
            print("          Voltage is present on VBUS, but the phone is drawing 0 mA (usb/online=0).")
            print("          Common cause: 30W PPS charger + USB-C PD hub + external HDD exceeding brick headroom.")
            print("          Fix: Upgrade to a 45W-65W+ USB-C PD brick or use a self-powered USB hub.")

    # Parse Props & Boot/Crash History
    props = dict(l.split("=", 1) for l in sections.get("PROPS", []) if "=" in l)
    print(f"      Phantom Proc : max={props.get('max_phantom', '?')}, monitor={props.get('monitor_phantom', '?')}")
    if props.get("last_boot_reason"):
        print(f"      Last Boot    : {props['last_boot_reason']}")
    if props.get("last_fatal_epoch"):
        print(f"      Last Fatal   : {format_epoch(props['last_fatal_epoch'])} (init fatal service reboot)")

    reason_hist = [l.strip() for l in sections.get("REASON_HISTORY", []) if l.strip()]
    if reason_hist:
        print("      Boot History :")
        for entry in reason_hist[:5]:
            parts = entry.rsplit(",", 1)
            if len(parts) == 2 and parts[1].isdigit():
                print(f"        - {format_epoch(parts[1])}  ({parts[0]})")
            else:
                print(f"        - {entry}")

    dropbox_lines = [l.strip() for l in sections.get("DROPBOX", []) if l.strip()]
    if dropbox_lines:
        print("      Recent Crash/Boot Events (dropbox):")
        for l in dropbox_lines[-8:]:
            print(f"        - {l}")
    print("")


if __name__ == "__main__":
    main()
