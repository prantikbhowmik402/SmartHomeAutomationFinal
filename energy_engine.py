"""
energy_engine.py — Smart Home Energy Analytics
Logs every device ON/OFF event with timestamps.
Estimates kWh consumption based on device wattage.

FIXES:
  - Added MAX_SESSION_HOURS cap (8h) to prevent huge fake kWh after server restart
  - Added kitchen/balcony AC guard — no AC in those rooms
  - Events capped at 500 to prevent file bloat
"""

import json
import os
import threading
from datetime import datetime, timedelta
from collections import defaultdict

ENERGY_FILE = os.path.join(os.path.dirname(__file__), "energy_log.json")
_file_lock  = threading.Lock()

# ── DEVICE WATTAGE TABLE (realistic estimates) ─────────
DEVICE_WATTS = {
    "light":     15,    # LED bulb
    "fan":       75,    # Ceiling fan at speed 3 avg
    "ac":       1500,   # 1.5 ton AC
    "inverter":  200,   # Inverter load
    "dimmer":    15,    # Same as light (dimmer-adjusted below)
}

FAN_SPEED_WATTS = {
    0: 0, 1: 20, 2: 40, 3: 60, 4: 75, 5: 90
}

# FIX: cap session duration at 8 hours so a server restart
# doesn't create impossibly large kWh values
MAX_SESSION_HOURS = 8

# Rooms that do NOT have AC (guard against bad AI/data)
NO_AC_ROOMS = {"kitchen", "balcony"}

# ── LOAD / SAVE ───────────────────────────────────────

def _load_log() -> dict:
    if not os.path.exists(ENERGY_FILE):
        return {"events": [], "daily_summary": {}}
    try:
        with _file_lock:
            with open(ENERGY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        return {"events": [], "daily_summary": {}}

def _save_log(data: dict):
    try:
        with _file_lock:
            # Keep only last 500 events to prevent file bloat
            if len(data.get("events", [])) > 500:
                data["events"] = data["events"][-500:]
            with open(ENERGY_FILE, "w") as f:
                json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Energy] Save error: {e}")

# ── LOG DEVICE EVENT ──────────────────────────────────

def log_device_event(room: str, device: str, state, old_state=None):
    """
    Call this whenever a device changes state.
    state: True/False for light/curtain/ac/inverter
           0-5 for fan_speed
           0-100 for dimmer
    """
    # FIX: Skip AC events for rooms that don't have AC
    if device == "ac" and room in NO_AC_ROOMS:
        return 0.0

    data     = _load_log()
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")

    # Calculate watts
    watts = 0
    if device == "light":
        watts = DEVICE_WATTS["light"] if state else 0
    elif device == "fan_speed":
        watts = FAN_SPEED_WATTS.get(int(state), 0)
    elif device == "ac":
        watts = DEVICE_WATTS["ac"] if state else 0
    elif device == "inverter":
        watts = DEVICE_WATTS["inverter"] if state else 0
    elif device == "dimmer":
        watts = int(DEVICE_WATTS["dimmer"] * int(state) / 100)

    # If there's a previous event for this device, calculate kWh consumed
    kwh_consumed = 0.0
    if old_state is not None and data["events"]:
        for ev in reversed(data["events"]):
            if ev["room"] == room and ev["device"] == device:
                try:
                    prev_time  = datetime.fromisoformat(ev["timestamp"])
                    raw_hours  = (now - prev_time).total_seconds() / 3600
                    # FIX: cap at MAX_SESSION_HOURS to prevent huge values after restart
                    hours      = min(raw_hours, MAX_SESSION_HOURS)
                    prev_watts = ev.get("watts", 0)
                    kwh_consumed = round((prev_watts * hours) / 1000, 4)
                except Exception:
                    pass
                break

    event = {
        "timestamp":           now.isoformat(),
        "date":                today,
        "time":                now.strftime("%H:%M:%S"),
        "room":                room,
        "device":              device,
        "state":               state,
        "watts":               watts,
        "kwh_this_session":    kwh_consumed,
    }
    data["events"].append(event)

    # Update daily summary
    if today not in data["daily_summary"]:
        data["daily_summary"][today] = {"total_kwh": 0.0, "events": 0, "cost_inr": 0.0}
    data["daily_summary"][today]["total_kwh"] = round(
        data["daily_summary"][today]["total_kwh"] + kwh_consumed, 4
    )
    data["daily_summary"][today]["events"] += 1
    # ₹8 per kWh (average Indian electricity rate)
    data["daily_summary"][today]["cost_inr"] = round(
        data["daily_summary"][today]["total_kwh"] * 8, 2
    )

    _save_log(data)
    return kwh_consumed

# ── ANALYTICS ─────────────────────────────────────────

def get_today_summary() -> dict:
    """Summary of today's energy usage."""
    data  = _load_log()
    today = datetime.now().strftime("%Y-%m-%d")
    summary = data["daily_summary"].get(today, {"total_kwh": 0.0, "events": 0, "cost_inr": 0.0})

    # Per-room breakdown for today
    room_kwh   = defaultdict(float)
    device_kwh = defaultdict(float)
    for ev in data["events"]:
        if ev["date"] == today:
            room_kwh[ev["room"]]     = round(room_kwh[ev["room"]]     + ev.get("kwh_this_session", 0), 4)
            device_kwh[ev["device"]] = round(device_kwh[ev["device"]] + ev.get("kwh_this_session", 0), 4)

    # Current live wattage (last state of each device)
    live_watts = 0
    seen       = set()
    for ev in reversed(data["events"]):
        key = (ev["room"], ev["device"])
        if key not in seen:
            seen.add(key)
            live_watts += ev.get("watts", 0)

    return {
        "date":         today,
        "total_kwh":    summary["total_kwh"],
        "cost_inr":     summary["cost_inr"],
        "total_events": summary["events"],
        "live_watts":   live_watts,
        "room_kwh":     dict(room_kwh),
        "device_kwh":   dict(device_kwh),
    }

def get_weekly_summary() -> list:
    """Last 7 days daily summary for chart."""
    data   = _load_log()
    result = []
    for i in range(6, -1, -1):
        day     = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        label   = (datetime.now() - timedelta(days=i)).strftime("%a")
        summary = data["daily_summary"].get(day, {"total_kwh": 0.0, "cost_inr": 0.0})
        result.append({
            "date":      day,
            "label":     label,
            "total_kwh": summary["total_kwh"],
            "cost_inr":  summary["cost_inr"],
        })
    return result

def get_recent_events(n: int = 20) -> list:
    """Last n device events."""
    data = _load_log()
    return list(reversed(data["events"][-n:]))

def get_top_consumers() -> list:
    """Which devices consume the most in last 7 days."""
    data      = _load_log()
    week_ago  = (datetime.now() - timedelta(days=7)).isoformat()
    device_kwh = defaultdict(float)
    for ev in data["events"]:
        if ev["timestamp"] >= week_ago:
            key = f"{ev['room']} {ev['device']}"
            device_kwh[key] = round(device_kwh[key] + ev.get("kwh_this_session", 0), 4)
    sorted_consumers = sorted(device_kwh.items(), key=lambda x: x[1], reverse=True)
    return [{"device": k, "kwh": v, "cost_inr": round(v * 8, 2)} for k, v in sorted_consumers[:8]]
