"""
fileguard_features.py - Feature implementations for new tabs.
"""

import os
import sys

# Fix pyzbar dylib path on Mac M1/M2
os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')

import re
import json
import hashlib
import difflib
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ── Image metadata ─────────────────────────────────────────────────────────

def get_all_metadata(path):
    """Return dict of all metadata for a file."""
    meta = {}
    try:
        stat = os.stat(path)
        meta['Created']  = datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M')
        meta['Modified'] = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
        meta['Size']     = f"{stat.st_size:,} bytes"
    except Exception:
        pass

    ext = Path(path).suffix.lower()
    if ext in ('.jpg', '.jpeg', '.png', '.tiff', '.heic', '.bmp'):
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS, GPSTAGS
            img = Image.open(path)
            raw_exif = img._getexif() or {}
            for tag_id, val in raw_exif.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag == 'GPSInfo':
                    gps = {GPSTAGS.get(k, k): v for k, v in val.items()}
                    meta['GPS'] = gps
                    # Try to extract lat/lon
                    try:
                        lat  = _dms_to_decimal(gps.get('GPSLatitude'),  gps.get('GPSLatitudeRef',  'N'))
                        lon  = _dms_to_decimal(gps.get('GPSLongitude'), gps.get('GPSLongitudeRef', 'E'))
                        meta['GPS_Decimal'] = f"lat {lat:.4f}, lon {lon:.4f}"
                    except Exception:
                        pass
                else:
                    meta[str(tag)] = str(val)[:200]
        except Exception:
            pass
    return meta


def _dms_to_decimal(dms, ref):
    if dms is None:
        return 0.0
    d, m, s = [float(x.numerator) / float(x.denominator) if hasattr(x, 'numerator') else float(x) for x in dms]
    decimal = d + m / 60 + s / 3600
    if ref in ('S', 'W'):
        decimal = -decimal
    return decimal


# ── Image EXIF strip ───────────────────────────────────────────────────────

def strip_exif(src_path, out_dir):
    """Strip all EXIF from image and save clean copy."""
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    os.makedirs(out_dir, exist_ok=True)

    found = []
    try:
        img = Image.open(src_path)
        raw_exif = img._getexif() or {}
        for tag_id, val in raw_exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == 'GPSInfo':
                found.append("GPS LOCATION — your physical location")
            elif tag == 'Make':
                found.append(f"Camera make: {val}")
            elif tag == 'Model':
                found.append(f"Device: {val}")
            elif tag == 'DateTime':
                found.append(f"Date taken: {val}")
            elif tag == 'Software':
                found.append(f"Software: {val}")
            elif tag == 'Artist':
                found.append(f"Artist: {val}")
            elif tag == 'Copyright':
                found.append(f"Copyright: {val}")
    except Exception:
        pass

    # Strip: create new image without metadata
    try:
        img = Image.open(src_path)
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))
        out = os.path.join(out_dir, Path(src_path).name)
        p = Path(src_path)
        fmt_map = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG',
                   '.bmp': 'BMP', '.tiff': 'TIFF', '.webp': 'WEBP'}
        fmt = fmt_map.get(p.suffix.lower(), 'PNG')
        save_kwargs = {'quality': 95} if fmt == 'JPEG' else {}
        clean.save(out, fmt, **save_kwargs)
        return {"found": found, "output": out, "cleaned": len(found) > 0, "ok": True}
    except Exception as e:
        return {"found": found, "output": None, "cleaned": False, "ok": False, "error": str(e)}


def strip_exif_folder(folder, out_dir, on_progress=None):
    """Strip EXIF from all images in folder."""
    image_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
    files = [f for f in Path(folder).rglob('*')
             if f.is_file() and f.suffix.lower() in image_exts]
    cleaned = 0
    gps_found = 0
    for i, f in enumerate(files):
        if on_progress:
            on_progress(i + 1, len(files), str(f))
        r = strip_exif(str(f), out_dir)
        if r['ok']:
            cleaned += 1
            if any('GPS' in item for item in r['found']):
                gps_found += 1
    return {'total': len(files), 'cleaned': cleaned, 'gps_found': gps_found, 'out_dir': out_dir}


# ── OCR ───────────────────────────────────────────────────────────────────

def ocr_image(image_path, language='eng'):
    """Extract text from image using Tesseract."""
    import pytesseract
    from PIL import Image
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang=language)
    return text.strip()


