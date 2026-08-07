"""NLI (National Library of Israel) media extractor.
Strategy: curl_cffi (impersonate Chrome) bypasses Cloudflare Turnstile,
parses page for DigiTool/asset URLs, and downloads.
"""
import sys, os, subprocess, re, json, time, glob

url = sys.argv[1] if len(sys.argv) > 1 else ""
if not url:
    print("Usage: python nli_extract.py <url>")
    sys.exit(1)

os.makedirs("videos", exist_ok=True)

# Step 0: Try FlareSolverr (real Cloudflare bypass)
flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "")
flare_html = None
flare_cookies = None
if flaresolverr_url:
    try:
        import requests as plain_req
        print(f"=== Step 0: FlareSolverr at {flaresolverr_url} ===")
        resp = plain_req.post(flaresolverr_url, json={
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        }, timeout=120)
        d = resp.json()
        if d.get("status") == "ok":
            sol = d.get("solution", {})
            flare_html = sol.get("response", "")
            flare_cookies = sol.get("cookies", [])
            print(f"  FlareSolverr OK: {len(flare_html)} chars, {len(flare_cookies)} cookies")
            print(f"  final URL: {sol.get('url','')}")
        else:
            print(f"  FlareSolverr failed: {d.get('message','?')}")
    except Exception as e:
        print(f"  FlareSolverr error: {e}")

