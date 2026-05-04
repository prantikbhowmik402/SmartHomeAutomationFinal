"""
face_engine.py — Smart Home Face Recognition Engine
Uses: face_recognition (dlib) — NO TensorFlow, NO DeepFace needed!
Works perfectly on Windows. Fast and accurate.

✅ UPDATED: Account-wise segregation — har login account ka apna alag
           face data folder hoga. Ek account ki profiles dusre account
           mein nahi dikhegi.

Folder structure (auto-created):
    face_data/
      sha_gmail_com/          ← sha@gmail.com
        dataset/
          Alice/
          Bob/
        embeddings.json
        profiles.json
        visitor_log/
      rahul_gmail_com/        ← rahul@gmail.com
        dataset/
          Rahul/
        embeddings.json
        profiles.json
        visitor_log/

Install:
    pip install face_recognition
    pip install cmake  (if not installed)
    pip install dlib   (if face_recognition doesn't auto-install it)

Windows shortcut (no cmake needed):
    pip install face_recognition_models
    pip install https://github.com/jloh02/dlib/releases/download/v19.22/dlib-19.22.99-cp310-cp310-win_amd64.whl
    (choose the .whl that matches your Python version)
"""

import cv2
import os
import json
import re
import shutil
import numpy as np
from datetime import datetime
import time as _time

# ── Base directory (account-wise subfolders banenge yahan) ──────────
BASE_DIR = os.path.join(os.path.dirname(__file__), "face_data")
os.makedirs(BASE_DIR, exist_ok=True)

# ── Config ──────────────────────────────────────────────────────────
TOLERANCE = 0.50

# ── Default profile preferences ─────────────────────────────────────
DEFAULT_PREFS = {
    "light":     True,
    "fan_speed": 2,
    "dimmer":    70,
    "curtain":   False,
    "ac":        False,
    "inverter":  False,
    "music":     "",
    "greeting":  "Welcome home!"
}


# ══════════════════════════════════════════════════════════════════════
# ACCOUNT-WISE PATH HELPERS
# ══════════════════════════════════════════════════════════════════════

def _safe_account(account: str) -> str:
    """
    Convert account string (email/username) to a safe folder name.
    e.g. "sha@gmail.com"  →  "sha_gmail_com"
         "Rahul Kumar"    →  "rahul_kumar"
    """
    return re.sub(r'[^a-zA-Z0-9]', '_', account.strip().lower())


def _account_dir(account: str) -> str:
    d = os.path.join(BASE_DIR, _safe_account(account))
    os.makedirs(d, exist_ok=True)
    return d


def _dataset_dir(account: str) -> str:
    d = os.path.join(_account_dir(account), "dataset")
    os.makedirs(d, exist_ok=True)
    return d


def _embeddings_path(account: str) -> str:
    return os.path.join(_account_dir(account), "embeddings.json")


def _profiles_path(account: str) -> str:
    return os.path.join(_account_dir(account), "profiles.json")


def _visitor_log_dir(account: str) -> str:
    d = os.path.join(_account_dir(account), "visitor_log")
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════════════════════════════════════════════════════════════
# PROFILE MANAGEMENT — account-aware
# ══════════════════════════════════════════════════════════════════════

def load_profiles(account: str = "default") -> dict:
    path = _profiles_path(account)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)

def save_profiles(profiles: dict, account: str = "default"):
    with open(_profiles_path(account), "w") as f:
        json.dump(profiles, f, indent=2)

def get_profile(name: str, account: str = "default") -> dict:
    profiles = load_profiles(account)
    merged   = DEFAULT_PREFS.copy()
    merged.update(profiles.get(name, {}))
    return merged

def save_profile(name: str, prefs: dict, account: str = "default"):
    profiles = load_profiles(account)
    profiles[name] = prefs
    save_profiles(profiles, account)

def list_registered_users(account: str = "default") -> list:
    dset = _dataset_dir(account)
    if not os.path.exists(dset):
        return []
    return [d for d in os.listdir(dset)
            if os.path.isdir(os.path.join(dset, d))]


# ══════════════════════════════════════════════════════════════════════
# EMBEDDINGS — account-wise
# ══════════════════════════════════════════════════════════════════════

def _load_embeddings(account: str = "default") -> dict:
    path = _embeddings_path(account)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _save_embeddings(embeddings: dict, account: str = "default"):
    with open(_embeddings_path(account), "w") as f:
        json.dump(embeddings, f, indent=2)


