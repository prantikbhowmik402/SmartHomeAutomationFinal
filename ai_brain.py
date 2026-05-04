"""
ai_brain.py — Smart Home AI Brain
Primary:  Groq API  (llama-3.3-70b — 14,400 free requests/day, super fast)
Fallback: Gemini    (gemini-1.5-flash — if Groq unavailable)
"""

import json, os, threading, time, requests, re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# ── AI ENGINE ────────────────────────────────────────────

def _ask_groq(prompt, system=""):
    if not GROQ_API_KEY:
        return None
    msgs = []
    if system: msgs.append({"role":"system","content":system})
    msgs.append({"role":"user","content":prompt})
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b-versatile","messages":msgs,"temperature":0.4,"max_tokens":1024},
            timeout=15)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Groq] Error: {e}"); return None

def _ask_gemini(prompt, system=""):
    if not GEMINI_API_KEY:
        return '{"actions":[],"reply":"AI key missing — .env mein GROQ_API_KEY daalo","reason":"no key"}'
    full = f"{system}\n\n{prompt}" if system else prompt
    try:
        r = requests.post(f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json={"contents":[{"parts":[{"text":full}]}],"generationConfig":{"temperature":0.4,"maxOutputTokens":1024}},
            timeout=15)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        return f'{{"actions":[],"reply":"AI Error: {str(e)[:80]}","reason":"error"}}'

def ask_ai(prompt, system=""):
    result = _ask_groq(prompt, system)
    if result is not None: return result
    print("[AI] Groq unavailable, trying Gemini...")
    return _ask_gemini(prompt, system)

def ask_ai_json(prompt, system=""):
    raw = ask_ai(prompt, system)
    clean = raw.strip()
    if "```" in clean:
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.startswith("json"): clean = clean[4:]
    try:
        return json.loads(clean.strip())
    except Exception:
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        if m:
            try: return json.loads(m.group())
            except: pass
        return {"error":raw,"actions":[],"reply":raw,"reason":raw}

# Legacy compat
def ask_gemini(p,s=""): return ask_ai(p,s)
def ask_gemini_json(p,s=""): return ask_ai_json(p,s)

# ── WEATHER ───────────────────────────────────────────

_wc = {"data":None,"fetched_at":0,"lat":None,"lon":None}

