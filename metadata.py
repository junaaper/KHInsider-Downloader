from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TRCK, error

def embed_album_art(mp3_file, art_path, title=None, artist=None, album=None, track_number=None):
    audio = MP3(mp3_file, ID3=ID3)
    try:
        audio.add_tags()
    except error:
        pass
    if title:
        audio.tags['TIT2'] = TIT2(encoding=3, text=title)
    if artist:
        audio.tags['TPE1'] = TPE1(encoding=3, text=artist)
    if album:
        audio.tags['TALB'] = TALB(encoding=3, text=album)
    if track_number:
        audio.tags['TRCK'] = TRCK(encoding=3, text=str(track_number))
    with open(art_path, 'rb') as img:
        audio.tags['APIC'] = APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc=u'Cover',
            data=img.read()
        )
    audio.save()
