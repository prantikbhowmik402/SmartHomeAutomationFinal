"""
memory_engine.py — Persistent AI Memory for Kitty

FIXES:
  - _safe_key() sanitizes the username so email addresses (with @ and .)
    work safely as JSON dictionary keys without collisions
  - MAX_HISTORY and MAX_FACTS enforced cleanly
"""

import json
import os
import re
import threading
from datetime import datetime

MEMORY_FILE  = os.path.join(os.path.dirname(__file__), "kitty_memory.json")
MAX_HISTORY  = 40   # Max messages stored per user
MAX_FACTS    = 20   # Max learned facts about user
_file_lock   = threading.Lock()


# ── KEY SANITIZER — FIX: use email as key safely ──────
def _safe_key(username: str) -> str:
    """
    Convert any username/email to a safe, stable dict key.
    e.g.  "prntkbk402@gmail.com" → "prntkbk402_gmail_com"
          "ROHIT"                 → "rohit"
    Lowercased + non-alphanumeric → underscore.
    """
    return re.sub(r'[^a-z0-9]', '_', username.strip().lower())


# ── DEFAULT MEMORY STRUCTURE ──────────────────────────

def _default_memory():
    return {
        "history":        [],
        "learned_facts":  [],
        "preferences": {
            "preferred_fan_speed": None,
            "sleep_time":          None,
            "wake_time":           None,
            "preferred_temp":      None,
            "music_taste":         None,
        },
        "last_updated":   None,
        "total_messages": 0,
    }

# ── LOAD / SAVE ───────────────────────────────────────

def load_memory(username: str = "default") -> dict:
    key = _safe_key(username)
    if not os.path.exists(MEMORY_FILE):
        return _default_memory()
    try:
        with _file_lock:
            with open(MEMORY_FILE, "r") as f:
                all_memories = json.load(f)
        return all_memories.get(key, _default_memory())
    except Exception as e:
        print(f"[Memory] Load error: {e}")
        return _default_memory()

def save_memory(memory: dict, username: str = "default"):
    key = _safe_key(username)
    try:
        with _file_lock:
            all_memories = {}
            if os.path.exists(MEMORY_FILE):
                with open(MEMORY_FILE, "r") as f:
                    all_memories = json.load(f)
            all_memories[key] = memory
            with open(MEMORY_FILE, "w") as f:
                json.dump(all_memories, f, indent=2)
    except Exception as e:
        print(f"[Memory] Save error: {e}")

# ── ADD MESSAGE ───────────────────────────────────────

def add_message(role: str, text: str, username: str = "default"):
    memory = load_memory(username)
    entry  = {
        "role": role,
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    memory["history"].append(entry)
    memory["total_messages"] += 1
    memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    if len(memory["history"]) > MAX_HISTORY:
        memory["history"] = memory["history"][-MAX_HISTORY:]

    save_memory(memory, username)

# ── LEARN FACTS ───────────────────────────────────────

def learn_fact(fact: str, username: str = "default"):
    memory = load_memory(username)
    if fact not in memory["learned_facts"]:
        memory["learned_facts"].append(fact)
        if len(memory["learned_facts"]) > MAX_FACTS:
            memory["learned_facts"] = memory["learned_facts"][-MAX_FACTS:]
        save_memory(memory, username)
        print(f"[Memory] Learned: {fact}")

def update_preference(key: str, value, username: str = "default"):
    memory = load_memory(username)
    memory["preferences"][key] = value
    memory["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_memory(memory, username)
    print(f"[Memory] Preference updated: {key} = {value}")

# ── GET HISTORY FOR AI ────────────────────────────────

def get_recent_history(n: int = 6, username: str = "default") -> list:
    memory = load_memory(username)
    return memory["history"][-n:] if memory["history"] else []

def get_memory_context(username: str = "default") -> str:
    memory = load_memory(username)
    parts  = []
    if memory["learned_facts"]:
        facts = "; ".join(memory["learned_facts"][-8:])
        parts.append(f"Known facts about user: {facts}")
    prefs = {k: v for k, v in memory["preferences"].items() if v is not None}
    if prefs:
        parts.append(f"User preferences: {json.dumps(prefs)}")
    if memory["total_messages"] > 0:
        parts.append(f"Total conversations so far: {memory['total_messages']}")
    return "\n".join(parts) if parts else "No memory yet — first conversation."

# ── CLEAR MEMORY ─────────────────────────────────────

def clear_history(username: str = "default"):
    memory = load_memory(username)
    memory["history"] = []
    save_memory(memory, username)

def clear_all(username: str = "default"):
    save_memory(_default_memory(), username)

# ── STATS ─────────────────────────────────────────────

def get_stats(username: str = "default") -> dict:
    memory = load_memory(username)
    return {
        "total_messages":  memory["total_messages"],
        "learned_facts":   len(memory["learned_facts"]),
        "history_count":   len(memory["history"]),
        "last_updated":    memory["last_updated"],
        "preferences":     memory["preferences"],
        "facts":           memory["learned_facts"],
    }
