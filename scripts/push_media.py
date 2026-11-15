#!/usr/bin/env python3
"""
Cross-Platform Smart Differential Media Uploader (macOS / Linux / Windows)

1. Resolves local files, folders, or space/dot-insensitive wildcards.
2. Checks what files already exist on the Android Jellyfin server.
3. Skips already-uploaded files (saves bandwidth & time).
4. Uploads only missing/new files over SSH (port 8022) or ADB.

Examples:
    python3 scripts/push_media.py --category Series --show-name "Sample Show" " ~/Downloads/Sample Show S01*"
    python3 scripts/push_media.py --category Movies "~/Movies/Big Buck Bunny (2008).mkv"
    python3 scripts/push_media.py --category Audiobooks --show-name "Sample Audiobook" "~/Audiobooks/Sample*"
"""

import argparse
import glob
import os
import re
import shlex
import shutil
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


def resolve_local_files(patterns: list[str]) -> list[Path]:
    found: dict[str, Path] = {}
    for raw in patterns:
        expanded = os.path.expanduser(raw.strip())
        p = Path(expanded)
        matched_paths: list[Path] = []

        if p.is_dir():
            matched_paths.append(p)
        elif p.is_file():
            matched_paths.append(p)
        else:
            # Exact glob + space/dot-flexible glob
            for m in glob.glob(expanded):
                matched_paths.append(Path(m))
            parent = os.path.dirname(expanded)
            leaf = os.path.basename(expanded)
            flex_leaf = re.sub(r"[\s.]+", "*", leaf)
            flex_pattern = os.path.join(parent, flex_leaf) if parent else flex_leaf
            if flex_pattern != expanded:
                for m in glob.glob(flex_pattern):
                    matched_paths.append(Path(m))

        for mp in matched_paths:
            if mp.is_dir():
                for child in sorted(mp.rglob("*")):
                    if child.is_file():
                        found[str(child.resolve())] = child
            elif mp.is_file():
                found[str(mp.resolve())] = mp

    return list(found.values())


def main():
    cfg = load_config()
    parser = argparse.ArgumentParser(
        description="Differential media uploader from macOS / Linux / Windows to Android Jellyfin Server."
    )
    parser.add_argument("paths", nargs="+", help="Local file(s), folder(s), or wildcard pattern(s)")
    parser.add_argument(
        "--category",
        choices=["Movies", "Series", "Audiobooks"],
        default="Series",
        help="Target library category (default: Series)",
    )
    parser.add_argument(
        "--show-name",
        "--book-name",
        dest="show_name",
        default="",
        help="Show or Audiobook folder name on the server",
    )
    parser.add_argument("--host-ip", default=cfg["ANDROID_HOST_IP"], help="Android host LAN IP")
    parser.add_argument("--ssh-user", default=cfg["ANDROID_SSH_USER"], help="Termux SSH username")
    parser.add_argument("--ssh-port", type=int, default=int(cfg["ANDROID_SSH_PORT"]), help="Termux SSH port (default: 8022)")
    parser.add_argument("--use-adb", action="store_true", help="Push over ADB instead of SSH/SCP")
    parser.add_argument("--force", action="store_true", help="Overwrite files even if already on server")
    args = parser.parse_args()

    local_files = resolve_local_files(args.paths)
    if not local_files:
        print(f"[!] No matching local files found for: {', '.join(args.paths)}", file=sys.stderr)
        sys.exit(1)

    if args.show_name:
        remote_dir = f"media/Audiobooks/{args.show_name}" if args.category == "Audiobooks" else f"media/Series/{args.show_name}"
    else:
        remote_dir = f"media/{args.category}"

    remote_dir_quoted = shlex.quote(remote_dir)
    target = f"{args.ssh_user}@{args.host_ip}" if args.ssh_user else args.host_ip

    print("\n========================================================")
    print("  Android Media Server Smart Differential Sync")
    print("========================================================\n")

    existing_files: set[str] = set()
    if not args.use_adb:
        subprocess.run(
            ["ssh", "-p", str(args.ssh_port), "-o", "StrictHostKeyChecking=no", target, f"mkdir -p {remote_dir_quoted}"],
            capture_output=True,
        )
        if not args.force:
            print(f"[*] Checking existing files on server in ~/{remote_dir}...")
            res = subprocess.run(
                ["ssh", "-p", str(args.ssh_port), "-o", "StrictHostKeyChecking=no", target, f"ls -1 {remote_dir_quoted}"],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and res.stdout:
                existing_files = {line.strip() for line in res.stdout.splitlines() if line.strip()}

    uploaded = 0
    skipped = 0

    for fpath in local_files:
        fn = fpath.name
        size_mb = round(fpath.stat().st_size / (1024 * 1024), 1)
        if fn in existing_files and not args.force:
            print(f"  [-] Skipping '{fn}' ({size_mb} MB) - already on server!")
            skipped += 1
            continue

        print(f"\n[*] Uploading '{fn}' ({size_mb} MB) -> ~/{remote_dir}/...")
        if args.use_adb:
            adb = shutil.which("adb") or "adb"
            df_res = subprocess.run(
                [adb, "shell", "df 2>/dev/null | awk '/\\/mnt\\/media_rw\\// {print $6; exit}'"],
                capture_output=True,
                text=True,
            )
            usb_path = (df_res.stdout or "").strip()
            adb_dest = f"{usb_path}/Media/Series/{args.show_name}/" if usb_path else f"/sdcard/Media/Series/{args.show_name}/"
            rc = subprocess.run([adb, "push", str(fpath), adb_dest]).returncode
        else:
            rc = subprocess.run(
                [
                    "scp",
                    "-O",
                    "-P",
                    str(args.ssh_port),
                    "-o",
                    "ServerAliveInterval=15",
                    "-o",
                    "ServerAliveCountMax=6",
                    "-o",
                    "TCPKeepAlive=yes",
                    "-o",
                    "StrictHostKeyChecking=no",
                    str(fpath),
                    f"{target}:{remote_dir_quoted}/",
                ]
            ).returncode

        if rc == 0:
            print(f"  [+] Uploaded '{fn}' successfully!")
            uploaded += 1
        else:
            print(f"  [!] Failed uploading '{fn}'")

    print("\n========================================================")
    print(f"  Summary: {uploaded} uploaded, {skipped} skipped (already present).")
    print("========================================================\n")


if __name__ == "__main__":
    main()
