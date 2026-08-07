#!/usr/bin/env python3
"""
local_dl_to_drive.py - מוריד מכל URL ומעלה ישירות לדרייב.
מריץ מהמחשב של יוסף = IP ישראלי = גישה לכל ערוצי ישראל.

שימוש:
  python local_dl_to_drive.py <URL> [תיקיית-דרייב]

דוגמאות:
  python local_dl_to_drive.py https://www.mako.co.il/... "ערוץ 12"
  python local_dl_to_drive.py https://www.kan.org.il/... "כאן 11"
  python local_dl_to_drive.py https://www.reshet.tv/... "ערוץ 13"
  python local_dl_to_drive.py https://www.youtube.com/... "YouTube"
"""
import sys, os, subprocess, glob, time, mimetypes, json
import requests

NO_WIN = subprocess.CREATE_NO_WINDOW

# טוען creds מה-CLAUDE.md deploy creds (זמינים בכל סשן)
def _get_creds():
    # טוען מ-secrets.json הגלובלי
    secrets_path = os.path.expanduser(r"~\.claude\secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, encoding="utf-8") as f:
            d = json.load(f)
        return d["DRIVE_CLIENT_ID"], d["DRIVE_CLIENT_SECRET"], d["DRIVE_REFRESH_TOKEN"]
    # fallback: environment variables
    return (os.environ["GOOGLE_CLIENT_ID"],
            os.environ["GOOGLE_CLIENT_SECRET"],
            os.environ["GOOGLE_REFRESH_TOKEN"])


def get_token():
    cid, csec, rt = _get_creds()
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cid, "client_secret": csec,
        "refresh_token": rt, "grant_type": "refresh_token"
    })
    return r.json()["access_token"]


def get_or_create_folder(token, name):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get("https://www.googleapis.com/drive/v3/files",
        params={"q": f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "files(id)"}, headers=headers)
    files = r.json().get("files", [])
    if files:
        return files[0]["id"]
    r2 = requests.post("https://www.googleapis.com/drive/v3/files",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": name, "mimeType": "application/vnd.google-apps.folder"})
    return r2.json()["id"]


def upload(token, fpath, folder_id):
    headers = {"Authorization": f"Bearer {token}"}
    fname = os.path.basename(fpath)
    size = os.path.getsize(fpath)
    mime = mimetypes.guess_type(fname)[0] or "video/mp4"
    print(f"  מעלה: {fname} ({size/1024/1024:.1f} MB)...")
    r = requests.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": fname, "parents": [folder_id]}
    )
    if r.status_code != 200:
        print(f"  שגיאה ב-init: {r.status_code}")
        return None
    with open(fpath, "rb") as f:
        r2 = requests.put(r.headers["Location"], data=f, headers={"Content-Type": mime})
    if r2.status_code == 200:
        fid = r2.json()["id"]
        print(f"  הועלה! https://drive.google.com/file/d/{fid}/view")
        return fid
    print(f"  נכשל: {r2.status_code}")
    return None


