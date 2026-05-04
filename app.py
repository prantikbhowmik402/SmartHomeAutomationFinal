import json
import os
import re
import threading
import time

import bcrypt
from datetime import timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO

# ── Resolve base directory so all paths work regardless of cwd ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

# ── Load .env ──────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))
app.secret_key = os.getenv("SECRET_KEY", "smarthome-dev-secret-change-in-prod")

# FIX: session expires after 24 hours
app.permanent_session_lifetime = timedelta(hours=24)

CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ── Engines ────────────────────────────────────────────
try:
    from music_engine import play as music_play, pause_resume, stop as music_stop, set_volume, get_status as music_status
    MUSIC_AVAILABLE = True
except ImportError:
    MUSIC_AVAILABLE = False

try:
    from voice_engine import start_listening, stop_listening, get_status as voice_get_status, set_status_callback
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

try:
    from ai_brain import (
        chat_with_ai, run_automation, get_current_context,
        start_automation, stop_automation, get_automation_status,
        set_location, set_auto_callback
    )
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

# ── FEATURE 1: Persistent Memory Engine ───────────────
try:
    from memory_engine import (
        add_message, get_recent_history, get_memory_context,
        learn_fact, update_preference, get_stats, clear_history
    )
    MEMORY_AVAILABLE = True
    print("[Memory] ✅ Memory engine loaded")
except ImportError:
    MEMORY_AVAILABLE = False
    print("[Memory] ⚠️ memory_engine.py not found — memory disabled")

    def add_message(role, text, username="default"): pass
    def get_recent_history(n=6, username="default"): return []
    def get_memory_context(username="default"): return ""
    def learn_fact(fact, username="default"): pass
    def update_preference(key, value, username="default"): pass
    def get_stats(username="default"): return {"total_messages":0,"learned_facts":0,"history_count":0,"last_updated":None,"preferences":{},"facts":[]}
    def clear_history(username="default"): pass

# ── FEATURE 2: Energy Analytics Engine ────────────────
try:
    from energy_engine import (
        log_device_event, get_today_summary,
        get_weekly_summary, get_recent_events, get_top_consumers
    )
    ENERGY_AVAILABLE = True
    print("[Energy] ✅ Energy engine loaded")
except ImportError:
    ENERGY_AVAILABLE = False
    print("[Energy] ⚠️ energy_engine.py not found — energy tracking disabled")

    def log_device_event(room, device, state, old_state=None): pass
    def get_today_summary(): return {"total_kwh":0,"cost_inr":0,"total_events":0,"live_watts":0,"room_kwh":{},"device_kwh":{}}
    def get_weekly_summary(): return []
    def get_recent_events(n=20): return []
    def get_top_consumers(): return []

# ── State ──────────────────────────────────────────────
STATE_FILE     = os.path.join(BASE_DIR, "state.json")
USER_FILE      = os.path.join(BASE_DIR, "users.json")
SCHEDULES_FILE = os.path.join(BASE_DIR, "schedules.json")  # FIX: persist schedules
_state_lock    = threading.RLock()

DEFAULT_STATE = {
    r: {"light": False, "fan_speed": 0, "curtain": False, "dimmer": 50, "inverter": False, "ac": False}
    for r in ["living", "bedroom", "kitchen", "balcony"]
}

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE)
        return DEFAULT_STATE.copy()
    with open(STATE_FILE) as f:
        data = json.load(f)
    if "living" not in data:
        save_state(DEFAULT_STATE)
        return DEFAULT_STATE.copy()
    changed = False
    for room in DEFAULT_STATE:
        if room not in data:
            data[room] = DEFAULT_STATE[room].copy(); changed = True
        for key, val in DEFAULT_STATE[room].items():
            if key not in data[room]:
                data[room][key] = val; changed = True
    # FIX: kitchen and balcony should never have AC = True
    for room in ("kitchen", "balcony"):
        if data.get(room, {}).get("ac"):
            data[room]["ac"] = False
            changed = True
    if changed:
        save_state(data)
    return data

def save_state(state):
    with _state_lock:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

rooms = load_state()

def persist():
    save_state(rooms)

def emit_update():
    socketio.emit("state_update", rooms)

def get_room(r):
    return rooms.get(r, rooms["living"])

_users_lock = threading.Lock()

def load_users():
    if not os.path.exists(USER_FILE):
        return {}
    with open(USER_FILE) as f:
        return json.load(f)

def save_users(users):
    with _users_lock:
        with open(USER_FILE, "w") as f:
            json.dump(users, f, indent=2)

# ── Activity Log ───────────────────────────────────────
activity_log = []
MAX_LOG      = 50
_log_lock    = threading.Lock()

def log_action(icon, message, room=None, device=None, state=None, old_state=None):
    from datetime import datetime
    entry = {"time": datetime.now().strftime("%I:%M:%S %p"), "icon": icon, "message": message}
    with _log_lock:
        activity_log.insert(0, entry)
        if len(activity_log) > MAX_LOG:
            activity_log.pop()
    socketio.emit("log_update", activity_log)

    if room and device and state is not None:
        # FIX: don't log AC events for rooms without AC
        if not (device == "ac" and room in ("kitchen", "balcony")):
            try:
                log_device_event(room, device, state, old_state)
            except Exception as e:
                print(f"[Energy] Log error: {e}")

    critical_icons = {"⚠️", "🚨", "🔥", "🔒"}
    if icon in critical_icons:
        socketio.emit("push_notification", {"title": "🏠 Smart Home Alert", "body": message, "tag": "alert"})
    elif icon == "🤖":
        socketio.emit("push_notification", {"title": "🤖 AI Auto-Control", "body": message, "tag": "ai"})
    elif icon == "⏰":
        socketio.emit("push_notification", {"title": "⏰ Schedule Executed", "body": message, "tag": "schedule"})


