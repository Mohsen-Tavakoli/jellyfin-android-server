#!/usr/bin/env python3
"""
Cross-Platform Self-Healing Launcher for Android 4K Jellyfin Media Server (macOS / Linux / Windows)

Automates all recovery levels:
- Level 1: Checks if Jellyfin is already running (Port 8096).
- Level 2: Checks if OpenSSH is running (Port 8022) and launches Jellyfin remotely.
- Level 3: If SSH is down, connects via ADB (Port 5555 or parallel scan of Wireless Debugging
           ports 30000-49999), wakes the phone, starts Termux + sshd, and launches Jellyfin.
- Level 4: Polls port 8096 until the Jellyfin web dashboard is online.
"""

import argparse
import concurrent.futures
import os
import shutil
import socket
import subprocess
import sys
import time
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


def test_port(ip: str, port: int, timeout: float = 0.8) -> bool:
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


def find_adb() -> str:
    return shutil.which("adb") or "adb"


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Self-healing launcher for Android Jellyfin Media Server.")
    parser.add_argument("--host-ip", default=cfg["ANDROID_HOST_IP"], help="Android host LAN IP")
    parser.add_argument("--ssh-user", default=cfg["ANDROID_SSH_USER"], help="Termux SSH username")
    parser.add_argument("--ssh-port", type=int, default=int(cfg["ANDROID_SSH_PORT"]), help="Termux SSH port (default: 8022)")
    parser.add_argument("--jellyfin-port", type=int, default=int(cfg["JELLYFIN_PORT"]), help="Jellyfin HTTP port (default: 8096)")
    parser.add_argument("--adb-port", type=int, default=0, help="Explicit ADB TCP port (optional)")
    args = parser.parse_args()

    print("\n========================================================")
    print("  Android 4K Media Server Self-Healing Launcher")
    print("========================================================\n")

    # LEVEL 1: Check Jellyfin HTTP port
    print(f"[Level 1] Checking if Jellyfin (port {args.jellyfin_port}) is already active on {args.host_ip}...")
    if test_port(args.host_ip, args.jellyfin_port, 1.0):
        print("[+] Jellyfin is ALREADY LIVE and running smoothly!")
        print(f"    Web / TV Dashboard: http://{args.host_ip}:{args.jellyfin_port}\n")
        return

    # LEVEL 2: Check SSH daemon
    print(f"[Level 2] Checking SSH daemon (port {args.ssh_port})...")
    if test_port(args.host_ip, args.ssh_port, 1.0):
        print("[+] SSH is up! Starting Jellyfin via SSH...")
        subprocess.run(
            [
                "ssh",
                "-p",
                str(args.ssh_port),
                "-o",
                "ConnectTimeout=5",
                "-o",
                "StrictHostKeyChecking=no",
                f"{args.ssh_user}@{args.host_ip}",
                "nohup ~/start-media-server.sh > ~/media-server.log 2>&1 &",
            ]
        )
    else:
        # LEVEL 3: Wake & recover via ADB
        print("[-] SSH is not listening. Initiating ADB auto-recovery...")
        adb_port = args.adb_port
        if adb_port <= 0:
            if test_port(args.host_ip, 5555, 0.8):
                adb_port = 5555
            else:
                print(f"[*] Scanning Android Wireless Debugging range (30000-49999) on {args.host_ip}...")
                adb_port = scan_adb_port(args.host_ip)

        if adb_port <= 0:
            print(f"\n[!] Could not reach SSH ({args.ssh_port}) or ADB on {args.host_ip}.")
            print("    Open Termux once on the phone screen OR enable Wireless Debugging in Developer Options.\n")
            sys.exit(1)

        adb = find_adb()
        print(f"[+] Connecting via ADB on {args.host_ip}:{adb_port}...")
        subprocess.run([adb, "connect", f"{args.host_ip}:{adb_port}"], capture_output=True)

        print("[*] Waking device and launching Termux + sshd + Jellyfin...")
        subprocess.run([adb, "shell", "input keyevent KEYCODE_WAKEUP"], capture_output=True)
        subprocess.run([adb, "shell", "am start -n com.termux/.app.TermuxActivity"], capture_output=True)
        time.sleep(1.0)
        subprocess.run([adb, "shell", "input keyevent 66"], capture_output=True)
        subprocess.run([adb, "shell", "input text 'sshd'"], capture_output=True)
        subprocess.run([adb, "shell", "input keyevent 66"], capture_output=True)
        time.sleep(0.6)
        subprocess.run([adb, "tcpip", "5555"], capture_output=True)
        subprocess.run(
            [adb, "shell", "input text 'nohup ~/start-media-server.sh > ~/media-server.log 2>&1 &'"],
            capture_output=True,
        )
        subprocess.run([adb, "shell", "input keyevent 66"], capture_output=True)

    # LEVEL 4: Health poll
    print(f"\n[*] Waiting for Jellyfin to come online (polling port {args.jellyfin_port})...")
    started = False
    for i in range(1, 16):
        sys.stdout.write(f"    Checking status ({i}/15)...")
        sys.stdout.flush()
        if test_port(args.host_ip, args.jellyfin_port, 1.5):
            print(" UP!")
            started = True
            break
        print(" starting...")
        time.sleep(1.0)

    if started:
        print("\n========================================================")
        print("  SUCCESS: Android 4K Media Server is ONLINE!")
        print(f"  Jellyfin Dashboard : http://{args.host_ip}:{args.jellyfin_port}")
        print(f"  SSH Daemon ({args.ssh_port})  : active (ready for media uploads)")
        print("========================================================\n")
    else:
        print("\n[!] Server process dispatched. Still initializing database/transcoder.")
        print(f"    Check dashboard shortly at: http://{args.host_ip}:{args.jellyfin_port}\n")


if __name__ == "__main__":
    main()