def check_tesseract():
    """Return True if tesseract is installed."""
    try:
        r = subprocess.run(['tesseract', '--version'],
                           capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


# ── Duplicate finder ──────────────────────────────────────────────────────

def find_duplicates(folder, file_filter=None, on_progress=None):
    """Find duplicate files by SHA-256 hash."""
    all_files = [f for f in Path(folder).rglob('*') if f.is_file()]
    if file_filter and file_filter != 'All files':
        ext_map = {
            'Images':    {'.jpg','.jpeg','.png','.gif','.bmp','.webp','.tiff'},
            'Videos':    {'.mp4','.avi','.mkv','.mov','.wmv','.flv'},
            'Documents': {'.pdf','.docx','.doc','.xlsx','.pptx','.txt'},
        }
        exts = ext_map.get(file_filter, set())
        all_files = [f for f in all_files if f.suffix.lower() in exts]

    # Pre-group by size
    by_size = defaultdict(list)
    for f in all_files:
        try:
            by_size[f.stat().st_size].append(f)
        except Exception:
            pass

    candidates = [f for files in by_size.values() if len(files) > 1 for f in files]

    by_hash = defaultdict(list)
    for i, f in enumerate(candidates):
        if on_progress:
            on_progress(i + 1, len(candidates), str(f))
        try:
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            by_hash[h].append(f)
        except Exception:
            pass

    return {h: files for h, files in by_hash.items() if len(files) > 1}


# ── Batch renamer ──────────────────────────────────────────────────────────

def apply_rename_pattern(filename, index, pattern):
    """Apply pattern to generate new filename."""
    p = Path(filename)
    date_str = datetime.now().strftime('%Y-%m-%d')
    result = pattern
    result = result.replace('{name}',        p.stem)
    result = result.replace('{ext}',         p.suffix.lstrip('.'))
    result = result.replace('{date}',        date_str)
    result = result.replace('{number:04d}',  f"{index+1:04d}")
    result = result.replace('{number:03d}',  f"{index+1:03d}")
    result = result.replace('{number:02d}',  f"{index+1:02d}")
    result = result.replace('{number}',      str(index + 1))
    # Keep extension if not in pattern
    if '{ext}' not in pattern and not result.endswith(p.suffix):
        result = result + p.suffix
    return result


def preview_rename(folder, file_filter, pattern):
    """Return list of (old_name, new_name) tuples."""
    import fnmatch
    files = sorted([f.name for f in Path(folder).iterdir() if f.is_file()])
    if file_filter and file_filter != '*':
        files = [f for f in files if fnmatch.fnmatch(f.lower(), file_filter.lower())]
    return [(f, apply_rename_pattern(f, i, pattern)) for i, f in enumerate(files)]


def do_rename(folder, file_filter, pattern, undo_file=None):
    """Rename files according to pattern. Returns count renamed."""
    import fnmatch
    pairs = preview_rename(folder, file_filter, pattern)
    undo_map = {}
    count = 0
    for old_name, new_name in pairs:
        old_path = os.path.join(folder, old_name)
        new_path = os.path.join(folder, new_name)
        if old_path == new_path:
            continue
        try:
            os.rename(old_path, new_path)
            undo_map[new_path] = old_path
            count += 1
        except Exception:
            pass
    if undo_file and undo_map:
        try:
            with open(undo_file, 'w') as f:
                json.dump(undo_map, f, indent=2)
        except Exception:
            pass
    return count


def undo_rename(undo_file):
    """Reverse the last rename operation."""
    try:
        with open(undo_file) as f:
            undo_map = json.load(f)
        count = 0
        for new_path, old_path in undo_map.items():
            try:
                if os.path.exists(new_path):
                    os.rename(new_path, old_path)
                    count += 1
            except Exception:
                pass
        return count
    except Exception as e:
        return 0


# ── Hash verifier ──────────────────────────────────────────────────────────

def verify_hash(filepath, expected):
    """Return True if SHA-256 of file matches expected."""
    try:
        actual = hashlib.sha256(open(filepath, 'rb').read()).hexdigest()
        return actual.lower().strip() == expected.lower().strip(), actual
    except Exception as e:
        return False, str(e)


# ── Smart unarchiver ───────────────────────────────────────────────────────

def extract_any(filepath, out_dir):
    """Extract any archive using patoolib."""
    import patoolib
    os.makedirs(out_dir, exist_ok=True)
    patoolib.extract_archive(filepath, outdir=out_dir)
    return out_dir


# ── QR Code reader ────────────────────────────────────────────────────────

def read_qr(image_path):
    """Read QR codes from image. Returns list of decoded strings."""
    try:
        from pyzbar.pyzbar import decode
        from PIL import Image
        results = decode(Image.open(image_path))
        return [r.data.decode('utf-8') for r in results]
    except ImportError:
        return ["pyzbar not installed — run: pip3 install pyzbar"]
    except Exception as e:
        return [f"Error: {e}"]


# ── File splitter/joiner ───────────────────────────────────────────────────

def split_file(filepath, chunk_mb, on_progress=None):
    """Split file into .part000, .part001, ... chunks."""
    chunk = chunk_mb * 1024 * 1024
    total = os.path.getsize(filepath)
    parts = 0
    with open(filepath, 'rb') as f:
        i = 0
        written = 0
        while True:
            data = f.read(chunk)
            if not data:
                break
            part = f"{filepath}.part{i:03d}"
            with open(part, 'wb') as pf:
                pf.write(data)
            written += len(data)
            if on_progress:
                on_progress(written, total, part)
            i += 1
            parts = i
    return parts


def join_files(first_part, on_progress=None):
    """Join .part000, .part001, ... back into original file."""
    base = str(first_part)
    if base.endswith('.part000'):
        base = base[:-8]
    elif '.part' in base:
        base = base[:base.rfind('.part')]
    parts = sorted(Path(first_part).parent.glob(Path(base).name + '.part*'))
    total_size = sum(p.stat().st_size for p in parts)
    written = 0
    with open(base, 'wb') as out:
        for part in parts:
            data = part.read_bytes()
            out.write(data)
            written += len(data)
            if on_progress:
                on_progress(written, total_size, str(part))
    return base


# ── Disk analyzer ─────────────────────────────────────────────────────────

def get_folder_sizes(root, depth=1):
    """Return top-10 subfolders by size as list of (name, bytes)."""
    sizes = {}
    try:
        for item in os.scandir(root):
            if item.is_dir() and not item.name.startswith('.'):
                try:
                    total = sum(
                        f.stat().st_size
                        for f in Path(item.path).rglob('*')
                        if f.is_file()
                    )
                    sizes[item.name] = total
                except Exception:
                    pass
    except Exception:
        pass
    return sorted(sizes.items(), key=lambda x: -x[1])[:10]


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ── File diff ────────────────────────────────────────────────────────────

def diff_text_files(file_a, file_b):
    """Return list of diff lines for two text files."""
    try:
        lines_a = open(file_a, 'r', errors='replace').readlines()
        lines_b = open(file_b, 'r', errors='replace').readlines()
        return list(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=os.path.basename(file_a),
            tofile=os.path.basename(file_b)
        ))
    except Exception as e:
        return [f"Error: {e}\n"]


