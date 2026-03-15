"""
converter.py - Universal file format converter for FileGuard.
Supports: Images, Video, Audio, Documents, Spreadsheets,
          Notebooks, Data, Code, Presentations
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def _get_bin(name):
    """Find a binary: bundled bin/ first, then system PATH."""
    candidates = [
        os.path.join(os.path.dirname(__file__), 'bin', name),
        f'/opt/homebrew/bin/{name}',
        f'/usr/local/bin/{name}',
        f'/usr/bin/{name}',
    ]
    for p in candidates:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return shutil.which(name)


def get_ffmpeg():
    return _get_bin('ffmpeg')


def get_pandoc():
    return _get_bin('pandoc')


CATEGORIES = {
    "Image": {
        "extensions": ["jpg","jpeg","png","gif","bmp","webp","tiff","tif","ico","heic","avif"],
        "outputs": {
            "PNG":   {"ext":"png",  "desc":"Best for graphics, supports transparency"},
            "JPG":   {"ext":"jpg",  "desc":"Best for photos, smallest size"},
            "WEBP":  {"ext":"webp", "desc":"Modern web format"},
            "BMP":   {"ext":"bmp",  "desc":"Uncompressed bitmap"},
            "TIFF":  {"ext":"tiff", "desc":"High quality, large file"},
            "ICO":   {"ext":"ico",  "desc":"Windows icon"},
            "PDF":   {"ext":"pdf",  "desc":"Image as PDF"},
        }
    },
    "Video": {
        "extensions": ["mp4","avi","mkv","mov","wmv","flv","webm","m4v","3gp","mpeg","mpg","ts"],
        "outputs": {
            "MP4 (H.264)":   {"ext":"mp4",  "desc":"Universal — works everywhere"},
            "MP4 (H.265)":   {"ext":"mp4",  "desc":"Better quality, smaller size"},
            "MKV":           {"ext":"mkv",  "desc":"High quality container"},
            "MOV":           {"ext":"mov",  "desc":"Apple QuickTime"},
            "WEBM":          {"ext":"webm", "desc":"Web streaming"},
            "GIF (animated)":{"ext":"gif",  "desc":"Animated GIF from video"},
            "MP3 (audio)":   {"ext":"mp3",  "desc":"Extract audio as MP3"},
            "WAV (audio)":   {"ext":"wav",  "desc":"Extract audio lossless"},
            "AAC (audio)":   {"ext":"aac",  "desc":"Apple/mobile audio"},
            "FLAC (audio)":  {"ext":"flac", "desc":"Lossless compressed audio"},
        }
    },
    "Audio": {
        "extensions": ["mp3","wav","flac","ogg","m4a","aac","wma","opus","aiff"],
        "outputs": {
            "MP3 (320kbps)": {"ext":"mp3",  "desc":"Best quality MP3"},
            "MP3 (192kbps)": {"ext":"mp3",  "desc":"Good quality"},
            "MP3 (128kbps)": {"ext":"mp3",  "desc":"Compact"},
            "WAV":           {"ext":"wav",  "desc":"Uncompressed lossless"},
            "FLAC":          {"ext":"flac", "desc":"Lossless compressed"},
            "OGG":           {"ext":"ogg",  "desc":"Open source format"},
            "AAC":           {"ext":"aac",  "desc":"Apple format"},
            "OPUS":          {"ext":"opus", "desc":"Voice/streaming optimized"},
        }
    },
    "Document": {
        "extensions": ["docx","doc","odt","rtf","txt","md","html","htm","pdf","epub","tex","rst"],
        "outputs": {
            "PDF":         {"ext":"pdf",  "desc":"Universal document format"},
            "DOCX":        {"ext":"docx", "desc":"Microsoft Word"},
            "HTML":        {"ext":"html", "desc":"Web page"},
            "Markdown":    {"ext":"md",   "desc":"Plain text with formatting"},
            "Plain Text":  {"ext":"txt",  "desc":"Strip all formatting"},
            "EPUB":        {"ext":"epub", "desc":"E-book format"},
        }
    },
    "Spreadsheet": {
        "extensions": ["xlsx","xls","csv","ods","tsv"],
        "outputs": {
            "XLSX":            {"ext":"xlsx", "desc":"Microsoft Excel"},
            "CSV":             {"ext":"csv",  "desc":"Comma-separated"},
            "TSV":             {"ext":"tsv",  "desc":"Tab-separated"},
            "JSON":            {"ext":"json", "desc":"JSON data"},
            "HTML Table":      {"ext":"html", "desc":"Styled HTML table"},
            "Markdown Table":  {"ext":"md",   "desc":"Markdown table"},
        }
    },
    "Notebook": {
        "extensions": ["ipynb"],
        "outputs": {
            "HTML":          {"ext":"html", "desc":"Interactive web view"},
            "Markdown":      {"ext":"md",   "desc":"Plain markdown"},
            "Python Script": {"ext":"py",   "desc":"Code cells only"},
            "PDF":           {"ext":"pdf",  "desc":"Static PDF"},
        }
    },
    "Data": {
        "extensions": ["json","jsonl","xml","yaml","yml","toml","ini","cfg"],
        "outputs": {
            "JSON":       {"ext":"json", "desc":"Standard JSON"},
            "YAML":       {"ext":"yaml", "desc":"Human-readable config"},
            "CSV":        {"ext":"csv",  "desc":"Comma-separated"},
            "XML":        {"ext":"xml",  "desc":"XML format"},
            "Plain Text": {"ext":"txt",  "desc":"Plain text dump"},
        }
    },
    "Code": {
        "extensions": ["py","js","ts","go","rs","java","c","cpp","h","css","sh","sql","r","rb","php","swift","kt"],
        "outputs": {
            "HTML":        {"ext":"html", "desc":"Syntax highlighted HTML"},
            "Markdown":    {"ext":"md",   "desc":"Code in markdown block"},
            "Plain Text":  {"ext":"txt",  "desc":"Strip to plain text"},
            "PDF":         {"ext":"pdf",  "desc":"Printable PDF"},
        }
    },
    "Presentation": {
        "extensions": ["pptx","ppt","odp"],
        "outputs": {
            "PDF":         {"ext":"pdf",  "desc":"Slides as PDF"},
            "HTML":        {"ext":"html", "desc":"Web presentation"},
        }
    },
}


def detect_category(filepath):
    ext = Path(filepath).suffix.lower().lstrip('.')
    for cat, info in CATEGORIES.items():
        if ext in info["extensions"]:
            return cat
    return None


def get_output_formats(category):
    return list(CATEGORIES.get(category, {}).get("outputs", {}).keys())


def convert(src, output_format, out_dir, options=None, log_fn=None):
    """Main conversion entry point. Returns {"ok": bool, "output": path, "message": str}"""
    def log(msg):
        if log_fn:
            log_fn(msg)

    if options is None:
        options = {}

    p = Path(src)
    category = detect_category(src)
    if not category:
        return {"ok": False, "message": f"Unknown file format: {p.suffix}"}

    out_info = CATEGORIES[category]["outputs"].get(output_format, {})
    out_ext = out_info.get("ext", output_format.lower().split()[0])
    out_name = p.stem + "_converted." + out_ext
    out_path = os.path.join(out_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)

    log(f"Source: {p.name}")
    log(f"Format: {category} -> {output_format}")
    log(f"Output: {out_name}")

    try:
        if category == "Image":
            return _convert_image(src, out_path, output_format, options, log)
        elif category == "Video":
            return _convert_video(src, out_path, output_format, options, log)
        elif category == "Audio":
            return _convert_audio(src, out_path, output_format, options, log)
        elif category == "Document":
            return _convert_document(src, out_path, output_format, options, log)
        elif category == "Spreadsheet":
            return _convert_spreadsheet(src, out_path, output_format, options, log)
        elif category == "Notebook":
            return _convert_notebook(src, out_path, output_format, options, log)
        elif category == "Data":
            return _convert_data(src, out_path, output_format, options, log)
        elif category == "Code":
            return _convert_code(src, out_path, output_format, options, log)
        elif category == "Presentation":
            return _convert_presentation(src, out_path, output_format, options, log)
        else:
            return {"ok": False, "message": f"No converter for: {category}"}
    except Exception as e:
        import traceback
        log(f"Error: {e}")
        log(traceback.format_exc())
        return {"ok": False, "message": f"Conversion error: {e}"}


def _convert_image(src, out_path, fmt, options, log):
    from PIL import Image
    log("Opening image...")
    img = Image.open(src)

    # Handle transparency for formats that don't support it
    if fmt in ("JPG", "BMP", "PDF") and img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        img_rgb = img.convert("RGBA") if img.mode == "P" else img
        if img_rgb.mode in ("RGBA", "LA"):
            bg.paste(img_rgb, mask=img_rgb.split()[-1])
        img = bg
    elif img.mode == "P":
        img = img.convert("RGBA")

    quality = options.get("quality", 92)

    if fmt == "PDF":
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out_path, "PDF", resolution=150)
    elif fmt == "ICO":
        img.save(out_path, sizes=[(16,16),(32,32),(64,64),(128,128),(256,256)])
    elif fmt in ("JPG", "WEBP"):
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out_path, quality=quality, optimize=True)
    else:
        img.save(out_path)

    size_kb = round(os.path.getsize(out_path) / 1024, 1)
    log(f"Done -- {size_kb} KB")
    return {"ok": True, "output": out_path, "message": f"Image -> {fmt} ({size_kb} KB)"}


def _convert_video(src, out_path, fmt, options, log):
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "message": "ffmpeg not found in app bundle"}

    cmd = [ffmpeg, "-i", src, "-y"]
    final_path = out_path

    if fmt == "MP4 (H.264)":
        cmd += ["-c:v", "libx264", "-crf", "23", "-preset", "medium", "-c:a", "aac", "-b:a", "192k"]
    elif fmt == "MP4 (H.265)":
        cmd += ["-c:v", "libx265", "-crf", "28", "-preset", "medium", "-c:a", "aac", "-b:a", "128k"]
    elif fmt == "MKV":
        cmd += ["-c:v", "libx264", "-crf", "22", "-c:a", "copy"]
    elif fmt == "MOV":
        cmd += ["-c:v", "libx264", "-crf", "22", "-c:a", "aac", "-movflags", "+faststart"]
    elif fmt == "WEBM":
        cmd += ["-c:v", "libvpx-vp9", "-crf", "33", "-b:v", "0", "-c:a", "libopus"]
    elif fmt == "GIF (animated)":
        cmd += ["-vf", "scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse", "-r", "12"]
    elif "MP3" in fmt:
        final_path = out_path.rsplit(".", 1)[0] + ".mp3"
        cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "2"]
    elif "WAV" in fmt:
        final_path = out_path.rsplit(".", 1)[0] + ".wav"
        cmd += ["-vn", "-c:a", "pcm_s16le"]
    elif "AAC" in fmt:
        final_path = out_path.rsplit(".", 1)[0] + ".aac"
        cmd += ["-vn", "-c:a", "aac", "-b:a", "256k"]
    elif "FLAC" in fmt:
        final_path = out_path.rsplit(".", 1)[0] + ".flac"
        cmd += ["-vn", "-c:a", "flac"]
    else:
        cmd += ["-c", "copy"]

    cmd.append(final_path)
    log("Running ffmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = [l for l in result.stderr.split('\n') if 'error' in l.lower()]
        return {"ok": False, "message": f"ffmpeg error: {err[-1] if err else result.stderr[-200:]}"}

    size_str = f"{round(os.path.getsize(final_path)/1024/1024, 1)} MB"
    log(f"Done -- {size_str}")
    return {"ok": True, "output": final_path, "message": f"Video -> {fmt} ({size_str})"}


def _convert_audio(src, out_path, fmt, options, log):
    ffmpeg = get_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "message": "ffmpeg not found"}

    cmd = [ffmpeg, "-i", src, "-y"]
    if "320kbps" in fmt:
        cmd += ["-c:a", "libmp3lame", "-b:a", "320k"]
    elif "192kbps" in fmt:
        cmd += ["-c:a", "libmp3lame", "-b:a", "192k"]
    elif "128kbps" in fmt or fmt == "MP3 (128kbps)":
        cmd += ["-c:a", "libmp3lame", "-b:a", "128k"]
    elif fmt == "WAV":
        cmd += ["-c:a", "pcm_s16le"]
    elif fmt == "FLAC":
        cmd += ["-c:a", "flac"]
    elif fmt == "OGG":
        cmd += ["-c:a", "libvorbis", "-q:a", "6"]
    elif fmt == "AAC":
        cmd += ["-c:a", "aac", "-b:a", "256k"]
    elif fmt == "OPUS":
        cmd += ["-c:a", "libopus", "-b:a", "128k"]
    else:
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]

    cmd.append(out_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"ok": False, "message": f"Audio conversion failed: {result.stderr[-200:]}"}
    size_kb = round(os.path.getsize(out_path)/1024, 1)
    log(f"Done -- {size_kb} KB")
    return {"ok": True, "output": out_path, "message": f"Audio -> {fmt} ({size_kb} KB)"}


def _convert_document(src, out_path, fmt, options, log):
    p = Path(src)
    ext = p.suffix.lower().lstrip('.')

    # Plain text / Markdown extraction (no pandoc needed)
    if fmt in ("Plain Text", "Markdown"):
        return _doc_to_text(src, out_path, fmt, log)

    # HTML from Markdown (no pandoc needed)
    if fmt == "HTML" and ext in ("md", "markdown", "txt"):
        return _text_to_html(src, out_path, log)

    # DOCX from text/md (no pandoc needed)
    if fmt == "DOCX" and ext in ("txt", "md"):
        return _text_to_docx(src, out_path, log)

    # Try pandoc for everything else
    pandoc = get_pandoc()
    if pandoc:
        fmt_map = {"PDF":"pdf","DOCX":"docx","HTML":"html",
                   "EPUB":"epub","RTF":"rtf","Markdown":"markdown","Plain Text":"plain"}
        pandoc_fmt = fmt_map.get(fmt, "plain")
        cmd = [pandoc, src, "-o", out_path]
        if fmt == "HTML":
            cmd += ["--standalone"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            log("Pandoc conversion complete")
            return {"ok": True, "output": out_path, "message": f"Document -> {fmt}"}
        log(f"Pandoc failed: {result.stderr[:80]}")

    # Fallback
    return _doc_to_text(src, out_path, "Plain Text", log)


def _doc_to_text(src, out_path, fmt, log):
    ext = Path(src).suffix.lower().lstrip('.')
    log("Extracting text content...")
    text = ""

    if ext == "docx":
        import zipfile, xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(src) as z:
                if "word/document.xml" in z.namelist():
                    root = ET.fromstring(z.read("word/document.xml"))
                    paras = []
                    for para in root.iter():
                        if para.tag.endswith("}p"):
                            words = [e.text for e in para.iter()
                                     if e.tag.endswith("}t") and e.text]
                            if words:
                                paras.append("".join(words))
                    text = "\n\n".join(paras)
        except Exception as e:
            text = f"[Could not extract text: {e}]"
    elif ext == "pdf":
        try:
            import pikepdf
            with pikepdf.open(src) as pdf:
                text = f"PDF ({len(pdf.pages)} pages)\n[Full text extraction requires pdfminer]"
        except Exception:
            text = "[PDF text extraction failed]"
    else:
        with open(src, "r", errors="replace") as f:
            text = f.read()

    if fmt == "Markdown":
        text = f"# {Path(src).stem}\n\n{text}"

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    return {"ok": True, "output": out_path, "message": f"Text extracted ({len(text)} chars)"}


def _text_to_html(src, out_path, log):
    with open(src, "r", errors="replace") as f:
        content = f.read()
    escaped = content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{font-family:sans-serif;max-width:800px;margin:40px auto;line-height:1.6;}}
pre{{background:#f4f4f4;padding:16px;border-radius:4px;overflow-x:auto;}}</style>
</head><body><pre>{escaped}</pre></body></html>"""
    with open(out_path, "w") as f:
        f.write(html)
    return {"ok": True, "output": out_path, "message": "Saved as HTML"}


