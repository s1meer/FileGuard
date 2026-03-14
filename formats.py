"""
formats.py - File format detection database.
"""

SIGNATURES = [
    (b"%PDF",              "pdf",    "document",   "PDF document"),
    (b"PK\x03\x04",       "zip",    "archive",    "ZIP/Office/EPUB/APK"),
    (b"\xd0\xcf\x11\xe0", "doc",    "document",   "Legacy MS Office"),
    (b"{\rtf",             "rtf",    "document",   "Rich Text Format"),
    (b"<html",             "html",   "web",        "HTML page"),
    (b"<!DOC",             "html",   "web",        "HTML page"),
    (b"<?xml",             "xml",    "data",       "XML document"),
    (b"\x89PNG\r\n",       "png",    "image",      "PNG image"),
    (b"\xff\xd8\xff",      "jpg",    "image",      "JPEG image"),
    (b"GIF87a",            "gif",    "image",      "GIF image"),
    (b"GIF89a",            "gif",    "image",      "GIF image"),
    (b"BM",                "bmp",    "image",      "Bitmap image"),
    (b"II*\x00",           "tiff",   "image",      "TIFF image"),
    (b"MM\x00*",           "tiff",   "image",      "TIFF image"),
    (b"8BPS",              "psd",    "image",      "Photoshop file"),
    (b"ID3",               "mp3",    "audio",      "MP3 audio"),
    (b"\xff\xfb",          "mp3",    "audio",      "MP3 audio"),
    (b"\xff\xf3",          "mp3",    "audio",      "MP3 audio"),
    (b"fLaC",              "flac",   "audio",      "FLAC audio"),
    (b"OggS",              "ogg",    "audio",      "OGG audio"),
    (b"RIFF",              "wav",    "audio",      "WAV/AVI/WebP"),
    (b"\x1a\x45\xdf\xa3", "mkv",    "video",      "MKV video"),
    (b"FLV\x01",           "flv",    "video",      "Flash video"),
    (b"\x30\x26\xb2\x75", "wmv",    "video",      "WMV video"),
    (b"\x1f\x8b",          "gz",     "archive",    "GZIP archive"),
    (b"BZh",               "bz2",    "archive",    "BZIP2 archive"),
    (b"7z\xbc\xaf\x27\x1c","7z",    "archive",    "7-Zip archive"),
    (b"Rar!\x1a\x07\x00",  "rar",   "archive",    "RAR archive"),
    (b"Rar!\x1a\x07\x01",  "rar",   "archive",    "RAR5 archive"),
    (b"MZ",                "exe",    "executable", "Windows executable"),
    (b"\x7fELF",           "elf",    "executable", "Linux executable"),
    (b"\xca\xfe\xba\xbe",  "macho", "executable", "macOS executable"),
    (b"\xfe\xed\xfa\xce",  "macho", "executable", "macOS executable"),
    (b"\xce\xfa\xed\xfe",  "macho", "executable", "macOS executable"),
    (b"#!",                "script", "executable", "Shell script"),
    (b"SQLite format 3",   "sqlite", "data",       "SQLite database"),
    (b"OTTO",              "otf",    "font",       "OpenType font"),
    (b"\x00\x01\x00\x00",  "ttf",   "font",       "TrueType font"),
]

HIGH_RISK_EXT = {
    "exe", "dll", "bat", "cmd", "com", "msi", "vbs",
    "ps1", "scr", "pif", "hta", "reg", "jar", "lnk",
}

SUSPICIOUS_PATTERNS = {
    "keylogger": [
        b"GetAsyncKeyState", b"SetWindowsHookEx",
        b"keylog", b"keystroke", b"WH_KEYBOARD",
    ],
    "persistence": [
        b"CurrentVersion\\Run",
        b"schtasks /create",
    ],
    "injection": [
        b"VirtualAlloc", b"WriteProcessMemory",
        b"CreateRemoteThread", b"ShellExecute",
    ],
    "obfuscation": [
        b"base64.b64decode", b"eval(base64",
        b"exec(compile",
    ],
}
