"""Batch download multiple NLI items via FlareSolverr → Rosetta → Drive."""
import sys, os, re, json, glob, time
import requests as plain_req
from pathlib import Path

flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

def flare_get(target):
    try:
        r = plain_req.post(flaresolverr_url, json={
            "cmd": "request.get", "url": target, "maxTimeout": 60000
        }, timeout=120)
        d = r.json()
        if d.get("status") == "ok":
            sol = d.get("solution", {})
            return sol.get("response", ""), sol.get("cookies", [])
    except Exception as e:
        print(f"  flare err: {e}")
    return None, None

def get_drive_token():
    tk = plain_req.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["CLIENT_ID"],
        "client_secret": os.environ["CLIENT_SECRET"],
        "refresh_token": os.environ["REFRESH_TOKEN"],
        "grant_type": "refresh_token"
    }).json()["access_token"]
    return tk

def get_or_create_folder(headers, name):
    r = plain_req.get("https://www.googleapis.com/drive/v3/files",
        params={"q": f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
                "fields": "files(id)"}, headers=headers)
    files = r.json().get("files", [])
    if files: return files[0]["id"]
    return plain_req.post("https://www.googleapis.com/drive/v3/files",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": name, "mimeType": "application/vnd.google-apps.folder"}).json()["id"]

def upload_to_drive(headers, folder_id, fpath, fname):
    init = plain_req.post(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name,webViewLink",
        headers={**headers, "Content-Type": "application/json"},
        json={"name": fname, "parents": [folder_id]}
    )
    up_url = init.headers.get("Location")
    with open(fpath, "rb") as f:
        up = plain_req.put(up_url, data=f, headers={"Content-Type": "audio/mpeg"})
    return up.json() if up.ok else None

def download_one(url, idx, total):
    print(f"\n========== [{idx}/{total}] {url} ==========")
    html, cookies = flare_get(url)
    if not html:
        print("  flare failed")
        return None

    mms = re.search(r'NNL_ALEPH(\d+)', url)
    mms_id = mms.group(1) if mms else "unknown"

    # Title from <title>
    title_m = re.search(r'<title>([^<]+)</title>', html)
    title = re.sub(r'\s+', ' ', (title_m.group(1) if title_m else "")).strip()
    title = re.sub(r'\s*-\s*הספרייה הלאומית.*$', '', title).strip()
    title = title[:120] or f"NLI_{mms_id}"
    print(f"  title: {title}")

    # Find FL pids
    fl_pids = list(set(re.findall(r'\bFL(\d{6,12})\b', html)))
    print(f"  FL pids found: {len(fl_pids)}")
    if not fl_pids:
        return None

    cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in (cookies or []))
    sess = plain_req.Session()
    sess.headers.update({
        "Cookie": cookie_hdr,
        "Referer": url,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
    })

    # HEAD probe each FL
    audio_fl = []
    for fid in fl_pids:
        stream_url = f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=FL{fid}&dps_func=stream"
        try:
            r4 = sess.head(stream_url, timeout=15, allow_redirects=True)
            ct = r4.headers.get('content-type','')
            sz = int(r4.headers.get('content-length','0') or 0)
            if any(x in ct.lower() for x in ['image/jpeg','image/jpg','image/png','image/gif','image/webp']):
                continue
            if sz > 1_000_000:
                audio_fl.append((fid, ct, sz))
        except Exception as e:
            pass

    audio_fl.sort(key=lambda x: -x[2])
    if not audio_fl:
        print("  no audio FL found")
        return None

    fid, ct, sz = audio_fl[0]
    print(f"  best: FL{fid} ({sz/1024/1024:.1f} MB, ct={ct})")

    # Sanitize filename
    safe = re.sub(r'[\\/:*?"<>|]', '_', title)
    out = f"videos/{safe}.mp3"
    stream_url = f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=FL{fid}&dps_func=stream"

    try:
        with sess.get(stream_url, stream=True, timeout=(30, 600), allow_redirects=True) as r5:
            r5.raise_for_status()
            with open(out, 'wb') as f:
                total_b = 0
                for chunk in r5.iter_content(chunk_size=1<<20):
                    if chunk:
                        f.write(chunk); total_b += len(chunk)
        size_mb = os.path.getsize(out)/1024/1024
        print(f"  downloaded: {size_mb:.1f} MB")
        if os.path.getsize(out) < 200_000:
            os.remove(out)
            return None
        return out
    except Exception as e:
        print(f"  download err: {e}")
        return None

def main():
    urls_file = sys.argv[1] if len(sys.argv) > 1 else "related_urls.json"
    if urls_file.endswith(".json"):
        with open(urls_file) as f: urls = json.load(f)
    else:
        with open(urls_file) as f: urls = [l.strip() for l in f if l.strip()]
    print(f"Loaded {len(urls)} URLs")

    os.makedirs("videos", exist_ok=True)
    drive_token = get_drive_token()
    headers = {"Authorization": f"Bearer {drive_token}"}
    folder_id = get_or_create_folder(headers, "סרטונים שהורדו")
    print(f"Drive folder: {folder_id}")

    results = []
    for i, u in enumerate(urls, 1):
        path = download_one(u, i, len(urls))
        if path:
            fname = os.path.basename(path)
            up = upload_to_drive(headers, folder_id, path, fname)
            if up:
                print(f"  → DRIVE: {up.get('webViewLink','')}")
                results.append({"url": u, "file": fname, "drive_id": up["id"], "link": up.get("webViewLink")})
                os.remove(path)
        time.sleep(2)  # gentle on Cloudflare

    with open("nli_batch_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n=== Done. {len(results)}/{len(urls)} uploaded ===")

if __name__ == "__main__":
    main()
