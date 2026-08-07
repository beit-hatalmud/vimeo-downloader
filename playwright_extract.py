"""Generic media extractor: open page in Playwright, capture media URLs, download largest."""
import sys, os, subprocess

url = sys.argv[1] if len(sys.argv) > 1 else ""
if not url:
    print("Usage: python playwright_extract.py <url>")
    sys.exit(1)

os.makedirs("videos", exist_ok=True)

from playwright.sync_api import sync_playwright

video_urls = []

def on_response(response):
    ct = response.headers.get("content-type", "")
    if any(x in ct for x in ["video/", "audio/"]) or any(x in response.url for x in [".mp4", ".webm", ".m3u8", "videoplayback"]):
        video_urls.append(response.url)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("response", on_response)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(5000)
    except Exception as e:
        print(f"Page error: {e}")
    browser.close()

if video_urls:
    print(f"Found {len(video_urls)} media URLs")
    best = max(video_urls, key=len)
    subprocess.run(["curl", "-L", "-o", "videos/extracted_video.mp4", best, "--max-time", "300"], timeout=310)
else:
    print("No media found in page")
