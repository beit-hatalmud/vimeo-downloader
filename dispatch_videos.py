#!/usr/bin/env python3
"""Re-dispatch failed YouTube videos using the (now WARP-enabled) Download to Drive workflow.

Pacing strategy:
  - Keep no more than MAX_QUEUE in-flight runs (queued + in_progress)
  - Sleep POLL_SECONDS between checks
"""
import argparse
import json
import os
import subprocess
import sys
import time

REPO = "yossi6742853/vimeo-downloader"
WORKFLOW = "download-to-drive.yml"
MAX_QUEUE = 28
POLL_SECONDS = 30
QUALITY = "480"


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


def in_flight_count():
    """Return the count of queued + in_progress runs for our workflow."""
    try:
        data = gh_json([
            "gh", "run", "list", "--repo", REPO, "--workflow", WORKFLOW,
            "--limit", "60", "--json", "status,databaseId",
        ])
    except Exception as e:
        print(f"  warn: in_flight_count failed: {e}", flush=True)
        return MAX_QUEUE  # be conservative -> wait
    return sum(1 for r in data if r.get("status") in ("queued", "in_progress", "waiting"))


def dispatch(url: str) -> bool:
    cmd = [
        "gh", "workflow", "run", WORKFLOW,
        "--repo", REPO,
        "-f", f"url={url}",
        "-f", f"quality={QUALITY}",
        "-f", "format=video",
        "-f", "download_to_pc=false",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        print(f"  ERR: {r.stderr.strip()[:200]}", flush=True)
        return False
    return True


def load_videos(path: str):
    """Each line: <id>|<title>"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            vid = line.split("|", 1)[0].strip()
            if vid:
                out.append(vid)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("lists", nargs="+", help="Paths to video_list.txt files")
    parser.add_argument("--limit", type=int, default=0, help="Cap total dispatches (0=unlimited)")
    parser.add_argument("--start", type=int, default=0, help="Skip the first N IDs across all lists")
    parser.add_argument("--max-queue", type=int, default=MAX_QUEUE)
    args = parser.parse_args()

    ids = []
    seen = set()
    for path in args.lists:
        for vid in load_videos(path):
            if vid in seen:
                continue
            seen.add(vid)
            ids.append(vid)

    print(f"Loaded {len(ids)} unique video ids from {len(args.lists)} list(s).", flush=True)
    if args.start:
        ids = ids[args.start:]
        print(f"Skipping first {args.start} -> {len(ids)} remaining.", flush=True)
    if args.limit:
        ids = ids[: args.limit]
        print(f"Limit applied -> {len(ids)} to dispatch.", flush=True)

    dispatched = 0
    failed = 0
    start = time.time()
    for i, vid in enumerate(ids, 1):
        url = f"https://www.youtube.com/watch?v={vid}"
        # Pace
        while True:
            inflight = in_flight_count()
            if inflight < args.max_queue:
                break
            elapsed = int(time.time() - start)
            print(f"[{i}/{len(ids)}] queue={inflight} >= {args.max_queue}, waiting (elapsed {elapsed}s)...", flush=True)
            time.sleep(POLL_SECONDS)

        ok = dispatch(url)
        if ok:
            dispatched += 1
            print(f"[{i}/{len(ids)}] dispatched {vid}  (total ok={dispatched}, fail={failed})", flush=True)
        else:
            failed += 1
            print(f"[{i}/{len(ids)}] FAILED   {vid}  (total ok={dispatched}, fail={failed})", flush=True)
        # small delay so GH registers the run before next inflight check
        time.sleep(2)

    elapsed = int(time.time() - start)
    print(f"\nFinished. Dispatched={dispatched}  Failed={failed}  Elapsed={elapsed}s", flush=True)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
