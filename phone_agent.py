#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Phone Agent v2 — GitHub Actions, every 5 minutes.
ext3 (record) -> Gemini STT -> Gemini Pro chat (with per-caller memory) -> Gemini TTS -> ext2.
Memory: docs/phone_history.json (keyed by caller phone number).
Tools: video download (repository_dispatch), web search (DuckDuckGo).
"""
import os, json, requests, base64, time, struct, re, datetime

YEMOT_USER     = os.environ["YEMOT_USER"]
YEMOT_PASS     = os.environ["YEMOT_PASS"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
GH_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
YEMOT_API      = "https://www.call2all.co.il/ym/api"
EXT_RECORD     = "3"
EXT_ANSWER     = "2"
SEEN_FILE      = "docs/phone_seen.json"
HEARTBEAT_FILE = "docs/pc_heartbeat.json"
HISTORY_FILE   = "docs/phone_history.json"
GH_REPO        = "beit-hatalmud/vimeo-downloader"
PC_ALIVE_MIN   = 10
MAX_HIST       = 20  # turns to keep per caller
CHAT_MODEL     = "gemini-2.5-pro"


# ── PC heartbeat ──────────────────────────────────────────────────────
def pc_is_alive():
    if not os.path.exists(HEARTBEAT_FILE):
        return False
    try:
        with open(HEARTBEAT_FILE, encoding="utf-8") as f:
            hb = json.load(f)
        ts = time.mktime(time.strptime(hb["ts"], "%Y-%m-%dT%H:%M:%SZ"))
        age = (time.time() - ts) / 60
        print(f"PC heartbeat age: {age:.1f} min")
        return age < PC_ALIVE_MIN
    except Exception as e:
        print(f"Heartbeat error: {e}")
        return False


# ── History ───────────────────────────────────────────────────────────
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def format_history_for_prompt(turns):
    if not turns:
        return "אין שיחות קודמות."
    lines = []
    for h in turns[-6:]:
        lines.append(f"[{h['ts']}] יוסף: {h['user']}")
        lines.append(f"[{h['ts']}] סוכן: {h['agent']}")
    return "\n".join(lines)


# ── Yemot ─────────────────────────────────────────────────────────────
def yemot_login():
    r = requests.get(f"{YEMOT_API}/Login",
        params={"username": YEMOT_USER, "password": YEMOT_PASS}, timeout=10)
    d = r.json()
    if d.get("responseStatus") != "OK":
        raise RuntimeError(f"Yemot login failed: {d}")
    return d["token"]

def yemot_list(tok):
    r = requests.get(f"{YEMOT_API}/GetIVR2Dir",
        params={"token": tok, "path": f"ivr2:/{EXT_RECORD}"}, timeout=10)
    return r.json()

def yemot_metadata(tok, name):
    r = requests.get(f"{YEMOT_API}/GetFile",
        params={"token": tok, "path": f"ivr2:/{EXT_RECORD}/{name}"}, timeout=10)
    try:
        f = r.json().get("file", {})
        return {
            "phone": f.get("phone", "unknown"),
            "date":  f.get("date", ""),
            "duration": f.get("duration", 0),
        }
    except Exception:
        return {"phone": "unknown", "date": "", "duration": 0}

def yemot_download(tok, name):
    r = requests.get(f"{YEMOT_API}/DownloadFile",
        params={"token": tok, "path": f"ivr2:/{EXT_RECORD}/{name}"}, timeout=30)
    if r.status_code == 200 and r.content[:4] == b'RIFF':
        return r.content
    print(f"  DownloadFile failed: {r.status_code} {r.content[:80]}")
    return None

def yemot_upload(tok, wav_bytes):
    ts = int(time.time())
    out_path = f"{EXT_ANSWER}/cloud_answer_{ts}.wav"
    r = requests.post(f"{YEMOT_API}/UploadFile",
        data={"token": tok, "path": f"ivr2:/{out_path}"},
        files={"file": ("answer.wav", wav_bytes, "audio/wav")},
        timeout=30)
    return r.json()


# ── Gemini STT ────────────────────────────────────────────────────────
def transcribe(audio_bytes):
    b64 = base64.b64encode(audio_bytes).decode()
    body = {
        "contents": [{"parts": [
            {"text": "תמלל את הקלטת השמע לעברית. החזר רק את הטקסט המדויק."},
            {"inlineData": {"mimeType": "audio/wav", "data": b64}}
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024}
    }
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}",
        json=body, timeout=60)
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        return ""


# ── Web search ────────────────────────────────────────────────────────
def web_search(query):
    try:
        r = requests.get("https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            timeout=8)
        d = r.json()
        results = []
        if d.get("AbstractText"):
            results.append(d["AbstractText"])
        for t in d.get("RelatedTopics", [])[:3]:
            if isinstance(t, dict) and t.get("Text"):
                results.append(t["Text"])
        return "\n".join(results[:3]) if results else None
    except Exception:
        return None

SEARCH_KEYWORDS = ["חפש", "מה זה", "מה הוא", "מי הוא", "מי זה", "כמה עולה",
                   "מחיר", "מתי", "היכן", "איפה", "טלפון של", "כתובת של"]

def needs_search(text):
    return any(k in text for k in SEARCH_KEYWORDS)


# ── Gemini chat ───────────────────────────────────────────────────────
def build_system(caller_history, caller_phone, call_date):
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%d/%m/%Y %H:%M")
    history_text = format_history_for_prompt(caller_history)
    return f"""אתה הסוכן הקולי של יוסף שניידר — מזכיר ישיבת בית התלמוד, מעלה עמוס.
