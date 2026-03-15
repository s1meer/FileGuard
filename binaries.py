"""
binaries.py - Manages bundled binary tools inside the FileGuard .app.
When running as PyInstaller .app, binaries are in Contents/Resources/bin/.
When running from source, binaries are in ./bin/ relative to this file.
"""
import os
import sys
import subprocess
from pathlib import Path


def get_app_dir():
    """Get the directory where our app resources live."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller .app — Resources in Contents/Resources/
        base = Path(sys.executable).parent.parent / 'Resources'
        if base.exists():
            return base
        return Path(sys.executable).parent
    else:
        # Running from source
        return Path(__file__).parent


def get_binary(name):
    """Get path to a bundled binary. Falls back to system PATH."""
    app_dir = get_app_dir()
    bundled = app_dir / 'bin' / name
    if bundled.exists() and os.access(str(bundled), os.X_OK):
        return str(bundled)
    local = app_dir / name
    if local.exists() and os.access(str(local), os.X_OK):
        return str(local)
    import shutil
    return shutil.which(name)


def get_ffmpeg():
    return get_binary('ffmpeg')


def get_yt_dlp():
    return get_binary('yt-dlp')


def get_tesseract():
    return get_binary('tesseract')


def get_tessdata():
    """Get path to tesseract language data."""
    app_dir = get_app_dir()
    bundled = app_dir / 'tessdata'
    if bundled.exists():
        return str(bundled)
    for p in ['/opt/homebrew/share/tessdata', '/usr/local/share/tessdata',
              '/usr/share/tesseract-ocr/4.00/tessdata']:
        if os.path.exists(p):
            return p
    return None


def check_all():
    return {
        'ffmpeg':    get_ffmpeg() is not None,
        'yt-dlp':   get_yt_dlp() is not None,
        'tesseract': get_tesseract() is not None,
        'tessdata':  get_tessdata() is not None,
    }