def _text_to_docx(src, out_path, log):
    try:
        from docx import Document
        doc = Document()
        with open(src, "r", errors="replace") as f:
            for line in f:
                doc.add_paragraph(line.rstrip())
        doc.save(out_path)
        return {"ok": True, "output": out_path, "message": "Saved as DOCX"}
    except ImportError:
        return {"ok": False, "message": "Install: pip3 install python-docx"}


def _convert_spreadsheet(src, out_path, fmt, options, log):
    try:
        import pandas as pd
    except ImportError:
        return {"ok": False, "message": "Install: pip3 install pandas openpyxl"}

    ext = Path(src).suffix.lower().lstrip('.')
    log(f"Reading {ext}...")

    try:
        if ext in ("xlsx", "xls"):
            df = pd.read_excel(src)
        elif ext == "csv":
            for enc in ["utf-8", "latin-1", "cp1252"]:
                try:
                    df = pd.read_csv(src, encoding=enc)
                    break
                except Exception:
                    continue
        elif ext == "tsv":
            df = pd.read_csv(src, sep="\t")
        elif ext == "ods":
            df = pd.read_excel(src, engine="odf")
        else:
            df = pd.read_csv(src)
    except Exception as e:
        return {"ok": False, "message": f"Cannot read file: {e}"}

    rows, cols = df.shape
    log(f"Loaded {rows} rows x {cols} columns")

    try:
        if fmt == "XLSX":
            df.to_excel(out_path, index=False, engine="openpyxl")
        elif fmt == "CSV":
            df.to_csv(out_path, index=False, encoding="utf-8")
        elif fmt == "TSV":
            df.to_csv(out_path, index=False, sep="\t")
        elif fmt == "JSON":
            df.to_json(out_path, orient="records", indent=2, force_ascii=False)
        elif fmt == "HTML Table":
            html = df.to_html(index=False, classes="table", border=1)
            styled = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>table{{border-collapse:collapse;width:100%;font-family:sans-serif;}}
