import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse

def get_album_slug_and_hq_cover(album_url):
    slug = album_url.rstrip("/").split("/")[-1]
    hq_cover_jpg = f"https://vgmtreasurechest.com/soundtracks/{slug}/Cover.jpg"
    hq_cover_png = f"https://vgmtreasurechest.com/soundtracks/{slug}/Cover.png"
    vgmsite_cover = f"https://vgmsite.com/soundtracks/{slug}/0%20-%20cover.png"
    return [hq_cover_jpg, hq_cover_png, vgmsite_cover]

def get_album_info(album_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(album_url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")
    raw_title = soup.find("title").text.strip()

    # Clean title: prefer <h2> (just the game name), append year from <title> if found
    h2 = soup.find("h2")
    if h2:
        clean_name = h2.text.strip()
    else:
        # Fallback: strip " MP3 - Download..." suffix from <title>
        clean_name = re.split(r'\s+MP3\s', raw_title)[0].strip()
        # Remove parenthetical platform/type tags, keep only year
        clean_name = re.sub(r'\s*\([^)]*\)\s*', ' ', clean_name).strip()

    # Extract year from raw title
    year_match = re.search(r'\((\d{4})\)', raw_title)
    year = year_match.group(1) if year_match else None
    if year and f"({year})" not in clean_name:
        clean_name = f"{clean_name} ({year})"

    artist = None
    album = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            th = row.find("th")
            td = row.find("td")
            if not th or not td: continue
            if "Published by" in th.text:
                artist = td.text.strip().split(",")[0]
            if "Album type" in th.text:
                album = clean_name

    if not album:
        album = clean_name
    if not artist:
        summary = soup.find("div", class_="albumHeader")
        if summary and "by" in summary.text:
            artist = summary.text.split("by")[-1].split("(")[0].strip()

    # Extract HD art link from clickable album image (highest priority)
    hd_art_link = None
    cover_div = soup.find("div", {"class": "albumImage"})
    if cover_div:
        a_tag = cover_div.find("a")
        if a_tag and a_tag.get("href"):
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://downloads.khinsider.com" + href
            hd_art_link = href

    # Template-based HQ art candidates
    hq_art_candidates = get_album_slug_and_hq_cover(album_url)

    # Page-provided art as fallback
    art_urls = []
    if cover_div:
        art_tags = cover_div.find_all("img")
        for img in art_tags:
            src = img.get("src")
            if src and src.startswith("/"):
                src = "https://downloads.khinsider.com" + src
            if src and src not in art_urls:
                art_urls.append(src)
    if not art_urls:
        for img in soup.find_all("img", {"class": "albumImage"}):
            src = img.get("src")
            if src and src.startswith("/"):
                src = "https://downloads.khinsider.com" + src
            if src and src not in art_urls:
                art_urls.append(src)
    if not art_urls:
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and "/albums/" in src:
                if src.startswith("/"):
                    src = "https://downloads.khinsider.com" + src
                if src not in art_urls:
                    art_urls.append(src)

    album_art_order = ([hd_art_link] if hd_art_link else []) + hq_art_candidates + art_urls

    # Detect available formats and sizes from table headers
    available_formats = []
    format_sizes = {}
    tracks = []
    track_table = None
    for table in soup.find_all("table"):
        table_headers = [th.text.strip() for th in table.find_all("th")]
        if any("Song Name" in h for h in table_headers):
            track_table = table
            ths = table_headers
            break
    if not track_table:
        raise Exception("Could not find tracklist table.")

    # Find format columns and their sizes from the header row
    # Headers look like: ['', '#', 'Song Name', 'MP3', 'FLAC', '', '', 'Total:', '1h 56m', '239 MB', '1,740 MB', '']
    fmt_col_indices = []
    for idx_h, h in enumerate(ths):
        h_upper = h.upper()
        if h_upper in ("MP3", "FLAC", "OGG"):
            available_formats.append(h_upper)
            fmt_col_indices.append((h_upper, idx_h))
    if not available_formats:
        available_formats = ["MP3"]

    # Extract sizes: after "Total:" in headers, sizes align with format columns
    if "Total:" in ths:
        total_idx = ths.index("Total:")
        # The size values follow Total: and duration, matching format column order
        size_values = [h for h in ths[total_idx+1:] if "MB" in h or "GB" in h]
        for i, (fmt_name, _) in enumerate(fmt_col_indices):
            if i < len(size_values):
                format_sizes[fmt_name] = size_values[i]

    try:
        name_col_idx = ths.index("Song Name")
    except ValueError:
        name_col_idx = 1

    for row in track_table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) <= name_col_idx:
            continue
        link = cols[name_col_idx].find("a")
        if not link or "/game-soundtracks/album/" not in link.get("href", ""):
            continue
        tracks.append({
            "title": link.text.strip(),
            "page_url": "https://downloads.khinsider.com" + link["href"]
        })

    return {
        "title": clean_name,
        "art_urls": album_art_order,
        "tracks": tracks,
        "artist": artist,
        "album": album,
        "formats": available_formats,
        "format_sizes": format_sizes,
    }

def get_download_link(track_page_url, fmt="MP3"):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(track_page_url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")
    allowed_domains = ("downloads.khinsider.com", "vgmtreasurechest.com", "vgmsite.com")
    ext_map = {"MP3": ".mp3", "FLAC": ".flac", "OGG": ".ogg"}
    target_ext = ext_map.get(fmt.upper(), f".{fmt.lower()}")
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href and href.lower().endswith(target_ext):
            if not href.startswith("http"):
                href = "https://downloads.khinsider.com" + href
            domain = urlparse(href).netloc
            if any(domain.endswith(ad) for ad in allowed_domains):
                return href
    return None

def download_album_art(art_url, save_path):
    if not art_url: return None
    try:
        r = requests.get(art_url, stream=True, timeout=10)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return save_path
    except Exception:
        pass
    return None

def download_file(url, save_path, progress_callback=None):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, stream=True)
    if r.status_code != 200:
        return False
    total = int(r.headers.get('content-length', 0))
    downloaded = 0
    with open(save_path, "wb") as f:
        for chunk in r.iter_content(1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
    return True
