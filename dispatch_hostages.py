#!/usr/bin/env python3
"""Dispatch Hostages (חטופים — ראיונות וסיפורי שבי) YouTube videos through hostages-batch.yml.

- Reads URLs from a list (one per line). Accepts either:
    https://www.youtube.com/watch?v=VIDEOID
    VIDEOID
    VIDEOID|title
- Throttles at MAX_QUEUE in-flight workflow runs
- Skips videos already in the destination Drive folder (matched by sanitized title)
- Logs progress to hostages_progress.txt next to this script
- Always sends the request to the workflow with the root folder id; the workflow
  itself routes per file to the proper subfolder based on the title.

Usage:
  python dispatch_hostages.py <url_list.txt> [--limit N] [--start N] [--max-queue N]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

REPO = "yossi6742853/vimeo-downloader"
WORKFLOW = "hostages-batch.yml"
ROOT_FOLDER_ID = "1tGjPhRZ-FIvNtFwLERFJiYGVLVNjZ_57"
SUBFOLDER_IDS = [
    "1mj4oZdy3dWUKLR4cicdwSePXRkAgdR-s",  # ראיונות אישיים
    "1QEzQoOWdtwwf0aTMJRvE2ix95Jekbrlo",  # סיפורי שבי
    "136NMrQ8FEkD_8AZ_YvDCns81lIdnL5BS",  # מהדורות חדשות
    "1IgMDdUFsgZ0_FhJtNQBpCyVpwv9bBju_",  # תיעוד וכתבות
]

CLIENT_ID = "1072944905499-vm2v2i5dvn0a0d2o4ca36i1vge8cvbn0.apps.googleusercontent.com"
CLIENT_SECRET = "v6V3fKV_zWU7iw1DrpO1rknX"
REFRESH_TOKEN = "1//03doYP5sR8165CgYIARAAGAMSNwF-L9Irwt3jH4FHlYkKBcdcEr_DCirl7AWT7Uxf36-gUtqITAWqJx-vLRNyMcDprd91JtFuhLc"

MAX_QUEUE = 25
POLL_SECONDS = 30
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hostages_progress.txt")


def log(msg: str):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def get_drive_token() -> str:
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token"
    }).encode()
    r = urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30)
    return json.loads(r.read())["access_token"]


def list_existing_titles(token: str) -> set:
    """Collect file names already in any subfolder of the Hostages root."""
    seen = set()
    headers = {"Authorization": f"Bearer {token}"}
    for fid in SUBFOLDER_IDS:
        page_token = None
        while True:
            params = {
                "q": f"'{fid}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
                "fields": "nextPageToken,files(id,name)",
                "pageSize": "1000",
            }
            if page_token:
                params["pageToken"] = page_token
            url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers=headers)
            try:
                resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
            except Exception as e:
                log(f"  warn: list folder {fid} failed: {e}")
                break
            for f in resp.get("files", []):
                seen.add(f["name"])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
    return seen


def normalize_title(t: str) -> str:
    """Best-effort match between YouTube title and saved filename."""
    t = t.strip()
    t = re.sub(r"\.(mp4|mkv|webm|mp3|m4a)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r'["\'“”‘’]', "", t)
    return t.lower()


def gh_json(args, max_retry: int = 3):
    last = None
    for _ in range(max_retry):
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if r.returncode == 0 and r.stdout.strip():
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                last = r.stdout
        else:
            last = r.stderr
        time.sleep(2)
    raise RuntimeError(f"gh failed: {' '.join(args)} -> {last}")


def in_flight_count() -> int:
    try:
        data = gh_json([
            "gh", "run", "list", "--repo", REPO, "--workflow", WORKFLOW,
            "--limit", "60", "--json", "status",
        ])
    except Exception as e:
        log(f"  warn: in_flight_count failed: {e}")
        return MAX_QUEUE
    return sum(1 for r in data if r.get("status") in ("queued", "in_progress", "waiting"))


def dispatch(url: str) -> bool:
    cmd = [
        "gh", "workflow", "run", WORKFLOW,
        "--repo", REPO,
        "-f", f"url={url}",
        "-f", f"folder_id={ROOT_FOLDER_ID}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        log(f"  ERR: {r.stderr.strip()[:300]}")
        return False
    return True


_VID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})")


def extract_vid(s: str):
    """Return 11-char YouTube id from URL or raw id, else None."""
    s = s.strip()
    if not s:
        return None
    m = _VID_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return None


def load_videos(path: str):
    """Accepts:
      <full-url>
      <id>
      <id>|<title>
      <full-url>|<title>
    """
    out = []
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 1)
            head = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else ""
            vid = extract_vid(head)
            if not vid:
                continue
            if vid in seen:
                continue
            seen.add(vid)
            out.append((vid, title))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("list", help="Path to URL list (urls/ids, one per line, optional |title)")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--max-queue", type=int, default=MAX_QUEUE)
    args = p.parse_args()

    log(f"=== Hostages dispatcher start. list={args.list} ===")
    videos = load_videos(args.list)
    log(f"Loaded {len(videos)} unique video entries")

    log("Fetching existing files in Hostages Drive folder...")
    try:
        token = get_drive_token()
        existing = list_existing_titles(token)
        log(f"Existing files in folder: {len(existing)}")
    except Exception as e:
        log(f"Drive listing failed: {e} — proceeding without skip")
        existing = set()

    existing_norm = {normalize_title(t) for t in existing}

    # Filter: only skip if we have a title to compare against
    filtered = []
    skipped = 0
    for vid, title in videos:
        if title and normalize_title(title) in existing_norm:
            skipped += 1
            continue
        filtered.append((vid, title))
    log(f"After dedup: {len(filtered)} to dispatch  (skipped {skipped})")

    if args.start:
        filtered = filtered[args.start:]
        log(f"Skipping first {args.start} -> {len(filtered)} remaining")
    if args.limit:
        filtered = filtered[: args.limit]
        log(f"Limit applied -> {len(filtered)} to dispatch")

    dispatched = failed = 0
    start = time.time()
    for i, (vid, title) in enumerate(filtered, 1):
        url = f"https://www.youtube.com/watch?v={vid}"
        # pace
        while True:
            inflight = in_flight_count()
            if inflight < args.max_queue:
                break
            elapsed = int(time.time() - start)
            log(f"[{i}/{len(filtered)}] queue={inflight} >= {args.max_queue}, waiting (elapsed {elapsed}s)")
            time.sleep(POLL_SECONDS)

        ok = dispatch(url)
        if ok:
            dispatched += 1
            log(f"[{i}/{len(filtered)}] OK  {vid}  | {title[:60]}  (ok={dispatched} fail={failed})")
        else:
            failed += 1
            log(f"[{i}/{len(filtered)}] FAIL {vid}  (ok={dispatched} fail={failed})")
        time.sleep(2)

    elapsed = int(time.time() - start)
    log(f"=== DONE. dispatched={dispatched} failed={failed} elapsed={elapsed}s ===")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