# ══════════════════════════════════════════════════════════════════════
# REGISTRATION — headless, no camera window
# ══════════════════════════════════════════════════════════════════════

def capture_faces(name: str, num_samples: int = 30, account: str = "default"):
    """
    Capture face images from webcam silently (no popup window).
    Saves images under: face_data/<account>/dataset/<name>/
    Returns: (success: bool, message: str)
    """
    user_dir = os.path.join(_dataset_dir(account), name)
    os.makedirs(user_dir, exist_ok=True)

    for f in os.listdir(user_dir):
        try:
            os.remove(os.path.join(user_dir, f))
        except Exception:
            pass

    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    face_cascade = cv2.CascadeClassifier(cascade_path)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return False, "Camera not found — check webcam connection."

    count      = 0
    frame_num  = 0
    max_frames = num_samples * 20

    print(f"[FaceEngine] [{account}] Capturing {num_samples} images for: {name}")

    try:
        while count < num_samples and frame_num < max_frames:
            ret, frame = cap.read()
            if not ret:
                break

            frame     = cv2.flip(frame, 1)
            gray      = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_num += 1

            if frame_num % 3 != 0:
                continue

            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100)
            )

            for (x, y, w, h) in faces:
                padding   = int(w * 0.2)
                x1        = max(0, x - padding)
                y1        = max(0, y - padding)
                x2        = min(frame.shape[1], x + w + padding)
                y2        = min(frame.shape[0], y + h + padding)
                face_crop = frame[y1:y2, x1:x2]
                face_img  = cv2.resize(face_crop, (256, 256))
                img_path  = os.path.join(user_dir, f"{count + 1}.jpg")
                cv2.imwrite(img_path, face_img)
                count += 1
                print(f"[FaceEngine] [{account}] Captured {count}/{num_samples}")
                if count >= num_samples:
                    break

            _time.sleep(0.05)
    finally:
        cap.release()

    if count < 8:
        return False, f"Only {count} images captured (need 8+). Sit closer and improve lighting."

    if name not in load_profiles(account):
        save_profile(name, DEFAULT_PREFS.copy(), account)

    print(f"[FaceEngine] [{account}] Done! {count} images for '{name}'.")
    return True, f"Captured {count} images for {name} ✅ — training model now..."


# ══════════════════════════════════════════════════════════════════════
# TRAINING — account-wise
# ══════════════════════════════════════════════════════════════════════

