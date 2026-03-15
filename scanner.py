"""
scanner.py - Real file threat scanner.
"""

import os
import hashlib
import zipfile
import re
from pathlib import Path
from formats import SIGNATURES, HIGH_RISK_EXT, SUSPICIOUS_PATTERNS


def sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def detect_real_type(path):
    try:
        with open(path, "rb") as f:
            header = f.read(32)
    except Exception:
        return "unreadable", "unknown"

    for sig, ext, cat, desc in SIGNATURES:
        if header[:len(sig)] == sig:
            if ext == "zip":
                ext, cat = _refine_zip(path)
            elif ext == "wav":
                ext, cat = _refine_riff(path)
            return ext, cat
    return "unknown", "unknown"


def _refine_riff(path):
    try:
        with open(path, "rb") as f:
            data = f.read(12)
        chunk = data[8:12]
        if chunk == b"WAVE": return "wav", "audio"
        if chunk == b"AVI ": return "avi", "video"
        if chunk == b"WEBP": return "webp", "image"
    except Exception:
        pass
    return "wav", "audio"


def _refine_zip(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if any(n.startswith("word/") for n in names):     return "docx", "document"
            if any(n.startswith("xl/") for n in names):       return "xlsx", "document"
            if any(n.startswith("ppt/") for n in names):      return "pptx", "document"
            if any(n.startswith("META-INF/") for n in names): return "epub", "document"
    except Exception:
        pass
    return "zip", "archive"


def scan_file(path):
    p = Path(path)
    try:
        size = p.stat().st_size
    except Exception:
        size = 0

    ext = p.suffix.lower().lstrip(".")
    real_type, category = detect_real_type(path)

    result = {
        "path": str(path),
        "name": p.name,
        "size_kb": round(size / 1024, 1),
        "claimed_ext": ext,
        "real_type": real_type,
        "category": category,
        "threats": [],
        "warnings": [],
        "info": [],
        "risk": "safe",
        "hash": sha256(path)[:16] + "...",
    }

    if size == 0:
        result["info"].append("File is empty")
        return result

    name_lower = p.name.lower()
    dangerous = [".exe", ".bat", ".cmd", ".vbs", ".ps1", ".scr"]
    if any(name_lower.endswith(d) for d in dangerous):
        parts = name_lower.split(".")
        if len(parts) > 2:
            result["threats"].append(f"Double extension: '{p.name}' — common malware trick")

    if real_type not in ("unknown", ext):
        safe_pairs = {("docx","zip"),("xlsx","zip"),("pptx","zip"),("epub","zip")}
        if (real_type, ext) not in safe_pairs and (ext, real_type) not in safe_pairs:
            result["warnings"].append(f"Extension mismatch: file says .{ext} but content is {real_type.upper()}")

    if ext in HIGH_RISK_EXT:
        result["warnings"].append(f".{ext} files can execute code — verify the source before opening")

    if ext in ("py","js","vbs","ps1","bat","sh","cmd") or real_type in ("exe","elf","macho","script"):
        _scan_content(path, result)
        if ext in ("py","js","vbs","ps1","bat","sh"):
            _scan_script(path, result)

    if result["threats"]:
        result["risk"] = "high"
    elif len(result["warnings"]) >= 2:
        result["risk"] = "medium"
    elif result["warnings"]:
        result["risk"] = "low"

    # Safe-to-open verdict
    def _get_verdict(r):
        if r['risk'] in ('critical', 'high'):
            reason = r['threats'][0] if r['threats'] else 'Suspicious content detected'
            return {'verdict': 'NO', 'color': '#cc2200', 'reason': reason}
        if r['risk'] == 'medium':
            reason = r['warnings'][0] if r['warnings'] else 'Warnings found'
            return {'verdict': 'CAUTION', 'color': '#b8860b', 'reason': reason}
        return {'verdict': 'YES', 'color': '#2d7a2d', 'reason': 'No threats found'}

    result['verdict'] = _get_verdict(result)
    return result


def _scan_content(path, result):
    try:
        with open(path, "rb") as f:
            content = f.read(512 * 1024)
        for category, patterns in SUSPICIOUS_PATTERNS.items():
            hits = [p for p in patterns if p in content]
            if hits:
                label = hits[0].decode(errors="replace")
                if category == "keylogger":
                    result["threats"].append(f"Keylogger indicator found: {label}")
                elif category == "persistence":
                    result["threats"].append("Persistence: file tries to run automatically on startup")
                elif category == "injection":
                    result["threats"].append("Process injection: tries to inject code into other programs")
                elif category == "obfuscation":
                    result["warnings"].append("Obfuscated/hidden code detected")
    except Exception:
        pass


def _scan_script(path, result):
    try:
        with open(path, "r", errors="replace") as f:
            text = f.read()
        if text.count("chr(") > 20:
            result["threats"].append(f"Heavy obfuscation: {text.count('chr(')} chr() calls")
        b64 = re.compile(r'[A-Za-z0-9+/]{50,}={0,2}')
        if len(b64.findall(text)) > 3:
            result["warnings"].append("Base64 encoded payload detected")
        danger_patterns = [
            ("Invoke-WebRequest", "PowerShell download command"),
            ("DownloadFile(",     "File download command"),
            ("os.system(",        "System command execution"),
            ("subprocess.call(",  "System command execution"),
        ]
        for pat, label in danger_patterns:
            if pat in text:
                result["warnings"].append(f"{label}: '{pat}'")
    except Exception:
        pass


def scan_directory(root, on_progress=None):
    root = os.path.expanduser(root)
    all_files = []
    skip_dirs = {".git", "__pycache__", "node_modules", ".npm", ".Trash"}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
        for fname in filenames:
            if not fname.startswith("."):
                all_files.append(os.path.join(dirpath, fname))

    results = {
        "root": root,
        "total": len(all_files),
        "scanned": 0,
        "critical": [], "high": [], "medium": [], "low": [], "safe": [],
        "errors": [],
    }

    for i, fpath in enumerate(all_files):
        if on_progress:
            on_progress(i + 1, len(all_files), fpath)
        try:
            r = scan_file(fpath)
            results["scanned"] += 1
            results[r["risk"]].append(r)
        except Exception as e:
            results["errors"].append({"path": fpath, "error": str(e)})

    return results
