#!/usr/bin/env python3
"""
Jellyfin Upcoming Episodes & Ended-Series Refresh Optimizer

Configures Jellyfin's TMDb plugin (`ImportUnairedEpisodes`) so that upcoming episodes
for currently airing TV shows appear on the Jellyfin calendar and season views WITHOUT:
  1. Backfilling thousands of historical missing episodes (`ImportMissingEpisodes = false`), or
  2. Repeatedly refreshing metadata for ended TV series (`AutomaticRefreshIntervalDays = 0`).
"""

import argparse
import json
import urllib.request

TMDB_PLUGIN_ID = "b8715ed16c4745289ad3f72deb539cd4"


def make_headers(api_key: str) -> dict:
    return {
        "X-Emby-Token": api_key,
        "Authorization": f'MediaBrowser Token="{api_key}"',
        "Content-Type": "application/json",
    }


def api_get(base_url: str, path: str, headers: dict):
    req = urllib.request.Request(base_url.rstrip("/") + path, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_post(base_url: str, path: str, headers: dict, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else None


def main():
    parser = argparse.ArgumentParser(
        description="Configure Jellyfin TMDb Upcoming Episodes without historical missing-episode bloat."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8096",
        help="Jellyfin server URL (default: http://127.0.0.1:8096)",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="Jellyfin API key (Dashboard -> Administration -> API Keys)",
    )
    parser.add_argument(
        "--grace-days",
        type=int,
        default=14,
        help="Keep recently aired missing episodes visible for N days after air date (default: 14)",
    )
    parser.add_argument(
        "--refresh-days",
        type=int,
        default=3,
        help="Refresh interval in days for active series upcoming episodes (default: 3)",
    )
    args = parser.parse_args()

    headers = make_headers(args.api_key)

    # 1. Discover TV Shows libraries
    vfolders = api_get(args.url, "/Library/VirtualFolders", headers)
    tv_lib_ids = []
    for vf in vfolders:
        if vf.get("CollectionType") == "tvshows":
            item_id = vf.get("ItemId")
            tv_lib_ids.append(item_id)
            lib_opts = vf.get("LibraryOptions", {})
            if lib_opts.get("AutomaticRefreshIntervalDays", 0) != 0:
                print(f"[*] Disabling periodic full-library refresh on '{vf.get('Name')}' so ended shows are skipped...")
                lib_opts["AutomaticRefreshIntervalDays"] = 0
                api_post(
                    args.url,
                    "/Library/VirtualFolders/LibraryOptions",
                    headers,
                    {"Id": item_id, "LibraryOptions": lib_opts},
                )

    if not tv_lib_ids:
        raise RuntimeError("No 'tvshows' library found on this Jellyfin server.")

    # 2. Update TMDb plugin configuration
    cfg_path = f"/Plugins/{TMDB_PLUGIN_ID}/Configuration"
    cfg = api_get(args.url, cfg_path, headers)
    cfg["ImportUnairedEpisodes"] = True
    cfg["ImportMissingEpisodes"] = False
    cfg["UpcomingEpisodeGracePeriodDays"] = args.grace_days
    cfg["MissingEpisodeRefreshIntervalDays"] = args.refresh_days
    cfg["EnabledMissingEpisodeLibraries"] = tv_lib_ids
    api_post(args.url, cfg_path, headers, cfg)

    updated = api_get(args.url, cfg_path, headers)
    print("[+] Updated TMDb Upcoming Episodes Configuration:")
    print(json.dumps(updated, indent=2))


if __name__ == "__main__":
    main()
