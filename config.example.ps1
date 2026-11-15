<#
.SYNOPSIS
    Example local configuration for jellyfin-android-server PowerShell scripts.
.DESCRIPTION
    Copy this file to `config.ps1` in the repository root and fill in your
    Jellyfin server's LAN IP address and SSH username (`whoami` inside Termux or Linux).
    `config.ps1` is gitignored so your network details stay private.
#>

$script:DefaultAndroidIp      = "192.168.1.100"
$script:DefaultAndroidUser    = "u0_a300"
$script:DefaultSshPort        = 8022
$script:DefaultRemoteRoot     = "media"
$script:DefaultJellyfinPort   = 8096
$script:DefaultJellyfinApiKey = ""
$script:DefaultDriveLetter    = "Z"
