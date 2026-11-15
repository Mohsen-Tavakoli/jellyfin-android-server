<#
.SYNOPSIS
    Example local configuration for jellyfin-android-server scripts.
.DESCRIPTION
    Copy this file to `config.ps1` in the repository root and fill in your
    Android phone's LAN IP address and Termux username (`whoami` inside Termux).
    `config.ps1` is gitignored so your network details stay private.
#>

$script:DefaultAndroidIp      = "192.168.1.100"
$script:DefaultAndroidUser    = "u0_a300"
$script:DefaultSshPort        = 8022
$script:DefaultJellyfinPort   = 8096
$script:DefaultDriveLetter    = "Z"