def train_model(account: str = "default"):
    """
    Build face encodings only from THIS account's registered images.
    Saves embeddings under: face_data/<account>/embeddings.json
    Returns: (success: bool, message: str)
    """
    try:
        import face_recognition
    except ImportError:
        return False, "face_recognition not installed! Run: pip install face_recognition"

    users = list_registered_users(account)
    if not users:
        return False, "No registered users found. Register first."

    all_embeddings = {}
    total_ok   = 0
    total_fail = 0

    print(f"[FaceEngine] [{account}] Training for: {users}")

    for name in users:
        user_dir  = os.path.join(_dataset_dir(account), name)
        encodings = []

        img_files = [f for f in os.listdir(user_dir)
                     if f.lower().endswith((".jpg", ".jpeg", ".png"))]

        if not img_files:
            continue

        for img_file in img_files:
            img_path = os.path.join(user_dir, img_file)
            try:
                img       = face_recognition.load_image_file(img_path)
                face_encs = face_recognition.face_encodings(img, model="hog")
                if face_encs:
                    encodings.append(face_encs[0].tolist())
                    total_ok += 1
                else:
                    total_fail += 1
            except Exception as e:
                total_fail += 1
                print(f"[FaceEngine] Error on {img_file}: {e}")

        if encodings:
            all_embeddings[name] = {
                "encodings":  encodings,
                "count":      len(encodings),
                "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
            print(f"[FaceEngine] [{account}] {name}: {len(encodings)} encodings ✅")

    if not all_embeddings:
        return False, "No encodings built. Re-register with better lighting."

    _save_embeddings(all_embeddings, account)
    msg = f"Model trained: {len(all_embeddings)} user(s), {total_ok} images"
    if total_fail:
        msg += f" ({total_fail} skipped)"
    print(f"[FaceEngine] [{account}] {msg}")
    return True, msg


# ══════════════════════════════════════════════════════════════════════
# PALM DETECTION HELPER
# ══════════════════════════════════════════════════════════════════════

def _is_palm_open(landmarks) -> bool:
    lm             = landmarks
    tips           = [8, 12, 16, 20]
    mcps           = [5,  9, 13, 17]
    extended_count = sum(1 for tip, mcp in zip(tips, mcps) if lm[tip].y < lm[mcp].y)
    spread         = abs(lm[8].x - lm[20].x)
    hand_size      = ((lm[0].x - lm[12].x)**2 + (lm[0].y - lm[12].y)**2) ** 0.5
    cond1 = extended_count >= 3
    cond2 = spread > 0.15
    cond3 = hand_size > 0.25
    return (cond1 and cond2) or (cond1 and cond3) or extended_count >= 4


# ══════════════════════════════════════════════════════════════════════
# RECOGNITION — only matches THIS account's trained faces
# ══════════════════════════════════════════════════════════════════════

def recognize_face(confidence_threshold: float = TOLERANCE,
                   progress_callback=None,
                   account: str = "default"):
    """
    Scan webcam and recognize face.
    Only compares against faces registered under this account — completely
    isolated from other accounts' data.
    Returns: dict — success, name, confidence, profile, play_music, message
    """
    try:
        import face_recognition
    except ImportError:
        return {
            "success": False, "name": "Unknown", "confidence": 0,
            "play_music": False,
            "message": "face_recognition not installed! Run: pip install face_recognition"
        }

    embeddings = _load_embeddings(account)
    if not embeddings:
        return {
            "success": False, "name": "Unknown", "confidence": 0,
            "play_music": False,
            "message": "No trained model for this account. Please register and train first."
        }

    known_names     = []
    known_encodings = []
    for person_name, data in embeddings.items():
        for enc in data.get("encodings", []):
            known_names.append(person_name)
            known_encodings.append(np.array(enc, dtype=np.float64))

    if not known_encodings:
        return {
            "success": False, "name": "Unknown", "confidence": 0,
            "play_music": False,
            "message": "No encodings found. Please train the model first."
        }

    try:
        import mediapipe as mp
        mp_hands  = mp.solutions.hands
        hands_det = mp_hands.Hands(
            max_num_hands=1,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5
        )
        USE_MP = True
    except ImportError:
        USE_MP    = False
        hands_det = None

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return {
            "success": False, "name": "Unknown", "confidence": 0,
            "play_music": False,
            "message": "Camera not found — check webcam connection."
        }

    for _ in range(10):
        cap.read()
        _time.sleep(0.03)

    if progress_callback:
        progress_callback("📷 Camera ready — please look at the camera...")

    result            = {"success": False, "name": "Unknown", "confidence": 0, "play_music": False}
    attempts          = 0
    max_attempts      = 80
    palm_frames       = 0
    recognition_votes = {}
    last_frame        = None
    faces_seen        = 0

    print(f"[FaceEngine] [{account}] Recognition started...")

    try:
        while attempts < max_attempts:
            ret, frame = cap.read()
            if not ret:
                break

            frame      = cv2.flip(frame, 1)
            last_frame = frame.copy()
            attempts  += 1

            if progress_callback and attempts % 15 == 0:
                pct = int(attempts / max_attempts * 100)
                msg = f"👤 Face detected! Matching... {pct}%" if faces_seen > 0 \
                      else f"🔍 Scanning... {pct}% — move closer if needed"
                progress_callback(msg)

            rgb       = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            small_rgb = cv2.resize(rgb, (0, 0), fx=0.5, fy=0.5)

            face_locations = face_recognition.face_locations(small_rgb, model="hog")

            if face_locations:
                faces_seen += 1
                face_locations_full = [
                    (top*2, right*2, bottom*2, left*2)
                    for (top, right, bottom, left) in face_locations
                ]
                live_encodings = face_recognition.face_encodings(rgb, face_locations_full)

                for live_enc in live_encodings:
                    distances = face_recognition.face_distance(known_encodings, live_enc)
                    best_idx  = int(np.argmin(distances))
                    best_dist = float(distances[best_idx])
                    best_name = known_names[best_idx]

                    if best_dist < confidence_threshold:
                        confidence_pct = round((1.0 - best_dist / confidence_threshold) * 100, 1)
                        recognition_votes[best_name] = recognition_votes.get(best_name, 0) + 1
                        print(f"[FaceEngine] [{account}] Vote: {best_name} ({confidence_pct:.1f}%)")

                        if progress_callback:
                            progress_callback(
                                f"✨ Possible match: {best_name} ({confidence_pct:.0f}%) — confirming...")

                        if recognition_votes.get(best_name, 0) >= 3 and not result["success"]:
                            result.update({
                                "success":    True,
                                "name":       best_name,
                                "confidence": confidence_pct,
                                "profile":    get_profile(best_name, account),
                                "message":    f"Welcome, {best_name}! ({confidence_pct:.0f}% match)"
                            })
                    else:
                        print(f"[FaceEngine] [{account}] Unknown face, dist={best_dist:.3f}")

            if USE_MP:
                hr = hands_det.process(rgb)
                if hr.multi_hand_landmarks:
                    for hl in hr.multi_hand_landmarks:
                        if _is_palm_open(hl.landmark):
                            palm_frames += 1

            if result["success"] and attempts >= 10:
                break

            _time.sleep(0.08)

    finally:
        cap.release()
        if USE_MP and hands_det:
            hands_det.close()

    if result["success"]:
        result["play_music"] = palm_frames >= 3
        suffix = " 🖐 Music will play!" if result["play_music"] else ""
        result["message"] += suffix
        print(f"[FaceEngine] [{account}] Recognized: {result['name']} ({result['confidence']}%)")
    else:
        _save_visitor_snapshot(last_frame, account)
        result["message"] = (
            "No face detected — sit closer and ensure good lighting."
            if faces_seen == 0 else
            "Face detected but not recognized — try re-registering."
        )
        print(f"[FaceEngine] [{account}] Recognition failed")

    return result


# ══════════════════════════════════════════════════════════════════════
# VISITOR LOG — account-wise
# ══════════════════════════════════════════════════════════════════════

def _save_visitor_snapshot(frame, account: str = "default"):
    if frame is None:
        return
    try:
        vlog_dir  = _visitor_log_dir(account)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path      = os.path.join(vlog_dir, f"unknown_{timestamp}.jpg")
        cv2.imwrite(path, frame)
        snapshots = sorted(os.listdir(vlog_dir))
        while len(snapshots) > 20:
            os.remove(os.path.join(vlog_dir, snapshots.pop(0)))
    except Exception as e:
        print(f"[FaceEngine] Snapshot error: {e}")

def get_visitor_log(account: str = "default") -> list:
    vlog_dir = _visitor_log_dir(account)
    if not os.path.exists(vlog_dir):
        return []
    files  = sorted(os.listdir(vlog_dir), reverse=True)
    result = []
    for f in files:
        if f.endswith(".jpg"):
            parts = f.replace("unknown_", "").replace(".jpg", "")
            try:
                dt    = datetime.strptime(parts, "%Y%m%d_%H%M%S")
                label = dt.strftime("%d %b %Y, %I:%M:%S %p")
            except Exception:
                label = f
            result.append({"filename": f, "time": label})
    return result


# ══════════════════════════════════════════════════════════════════════
# DELETE USER — only from this account
# ══════════════════════════════════════════════════════════════════════

def delete_user(name: str, account: str = "default") -> bool:
    user_dir = os.path.join(_dataset_dir(account), name)
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
    profiles = load_profiles(account)
    profiles.pop(name, None)
    save_profiles(profiles, account)
    embeddings = _load_embeddings(account)
    if name in embeddings:
        del embeddings[name]
        _save_embeddings(embeddings, account)
        print(f"[FaceEngine] [{account}] Deleted: {name}")
    return True


# ══════════════════════════════════════════════════════════════════════
# UTILITY
# ══════════════════════════════════════════════════════════════════════

def get_engine_info(account: str = "default") -> dict:
    embeddings = _load_embeddings(account)
    users      = list_registered_users(account)
    return {
        "engine":            "face_recognition (dlib)",
        "model":             "HOG + 128-dim face encodings",
        "threshold":         TOLERANCE,
        "account":           account,
        "registered_users":  users,
        "trained_users":     list(embeddings.keys()),
        "total_encodings":   sum(d.get("count", 0) for d in embeddings.values()),
        "embeddings_file":   os.path.exists(_embeddings_path(account)),
        "visitor_snapshots": len(os.listdir(_visitor_log_dir(account)))
                             if os.path.exists(_visitor_log_dir(account)) else 0,
    }