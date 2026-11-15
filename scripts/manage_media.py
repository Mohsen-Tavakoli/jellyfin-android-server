#!/usr/bin/env python3
"""
Cross-Platform Storage Manager for Android Jellyfin Media Server (macOS / Linux / Windows)

Examples:
    python3 scripts/manage_media.py --action space
    python3 scripts/manage_media.py --action list
    python3 scripts/manage_media.py --action list --filter "Sample Show"
    python3 scripts/manage_media.py --action remove --target "Sample Show S01E01"
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    cfg = {
        "ANDROID_HOST_IP": os.environ.get("ANDROID_HOST_IP", "192.168.1.100"),
        "ANDROID_SSH_USER": os.environ.get("ANDROID_SSH_USER", "u0_a300"),
        "ANDROID_SSH_PORT": os.environ.get("ANDROID_SSH_PORT", "8022"),
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


def ssh_capture(target: str, port: int, remote_cmd: str) -> str:
    res = subprocess.run(
        ["ssh", "-p", str(port), "-o", "StrictHostKeyChecking=no", target, remote_cmd],
        capture_output=True,
        text=True,
    )
    return (res.stdout or "").strip()


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Manage media storage on the Android Jellyfin host.")
    parser.add_argument(
        "--action",
        choices=["list", "space", "remove"],
        default="list",
        help="Action to perform: list, space, or remove (default: list)",
    )
    parser.add_argument("--filter", default="", help="Optional title/substring filter for --action list")
    parser.add_argument("--target", default="", help="Pattern of file(s) to delete for --action remove")
    parser.add_argument("--host-ip", default=cfg["ANDROID_HOST_IP"], help="Android host LAN IP")
    parser.add_argument("--ssh-user", default=cfg["ANDROID_SSH_USER"], help="Termux SSH username")
    parser.add_argument("--ssh-port", type=int, default=int(cfg["ANDROID_SSH_PORT"]), help="Termux SSH port (default: 8022)")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt when removing files")
    args = parser.parse_args()

    ssh_target = f"{args.ssh_user}@{args.host_ip}"

    print("\n========================================================")
    print(f"  Android Media Storage Manager ({args.action.capitalize()})")
    print("========================================================\n")

    if args.action == "space":
        print("[*] Checking storage capacity on Android host...")
        out = ssh_capture(
            ssh_target,
            args.ssh_port,
            "df -h ~/media; echo ''; du -sh ~/media/* ~/media/Series/* ~/media/Audiobooks/* 2>/dev/null",
        )
        print(out)
        return

    if args.action == "list":
        raw = ssh_capture(
            ssh_target,
            args.ssh_port,
            "cd ~/media && find Movies Series Audiobooks -type f 2>/dev/null | sort",
        )
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if args.filter:
            flex = re.sub(r"[\s.]+", ".*", args.filter)
            lines = [line for line in lines if re.search(flex, line, re.IGNORECASE)]

        if not lines:
            print("  No matching media files found on server.")
        else:
            for line in lines:
                if line.startswith("Movies/"):
                    print(f"  [Movie]     {line}")
                elif line.startswith("Audiobooks/"):
                    print(f"  [Audiobook] {line}")
                else:
                    print(f"  [Series]    {line}")
            print(f"\n  Total files matched: {len(lines)}")

        print("\n[*] Folder sizes:")
        print(
            ssh_capture(
                ssh_target,
                args.ssh_port,
                "du -sh ~/media/Movies ~/media/Series/* ~/media/Audiobooks/* 2>/dev/null",
            )
        )
        return

    if args.action == "remove":
        if not args.target:
            print("[!] Please specify --target (e.g. --target 'Sample Show S01E01')", file=sys.stderr)
            sys.exit(1)

        flex = re.sub(r"[\s.*]+", ".*", args.target)
        raw = ssh_capture(
            ssh_target,
            args.ssh_port,
            "cd ~/media && find Movies Series Audiobooks -type f 2>/dev/null | sort",
        )
        matches = [
            line.strip()
            for line in raw.splitlines()
            if line.strip() and re.search(flex, line.strip(), re.IGNORECASE)
        ]

        if not matches:
            print(f"  [!] No files on server matched '{args.target}'.")
            return

        print(f"The following file(s) on the server matched '{args.target}':")
        for m in matches:
            print(f"  - {m}")

        if not args.force:
            ans = input(f"\nAre you sure you want to PERMANENTLY delete these {len(matches)} file(s)? (y/N): ")
            if not ans.strip().lower().startswith("y"):
                print("Aborted.")
                return

        for m in matches:
            quoted = shlex.quote(f"media/{m}")
            rc = subprocess.run(
                ["ssh", "-p", str(args.ssh_port), "-o", "StrictHostKeyChecking=no", ssh_target, f"rm -f {quoted}"]
            ).returncode
            if rc == 0:
                print(f"  [+] Deleted: {m}")
            else:
                print(f"  [!] Failed to delete: {m}")

        subprocess.run(
            [
                "ssh",
                "-p",
                str(args.ssh_port),
                "-o",
                "StrictHostKeyChecking=no",
                ssh_target,
                "find media/Series -mindepth 1 -type d -empty -delete 2>/dev/null",
            ],
            capture_output=True,
        )


if __name__ == "__main__":
    main()