# ── Schedules — FIX: persistent across restarts ────────
def load_schedules():
    if not os.path.exists(SCHEDULES_FILE):
        return []
    try:
        with open(SCHEDULES_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_schedules(sched_list):
    with _state_lock:
        with open(SCHEDULES_FILE, "w") as f:
            json.dump(sched_list, f, indent=2)

schedules = load_schedules()

def schedule_checker():
    fired = {}
    while True:
        try:
            from datetime import datetime
            dt    = datetime.now()
            now   = dt.strftime("%H:%M")
            today = dt.strftime("%Y-%m-%d")
            with _state_lock:
                current_schedules = list(schedules)
            for sch in current_schedules:
                room, device = sch.get("room", "living"), sch.get("device", "light")
                on_time, off_time = sch.get("on_time", ""), sch.get("off_time", "")
                on_key  = (room, device, on_time,  "on")
                off_key = (room, device, off_time, "off")
                if on_time and now == on_time and fired.get(on_key) != today:
                    fired[on_key] = today
                    old = rooms[room].get(device, False)
                    if device == "light":
                        rooms[room]["light"] = True
                        log_action("⏰", f"[{room.title()}] Schedule: Light ON", room=room, device="light", state=True, old_state=old)
                    elif device == "fan":
                        rooms[room]["fan_speed"] = 3
                        log_action("⏰", f"[{room.title()}] Schedule: Fan ON", room=room, device="fan_speed", state=3, old_state=old)
                    elif device == "curtain":
                        rooms[room]["curtain"] = True
                        log_action("⏰", f"[{room.title()}] Schedule: Curtain Open", room=room, device="curtain", state=True, old_state=old)
                    persist(); emit_update()
                if off_time and now == off_time and fired.get(off_key) != today:
                    fired[off_key] = today
                    old = rooms[room].get(device, False)
                    if device == "light":
                        rooms[room]["light"] = False
                        log_action("⏰", f"[{room.title()}] Schedule: Light OFF", room=room, device="light", state=False, old_state=old)
                    elif device == "fan":
                        rooms[room]["fan_speed"] = 0
                        log_action("⏰", f"[{room.title()}] Schedule: Fan OFF", room=room, device="fan_speed", state=0, old_state=old)
                    elif device == "curtain":
                        rooms[room]["curtain"] = False
                        log_action("⏰", f"[{room.title()}] Schedule: Curtain Closed", room=room, device="curtain", state=False, old_state=old)
                    persist(); emit_update()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(5)

threading.Thread(target=schedule_checker, daemon=True).start()


# ══════════════════════════════════════════════════════════════════
# AI BRAIN INTEGRATION
# ══════════════════════════════════════════════════════════════════

if AI_AVAILABLE:
    def _ai_action_callback(actions: list, reason: str):
        changed = []
        with _state_lock:
            for action in actions:
                room   = action.get("room", "living")
                device = action.get("device")
                value  = action.get("value")
                if room not in rooms:
                    continue
                if device == "light":
                    old = rooms[room]["light"]
                    rooms[room]["light"] = bool(value)
                    log_device_event(room, "light", bool(value), old)
                    changed.append(f"💡 {room} light → {'ON' if value else 'OFF'}")
                elif device == "fan_speed":
                    old = rooms[room]["fan_speed"]
                    rooms[room]["fan_speed"] = max(0, min(5, int(value)))
                    log_device_event(room, "fan_speed", int(value), old)
                    changed.append(f"🌀 {room} fan → {value}")
                elif device == "curtain":
                    old = rooms[room]["curtain"]
                    rooms[room]["curtain"] = bool(value)
                    log_device_event(room, "curtain", bool(value), old)
                    changed.append(f"🪟 {room} curtain → {'Open' if value else 'Closed'}")
                elif device == "dimmer":
                    rooms[room]["dimmer"] = max(0, min(100, int(value)))
                    changed.append(f"🔆 {room} dimmer → {value}%")
                elif device == "ac":
                    if room in ("kitchen", "balcony"):
                        continue
                    old = rooms[room]["ac"]
                    rooms[room]["ac"] = bool(value)
                    log_device_event(room, "ac", bool(value), old)
                    changed.append(f"❄️ {room} AC → {'ON' if value else 'OFF'}")
            if changed:
                persist(); emit_update()
        if changed:
            log_action("🤖", f"[AI Auto] {reason} → {' | '.join(changed)}")
            socketio.emit("ai_automation", {
                "actions": actions, "reason": reason,
                "changed": changed,
                "time": __import__('datetime').datetime.now().strftime("%H:%M:%S")
            })

    set_auto_callback(_ai_action_callback)


@app.route("/ai/set_location", methods=["POST"])
def ai_set_location():
    if not AI_AVAILABLE:
        return jsonify({"success": False, "message": "AI not available"})
    data = request.get_json() or {}
    lat, lon = data.get("lat"), data.get("lon")
    if lat is None or lon is None:
        return jsonify({"success": False, "message": "lat/lon required"})
    try:
        lat_f = float(lat); lon_f = float(lon)
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid lat/lon format"})
    set_location(lat_f, lon_f)
    log_action("📍", f"GPS: {lat_f:.4f}°N, {lon_f:.4f}°E")
    return jsonify({"success": True})


@app.route("/ai/context", methods=["GET"])
def ai_context():
    if not AI_AVAILABLE:
        return jsonify({"error": "AI not available"})
    status = get_automation_status()
    lat = status["location"].get("lat")
    lon = status["location"].get("lon")
    if not lat or not lon:
        return jsonify({"error": "No location set"})
    ctx = get_current_context(float(lat), float(lon))
    return jsonify(ctx)


@app.route("/ai/chat", methods=["POST"])
def ai_chat():
    if not AI_AVAILABLE:
        return jsonify({"success": False, "reply": "AI engine not available. Check ai_brain.py"})

    data    = request.get_json() or {}
    message = data.get("message", "").strip()
    lat     = data.get("lat")
    lon     = data.get("lon")

    if not message:
        return jsonify({"success": False, "reply": "Empty message"})

    if lat and lon:
        set_location(float(lat), float(lon))

    status = get_automation_status()
    lat = lat or status["location"].get("lat")
    lon = lon or status["location"].get("lon")

    if not lat or not lon:
        return jsonify({
            "success": True,
            "reply": "📍 Please share your location first — click the 'Share Location' button!",
            "actions": []
        })

    # FIX: use email from session for memory key to avoid name collisions
    username    = session.get("user_email", session.get("user", "default"))
    mem_history = get_recent_history(6, username)

    result  = chat_with_ai(message, float(lat), float(lon), rooms, mem_history)
    reply   = result.get("reply", "Sorry, I could not understand that. Please try again.")
    actions = result.get("actions", [])

    changed = []
    with _state_lock:
        for action in actions:
            room, device, value = action.get("room", "living"), action.get("device"), action.get("value")
            if room not in rooms:
                continue
            if device == "light":
                old = rooms[room]["light"]
                rooms[room]["light"] = bool(value)
                log_device_event(room, "light", bool(value), old)
                changed.append(f"{room} light")
            elif device == "fan_speed":
                old = rooms[room]["fan_speed"]
                rooms[room]["fan_speed"] = max(0, min(5, int(value)))
                log_device_event(room, "fan_speed", int(value), old)
                changed.append(f"{room} fan")
            elif device == "curtain":
                old = rooms[room]["curtain"]
                rooms[room]["curtain"] = bool(value)
                log_device_event(room, "curtain", bool(value), old)
                changed.append(f"{room} curtain")
            elif device == "dimmer":
                rooms[room]["dimmer"] = max(0, min(100, int(value)))
                changed.append(f"{room} dimmer")
            elif device == "ac":
                if room in ("kitchen", "balcony"):
                    continue
                old = rooms[room]["ac"]
                rooms[room]["ac"] = bool(value)
                log_device_event(room, "ac", bool(value), old)
                changed.append(f"{room} AC")
            elif device == "music" and MUSIC_AVAILABLE:
                music_result = music_play(str(value))
                socketio.emit("music_update", music_status())
                socketio.emit("kitty_play_music", {
                    "query":     str(value),
                    "audio_url": music_result.get("audio_url", ""),
                    "title":     music_result.get("title", str(value)),
                    "success":   music_result.get("success", False)
                })
                changed.append(f"music: {value}")

        if changed:
            persist(); emit_update()
    if changed:
        log_action("🤖", f"[Jarvis] {message[:40]} → {', '.join(changed)}")

    add_message("user",      message, username)
    add_message("assistant", reply,   username)

    # Auto-learn facts
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["sleep", "so jata", "so jaata", "sone"]):
        time_match = re.search(r'(\d{1,2})\s*(baje|pm|am|:00)', msg_lower)
        if time_match:
            learn_fact(f"User mentioned sleep time: {time_match.group(0)}", username)
    if "fan" in msg_lower:
        for n in range(6):
            if str(n) in msg_lower:
                update_preference("preferred_fan_speed", n, username)
                break
    if any(w in msg_lower for w in ["wake", "uthta", "subah"]):
        time_match = re.search(r'(\d{1,2})\s*(baje|am|:00)', msg_lower)
        if time_match:
            learn_fact(f"User wakes up around: {time_match.group(0)}", username)

    socketio.emit("jarvis_reply", {"reply": reply, "actions": actions})
    return jsonify({"success": True, "reply": reply, "actions": actions, "changed": changed})


