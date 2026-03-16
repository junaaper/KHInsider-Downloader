import os
import sys
import threading
import concurrent.futures
import re
from tqdm import tqdm

from downloader import get_album_info, get_download_link, download_album_art, download_file
from metadata import embed_album_art

def strip_leading_number(title):
    return re.sub(r"^\s*\d+\s*[\.\-]?\s*", "", title).strip()

def safe_filename(s):
    return re.sub(r'[\\/*?:"<>|]', '', s).replace('%20', ' ').replace('_', ' ').strip()

def safe_foldername(s):
    return re.sub(r'[\\/*?:"<>|]', '', s).strip()

def clean_album_title(title):
    m = re.match(r'^(.*?\(\d{4}\))', title)
    if m:
        return m.group(1)
    return title.split('-')[0].strip()

def main():
    import argparse
    parser = argparse.ArgumentParser(description="KHInsider Album Downloader (CLI, multi-threaded, tqdm progress)")
    parser.add_argument("--url", help="Album URL")
    parser.add_argument("--folder", help="Download directory", default=os.getcwd())
    args = parser.parse_args()

    # ask for album URL if not given on the command line
    if not args.url:
        args.url = input("Album URL: ").strip()
    if not args.url:
        print("No album URL provided.")
        return

    # ask for folder if not given
    if not args.folder or args.folder.strip() == "" or args.folder == os.getcwd():
        folder = input("Where do you want to save the album? (enter full folder path): ").strip()
        if not folder:
            confirm = input(f"No folder entered. Save to current directory?\n{os.getcwd()}\n(Y/n): ").strip().lower()
            if confirm == 'n':
                print("Aborted. Please run again and specify a folder.")
                return
            folder = os.getcwd()
        args.folder = folder

    print("Fetching album info...")
    album_info = get_album_info(args.url)
    full_title = album_info["title"] if album_info and "title" in album_info else "KHInsider Album"
    album_title = clean_album_title(full_title)
    album_folder = safe_foldername(album_title)
    save_dir = os.path.join(args.folder, album_folder)
    os.makedirs(save_dir, exist_ok=True)
    tracks = album_info["tracks"]
    artist = album_info.get("artist") or ""
    album = album_title

    print(f"Album: {album_title}")
    print(f"Tracks: {len(tracks)}\n")

    album_art_urls = album_info["art_urls"]
    album_art_path = None
    for idx, art_url in enumerate(album_art_urls):
        art_path_try = os.path.join(save_dir, f"album_art_{idx}.jpg")
        if download_album_art(art_url, art_path_try):
            album_art_path = art_path_try
            break

    total_tracks = len(tracks)
    stop_event = threading.Event()
    main_bar = tqdm(
        total=total_tracks,
        desc="Downloaded",
        position=0,
        leave=True,
        bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} {postfix}',
        dynamic_ncols=False
    )
    progress_bars = {}

    def download_one(i, track):
        if stop_event.is_set():
            return
        try:
            fmt = "MP3"
            download_link = get_download_link(track["page_url"], fmt)
            if not download_link:
                main_bar.update(1)
                return
            number = i + 1
            track_title = track["title"]
            ext = download_link.split('.')[-1].split('?')[0]
            filename = f"{number:02d}. {safe_filename(track_title)}.{ext}"
            save_path = os.path.join(save_dir, filename)

            def progress_callback(dl, total):
                bar = progress_bars.get(i)
                if bar and total:
                    bar.total = total
                    bar.n = dl
                    bar.refresh()

            progress_bars[i] = tqdm(
                total=1,
                desc=f"{filename[:36]}",
                position=i+1,
                leave=True,
                unit='B',
                unit_scale=True,
                dynamic_ncols=False
            )
            download_file(download_link, save_path, progress_callback)
            bar = progress_bars[i]
            bar.n = bar.total
            bar.refresh()

            if ext.lower() == "mp3" and album_art_path:
                try:
                    clean_title = strip_leading_number(track_title)
                    embed_album_art(
                        save_path,
                        album_art_path,
                        title=clean_title,
                        artist=artist,
                        album=album,
                        track_number=number
                    )
                except Exception:
                    pass
            main_bar.update(1)
        except Exception as e:
            tqdm.write(f"\nError downloading track: {track.get('title')} ({e})")
            main_bar.update(1)

    try:
        # change max_workers=4 if you want to increase the number of concurrent downloads
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(download_one, i, track) for i, track in enumerate(tracks)]
            for f in futures:
                try:
                    f.result()
                except KeyboardInterrupt:
                    tqdm.write("Cancelling, please wait for downloads in progress to finish...")
                    stop_event.set()
                    break
        main_bar.close()
        tqdm.write("All done or aborted.")
    except KeyboardInterrupt:
        tqdm.write("Aborted by user (Ctrl+C). Exiting.")
        stop_event.set()

if __name__ == "__main__":
    main()