# Step 1: Try curl_cffi (best for Cloudflare)
try:
    from curl_cffi import requests as cffi_req
    print("=== Step 1: curl_cffi with chrome impersonation ===")
    if flare_html:
        html = flare_html
        print(f"  using FlareSolverr HTML ({len(html)} chars)")
        r = type('R', (), {'status_code': 200, 'text': html, 'content': html.encode('utf-8','ignore')})()
    else:
        r = cffi_req.get(url, impersonate="chrome131", timeout=30)
        print(f"  HTTP {r.status_code}, length {len(r.text)}")
        html = r.text
    # Extract MMS ID
    mms = re.search(r'(?:NNL_ALEPH|MMS_ID[^\d]*)(\d{15,20})', url + " " + html)
    mms_id = mms.group(1) if mms else None
    print(f"  MMS ID: {mms_id}")

    # Find DigiTool / asset / streaming URLs
    candidates = []
    for pat in [
        r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|m3u8|aac))',
        r'(https?://[^"\'\s]*nli\.org\.il[^"\'\s]*(?:asset|media|stream|audio|digitool|player)[^"\'\s]*)',
        r'(https?://[^"\'\s]*rosetta[^"\'\s]+)',
        r'src="(https?://[^"]+(?:viewer|player|delivery)[^"]+)"',
        r'dataPid["\']?\s*[:=]\s*["\']([^"\']+)',
        r'fileUrl["\']?\s*[:=]\s*["\']([^"\']+)',
    ]:
        for m in re.finditer(pat, html, re.I):
            u = m.group(1)
            if u not in candidates:
                candidates.append(u)
                print(f"  candidate: {u[:160]}")

    # Look for json-ld / og:audio
    og = re.search(r'<meta[^>]+property="og:audio"[^>]+content="([^"]+)"', html)
    if og:
        print(f"  og:audio: {og.group(1)}")
        candidates.insert(0, og.group(1))
    og2 = re.search(r'<meta[^>]+property="og:video"[^>]+content="([^"]+)"', html)
    if og2:
        print(f"  og:video: {og2.group(1)}")
        candidates.insert(0, og2.group(1))

    # Find IE / FL pids in NLI page HTML (Rosetta DPS identifiers)
    ie_pids = list(set(re.findall(r'\bIE(\d{6,12})\b', html)))
    fl_pids = list(set(re.findall(r'\bFL(\d{6,12})\b', html)))
    # First IE pid in the page is usually the main object for this record
    main_ie = ie_pids[0] if ie_pids else None
    print(f"  found IE pids: {ie_pids[:5]}, main: IE{main_ie}")
    print(f"  found FL pids count: {len(fl_pids)}")

    def flare_get(target):
        if not flaresolverr_url:
            return None
        try:
            import requests as plain_req
            r = plain_req.post(flaresolverr_url, json={
                "cmd": "request.get", "url": target, "maxTimeout": 60000
            }, timeout=120)
            d = r.json()
            if d.get("status") == "ok":
                return d.get("solution", {}).get("response", "")
        except Exception as e:
            print(f"    flare_get err: {e}")
        return None

    # Try Rosetta delivery for the IE
    if main_ie:
        for variant in [
            f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=IE{main_ie}",
            f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=IE{main_ie}&dps_custom_att_1=ie_pid",
        ]:
            print(f"  trying rosetta: {variant}")
            html2 = flare_get(variant)
            if html2:
                print(f"    rosetta resp: {len(html2)} chars")
                # Mine FL pids and direct media URLs
                more_fl = re.findall(r'\bFL(\d{6,12})\b', html2)
                for f in more_fl:
                    if f not in fl_pids:
                        fl_pids.append(f)
                        print(f"    + FL{f}")
                for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|m3u8))', html2, re.I):
                    if m.group(1) not in candidates:
                        candidates.append(m.group(1))
                        print(f"    + media: {m.group(1)[:160]}")
                # Direct stream URL pattern
                for m in re.finditer(r'(https?://[^\s"\'<>]+(?:DeliveryManager|stream)[^\s"\'<>]+)', html2, re.I):
                    u = m.group(1)
                    if 'thumbnail' not in u and u not in candidates:
                        candidates.append(u)
                        print(f"    + delivery: {u[:160]}")
                break

    # First save Rosetta delivery HTML for inspection
    if main_ie:
        delivery_url = f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=IE{main_ie}"
        del_html = flare_get(delivery_url) or ""
        with open(f"videos/_rosetta_IE{main_ie}.html","w",encoding="utf-8") as f: f.write(del_html)
        print(f"  saved rosetta delivery to videos/_rosetta_IE{main_ie}.html ({len(del_html)} chars)")
        # Search delivery HTML for media URLs and pids
        for m in re.finditer(r'(https?://[^\s"\'<>()]+)', del_html):
            u = m.group(1)
            if any(x in u.lower() for x in ['stream','.mp3','.m4a','.wav','.m3u8','viewer','player','manifest']):
                if u not in candidates:
                    candidates.append(u)
                    print(f"    + from-delivery: {u[:160]}")
        # Specifically look for iframe src pointing to viewer
        for m in re.finditer(r'<iframe[^>]+src="([^"]+)"', del_html, re.I):
            print(f"    iframe in delivery: {m.group(1)[:160]}")
            candidates.append(m.group(1))

    # Save flare HTML for inspection
    with open("videos/_nli_flare.html","w",encoding="utf-8") as f: f.write(html)

    # Try each FL pid: HEAD probe first, then stream-download non-images
    cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in (flare_cookies or []))
    print(f"\n  probing {len(fl_pids)} FL pids (HEAD requests):")
    audio_fl = []
    import requests as plain_req
    sess = plain_req.Session()
    sess.headers.update({
        "Cookie": cookie_hdr,
        "Referer": url,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    })
    for fid in fl_pids:
        stream_url = f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=FL{fid}&dps_func=stream"
        try:
            r4 = sess.head(stream_url, timeout=15, allow_redirects=True)
            ct = r4.headers.get('content-type','')
            cl = r4.headers.get('content-length','0')
            sz = int(cl) if cl.isdigit() else 0
            print(f"  FL{fid} → HTTP {r4.status_code}, ct={ct[:40]}, size={sz}")
            # NLI mislabels audio as image/tiff. Skip jpg/png/gif (real images), keep tiff/non-image with large size.
            if any(x in ct.lower() for x in ['image/jpeg','image/jpg','image/png','image/gif','image/webp']):
                continue
            # Anything large (>5MB) is probably the audio, regardless of mislabel
            if sz > 5_000_000 or 'audio' in ct or 'mpeg' in ct or 'mp3' in ct or 'wav' in ct or 'm4a' in ct or 'octet-stream' in ct or 'video' in ct:
                audio_fl.append((fid, ct, sz))
        except Exception as e:
            print(f"  FL{fid} probe err: {type(e).__name__}: {str(e)[:80]}")

    # Sort by size desc — largest first (most likely the audio)
    audio_fl.sort(key=lambda x: -x[2])
    print(f"\n  candidate audio FLs: {audio_fl}")
    for fid, ct, _sz in audio_fl:
        stream_url = f"https://rosetta.nli.org.il/delivery/DeliveryManagerServlet?dps_pid=FL{fid}&dps_func=stream"
        ext = 'mp3'
        if 'mp4' in ct or 'm4a' in ct: ext = 'm4a'
        elif 'wav' in ct: ext = 'wav'
        elif 'ogg' in ct: ext = 'ogg'
        out = f"videos/nli_FL{fid}.{ext}"
        print(f"  downloading FL{fid} → {out}")
        # Use plain requests with stream=True for big files (no timeout limit per byte)
        import requests as plain_req
        try:
            with plain_req.get(stream_url, headers={"Cookie": cookie_hdr, "Referer": url,
                                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
                               stream=True, timeout=(30, 600), allow_redirects=True) as r5:
                r5.raise_for_status()
                with open(out, 'wb') as f:
                    total = 0
                    for chunk in r5.iter_content(chunk_size=1<<20):
                        if chunk:
                            f.write(chunk)
                            total += len(chunk)
                            if total % (10<<20) < (1<<20):
                                print(f"    {total/1024/1024:.1f} MB...")
                    print(f"    final: {total/1024/1024:.1f} MB")
            if os.path.getsize(out) > 200_000:
                print(f"  ROSETTA STREAM OK: {out} ({os.path.getsize(out)/1024/1024:.2f} MB)")
                # Remove other small junk in videos/
                for j in glob.glob("videos/*"):
                    if j != out and not j.startswith("videos/_") and os.path.getsize(j) < 100_000:
                        os.remove(j)
                sys.exit(0)
        except Exception as e:
            print(f"  FL{fid} download err: {e}")

    # Try downloading best candidate (extension match only — exclude page URLs)
    media_cands = [c for c in candidates if re.search(r'\.(mp3|m4a|wav|ogg|aac|m3u8|mpd)(\?|$)', c.lower())]
    if media_cands:
        best = media_cands[0]
        print(f"\n  best candidate: {best}")
        out = "videos/nli_audio.mp3"
        # Build cookie header from FlareSolverr if we have it
        cookie_hdr = ""
        if flare_cookies:
            cookie_hdr = "; ".join(f"{c['name']}={c['value']}" for c in flare_cookies)
        if ".m3u8" in best.lower():
            ytcmd = ["yt-dlp","-x","--audio-format","mp3","-o",out,best]
            if cookie_hdr:
                ytcmd += ["--add-header", f"Cookie:{cookie_hdr}", "--add-header", f"Referer:{url}"]
            subprocess.run(ytcmd, timeout=600)
        else:
            ext = best.split("?")[0].split(".")[-1].lower()
            if ext in ("mp3","m4a","wav","ogg","aac"):
                out = f"videos/nli_audio.{ext}"
            hdrs = {"Referer": url}
            if cookie_hdr: hdrs["Cookie"] = cookie_hdr
            r3 = cffi_req.get(best, impersonate="chrome131", timeout=600, headers=hdrs)
            with open(out,'wb') as f: f.write(r3.content)
        if os.path.exists(out) and os.path.getsize(out) > 50000:
            print(f"  curl_cffi OK: {out} ({os.path.getsize(out)/1024/1024:.2f} MB)")
            sys.exit(0)
        else:
            print(f"  curl_cffi small file, falling through to playwright")

    # Save HTML for debugging
    with open("videos/_nli_raw.html","w",encoding="utf-8") as f: f.write(html)
    print(f"  saved raw HTML to videos/_nli_raw.html ({len(html)} chars)")
except Exception as e:
    print(f"curl_cffi step error: {e}")

print("\n=== Step 2: Playwright fallback ===")
from playwright.sync_api import sync_playwright

media_urls = []
all_responses = []

def is_media(u, ct=""):
    if any(ext in u.lower() for ext in [".mp3", ".m4a", ".wav", ".ogg", ".aac", ".m3u8", ".mpd", "audio", "stream"]):
        return True
    if ct and any(t in ct for t in ["audio/", "video/", "application/vnd.apple.mpegurl", "application/dash+xml"]):
        return True
    return False

def on_response(response):
    try:
        ct = response.headers.get("content-type", "")
        u = response.url
        all_responses.append((u, ct))
        if is_media(u, ct):
            media_urls.append((u, ct, int(response.headers.get("content-length", "0") or 0)))
            print(f"  → media: {u[:120]} ({ct})")
    except Exception:
        pass

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        locale="he-IL"
    )
    page = ctx.new_page()
    page.on("response", on_response)

    print(f"Loading: {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"goto warn: {e}")

    # Wait for Cloudflare + page settle
    for i in range(8):
        time.sleep(3)
        title = page.title() or ""
        print(f"  t+{(i+1)*3}s title='{title[:80]}'")
        if title and "challenge" not in title.lower() and "just a moment" not in title.lower():
            break

    # Try clicking play button (common selectors)
    for sel in ["button[aria-label*='play' i]", "button.play", ".play-button", "[data-testid='play']", "button:has-text('השמע')", "button:has-text('נגן')"]:
        try:
            if page.locator(sel).count() > 0:
                print(f"  clicking {sel}")
                page.locator(sel).first.click(timeout=5000)
                time.sleep(3)
                break
        except Exception:
            pass

    # Scan iframes
    for frame in page.frames:
        try:
            furl = frame.url
            if furl and furl != url:
                print(f"  iframe: {furl[:120]}")
                # Look inside iframe HTML for media src
                try:
                    html = frame.content()
                    for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|m3u8))', html, re.I):
                        media_urls.append((m.group(1), "from-iframe-html", 0))
                        print(f"  → found in iframe HTML: {m.group(1)[:120]}")
                    for m in re.finditer(r'src="(https?://[^"]+stream[^"]+)"', html, re.I):
                        media_urls.append((m.group(1), "stream-attr", 0))
                except Exception as e:
                    print(f"  iframe html error: {e}")
        except Exception:
            pass

    # Scan main page HTML too
    try:
        html = page.content()
        for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:mp3|m4a|wav|ogg|m3u8))', html, re.I):
            media_urls.append((m.group(1), "from-page-html", 0))
            print(f"  → in page HTML: {m.group(1)[:120]}")
        # NLI uses asset URLs - look for them
        for m in re.finditer(r'(https?://[^"\']*nli\.org\.il[^"\']*(?:asset|media|stream|audio)[^"\']*)', html, re.I):
            u = m.group(1)
            if u not in [x[0] for x in media_urls]:
                media_urls.append((u, "nli-asset", 0))
                print(f"  → NLI asset: {u[:120]}")
    except Exception as e:
        print(f"page content error: {e}")

    # Wait a bit more for any late-loading streams
    time.sleep(5)
    browser.close()