@app.route("/ai/auto_run", methods=["POST"])
def ai_auto_run():
    if not AI_AVAILABLE:
        return jsonify({"success": False})
    status = get_automation_status()
    lat, lon = status["location"].get("lat"), status["location"].get("lon")
    if not lat or not lon:
        return jsonify({"success": False, "message": "No location set"})
    result = run_automation(float(lat), float(lon), rooms)
    _ai_action_callback(result.get("actions", []), result.get("reason", "Manual"))
    return jsonify({"success": True, **result})


@app.route("/ai/start_auto", methods=["POST"])
def ai_start_auto():
    if not AI_AVAILABLE:
        return jsonify({"success": False})
    data     = request.get_json() or {}
    try:
        interval = int(data.get("interval", 300))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid interval"})
    result = start_automation(lambda: rooms, interval_seconds=interval)
    log_action("🤖", f"AI automation started (every {interval}s)")
    socketio.emit("ai_status", get_automation_status())
    return jsonify(result)


@app.route("/ai/stop_auto", methods=["POST"])
def ai_stop_auto():
    if not AI_AVAILABLE:
        return jsonify({"success": False})
    result = stop_automation()
    log_action("🔴", "AI automation stopped")
    socketio.emit("ai_status", get_automation_status())
    return jsonify(result)


@app.route("/ai/status", methods=["GET"])
def ai_status_route():
    if not AI_AVAILABLE:
        return jsonify({"running": False, "available": False})
    return jsonify({**get_automation_status(), "available": True})


@app.route("/ai/clear_chat", methods=["POST"])
def ai_clear_chat():
    username = session.get("user_email", session.get("user", "default"))
    clear_history(username)
    return jsonify({"success": True})


# ══════════════════════════════════════════════════════════════════
# FEATURE 1 — MEMORY ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/memory/stats", methods=["GET"])
def memory_stats():
    username = session.get("user_email", session.get("user", "default"))
    return jsonify(get_stats(username))

@app.route("/memory/clear_chat", methods=["POST"])
def memory_clear_chat():
    username = session.get("user_email", session.get("user", "default"))
    clear_history(username)
    return jsonify({"success": True, "message": "Chat history cleared"})

@app.route("/memory/learn", methods=["POST"])
def memory_learn():
    data     = request.get_json() or {}
    username = session.get("user_email", session.get("user", "default"))
    fact     = data.get("fact", "").strip()
    if fact:
        learn_fact(fact, username)
    return jsonify({"success": True})


# ══════════════════════════════════════════════════════════════════
# FEATURE 2 — ENERGY ANALYTICS ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/energy/today", methods=["GET"])
def energy_today():
    return jsonify(get_today_summary())

@app.route("/energy/weekly", methods=["GET"])
def energy_weekly():
    return jsonify(get_weekly_summary())

@app.route("/energy/events", methods=["GET"])
def energy_events():
    n = int(request.args.get("n", 20))
    return jsonify(get_recent_events(n))

@app.route("/energy/top", methods=["GET"])
def energy_top():
    return jsonify(get_top_consumers())


# ══════════════════════════════════════════════════════════════════
# FEATURE 3 — PUSH NOTIFICATION ROUTES
# ══════════════════════════════════════════════════════════════════

push_subscriptions = []

@app.route("/push/subscribe", methods=["POST"])
def push_subscribe():
    sub = request.get_json()
    if sub and sub not in push_subscriptions:
        push_subscriptions.append(sub)
        print(f"[Push] New subscription. Total: {len(push_subscriptions)}")
    return jsonify({"success": True})

