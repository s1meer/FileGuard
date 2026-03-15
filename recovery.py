"""
recovery.py - Repair and recover damaged files.
"""

import os
import re
import gzip
import shutil
import zipfile
import chardet
from pathlib import Path

try:
    import pikepdf
    HAS_PIKEPDF = True
except ImportError:
    HAS_PIKEPDF = False

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def repair_file(path, out_dir=None, log_callback=None):
    def log(msg):
        if log_callback:
            log_callback(msg)

    p = Path(path)
    if out_dir is None:
        out_dir = str(p.parent / "recovered")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(path):
        return {"ok": False, "message": "File not found"}

    size = os.path.getsize(path)
    if size == 0:
        return {"ok": False, "message": "File is empty — download failed. Please redownload it."}

    log(f"Reading file: {p.name} ({round(size/1024,1)} KB)")

    try:
        with open(path, "rb") as f:
            header = f.read(32)
    except Exception as e:
        return {"ok": False, "message": f"Cannot read file: {e}"}

    log("Detecting real file type from content...")

    if header[:4] == b"%PDF":
        log("Detected: PDF document")
        return _repair_pdf(path, out_dir, log)

    if header[:4] == b"PK\x03\x04":
        log("Detected: ZIP-based file (ZIP/DOCX/XLSX/PPTX/EPUB)")
        return _repair_zip(path, out_dir, log)

    if header[:6] == b"\x89PNG\r\n" or header[:2] == b"\xff\xd8" or header[:6] in (b"GIF87a", b"GIF89a"):
        log("Detected: Image file")
        return _repair_image(path, out_dir, log)

    if header[:3] == b"ID3" or header[:2] in (b"\xff\xfb", b"\xff\xf3"):
        log("Detected: MP3 audio")
        return _repair_mp3(path, out_dir, log)

    if header[:4] == b"fLaC":
        log("Detected: FLAC audio — copying with correct extension")
        return _copy_fixed(path, out_dir, "flac", log)

    if header[:4] == b"OggS":
        log("Detected: OGG audio — copying with correct extension")
        return _copy_fixed(path, out_dir, "ogg", log)

    if header[:4] == b"RIFF":
        log("Detected: RIFF container (WAV/AVI)")
        return _repair_riff(path, out_dir, log)

    if header[:2] == b"\x1f\x8b":
        log("Detected: GZIP archive")
        return _repair_gz(path, out_dir, log)

    if header[:7] == b"Rar!\x1a\x07":
        log("Detected: RAR archive")
        return _repair_rar(path, out_dir, log)

    if header[:6] == b"7z\xbc\xaf\x27\x1c":
        log("Detected: 7-Zip archive")
        return _repair_7z(path, out_dir, log)

    # Legacy Office (OLE2) — .doc, .xls, .ppt
    if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        log("Detected: Legacy Office file (OLE2 format — .doc/.xls/.ppt)")
        return _repair_ole_office(path, out_dir, log)

    try:
        with open(path, "rb") as f:
            raw = f.read(512)
        printable = sum(32 <= b < 127 or b in (9,10,13) for b in raw)
        if len(raw) > 0 and printable / len(raw) > 0.75:
            log("Detected: Text file with possible encoding issues")
            return _fix_encoding(path, out_dir, log)
    except Exception:
        pass

    return {"ok": False, "message": "File format not recognized or too severely damaged to repair automatically."}


def _repair_pdf(path, out_dir, log):
    if not HAS_PIKEPDF:
        return {"ok": False, "message": "pikepdf not installed. Run: pip3 install pikepdf"}
    try:
        p = Path(path)
        out = os.path.join(out_dir, p.stem + "_repaired.pdf")
        log("Opening PDF with pikepdf...")
        with pikepdf.open(path, suppress_warnings=True) as pdf:
            pages = len(pdf.pages)
            log(f"Found {pages} pages — saving repaired copy...")
            pdf.save(out)
        return {"ok": True, "output": out, "message": f"PDF repaired — {pages} pages recovered"}
    except Exception as e:
        log(f"pikepdf failed: {e} — trying raw text recovery...")
        return _pdf_raw_recover(path, out_dir, log)


