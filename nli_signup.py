"""Auto-register at api2.nli.org.il/signup, get API key after email verification."""
import os, re, sys, time, json
import requests as plain_req

flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

def flare_get(target, session=None):
    payload = {"cmd": "request.get", "url": target, "maxTimeout": 60000}
    if session: payload["session"] = session
    r = plain_req.post(flaresolverr_url, json=payload, timeout=120)
    sol = r.json().get("solution", {})
    return sol

def flare_post(target, post_data, session=None):
    payload = {"cmd": "request.post", "url": target, "postData": post_data, "maxTimeout": 60000}
    if session: payload["session"] = session
    r = plain_req.post(flaresolverr_url, json=payload, timeout=120)
    return r.json()

# Step 0: create persistent session
sess_id = "nli_signup"
plain_req.post(flaresolverr_url, json={"cmd":"sessions.create","session":sess_id}, timeout=30)

# Step 1: GET signup page, extract csrf_token + form action
print("Step 1: GET /signup/")
sol = flare_get("https://api2.nli.org.il/signup/", session=sess_id)
html = sol.get("response","")
print(f"  got {len(html)} chars, status={sol.get('status')}")
# Save full
with open("_signup_form.html","w",encoding="utf-8") as f: f.write(html)

# Find ALL forms
forms = re.findall(r'<form([^>]*)>([\s\S]*?)</form>', html)
for i, (attrs, body) in enumerate(forms):
    print(f"\n  FORM {i}: attrs={attrs[:200]}")
    inputs = re.findall(r'<input[^>]+>', body)
    for inp in inputs:
        n = re.search(r'name="([^"]+)"', inp)
        v = re.search(r'value="([^"]*)"', inp)
        t = re.search(r'type="([^"]*)"', inp)
        print(f"    input type={t.group(1) if t else '?':10s} name={n.group(1) if n else '?':30s} value={(v.group(1) if v else '')[:60]}")

# Find authenticity_token in any input or meta
csrf = None
csrf_m = re.search(r'name="authenticity_token"\s+value="([^"]+)"', html)
if csrf_m: csrf = csrf_m.group(1)
if not csrf:
    meta_m = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
    if meta_m: csrf = meta_m.group(1)
print(f"\n  csrf: {(csrf[:30]+'...') if csrf else 'NOT FOUND'}")

# Form action
action_m = re.search(r'<form[^>]+action="([^"]+)"', html, re.I)
action = action_m.group(1) if action_m else "/users"
print(f"  form action: {action}")

# Hidden inputs
hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
print(f"  hidden fields (in any form): {list(hidden.keys())}")

# Step 2: POST signup with the user details
form_data = {
    **hidden,
    "user[first_name]": "Yosef",
    "user[last_name]": "Schneider",
    "user[email]": "6742853@gmail.com",
    "user[terms_and_conditions]": "1",
    "user[registration_source]": "website",
}
if csrf: form_data["authenticity_token"] = csrf
from urllib.parse import urlencode

# Try multiple endpoint variants to discover the right one
endpoints_to_try = [
    "https://api2.nli.org.il/users",
    "https://api2.nli.org.il/api/v1/users",
    "https://api2.nli.org.il/api/users",
    "https://api2.nli.org.il/signup",
    "https://api2.nli.org.il/api/v1/signup",
]
out_html = ""
for post_url in endpoints_to_try:
    print(f"\nStep 2: POST to {post_url}")
    body_str = urlencode(form_data)
    resp = flare_post(post_url, body_str, session=sess_id)
    sol2 = resp.get("solution",{})
    code = sol2.get('status'); body = sol2.get("response","")
    print(f"  HTTP {code}, body len {len(body)}, body[:300]: {body[:300]}")
    if code and code not in (404, 405):
        out_html = body
        # Save for inspection
        with open("_signup_response.html","w",encoding="utf-8") as f: f.write(body)
        break

# Also try JSON content-type
print(f"\nStep 3: try JSON POST to /users")
import json as jsonm
json_body = jsonm.dumps({"user": {
    "first_name":"Yosef","last_name":"Schneider","email":"6742853@gmail.com",
    "terms_and_conditions":True,"registration_source":"web"
}})
# FlareSolverr request.post does form encoding by default. Try direct via cookies extracted.
cookies_arr = sol.get("cookies",[]) if 'sol' in dir() else []
ck_hdr = "; ".join(f"{c['name']}={c['value']}" for c in cookies_arr)
ua_str = sol.get("userAgent","Mozilla/5.0") if 'sol' in dir() else "Mozilla/5.0"
for ep in ["https://api2.nli.org.il/users", "https://api2.nli.org.il/api/v1/users"]:
    try:
        rr = plain_req.post(ep, data=json_body,
                            headers={"Content-Type":"application/json","Accept":"application/json",
                                     "Cookie": ck_hdr, "User-Agent": ua_str,
                                     "Referer":"https://api2.nli.org.il/signup/"},
                            timeout=30)
        print(f"  JSON POST {ep} → {rr.status_code}, body[:300]: {rr.text[:300]}")
    except Exception as e:
        print(f"  err: {e}")

# Look for success/error indicators
for marker in ['success','confirm','sent','verify','error','invalid','already','exists','wrong']:
    if marker.lower() in out_html.lower():
        # Find context
        idx = out_html.lower().find(marker.lower())
        ctx = re.sub(r'\s+',' ',out_html[max(0,idx-100):idx+200])
        print(f"  '{marker}' context: ...{ctx[:300]}...")
        break

# Cleanup session
plain_req.post(flaresolverr_url, json={"cmd":"sessions.destroy","session":sess_id}, timeout=30)
print("\nDone. Check 6742853@gmail.com inbox for verification email.")