יוסף מדבר דרך הטלפון (0772251404 שלוחה 3). עכשיו: {now}.
מתקשר: {caller_phone} | תאריך שיחה: {call_date}

יכולות שלך:
• תשובות על כל שאלה — הלכה, ניהול, טכנולוגיה, כספים, תכנון
• הורדת סרטונים מיוטיוב/וימאו/ערוץ 12-13 לדרייב — אמור URL ואני מפעיל
• חיפוש מידע ברשת — אם תשובה מחייבת חיפוש אמור "מחפש: [שאלה]"
• הכרת לוח שנה, שעות, חישובים
• ייעוץ בכל נושא — תמיד עם זווית ביקורתית

שיחות קודמות עם מתקשר זה:
{history_text}

כללי תגובה קבועים:
- עברית בלבד, ללא אנגלית, ללא bullets, ללא emojis
- אורך לפי מורכבות: שאלה פשוטה=1-2 משפטים, מורכבת=עד 5
- תמיד ציין סיכון אחד או מה לא נבדק (אתה פסימי וביקורתי)
- התייחס להיסטוריה הקודמת כשרלוונטי
- אל תפתח ב"שלום" ואל תסיים ב"אם יש עוד שאלות"
- אם הבקשה לא ברורה — בקש הבהרה ספציפית"""

def ai_respond(transcript, caller_history, caller_phone, call_date, search_result=None):
    url_match = re.search(r'https?://\S+', transcript)
    dl_kw = ["הורד", "תוריד", "youtube", "יוטיוב", "סרטון", "וידאו", "ערוץ 12", "ערוץ 13"]
    is_dl = url_match or any(k in transcript for k in dl_kw)

    if is_dl and url_match:
        url = url_match.group(0)
        trigger_download(url)
        return "מפעיל הורדה בענן. הסרטון יגיע לדרייב שלך תוך כמה דקות."
    if is_dl:
        return "לא מצאתי קישור. אמור לי את הקישור המלא של הסרטון."

    system = build_system(caller_history, caller_phone, call_date)

    # Inject search result if available
    user_text = transcript
    if search_result:
        user_text = f"{transcript}\n\n[תוצאת חיפוש: {search_result}]"

    # Multi-turn context: last 3 turns as conversation history
    contents = []
    for h in caller_history[-3:]:
        contents.append({"role": "user",  "parts": [{"text": h["user"]}]})
        contents.append({"role": "model", "parts": [{"text": h["agent"]}]})
    contents.append({"role": "user", "parts": [{"text": system + "\n\n---\nשאלה: " + user_text}]})

    body = {"contents": contents,
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 800}}
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{CHAT_MODEL}:generateContent?key={GEMINI_KEY}",
        json=body, timeout=90)
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"  Chat error: {e}, response: {r.text[:200]}")
        return "מצטער, לא הצלחתי לעבד את הבקשה."


# ── Gemini TTS ────────────────────────────────────────────────────────
def tts(text):
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}
        }
    }
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_KEY}",
        json=body, timeout=60)
    try:
        pcm = base64.b64decode(
            r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        rate = 24000
        return (b'RIFF' + struct.pack('<I', 36+len(pcm)) + b'WAVEfmt ' +
                struct.pack('<IHHIIHH', 16, 1, 1, rate, rate*2, 2, 16) +
                b'data' + struct.pack('<I', len(pcm)) + pcm)
    except Exception:
        return None


# ── Video download ────────────────────────────────────────────────────
def trigger_download(url, folder="הורדות מהטלפון"):
    payload = {"event_type": "download-video",
               "client_payload": {"url": url, "quality": "720",
                                  "format": "video", "folder_name": folder}}
    requests.post(f"https://api.github.com/repos/{GH_REPO}/dispatches",
        headers={"Authorization": f"token {GH_TOKEN}",
                 "Accept": "application/vnd.github.v3+json"},
        json=payload, timeout=10)
    print(f"  Download dispatched: {url}")


# ── Main ──────────────────────────────────────────────────────────────
def main():
    os.makedirs("docs", exist_ok=True)

    if pc_is_alive():
        print("PC is alive — local Claude agent handles calls. Skipping.")
        return

    # Load seen list
    first_run = not os.path.exists(SEEN_FILE)
    seen = set()
    if not first_run:
        try:
            with open(SEEN_FILE, encoding="utf-8") as f:
                data = json.load(f)
                seen = set(data)
                if not data:
                    first_run = True
        except Exception:
            first_run = True

    # Load conversation history
    history = load_history()

    print("Logging in to Yemot...")
    tok = yemot_login()

    print(f"Listing ext/{EXT_RECORD}...")
    d = yemot_list(tok)
    files = [x for x in d.get("dirs", []) if isinstance(x, dict) and x.get("fileType") == "FILE"]
    files += [x for x in d.get("files", []) if isinstance(x, dict)]
    print(f"Found {len(files)} files, {len(seen)} already seen")

    if first_run:
        all_names = [x.get("name", "") for x in files if x.get("name")]
        print(f"First run: marking {len(all_names)} existing files as seen")
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(all_names[-500:], f)
        return

    processed = 0
    for item in sorted(files, key=lambda x: x.get("name", "")):
        name = item.get("name", "")
        if not name or name in seen:
            continue

        print(f"\nProcessing: {name}")

        # Get caller metadata BEFORE downloading audio
        meta = yemot_metadata(tok, name)
        caller_phone = meta["phone"]
        call_date    = meta["date"]
        print(f"  Caller: {caller_phone} | Date: {call_date} | Duration: {meta['duration']:.0f}s")

        audio = yemot_download(tok, name)
        if not audio:
            seen.add(name)
            continue

        print(f"  Transcribing {len(audio)//1024}KB...")
        transcript = transcribe(audio)
        print(f"  Text: {transcript[:150]}")

        if len(transcript.strip()) < 3:
            print("  Too short, skipping")
            seen.add(name)
            continue

        # Web search if needed
        search_result = None
        if needs_search(transcript):
            print("  Web search...")
            search_result = web_search(transcript)
            if search_result:
                print(f"  Search: {search_result[:80]}")

        # Get this caller's history
        caller_history = history.get(caller_phone, [])
        print(f"  Caller history: {len(caller_history)} previous turns")

        print("  Getting AI response (Gemini Pro)...")
        response_text = ai_respond(transcript, caller_history, caller_phone, call_date, search_result)
        print(f"  Response: {response_text[:200]}")

        print("  Generating TTS...")
        wav = tts(response_text)
        if not wav:
            print("  TTS failed")
            seen.add(name)
            continue

        result = yemot_upload(tok, wav)
        print(f"  Upload: {result.get('responseStatus')} | {result.get('path')}")

        # Save to history
        if caller_phone not in history:
            history[caller_phone] = []
        history[caller_phone].append({
            "ts":    call_date or datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M"),
            "file":  name,
            "user":  transcript,
            "agent": response_text
        })
        history[caller_phone] = history[caller_phone][-MAX_HIST:]

        seen.add(name)
        processed += 1
        if processed >= 5:
            break

    # Save state
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-500:], f)
    save_history(history)
    print(f"\nDone. Processed {processed} new recordings.")


if __name__ == "__main__":
    main()
