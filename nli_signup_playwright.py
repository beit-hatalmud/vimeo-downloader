"""Use Playwright to fill and submit NLI signup form (handles JS-based form submit)."""
import os, re, time, json
from playwright.sync_api import sync_playwright

EMAIL = os.environ.get("SIGNUP_EMAIL", "6742853@gmail.com")

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
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    page = ctx.new_page()

    # Capture network requests/responses to find the real submit endpoint
    captured = []
    def on_req(req):
        if req.method != "GET":
            captured.append(("REQ", req.method, req.url, req.headers.get("content-type",""), req.post_data or ""))
    def on_resp(r):
        if r.request.method != "GET" and r.status >= 200:
            try: body = r.text()[:500]
            except: body = ""
            captured.append(("RESP", r.status, r.url, r.headers.get("content-type",""), body))
    page.on("request", on_req)
    page.on("response", on_resp)

    print("Going to /signup/")
    try:
        page.goto("https://api2.nli.org.il/signup/", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
    except Exception as e:
        print(f"  goto err: {e}")

    # Fill fields
    print("\nFilling form...")
    try:
        page.fill('input[name="user[first_name]"]', "Yosef")
        page.fill('input[name="user[last_name]"]', "Schneider")
        page.fill('input[name="user[email]"]', EMAIL)
        # Check terms
        try: page.check('input[name="user[terms_and_conditions]"]', force=True)
        except: page.locator('input[name="user[terms_and_conditions]"]').click(force=True)
        print("  fields filled")
    except Exception as e:
        print(f"  fill err: {e}")

    # Find and click submit button
    print("\nClicking submit...")
    try:
        # Try various button selectors
        for sel in ['button[type="submit"]', 'input[type="submit"]', 'button:has-text("הירשם")', 'button:has-text("Register")', 'button:has-text("Sign")', 'button.submit']:
            if page.locator(sel).count() > 0:
                print(f"  clicking {sel}")
                page.locator(sel).first.click(timeout=10000)
                break
        time.sleep(8)  # wait for response
    except Exception as e:
        print(f"  submit err: {e}")

    # Print final URL and any visible message
    print(f"\nFinal URL: {page.url}")
    final_html = page.content()
    print(f"Final HTML len: {len(final_html)}")
    with open("_signup_final.html","w",encoding="utf-8") as f: f.write(final_html)

    # Look for success/error text
    for marker in ['success','sent','verify','confirm','error','invalid','already','wrong','שגיאה','נשלח','אישור']:
        if marker.lower() in final_html.lower() or marker in final_html:
            idx = max(final_html.lower().find(marker.lower()), final_html.find(marker))
            ctx_str = re.sub(r'<[^>]+>',' ',final_html[max(0,idx-200):idx+400])
            ctx_str = re.sub(r'\s+',' ',ctx_str)
            print(f"  '{marker}': ...{ctx_str[:400]}...")

    print("\n=== Network activity (POST/etc) ===")
    for entry in captured[-15:]:
        if entry[0] == "REQ":
            print(f"  REQ {entry[1]} {entry[2][:120]} ct={entry[3][:30]} body={entry[4][:200]}")
        else:
            print(f"  RESP {entry[1]} {entry[2][:120]} ct={entry[3][:30]} body={entry[4][:200]}")

    browser.close()

print("\nDone — check Gmail for verification email.")
