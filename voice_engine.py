"""
voice_engine.py — Kitty Hybrid Wake Word Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARCHITECTURE:
  Stage 1 — Vosk (always-on, offline)
              Sirf "kitty" dhundhta hai — chhota kaam, chota model bhi theek hai.
              Accurate transcription ki zaroorat NAHI — bas wake word pakdna hai.

  Stage 2 — Groq Whisper (triggered, cloud)
              Wake word ke baad mic se RECORD_SECONDS ka audio record karta hai.
              Groq Whisper API pe bhejta hai → crystal-clear transcription milti hai.
              Is text ko parser mein deta hai → perfect commands.

Yeh isliye better hai:
  • Vosk ka small model "kitty" pakad sakta hai (ek word, low bar)
  • Commands ka transcription Whisper karta hai jo 99% accurate hai
  • "tarn of" ki jagah seedha "turn off" milta hai
"""

import os, io, json, re, wave, threading, queue, time
import requests as _requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MODEL_PATH   = os.path.join(os.path.dirname(__file__), "vosk-model")

WHISPER_URL      = "https://api.groq.com/openai/v1/audio/transcriptions"
SAMPLE_RATE      = 16000
RECORD_SECONDS   = 4       # seconds to record after wake word
COMMAND_CHANNELS = 1
SAMPLE_WIDTH     = 2       # 16-bit PCM

# Wake word variants — Vosk sometimes mishears "kitty" as these
WAKE_WORDS = {
    "kitty", "kitti", "kiddy", "kitties", "kittie",
    "hey kitty", "ok kitty", "okay kitty", "hi kitty",
}

# ── Global state ──────────────────────────────────────
_listening       = False
_listen_thread   = None
_result_queue    = queue.Queue()
_status_callback = None   # called whenever mode changes — used by app.py to emit socket
_status          = {
    "listening":     False,
    "wake_detected": False,
    "last_command":  "",
    "last_text":     "",
    "mode":          "idle",  # idle | waiting_wake | recording | transcribing | executing
}

def _set_mode(mode, extra=None):
    """Update _status mode and fire the status_callback so app.py can emit socket."""
    _status["mode"] = mode
    if extra:
        _status.update(extra)
    if _status_callback:
        try:
            _status_callback(dict(_status))
        except Exception as e:
            print(f"[Voice] status_callback error: {e}")


# ══════════════════════════════════════════════════════
# WAKE WORD HELPERS
# ══════════════════════════════════════════════════════

def _contains_wake_word(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in WAKE_WORDS)


# ══════════════════════════════════════════════════════
# COMMAND PARSER  (runs on Whisper output — clean text)
# ══════════════════════════════════════════════════════

