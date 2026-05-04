"""
╔══════════════════════════════════════════════════════════╗
║       🔍 SmartHome IoT — Project Diagnostic Tool        ║
║    Checks all dependencies, files, env vars & engines   ║
╚══════════════════════════════════════════════════════════╝
Run:  python diagnose.py
"""

import sys
import os
import importlib
import socket

# ── Colors for terminal output ─────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

ok   = f"{GREEN}[✅ OK]{RESET}"
fail = f"{RED}[❌ MISSING]{RESET}"
warn = f"{YELLOW}[⚠️  WARN]{RESET}"

results = {"ok": 0, "fail": 0, "warn": 0}

def check(label, condition, fix="", level="ok"):
    if condition:
        print(f"  {ok}  {label}")
        results["ok"] += 1
    else:
        sym = fail if level == "fail" else warn
        key = "fail" if level == "fail" else "warn"
        print(f"  {sym}  {label}")
        if fix:
            print(f"         {CYAN}👉 Fix: {fix}{RESET}")
        results[key] += 1

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*55}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*55}{RESET}")


# ══════════════════════════════════════════════════════
# 1. PYTHON VERSION
# ══════════════════════════════════════════════════════
section("🐍 Python Version")
ver = sys.version_info
check(
    f"Python {ver.major}.{ver.minor}.{ver.micro}",
    ver.major == 3 and ver.minor >= 9,
    "Install Python 3.9 or higher from python.org",
    "fail"
)


# ══════════════════════════════════════════════════════
# 2. REQUIRED PIP PACKAGES
# ══════════════════════════════════════════════════════
section("📦 Required Pip Packages")

pip_packages = {
    "flask"        : "flask",
    "flask-cors"   : "flask_cors",
    "flask-socketio": "flask_socketio",
    "python-dotenv": "dotenv",
    "bcrypt"       : "bcrypt",
    "requests"     : "requests",
    "pyngrok"      : "pyngrok",
}

optional_packages = {
    "opencv-python": "cv2",
    "mediapipe"    : "mediapipe",
    "numpy"        : "numpy",
    "vosk"         : "vosk",
    "pygame"       : "pygame",
    "yt-dlp"       : "yt_dlp",
    "pyaudio"      : "pyaudio",
    "Pillow"       : "PIL",
    "scikit-learn" : "sklearn",
}

for pkg, imp in pip_packages.items():
    try:
        importlib.import_module(imp)
        check(f"{pkg}", True)
    except ImportError:
        check(f"{pkg}", False, f"pip install {pkg}", "fail")

section("📦 Optional / Engine Packages")
for pkg, imp in optional_packages.items():
    try:
        importlib.import_module(imp)
        check(f"{pkg}", True)
    except ImportError:
        check(f"{pkg} (optional)", False, f"pip install {pkg}", "warn")


# ══════════════════════════════════════════════════════
# 3. CUSTOM ENGINE FILES
# ══════════════════════════════════════════════════════
section("🔧 Custom Engine Files (.py)")

engine_files = {
    "ai_brain.py"      : "Core AI chat + automation engine",
    "memory_engine.py" : "Persistent chat memory",
    "energy_engine.py" : "Energy analytics tracker",
    "music_engine.py"  : "Music playback engine",
    "voice_engine.py"  : "Vosk voice recognition engine",
    "face_engine.py"   : "OpenCV face recognition engine",
}

for fname, desc in engine_files.items():
    exists = os.path.isfile(fname)
    check(f"{fname}  ({desc})", exists, f"Create {fname} in project root", "warn")


# ══════════════════════════════════════════════════════
# 4. TEMPLATE & STATIC FILES  ← FIX: correct folder paths
# ══════════════════════════════════════════════════════
section("🗂️  Templates & Static Files")

important_files = [
    ("templates/index.html",     "Main dashboard HTML"),
    ("templates/login.html",     "Login page HTML"),
    ("static/style.css",         "Main stylesheet"),
    ("static/script.js",         "Main JavaScript"),
    ("static/login.js",          "Login page JavaScript"),
    ("static/manifest.json",     "PWA manifest"),
    ("static/service-worker.js", "Service Worker for push notifications"),
]

for fpath, desc in important_files:
    check(f"{fpath}  ({desc})", os.path.isfile(fpath), f"Create/move file to: {fpath}", "warn")


# ══════════════════════════════════════════════════════
# 5. .ENV FILE & ENVIRONMENT VARIABLES
# ══════════════════════════════════════════════════════
section("🔐 .env File & Environment Variables")

check(
    ".env file exists",
    os.path.isfile(".env"),
    "Create .env file in project root with your keys",
    "warn"
)

