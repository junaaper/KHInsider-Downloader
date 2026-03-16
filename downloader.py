import os
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
    title = soup.find("title").text.strip()


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
                album = title

    if not album:
        album = title
    if not artist:
        summary = soup.find("div", class_="albumHeader")
        if summary and "by" in summary.text:
            artist = summary.text.split("by")[-1].split("(")[0].strip()

    # prefer HQ art from template if available
    hq_art_candidates = get_album_slug_and_hq_cover(album_url)
    art_urls = []
    cover_div = soup.find("div", {"class": "albumImage"})
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
    album_art_order = hq_art_candidates + art_urls

    # tracks
    tracks = []
    track_table = None
    for table in soup.find_all("table"):
        headers = [th.text.strip() for th in table.find_all("th")]
        if any("Song Name" in h for h in headers):
            track_table = table
            ths = headers
            break
    if not track_table:
        raise Exception("Could not find tracklist table. Found tables: " +
                        str([ [th.text.strip() for th in t.find_all("th")] for t in soup.find_all("table") ]))
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

    return {"title": title, "art_urls": album_art_order, "tracks": tracks, "artist": artist, "album": album}

def get_download_link(track_page_url, fmt="MP3"):
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(track_page_url, headers=headers)
    soup = BeautifulSoup(r.text, "html.parser")
    allowed_domains = ("downloads.khinsider.com", "vgmtreasurechest.com", "vgmsite.com")
    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href and (fmt.lower() in href.lower()) and (href.lower().endswith('.mp3') or href.lower().endswith('.ogg')):
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
