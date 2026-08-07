"""Verify creator/title of NLI items — sample first 5 URLs from related list."""
import sys, os, re, json
import requests as plain_req

flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

def flare_get(target):
    r = plain_req.post(flaresolverr_url, json={
        "cmd": "request.get", "url": target, "maxTimeout": 60000
    }, timeout=120)
    return r.json().get("solution", {}).get("response", "")

def extract_meta(html):
    out = {}
    # Title
    t = re.search(r'<title>([^<]+)</title>', html)
    if t: out['title'] = re.sub(r'\s*-\s*הספרייה.*$','',re.sub(r'\s+',' ',t.group(1))).strip()
    # OG title
    og = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
    if og: out['og_title'] = og.group(1).strip()
    # Creator/author from JSON-LD
    for m in re.finditer(r'"(?:creator|author|contributor|performer|composer)"\s*:\s*(?:"([^"]+)"|\{[^}]*"name"\s*:\s*"([^"]+)")', html):
        v = m.group(1) or m.group(2)
        out.setdefault('creators', []).append(v)
    # Hebrew "מבצע" / "יוצר" / "דובר" labels in HTML
    for label in ['מבצע','יוצר','דובר','מרצה','מחבר','אמן','שם','כותב']:
        for m in re.finditer(r'>(?:' + label + r')[^<]{0,5}</[^>]+>\s*<[^>]+>([^<]{2,80})<', html):
            out.setdefault('labeled_'+label, []).append(m.group(1).strip())
    # data fields
    for m in re.finditer(r'"display_name"\s*:\s*"([^"]+)"', html):
        out.setdefault('display_names', []).append(m.group(1))
    return out

# Read URLs (from related_urls.json + seed)
with open('related_urls.json') as f: urls = json.load(f)
seed = sys.argv[1] if len(sys.argv) > 1 else None
sample = ([seed] if seed else []) + urls[:4]

for u in sample:
    print(f"\n=== {u} ===")
    html = flare_get(u)
    if not html:
        print("  no html")
        continue
    meta = extract_meta(html)
    for k, v in meta.items():
        if isinstance(v, list):
            uniq = list(dict.fromkeys(v))[:6]
            print(f"  {k}: {uniq}")
        else:
            print(f"  {k}: {v}")
