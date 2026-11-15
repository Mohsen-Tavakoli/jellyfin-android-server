#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# Android Jellyfin Media Server LAN Hardening Script (Runs inside Termux)
#
# 1. Configures OpenSSH (port 8022) for SSH-key-only authentication.
# 2. Dynamically detects the device's LAN IP & /24 subnet and locks Jellyfin
#    to LAN-only access with UPnP and remote access disabled.
# ==============================================================================
set -e

if [[ ! -s ~/.ssh/authorized_keys ]]; then
    echo "[!] WARNING: ~/.ssh/authorized_keys is empty or missing."
    echo "    Add your PC's public key (ssh-copy-id -p 8022 $(whoami)@<device-ip>) before disabling password login!"
    exit 1
fi

echo "[1/3] Hardening Termux OpenSSH Server (Key-Only Auth + KeepAlives)..."
mkdir -p /data/data/com.termux/files/usr/etc/ssh/sshd_config.d
cat << 'EOF' > /data/data/com.termux/files/usr/etc/ssh/sshd_config.d/lan-hardening.conf
# Android LAN Media Server Hardening
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 30
ClientAliveCountMax 6
TCPKeepAlive yes
X11Forwarding no
AllowAgentForwarding no
EOF
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys

# Detect current LAN IP and /24 subnet dynamically
IP_ADDR=$(ip -4 addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)
if [[ -z "$IP_ADDR" ]]; then
    IP_ADDR=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}')
fi
SUBNET_CIDR="${1:-$(echo "$IP_ADDR" | awk -F. '{print $1"."$2"."$3".0/24"}')}"

echo "[2/3] Hardening Jellyfin Network Config (LAN-Only ${SUBNET_CIDR}, Disable Remote Access & UPnP)..."
DEBIAN_CONFIG_DIR="/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/debian/var/lib/jellyfin/config"
mkdir -p "$DEBIAN_CONFIG_DIR"
cat << EOF > "$DEBIAN_CONFIG_DIR/network.xml"
<?xml version="1.0" encoding="utf-8"?>
<NetworkConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <BaseUrl />
  <EnableHttps>false</EnableHttps>
  <RequireHttps>false</RequireHttps>
  <InternalHttpPort>8096</InternalHttpPort>
  <InternalHttpsPort>8920</InternalHttpsPort>
  <PublicHttpPort>8096</PublicHttpPort>
  <PublicHttpsPort>8920</PublicHttpsPort>
  <AutoDiscovery>true</AutoDiscovery>
  <EnableUPnP>false</EnableUPnP>
  <EnableIPv4>true</EnableIPv4>
  <EnableIPv6>false</EnableIPv6>
  <EnableRemoteAccess>false</EnableRemoteAccess>
  <LocalNetworkSubnets>
    <string>${SUBNET_CIDR}</string>
  </LocalNetworkSubnets>
  <LocalNetworkAddresses>
    <string>${IP_ADDR}</string>
    <string>127.0.0.1</string>
  </LocalNetworkAddresses>
  <KnownProxies />
  <IgnoreVirtualInterfaces>true</IgnoreVirtualInterfaces>
  <VirtualInterfaceNames>
    <string>veth</string>
  </VirtualInterfaceNames>
  <EnablePublishedServerUriByRequest>false</EnablePublishedServerUriByRequest>
  <PublishedServerUriBySubnet />
  <RemoteIPFilter />
  <IsRemoteIPFilterBlacklist>false</IsRemoteIPFilterBlacklist>
</NetworkConfiguration>
EOF

echo "[3/3] Verifying and reloading SSHD daemon..."
sshd -t && echo "[+] SSHD config syntax OK!"
if [[ -f /data/data/com.termux/files/usr/var/run/sshd.pid ]]; then
    kill -HUP "$(cat /data/data/com.termux/files/usr/var/run/sshd.pid)" 2>/dev/null || true
fi
pgrep -x "sshd" >/dev/null || sshd
echo "[+] Hardening complete!"
