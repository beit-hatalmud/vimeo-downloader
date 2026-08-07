"""Open NLI search page in Playwright, wait for JS results, extract MMS IDs."""
import sys, os, re, json, time
from urllib.parse import quote
from playwright.sync_api import sync_playwright

term = sys.argv[1] if len(sys.argv) > 1 else "בלוי משה"
print(f"Search term: {term}")

# NLI search URL — uses front-end React app
search_urls = [
    f"https://www.nli.org.il/he/discover/search?q={quote(term)}&materialType=audio",
    f"https://www.nli.org.il/he/results?q=any,contains,{quote(term)}&material=audio",
    f"https://www.nli.org.il/he/sounds/recordings?q={quote(term)}",
    # Also publisher search ("תושייה ועצה" is the series of Rabbi Bloi recordings)
    f"https://www.nli.org.il/he/discover/search?q=תושייה ועצה&materialType=audio",
]

all_mms = set()
captured_responses = []

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled","--no-sandbox","--disable-dev-shm-usage"]
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="he-IL",
        viewport={"width": 1366, "height": 900}
    )
    # Stealth tweaks
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

    for u in search_urls:
        print(f"\n=== {u} ===")
        page = ctx.new_page()
        json_responses = []
        def on_resp(r):
            try:
                ct = r.headers.get("content-type","")
                if "json" in ct or "/api/" in r.url or "/search" in r.url or "primaws" in r.url:
                    body = r.text() if r.status == 200 else ""
                    json_responses.append((r.url, r.status, body[:50000]))
            except Exception:
                pass
        page.on("response", on_resp)

        try:
            page.goto(u, wait_until="networkidle", timeout=60000)
        except Exception as e:
            print(f"  goto warn: {e}")

        # Wait for results to render
        for sec in [3, 5, 8, 12, 20]:
            time.sleep(3)
            html = page.content()
            mms = set(re.findall(r'NNL_ALEPH(\d{15,20})', html))
            mms |= set(re.findall(r'\b(99\d{12,17}0205171)\b', html))
            mms |= set(re.findall(r'\b(99\d{12,17}4605171)\b', html))
            print(f"  +{sec}s: html={len(html)}, mms_found={len(mms)}, json_resps={len(json_responses)}")
            if mms:
                all_mms |= mms
                # Save html for inspection
                fname = re.sub(r'[^\w]','_',u)[:60]
                with open(f"_pw_{fname}.html","w",encoding="utf-8") as f: f.write(html[:300_000])
                break

        # Mine captured JSON responses
        for jurl, jstatus, jbody in json_responses[-30:]:
            mms_in_json = set(re.findall(r'NNL_ALEPH(\d{15,20})', jbody))
            mms_in_json |= set(re.findall(r'\b(99\d{12,17}0205171)\b', jbody))
            if mms_in_json:
                print(f"  json [{jstatus}] {jurl[:120]} → {len(mms_in_json)} mms")
                all_mms |= mms_in_json
                captured_responses.append((jurl, list(mms_in_json)[:5]))

        page.close()

    browser.close()

print(f"\n\n=== Total unique MMS: {len(all_mms)} ===")
download_urls = sorted({f"https://www.nli.org.il/he/audio/NNL_ALEPH{m}/NLI" for m in all_mms})
with open("creator_urls.json","w") as f: json.dump(download_urls, f, indent=2)
for u in download_urls[:50]:
    print(f"  {u}")
print(f"\n=== captured json sample ===")
for jurl, sample in captured_responses[:5]:
    print(f"  {jurl[:120]} → {sample}")
