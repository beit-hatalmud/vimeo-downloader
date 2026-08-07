"""YouTube downloader using Piped/Invidious APIs - runs on GitHub Actions"""
import requests, os, sys, subprocess

url = sys.argv[1] if len(sys.argv) > 1 else ""
if not url:
    print("Usage: python youtube_download.py <youtube_url>")
    sys.exit(1)

# Extract video ID
vid = ""
if "v=" in url:
    vid = url.split("v=")[1].split("&")[0]
elif "youtu.be/" in url:
    vid = url.split("youtu.be/")[1].split("?")[0]
print(f"Video ID: {vid}")

os.makedirs("videos", exist_ok=True)
ok = False

# Method 1: Piped instances
print("\n=== Piped ===")
piped_instances = [
    "pipedapi.kavin.rocks",
    "pipedapi.adminforge.de",
    "api.piped.privacydev.net",
    "pipedapi.in.projectsegfau.lt",
    "pipedapi.darkness.services",
]
for inst in piped_instances:
    try:
        api_url = f"https://{inst}/streams/{vid}"
        print(f"  Trying: {api_url}")
        r = requests.get(api_url, timeout=15)
        if r.status_code != 200:
            print(f"  Status: {r.status_code}")
            continue
        data = r.json()
        streams = data.get("videoStreams", [])
        title = data.get("title", "youtube_video")
        print(f"  Found: {len(streams)} streams, title: {title}")

        # Prefer non-video-only stream (has audio included)
        best = None
        for s in streams:
            if not s.get("videoOnly", True):
                best = s
                break
        # Fallback to any stream
        if not best and streams:
            best = streams[0]

        if best:
            print(f"  Downloading: {best.get('quality','')} {best.get('format','')}")
            r2 = requests.get(best["url"], stream=True, timeout=300)
            ext = "mp4" if "mp4" in best.get("mimeType", "") else "webm"
            fname = f"videos/{title}.{ext}"
            with open(fname, "wb") as f:
                for chunk in r2.iter_content(8192):
                    f.write(chunk)
            size = os.path.getsize(fname)
            if size > 10000:
                print(f"  SUCCESS: {size/1024/1024:.1f} MB -> {fname}")
                ok = True
                break
            else:
                print(f"  Too small: {size} bytes")
                os.remove(fname)
    except Exception as e:
        print(f"  Error: {e}")

# Method 2: Invidious
if not ok:
    print("\n=== Invidious ===")
    inv_instances = [
        "inv.nadeko.net",
        "invidious.nerdvpn.de",
        "invidious.privacyredirect.com",
        "invidious.protokolla.fi",
    ]
    for inst in inv_instances:
        try:
            api_url = f"https://{inst}/api/v1/videos/{vid}"
            print(f"  Trying: {api_url}")
            r = requests.get(api_url, timeout=15)
            if r.status_code != 200:
                print(f"  Status: {r.status_code}")
                continue
            data = r.json()
            title = data.get("title", "youtube_video")
            fmts = data.get("formatStreams", [])
            print(f"  Found: {len(fmts)} formats, title: {title}")

            for fmt in fmts:
                dl_url = fmt.get("url", "")
                if not dl_url:
                    continue
                quality = fmt.get("qualityLabel", "")
                print(f"  Downloading: {quality}")
                r2 = requests.get(dl_url, stream=True, timeout=300)
                fname = f"videos/{title}.mp4"
                with open(fname, "wb") as f:
                    for chunk in r2.iter_content(8192):
                        f.write(chunk)
                size = os.path.getsize(fname)
                if size > 10000:
                    print(f"  SUCCESS: {size/1024/1024:.1f} MB")
                    ok = True
                    break
            if ok:
                break
        except Exception as e:
            print(f"  Error: {e}")

# Method 3: yt-dlp as last resort
if not ok:
    print("\n=== yt-dlp ===")
    subprocess.run(["yt-dlp", "--no-overwrites", "-o", "videos/%(title)s.%(ext)s", url])

# Check results
files = [f for f in os.listdir("videos") if os.path.getsize(f"videos/{f}") > 1000]
print(f"\n=== Result: {len(files)} files ===")
for f in files:
    print(f"  {f}: {os.path.getsize(f'videos/{f}')/1024/1024:.1f} MB")

sys.exit(0 if files else 1)
