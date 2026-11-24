#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Android / Pixel 4K Jellyfin Media Server Bootstrap (Runs inside Termux ARM64)
#
# Give a retired Android phone a second life as a silent, ultra-low-power
# (~3W idle) 24/7 Jellyfin media server without root.
#
# Installs & Configures:
#   1. OpenSSH Server (Port 8022) + Rclone (for optional SSH-tunneled WebDAV)
#   2. Automatic External USB-C Drive detection (with internal storage fallback)
#   3. Debian ARM64 (proot-distro) + Official Jellyfin Media Server (Port 8096)
#   4. ~/start-media-server.sh & Termux:Boot auto-start script
# ==============================================================================
set -e

echo "========================================================"
echo "  Android 4K Jellyfin Media Server Installer (Termux)"
echo "========================================================"

# 1. Acquire wake-lock so the CPU/Wi-Fi stay active during setup and streaming
termux-wake-lock || true

# 2. Update Termux & install core dependencies
echo "[1/5] Installing Termux server dependencies (openssh, proot-distro, rclone, rsync, tmux)..."
pkg update -y -o Dpkg::Options::="--force-confnew"
pkg upgrade -y -o Dpkg::Options::="--force-confnew"
pkg install -y openssh proot-distro rclone rsync tmux iproute2 procps curl

