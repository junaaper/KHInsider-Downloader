# KHInsider Album Downloader (CLI)

A fast, fully automated __command-line tool__ for downloading entire soundtracks from [KHInsider](https://downloads.khinsider.com/) complete with album art, track metadata, artist, album, and track numbers.  

---

## Features

- **Batch download** any KHInsider album by URL
- __Automatic tagging__:  
  - Sets track number, album name, track title, artist (parsed from the site)
  - Album art embedded in every MP3  
- **Multi-threaded**: Downloads up to 4 tracks at a time for speed (customizable)
- **Beautiful progress bars** with `tqdm`
---

## Quickstart

1. **Install dependencies**:
    ```bash
    pip install requests beautifulsoup4 mutagen tqdm
    ```

2. **Clone this repo**:
    ```bash
    git clone https://github.com/yourusername/khinsider-downloader.git
    cd khinsider-downloader
    ```

3. **Run the script!**
    ```bash
    python main.py
    ```

    You will be prompted for:
    - The KHInsider album URL  
    - The folder where you want the album to be saved

    Example:
    ```
    Album URL: https://downloads.khinsider.com/game-soundtracks/album/sifu-2022
    Where do you want to save the album? (enter full folder path): C:\Music
    ```
    Another way to use it:
    ```bash
    python main.py --url "https://downloads.khinsider.com/game-soundtracks/album/mario-kart-8-full-gamerip" --folder "C:\Music"
    ```


All tracks will be saved to:
C:\Music\Sifu (2022)\01. Martial Mastery.mp3, etc.


## Settings
Threads:
By default, downloads up to 4 tracks at once. You can change this in main.py:

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:

## Requirements

    requests

    beautifulsoup4

    tqdm

    mutagen

Install them with:
```bash
pip install requests beautifulsoup4 mutagen tqdm
```
