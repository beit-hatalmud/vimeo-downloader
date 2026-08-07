"""Download video from Gemini share URL (Veo AI generated videos).

Gemini share pages render videos via blob URLs or signed CDN links.
Strategy:
1. Open page in Playwright (headless Chrome)
2. Intercept ALL network responses for video/audio content
3. Wait for <video> element + record its src (might be blob:)
4. If blob: use page.evaluate to FileReader → base64 → save
5. If signed URL: download directly with cookies from page
6. Fallback: save largest video response captured during page load
"""
import sys, os, time, json, base64, subprocess

url = sys.argv[1] if len(sys.argv) > 1 else ""
if not url:
    print("Usage: python gemini_extract.py <gemini_share_url>")
    sys.exit(1)

os.makedirs("videos", exist_ok=True)

from playwright.sync_api import sync_playwright

video_responses = []

def on_response(response):
    try:
        ct = response.headers.get("content-type", "")
        u = response.url
        if "video/" in ct or "audio/" in ct:
            video_responses.append({"url": u, "ct": ct, "response": response})
            print(f"  [media] {ct} <- {u[:120]}")
        elif any(x in u for x in [".mp4", ".webm", "videoplayback", "videos.googleusercontent"]):
            video_responses.append({"url": u, "ct": ct, "response": response})
            print(f"  [url-match] {ct} <- {u[:120]}")
    except Exception as e:
        pass

print(f"Opening Gemini share: {url}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    page = ctx.new_page()
    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print(f"Goto error (continuing): {e}")

    print("Page loaded, waiting for video element...")

    # Wait up to 30s for a <video> element with a src
    video_src = None
    for i in range(60):
        time.sleep(0.5)
        try:
            srcs = page.evaluate("""() => {
                const vids = Array.from(document.querySelectorAll('video'));
                return vids.map(v => ({
                    src: v.src || v.currentSrc,
                    duration: v.duration,
                    readyState: v.readyState,
                    paused: v.paused
                }));
            }""")
            if srcs:
                print(f"  [{(i+1)/2}s] videos found: {srcs}")
                for s in srcs:
                    if s.get("src"):
                        video_src = s["src"]
                        break
                if video_src and not video_src.startswith("blob:"):
                    break
        except: pass

    # Try clicking play button to trigger video load (in case it's idle)
    try:
        page.evaluate("""() => {
            document.querySelectorAll('video').forEach(v => v.play().catch(()=>{}));
        }""")
    except: pass

    print("Waiting for video data to load...")
    time.sleep(15)  # let chunks accumulate

    # Try reading blob via FileReader if src is blob:
    saved = False
    if video_src and video_src.startswith("blob:"):
        print(f"Detected blob URL: {video_src}")
        try:
            data_b64 = page.evaluate("""async (blobUrl) => {
                const resp = await fetch(blobUrl);
                const blob = await resp.blob();
                const buf = await blob.arrayBuffer();
                let bin = '';
                const bytes = new Uint8Array(buf);
                for (let i = 0; i < bytes.byteLength; i++) bin += String.fromCharCode(bytes[i]);
                return btoa(bin);
            }""", video_src)
            if data_b64 and len(data_b64) > 5000:
                with open("videos/gemini_video.mp4", "wb") as f:
                    f.write(base64.b64decode(data_b64))
                print(f"Saved blob: videos/gemini_video.mp4 ({os.path.getsize('videos/gemini_video.mp4')/1024/1024:.1f} MB)")
                saved = True
        except Exception as e:
            print(f"Blob read failed: {e}")

    # Save largest captured response if still nothing
    if not saved:
        print(f"Captured {len(video_responses)} video/audio responses")
        biggest = None
        biggest_size = 0
        for r in video_responses:
            try:
                body = r["response"].body()
                if len(body) > biggest_size:
                    biggest_size = len(body)
                    biggest = (r, body)
            except Exception as e:
                pass
        if biggest and biggest_size > 5000:
            r, body = biggest
            ext = ".webm" if "webm" in r["ct"] else ".mp4"
            with open(f"videos/gemini_video{ext}", "wb") as f:
                f.write(body)
            print(f"Saved captured: videos/gemini_video{ext} ({biggest_size/1024/1024:.1f} MB)")
            saved = True

    browser.close()

if not saved:
    print("FAILED: no video extracted")
    sys.exit(1)

print("DONE")