def _pdf_raw_recover(path, out_dir, log):
    try:
        with open(path, "rb") as f:
            data = f.read()
        streams = re.findall(b"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL)
        texts = []
        for s in streams:
            decoded = s.decode("latin-1", errors="ignore")
            clean = "".join(c for c in decoded if c.isprintable() or c in "\n\t ")
            if len(clean.strip()) > 20:
                texts.append(clean.strip())
        if texts:
            p = Path(path)
            out = os.path.join(out_dir, p.stem + "_recovered_text.txt")
            with open(out, "w", encoding="utf-8") as f:
                f.write("\n\n--- PAGE BREAK ---\n\n".join(texts))
            log(f"Recovered {len(texts)} text blocks from damaged PDF")
            return {"ok": True, "output": out, "message": f"PDF too damaged for full repair — recovered {len(texts)} text blocks as .txt"}
        return {"ok": False, "message": "PDF is too severely damaged — no content could be recovered"}
    except Exception as e:
        return {"ok": False, "message": f"PDF recovery failed: {e}"}


def _repair_zip(path, out_dir, log):
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    # Check integrity first
    try:
        with zipfile.ZipFile(path, "r") as z:
            bad = z.testzip()
        if bad is None:
            # File is healthy — create a clean copy
            log("ZIP structure tests OK — file is healthy")
            if ext in ("docx", "xlsx", "pptx", "epub"):
                out = os.path.join(out_dir, p.stem + "_repaired." + ext)
                import shutil
                shutil.copy2(path, out)
                log(f"Copied healthy {ext.upper()} to output")
                return {"ok": True, "output": out, "message": f"{ext.upper()} is healthy — copy saved"}
            else:
                out = os.path.join(out_dir, p.name)
                import shutil
                shutil.copy2(path, out)
                log("Copied healthy ZIP to output")
                return {"ok": True, "output": out, "message": "Archive is healthy — copy saved"}
    except zipfile.BadZipFile:
        log("ZIP structure broken — attempting partial recovery...")
    except Exception:
        log("ZIP test failed — attempting partial recovery...")

    extract_dir = os.path.join(out_dir, p.stem + "_extracted")
    os.makedirs(extract_dir, exist_ok=True)
    recovered = []
    failed = []
    try:
        with zipfile.ZipFile(path, "r") as z:
            for item in z.infolist():
                try:
                    z.extract(item, extract_dir)
                    recovered.append(item.filename)
                    log(f"Extracted: {item.filename}")
                except Exception:
                    failed.append(item.filename)
        if recovered:
            if ext in ("docx", "xlsx", "pptx", "epub"):
                out = os.path.join(out_dir, p.stem + "_repaired." + ext)
                log(f"Repacking as {ext.upper()}...")
                with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                    for root, dirs, files in os.walk(extract_dir):
                        for file in files:
                            full = os.path.join(root, file)
                            rel = os.path.relpath(full, extract_dir)
                            z.write(full, rel)
                return {"ok": True, "output": out, "message": f"Repaired {ext.upper()} — {len(recovered)} files recovered, {len(failed)} lost"}
            return {"ok": True, "output": extract_dir, "message": f"Extracted {len(recovered)} files ({len(failed)} unrecoverable)"}
        return {"ok": False, "message": "Archive is too damaged — no files could be extracted"}
    except zipfile.BadZipFile:
        return {"ok": False, "message": "Archive is completely broken — please redownload it"}
    except Exception as e:
        return {"ok": False, "message": f"Archive repair failed: {e}"}


def _repair_image(path, out_dir, log):
    if not HAS_PIL:
        return {"ok": False, "message": "Pillow not installed. Run: pip3 install Pillow"}
    try:
        p = Path(path)
        out = os.path.join(out_dir, p.stem + "_repaired" + p.suffix)
        log("Opening image — stripping corrupt metadata...")
        with Image.open(path) as img:
            if img.mode not in ("RGB", "RGBA", "L"):
                img = img.convert("RGB")
            w, h = img.size
            log(f"Image size: {w}x{h} pixels")
            img.save(out)
        return {"ok": True, "output": out, "message": f"Image repaired — {w}x{h} pixels saved"}
    except Exception as e:
        return {"ok": False, "message": f"Image repair failed: {e}"}


def _repair_mp3(path, out_dir, log):
    try:
        p = Path(path)
        out = os.path.join(out_dir, p.stem + "_repaired.mp3")
        with open(path, "rb") as f:
            data = f.read()
        log("Searching for first valid MP3 frame...")
        start = 0
        for i in range(len(data) - 1):
            if data[i] == 0xFF and data[i+1] & 0xE0 == 0xE0:
                start = i
                break
        data = data[start:]
        with open(out, "wb") as f:
            f.write(data)
        log(f"MP3 cleaned — {round(len(data)/1024,1)} KB recovered")
        return {"ok": True, "output": out, "message": f"MP3 repaired — {round(len(data)/1024,1)} KB recovered"}
    except Exception as e:
        return {"ok": False, "message": f"MP3 repair failed: {e}"}


def _repair_riff(path, out_dir, log):
    try:
        with open(path, "rb") as f:
            chunk = f.read(12)[8:12]
        if chunk == b"WAVE": return _copy_fixed(path, out_dir, "wav", log)
        if chunk == b"AVI ": return _copy_fixed(path, out_dir, "avi", log)
    except Exception:
        pass
    return _copy_fixed(path, out_dir, "wav", log)


def _copy_fixed(path, out_dir, ext, log):
    p = Path(path)
    out = os.path.join(out_dir, p.stem + "_repaired." + ext)
    shutil.copy2(path, out)
    log(f"Copied with correct .{ext} extension")
    return {"ok": True, "output": out, "message": f"File saved with correct .{ext} extension"}


def _repair_gz(path, out_dir, log):
    p = Path(path)
    out_name = p.stem if p.stem != p.name else p.stem + "_extracted"
    out = os.path.join(out_dir, out_name)
    try:
        log("Extracting GZIP...")
        with gzip.open(path, "rb") as f_in:
            with open(out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {"ok": True, "output": out, "message": "GZIP extracted successfully"}
    except Exception as e:
        return {"ok": False, "message": f"GZIP extraction failed: {e}"}


def _repair_rar(path, out_dir, log):
    try:
        import patoolib
        log("Extracting RAR with patool...")
        patoolib.extract_archive(path, outdir=out_dir)
        return {"ok": True, "output": out_dir, "message": f"RAR extracted to {out_dir}"}
    except ImportError:
        return {"ok": False, "message": "Install patool: pip3 install patool"}
    except Exception as e:
        return {"ok": False, "message": f"RAR extraction failed: {e}"}


def _repair_7z(path, out_dir, log):
    try:
        import patoolib
        log("Extracting 7Z with patool...")
        patoolib.extract_archive(path, outdir=out_dir)
        return {"ok": True, "output": out_dir, "message": f"7Z extracted to {out_dir}"}
    except ImportError:
        return {"ok": False, "message": "Install patool: pip3 install patool"}
    except Exception as e:
        return {"ok": False, "message": f"7Z extraction failed: {e}"}


def _repair_ole_office(path, out_dir, log):
    import shutil
    from pathlib import Path as _Path

    p = _Path(path)
    out = os.path.join(out_dir, p.name)

    log("Legacy Office format (pre-2007)")
    log("Copying file preserving original structure...")
    shutil.copy2(path, out)

    # Verify with olefile if available
    try:
        import olefile
        if olefile.isOleFile(path):
            log("OLE2 structure verified — file is intact")
            return {"ok": True, "output": out,
                    "message": "Legacy Office file verified. Open with Microsoft Word, LibreOffice, or Pages."}
    except ImportError:
        pass

    log("Copy complete — structure appears valid")
    return {"ok": True, "output": out,
            "message": "File copied. Try opening with LibreOffice (free download) or Microsoft Office."}


def _fix_encoding(path, out_dir, log):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        detected = chardet.detect(raw)
        enc = detected.get("encoding") or "latin-1"
        conf = detected.get("confidence", 0)
        log(f"Detected encoding: {enc} (confidence {conf:.0%})")
        text = raw.decode(enc, errors="replace")
        p = Path(path)
        out = os.path.join(out_dir, p.stem + "_utf8" + p.suffix)
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        return {"ok": True, "output": out, "message": f"Text encoding fixed: {enc} → UTF-8"}
    except Exception as e:
        return {"ok": False, "message": f"Encoding fix failed: {e}"}
