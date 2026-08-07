"""Inspect NLI API signup page to understand registration flow."""
import os, re, sys
import requests as plain_req

flaresolverr_url = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")

def flare_get(target):
    r = plain_req.post(flaresolverr_url, json={
        "cmd": "request.get", "url": target, "maxTimeout": 60000
    }, timeout=120)
    sol = r.json().get("solution", {})
    return sol.get("status",0), sol.get("response",""), sol.get("url","")

# Probe likely signup endpoints
urls = [
    "https://api2.nli.org.il/",
    "https://api.nli.org.il/openlibrary/index.html",
    "https://www.nli.org.il/he/openlibrary",
    "https://www.nli.org.il/he/openlibrary/api-key",
    "https://api2.nli.org.il/login",
    "https://api2.nli.org.il/signup",
    "https://api2.nli.org.il/users/sign_up",
    "https://api2.nli.org.il/register",
]
for u in urls:
    print(f"\n=== {u} ===")
    status, body, final = flare_get(u)
    print(f"  status={status}, final={final[:120]}")
    print(f"  body[:1000]: {body[:1000]}")
    # Save likely useful pages
    if 'form' in body.lower() and ('email' in body.lower() or 'register' in body.lower() or 'sign' in body.lower()):
        fname = re.sub(r'[^\w]','_',u)[:60]
        with open(f"_signup_{fname}.html","w",encoding="utf-8") as f: f.write(body)
        print(f"  → saved _signup_{fname}.html")
        # Find form fields
        forms = re.findall(r'<form[^>]*>([\s\S]*?)</form>', body)
        for i, f in enumerate(forms[:3]):
            inputs = re.findall(r'<input[^>]+name="([^"]+)"', f)
            print(f"  form {i}: inputs={inputs}")
