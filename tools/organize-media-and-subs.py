#!/usr/bin/env python3
"""
Jellyfin Media Folder & Subtitle Organizer (with Persian CP1256 -> UTF-8 Normalization)

Features:
1. Organizes flat season folders (e.g. `Sample.Show.S01.1080p...`) into clean
   Jellyfin `Show Name/Season 01` hierarchies.
2. Extracts `.zip` subtitle archives and nested `Subs/` directories alongside
   matching video files as `<VideoName>.<lang>.srt`.
3. Automatically detects and converts legacy subtitle encodings (`Windows-1256` /
   `CP1256` for Persian/Farsi, `UTF-16`, `Windows-1252`) into clean `UTF-8`.
"""

import argparse
import os
import re
import shutil
import zipfile

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".mov", ".ts"}


def ensure_utf8_srt(src_path: str, dst_path: str) -> None:
    """Copy an .srt file to dst_path, converting CP1256 (Persian) or UTF-16 to UTF-8 if needed."""
    with open(src_path, "rb") as f:
        raw = f.read()

    text = None
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        try:
            text = raw.decode("utf-16")
        except Exception:
            pass
    elif raw.startswith(b"\xef\xbb\xbf"):
        try:
            text = raw.decode("utf-8-sig")
        except Exception:
            pass

    if text is None:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1256")
            except Exception:
                text = raw.decode("latin-1", errors="replace")

    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(text)


def detect_sub_lang(sub_path: str, filename_hint: str = "") -> str:
    """Detect whether a subtitle file is Persian ('fa'), English ('en'), French ('fr'), etc."""
    lower = filename_hint.lower()
    if "sdh" in lower or ".hi." in lower:
        return "sdh.en"
    if any(tag in lower for tag in ("farsi", "persian", ".fa.", ".per.")):
        return "fa"
    if ".fre." in lower or "french" in lower:
        return "fr"
    if any(tag in lower for tag in ("english", "_eng", ".en.", ".eng.")):
        return "en"

    try:
        with open(sub_path, "rb") as f:
            sample = f.read(4096)
        for enc in ("utf-8", "utf-16", "cp1256"):
            try:
                txt = sample.decode(enc)
                if re.search(r"[\u0600-\u06FF]", txt):
                    return "fa"
                break
            except Exception:
                continue
    except Exception:
        pass
    return "en"


def parse_season_folder_name(folder_name: str):
    """
    Parse a release-style folder name like:
      'Sample.Show.2022.S01.1080p.WEB-DL' or 'Sample Show (2022) Season 1 S01 (1080p...)'
    Returns (clean_show_name, season_folder_name) or None if already clean.
    """
    pattern = re.compile(
        r"^(?P<title>.+?)[.\s_-]+(?:Season[.\s_-]*\d+[.\s_-]*)?S(?P<season>\d{1,2})\b",
        re.IGNORECASE,
    )
    m = pattern.match(folder_name)
    if not m:
        return None

    raw_title = m.group("title")
    season_num = int(m.group("season"))
    clean_title = re.sub(r"[._]+", " ", raw_title).strip(" -._")
    clean_title = re.sub(r"\b((?:19|20)\d{2})$", r"(\1)", clean_title)
    if not clean_title:
        return None
    return clean_title, f"Season {season_num:02d}"


def reorganize_series_folders(series_dir: str, dry_run: bool = False) -> int:
    """Group top-level season folders under `<Show Name>/Season XX`."""
    if not os.path.isdir(series_dir):
        return 0

    moved = 0
    for entry in sorted(os.listdir(series_dir)):
        src = os.path.join(series_dir, entry)
        if not os.path.isdir(src):
            continue
        parsed = parse_season_folder_name(entry)
        if not parsed:
            continue
        show_name, season_name = parsed
        show_dir = os.path.join(series_dir, show_name)
        dst = os.path.join(show_dir, season_name)
        if os.path.abspath(src) == os.path.abspath(dst) or os.path.exists(dst):
            continue
        print(f"  -> Moving '{entry}' => '{show_name}/{season_name}'")
        if not dry_run:
            os.makedirs(show_dir, exist_ok=True)
            shutil.move(src, dst)
        moved += 1
    return moved