def fetch_weather(lat, lon):
    now = time.time()
    if _wc["data"] and _wc["lat"]==lat and _wc["lon"]==lon and now-_wc["fetched_at"]<600:
        return _wc["data"]
    if not OPENWEATHER_API_KEY: return {}
    try:
        r = requests.get(f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric",timeout=8)
        r.raise_for_status(); raw = r.json()
        data = {
            "temp":round(raw["main"]["temp"],1),"feels_like":round(raw["main"]["feels_like"],1),
            "humidity":raw["main"]["humidity"],"condition":raw["weather"][0]["main"],
            "description":raw["weather"][0]["description"],"wind_speed":raw["wind"]["speed"],
            "city":raw.get("name","Unknown"),
            "is_raining":raw["weather"][0]["main"] in ("Rain","Drizzle","Thunderstorm"),
            "is_hot":raw["main"]["temp"]>30,"is_cold":raw["main"]["temp"]<18,
        }
        _wc.update({"data":data,"fetched_at":now,"lat":lat,"lon":lon})
        print(f"[Weather] {data['city']}: {data['temp']}°C, {data['condition']}")
        return data
    except Exception as e:
        print(f"[Weather] Error: {e}"); return _wc["data"] or {}

# ── SUN TIMES ─────────────────────────────────────────

_sc = {"data":None,"date":None,"lat":None,"lon":None}

def fetch_sun_times(lat, lon):
    today = datetime.now().strftime("%Y-%m-%d")
    if _sc["data"] and _sc["date"]==today and _sc["lat"]==lat and _sc["lon"]==lon:
        return _sc["data"]
    try:
        r = requests.get(f"https://api.sunrise-sunset.org/json?lat={lat}&lng={lon}&formatted=0",timeout=8)
        r.raise_for_status(); raw = r.json()["results"]
        def tl(s):
            dt = datetime.fromisoformat(s.replace("Z","+00:00"))
            return dt.astimezone().strftime("%H:%M")
        sr,ss = tl(raw["sunrise"]),tl(raw["sunset"])
        now = datetime.now().strftime("%H:%M")
        def minto(t):
            h,m=map(int,t.split(":")); now2=datetime.now()
            delta=int((now2.replace(hour=h,minute=m,second=0,microsecond=0)-now2).total_seconds()/60)
            if delta<0: delta+=24*60
            return delta
        data = {"sunrise":sr,"sunset":ss,"solar_noon":tl(raw["solar_noon"]),
                "is_daytime":sr<=now<=ss,"minutes_to_sunset":minto(ss),"minutes_to_sunrise":minto(sr)}
        _sc.update({"data":data,"date":today,"lat":lat,"lon":lon})
        print(f"[Sun] Rise {sr}, Set {ss}, Day:{data['is_daytime']}")
        return data
    except Exception as e:
        print(f"[Sun] Error: {e}")
        return _sc["data"] or {"is_daytime":True,"sunrise":"06:00","sunset":"18:30","solar_noon":"12:15","minutes_to_sunset":0,"minutes_to_sunrise":0}

# ── PROMPTS ───────────────────────────────────────────

AUTOMATION_SYSTEM = """You are a smart home automation AI. Respond ONLY with valid JSON.
Rules: temp>30=fan 4+ac on, temp>35=fan 5, temp<18=fan off+ac off, rain=curtains closed,
after sunset=lights on, 30min before sunset=dimmer 60%, night=lights off unless needed.
Be conservative, only change what truly needs changing.
Format:
{"actions":[{"room":"living","device":"light","value":true}],"reason":"one line English reason"}
Devices: light(bool), fan_speed(0-5), curtain(bool), dimmer(0-100), ac(bool)
Rooms: living, bedroom, kitchen, balcony
IMPORTANT: ac device is ONLY valid for rooms: living, bedroom. Never set ac for kitchen or balcony."""

CHAT_SYSTEM = """You are Kitty, a smart home AI assistant. Respond ONLY with valid JSON.

LANGUAGE RULE (very important):
- DEFAULT: Always reply in English.
- If the user's message contains Hindi or Hinglish words (like "karo", "band", "chalu", "garmi", "bahut", "kar do", "on kar", "off kar", "bhai", "yaar", etc.), then reply in Hinglish (mix of English + casual Hindi).
- Match the user's vibe — if they're casual in Hinglish, be casual back. If they're formal in English, be polished back.
- Never reply in pure Hindi. Hinglish means English sentences with some Hindi words mixed in naturally.

English reply examples:
- "Sure! The light is now ON ✅"
- "It's really hot outside, I've turned on the AC for you ❄️"
- "Done! Fan speed set to 3 in the living room 🌀"
- "All lights have been turned off. Good night! 🌙"

Hinglish reply examples (only when user writes in Hinglish):
- "Done! Light on kar di ✅"
- "Bahut garmi hai bahar, AC on kar diya ❄️"
- "Fan speed 3 kar diya living room mein 🌀"
- "Sab lights band kar di. Good night! 🌙"

Control: light(bool), fan_speed(0-5), curtain(bool), dimmer(0-100), ac(bool), music(string)
Rooms: living, bedroom, kitchen, balcony
IMPORTANT: ac is ONLY available in living and bedroom. Never control ac for kitchen or balcony.
Format for control: {"reply":"your reply here","actions":[{"room":"living","device":"light","value":true}]}
Format for questions: {"reply":"your answer here","actions":[]}
Always valid JSON only, no extra text."""

# ── MAIN FUNCTIONS ────────────────────────────────────

def run_automation(lat, lon, current_rooms):
    w = fetch_weather(lat, lon); s = fetch_sun_times(lat, lon)
    if not w: return {"actions":[],"reason":"Weather unavailable"}
    ctx = f"""Time:{datetime.now().strftime('%H:%M')} City:{w.get('city')}
Temp:{w.get('temp')}°C feels:{w.get('feels_like')}°C humidity:{w.get('humidity')}%
Condition:{w.get('condition')} rain:{w.get('is_raining')} hot:{w.get('is_hot')} cold:{w.get('is_cold')}
Sunrise:{s.get('sunrise')} Sunset:{s.get('sunset')} Daytime:{s.get('is_daytime')} MinToSunset:{s.get('minutes_to_sunset')}
Current states:{json.dumps(current_rooms)}"""
    return ask_ai_json(ctx, AUTOMATION_SYSTEM)

def chat_with_ai(user_message, lat, lon, current_rooms, history):
    w = fetch_weather(lat, lon); s = fetch_sun_times(lat, lon)
    hist = "\n".join([f"{h['role'].upper()}: {h['text']}" for h in history[-4:]])
    ctx = f"""Time:{datetime.now().strftime('%A %d %B %Y %H:%M')} City:{w.get('city','?')}
Temp:{w.get('temp','?')}°C {w.get('condition','?')} {w.get('description','?')}
Rain:{w.get('is_raining')} Hot:{w.get('is_hot')} Cold:{w.get('is_cold')}
Sunrise:{s.get('sunrise','?')} Sunset:{s.get('sunset','?')} Daytime:{s.get('is_daytime')} MinToSunset:{s.get('minutes_to_sunset','?')}
Devices:{json.dumps(current_rooms)}
History:{hist}
USER:{user_message}"""
    return ask_ai_json(ctx, CHAT_SYSTEM)

def get_current_context(lat, lon):
    w = fetch_weather(lat, lon) if lat and lon else {}
    s = fetch_sun_times(lat, lon) if lat and lon else {}
    return {"weather":w,"sun":s,"time":datetime.now().strftime("%H:%M"),"date":datetime.now().strftime("%A, %d %B %Y")}

# ── AUTOMATION LOOP ───────────────────────────────────

_auto_thread=None; _auto_running=False; _auto_interval=300
_auto_callback=None; _auto_location={"lat":None,"lon":None}
_last_auto_result={"actions":[],"reason":"","time":""}

def set_location(lat,lon): _auto_location["lat"]=lat; _auto_location["lon"]=lon
def set_auto_callback(fn): global _auto_callback; _auto_callback=fn

def _worker(get_rooms_fn):
    global _auto_running,_last_auto_result
    print("[AI Brain] Loop started")
    while _auto_running:
        lat=_auto_location.get("lat"); lon=_auto_location.get("lon")
        if lat and lon:
            try:
                result=run_automation(float(lat),float(lon),get_rooms_fn())
                actions=result.get("actions",[]); reason=result.get("reason","")
                _last_auto_result={"actions":actions,"reason":reason,"time":datetime.now().strftime("%H:%M:%S")}
                if actions and _auto_callback: _auto_callback(actions,reason); print(f"[AI] {len(actions)} actions: {reason}")
                else: print(f"[AI] No changes: {reason}")
            except Exception as e: print(f"[AI Brain] Error: {e}")
        else: print("[AI Brain] Waiting for GPS...")
        time.sleep(_auto_interval)

def start_automation(get_rooms_fn, interval_seconds=300):
    global _auto_thread,_auto_running,_auto_interval
    if _auto_running: return {"success":False,"message":"Already running"}
    _auto_running=True; _auto_interval=interval_seconds
    _auto_thread=threading.Thread(target=_worker,args=(get_rooms_fn,),daemon=True)
    _auto_thread.start()
    return {"success":True,"message":f"Started (every {interval_seconds}s)"}

def stop_automation():
    global _auto_running; _auto_running=False
    return {"success":True,"message":"Stopped"}

def get_automation_status():
    return {"running":_auto_running,"location":_auto_location,"last_result":_last_auto_result,"interval":_auto_interval}