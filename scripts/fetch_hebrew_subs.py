#!/usr/bin/env python3
"""Look up Hebrew subtitles for a movie via IMDb + wizdom.xyz.

Usage: fetch_hebrew_subs.py "<title>" <year> <output_srt_path>
Exits 0 on success (writes UTF-8 .srt), 1 on any failure.
Prints diagnostic lines to stderr.
"""
import sys, json, urllib.parse, urllib.request, zipfile, io, os, re

UA = {'User-Agent': 'Mozilla/5.0'}


def log(*a):
    print(*a, file=sys.stderr)


def get_imdb_id(title: str, year: str) -> str:
    q = urllib.parse.quote(f"{title}")
    url = f"https://v3.sg.media-imdb.com/suggestion/x/{q}.json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read())
    except Exception as e:
        log(f"imdb suggest err: {e}"); return ''
    feats = [r for r in d.get('d', []) if r.get('q') == 'feature']
    # Prefer exact year match
    for r in feats:
        if str(r.get('y', '')) == str(year):
            return r['id']
    return feats[0]['id'] if feats else ''


def get_wizdom_sub(imdb_id: str) -> bytes:
    """Returns the .srt bytes of the most-downloaded Hebrew sub, or b''."""
    url = f"https://wizdom.xyz/api/releases/imdb/{imdb_id}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
            d = json.loads(r.read())
    except Exception as e:
        log(f"wizdom list err: {e}"); return b''

    # Response shape varies — handle list, dict-with-'subs', or dict keyed by lang.
    subs = []
    if isinstance(d, list):
        subs = d
    elif isinstance(d, dict):
        if 'subs' in d:
            v = d['subs']
            subs = v.get('he', []) if isinstance(v, dict) else (v if isinstance(v, list) else [])
        elif 'he' in d:
            subs = d['he']
        else:
            # Last resort — flatten one level
            for k, v in d.items():
                if isinstance(v, list):
                    subs = v; break

    if not subs:
        log(f"wizdom: no Hebrew subs for {imdb_id}"); return b''
    # Pick best by downloads or score
    best = max(subs, key=lambda s: int(s.get('downloads') or s.get('score') or 0))
    sid = best.get('id') or best.get('subtitle_id')
    if not sid:
        log(f"wizdom: no id in best entry: {best}"); return b''

    dl = f"https://wizdom.xyz/api/files/sub/{sid}"
    try:
        with urllib.request.urlopen(urllib.request.Request(dl, headers=UA), timeout=30) as r:
            return r.read()
    except Exception as e:
        log(f"wizdom dl err: {e}"); return b''


def extract_srt(zip_bytes: bytes) -> bytes:
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        # Already a raw .srt
        return zip_bytes if zip_bytes.lstrip()[:1].isdigit() else b''
    srts = [n for n in z.namelist() if n.lower().endswith('.srt')]
    if not srts:
        return b''
    # Prefer the largest .srt (least likely to be 'donate' / 'readme' files)
    srts.sort(key=lambda n: -z.getinfo(n).file_size)
    return z.read(srts[0])


def decode_srt(raw: bytes) -> str:
    for enc in ('utf-8', 'utf-8-sig', 'cp1255', 'iso-8859-8', 'windows-1255'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def main():
    if len(sys.argv) < 4:
        log("usage: fetch_hebrew_subs.py <title> <year> <out.srt>")
        sys.exit(1)
    title, year, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    imdb = get_imdb_id(title, year)
    if not imdb:
        log(f"no IMDb match for {title!r} ({year})"); sys.exit(1)
    log(f"IMDb: {imdb}")
    raw = get_wizdom_sub(imdb)
    if not raw:
        sys.exit(1)
    srt = extract_srt(raw)
    if not srt:
        log("no .srt inside response"); sys.exit(1)
    text = decode_srt(srt)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    log(f"wrote {len(text)} chars to {out_path}")


if __name__ == '__main__':
    main()