@app.route("/push/test", methods=["POST"])
def push_test():
    socketio.emit("push_notification", {
        "title": "🏠 Smart Home",
        "body":  "Push notifications are working! ✅",
        "tag":   "test"
    })
    return jsonify({"success": True})


# ══════════════════════════════════════════════════════════════════
# ALL DEVICE CONTROL ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/get_state", methods=["GET"])
def get_state():
    return jsonify(rooms)

@app.route("/static/manifest.json")
def manifest():
    return send_from_directory(app.static_folder, "manifest.json")

@app.route("/static/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    return response

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login_page"))
    return render_template("index.html", username=session["user"])

@app.route("/loginpage")
def login_page():
    return render_template("login.html")

@app.route("/get_log", methods=["GET"])
def get_log():
    return jsonify(activity_log)

@app.route("/clear_log", methods=["POST"])
def clear_log():
    with _log_lock:
        activity_log.clear()
    return jsonify({"success": True})

@app.route("/get_schedules", methods=["GET"])
def get_schedules():
    return jsonify(schedules)

@app.route("/delete_schedule", methods=["POST"])
def delete_schedule():
    data = request.get_json() or {}
    with _state_lock:
        schedules[:] = [s for s in schedules if not (s["room"] == data.get("room") and s["device"] == data.get("device"))]
        save_schedules(schedules)  # FIX: persist after delete
    return jsonify({"success": True})

@app.route("/toggle_ac", methods=["POST"])
def toggle_ac():
    data      = request.get_json() or {}
    room      = data.get("room", "bedroom")
    new_state = data.get("status", False)
    if room in ("kitchen", "balcony"):
        return jsonify({"message": "AC not available in this room"})
    if room in rooms:
        with _state_lock:
            old = rooms[room]["ac"]
            rooms[room]["ac"] = new_state
            persist(); emit_update()
        log_action("❄️", f"[{room.title()}] AC {'ON' if new_state else 'OFF'}",
                   room=room, device="ac", state=new_state, old_state=old)
    return jsonify({"message": f"AC {'ON' if new_state else 'OFF'}"})

@app.route("/toggle_light", methods=["POST"])
def toggle_light():
    data      = request.get_json() or {}
    room      = data.get("room", "living")
    with _state_lock:
        old_state = rooms[room]["light"]
        rooms[room]["light"] = not rooms[room]["light"]
        state     = rooms[room]["light"]
        persist(); emit_update()
    log_action("💡", f"[{room.title()}] Light {'ON' if state else 'OFF'}",
               room=room, device="light", state=state, old_state=old_state)
    return jsonify({"status": "on" if state else "off"})

@app.route("/set_fan_speed", methods=["POST"])
def set_fan_speed():
    data      = request.get_json() or {}
    room      = data.get("room", "living")
    speed     = data.get("speed", 0)
    with _state_lock:
        old_speed = rooms[room]["fan_speed"]
        rooms[room]["fan_speed"] = speed
        persist(); emit_update()
    log_action("🌀", f"[{room.title()}] Fan speed {speed}",
               room=room, device="fan_speed", state=speed, old_state=old_speed)
    return jsonify({"message": f"Fan speed {speed}"})

@app.route("/toggle_curtain", methods=["POST"])
def toggle_curtain():
    data      = request.get_json() or {}
    room      = data.get("room", "living")
    open_     = data.get("open", False)
    with _state_lock:
        old_state = rooms[room]["curtain"]
        rooms[room]["curtain"] = open_
        persist(); emit_update()
    log_action("🪟", f"[{room.title()}] Curtain {'Open' if open_ else 'Closed'}",
               room=room, device="curtain", state=open_, old_state=old_state)
    return jsonify({"message": "Open" if open_ else "Closed"})

@app.route("/set_dimmer", methods=["POST"])
def set_dimmer():
    data = request.get_json() or {}
    room = data.get("room", "living")
    br   = data.get("brightness", 50)
    with _state_lock:
        old  = rooms[room]["dimmer"]
        rooms[room]["dimmer"] = br
        persist(); emit_update()
    log_action("🔆", f"[{room.title()}] Brightness {br}%",
               room=room, device="dimmer", state=br, old_state=old)
    return jsonify({"message": f"Brightness: {br}%"})

@app.route("/inverter", methods=["POST"])
def inverter():
    data      = request.get_json() or {}
    room      = data.get("room", "living")
    new_state = data.get("status", False)
    with _state_lock:
        old       = rooms[room]["inverter"]
        rooms[room]["inverter"] = new_state
        persist(); emit_update()
    log_action("⚡", f"[{room.title()}] Inverter {'ON' if new_state else 'OFF'}",
               room=room, device="inverter", state=new_state, old_state=old)
    return jsonify({"message": "Inverter ON" if new_state else "Inverter OFF"})

@app.route("/detect_gas", methods=["POST"])
def detect_gas():
    leak = (request.get_json() or {}).get("leak", False)
    msg = "Gas Leak Detected! Ventilate immediately!" if leak else "Gas: Safe"
    log_action("⚠️" if leak else "✅", f"[Kitchen] {msg}")
    if leak:
        socketio.emit("sensor_alert", {"type": "gas", "message": "⚠️ " + msg, "critical": True})
        socketio.emit("push_notification", {"title": "⚠️ Gas Alert!", "body": msg, "tag": "gas"})
    return jsonify({"status": "Leak Detected" if leak else "Safe"})

@app.route("/unlock_door", methods=["POST"])
def unlock_door():
    data    = request.get_json() or {}
    door_pw = os.getenv("DOOR_PASSWORD", "1234")
    if data.get("password") == door_pw:
        log_action("🔓", "Door unlocked")
        return jsonify({"status": "success", "message": "Door Unlocked"})
    log_action("🔒", "Door unlock failed")
    return jsonify({"status": "fail", "message": "Incorrect Password"})

@app.route("/check_soil", methods=["POST"])
def check_soil():
    dry = (request.get_json() or {}).get("dry", False)
    log_action("🌿", f"Soil: {'Watering' if dry else 'OK'}")
    return jsonify({"message": "Watering..." if dry else "No need."})

@app.route("/ring_bell", methods=["POST"])
def ring_bell():
    log_action("🔔", "Doorbell pressed")
    socketio.emit("sensor_alert", {"type": "bell", "message": "🔔 Someone is at the door!", "critical": True})
    socketio.emit("push_notification", {"title": "🔔 Doorbell", "body": "Someone is at the door!", "tag": "bell"})
    return jsonify({"message": "🔔 Someone at door!"})

@app.route("/approach_door", methods=["POST"])
def approach_door():
    log_action("🚪", "Auto door opened")
    socketio.emit("sensor_alert", {"type": "door", "message": "🚪 Someone approaching — door auto-opened!", "critical": True})
    socketio.emit("push_notification", {"title": "🚪 Auto Door", "body": "Someone approaching — door opened!", "tag": "door"})
    return jsonify({"message": "🚪 Door opened!"})

@app.route("/detect_intruder", methods=["POST"])
def detect_intruder():
    intruder = (request.get_json() or {}).get("intruder", False)
    msg = "INTRUDER DETECTED! Check security cameras!" if intruder else "Motion: Safe"
    log_action("🚨" if intruder else "✅", msg)
    if intruder:
        socketio.emit("sensor_alert", {"type": "intruder", "message": "🚨 " + msg, "critical": True})
        socketio.emit("push_notification", {"title": "🚨 Security Alert!", "body": msg, "tag": "intruder"})
    return jsonify({"message": "⚠️ Intruder!" if intruder else "All safe"})

@app.route("/detect_smoke", methods=["POST"])
def detect_smoke():
    det = (request.get_json() or {}).get("smoke", False)
    msg = "SMOKE DETECTED! Check kitchen immediately!" if det else "Smoke: None"
    log_action("🔥" if det else "✅", f"[Kitchen] {msg}")
    if det:
        socketio.emit("sensor_alert", {"type": "smoke", "message": "🔥 " + msg, "critical": True})
        socketio.emit("push_notification", {"title": "🔥 Smoke Alert!", "body": msg, "tag": "smoke"})
    return jsonify({"message": "🔥 Smoke!" if det else "No smoke"})

@app.route("/set_schedule", methods=["POST"])
def set_schedule():
    data     = request.get_json() or {}
    room     = data.get("room", "living")
    on_time  = data.get("on", "")
    off_time = data.get("off", "")
    device   = data.get("device", "light")
    if not on_time and not off_time:
        return jsonify({"message": "No times provided"})
    with _state_lock:
        schedules[:] = [s for s in schedules if not (s["room"] == room and s["device"] == device)]
        schedules.append({"room": room, "device": device, "on_time": on_time, "off_time": off_time})
        save_schedules(schedules)  # FIX: persist after add
    log_action("⏰", f"[{room.title()}] {device} schedule saved")
    return jsonify({"message": f"{device}: ON {on_time}, OFF {off_time}"})

@app.route("/water_level", methods=["POST"])
def water_level():
    level = (request.get_json() or {}).get("level", 0)
    log_action("💧", f"Water: {level}%")
    return jsonify({"message": f"Water Level: {level}%"})

@app.route("/fire_alert", methods=["POST"])
def fire_alert():
    log_action("🔥", "[Kitchen] FIRE ALERT!")
    return jsonify({"message": "🔥 Fire! Buzzer ON!"})

@app.route("/feed_pet", methods=["POST"])
def feed_pet():
    from datetime import datetime
    t = datetime.now().strftime("%I:%M:%S %p")
    log_action("🐶", f"Pet fed at {t}")
    return jsonify({"message": f"🐶 Pet fed at {t}"})

@app.route("/check_inverter_status", methods=["POST"])
def check_inverter_status():
    data    = request.get_json() or {}
    room    = data.get("room", "living")
    battery = data.get("battery", 0)
    msg = ("✅ All appliances on inverter." if battery > 50
           else "⚠️ Only essential appliances." if battery > 10
           else "🔴 Low battery! Minimal devices only.")
    log_action("🔋", f"[{room.title()}] Battery {battery}%")
    return jsonify({"message": msg})

@app.route("/set_pet_feeder_automation", methods=["POST"])
def set_pet_feeder_automation():
    data = request.get_json() or {}
    log_action("🐾", f"Pet feeder scheduled at {data.get('time')}")
    return jsonify({"message": f"Scheduled at {data.get('time')}"})

# ── Face Engine ────────────────────────────────────────
try:
    from face_engine import (capture_faces, train_model, recognize_face,
                             load_profiles, save_profile, list_registered_users,
                             delete_user, DEFAULT_PREFS)
    FACE_ENGINE_AVAILABLE = True
except ImportError:
    FACE_ENGINE_AVAILABLE = False

face_task_status = {"status": "idle", "message": ""}

@app.route("/face/users", methods=["GET"])
def face_users():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"error": "Face engine not available"})
    account = session.get("user", "default")
    users   = list_registered_users(account)
    raw     = load_profiles(account)
    merged  = {}
    for u in users:
        base = DEFAULT_PREFS.copy(); base.update(raw.get(u, {})); merged[u] = base
    return jsonify({"users": users, "profiles": merged})

