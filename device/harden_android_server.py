#!/usr/bin/env python3
"""
Android Jellyfin Media Server LAN Hardening Script (Python version for Termux)

1. Configures OpenSSH (port 8022) for SSH-key-only authentication.
2. Dynamically detects the device's LAN IP & /24 subnet and locks Jellyfin
   to LAN-only access with UPnP and remote access disabled.

Can be run directly inside Termux (`python3 harden_android_server.py`) or remotely:
  ssh -p 8022 u0_a300@192.168.1.100 "python3 -" < device/harden_android_server.py
"""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path


def capture(cmd: str) -> str:
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (res.stdout or "").strip()


def detect_lan_ip() -> str:
    ip = capture("ip -4 addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1")
    if not ip:
        ip = capture("ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i==\"src\") print $(i+1)}'")
    return ip or "127.0.0.1"


def main():
    parser = argparse.ArgumentParser(description="Harden Termux OpenSSH and Jellyfin LAN configuration.")
    parser.add_argument("--subnet", default="", help="Optional CIDR subnet override (e.g. 192.168.1.0/24)")
    args = parser.parse_args()

    ssh_dir = Path.home() / ".ssh"
    auth_keys = ssh_dir / "authorized_keys"
    if not auth_keys.is_file() or auth_keys.stat().st_size == 0:
        print("[!] WARNING: ~/.ssh/authorized_keys is empty or missing.")
        print("    Add your computer's public key before disabling password login!")
        sys.exit(1)

    print("[1/3] Hardening Termux OpenSSH Server (Key-Only Auth + KeepAlives)...")
    sshd_conf_dir = Path("/data/data/com.termux/files/usr/etc/ssh/sshd_config.d")
    sshd_conf_dir.mkdir(parents=True, exist_ok=True)
    (sshd_conf_dir / "lan-hardening.conf").write_text(
        """# Android LAN Media Server Hardening
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
""",
        encoding="utf-8",
        newline="\n",
    )
    ssh_dir.chmod(0o700)
    auth_keys.chmod(0o600)

    ip_addr = detect_lan_ip()
    octets = ip_addr.split(".")
    subnet_cidr = args.subnet or (f"{octets[0]}.{octets[1]}.{octets[2]}.0/24" if len(octets) == 4 else "192.168.1.0/24")

    print(f"[2/3] Hardening Jellyfin Network Config (LAN-Only {subnet_cidr}, Disable Remote Access & UPnP)...")
    debian_cfg_dir = Path(
        "/data/data/com.termux/files/usr/var/lib/proot-distro/installed-rootfs/debian/var/lib/jellyfin/config"
    )
    debian_cfg_dir.mkdir(parents=True, exist_ok=True)
    (debian_cfg_dir / "network.xml").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
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
    <string>{subnet_cidr}</string>
  </LocalNetworkSubnets>
  <LocalNetworkAddresses>
    <string>{ip_addr}</string>
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
""",
        encoding="utf-8",
        newline="\n",
    )

    print("[3/3] Verifying and reloading SSHD daemon...")
    subprocess.run(["sshd", "-t"], check=True)
    print("[+] SSHD config syntax OK!")

    pid_file = Path("/data/data/com.termux/files/usr/var/run/sshd.pid")
    if pid_file.is_file():
        try:
            os.kill(int(pid_file.read_text().strip()), signal.SIGHUP)
        except Exception:
            pass
    if not capture("pgrep -x sshd"):
        subprocess.run(["sshd"], check=False)

    print("[+] Hardening complete!")


if __name__ == "__main__":
    main()