def parse_command(text: str):
    """
    Keyword-based parser — works regardless of word order.
    Whisper gives clean natural English so we use presence-of-keywords,
    not fixed phrases. This handles:
      "turn off bedroom fan"       ✅
      "turn on the balcony light"  ✅
      "bedroom light off"          ✅
      "turn off music"             ✅
      "सारे light on कर दो"        ✅  (Hinglish)
    """
    text = text.lower().strip().rstrip(".")

    # Strip wake word if Whisper caught it too
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        text = text.replace(w, "").strip(" ,.")
    text = text.strip()

    if not text or len(text) < 2:
        return None

    print(f"[Voice] Parsing (Whisper): '{text}'")
    words = set(text.split())   # individual words for fast lookup
    cmd   = {"raw": text, "action": None, "device": None, "value": None, "room": "living"}

    # ── Helpers ────────────────────────────────────────
    def has(*kws):
        """True if ANY keyword is a substring of text."""
        return any(k in text for k in kws)

    def has_all(*kws):
        """True if ALL keywords are substrings of text."""
        return all(k in text for k in kws)

    # ── Room detection (run first — needed by all devices) ─
    if has("bedroom", "bed room"):
        cmd["room"] = "bedroom"
    elif has("kitchen"):
        cmd["room"] = "kitchen"
    elif has("balcony"):
        cmd["room"] = "balcony"
    elif has("living"):
        cmd["room"] = "living"

    # ── Detect ON / OFF intent ──────────────────────────
    # ON signals
    on_words  = {"on", "start", "chalo", "jalo", "chalu", "on karo",
                 "turn on", "switch on", "chalao", "켜", "on kar"}
    # OFF signals
    off_words = {"off", "stop", "band", "bandh", "off karo", "band karo",
                 "turn off", "switch off", "rok", "बंद", "off kar"}

    is_on  = any(k in text for k in on_words)
    is_off = any(k in text for k in off_words)

    # If both somehow present, trust position: "turn off" beats "on" in "turn off bedroom light"
    if is_on and is_off:
        is_on = False   # off takes priority when ambiguous

    # ── MUSIC (check before light/fan to avoid "turn off" ambiguity) ──
    if has("music", "gaana", "gana", "song", "audio"):
        # Play song check first
        for trigger in ["play music", "play song", "play gana", "play gaana",
                        "play the song", "bajao", "play"]:
            if trigger in text:
                song = text.split(trigger, 1)[-1].strip()
                for filler in ["please", "karo", "do", "now", "abhi", "on", "zara"]:
                    song = song.replace(filler, "").strip()
                if song and len(song) > 1:
                    cmd.update({"action": "play", "device": "music", "value": song})
                    return cmd
                break
        if has("pause", "roko"):
            cmd.update({"action": "pause",        "device": "music"}); return cmd
        if has("resume", "chalao", "shuru"):
            cmd.update({"action": "resume",       "device": "music"}); return cmd
        if is_off or has("stop", "band", "rok", "off"):
            cmd.update({"action": "stop",         "device": "music"}); return cmd
        if is_on:
            cmd.update({"action": "resume",       "device": "music"}); return cmd

    # ── VOLUME ─────────────────────────────────────────
    if has("volume", "vol"):
        if has("up", "increase", "badha", "high", "zyada", "louder"):
            cmd.update({"action": "volume_up",   "device": "music"}); return cmd
        if has("down", "decrease", "kam", "low", "quieter"):
            cmd.update({"action": "volume_down", "device": "music"}); return cmd

    # ── LIGHT ─────────────────────────────────────────
    if has("light", "lights", "batti", "bulb",
           "सारे light", "sab light", "all light"):
        if is_on  or has("jalo", "on kar", "켜"):
            cmd.update({"action": "on",  "device": "light"}); return cmd
        if is_off or has("band", "bujhao", "बंद"):
            cmd.update({"action": "off", "device": "light"}); return cmd

    # ── FAN ────────────────────────────────────────────
    if has("fan", "pankha"):
        # Fan speed check first: "fan speed 3" / "fan to three"
        num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                   "1":   1, "2":   2, "3":     3, "4":     4, "5":     5}
        if has("speed") or has_all("fan", "set"):
            for w, n in num_map.items():
                if w in text:
                    cmd.update({"action": "speed", "device": "fan", "value": n}); return cmd
        # Direct number with fan: "fan 3", "fan three"
        if has("fan") and not has("speed"):
            for w, n in num_map.items():
                if w in words:   # exact word match to avoid "four" in "before"
                    cmd.update({"action": "speed", "device": "fan", "value": n}); return cmd
        if is_on  or has("chalo", "chalao", "start"):
            cmd.update({"action": "on",  "device": "fan", "value": 3}); return cmd
        if is_off or has("band", "rok"):
            cmd.update({"action": "off", "device": "fan", "value": 0}); return cmd

    # ── AC ─────────────────────────────────────────────
    if has("ac", "a.c", "air condition", "aircondition"):
        if cmd["room"] in ("kitchen", "balcony"):
            print("[Voice] ⚠️  AC not available in kitchen/balcony")
            return None
        if is_on:
            cmd.update({"action": "on",  "device": "ac"}); return cmd
        if is_off:
            cmd.update({"action": "off", "device": "ac"}); return cmd

    # ── CURTAIN ────────────────────────────────────────
    if has("curtain", "parda", "blinds"):
        if is_on  or has("open", "kholo", "utha"):
            cmd.update({"action": "open",  "device": "curtain"}); return cmd
        if is_off or has("close", "band", "gira"):
            cmd.update({"action": "close", "device": "curtain"}); return cmd

    # ── DIMMER / BRIGHTNESS ────────────────────────────
    if has("brightness", "dimmer", "dim"):
        word_map = {"zero": 0, "ten": 10, "twenty": 20, "thirty": 30,
                    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
                    "eighty": 80, "ninety": 90, "hundred": 100,
                    "full": 100, "half": 50, "minimum": 10, "maximum": 100}
        for w, n in word_map.items():
            if w in text:
                cmd.update({"action": "set", "device": "dimmer", "value": n}); return cmd
        m = re.search(r'\b(\d{1,3})\b', text)
        if m:
            cmd.update({"action": "set", "device": "dimmer",
                        "value": max(0, min(100, int(m.group(1))))}); return cmd

    # ── INVERTER ───────────────────────────────────────
    if has("inverter"):
        if is_on:
            cmd.update({"action": "on",  "device": "inverter"}); return cmd
        if is_off:
            cmd.update({"action": "off", "device": "inverter"}); return cmd

    # ── STOP VOICE ─────────────────────────────────────
    if has("stop listening", "voice off", "stop voice", "goodbye", "bye kitty"):
        cmd.update({"action": "stop_listening", "device": "voice"}); return cmd

    return None   # not recognised


