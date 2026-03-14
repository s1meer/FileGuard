"""
reporter.py - Automatically report unknown file formats to the developer.
No login. No signup. Anonymous. Sends format info only, never file content.
"""

import os
import json
import hashlib
import platform
import urllib.request
import urllib.parse
import datetime
from pathlib import Path

REPORT_URL = "https://formspree.io/f/YOUR_FORM_ID"

SEEN_FORMATS_FILE = os.path.join(Path.home(), ".fileguard_seen_formats.json")


def load_seen_formats():
    try:
        with open(SEEN_FORMATS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen_formats(seen):
    try:
        with open(SEEN_FORMATS_FILE, "w") as f:
            json.dump(seen, f, indent=2)
    except Exception:
        pass


def report_unknown_format(path: str, real_type: str, claimed_ext: str):
    seen = load_seen_formats()
    key = f"{claimed_ext}_{real_type}"
    if key in seen:
        return False
    seen[key] = datetime.datetime.now().isoformat()
    save_seen_formats(seen)
    try:
        with open(path, "rb") as f:
            magic = f.read(16).hex()
    except Exception:
        magic = "unreadable"
    payload = {
        "format_extension": claimed_ext or "(none)",
        "detected_type": real_type,
        "magic_bytes": magic,
        "os": platform.system(),
        "os_version": platform.version(),
        "file_size_kb": round(os.path.getsize(path) / 1024, 1),
        "reported_at": datetime.datetime.now().isoformat(),
    }
    try:
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(
            REPORT_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def check_and_report(scan_result: dict):
    if scan_result.get("real_type") in ("unknown", "unreadable"):
        import threading
        threading.Thread(
            target=report_unknown_format,
            args=(
                scan_result["path"],
                scan_result.get("real_type", "unknown"),
                scan_result.get("claimed_ext", ""),
            ),
            daemon=True
        ).start()
