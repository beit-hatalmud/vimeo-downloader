"""Search NLI for all AUDIO items by a specific creator via Primo VE API."""
import sys, os, re, json
import requests as plain_req
from urllib.parse import quote

flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

def flare_get(target):
    r = plain_req.post(flaresolverr_url, json={
        "cmd": "request.get", "url": target, "maxTimeout": 60000
    }, timeout=120)
    sol = r.json().get("solution", {})
    return sol.get("response", ""), sol.get("cookies", []), sol.get("userAgent","")

term = sys.argv[1] if len(sys.argv) > 1 else "בלוי משה"
print(f"Searching for: {term}")

# Primo VE API base for NLI
# Step 1: Hit any NLI page first to get Cloudflare cookies
print("\nStep 1: Get NLI Cloudflare cookies via FlareSolverr...")
_, cookies, ua = flare_get("https://www.nli.org.il/he")
cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in (cookies or []))
print(f"  got {len(cookies or [])} cookies, UA: {ua[:60]}")

# Step 2: Try multiple search APIs via FlareSolverr (cookies + UA bypass)
print("\nStep 2: Call NLI APIs via FlareSolverr POST")

def flare_get_raw(target):
    r = plain_req.post(flaresolverr_url, json={
        "cmd": "request.get", "url": target, "maxTimeout": 60000
    }, timeout=120)
    sol = r.json().get("solution", {})
    return sol.get("status",0), sol.get("response","")

all_mms = set()
endpoints = [
    # Open Library — see actual error/format
    f"https://api.nli.org.il/openlibrary/search?query=any,contains,{quote(term)}&material_type=AUDIO&result_format=json",
    # Try common public/demo keys
    f"https://api.nli.org.il/openlibrary/search?api_key=public&query=any,contains,{quote(term)}&material_type=AUDIO",
    # Discovery URL
    f"https://www.nli.org.il/he/discover/search?q={quote(term)}&materialType=audio",
]

for ep in endpoints:
    print(f"\n--- {ep[:120]}")
    code, body = flare_get_raw(ep)
    print(f"  status={code}, body len={len(body)}")
    print(f"  body[:600]: {body[:600]}")
    if not body:
        continue
    mms = set(re.findall(r'NNL_ALEPH(\d{15,20})', body))
    mms |= set(re.findall(r'"recordid"\s*:\s*"NNL[^"]*?(\d{15,20})', body))
    mms |= set(re.findall(r'\b(99\d{12,17}0205171)\b', body))
    print(f"  MMS found here: {len(mms)}")
    all_mms |= mms

# Step 3: Mine SEED page for author/series links and embedded JS keys
print("\n\nStep 3: Mine seed page for author/series links")
seed_html, _, _ = flare_get("https://www.nli.org.il/he/audio/NNL_ALEPH990033611980205171/NLI")
print(f"  seed: {len(seed_html)} chars")
# Save it for manual inspection
with open("_seed_page.html","w",encoding="utf-8") as f: f.write(seed_html)

# Hunt for any link containing "בלוי" or "תושייה" anchor text
ctx = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{2,200})</a>', seed_html)
for href, text in ctx:
    if any(x in text for x in ['בלוי','תושייה','פינק']):
        print(f"  link: '{text.strip()[:60]}' → {href[:200]}")

# Discover/search/persons hrefs anywhere
for m in re.finditer(r'href="([^"]*?(?:discover|search|persons|creators|authors|results|browse)[^"]*)"', seed_html, re.I):
    h = m.group(1)
    if 'NNL_ALEPH' not in h:  # skip individual item links
        print(f"  nav-href: {h[:200]}")

# Embedded JS API keys
print("\n\nStep 4: Hunt for embedded API key in JS")
home_html, _, _ = flare_get("https://www.nli.org.il/he")
js_urls = re.findall(r'<script[^>]+src="([^"]+\.js[^"]*)"', home_html)
print(f"  found {len(js_urls)} script tags in homepage")
for js_url in js_urls[:6]:
    full = js_url if js_url.startswith("http") else f"https://www.nli.org.il{js_url}"
    code, body = flare_get_raw(full)
    for pat in [
        r'(?:api[_-]?key|apiKey|API_KEY)["\']?\s*[:=]\s*["\']([A-Za-z0-9_\-]{16,64})',
        r'openlibrary["\'\s,:=]+([A-Za-z0-9_\-]{20,64})',
    ]:
        for m in re.finditer(pat, body):
            print(f"    JS key candidate: {m.group(1)}")

print(f"\n=== Total unique MMS IDs: {len(all_mms)} ===")
download_urls = sorted({f"https://www.nli.org.il/he/audio/NNL_ALEPH{m}/NLI" for m in all_mms})
with open("creator_urls.json","w") as f: json.dump(download_urls, f, indent=2)
for u in download_urls:
    print(f"  {u}")
