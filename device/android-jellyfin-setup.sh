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
USB_UUID=""
for dir in /storage/*; do
    base=$(basename "$dir")
    if [[ "$base" != "emulated" && "$base" != "self" && "$base" != "*" && -d "$dir" ]]; then
        USB_UUID="$base"
        break
    fi
done

if [[ -n "$USB_UUID" ]]; then
    echo "  -> Found External USB Drive: /storage/$USB_UUID"
    MEDIA_ROOT="/storage/$USB_UUID/Android/data/com.termux/files/Media"
else
    echo "  -> No external USB drive currently mounted. Using internal storage (/sdcard/Media)."
    echo "     (Re-run ~/start-media-server.sh anytime after plugging in a USB-C hub + drive.)"
    MEDIA_ROOT="/sdcard/Media"
fi

mkdir -p "$MEDIA_ROOT/Movies" "$MEDIA_ROOT/Series" "$MEDIA_ROOT/Audiobooks"
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

# Auto-detect External USB Drive on every start (/mnt/media_rw/<UUID> or /storage/<UUID>)
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
    # Fallback: parse df for /mnt/media_rw/<UUID> (Android 14+ hides /mnt/media_rw parent listing)
    USB_PATH=$(df 2>/dev/null | awk '/\/mnt\/media_rw\// {print $6; exit}')
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

# Ensure SSH/SFTP server is running on port 8022
pgrep -x "sshd" >/dev/null || sshd

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
    -- bash -c "jellyfin --datadir /var/lib/jellyfin --cachedir /var/cache/jellyfin --webdir /usr/share/jellyfin/web --ffmpeg /usr/lib/jellyfin-ffmpeg/ffmpeg"
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
