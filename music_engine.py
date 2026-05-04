"""
music_engine.py — Smart Home YouTube Music Engine
Returns audio stream URL to browser — browser plays it via <audio> tag.
No ffmpeg, no pygame audio needed.
"""

import yt_dlp

_current_song = {"title": "", "query": "", "status": "stopped", "audio_url": ""}

def search_and_get_url(query):
    """Search YouTube, return direct audio stream URL."""
    ydl_opts = {
        "quiet":       True,
        "no_warnings": True,
        "noplaylist":  True,
        "format":      "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if "entries" in info:
                info = info["entries"][0]
            title = info.get("title", query)
            # Get direct URL
            audio_url = None
            for fmt in info.get("formats", []):
                if fmt.get("acodec") != "none" and fmt.get("vcodec") == "none":
                    audio_url = fmt["url"]
                    break
            if not audio_url:
                audio_url = info.get("url") or info["formats"][-1]["url"]
            return {"success": True, "title": title, "audio_url": audio_url}
    except Exception as e:
        return {"success": False, "message": str(e)}

def play(query):
    _current_song["status"] = "searching"
    _current_song["query"]  = query
    _current_song["title"]  = f"Searching: {query}..."
    result = search_and_get_url(query)
    if result["success"]:
        _current_song["title"]     = result["title"]
        _current_song["audio_url"] = result["audio_url"]
        _current_song["status"]    = "ready"
        print(f"[Music] Ready: {result['title']}")
    else:
        _current_song["status"] = "error"
        _current_song["title"]  = result.get("message", "Error")
    return result

def pause_resume():
    return {"success": True, "message": "Use browser controls"}

def stop():
    _current_song["status"]    = "stopped"
    _current_song["audio_url"] = ""
    _current_song["title"]     = ""
    return {"success": True, "message": "Stopped"}

def set_volume(vol):
    return {"success": True, "volume": vol}

def get_status():
    return dict(_current_song)