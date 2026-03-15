"""
updater.py - Silent auto-updater using GitHub releases.
"""

import os
import sys
import json
import shutil
import zipfile
import platform
import threading
import subprocess
import urllib.request
from pathlib import Path

GITHUB_USER    = "YOUR_GITHUB_USERNAME"
GITHUB_REPO    = "FileGuard"
CURRENT_VERSION = "1.1.0"
VERSION_FILE   = os.path.join(Path.home(), ".fileguard_version.json")

RELEASES_URL = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"


def get_current_version():
    try:
        with open(VERSION_FILE) as f:
            return json.load(f).get("version", CURRENT_VERSION)
    except Exception:
        return CURRENT_VERSION


def save_version(version):
    try:
        with open(VERSION_FILE, "w") as f:
            json.dump({"version": version}, f)
    except Exception:
        pass


def check_for_update():
    try:
        req = urllib.request.Request(
            RELEASES_URL,
            headers={"User-Agent": "FileGuard-Updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        latest = data.get("tag_name", "").lstrip("v")
        current = get_current_version()

        if not latest:
            return False, None, None

        def ver(v):
            try: return tuple(int(x) for x in v.split("."))
            except: return (0,)

        if ver(latest) > ver(current):
            assets = data.get("assets", [])
            system = platform.system()
            keywords = {
                "Darwin":  ["mac", "macos", "darwin"],
                "Windows": ["win", "windows"],
                "Linux":   ["linux"],
            }.get(system, [])

            dl_url = None
            for asset in assets:
                name = asset["name"].lower()
                if any(k in name for k in keywords):
                    dl_url = asset["browser_download_url"]
                    break

            if not dl_url and assets:
                dl_url = assets[0]["browser_download_url"]

            return True, latest, dl_url

        return False, None, None

    except Exception:
        return False, None, None


def download_and_install(url: str, version: str, on_progress=None, on_done=None):
    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))
        tmp_zip = os.path.join(Path.home(), ".fileguard_update.zip")

        if on_progress: on_progress("Downloading update...")

        urllib.request.urlretrieve(url, tmp_zip)

        if on_progress: on_progress("Installing update...")

        with zipfile.ZipFile(tmp_zip, "r") as z:
            z.extractall(app_dir)

        os.remove(tmp_zip)
        save_version(version)

        if on_progress: on_progress(f"Updated to v{version} — restart to apply")
        if on_done: on_done(version)

    except Exception as e:
        if on_done: on_done(None, error=str(e))


def check_and_update_in_background(on_update_available=None):
    def run():
        has_update, version, url = check_for_update()
        if has_update and on_update_available:
            on_update_available(version, url)

    threading.Thread(target=run, daemon=True).start()
