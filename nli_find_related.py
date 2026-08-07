"""Find all related/series items on a NLI page (links to other audio/recordings)."""
import sys, os, re, json
import requests as plain_req

url = sys.argv[1] if len(sys.argv) > 1 else ""
flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

print(f"Loading {url} via FlareSolverr...")
resp = plain_req.post(flaresolverr_url, json={
    "cmd": "request.get", "url": url, "maxTimeout": 60000
}, timeout=120)
sol = resp.json().get("solution", {})
html = sol.get("response", "")
print(f"Got {len(html)} chars")

found = set()

# Pattern 1: NNL_ALEPH IDs in href / data-* / etc
for m in re.finditer(r'NNL_ALEPH(\d{15,20})', html):
    found.add(("nli_audio", m.group(1)))

# Pattern 2: ALMA MMS IDs (end with 0005171 for NLI)
for m in re.finditer(r'(\d{13,19}0005171)', html):
    found.add(("alma_mms", m.group(1)))

# Pattern 3: links to /he/audio/, /he/recordings/, /he/musicrecordings/
for m in re.finditer(r'/he/(audio|recording|music|sounds|lecture|shiur)s?/([A-Z0-9_]+)', html, re.I):
    found.add((f"link_{m.group(1).lower()}", m.group(2)))

# Pattern 4: search-result style cards with data-pid
for m in re.finditer(r'data-(?:pid|mms|id)="([0-9A-Z_]+)"', html):
    found.add(("data_attr", m.group(1)))

# Filter: drop the source page's own ID
src_mms = re.search(r'NNL_ALEPH(\d+)', url)
src_id = src_mms.group(1) if src_mms else ""

print(f"\nSource MMS: {src_id}")
print(f"\n=== Found {len(found)} unique references ===")

# Group by type
by_type = {}
for t, v in found:
    by_type.setdefault(t, set()).add(v)
for t, vals in by_type.items():
    print(f"\n{t} ({len(vals)}):")
    for v in sorted(vals):
        marker = " ← SOURCE" if v == src_id else ""
        print(f"  {v}{marker}")

# Build candidate URLs to download
download_urls = set()
for v in by_type.get("nli_audio", []):
    if v != src_id:
        download_urls.add(f"https://www.nli.org.il/he/audio/NNL_ALEPH{v}/NLI")
for v in by_type.get("alma_mms", []):
    # Try both: as nli_audio and as standalone
    if v != src_id:
        download_urls.add(f"https://www.nli.org.il/he/audio/NNL_ALEPH{v}/NLI")

print(f"\n=== {len(download_urls)} candidate download URLs ===")
with open("related_urls.json", "w") as f:
    json.dump(sorted(download_urls), f, indent=2)
for u in sorted(download_urls):
    print(f"  {u}")
