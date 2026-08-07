"""Download YouTube video using Playwright - intercept video stream and record"""
import sys, os, time, json

url = sys.argv[1] if len(sys.argv) > 1 else ""
if not url:
    print("Usage: python youtube_playwright.py <youtube_url>")
    sys.exit(1)

os.makedirs("videos", exist_ok=True)

from playwright.sync_api import sync_playwright

video_segments = []
audio_segments = []

def handle_response(response):
    """Intercept googlevideo.com responses"""
    u = response.url
    if "googlevideo.com" not in u:
        return
    ct = response.headers.get("content-type", "")
    cl = response.headers.get("content-length", "0")
    if "video" in ct or "audio" in ct:
        try:
            body = response.body()
            if len(body) > 1000:
                if "video" in ct:
                    video_segments.append(body)
                    print(f"  VIDEO segment: {len(body)/1024:.0f}KB")
                else:
                    audio_segments.append(body)
                    print(f"  AUDIO segment: {len(body)/1024:.0f}KB")
        except:
            pass

print(f"Opening YouTube: {url}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720}
    )
    page = ctx.new_page()
    page.on("response", handle_response)

    # Navigate to YouTube
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # Accept consent if needed
    try:
        page.click("button:has-text('Accept all')", timeout=3000)
        time.sleep(1)
    except:
        pass

    # Click play
    try:
        page.click(".ytp-large-play-button", timeout=5000)
    except:
        try:
            page.click("button[aria-label*='Play']", timeout=3000)
        except:
            pass

    print("Waiting for video to buffer...")

    # Wait and collect segments
    for i in range(60):  # Wait up to 60 seconds
        time.sleep(1)
        total_video = sum(len(s) for s in video_segments)
        total_audio = sum(len(s) for s in audio_segments)
        if (i + 1) % 10 == 0:
            print(f"  [{i+1}s] Video: {total_video/1024/1024:.1f}MB ({len(video_segments)} segments), Audio: {total_audio/1024/1024:.1f}MB ({len(audio_segments)} segments)")
        # Stop if we have enough (at least 5MB of video)
        if total_video > 5 * 1024 * 1024:
            print("  Got enough video data!")
            break

    browser.close()

# Save collected data
total_video = sum(len(s) for s in video_segments)
total_audio = sum(len(s) for s in audio_segments)

print(f"\nCollected: Video={total_video/1024/1024:.1f}MB, Audio={total_audio/1024/1024:.1f}MB")

if total_video > 10000:
    with open("videos/youtube_video.mp4", "wb") as f:
        for seg in video_segments:
            f.write(seg)
    print(f"Saved: videos/youtube_video.mp4 ({total_video/1024/1024:.1f} MB)")

    if total_audio > 10000:
        with open("videos/youtube_audio.mp4", "wb") as f:
            for seg in audio_segments:
                f.write(seg)
        # Merge with ffmpeg
        import subprocess
        subprocess.run(["ffmpeg", "-y", "-i", "videos/youtube_video.mp4", "-i", "videos/youtube_audio.mp4",
                       "-c", "copy", "videos/merged.mp4"], capture_output=True)
        if os.path.exists("videos/merged.mp4") and os.path.getsize("videos/merged.mp4") > 10000:
            os.remove("videos/youtube_video.mp4")
            os.remove("videos/youtube_audio.mp4")
            print(f"Merged: videos/merged.mp4 ({os.path.getsize('videos/merged.mp4')/1024/1024:.1f} MB)")

    files = [f for f in os.listdir("videos") if os.path.getsize(f"videos/{f}") > 1000]
    print(f"\nFinal: {len(files)} files")
    sys.exit(0)
else:
    print("Failed to capture enough video data")
    sys.exit(1)