@app.route("/face/register", methods=["POST"])
def face_register():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"success": False, "message": "Face engine not available"})
    if gesture_running:
        return jsonify({"success": False, "message": "⚠️ Gesture control is running — stop it first, then register."})
    data    = request.get_json() or {}
    name    = data.get("name", "").strip()
    account = session.get("user", "default")
    if not name: return jsonify({"success": False, "message": "Name required"})
    face_task_status["status"] = "registering"
    face_task_status["message"] = f"Registering {name}... (camera is open, look at it!)"
    socketio.emit("face_task", face_task_status)
    def do():
        if not _camera_lock.acquire(blocking=True, timeout=5):
            face_task_status.update({"status": "error", "message": "Camera busy — try again."})
            socketio.emit("face_task", face_task_status)
            return
        try:
            ok, msg = capture_faces(name, num_samples=30, account=account)
        finally:
            _camera_lock.release()
        if ok:
            ok2, msg2 = train_model(account=account)
            face_task_status.update({"status": "done", "message": f"✅ {msg} | {msg2}"})
            log_action("👤", f"Face registered: {name}")
            socketio.emit("face_task", face_task_status)
            socketio.emit("face_registered", {"name": name, "success": True})
        else:
            face_task_status.update({"status": "error", "message": f"❌ {msg}"})
            socketio.emit("face_task", face_task_status)
            socketio.emit("face_registered", {"name": name, "success": False, "message": msg})
    threading.Thread(target=do, daemon=True).start()
    return jsonify({"success": True, "message": f"Registration started for {name} — camera is opening!"})