# Warn if .env has duplicate SECRET_KEY
if os.path.isfile(".env"):
    with open(".env") as f:
        lines = f.readlines()
    sk_count = sum(1 for l in lines if l.strip().startswith("SECRET_KEY"))
    check(
        "No duplicate SECRET_KEY in .env",
        sk_count <= 1,
        "Remove duplicate SECRET_KEY lines — only one should exist",
        "warn"
    )

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

env_vars = {
    "SECRET_KEY"   : ("Required", "Set any random secret string"),
    "GROQ_API_KEY" : ("Required for AI chat", "Get free key from console.groq.com"),
    "DOOR_PASSWORD": ("Optional", "Set door unlock password (default: 1234)"),
}

for var, (importance, hint) in env_vars.items():
    val   = os.getenv(var, "")
    is_set = bool(val)
    level  = "fail" if importance == "Required" else "warn"
    check(
        f"{var}  [{importance}]" + ("  ✔ set" if is_set else "  ✘ NOT SET"),
        is_set,
        hint,
        level
    )


# ══════════════════════════════════════════════════════
# 6. STATE & DATA FILES
# ══════════════════════════════════════════════════════
section("💾 Data / State Files")

data_files = [
    ("state.json",     "Device state (auto-created on first run)"),
    ("users.json",     "User accounts (auto-created on signup)"),
    ("schedules.json", "Schedules (auto-created when first schedule is set)"),
]

for fname, desc in data_files:
    exists = os.path.isfile(fname)
    sym = ok if exists else f"{YELLOW}[⚠️  NOT YET]{RESET}"
    print(f"  {sym}  {fname}  ({desc})")
    if not exists:
        print(f"         {CYAN}👉 Will be auto-created when app runs{RESET}")


# ══════════════════════════════════════════════════════
# 7. TRY IMPORTING ENGINES
# ══════════════════════════════════════════════════════
section("🚀 Engine Import Test (actual import trial)")

engines = [
    ("ai_brain",      "AI_AVAILABLE"),
    ("memory_engine", "MEMORY_AVAILABLE"),
    ("energy_engine", "ENERGY_AVAILABLE"),
    ("music_engine",  "MUSIC_AVAILABLE"),
    ("voice_engine",  "VOICE_AVAILABLE"),
    ("face_engine",   "FACE_AVAILABLE"),
]

for mod, flag in engines:
    try:
        importlib.import_module(mod)
        check(f"import {mod}", True)
    except ImportError as e:
        check(f"import {mod}  ← {e}", False, f"Check {mod}.py and its dependencies", "warn")
    except Exception as e:
        check(f"import {mod}  ← ERROR: {e}", False, f"Fix error in {mod}.py", "fail")


# ══════════════════════════════════════════════════════
# 8. PORT 5000 CHECK
# ══════════════════════════════════════════════════════
section("🌐 Network / Port Check")

def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) != 0

check("Port 5000 is free (Flask will use it)", port_free(5000),
      "Another app is using port 5000 — close it or change port in app.py", "warn")


# ══════════════════════════════════════════════════════
# 9. FOLDER STRUCTURE CHECK
# ══════════════════════════════════════════════════════
section("📁 Folder Structure")

check("templates/ folder exists", os.path.isdir("templates"),
      "Create a 'templates' folder and put index.html + login.html inside it", "fail")
check("static/ folder exists", os.path.isdir("static"),
      "Create a 'static' folder and put style.css, script.js, login.js etc inside it", "fail")


# ══════════════════════════════════════════════════════
# 10. SUMMARY REPORT
# ══════════════════════════════════════════════════════
section("📊 FINAL SUMMARY")

total = results["ok"] + results["fail"] + results["warn"]
print(f"""
  {GREEN}✅ Passed  : {results['ok']}{RESET}
  {RED}❌ Failed  : {results['fail']}{RESET}
  {YELLOW}⚠️  Warnings: {results['warn']}{RESET}
  ──────────────────
  Total Checks: {total}
""")

if results["fail"] > 0:
    print(f"  {RED}{BOLD}🚨 Fix the ❌ FAILED items first — app won't start without them!{RESET}")
elif results["warn"] > 0:
    print(f"  {YELLOW}{BOLD}⚠️  Fix warnings for full feature support.{RESET}")
else:
    print(f"  {GREEN}{BOLD}🎉 Everything looks great! Run: python app.py{RESET}")

print()
print(f"  {CYAN}💡 Install all missing packages at once:{RESET}")
print(f"  {BOLD}  pip install flask flask-cors flask-socketio python-dotenv bcrypt requests pyngrok{RESET}")
print(f"  {BOLD}  pip install opencv-python mediapipe numpy pygame yt-dlp vosk pyaudio Pillow scikit-learn{RESET}")
print()