def fix_subtitles_in_tree(root_dir: str, dry_run: bool = False) -> int:
    """Extract nested subtitles and normalize encodings to UTF-8 alongside video files."""
    if not os.path.isdir(root_dir):
        return 0

    fixed_count = 0

    # Step A: Extract .zip subtitle archives
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if fn.lower().endswith(".zip"):
                zip_path = os.path.join(dirpath, fn)
                extract_dir = os.path.join(dirpath, "_extracted_subs")
                if not os.path.exists(extract_dir):
                    print(f"  [+] Extracting subtitle archive: {fn}")
                    if not dry_run:
                        try:
                            os.makedirs(extract_dir, exist_ok=True)
                            with zipfile.ZipFile(zip_path, "r") as zf:
                                for member in zf.namelist():
                                    if member.lower().endswith(".srt"):
                                        zf.extract(member, extract_dir)
                        except Exception as e:
                            print(f"  [!] Failed to extract {fn}: {e}")

    # Step B: Process nested 'Subs/' folders
    for dirpath, dirnames, filenames in os.walk(root_dir):
        if os.path.basename(dirpath).lower() != "subs":
            continue
        parent_dir = os.path.dirname(dirpath)
        parent_videos = {}
        for fn in os.listdir(parent_dir):
            base, ext = os.path.splitext(fn)
            if ext.lower() in VIDEO_EXTS:
                parent_videos[base] = os.path.join(parent_dir, fn)

        # Single-movie style: Subs/English.srt
        if len(parent_videos) == 1:
            video_base = next(iter(parent_videos.keys()))
            for fn in filenames:
                if fn.lower().endswith(".srt"):
                    src_srt = os.path.join(dirpath, fn)
                    lang = detect_sub_lang(src_srt, fn)
                    dst_srt = os.path.join(parent_dir, f"{video_base}.{lang}.srt")
                    if not os.path.exists(dst_srt):
                        if not dry_run:
                            ensure_utf8_srt(src_srt, dst_srt)
                        fixed_count += 1

        # Multi-episode style: Subs/<EpisodeBaseName>/<track>.srt
        for sub_ep_dir in dirnames:
            ep_sub_path = os.path.join(dirpath, sub_ep_dir)
            target_video_base = None
            if sub_ep_dir in parent_videos:
                target_video_base = sub_ep_dir
            else:
                m = re.search(r"(S\d{1,2}E\d{1,2})", sub_ep_dir, re.IGNORECASE)
                if m:
                    code = m.group(1).upper()
                    for vbase in parent_videos:
                        if code in vbase.upper():
                            target_video_base = vbase
                            break

            if not target_video_base:
                continue

            srt_files = sorted(f for f in os.listdir(ep_sub_path) if f.lower().endswith(".srt"))
            eng_idx = 0
            for srt_fn in srt_files:
                lower_fn = srt_fn.lower()
                is_eng = "english" in lower_fn or "_eng" in lower_fn
                is_per = "per" in lower_fn or "far" in lower_fn
                if not (is_eng or is_per):
                    continue

                src_srt = os.path.join(ep_sub_path, srt_fn)
                if is_per:
                    suffix = "fa"
                elif "sdh" in lower_fn:
                    suffix = "sdh.en"
                else:
                    eng_idx += 1
                    suffix = "en" if eng_idx == 1 else f"en{eng_idx}.en"

                dst_srt = os.path.join(parent_dir, f"{target_video_base}.{suffix}.srt")
                if not os.path.exists(dst_srt):
                    if not dry_run:
                        ensure_utf8_srt(src_srt, dst_srt)
                    fixed_count += 1

    # Step C: Match loose SxxExx .srt files and normalize existing Persian SRTs in-place
    for dirpath, _, filenames in os.walk(root_dir):
        if os.path.basename(dirpath).lower() == "subs":
            continue
        videos_by_code = {}
        srts_by_code = []
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            base, ext = os.path.splitext(fn)
            if ext.lower() == ".srt":
                lang = detect_sub_lang(full, fn)
                if lang == "fa" and not dry_run:
                    ensure_utf8_srt(full, full)
            m = re.search(r"S(\d{1,2})E(\d{1,2})", fn, re.IGNORECASE)
            if not m:
                continue
            code = f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
            if ext.lower() in VIDEO_EXTS and "sample" not in fn.lower():
                videos_by_code[code] = (dirpath, base)
            elif ext.lower() == ".srt":
                srts_by_code.append((code, full, fn))

        for code, srt_full, srt_fn in srts_by_code:
            if code not in videos_by_code:
                continue
            v_dir, v_base = videos_by_code[code]
            if srt_fn.startswith(v_base):
                continue
            lang = detect_sub_lang(srt_full, srt_fn)
            dst_srt = os.path.join(v_dir, f"{v_base}.{lang}.srt")
            if not os.path.exists(dst_srt):
                if not dry_run:
                    ensure_utf8_srt(srt_full, dst_srt)
                fixed_count += 1

    return fixed_count


def main():
    parser = argparse.ArgumentParser(
        description="Organize Jellyfin TV/Movie folders and normalize nested/Persian (CP1256) subtitles to UTF-8."
    )
    parser.add_argument(
        "--media-root",
        default="/media",
        help="Path to the media root folder containing Movies/ and Series/ (default: /media)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview folder moves and subtitle extractions without modifying files",
    )
    args = parser.parse_args()

    series_dir = os.path.join(args.media_root, "Series")
    movies_dir = os.path.join(args.media_root, "Movies")

    print(f"[*] Scanning media root: {args.media_root} (dry_run={args.dry_run})")
    moved = reorganize_series_folders(series_dir, dry_run=args.dry_run)
    subs_movies = fix_subtitles_in_tree(movies_dir, dry_run=args.dry_run)
    subs_series = fix_subtitles_in_tree(series_dir, dry_run=args.dry_run)

    print(
        f"[+] Done! Organized {moved} season folder(s) and prepared {subs_movies + subs_series} UTF-8 subtitle file(s)."
    )


if __name__ == "__main__":
    main()