@app.route("/face/recognize", methods=["POST"])
def face_recognize():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"success": False, "message": "Face engine not available"})
    if gesture_running:
        return jsonify({"success": False, "message": "⚠️ Gesture control is running — stop it first, then scan."})
    account = session.get("user", "default")
    face_task_status.update({"status": "recognizing", "message": "Scanning..."})
    def do():
        if not _camera_lock.acquire(blocking=True, timeout=5):
            face_task_status.update({"status": "error", "message": "Camera busy — try again in a moment."})
            socketio.emit("face_task", face_task_status)
            return
        try:
            result = recognize_face(confidence_threshold=0.40, account=account)
        finally:
            _camera_lock.release()
        face_task_status.update({"status": "done", "message": result.get("message", "")})
        socketio.emit("face_task", face_task_status)
        if result["success"]:
            name, profile, conf = result["name"], result["profile"], result.get("confidence", 0)
            with _state_lock:
                rooms["living"].update({
                    "light":     profile.get("light", True),
                    "fan_speed": profile.get("fan_speed", 2),
                    "dimmer":    profile.get("dimmer", 70),
                    "curtain":   profile.get("curtain", False),
                    "ac":        profile.get("ac", False)
                })
                persist(); emit_update()
            if profile.get("music") and result.get("play_music") and MUSIC_AVAILABLE:
                music_play(profile["music"])
                socketio.emit("music_update", music_status())
            log_action("✅", f"[Face] {name} ({conf}%) — room adjusted")
            socketio.emit("face_recognized", {
                "name": name, "confidence": conf, "profile": profile,
                "play_music": result.get("play_music", False),
                "message": result.get("message", "")
            })
        else:
            log_action("❌", "[Face] Not recognized")
            socketio.emit("face_recognized", {
                "name": "Unknown", "confidence": 0,
                "message": result.get("message", "Not recognized")
            })
    threading.Thread(target=do, daemon=True).start()
    return jsonify({"success": True, "message": "Recognition started"})

@app.route("/face/train", methods=["POST"])
def face_train():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"success": False})
    account  = session.get("user", "default")
    ok, msg  = train_model(account=account)
    if ok: log_action("🧠", f"Model trained: {msg}")
    return jsonify({"success": ok, "message": msg})

@app.route("/face/profile", methods=["GET", "POST"])
def face_profile():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"error": "Face engine not available"})
    account = session.get("user", "default")
    if request.method == "GET":
        return jsonify(load_profiles(account).get(request.args.get("name", ""), DEFAULT_PREFS.copy()))
    data = request.get_json() or {}
    name, prefs = data.get("name", ""), data.get("prefs", {})
    if not name: return jsonify({"success": False})
    save_profile(name, prefs, account)
    log_action("✏️", f"Profile updated: {name}")
    return jsonify({"success": True})

@app.route("/face/delete", methods=["POST"])
def face_delete():
    if not FACE_ENGINE_AVAILABLE: return jsonify({"success": False})
    data    = request.get_json() or {}
    name    = data.get("name", "")
    account = session.get("user", "default")
    if not name: return jsonify({"success": False})
    delete_user(name, account)
    log_action("🗑️", f"Face deleted: {name}")
    return jsonify({"success": True})

@app.route("/face/status", methods=["GET"])
def face_status_route():
    return jsonify(face_task_status)

# ── Camera lock ────────────────────────────────────────
_camera_lock = threading.Lock()

# ── Gesture ────────────────────────────────────────────
gesture_thread      = None
gesture_running     = False
gesture_status      = "stopped"
gesture_last_action = ""

def gesture_loop():
    global gesture_running, gesture_status, gesture_last_action
    cap = None
    det = None

    if not _camera_lock.acquire(blocking=False):
        gesture_status = "error"
        gesture_last_action = "Camera busy — face scan is running. Stop it first."
        gesture_running = False
        print("[Gesture] Camera busy, cannot start.")
        return

    try:
        import cv2, mediapipe as mp
        mp_hands = mp.solutions.hands
        det = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            gesture_status = "error"; gesture_last_action = "Camera not found. Check webcam connection."
            gesture_running = False; return
        gesture_status = "running"
        prev_state = "neutral"; last_time = 0; COOLDOWN = 1.0

        def hand_state(lm):
            closed = sum(1 for tip, pip in zip([8, 12, 16, 20], [6, 10, 14, 18]) if lm[tip].y > lm[pip].y)
            ty, iy, py = lm[4].y, lm[5].y, lm[17].y
            if closed >= 4:
                if ty < iy - 0.05: return "thumbs_up"
                if ty > py + 0.05: return "thumbs_down"
                return "fist"
            if closed == 0: return "open"
            return "neutral"

        while gesture_running:
            ret, frame = cap.read()
            if not ret: break
            frame = cv2.flip(frame, 1)
            res   = det.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            cur   = "neutral"
            if res.multi_hand_landmarks:
                for hl in res.multi_hand_landmarks:
                    cur = hand_state(hl.landmark)
            if time.time() - last_time > COOLDOWN and prev_state == "neutral" and cur != "neutral":
                with _state_lock:
                    old_light = rooms["living"]["light"]
                    old_fan   = rooms["living"]["fan_speed"]
                    if cur == "open":
                        rooms["living"]["light"] = not rooms["living"]["light"]
                        gesture_last_action = f"💡 Light {'ON' if rooms['living']['light'] else 'OFF'}"
                        log_device_event("living", "light", rooms["living"]["light"], old_light)
                    elif cur == "fist":
                        rooms["living"]["fan_speed"] = 0 if rooms["living"]["fan_speed"] > 0 else 3
                        gesture_last_action = f"🌀 Fan {'ON (3)' if rooms['living']['fan_speed'] else 'OFF'}"
                        log_device_event("living", "fan_speed", rooms["living"]["fan_speed"], old_fan)
                    elif cur == "thumbs_up":
                        new = min(5, rooms["living"]["fan_speed"] + 1)
                        rooms["living"]["fan_speed"] = new
                        gesture_last_action = f"⬆️ Fan → {new}"
                        log_device_event("living", "fan_speed", new, old_fan)
                    elif cur == "thumbs_down":
                        new = max(0, rooms["living"]["fan_speed"] - 1)
                        rooms["living"]["fan_speed"] = new
                        gesture_last_action = f"⬇️ Fan → {new}"
                        log_device_event("living", "fan_speed", new, old_fan)
                    persist(); emit_update()
                log_action("✋", f"[Gesture] {gesture_last_action}")
                socketio.emit("gesture_action", {"action": gesture_last_action})
                last_time = time.time()
            prev_state = "neutral" if not res.multi_hand_landmarks else cur
            time.sleep(0.03)
    except Exception as e:
        gesture_status = "error"; gesture_last_action = str(e)
        print(f"[Gesture] Error: {e}")
    finally:
        if cap is not None:
            cap.release()
        if det is not None:
            det.close()
        gesture_running = False
        gesture_status = "stopped"
        _camera_lock.release()

