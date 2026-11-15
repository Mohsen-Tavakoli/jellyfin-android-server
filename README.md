# Jellyfin Android Server (`jellyfin-android-server`)

**Give your retired Android phone a second life as a silent, ~3W 24/7 4K Jellyfin Media Server + USB-C NAS—without root.**

Millions of capable 64-bit Android phones end up in drawers or e-waste every year despite having fast ARM64 CPUs, gigabit Wi-Fi, built-in battery backup (UPS), and USB-C storage support. This toolkit turns any modern Android phone (Android 10–16+, e.g. Pixel, Galaxy, OnePlus) into a self-healing 24/7 **Jellyfin Media Server** using Termux + Debian ARM64 (`proot-distro`), complete with **cross-platform Python (macOS / Linux / Windows)** and **PowerShell** management scripts.

---

## ✨ Features

- **♻️ Zero E-Waste, Ultra-Low Power (~2–4W Idle)**: Runs silently 24/7 with a built-in battery UPS and no root required.
- **🍎🐧🪟 Full Cross-Platform Support**: Every host management script includes both a **Python 3** version (zero external dependencies for macOS, Linux, and Windows) and a native **PowerShell** version.
- **🛡️ Android 12–16+ Phantom Process Killer Fix**: Automatically configures `max_phantom_processes` and Doze battery whitelists over ADB so Android never kills `jellyfin` or `sshd` in the background.
- **💾 External USB-C Drive + Internal Storage Auto-Detection**: Automatically detects external USB-C SSDs/HDDs (including Android 14+ `/mnt/media_rw/<UUID>` mounts) and binds them to `/media/{Movies,Series,Audiobooks}` inside Debian.
- **🔄 Self-Healing Launcher (`start_media_server.py` / `start-media-server.ps1`)**: Checks if Jellyfin (`:8096`) is online; if not, starts it over SSH (`:8022`); if SSH is down, automatically scans for Android Wireless Debugging ports, wakes the phone, starts `sshd`, and launches Jellyfin.
- **📦 Differential Media Sync (`push_media.py` / `push-media.ps1`)**: Pushes Movies, TV Series, and Audiobooks from your computer while skipping files already on the server.
- **🌐 Persian (`CP1256`) & Nested Subtitle Organizer (`organize-media-and-subs.py`)**: Extracts nested `Subs/` folders and `.zip` subtitle archives alongside video files and automatically converts `Windows-1256` (`CP1256` Persian/Farsi) and `UTF-16` `.srt` files into clean `UTF-8`.
- **📅 Upcoming Episodes Optimizer (`optimize-upcoming-episodes.py`)**: Configures Jellyfin's TMDb plugin to display upcoming episodes (`ImportUnairedEpisodes = true`) without backfilling thousands of historical missing episodes or repeatedly refreshing ended TV shows.

---

## 📁 Repository Structure

```text
jellyfin-android-server/
├── .env.example                       # Copy to .env (gitignored) for Python scripts (macOS/Linux/Windows)
├── config.example.ps1                 # Copy to config.ps1 (gitignored) for PowerShell scripts
├── device/
│   ├── android-jellyfin-setup.sh      # Runs inside Termux: installs SSH, Debian ARM64 & Jellyfin
│   └── harden-android-server.sh       # Locks SSH to key-only auth & restricts Jellyfin to your LAN subnet
├── scripts/
│   ├── setup_android_host.py          # Cross-platform ADB provisioner (macOS / Linux / Windows)
│   ├── setup-android-host.ps1         # PowerShell ADB provisioner
│   ├── start_media_server.py          # Cross-platform self-healing launcher (HTTP -> SSH -> Wireless ADB)
│   ├── start-media-server.ps1         # PowerShell self-healing launcher
│   ├── push_media.py                  # Cross-platform differential media uploader
│   ├── push-media.ps1                 # PowerShell differential media uploader
│   ├── manage_media.py                # Cross-platform remote storage manager (list, space, remove)
│   ├── manage-media.ps1               # PowerShell remote storage manager
│   ├── mount_media_drive.py           # Mounts phone storage via SSH-tunneled WebDAV (macOS Finder / Linux / Windows)
│   └── mount-media-drive.ps1          # PowerShell WebDAV drive mounter
└── tools/
    ├── organize-media-and-subs.py     # Season folder organizer + Persian (CP1256 -> UTF-8) subtitle fixer
    └── optimize-upcoming-episodes.py  # Configures TMDb Upcoming Episodes without historical missing bloat
```

