#!/usr/bin/env python3
"""
Android / Pixel 4K Jellyfin Media Server Bootstrap (Python version for Termux ARM64)

Give a retired Android phone a second life as a silent, ultra-low-power
(~3W idle) 24/7 Jellyfin media server without root.

Installs & Configures:
  1. OpenSSH Server (Port 8022) + Rclone (for optional SSH-tunneled WebDAV)
  2. Automatic External USB-C Drive detection (with internal storage fallback)
  3. Debian ARM64 (proot-distro) + Official Jellyfin Media Server (Port 8096)
  4. ~/start-media-server.sh & Termux:Boot auto-start script
"""

import getpass
import os
import re
import shutil
import subprocess
from pathlib import Path


def run(cmd: list[str] | str, check: bool = True, shell: bool = False):
    return subprocess.run(cmd, check=check, shell=shell)


def capture(cmd: str) -> str:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (res.stdout or "").strip()


def detect_usb_uuid() -> str:
    storage = Path("/storage")
    if not storage.is_dir():
        return ""
    for entry in sorted(storage.iterdir()):
        if entry.name not in ("emulated", "self", "*") and entry.is_dir():
            return entry.name
    return ""


def detect_lan_ip() -> str:
    ip = capture("ip -4 addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1")
    if not ip:
        ip = capture("ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"src\") print $(i+1)}'")
    return ip


def main():
    print("========================================================")
    print("  Android 4K Jellyfin Media Server Installer (Python)")
    print("========================================================")

    # 1. Acquire wake-lock
    if shutil.which("termux-wake-lock"):
        run(["termux-wake-lock"], check=False)

    # 2. Install Termux server dependencies
    print("[1/5] Installing Termux server dependencies (openssh, proot-distro, rclone, rsync, tmux)...")
    run('pkg update -y -o Dpkg::Options::="--force-confnew"', shell=True)
    run('pkg upgrade -y -o Dpkg::Options::="--force-confnew"', shell=True)
    run("pkg install -y openssh proot-distro rclone rsync tmux iproute2 procps curl", shell=True)

    # 3. Detect External USB-C Drive
    print("[2/5] Detecting External USB-C Drive...")
    usb_uuid = detect_usb_uuid()
    if usb_uuid:
        print(f"  -> Found External USB Drive: /storage/{usb_uuid}")
        media_root = Path(f"/storage/{usb_uuid}/Android/data/com.termux/files/Media")
    else:
        print("  -> No external USB drive currently mounted. Using internal storage (/sdcard/Media).")
        media_root = Path("/sdcard/Media")

    for sub in ("Movies", "Series", "Audiobooks"):
        (media_root / sub).mkdir(parents=True, exist_ok=True)

    home = Path.home()
    media_link = home / "media"
    if media_link.is_symlink() or media_link.exists():
        media_link.unlink(missing_ok=True)
    media_link.symlink_to(media_root)
    print(f"  -> Media folders ready at: {media_root}/{{Movies,Series,Audiobooks}} (symlinked to ~/media)")

    # 4. Start OpenSSH Server (Port 8022)
    print("[3/5] Starting OpenSSH Server on port 8022...")
    if not capture("pgrep -x sshd"):
        run(["sshd"], check=False)

    user_name = getpass.getuser()
    ip_addr = detect_lan_ip()

    # 5. Install Debian ARM64 & Official Jellyfin Server
    print("[4/5] Setting up Debian ARM64 container & Jellyfin Media Server...")
    distro_list = capture("proot-distro list")
    if not re.search(r"debian.*installed", distro_list):
        run(["proot-distro", "install", "debian"])

    debian_setup = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl gnupg apt-transport-https ca-certificates locales

if ! command -v jellyfin >/dev/null 2>&1; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg --yes
    VERSION_CODENAME=$(awk -F"=" '/^VERSION_CODENAME=/{ print $NF }' /etc/os-release)
    cat <<EOF >/etc/apt/sources.list.d/jellyfin.sources