@app.route("/start_gesture", methods=["POST"])
def start_gesture():
    global gesture_thread, gesture_running, gesture_status
    if gesture_running: return jsonify({"success": False, "message": "Already running"})
    if face_task_status.get("status") in ("registering", "recognizing"):
        return jsonify({"success": False, "message": "⚠️ Face scan in progress — wait for it to finish first."})
    gesture_running = True; gesture_status = "starting"
    gesture_thread  = threading.Thread(target=gesture_loop, daemon=True)
    gesture_thread.start()
    return jsonify({"success": True, "message": "Gesture control starting..."})

@app.route("/stop_gesture", methods=["POST"])
def stop_gesture():
    global gesture_running, gesture_status
    gesture_running = False; gesture_status = "stopped"
    return jsonify({"success": True, "message": "Stopped"})

@app.route("/gesture_status", methods=["GET"])
def get_gesture_status():
    return jsonify({"status": gesture_status, "last_action": gesture_last_action})

# ── Music ──────────────────────────────────────────────
@app.route("/music/play", methods=["POST"])
def music_play_route():
    if not MUSIC_AVAILABLE: return jsonify({"success": False})
    data  = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query: return jsonify({"success": False, "message": "Query required"})
    result = music_play(query)
    log_action("🎵", f"Playing: {query}")
    socketio.emit("music_update", music_status())
    return jsonify(result)

@app.route("/music/search", methods=["POST"])
def music_search_route():
    if not MUSIC_AVAILABLE: return jsonify({"success": False})
    data  = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query: return jsonify({"success": False, "message": "Query required"})
    result = music_play(query)
    log_action("🎵", f"Search+Play: {query}")
    socketio.emit("music_update", music_status())
    return jsonify(result)

@app.route("/music/stop", methods=["POST"])
def music_stop_route():
    if not MUSIC_AVAILABLE: return jsonify({"success": False})
    result = music_stop()
    log_action("⏹️", "Music stopped")
    socketio.emit("music_update", music_status())
    return jsonify(result)

@app.route("/music/volume", methods=["POST"])
def music_volume_route():
    if not MUSIC_AVAILABLE: return jsonify({"success": False})
    vol = (request.get_json() or {}).get("volume", 0.7)
    return jsonify(set_volume(vol))

@app.route("/music/status", methods=["GET"])
def music_status_route():
    if not MUSIC_AVAILABLE: return jsonify({"status": "unavailable", "title": ""})
    return jsonify(music_status())

# ── Voice ──────────────────────────────────────────────
def _voice_handler(cmd):
    try:
        action = cmd.get("action")
        device = cmd.get("device")
        value  = cmd.get("value")
        room   = cmd.get("room", "living")
        raw    = cmd.get("raw", "")

        # Detect "all rooms" intent from the raw transcription
        all_rooms_keywords = [
            "all", "every", "sab", "saare", "सारे", "poora", "pura",
            "ghar", "house", "home", "everywhere",
        ]
        is_all_rooms = any(k in raw.lower() for k in all_rooms_keywords)

        # Which rooms to apply to
        target_rooms = list(rooms.keys()) if is_all_rooms else [room]

        # Ensure single room is valid
        if not is_all_rooms and room not in rooms:
            room = "living"
            target_rooms = ["living"]

        with _state_lock:
            if device == "light":
                new_state = (action == "on")
                for r in target_rooms:
                    old = rooms[r]["light"]
                    rooms[r]["light"] = new_state
                    log_action("🎤💡", f"[Voice] {r} Light {'ON' if new_state else 'OFF'}",
                               room=r, device="light", state=new_state, old_state=old)
                persist(); emit_update()

            elif device == "fan":
                new_speed = max(0, min(5, int(value or 3))) if action in ("on", "speed") else 0
                for r in target_rooms:
                    old = rooms[r]["fan_speed"]
                    rooms[r]["fan_speed"] = new_speed
                    log_action("🎤🌀", f"[Voice] {r} Fan → {new_speed}",
                               room=r, device="fan_speed", state=new_speed, old_state=old)
                persist(); emit_update()

            elif device == "ac":
                new_state = (action == "on")
                for r in target_rooms:
                    if r in ("kitchen", "balcony"):
                        continue
                    old = rooms[r]["ac"]
                    rooms[r]["ac"] = new_state
                    log_action("🎤❄️", f"[Voice] {r} AC {'ON' if new_state else 'OFF'}",
                               room=r, device="ac", state=new_state, old_state=old)
                persist(); emit_update()

            elif device == "curtain":
                new_state = (action == "open")
                for r in target_rooms:
                    old = rooms[r]["curtain"]
                    rooms[r]["curtain"] = new_state
                    log_action("🎤🪟", f"[Voice] {r} Curtain {'Open' if new_state else 'Closed'}",
                               room=r, device="curtain", state=new_state, old_state=old)
                persist(); emit_update()

            elif device == "dimmer":
                br = max(0, min(100, int(value or 50)))
                for r in target_rooms:
                    old = rooms[r]["dimmer"]
                    rooms[r]["dimmer"] = br
                    log_action("🎤🔆", f"[Voice] {r} Brightness → {br}%",
                               room=r, device="dimmer", state=br, old_state=old)
                persist(); emit_update()

            elif device == "inverter":
                new_state = (action == "on")
                for r in target_rooms:
                    old = rooms[r]["inverter"]
                    rooms[r]["inverter"] = new_state
                    log_action("🎤⚡", f"[Voice] {r} Inverter {'ON' if new_state else 'OFF'}",
                               room=r, device="inverter", state=new_state, old_state=old)
                persist(); emit_update()

            elif device == "music":
                if MUSIC_AVAILABLE:
                    if action == "play" and value:
                        result = music_play(value)
                        log_action("🎤🎵", f"[Voice] Playing: {value}")
                        socketio.emit("music_update", music_status())
                        socketio.emit("kitty_play_music", {
                            "query":     str(value),
                            "audio_url": result.get("audio_url", ""),
                            "title":     result.get("title", str(value)),
                            "success":   result.get("success", False),
                        })
                    elif action == "stop":
                        music_stop()
                        log_action("🎤⏹️", "[Voice] Music stopped")
                        socketio.emit("music_update", music_status())
                    elif action == "pause":
                        pause_resume()
                        log_action("🎤⏸️", "[Voice] Music paused")
                        socketio.emit("music_update", music_status())
                    elif action == "resume":
                        pause_resume()
                        log_action("🎤▶️", "[Voice] Music resumed")
                        socketio.emit("music_update", music_status())
                    elif action == "volume_up":
                        set_volume(0.9)
                        log_action("🎤🔊", "[Voice] Volume up")
                    elif action == "volume_down":
                        set_volume(0.4)
                        log_action("🎤🔉", "[Voice] Volume down")

        socketio.emit("voice_command", {
            "text": raw, "action": action,
            "device": device, "room": "all" if is_all_rooms else room,
        })
    except Exception as e:
        print(f"[Voice] Handler error: {e}")