print(f"\n=== Total responses captured: {len(all_responses)} ===")
print(f"=== Media URLs found: {len(media_urls)} ===")

# Dedupe and write
unique = list({u: (u, ct, sz) for u, ct, sz in media_urls}.values())
with open("videos/_nli_urls.json", "w", encoding="utf-8") as f:
    json.dump([{"url": u, "ct": ct, "size": sz} for u, ct, sz in unique], f, ensure_ascii=False, indent=2)

if not unique:
    print("\nNo media found. Sample of all responses:")
    for u, ct in all_responses[-30:]:
        print(f"  {ct[:30]:30s} {u[:140]}")
    sys.exit(0)

# Pick best: prefer mp3/m4a, then largest
def score(item):
    u, ct, sz = item
    s = sz
    if ".mp3" in u.lower() or "audio/mp" in ct: s += 100_000_000
    if ".m4a" in u.lower(): s += 90_000_000
    if ".m3u8" in u.lower(): s += 80_000_000
    return s

best = max(unique, key=score)
best_url = best[0]
print(f"\nBest URL: {best_url}")

# Download
out = "videos/nli_audio.mp3"
if ".m3u8" in best_url.lower():
    out = "videos/nli_audio.mp3"
    subprocess.run(["yt-dlp", "-x", "--audio-format", "mp3", "-o", out, best_url], timeout=600)
else:
    ext = best_url.split("?")[0].split(".")[-1].lower()
    if ext in ("mp3", "m4a", "wav", "ogg", "aac"):
        out = f"videos/nli_audio.{ext}"
    subprocess.run([
        "curl", "-L", "-o", out, best_url,
        "--max-time", "600",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", f"Referer: {url}"
    ], timeout=620)

if os.path.exists(out) and os.path.getsize(out) > 1000:
    print(f"OK: {out} ({os.path.getsize(out)/1024/1024:.2f} MB)")
else:
    print(f"FAIL: {out} too small or missing")