def diff_binary_files(file_a, file_b, max_bytes=4096):
    """Return summary of differences for binary files."""
    try:
        data_a = open(file_a, 'rb').read(max_bytes)
        data_b = open(file_b, 'rb').read(max_bytes)
        diffs = [(i, data_a[i], data_b[i])
                 for i in range(min(len(data_a), len(data_b)))
                 if data_a[i] != data_b[i]]
        lines = [f"Binary files differ at {len(diffs)} byte positions (first {max_bytes} bytes)\n"]
        for i, a, b in diffs[:20]:
            lines.append(f"  Offset {i:04x}: {a:02x} → {b:02x}\n")
        if len(diffs) > 20:
            lines.append(f"  ... and {len(diffs)-20} more differences\n")
        return lines
    except Exception as e:
        return [f"Error: {e}\n"]


# ── Image converter ───────────────────────────────────────────────────────

def convert_image(src, dst_format, quality=85, out_dir=None):
    """Convert image to another format using Pillow."""
    from PIL import Image
    img = Image.open(src)
    dst_fmt_upper = dst_format.upper()
    if dst_fmt_upper == 'JPG':
        dst_fmt_upper = 'JPEG'
    if img.mode in ('RGBA', 'LA', 'P') and dst_fmt_upper == 'JPEG':
        img = img.convert('RGB')
    ext = dst_format.lower()
    if ext == 'jpg':
        ext = 'jpg'
    if out_dir:
        out = os.path.join(out_dir, Path(src).stem + '.' + ext)
    else:
        out = str(Path(src).parent / (Path(src).stem + '.' + ext))
    save_kwargs = {}
    if dst_fmt_upper == 'JPEG':
        save_kwargs['quality'] = quality
    img.save(out, dst_fmt_upper, **save_kwargs)
    return out


def convert_media(src, dst_format, out_dir=None):
    """Convert audio or video using ffmpeg."""
    ext = dst_format.lower()
    if out_dir:
        out = os.path.join(out_dir, Path(src).stem + '.' + ext)
    else:
        out = str(Path(src).parent / (Path(src).stem + '.' + ext))
    result = subprocess.run(
        ['ffmpeg', '-i', src, '-y', out],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-500:] if result.stderr else 'ffmpeg failed')
    return out


def get_media_info(path):
    """Get media metadata via ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', path],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        info = {}
        fmt = data.get('format', {})
        info['Duration'] = _fmt_duration(float(fmt.get('duration', 0)))
        info['Format']   = fmt.get('format_long_name', fmt.get('format_name', 'Unknown'))
        info['Bitrate']  = f"{int(fmt.get('bit_rate',0))//1000} kbps" if fmt.get('bit_rate') else ''
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                info['Video codec'] = stream.get('codec_name', '')
                info['Resolution']  = f"{stream.get('width','?')}x{stream.get('height','?')}"
                info['FPS']         = stream.get('r_frame_rate', '')
            elif stream.get('codec_type') == 'audio':
                info['Audio codec']   = stream.get('codec_name', '')
                info['Sample rate']   = f"{stream.get('sample_rate','')} Hz"
                info['Channels']      = str(stream.get('channels', ''))
        return {k: v for k, v in info.items() if v}
    except Exception:
        return {}


def _fmt_duration(seconds):
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
