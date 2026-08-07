#!/usr/bin/env python3
"""Cleanup pass: delete files from the OLD 'סרטונים שהורדו' folder that already
exist (by sanitized title match) inside the new Pivelzon folder hierarchy.

Run this AFTER `dispatch_pitchei_olam.py` has uploaded a meaningful share of
the 502 videos (e.g., when in-flight count drops near zero).

Usage:
  python cleanup_old_pivelzon.py [--dry-run] [--list LIST.txt]

  --dry-run   : print actions only, do not trash
  --list      : optional path to the original id|title list. If given, only
                files whose normalized title is also a known Pivelzon title
                are eligible for cleanup. Otherwise, ANY file whose name
                matches a name found in the new hierarchy is trashed.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

OLD_FOLDER_ID = "12-Yf8lDXn-aqQ-wgR8dHNIuFDTBkmxzO"  # 'סרטונים שהורדו'
NEW_ROOT_ID = "1Brp6QGSUmMdnXc4TLj_lYepmFk20Kk9h"
NEW_SUBFOLDERS = [
    "17GHLnb_hyI-wgV78PiZDm3odriFgCfN7",
    "1ERYbsj4EK1j_MaZYlxkErMrgfzNk9Z5C",
    "1kD5z4V-PK6Ib1HWmJgUxhpTFR7wr9hzB",
    "1CJB9nsLoYhiZXBnjSAPHhHBlFoNAFO8w",
    "1U0p2or5-J4v9XpcchWtlYi110bi47-sM",
    "1vPQ1iC7v0fko9qyJAGAfQPa_-ZPWCMAm",
    "1qqyJceu1G37_eFWOrKOzCBEDsTFk6-ag",
    "1X0AtekZqzx6_mrH_O45CISHFgHJCm28g",
]

CLIENT_ID = "1072944905499-vm2v2i5dvn0a0d2o4ca36i1vge8cvbn0.apps.googleusercontent.com"
CLIENT_SECRET = "v6V3fKV_zWU7iw1DrpO1rknX"
REFRESH_TOKEN = "1//03doYP5sR8165CgYIARAAGAMSNwF-L9Irwt3jH4FHlYkKBcdcEr_DCirl7AWT7Uxf36-gUtqITAWqJx-vLRNyMcDprd91JtFuhLc"


def get_token():
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token"
    }).encode()
    r = urllib.request.urlopen("https://oauth2.googleapis.com/token", data=data, timeout=30)
    return json.loads(r.read())["access_token"]


def list_folder(token, folder_id):
    out = []
    page = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            "fields": "nextPageToken,files(id,name,size)",
            "pageSize": "1000",
        }
        if page:
            params["pageToken"] = page
        url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        d = json.loads(urllib.request.urlopen(req, timeout=30).read())
        out.extend(d.get("files", []))
        page = d.get("nextPageToken")
        if not page:
            break
    return out


def normalize(t):
    t = t.strip()
    t = re.sub(r"\.(mp4|mkv|webm|mp3|m4a)$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+", " ", t)
    # yt-dlp replacements
    t = t.replace("｜", "|").replace("＂", '"').replace("：", ":")
    t = re.sub(r'["\'“”‘’]', "", t)
    return t.lower()


def trash(token, fid):
    req = urllib.request.Request(
        f"https://www.googleapis.com/drive/v3/files/{fid}",
        data=json.dumps({"trashed": True}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=30).read()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--list", default=None, help="Optional id|title list to limit scope")
    args = p.parse_args()

    token = get_token()
    print("Listing OLD folder...")
    old = list_folder(token, OLD_FOLDER_ID)
    print(f"  OLD: {len(old)} files")

    print("Listing NEW subfolders...")
    new_names = set()
    for fid in NEW_SUBFOLDERS:
        for f in list_folder(token, fid):
            new_names.add(normalize(f["name"]))
    print(f"  NEW: {len(new_names)} unique normalized names")

    pivelzon_titles = None
    if args.list:
        pivelzon_titles = set()
        with open(args.list, encoding="utf-8") as f:
            for line in f:
                if "|" in line:
                    pivelzon_titles.add(normalize(line.split("|", 1)[1]))
        print(f"  Pivelzon scope: {len(pivelzon_titles)} titles")

    deleted = skipped = 0
    for f in old:
        n = normalize(f["name"])
        if pivelzon_titles is not None and n not in pivelzon_titles:
            continue
        if n not in new_names:
            continue
        size_mb = int(f.get("size", 0)) / 1024 / 1024
        if args.dry_run:
            print(f"  WOULD DELETE  {f['name']}  ({size_mb:.1f}MB)")
        else:
            try:
                trash(token, f["id"])
                print(f"  TRASHED  {f['name']}  ({size_mb:.1f}MB)")
                deleted += 1
            except Exception as e:
                print(f"  FAIL  {f['name']}  ({e})")
                skipped += 1
        time.sleep(0.05)

    print(f"\nDone. deleted={deleted} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    sys.exit(main() or 0)