# ══════════════════════════════════════════════════════
# AUDIO HELPERS
# ══════════════════════════════════════════════════════

def _record_audio(stream, seconds: int) -> bytes:
    """Record `seconds` of 16-bit PCM from the open PyAudio stream."""
    frames = []
    chunk  = 1024
    total  = int(SAMPLE_RATE / chunk * seconds)
    for _ in range(total):
        try:
            frames.append(stream.read(chunk, exception_on_overflow=False))
        except Exception:
            pass
    return b"".join(frames)


def _pcm_to_wav(pcm_data: bytes) -> bytes:
    """Wrap raw PCM bytes in a WAV container (in-memory)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(COMMAND_CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_data)
    return buf.getvalue()


# ══════════════════════════════════════════════════════
# GROQ WHISPER TRANSCRIPTION
# ══════════════════════════════════════════════════════

def _whisper_transcribe(wav_bytes: bytes) -> str:
    """Send WAV bytes to Groq Whisper API via requests library, return transcribed text."""
    if not GROQ_API_KEY:
        print("[Voice] ⚠️  GROQ_API_KEY not set — cannot transcribe")
        return ""
    try:
        resp = _requests.post(
            WHISPER_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("cmd.wav", wav_bytes, "audio/wav")},
            data={"model": "whisper-large-v3-turbo", "response_format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
        print(f"[Voice] 🎙️  Whisper transcribed: '{text}'")
        return text
    except _requests.HTTPError as e:
        print(f"[Voice] Whisper HTTP {e.response.status_code}: {e.response.text[:200]}")
        return ""
    except Exception as e:
        print(f"[Voice] Whisper error: {e}")
        return ""


# ══════════════════════════════════════════════════════
# MAIN WORKER — Vosk detects wake word → Whisper transcribes command
# ══════════════════════════════════════════════════════

def _listen_worker(callback=None):
    global _listening, _status

    try:
        import vosk
        import pyaudio
    except ImportError as e:
        print(f"[Voice] Import error: {e}")
        _status["listening"] = False
        return

    if not os.path.exists(MODEL_PATH):
        print(f"[Voice] Vosk model not found: {MODEL_PATH}")
        _status["listening"] = False
        return

    print("[Voice] Loading Vosk (wake word only — any model size works)…")
    model = vosk.Model(MODEL_PATH)
    rec   = vosk.KaldiRecognizer(model, SAMPLE_RATE)

    pa      = pyaudio.PyAudio()
    dev_idx = None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            dev_idx = i
            print(f"[Voice] Mic: {info['name']}")
            break

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=COMMAND_CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        input_device_index=dev_idx,
        frames_per_buffer=4096,
    )
    stream.start_stream()

    _status["listening"] = True
    _set_mode("waiting_wake", {"wake_detected": False})
    print("[Voice] 🐱 Kitty is always on — say 'Kitty' to activate!")
    print(f"[Voice] Groq API: {'✅ ready' if GROQ_API_KEY else '❌ GROQ_API_KEY missing!'}")

    partial_buffer = ""

    while _listening:
        try:
            data = stream.read(2048, exception_on_overflow=False)
        except Exception:
            continue

        if rec.AcceptWaveform(data):
            text = json.loads(rec.Result()).get("text", "").strip()
            if not text:
                continue

            _status["last_text"] = text

            if _contains_wake_word(text):
                print(f"[Voice] 🐱 Wake word! Vosk heard: '{text}'")
                _set_mode("recording", {"wake_detected": True})

                # ── Record the command ──────────────────────
                print(f"[Voice] 🔴 Recording {RECORD_SECONDS}s…")
                pcm = _record_audio(stream, RECORD_SECONDS)

                # ── Send to Groq Whisper ─────────────────────
                _set_mode("transcribing")
                print("[Voice] ☁️  Transcribing via Groq Whisper…")
                whisper_text = _whisper_transcribe(_pcm_to_wav(pcm))

                if whisper_text:
                    _status["last_text"] = whisper_text
                    cmd = parse_command(whisper_text)
                    if cmd:
                        _dispatch(cmd, callback)
                        if cmd.get("action") == "stop_listening":
                            _listening = False
                            break
                    else:
                        msg = f"❓ '{whisper_text}' — not recognised"
                        print(f"[Voice] {msg}")
                        _status["last_text"] = msg
                else:
                    print("[Voice] ⚠️  Nothing heard after wake word")

                _set_mode("waiting_wake", {"wake_detected": False})

        else:
            # Check partial results too — catch "kitty" faster and more reliably
            pt = json.loads(rec.PartialResult()).get("partial", "").strip()
            if pt and pt != partial_buffer:
                partial_buffer = pt
                # If partial already contains the wake word → trigger immediately
                if _contains_wake_word(pt):
                    print(f"[Voice] 🐱 Wake word (partial)! Vosk heard: '{pt}'")
                    _set_mode("recording", {"wake_detected": True})
                    print(f"[Voice] 🔴 Recording {RECORD_SECONDS}s…")
                    pcm = _record_audio(stream, RECORD_SECONDS)
                    _set_mode("transcribing")
                    print("[Voice] ☁️  Transcribing via Groq Whisper…")
                    whisper_text = _whisper_transcribe(_pcm_to_wav(pcm))
                    if whisper_text:
                        _status["last_text"] = whisper_text
                        cmd_p = parse_command(whisper_text)
                        if cmd_p:
                            _dispatch(cmd_p, callback)
                            if cmd_p.get("action") == "stop_listening":
                                _listening = False
                                break
                        else:
                            msg = f"❓ '{whisper_text}' — not recognised"
                            print(f"[Voice] {msg}")
                            _status["last_text"] = msg
                    else:
                        print("[Voice] ⚠️  Nothing heard after wake word")
                    _set_mode("waiting_wake", {"wake_detected": False})
                    partial_buffer = ""
                    rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)  # fresh recognizer
                elif any(pt.startswith(w[:3]) for w in WAKE_WORDS if len(pt) >= 3):
                    _status["last_text"] = f"… {pt}"

    stream.stop_stream()
    stream.close()
    pa.terminate()
    _status["listening"] = False
    _set_mode("idle", {"wake_detected": False})
    print("[Voice] 🔇 Kitty stopped.")


def _dispatch(cmd: dict, callback):
    print(f"[Voice] ✅ Executing: {cmd}")
    _status["last_command"] = cmd["raw"]
    _set_mode("executing")
    _result_queue.put(cmd)
    if callback:
        try:
            callback(cmd)
        except Exception as e:
            print(f"[Voice] Callback error: {e}")


# ══════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════

def set_status_callback(fn):
    """app.py yeh call karta hai taaki socket emit ho sake jab mode change ho."""
    global _status_callback
    _status_callback = fn


def start_listening(callback=None):
    global _listening, _listen_thread
    if _listening:
        return {"success": False, "message": "Already listening"}
    _listening     = True
    _listen_thread = threading.Thread(target=_listen_worker, args=(callback,), daemon=True)
    _listen_thread.start()
    return {"success": True, "message": "Kitty is always on — say 'Kitty' to activate!"}


def stop_listening():
    global _listening
    _listening = False
    _status["listening"] = False
    _set_mode("idle", {"wake_detected": False})
    return {"success": True, "message": "Stopped"}


def get_status():
    return dict(_status)