def download(url, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    def has_files():
        return bool([f for f in glob.glob(f"{out_dir}/*") if os.path.getsize(f) > 10000])

    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    methods = [
        # 1: default - מכסה 1000+ אתרים
        ["yt-dlp", "--no-overwrites", "--merge-output-format", "mp4",
         "-f", "bv*+ba/b", "-o", f"{out_dir}/%(title)s.%(ext)s", url],
        # 2: impersonate chrome
        ["yt-dlp", "--impersonate", "chrome", "--no-overwrites", "--merge-output-format", "mp4",
         "-f", "bv*+ba/b", "-o", f"{out_dir}/%(title)s.%(ext)s", url],
        # 3: geo-bypass IL + referer (לאתרים ישראליים)
        ["yt-dlp", "--geo-bypass-country", "IL",
         "--add-header", f"Referer:{domain}",
         "--add-header", "Accept-Language:he-IL,he;q=0.9",
         "--no-overwrites", "--merge-output-format", "mp4",
         "-f", "bv*+ba/b", "-o", f"{out_dir}/%(title)s.%(ext)s", url],
        # 4: impersonate safari
        ["yt-dlp", "--impersonate", "safari", "--geo-bypass-country", "IL",
         "--no-overwrites", "--merge-output-format", "mp4",
         "-f", "bv*+ba/b", "-o", f"{out_dir}/%(title)s.%(ext)s", url],
        # 5: audio fallback
        ["yt-dlp", "--no-overwrites", "-x", "--audio-format", "mp3",
         "-o", f"{out_dir}/%(title)s.%(ext)s", url],
    ]

    for i, cmd in enumerate(methods, 1):
        print(f"--- שיטה {i}: {' '.join(cmd[1:4])} ---")
        subprocess.run(cmd, creationflags=NO_WIN)
        if has_files():
            return [f for f in glob.glob(f"{out_dir}/*") if os.path.getsize(f) > 10000]

    # streamlink (לסטרימים חיים)
    print("--- שיטה 6: streamlink ---")
    subprocess.run(["streamlink", "--output", f"{out_dir}/stream.mp4", url, "best"],
                   creationflags=NO_WIN)
    if has_files():
        return [f for f in glob.glob(f"{out_dir}/*") if os.path.getsize(f) > 10000]

    # Playwright - חילוץ stream URL מהדפדפן
    print("--- שיטה 7: Playwright stream extraction ---")
    try:
        from playwright.sync_api import sync_playwright
        streams = []

        def on_response(response):
            rurl = response.url
            ct = response.headers.get("content-type", "")
            if any(x in rurl for x in [".m3u8", "manifest", "chunklist"]) or "mpegurl" in ct:
                streams.append(rurl)
            elif any(x in rurl for x in [".mp4", ".webm"]) and len(rurl) > 40:
                streams.append(rurl)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                locale="he-IL", timezone_id="Asia/Jerusalem",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = ctx.new_page()
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                for sel in ["button[class*='play']", ".vjs-big-play-button",
                            "[aria-label='Play']", "[aria-label='נגן']", ".jw-icon-display"]:
                    try:
                        page.click(sel, timeout=1000)
                        time.sleep(4)
                        break
                    except:
                        pass
                time.sleep(5)
            except Exception as e:
                print(f"  שגיאת דף: {e}")
            browser.close()

        print(f"  נמצאו {len(streams)} streams")
        for s in list(set(streams))[:5]:
            print(f"  {s[:100]}")
            subprocess.run(
                ["yt-dlp", "--no-overwrites", "--merge-output-format", "mp4",
                 "-o", f"{out_dir}/%(title)s.%(ext)s", s],
                creationflags=NO_WIN
            )
            if has_files():
                return [f for f in glob.glob(f"{out_dir}/*") if os.path.getsize(f) > 10000]
            # ffmpeg fallback לHLS
            if ".m3u8" in s:
                subprocess.run(
                    ["ffmpeg", "-i", s, "-c", "copy", f"{out_dir}/stream_playwright.mp4"],
                    creationflags=NO_WIN
                )
                if has_files():
                    return [f for f in glob.glob(f"{out_dir}/*") if os.path.getsize(f) > 10000]

    except ImportError:
        print("  Playwright לא מותקן - הרץ: pip install playwright && playwright install chromium")
    except Exception as e:
        print(f"  שגיאת Playwright: {e}")

    return []


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    url = sys.argv[1]
    folder_name = sys.argv[2] if len(sys.argv) > 2 else "הורדות"
    out_dir = r"C:\tmp\dl_temp"

    print(f"\nמוריד: {url}")
    print(f"תיקיית דרייב: {folder_name}\n")

    files = download(url, out_dir)

    if not files:
        print("\nERROR: לא הצלחתי להוריד מאף שיטה")
        sys.exit(1)

    print(f"\nמעלה {len(files)} קבצים לדרייב...")
    token = get_token()
    folder_id = get_or_create_folder(token, folder_name)
    for f in files:
        upload(token, f, folder_id)
    print("\nסיום!")
