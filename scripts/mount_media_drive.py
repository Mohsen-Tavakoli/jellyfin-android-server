#!/usr/bin/env python3
"""
Cross-Platform SSH-Tunneled WebDAV Media Drive Mounter (macOS / Linux / Windows)

Starts a localhost-bound WebDAV server (`rclone serve webdav`) on the Android host,
forwards it over SSH to `http://127.0.0.1:8081`, and mounts it natively in:
  - macOS Finder (`osascript` mount volume "http://127.0.0.1:8081")
  - Windows File Explorer (`net use Z: http://127.0.0.1:8081`)
  - Linux (`gio mount dav://127.0.0.1:8081`)
"""

import argparse
import os
import platform
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    cfg = {
        "ANDROID_HOST_IP": os.environ.get("ANDROID_HOST_IP", "192.168.1.100"),
        "ANDROID_SSH_USER": os.environ.get("ANDROID_SSH_USER", "u0_a300"),
        "ANDROID_SSH_PORT": os.environ.get("ANDROID_SSH_PORT", "8022"),
        "WEBDAV_LOCAL_PORT": os.environ.get("WEBDAV_LOCAL_PORT", "8081"),
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


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Mount Android media storage via SSH-tunneled WebDAV.")
    parser.add_argument("--host-ip", default=cfg["ANDROID_HOST_IP"], help="Android host LAN IP")
    parser.add_argument("--ssh-user", default=cfg["ANDROID_SSH_USER"], help="Termux SSH username")
    parser.add_argument("--ssh-port", type=int, default=int(cfg["ANDROID_SSH_PORT"]), help="Termux SSH port (default: 8022)")
    parser.add_argument("--local-port", type=int, default=int(cfg["WEBDAV_LOCAL_PORT"]), help="Local port for WebDAV tunnel (default: 8081)")
    parser.add_argument("--drive-letter", default="Z", help="Windows drive letter (default: Z)")
    parser.add_argument("--unmount", action="store_true", help="Unmount WebDAV share and stop tunnel")
    args = parser.parse_args()

    ssh_target = f"{args.ssh_user}@{args.host_ip}"
    system = platform.system().lower()
    url = f"http://127.0.0.1:{args.local_port}"

    if args.unmount:
        print("[*] Stopping WebDAV server on Android host and closing tunnel...")
        if system == "windows":
            drive = f"{args.drive_letter.rstrip(':')}:"
            subprocess.run(["net", "use", drive, "/delete", "/y"], capture_output=True)
        elif system == "linux":
            subprocess.run(["gio", "mount", "-u", f"dav://127.0.0.1:{args.local_port}"], capture_output=True)
        subprocess.run(
            ["ssh", "-p", str(args.ssh_port), ssh_target, "pkill -f 'rclone serve webdav' 2>/dev/null || true"],
            capture_output=True,
        )
        print("[+] Unmounted cleanly.")
        return

    print("[1/2] Starting localhost-bound WebDAV server on Android host (tunneled over SSH)...")
    subprocess.run(
        [
            "ssh",
            "-p",
            str(args.ssh_port),
            ssh_target,
            "pkill -f 'rclone serve webdav' 2>/dev/null || true; nohup rclone serve webdav ~/media/ --addr 127.0.0.1:8081 >/dev/null 2>&1 &",
        ]
    )

    subprocess.Popen(
        [
            "ssh",
            "-N",
            "-L",
            f"127.0.0.1:{args.local_port}:127.0.0.1:8081",
            "-p",
            str(args.ssh_port),
            "-o",
            "ServerAliveInterval=15",
            ssh_target,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2.0)

    print(f"[2/2] Mounting {url}...")
    if system == "darwin":
        subprocess.run(["osascript", "-e", f'tell application "Finder" to mount volume "{url}"'])
        print(f"[+] Mounted {url} in macOS Finder!")
    elif system == "windows":
        drive = f"{args.drive_letter.rstrip(':')}:"
        subprocess.run(["net", "use", drive, "/delete", "/y"], capture_output=True)
        rc = subprocess.run(["net", "use", drive, url, "/persistent:no"]).returncode
        if rc == 0:
            print(f"[+] Mounted at {drive} in Windows File Explorer!")
        else:
            print(f"[i] WebDAV tunnel is active at {url}")
    else:
        subprocess.run(["gio", "mount", f"dav://127.0.0.1:{args.local_port}"], capture_output=True)
        print(f"[+] WebDAV tunnel is active at {url} (dav://127.0.0.1:{args.local_port})")


if __name__ == "__main__":
    main()