---

## 🚀 Step-by-Step Quick Start

### Prerequisites
1. **An Android Phone (64-bit ARM64, Android 10+)**:
   - Install **[Termux](https://github.com/termux/termux-app/releases)** and **[Termux:Boot](https://github.com/termux/termux-boot/releases)** (from GitHub Releases or F-Droid—*not* the outdated Play Store build).
   - Enable **Developer Options** → **USB Debugging** (or **Wireless Debugging**).
2. **A Computer (macOS, Linux, or Windows) with `adb`, `ssh`/`scp`, and `python3` (or PowerShell)**.
3. *(Optional)* A **USB-C Hub with Power Delivery (PD)** + an external USB SSD/HDD formatted as `exFAT`.

---

### Step 1: Provision the Android Phone from Your Computer
Connect your phone via USB-C (or Wireless Debugging) and run:

**macOS / Linux / Cross-Platform (Python 3):**
```bash
python3 scripts/setup_android_host.py
# Or over Wireless ADB:
python3 scripts/setup_android_host.py --connect 192.168.1.100:5555
```

**Windows (PowerShell):**
```powershell
.\scripts\setup-android-host.ps1
# Or over Wireless ADB:
.\scripts\setup-android-host.ps1 -ConnectIpPort "192.168.1.100:5555"
```

What this does:
- Disables Android's **Phantom Process Killer** (`max_phantom_processes = 2147483647`) so background server processes are never killed.
- Whitelists `com.termux` and `com.termux.boot` from Android Doze battery restrictions and grants `MANAGE_EXTERNAL_STORAGE`.
- Pushes `android-jellyfin-setup.sh` to `/sdcard/Download/android-jellyfin-setup.sh` and opens Termux.

---

### Step 2: Bootstrap Debian & Jellyfin Inside Termux
On the phone inside **Termux**, run:

```bash
bash /sdcard/Download/android-jellyfin-setup.sh
```

Once setup completes:
1. Note your **Termux username** (e.g. `u0_a300`) and **LAN IP** printed at the end.
2. Set an initial SSH password (or copy your computer's SSH key):
   ```bash
   passwd
   ```
3. Start the server:
   ```bash
   ~/start-media-server.sh
   ```
4. Open `http://<device-ip>:8096` in your browser to complete the Jellyfin wizard and add your libraries:
   - **Movies** → `/media/Movies`
   - **Shows** → `/media/Series`
   - **Books** → `/media/Audiobooks`

---

### Step 3: Configure Local Scripts (`.env` or `config.ps1`)
Copy `.env.example` to `.env` (for Python on macOS/Linux/Windows) or `config.example.ps1` to `config.ps1` (for PowerShell). Both files are gitignored so your personal IPs stay private:

```bash
cp .env.example .env
```

Edit `.env` with your phone's LAN IP and Termux username:
```ini
ANDROID_HOST_IP=192.168.1.100
ANDROID_SSH_USER=u0_a300
ANDROID_SSH_PORT=8022
JELLYFIN_PORT=8096
```

Copy your SSH key to the phone for passwordless uploads:
```bash
ssh-copy-id -p 8022 u0_a300@192.168.1.100
```

*(Optional)* Lock down SSH (key-only) and restrict Jellyfin to your local subnet:
```bash
ssh -p 8022 u0_a300@192.168.1.100 "bash -s" < device/harden-android-server.sh
```

---

## 🖥️ Daily Usage & Media Management

### 1. Start or Self-Heal the Server
Checks Jellyfin (`:8096`), falls back to SSH (`:8022`), or wakes the phone via ADB if needed:

```bash
# macOS / Linux / Windows (Python):
python3 scripts/start_media_server.py

# Windows (PowerShell):
.\scripts\start-media-server.ps1
```

### 2. Upload Movies, TV Episodes, or Audiobooks
Automatically checks existing files on the server and uploads only new files:

**macOS / Linux / Windows (Python):**
```bash
# Upload new TV show episodes (supports space/dot wildcards):
python3 scripts/push_media.py --category Series --show-name "Sample Show" "~/Downloads/Sample Show S01*"

# Upload multiple movies at once:
python3 scripts/push_media.py --category Movies "~/Movies/Big Buck Bunny (2008).mkv" "~/Movies/Sintel (2010).mkv"

# Upload audiobooks:
python3 scripts/push_media.py --category Audiobooks --book-name "Sample Audiobook" "~/Audiobooks/Sample Audiobook*"
```

**Windows (PowerShell):**
```powershell
.\scripts\push-media.ps1 -Category Series -ShowName "Sample Show" -Path "C:\Media\Sample Show S01*"
.\scripts\push-media.ps1 -Category Movies -Path "C:\Media\Big Buck Bunny (2008).mkv", "C:\Media\Sintel (2010).mkv"
.\scripts\push-media.ps1 -Category Audiobooks -BookName "Sample Audiobook" -Path "C:\Media\Sample Audiobook*"
```

### 3. Check Storage Space, List Media, or Delete Files
**macOS / Linux / Windows (Python):**
```bash
python3 scripts/manage_media.py --action space
python3 scripts/manage_media.py --action list --filter "Sample Show"
python3 scripts/manage_media.py --action remove --target "Sample Show S01E01"
```

**Windows (PowerShell):**
```powershell
.\scripts\manage-media.ps1 -Action Space
.\scripts\manage-media.ps1 -Action List -Filter "Sample Show"
.\scripts\manage-media.ps1 -Action Remove -Target "Sample Show S01E01"
```

### 4. Mount Phone Storage in Finder / File Explorer
Mounts `~/media/` on the phone via an SSH-tunneled localhost WebDAV server (mounts natively in **macOS Finder**, **Linux GIO**, or **Windows Explorer**):

```bash
# macOS / Linux / Windows (Python):
python3 scripts/mount_media_drive.py
python3 scripts/mount_media_drive.py --unmount

# Windows (PowerShell):
.\scripts\mount-media-drive.ps1 -DriveLetter Z
.\scripts\mount-media-drive.ps1 -Unmount -DriveLetter Z
```

---

## 🧰 Library & Subtitle Utilities (`tools/`)

### 1. Subtitle & Series Folder Organizer (`organize-media-and-subs.py`)
Fixes two common Jellyfin library headaches:
- Reorganizes flat season folders (`Sample.Show.2022.S01.1080p...`) into clean `Sample Show (2022)/Season 01` directories.
- Extracts `.zip` subtitle archives and nested `Subs/` folders alongside video files (`<VideoName>.en.srt`, `<VideoName>.fa.srt`), automatically converting **`Windows-1256` (`CP1256` Persian/Farsi)** and **`UTF-16`** subtitles into **`UTF-8`**.

```bash
# Preview changes without modifying files:
python3 tools/organize-media-and-subs.py --media-root /media --dry-run

# Apply organization and UTF-8 subtitle normalization:
python3 tools/organize-media-and-subs.py --media-root /media
```

### 2. Upcoming Episodes Optimizer (`optimize-upcoming-episodes.py`)
Configures Jellyfin's **TheMovieDb (TMDb)** plugin so that unaired/upcoming episodes for currently airing shows appear on your Jellyfin calendar and season views **without** importing thousands of historical missing episodes or refreshing ended shows:

```bash
python3 tools/optimize-upcoming-episodes.py --url http://127.0.0.1:8096 --api-key YOUR_JELLYFIN_API_KEY
```

---

## 📄 License

Released under the [MIT License](LICENSE).