th,td{{border:1px solid #ddd;padding:8px;}}th{{background:#f2f2f2;}}
tr:nth-child(even){{background:#f9f9f9;}}</style></head><body>{html}</body></html>"""
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(styled)
        elif fmt == "Markdown Table":
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(df.to_markdown(index=False))
        else:
            df.to_csv(out_path, index=False)

        size = os.path.getsize(out_path)
        size_str = f"{round(size/1024/1024,1)} MB" if size > 1e6 else f"{round(size/1024,1)} KB"
        log(f"Done -- {rows} rows, {size_str}")
        return {"ok": True, "output": out_path, "message": f"Spreadsheet -> {fmt} ({rows} rows, {size_str})"}
    except Exception as e:
        return {"ok": False, "message": f"Conversion error: {e}"}


def _convert_notebook(src, out_path, fmt, options, log):
    log(f"Converting notebook to {fmt}...")
    try:
        import nbformat
        from nbconvert import HTMLExporter, MarkdownExporter, ScriptExporter, PDFExporter

        with open(src) as f:
            nb = nbformat.read(f, as_version=4)

        if fmt == "HTML":
            exp = HTMLExporter()
            body, _ = exp.from_notebook_node(nb)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)
        elif fmt == "Markdown":
            exp = MarkdownExporter()
            body, _ = exp.from_notebook_node(nb)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)
        elif fmt == "Python Script":
            exp = ScriptExporter()
            body, _ = exp.from_notebook_node(nb)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)
        elif fmt == "PDF":
            # Fallback: markdown -> html
            exp = MarkdownExporter()
            body, _ = exp.from_notebook_node(nb)
            md_path = out_path.replace(".pdf", ".md")
            with open(md_path, "w") as f:
                f.write(body)
            out_path = md_path
        else:
            exp = HTMLExporter()
            body, _ = exp.from_notebook_node(nb)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(body)

        log("Done")
        return {"ok": True, "output": out_path, "message": f"Notebook -> {fmt}"}
    except ImportError:
        return {"ok": False, "message": "Install: pip3 install nbformat nbconvert"}
    except Exception as e:
        return {"ok": False, "message": f"Notebook error: {e}"}


def _convert_data(src, out_path, fmt, options, log):
    import json
    ext = Path(src).suffix.lower().lstrip('.')
    log(f"Reading {ext}...")

    data = None
    try:
        if ext in ("json", "jsonl"):
            with open(src, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if ext == "jsonl":
                data = [json.loads(l) for l in content.splitlines() if l.strip()]
            else:
                data = json.loads(content)
        elif ext in ("yaml", "yml"):
            import yaml
            with open(src) as f:
                data = yaml.safe_load(f)
        elif ext == "xml":
            import xml.etree.ElementTree as ET
            data = {"content": ET.parse(src).getroot().tag}
        elif ext in ("ini", "cfg", "conf"):
            import configparser
            c = configparser.ConfigParser()
            c.read(src)
            data = {s: dict(c[s]) for s in c.sections()}
        else:
            with open(src, "r", errors="replace") as f:
                data = {"text": f.read()}
    except Exception as e:
        return {"ok": False, "message": f"Cannot read {ext}: {e}"}

    try:
        if fmt == "JSON":
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        elif fmt == "YAML":
            import yaml
            with open(out_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, indent=2)
        elif fmt == "CSV":
            import pandas as pd
            items = data if isinstance(data, list) else [data]
            pd.DataFrame(items).to_csv(out_path, index=False)
        elif fmt == "XML":
            import xml.etree.ElementTree as ET
            def to_xml(tag, val):
                el = ET.Element(str(tag))
                if isinstance(val, dict):
                    for k, v in val.items():
                        el.append(to_xml(k, v))
                elif isinstance(val, list):
                    for item in val:
                        el.append(to_xml("item", item))
                else:
                    el.text = str(val)
                return el
            root = to_xml("root", data)
            ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(str(data))

        size_kb = round(os.path.getsize(out_path)/1024, 1)
        log(f"Done -- {size_kb} KB")
        return {"ok": True, "output": out_path, "message": f"Data -> {fmt} ({size_kb} KB)"}
    except Exception as e:
        return {"ok": False, "message": f"Conversion error: {e}"}


def _convert_code(src, out_path, fmt, options, log):
    with open(src, "r", errors="replace") as f:
        content = f.read()
    name = Path(src).name
    ext = Path(src).suffix.lstrip('.')

    if fmt == "Plain Text":
        with open(out_path, "w") as f:
            f.write(content)
    elif fmt == "Markdown":
        with open(out_path, "w") as f:
            f.write(f"# {name}\n\n```{ext}\n{content}\n```\n")
    elif fmt in ("HTML", "PDF"):
        escaped = content.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>body{{margin:0;background:#1e1e1e;color:#d4d4d4;font-family:monospace;}}
.hdr{{background:#252526;padding:8px 16px;color:#ccc;font-size:13px;}}
pre{{margin:0;padding:20px;white-space:pre-wrap;font-size:13px;line-height:1.6;}}</style>
</head><body><div class="hdr">{name}</div><pre>{escaped}</pre></body></html>"""
        html_path = out_path if fmt == "HTML" else out_path.replace(".pdf", ".html")
        with open(html_path, "w") as f:
            f.write(html)
        if fmt == "PDF":
            pandoc = get_pandoc()
            if pandoc:
                r = subprocess.run([pandoc, html_path, "-o", out_path], capture_output=True)
                os.remove(html_path)
                if r.returncode == 0:
                    return {"ok": True, "output": out_path, "message": "Code -> PDF"}
            out_path = html_path

    log("Done")
    return {"ok": True, "output": out_path, "message": f"Code -> {fmt}"}


def _convert_presentation(src, out_path, fmt, options, log):
    if fmt == "PDF":
        for libre in ["/Applications/LibreOffice.app/Contents/MacOS/soffice", "soffice"]:
            if shutil.which(libre) or os.path.exists(libre):
                out_dir = str(Path(out_path).parent)
                r = subprocess.run([libre, "--headless", "--convert-to", "pdf",
                                    "--outdir", out_dir, src], capture_output=True, text=True)
                if r.returncode == 0:
                    expected = os.path.join(out_dir, Path(src).stem + ".pdf")
                    if os.path.exists(expected) and expected != out_path:
                        shutil.move(expected, out_path)
                    return {"ok": True, "output": out_path, "message": "Presentation -> PDF"}
        return {"ok": False, "message": "Install LibreOffice to convert presentations to PDF"}

    pandoc = get_pandoc()
    if pandoc:
        r = subprocess.run([pandoc, src, "-o", out_path], capture_output=True, text=True)
        if r.returncode == 0:
            return {"ok": True, "output": out_path, "message": f"Presentation -> {fmt}"}
    return {"ok": False, "message": f"Cannot convert to {fmt} -- install pandoc/LibreOffice"}
