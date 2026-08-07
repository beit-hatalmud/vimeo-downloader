#!/usr/bin/env python3
"""Delete empty / placeholder video files from Google Drive folder.

Targets:
  - Files smaller than 100 KB
  - Files named "extracted_video.mp4" (any size)

Usage:
  python cleanup_empty_drive_files.py [--folder FOLDER_ID] [--dry-run]

Credentials are read from environment variables, with fallback to the
default Beit HaTalmud OAuth client (same Google account that owns the
target folder).
"""
import argparse
import os
import sys
import time

import requests

DEFAULT_FOLDER_ID = "12-Yf8lDXn-aqQ-wgR8dHNIuFDTBkmxzO"
DEFAULT_CLIENT_ID = "1072944905499-vm2v2i5dvn0a0d2o4ca36i1vge8cvbn0.apps.googleusercontent.com"
DEFAULT_CLIENT_SECRET = "v6V3fKV_zWU7iw1DrpO1rknX"
DEFAULT_REFRESH_TOKEN = (
    "1//03doYP5sR8165CgYIARAAGAMSNwF-L9Irwt3jH4FHlYkKBcdcEr_DCirl7AWT7"
    "Uxf36-gUtqITAWqJx-vLRNyMcDprd91JtFuhLc"
)
SIZE_THRESHOLD = 100 * 1024  # 100 KB


def get_token() -> str:
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", DEFAULT_CLIENT_ID),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", DEFAULT_CLIENT_SECRET),
            "refresh_token": os.environ.get("GOOGLE_REFRESH_TOKEN", DEFAULT_REFRESH_TOKEN),
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def list_files(token: str, folder_id: str):
    headers = {"Authorization": f"Bearer {token}"}
    files = []
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken, files(id,name,size,mimeType)",
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token
        r = requests.get(
            "https://www.googleapis.com/drive/v3/files",
            params=params,
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        files.extend(data.get("files", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return files


def delete_file(token: str, file_id: str) -> bool:
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.delete(
        f"https://www.googleapis.com/drive/v3/files/{file_id}",
        headers=headers,
        timeout=30,
    )
    return r.status_code in (200, 204)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", default=DEFAULT_FOLDER_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = get_token()
    print(f"Listing folder {args.folder} ...", flush=True)
    files = list_files(token, args.folder)
    print(f"Total files in folder: {len(files)}", flush=True)

    targets = []
    for f in files:
        name = f.get("name", "")
        try:
            size = int(f.get("size", "0"))
        except ValueError:
            size = 0
        is_empty = size < SIZE_THRESHOLD
        is_placeholder = name == "extracted_video.mp4"
        if is_empty or is_placeholder:
            targets.append((f["id"], name, size))

    print(f"Targets to delete: {len(targets)}", flush=True)
    if args.dry_run:
        for fid, name, size in targets[:20]:
            print(f"  DRY: {size:>9} bytes  {name}  ({fid})")
        if len(targets) > 20:
            print(f"  ...and {len(targets) - 20} more")
        return 0

    deleted = 0
    failed = 0
    for i, (fid, name, size) in enumerate(targets, 1):
        ok = delete_file(token, fid)
        if ok:
            deleted += 1
        else:
            failed += 1
        if i % 25 == 0 or i == len(targets):
            print(f"  Progress: {i}/{len(targets)}  deleted={deleted}  failed={failed}", flush=True)
        # Refresh token every 500 deletions just in case
        if i % 500 == 0:
            token = get_token()
        time.sleep(0.05)

    print(f"\nDone. Deleted {deleted} files, failed {failed}.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
