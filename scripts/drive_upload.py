#!/usr/bin/env python3
"""
Resumable upload ל-Google Drive עם token refresh אוטומטי - מטפל בריצות ארוכות (>1h).
Usage: drive_upload2.py <client_id> <client_secret> <refresh_token> <folder_id> <local_path> <drive_filename>
"""
import sys, os, json, time, urllib.request, urllib.error, urllib.parse

CHUNK = 64 * 1024 * 1024  # 64MB

def get_access(client_id, client_secret, refresh_token):
    data = urllib.parse.urlencode({
        'client_id': client_id, 'client_secret': client_secret,
        'refresh_token': refresh_token, 'grant_type': 'refresh_token'
    }).encode()
    return json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', data=data, timeout=30))['access_token']

def main():
    if len(sys.argv) < 7:
        print('Usage: drive_upload2.py <client_id> <secret> <refresh> <folder> <local> <name>', file=sys.stderr)
        sys.exit(2)
    cid, csec, rtok, folder_id, local_path, drive_filename = sys.argv[1:7]
    if not os.path.exists(local_path):
        print(f'ERROR: file not found: {local_path}', file=sys.stderr); sys.exit(2)
    size = os.path.getsize(local_path)
    print(f'Uploading {drive_filename} ({size/(1024*1024):.1f}MB)...', file=sys.stderr)

    token = get_access(cid, csec, rtok)
    token_obtained_at = time.time()

    def refresh_if_needed():
        nonlocal token, token_obtained_at
        if time.time() - token_obtained_at > 2700:  # 45 דק' - מתחת ל-60 דק' tokenex
            token = get_access(cid, csec, rtok)
            token_obtained_at = time.time()
            print(f'  refreshed token', file=sys.stderr)

    # שלב 1: initiate
    meta = {'name': drive_filename, 'parents': [folder_id]}
    init_url = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true&fields=id,name'
    req = urllib.request.Request(
        init_url,
        data=json.dumps(meta).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json; charset=UTF-8',
            'X-Upload-Content-Type': 'video/mp4',
            'X-Upload-Content-Length': str(size),
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            session_url = r.headers.get('Location')
    except urllib.error.HTTPError as e:
        print(f'INIT-FAIL HTTP={e.code}: {e.read().decode(errors="replace")[:300]}', file=sys.stderr)
        sys.exit(1)

    if not session_url:
        print('INIT-FAIL: no session URL', file=sys.stderr); sys.exit(1)

    # שלב 2: upload בחלקים
    file_id = None
    with open(local_path, 'rb') as f:
        offset = 0
        while offset < size:
            refresh_if_needed()
            f.seek(offset)
            chunk_data = f.read(CHUNK)
            chunk_len = len(chunk_data)
            chunk_end = offset + chunk_len - 1
            req = urllib.request.Request(
                session_url,
                data=chunk_data,
                headers={
                    'Content-Length': str(chunk_len),
                    'Content-Range': f'bytes {offset}-{chunk_end}/{size}',
                },
                method='PUT',
            )
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    body = r.read().decode(errors='replace')
                    if r.status in (200, 201):
                        result = json.loads(body)
                        file_id = result.get('id')
                        offset = size
                        break
            except urllib.error.HTTPError as e:
                if e.code == 308:
                    rng = e.headers.get('Range', '')
                    if rng.startswith('bytes=0-'):
                        offset = int(rng.split('-')[1]) + 1
                    else:
                        offset += chunk_len
                    print(f'  {offset/size*100:.1f}% ({offset/(1024*1024):.0f}/{size/(1024*1024):.0f}MB)', file=sys.stderr)
                    continue
                else:
                    print(f'CHUNK-FAIL HTTP={e.code} at offset={offset}: {e.read().decode(errors="replace")[:300]}', file=sys.stderr)
                    sys.exit(1)

    if file_id:
        print(f'OK uploaded id={file_id} name={drive_filename}')
        sys.exit(0)
    else:
        print('UPLOAD-FAIL: no file id', file=sys.stderr); sys.exit(1)

if __name__ == '__main__':
    main()