# ── Auto-start always-on voice with wake word ──────────
if VOICE_AVAILABLE:
    def _voice_status_socket_emit(status_dict):
        """voice_engine mode change hone par yeh call hota hai — socket broadcast karta hai."""
        socketio.emit("voice_status", status_dict)
    set_status_callback(_voice_status_socket_emit)

    def _auto_voice_start():
        time.sleep(3)  # Let app fully initialise first
        start_listening(callback=_voice_handler)
        print("[Voice] 🐱 Always-on wake word mode started automatically")
    threading.Thread(target=_auto_voice_start, daemon=True).start()


@app.route("/voice/start", methods=["POST"])
def voice_start():
    if not VOICE_AVAILABLE: return jsonify({"success": False, "message": "vosk not installed"})
    result = start_listening(callback=_voice_handler)
    if result.get("success"):
        log_action("🎤", "Voice wake-word mode started")
        socketio.emit("voice_status", {"listening": True, "mode": "waiting_wake"})
    else:
        socketio.emit("voice_status", {"listening": True, "mode": "waiting_wake"})
    return jsonify(result)

@app.route("/voice/stop", methods=["POST"])
def voice_stop():
    if not VOICE_AVAILABLE: return jsonify({"success": False})
    result = stop_listening()
    log_action("🔇", "Voice stopped")
    socketio.emit("voice_status", {"listening": False})
    return jsonify(result)

@app.route("/voice/status", methods=["GET"])
def voice_status_route():
    if not VOICE_AVAILABLE:
        return jsonify({"listening": False, "available": False, "mode": "idle"})
    s = voice_get_status()
    s["available"] = True
    # Emit socket update so UI reflects recording/transcribing states live
    socketio.emit("voice_status", s)
    return jsonify(s)

# ── Auth ───────────────────────────────────────────────
@app.route("/signup", methods=["POST"])
def signup():
    data  = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data received."})
    email, password, name = data.get("email", "").strip().lower(), data.get("password", ""), data.get("name", "").strip()
    if not email or not password or not name:
        return jsonify({"success": False, "message": "All fields are required."})
    with _users_lock:
        users = load_users()
        if email in users:
            return jsonify({"success": False, "message": "Email already registered."})
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        users[email] = {"password": hashed, "name": name}
        save_users(users)
    return jsonify({"success": True, "message": "Signup successful!"})

@app.route("/login", methods=["POST"])
def login():
    data  = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "No data received."})
    email    = data.get("email", "").strip().lower()
    password = data.get("password", "")
    with _users_lock:
        users = load_users()
        if email in users and bcrypt.checkpw(password.encode("utf-8"), users[email]["password"].encode("utf-8")):
            session.permanent = True  # FIX: honour permanent_session_lifetime
            session["user"]       = users[email]["name"]
            session["user_email"] = email  # FIX: store email as memory key
            return jsonify({"success": True, "message": f"Welcome {users[email]['name']}!"})
    return jsonify({"success": False, "message": "Invalid credentials."})

# ── Groq Whisper Voice Route ───────────────────────────
# FIX: added 10 MB file size limit
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB

@app.route("/voice/whisper", methods=["POST"])
def voice_whisper():
    import requests as req
    import tempfile

    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    if not GROQ_API_KEY:
        return jsonify({"success": False, "text": "", "error": "GROQ_API_KEY not set in .env"})

    audio_file = request.files.get("audio")
    if not audio_file:
        return jsonify({"success": False, "text": "", "error": "No audio received"})

    # FIX: check file size before processing
    audio_file.seek(0, 2)  # seek to end
    file_size = audio_file.tell()
    audio_file.seek(0)     # reset
    if file_size > MAX_AUDIO_BYTES:
        return jsonify({"success": False, "text": "", "error": "Audio file too large (max 10 MB)"})

    try:
        suffix = ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            response = req.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (f"audio{suffix}", f, "audio/webm")},
                data={"model": "whisper-large-v3-turbo", "response_format": "json"},
                timeout=30
            )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        if response.status_code == 200:
            result = response.json()
            text   = result.get("text", "").strip()
            print(f"[Whisper] Transcribed: '{text}'")
            return jsonify({"success": True, "text": text})
        else:
            err = response.text[:200]
            print(f"[Whisper] Error {response.status_code}: {err}")
            return jsonify({"success": False, "text": "", "error": f"Groq error: {response.status_code}"})

    except Exception as e:
        print(f"[Whisper] Exception: {e}")
        return jsonify({"success": False, "text": "", "error": str(e)})

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/loginpage")


# ══════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    try:
        from pyngrok import ngrok
        public_url = ngrok.connect(5000)
        print(f"\n{'='*50}\n  🌐 URL: {public_url}\n{'='*50}\n")
    except Exception as e:
        print(f"  ⚠️ Ngrok: {e}")

    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)