# 3. Detect External USB Hard Drive (or fallback to internal storage)
echo "[2/5] Detecting External USB-C Drive..."
USB_PATH=$(df 2>/dev/null | awk '/\/mnt\/media_rw\// {print $6; exit}')
if [[ -z "$USB_PATH" ]]; then
    for base_dir in /mnt/media_rw /storage; do
        for dir in "$base_dir"/*; do
            base=$(basename "$dir")
            if [[ "$base" != "emulated" && "$base" != "self" && "$base" != "*" && -d "$dir" ]]; then
                USB_PATH="$dir"
                break 2
            fi
        done
    done
fi

if [[ -n "$USB_PATH" && -d "$USB_PATH" ]]; then
    echo "  -> Found External USB Drive: $USB_PATH"
    touch "$HOME/.prefer-usb-storage"
    MEDIA_ROOT="$USB_PATH/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks" 2>/dev/null || {
        MEDIA_ROOT="$USB_PATH/Android/data/com.termux/files/Media"
        mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
    }
else
    echo "  -> No external USB drive currently mounted. Using internal storage (/sdcard/Media)."
    echo "     (Re-run ~/start-media-server.sh anytime after plugging in a USB-C hub + drive.)"
    MEDIA_ROOT="/sdcard/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
fi

ln -sfn "$MEDIA_ROOT" "$HOME/media"
echo "  -> Media folders ready at: $MEDIA_ROOT/{Movies,Series,Audiobooks} (symlinked to ~/media)"

# 4. Configure OpenSSH Server (Port 8022)
echo "[3/5] Starting OpenSSH Server on port 8022..."
if ! pgrep -x "sshd" >/dev/null; then
    sshd
fi
USER_NAME=$(whoami)
IP_ADDR=$(ip -4 addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)
if [[ -z "$IP_ADDR" ]]; then
    IP_ADDR=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
fi

# 5. Install Debian ARM64 & Official Jellyfin Server
echo "[4/5] Setting up Debian ARM64 container & Jellyfin Media Server..."
if ! proot-distro list | grep -q "debian.*installed"; then
    proot-distro install debian
fi

proot-distro login debian -- bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl gnupg apt-transport-https ca-certificates locales

if ! command -v jellyfin >/dev/null 2>&1; then
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor -o /etc/apt/keyrings/jellyfin.gpg --yes
    VERSION_CODENAME=$(awk -F"=" "/^VERSION_CODENAME=/{ print \$NF }" /etc/os-release)
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
'

# 6. Create ~/start-media-server.sh launcher
echo "[5/5] Creating ~/start-media-server.sh launcher..."
cat << 'EOF' > "$HOME/start-media-server.sh"
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true

# Optional: pass --restart to cleanly stop an existing Jellyfin instance first
RESTART=0
if [[ "$1" == "--restart" ]]; then
    RESTART=1
fi

# Ensure SSH/SFTP server is running on port 8022
pgrep -x "sshd" >/dev/null || sshd

if pgrep -f "jellyfin --datadir" >/dev/null 2>&1; then
    if [[ "$RESTART" -eq 1 ]]; then
        echo "[*] Stopping existing Jellyfin instance..."
        pkill -TERM -f "jellyfin --datadir" 2>/dev/null || true
        for _ in $(seq 1 15); do
            pgrep -f "jellyfin --datadir" >/dev/null 2>&1 || break
            sleep 1
        done
        pkill -KILL -f "jellyfin --datadir" 2>/dev/null || true
    else
        echo "[i] Jellyfin is already running (pass --restart to restart it)."
        exit 0
    fi
fi

# Auto-detect External USB Drive (/mnt/media_rw/<UUID> or /storage/<UUID>)
detect_usb_path() {
    local p=""
    # Parse df first (Android 14+ hides /mnt/media_rw parent directory listing)
    p=$(df 2>/dev/null | awk '/\/mnt\/media_rw\// {print $6; exit}')
    if [[ -n "$p" && -d "$p" ]]; then
        echo "$p"
        return 0
    fi
    for base_dir in /mnt/media_rw /storage; do
        for dir in "$base_dir"/*; do
            local base
            base=$(basename "$dir")
            if [[ "$base" != "emulated" && "$base" != "self" && "$base" != "*" && -d "$dir" ]]; then
                echo "$dir"
                return 0
            fi
        done
    done
    return 1
}

# On boot, Android's vold often takes 20-60s to enumerate & mount USB-C drives.
# If this host has previously used USB storage (or USB_WAIT_SECONDS is set), wait for it.
PREFER_USB_MARKER="$HOME/.prefer-usb-storage"
DEFAULT_WAIT=15
if [[ -f "$PREFER_USB_MARKER" ]]; then
    DEFAULT_WAIT=90
fi
WAIT_LIMIT="${USB_WAIT_SECONDS:-$DEFAULT_WAIT}"
REQUIRE_USB="${REQUIRE_USB:-0}"

USB_PATH=$(detect_usb_path || true)
ELAPSED=0
while [[ -z "$USB_PATH" && "$ELAPSED" -lt "$WAIT_LIMIT" ]]; do
    if [[ "$ELAPSED" -eq 0 ]]; then
        echo "[*] Waiting up to ${WAIT_LIMIT}s for storage / external USB drive to mount..."
    fi
    sleep 3
    ELAPSED=$((ELAPSED + 3))
    USB_PATH=$(detect_usb_path || true)
done

if [[ -n "$USB_PATH" && -d "$USB_PATH" ]]; then
    touch "$PREFER_USB_MARKER"
    MEDIA_ROOT="$USB_PATH/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks" 2>/dev/null || {
        MEDIA_ROOT="$USB_PATH/Android/data/com.termux/files/Media"
        mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
    }
    echo "[+] Mounted External USB Drive: $MEDIA_ROOT (after ${ELAPSED}s)"
else
    if [[ "$REQUIRE_USB" -eq 1 ]]; then
        echo "[!] ERROR: External USB drive not detected after ${WAIT_LIMIT}s and REQUIRE_USB=1. Aborting start."
        exit 1
    fi
    for _ in $(seq 1 10); do
        [[ -d "/sdcard" ]] && break
        sleep 2
    done
    MEDIA_ROOT="/sdcard/Media"
    mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
    echo "[i] Using Internal Storage: $MEDIA_ROOT"
fi
ln -sfn "$MEDIA_ROOT" "$HOME/media"

IP_ADDR=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
echo "========================================================"
echo "  ANDROID 4K JELLYFIN MEDIA SERVER ACTIVE"
echo "  Jellyfin Web / TV URL : http://${IP_ADDR:-<device-ip>}:8096"
echo "  SSH / SFTP Upload     : ssh -p 8022 $(whoami)@${IP_ADDR:-<device-ip>}"
echo "  Media Directory       : $MEDIA_ROOT"
echo "========================================================"

# Launch Jellyfin inside Debian with the media directory bound to /media
proot-distro login debian \
    --bind "$MEDIA_ROOT:/media" \
    -- bash -c "DOTNET_SYSTEM_NET_DISABLEIPV6=1 jellyfin --datadir /var/lib/jellyfin --cachedir /var/cache/jellyfin --webdir /usr/share/jellyfin/web --ffmpeg /usr/lib/jellyfin-ffmpeg/ffmpeg"
EOF

chmod +x "$HOME/start-media-server.sh"

# Configure Termux:Boot auto-start script so the server starts automatically on reboot
mkdir -p "$HOME/.termux/boot"
cat << 'BOOTEOF' > "$HOME/.termux/boot/start-media-server.sh"
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock || true
pgrep -x "sshd" >/dev/null || sshd
nohup "$HOME/start-media-server.sh" > "$HOME/media-server.log" 2>&1 &
BOOTEOF
chmod +x "$HOME/.termux/boot/start-media-server.sh"

echo ""
echo "========================================================"
echo "  SETUP COMPLETE!"
echo "  Your Termux SSH Username : $USER_NAME"
echo "  Your Device LAN IP       : ${IP_ADDR:-<check Wi-Fi settings>}"
echo ""
echo "  Next steps:"
echo "  1. Set a temporary SSH password (or copy your SSH public key) by typing:"
echo "       passwd"
echo "  2. Start the Jellyfin Media Server anytime by typing:"
echo "       ~/start-media-server.sh"
echo "  3. Open Jellyfin in your browser (http://${IP_ADDR:-localhost}:8096) and add:"
echo "       - Movies     -> /media/Movies"
echo "       - Shows      -> /media/Series"
echo "       - Books      -> /media/Audiobooks"
echo "========================================================"