Types: deb
URIs: https://repo.jellyfin.org/debian
Suites: ${VERSION_CODENAME}
Components: main
Architectures: arm64
Signed-By: /etc/apt/keyrings/jellyfin.gpg
EOF
    apt-get update -y
    apt-get install -y jellyfin
fi
"""
    run(["proot-distro", "login", "debian", "--", "bash", "-c", debian_setup])

    # 6. Create ~/start-media-server.sh and Termux:Boot script
    print("[5/5] Creating ~/start-media-server.sh launcher...")
    start_script = home / "start-media-server.sh"
    start_script.write_text(
        """#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true

USB_PATH=""
for base_dir in /mnt/media_rw /storage; do
    for dir in "$base_dir"/*; do
        base=$(basename "$dir")
        if [[ "$base" != "emulated" && "$base" != "self" && "$base" != "*" && -d "$dir" ]]; then
            USB_PATH="$dir"
            break 2
        fi
    done
done
if [[ -z "$USB_PATH" ]]; then
    USB_PATH=$(df 2>/dev/null | awk '/\\/mnt\\/media_rw\\// {print $6; exit}')
fi

if [[ -n "$USB_PATH" && -d "$USB_PATH" ]]; then
    MEDIA_ROOT="$USB_PATH/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks" 2>/dev/null || {
        MEDIA_ROOT="$USB_PATH/Android/data/com.termux/files/Media"
        mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
    }
    echo "[+] Mounted External USB Drive: $MEDIA_ROOT"
else
    MEDIA_ROOT="/sdcard/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
    echo "[i] Using Internal Storage: $MEDIA_ROOT"
fi
ln -sfn "$MEDIA_ROOT" "$HOME/media"

pgrep -x "sshd" >/dev/null || sshd

IP_ADDR=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
echo "========================================================"
echo "  ANDROID 4K JELLYFIN MEDIA SERVER ACTIVE"
echo "  Jellyfin Web / TV URL : http://${IP_ADDR:-<device-ip>}:8096"
echo "  SSH / SFTP Upload     : ssh -p 8022 $(whoami)@${IP_ADDR:-<device-ip>}"
echo "  Media Directory       : $MEDIA_ROOT"
echo "========================================================"

proot-distro login debian \\
    --bind "$MEDIA_ROOT:/media" \\
    -- bash -c "jellyfin --datadir /var/lib/jellyfin --cachedir /var/cache/jellyfin --webdir /usr/share/jellyfin/web --ffmpeg /usr/lib/jellyfin-ffmpeg/ffmpeg"
""",
        encoding="utf-8",
        newline="\n",
    )
    start_script.chmod(0o755)

    boot_dir = home / ".termux" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    boot_script = boot_dir / "start-media-server.sh"
    boot_script.write_text(
        """#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true
pgrep -x "sshd" >/dev/null || sshd
nohup "$HOME/start-media-server.sh" > "$HOME/media-server.log" 2>&1 &
""",
        encoding="utf-8",
        newline="\n",
    )
    boot_script.chmod(0o755)

    print("\n========================================================")
    print("  SETUP COMPLETE!")
    print(f"  Your Termux SSH Username : {user_name}")
    print(f"  Your Device LAN IP       : {ip_addr or '<check Wi-Fi settings>'}")
    print("\n  Next steps:")
    print("  1. Set a temporary SSH password (or copy your SSH public key) by typing:")
    print("       passwd")
    print("  2. Start the Jellyfin Media Server anytime by typing:")
    print("       ~/start-media-server.sh")
    print(f"  3. Open Jellyfin in your browser (http://{ip_addr or 'localhost'}:8096) and add:")
    print("       - Movies     -> /media/Movies")
    print("       - Shows      -> /media/Series")
    print("       - Books      -> /media/Audiobooks")
    print("========================================================")


if __name__ == "__main__":
    main()
