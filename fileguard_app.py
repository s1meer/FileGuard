"""
fileguard_app.py - FileGuard Desktop Application
Real working GUI for Mac M1 using Python Tkinter + tkinterdnd2.
Tabs: SCAN | REPAIR | DOWNLOAD | INFO
Features: drag-drop repair, auto-diagnose, unknown format reporting, auto-update
"""

import os
import sys
import ssl
import platform
import subprocess
import threading
import queue
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

# Fix SSL verification on Mac (certificate issue)
os.environ['PYTHONHTTPSVERIFY'] = '0'
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

import ssl as _ssl_mod
import os as _os_mod
_os_mod.environ['PYTHONHTTPSVERIFY'] = '0'
try:
    _ssl_mod._create_default_https_context = _ssl_mod._create_unverified_context
except AttributeError:
    pass

# Try tkinterdnd2 for drag and drop — fallback gracefully if not installed
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scanner import scan_file, scan_directory
from recovery import repair_file
from reporter import check_and_report
from updater import check_and_update_in_background, download_and_install, get_current_version
from fileguard_features import (
    get_all_metadata, strip_exif, strip_exif_folder,
    ocr_image, check_tesseract,
    find_duplicates, preview_rename, do_rename, undo_rename,
    verify_hash, extract_any, read_qr,
    split_file, join_files,
    get_folder_sizes, human_size,
    diff_text_files, diff_binary_files,
    convert_image, convert_media, get_media_info,
)
from binaries import get_ffmpeg, get_yt_dlp, get_tesseract, get_tessdata

# ── Colors and fonts ──────────────────────────────────────
BG       = "#ffffff"
BG2      = "#f5f5f5"
BORDER   = "#dddddd"
TEXT     = "#1a1a1a"
MUTED    = "#666666"
GREEN    = "#2d7a2d"
YELLOW   = "#b8860b"
RED      = "#cc2200"
BLUE     = "#1a5fa8"
FONT     = ("Helvetica", 13)
FONT_SM  = ("Helvetica", 12)
FONT_B   = ("Helvetica", 13, "bold")
FONT_LG  = ("Helvetica", 15, "bold")

RISK_COLORS = {
    "critical": RED,
    "high":     RED,
    "medium":   YELLOW,
    "low":      "#888800",
    "safe":     GREEN,
}

RISK_BG = {
    "critical": "#fff0f0",
    "high":     "#fff0f0",
    "medium":   "#fffbee",
    "low":      "#f8f8e8",
    "safe":     "#f0fff0",
}

RISK_LABELS = {
    "critical": "CRITICAL",
    "high":     "HIGH RISK",
    "medium":   "MEDIUM",
    "low":      "LOW",
    "safe":     "SAFE",
}


class FileGuardApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FileGuard")
        self.root.geometry("1150x740")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(950, 620)

        self.q = queue.Queue()
        self.scan_running = False
        self.download_running = False
        self.scan_results = []
        self._pending_update_url = None
        self.repaired_output = None
        self.dl_output_path = None
        self.dl_process = None
        self._conv_output = None
        self._dup_groups = {}
        self.rename_previewed = False
        self._rename_undo_file = os.path.join(Path.home(), ".fileguard_rename_undo.json")
        self._downloads_scanned_today = 0

        self._build_update_banner()
        self._build_header()
        self._build_tabs()
        self._build_status_bar()
        self._poll_queue()
        self._start_downloads_watcher()

        # Start background update check
        check_and_update_in_background(on_update_available=self._on_update_found)

    def _build_update_banner(self):
        self.update_banner = tk.Frame(self.root, bg="#fff9e6")
        self.update_label = tk.Label(self.update_banner, text="", font=FONT_SM,
                                      bg="#fff9e6", fg="#8a6000")
        self.update_label.pack(side="left", padx=16, pady=6)
        self.update_btn = tk.Button(self.update_banner, text="Update Now", font=FONT_B,
                                     bg=YELLOW, fg="white", relief="flat", padx=10, cursor="hand2")
        self.update_btn.pack(side="right", padx=16, pady=6)
        # Banner stays hidden until update found

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=BG, pady=12)
        hdr.pack(fill="x", padx=24)
        tk.Label(hdr, text="FileGuard", font=("Helvetica", 20, "bold"),
                 bg=BG, fg=TEXT).pack(side="left")
        tk.Label(hdr, text="  Scan · Repair · Download",
                 font=FONT_SM, bg=BG, fg=MUTED).pack(side="left", pady=6)
        tk.Label(hdr, text=f"v{get_current_version()}", font=FONT_SM,
                 bg=BG, fg=MUTED).pack(side="right")

    def _build_tabs(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=16, pady=(0, 4))

        style = ttk.Style()
        style.configure("TNotebook.Tab", font=FONT_B, padding=[12, 7])

        self.tab_scan      = tk.Frame(nb, bg=BG)
        self.tab_repair    = tk.Frame(nb, bg=BG)
        self.tab_download  = tk.Frame(nb, bg=BG)
        self.tab_info      = tk.Frame(nb, bg=BG)
        self.tab_preview   = tk.Frame(nb, bg=BG)
        self.tab_convert   = tk.Frame(nb, bg=BG)
        self.tab_privacy   = tk.Frame(nb, bg=BG)
        self.tab_ocr       = tk.Frame(nb, bg=BG)
        self.tab_duplicates= tk.Frame(nb, bg=BG)
        self.tab_rename    = tk.Frame(nb, bg=BG)
        self.tab_tools     = tk.Frame(nb, bg=BG)

        nb.add(self.tab_scan,       text="Scan")
        nb.add(self.tab_repair,     text="Repair")
        nb.add(self.tab_download,   text="Download")
        nb.add(self.tab_info,       text="Info")
        nb.add(self.tab_preview,    text="Preview")
        nb.add(self.tab_convert,    text="Convert")
        nb.add(self.tab_privacy,    text="Privacy")
        nb.add(self.tab_ocr,        text="OCR")
        nb.add(self.tab_duplicates, text="Dupes")
        nb.add(self.tab_rename,     text="Rename")
        nb.add(self.tab_tools,      text="Tools")

        self._build_scan_tab()
        self._build_repair_tab()
        self._build_download_tab()
        self._build_info_tab()
        self._build_preview_tab()
        self._build_convert_tab()
        self._build_privacy_tab()
        self._build_ocr_tab()
        self._build_duplicates_tab()
        self._build_rename_tab()
        self._build_tools_tab()

    # ── SCAN TAB ──────────────────────────────────────────

    def _build_scan_tab(self):
        f = self.tab_scan
        pad = {"padx": 20, "pady": 8}

        top = tk.Frame(f, bg=BG)
        top.pack(fill="x", **pad)

        tk.Label(top, text="Folder to scan:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w")
        row = tk.Frame(top, bg=BG)
        row.pack(fill="x", pady=4)

        self.scan_path = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Entry(row, textvariable=self.scan_path, font=FONT, width=55,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_scan_folder,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        self.scan_btn = tk.Button(row, text="Scan Now", font=FONT_B, bg=BLUE, fg="white",
                                  command=self._start_scan, relief="flat", padx=14, cursor="hand2")
        self.scan_btn.pack(side="left", padx=(8,0))

        prog_frame = tk.Frame(f, bg=BG)
        prog_frame.pack(fill="x", padx=20, pady=(0,4))
        self.scan_progress = ttk.Progressbar(prog_frame, mode="determinate", length=400)
        self.scan_progress.pack(fill="x")
        self.scan_status = tk.Label(prog_frame, text="", font=FONT_SM, bg=BG, fg=MUTED)
        self.scan_status.pack(anchor="w", pady=2)

        self.scan_summary = tk.Label(f, text="", font=FONT_SM, bg=BG2,
                                     relief="flat", padx=16, pady=8, anchor="w")
        self.scan_summary.pack(fill="x", padx=20, pady=(0,6))

        list_frame = tk.Frame(f, bg=BG, relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0,4))

        cols = ("verdict", "risk", "name", "size", "type")
        self.scan_tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                       selectmode="browse", height=12)
        self.scan_tree.heading("verdict", text="Safe?")
        self.scan_tree.heading("risk",    text="Risk")
        self.scan_tree.heading("name",    text="File Name")
        self.scan_tree.heading("size",    text="Size")
        self.scan_tree.heading("type",    text="Type")
        self.scan_tree.column("verdict", width=70,  anchor="center")
        self.scan_tree.column("risk",    width=95,  anchor="center")
        self.scan_tree.column("name",    width=330)
        self.scan_tree.column("size",    width=75,  anchor="e")
        self.scan_tree.column("type",    width=75,  anchor="center")

        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.scan_tree.pack(fill="both", expand=True)
        self.scan_tree.bind("<<TreeviewSelect>>", self._on_scan_select)

        self.scan_detail = tk.Text(f, font=FONT_SM, height=5, bg=BG2,
                                    relief="solid", bd=1, state="disabled",
                                    padx=10, pady=8, wrap="word")
        self.scan_detail.pack(fill="x", padx=20, pady=(0,4))

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,8))
        tk.Button(btn_row, text="Export Report", font=FONT, command=self._export_scan_report,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="Clear", font=FONT, command=self._clear_scan,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=8)

        self.scan_tree.tag_configure("critical", foreground=RED,    background="#fff0f0")
        self.scan_tree.tag_configure("high",     foreground=RED,    background="#fff0f0")
        self.scan_tree.tag_configure("medium",   foreground=YELLOW, background="#fffbee")
        self.scan_tree.tag_configure("low",      foreground="#888800", background="#f8f8e8")
        self.scan_tree.tag_configure("safe",     foreground=GREEN,  background="#f0fff0")
        self.scan_tree.tag_configure("verdict_yes",     foreground="#2d7a2d")
        self.scan_tree.tag_configure("verdict_no",      foreground="#cc2200")
        self.scan_tree.tag_configure("verdict_caution", foreground="#b8860b")

    def _browse_scan_folder(self):
        d = filedialog.askdirectory(title="Select folder to scan",
                                    initialdir=self.scan_path.get())
        if d:
            self.scan_path.set(d)

    def _start_scan(self):
        path = self.scan_path.get().strip()
        if not os.path.isdir(path):
            messagebox.showerror("Not found", f"Folder not found:\n{path}")
            return
        if self.scan_running:
            return
        self.scan_running = True
        self.scan_btn.config(text="Scanning...", state="disabled")
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_results = []
        self.scan_detail.config(state="normal")
        self.scan_detail.delete("1.0", "end")
        self.scan_detail.config(state="disabled")
        self.scan_summary.config(text="Scanning...")
        self.scan_progress["value"] = 0

        def run():
            def progress(done, total, current_file):
                self.q.put(("scan_progress", done, total, current_file))

            results = scan_directory(path, on_progress=progress)
            self.q.put(("scan_done", results))

        threading.Thread(target=run, daemon=True).start()

    def _on_scan_select(self, event):
        sel = self.scan_tree.selection()
        if not sel:
            return
        vals = self.scan_tree.item(sel[0], "values")
        if len(vals) < 6:
            return
        idx = vals[5]
        r = self.scan_results[int(idx)]
        v = r.get("verdict", {})
        verdict_text = v.get("verdict", "YES")
        verdict_reason = v.get("reason", "")
        if verdict_text == "YES":
            verdict_banner = "\u2713  SAFE TO OPEN"
        elif verdict_text == "NO":
            verdict_banner = f"\u2717  DO NOT OPEN \u2014 {verdict_reason}"
        else:
            verdict_banner = f"\u26a0  CHECK BEFORE OPENING \u2014 {verdict_reason}"
        lines = [verdict_banner, "", f"File: {r['path']}", f"Real type: {r['real_type'].upper()}  |  Size: {r['size_kb']} KB  |  Hash: {r['hash']}"]
        if r["threats"]:
            lines.append("\nTHREATS:")
            for t in r["threats"]: lines.append(f"  \u2022 {t}")
        if r["warnings"]:
            lines.append("\nWARNINGS:")
            for w in r["warnings"]: lines.append(f"  \u2022 {w}")
        if r["info"]:
            lines.append("\nINFO:")
            for i in r["info"]: lines.append(f"  \u2022 {i}")
        if not r["threats"] and not r["warnings"]:
            lines.append("\nNo threats or warnings found.")
        self.scan_detail.config(state="normal")
        self.scan_detail.delete("1.0", "end")
        self.scan_detail.insert("1.0", "\n".join(lines))
        self.scan_detail.config(state="disabled")

    def _export_scan_report(self):
        if not self.scan_results:
            messagebox.showinfo("No results", "Run a scan first.")
            return
        desktop = str(Path.home() / "Desktop")
        date = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        out = os.path.join(desktop, f"fileguard_report_{date}.txt")
        lines = [f"FileGuard Scan Report \u2014 {date}", "="*60, ""]
        for r in self.scan_results:
            if r["risk"] != "safe":
                lines.append(f"[{r['risk'].upper()}] {r['path']}")
                for t in r["threats"]: lines.append(f"  THREAT: {t}")
                for w in r["warnings"]: lines.append(f"  WARNING: {w}")
                lines.append("")
        with open(out, "w") as f:
            f.write("\n".join(lines))
        messagebox.showinfo("Saved", f"Report saved to:\n{out}")
        self._open_path(out)

    def _clear_scan(self):
        self.scan_tree.delete(*self.scan_tree.get_children())
        self.scan_results = []
        self.scan_summary.config(text="")
        self.scan_progress["value"] = 0
        self.scan_status.config(text="")
        self.scan_detail.config(state="normal")
        self.scan_detail.delete("1.0", "end")
        self.scan_detail.config(state="disabled")

    # ── REPAIR TAB with Drag-Drop + Auto-Diagnosis ─────────────────────────

    def _build_repair_tab(self):
        f = self.tab_repair
        pad = {"padx": 20, "pady": 8}

        # Drop zone
        drop_frame = tk.Frame(f, bg="#e8f4fd", relief="solid", bd=2,
                               highlightbackground=BLUE, highlightthickness=2)
        drop_frame.pack(fill="x", padx=20, pady=(16,4))

        self.drop_label = tk.Label(drop_frame,
                                    text="Drag any file here  OR  click Browse",
                                    font=FONT_B, bg="#e8f4fd", fg=BLUE, pady=20)
        self.drop_label.pack()

        # Enable drag-drop if tkinterdnd2 available
        if HAS_DND:
            drop_frame.drop_target_register(DND_FILES)
            drop_frame.dnd_bind('<<Drop>>', self._on_file_drop)
            self.drop_label.drop_target_register(DND_FILES)
            self.drop_label.dnd_bind('<<Drop>>', self._on_file_drop)

        # File path row
        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=20, pady=(4,4))
        self.repair_path = tk.StringVar()
        tk.Entry(row, textvariable=self.repair_path, font=FONT, width=55,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_repair_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        self.repair_btn = tk.Button(row, text="Repair File", font=FONT_B, bg=BLUE, fg="white",
                                    command=self._start_repair, relief="flat", padx=14, cursor="hand2")
        self.repair_btn.pack(side="left", padx=(8,0))

        # Quick diagnosis label
        self.diag_label = tk.Label(f, text="", font=FONT_SM, bg=BG2,
                                    relief="flat", padx=16, pady=8, anchor="w", wraplength=800)
        self.diag_label.pack(fill="x", padx=20, pady=(0,4))

        tk.Label(f, text="Repair log:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(4,2))

        self.repair_log = scrolledtext.ScrolledText(f, font=FONT_SM, height=14,
                                                     bg="#0d1117", fg="#58d68d", insertbackground="#58d68d",
                                                     relief="solid", bd=1,
                                                     state="disabled", padx=10, pady=8, wrap="word")
        self.repair_log.pack(fill="both", expand=True, padx=20, pady=(0,8))

        self.repair_result_frame = tk.Frame(f, bg=BG)
        self.repair_result_frame.pack(fill="x", padx=20, pady=(0,8))
        self.repair_result_label = tk.Label(self.repair_result_frame, text="",
                                             font=FONT_B, bg=BG, fg=GREEN)
        self.repair_result_label.pack(side="left")
        self.repair_open_btn = tk.Button(self.repair_result_frame, text="Open File",
                                          font=FONT, command=self._open_repaired_file,
                                          relief="solid", bd=1, padx=10, cursor="hand2")

        # Footer note
        tk.Label(f, text="Unknown file formats are reported anonymously to improve FileGuard.",
                 font=("Helvetica", 10), bg=BG, fg=MUTED).pack(anchor="w", padx=20, pady=(0,4))

    def _on_file_drop(self, event):
        path = event.data.strip()
        # tkinterdnd2 on Mac wraps paths with braces for paths with spaces
        if path.startswith("{") and path.endswith("}"):
            path = path[1:-1]
        self.repair_path.set(path)
        self._diagnose_file(path)

    def _browse_repair_file(self):
        f = filedialog.askopenfilename(title="Select file to repair")
        if f:
            self.repair_path.set(f)
            self._diagnose_file(f)

    def _diagnose_file(self, path):
        """Run quick diagnosis before user clicks Repair."""
        if not os.path.exists(path):
            self.diag_label.config(text="File not found.", fg=RED, bg=BG2)
            return
        self.diag_label.config(text="Diagnosing...", fg=MUTED, bg=BG2)
        self.root.update_idletasks()

        def run():
            r = scan_file(path)
            check_and_report(r)
            self.q.put(("diag_done", r))

        threading.Thread(target=run, daemon=True).start()

    def _start_repair(self):
        path = self.repair_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        self.repair_btn.config(text="Repairing...", state="disabled")
        self.repair_log.config(state="normal")
        self.repair_log.delete("1.0", "end")
        self.repair_log.config(state="disabled")
        self.repair_result_label.config(text="")
        self.repair_open_btn.pack_forget()
        self.repaired_output = None

        out_dir = str(Path(path).parent / "recovered")

        def log(msg):
            self.q.put(("repair_log", msg))

        def run():
            result = repair_file(path, out_dir=out_dir, log_callback=log)
            self.q.put(("repair_done", result))

        threading.Thread(target=run, daemon=True).start()

    def _open_repaired_file(self):
        if self.repaired_output:
            if os.path.exists(self.repaired_output):
                self._reveal_in_finder(self.repaired_output)
            else:
                self._open_path(self.repaired_output)

    # ── DOWNLOAD TAB ──────────────────────────────────────

    def _build_download_tab(self):
        f = self.tab_download
        pad = {"padx": 20, "pady": 6}

        tk.Label(f, text="Paste a URL to download:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", **pad)

        url_row = tk.Frame(f, bg=BG)
        url_row.pack(fill="x", padx=20, pady=(0,8))
        self.dl_url = tk.StringVar()
        tk.Entry(url_row, textvariable=self.dl_url, font=FONT, width=60,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)

        options_row = tk.Frame(f, bg=BG)
        options_row.pack(fill="x", padx=20, pady=(0,8))
        tk.Label(options_row, text="Quality:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        self.dl_quality = tk.StringVar(value="1080p Full HD")
        quality_opts = [
            "4K Ultra HD (2160p)",
            "1080p Full HD",
            "720p HD",
            "480p",
            "360p (small file)",
            "Audio only — MP3 (best)",
            "Audio only — MP3 (128kbps)",
            "Audio only — WAV (lossless)",
            "Audio only — FLAC (lossless)",
            "Video only (no audio)",
        ]
        ttk.Combobox(options_row, textvariable=self.dl_quality, values=quality_opts,
                     font=FONT, width=28, state="readonly").pack(side="left", padx=(8,16))
        tk.Label(options_row, text="Save to:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        self.dl_out = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Entry(options_row, textvariable=self.dl_out, font=FONT, width=22,
                 relief="solid", bd=1).pack(side="left", padx=(8,4), ipady=4)
        tk.Button(options_row, text="Browse", font=FONT_SM, command=self._browse_dl_folder,
                  relief="solid", bd=1, padx=6, cursor="hand2").pack(side="left")

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,8))
        self.dl_btn = tk.Button(btn_row, text="Download", font=FONT_B, bg=BLUE, fg="white",
                                 command=self._start_download, relief="flat", padx=16, cursor="hand2")
        self.dl_btn.pack(side="left")
        self.dl_cancel_btn = tk.Button(btn_row, text="Cancel", font=FONT, command=self._cancel_download,
                                        relief="solid", bd=1, padx=10, cursor="hand2", state="disabled")
        self.dl_cancel_btn.pack(side="left", padx=8)

        self.dl_progress = ttk.Progressbar(f, mode="determinate", length=400)
        self.dl_progress.pack(fill="x", padx=20, pady=(0,4))
        self.dl_status = tk.Label(f, text="", font=FONT_SM, bg=BG, fg=MUTED, anchor="w")
        self.dl_status.pack(fill="x", padx=20, pady=(0,4))

        tk.Label(f, text="Download log:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(4,2))
        self.dl_log = scrolledtext.ScrolledText(f, font=FONT_SM, height=12,
                                                 bg="#0d1117", fg="#58d68d", insertbackground="#58d68d",
                                                 selectbackground="#1f6feb", selectforeground="white",
                                                 relief="solid", bd=1,
                                                 state="disabled", padx=10, pady=8, wrap="word")
        self.dl_log.pack(fill="both", expand=True, padx=20, pady=(0,8))

        self.dl_result_frame = tk.Frame(f, bg=BG)
        self.dl_result_frame.pack(fill="x", padx=20, pady=(0,12))
        self.dl_result_label = tk.Label(self.dl_result_frame, text="", font=FONT_B, bg=BG, fg=GREEN)
        self.dl_result_label.pack(side="left")
        self.dl_open_btn = tk.Button(self.dl_result_frame, text="Open File",
                                      font=FONT, command=self._open_downloaded_file,
                                      relief="solid", bd=1, padx=10, cursor="hand2")

    def _browse_dl_folder(self):
        d = filedialog.askdirectory(title="Save downloads to")
        if d:
            self.dl_out.set(d)

    def _start_download(self):
        url = self.dl_url.get().strip()
        if not url:
            messagebox.showerror("No URL", "Please paste a URL first.")
            return

        try:
            import yt_dlp
        except ImportError:
            if messagebox.askyesno("Install required", "yt-dlp is needed for downloads.\nInstall it now?"):
                subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"], check=True)
                messagebox.showinfo("Done", "yt-dlp installed. Click Download again.")
            return

        if self.download_running:
            return
        self.download_running = True
        self.dl_btn.config(text="Downloading...", state="disabled")
        self.dl_cancel_btn.config(state="normal")
        self.dl_progress["value"] = 0
        self.dl_status.config(text="Starting download...")
        self.dl_log.config(state="normal")
        self.dl_log.delete("1.0", "end")
        self.dl_log.config(state="disabled")
        self.dl_result_label.config(text="")
        self.dl_open_btn.pack_forget()
        self.dl_output_path = None

        quality = self.dl_quality.get()
        out_dir = self.dl_out.get()

        def progress_hook(d):
            if d["status"] == "downloading":
                pct_str = d.get("_percent_str", "0%").strip().replace("%","")
                try:
                    pct = float(pct_str)
                except Exception:
                    pct = 0
                speed = d.get("_speed_str", "").strip()
                eta = d.get("_eta_str", "").strip()
                fname = os.path.basename(d.get("filename",""))
                self.q.put(("dl_progress", pct, f"{fname}  {speed}  ETA {eta}"))
            elif d["status"] == "finished":
                fname = d.get("filename", "")
                self.q.put(("dl_done_file", fname))

        def run():
            try:
                import ssl as _ssl
                ffmpeg_path = get_ffmpeg()
                self.q.put(("dl_log", f"Starting download..."))
                self.q.put(("dl_log", f"URL: {url}"))

                clean = url.split('?')[0].lower()

                DIRECT_EXTS = (
                    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
                    '.ppt', '.pptx', '.zip', '.rar', '.7z',
                    '.tar', '.gz', '.bz2', '.mp3', '.wav',
                    '.flac', '.ogg', '.m4a', '.aac', '.epub',
                    '.mobi', '.txt', '.csv', '.json', '.xml',
                    '.png', '.jpg', '.jpeg', '.gif', '.bmp',
                    '.webp', '.tiff', '.svg', '.mp4', '.avi',
                    '.mkv', '.mov', '.wmv', '.flv', '.webm',
                )

                VIDEO_SITES = (
                    'youtube.com', 'youtu.be', 'twitter.com', 'x.com',
                    'instagram.com', 'tiktok.com', 'facebook.com',
                    'vimeo.com', 'dailymotion.com', 'reddit.com',
                    'twitch.tv', 'soundcloud.com',
                )

                is_direct = any(clean.endswith(e) for e in DIRECT_EXTS)
                is_archive_org = 'archive.org/details/' in url
                is_video = any(s in url for s in VIDEO_SITES)

                if url.startswith('magnet:'):
                    self.q.put(("dl_log", "Magnet link detected"))
                    self.q.put(("dl_log", "Note: Requires torrent seeders — may be slow"))
                    self._download_magnet(url, out_dir)
                    return

                elif is_archive_org:
                    self.q.put(("dl_log", "Detected: Internet Archive page"))
                    self.q.put(("dl_log", "Fetching file list from Archive.org API..."))

                    import urllib.request, json
                    ctx = _ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = _ssl.CERT_NONE

                    item_id = url.split('archive.org/details/')[-1].split('/')[0].split('?')[0].strip('/')
                    self.q.put(("dl_log", f"Item ID: {item_id}"))

                    api_url = f"https://archive.org/metadata/{item_id}"
                    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, context=ctx, timeout=15) as r:
                        data = json.loads(r.read())

                    files = data.get('files', [])
                    self.q.put(("dl_log", f"Found {len(files)} files in archive"))

                    priority_exts = ['.pdf', '.epub', '.mp4', '.mp3', '.ogg', '.ogv', '.avi', '.mkv', '.flac', '.wav', '.txt', '.djvu']
                    skip_suffixes = ('_meta.xml', '_files.xml', '_reviews.xml', '.sqlite', '_itemimage.jpg', '.torrent')

                    chosen = None
                    chosen_name = None
                    for ext in priority_exts:
                        for f in files:
                            name = f.get('name', '')
                            if any(name.endswith(s) for s in skip_suffixes):
                                continue
                            if name.lower().endswith(ext):
                                chosen_name = name
                                chosen = f"https://archive.org/download/{item_id}/{name}"
                                break
                        if chosen:
                            break

                    if not chosen:
                        valid = [f for f in files if not any(f.get('name','').endswith(s) for s in skip_suffixes)]
                        if valid:
                            best = max(valid, key=lambda x: int(x.get('size', 0) or 0))
                            chosen_name = best['name']
                            chosen = f"https://archive.org/download/{item_id}/{chosen_name}"

                    if not chosen:
                        self.q.put(("dl_error", "No downloadable files found in this Archive.org item"))
                        return

                    self.q.put(("dl_log", f"Downloading: {chosen_name}"))
                    url_to_download = chosen

                    # Fall through to direct download below
                    self._do_direct_download(url_to_download, out_dir)

                elif is_direct:
                    fname = url.split('/')[-1].split('?')[0]
                    self.q.put(("dl_log", f"Direct file: {fname}"))
                    self._do_direct_download(url, out_dir)

                elif is_video:
                    self.q.put(("dl_log", "Video site detected — using yt-dlp"))

                    fmt_map = {
                        "4K Ultra HD (2160p)":
                            "bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best",
                        "1080p Full HD":
                            "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                        "720p HD":
                            "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",
                        "480p":
                            "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]",
                        "360p (small file)": "best[height<=360]/worst",
                        "Audio only — MP3 (best)": "bestaudio/best",
                        "Audio only — MP3 (128kbps)": "bestaudio[abr<=128]/bestaudio/best",
                        "Audio only — WAV (lossless)": "bestaudio/best",
                        "Audio only — FLAC (lossless)": "bestaudio/best",
                        "Video only (no audio)": "bestvideo[ext=mp4]/bestvideo/best",
                    }
                    opts = {
                        "outtmpl":              os.path.join(out_dir, "%(title)s.%(ext)s"),
                        "progress_hooks":       [progress_hook],
                        "quiet":                True,
                        "no_warnings":          True,
                        "nocheckcertificate":   True,
                    }
                    opts["format"] = fmt_map.get(quality, "best[ext=mp4]/best")
                    opts["merge_output_format"] = "mp4"

                    if ffmpeg_path and os.path.exists(ffmpeg_path):
                        opts["ffmpeg_location"] = os.path.dirname(ffmpeg_path)
                        self.q.put(("dl_log", "ffmpeg: bundled"))
                    else:
                        opts["format"] = "best[ext=mp4]/best"
                        self.q.put(("dl_log", "ffmpeg not found — using single-file format"))

                    # Audio-only post-processors
                    if "MP3" in quality and ffmpeg_path and os.path.exists(ffmpeg_path):
                        bitrate = "128" if "128kbps" in quality else "320"
                        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                                    "preferredcodec": "mp3",
                                                    "preferredquality": bitrate}]
                        opts.pop("merge_output_format", None)
                    elif "WAV" in quality and ffmpeg_path and os.path.exists(ffmpeg_path):
                        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]
                        opts.pop("merge_output_format", None)
                    elif "FLAC" in quality and ffmpeg_path and os.path.exists(ffmpeg_path):
                        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "flac"}]
                        opts.pop("merge_output_format", None)
                    elif "Video only" in quality:
                        opts.pop("merge_output_format", None)

                    import yt_dlp
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([url])
                    self.q.put(("dl_finished", True))

                else:
                    # Unknown URL — try direct first, then yt-dlp
                    self.q.put(("dl_log", "Unknown URL type — trying direct download..."))
                    try:
                        self._do_direct_download(url, out_dir)
                    except Exception as e1:
                        self.q.put(("dl_log", f"Direct failed ({e1}) — trying yt-dlp..."))
                        import yt_dlp
                        opts = {
                            "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
                            "progress_hooks": [progress_hook],
                            "quiet": True,
                            "no_warnings": True,
                            "nocheckcertificate": True,
                            "format": "best",
                        }
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            ydl.download([url])
                        self.q.put(("dl_finished", True))

            except Exception as e:
                self.q.put(("dl_error", str(e)))

        threading.Thread(target=run, daemon=True).start()

    def _cancel_download(self):
        self.download_running = False
        self.dl_btn.config(text="Download", state="normal")
        self.dl_cancel_btn.config(state="disabled")
        self.dl_status.config(text="Cancelled")

    def _reveal_in_finder(self, path):
        """Reveal file in Finder (Mac) or Explorer (Win) with it selected."""
        import subprocess, platform
        system = platform.system()
        if system == "Darwin":
            if os.path.isfile(path):
                subprocess.run(['open', '-R', path])
            else:
                subprocess.run(['open', path])
        elif system == "Windows":
            if os.path.isfile(path):
                subprocess.run(['explorer', f'/select,{path}'])
            else:
                subprocess.run(['explorer', path])
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.run(['xdg-open', folder])

    def _open_dl_result(self):
        path = getattr(self, 'dl_output_path', None)
        if not path:
            messagebox.showinfo("No file", "No downloaded file to open")
            return
        if os.path.isdir(path):
            self._reveal_in_finder(path)
        elif os.path.exists(path):
            self._reveal_in_finder(path)
        else:
            parent = os.path.dirname(path)
            if os.path.exists(parent):
                self._reveal_in_finder(parent)
            else:
                messagebox.showinfo("Not found", f"File not found:\n{path}")

    def _open_downloaded_file(self):
        self._open_dl_result()

    # ── INFO TAB ──────────────────────────────────────────

    def _build_info_tab(self):
        f = self.tab_info

        tk.Label(f, text="Select any file to see its real type and safety info:",
                 font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(16,6))

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=20, pady=(0,12))
        self.info_path = tk.StringVar()
        tk.Entry(row, textvariable=self.info_path, font=FONT, width=55,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_info_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        tk.Button(row, text="Analyze", font=FONT_B, bg=BLUE, fg="white",
                  command=self._run_info, relief="flat", padx=14, cursor="hand2").pack(side="left", padx=(8,0))

        self.info_frame = tk.Frame(f, bg=BG2, relief="solid", bd=1)
        self.info_frame.pack(fill="x", padx=20, pady=(0,12))
        self.info_labels = {}
        fields = [
            ("File name",   "name"),
            ("Real type",   "real_type"),
            ("Extension",   "claimed_ext"),
            ("Size",        "size_kb"),
            ("Category",    "category"),
            ("Risk level",  "risk"),
            ("Hash (SHA256)","hash"),
        ]
        for i, (label, key) in enumerate(fields):
            row_f = tk.Frame(self.info_frame, bg=BG2 if i % 2 == 0 else "#eeeeee")
            row_f.pack(fill="x")
            tk.Label(row_f, text=label, font=FONT_B, bg=row_f["bg"], fg=MUTED,
                     width=18, anchor="w", padx=14, pady=8).pack(side="left")
            lbl = tk.Label(row_f, text="\u2014", font=FONT, bg=row_f["bg"], fg=TEXT, anchor="w", pady=8)
            lbl.pack(side="left", fill="x", expand=True)
            self.info_labels[key] = lbl

        self.info_threats_frame = tk.Frame(f, bg=BG)
        self.info_threats_frame.pack(fill="both", expand=True, padx=20, pady=(0,12))
        self.info_threats_text = scrolledtext.ScrolledText(
            self.info_threats_frame, font=FONT_SM, height=8,
            bg=BG2, relief="solid", bd=1, state="disabled", padx=10, pady=8, wrap="word")
        self.info_threats_text.pack(fill="both", expand=True)

    def _browse_info_file(self):
        f = filedialog.askopenfilename(title="Select any file")
        if f:
            self.info_path.set(f)

    def _run_info(self):
        path = self.info_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        r = scan_file(path)
        check_and_report(r)
        self.info_labels["name"].config(text=r["name"])
        self.info_labels["real_type"].config(text=r["real_type"].upper())
        self.info_labels["claimed_ext"].config(text=f".{r['claimed_ext']}" if r["claimed_ext"] else "(none)")
        self.info_labels["size_kb"].config(text=f"{r['size_kb']} KB")
        self.info_labels["category"].config(text=r["category"])
        self.info_labels["hash"].config(text=r["hash"])

        risk = r["risk"]
        self.info_labels["risk"].config(text=RISK_LABELS[risk],
                                         fg=RISK_COLORS[risk], font=FONT_B)

        lines = []
        if r["threats"]:
            lines.append("THREATS:")
            for t in r["threats"]: lines.append(f"  \u2022 {t}")
        if r["warnings"]:
            lines.append("WARNINGS:")
            for w in r["warnings"]: lines.append(f"  \u2022 {w}")
        if r["info"]:
            lines.append("INFO:")
            for i in r["info"]: lines.append(f"  \u2022 {i}")
        if not lines:
            lines.append("No threats or warnings. File appears safe.")

        self.info_threats_text.config(state="normal")
        self.info_threats_text.delete("1.0", "end")
        self.info_threats_text.insert("1.0", "\n".join(lines))
        self.info_threats_text.config(state="disabled")

    # ── Update system ─────────────────────────────────────

    def _on_update_found(self, version, url):
        self._pending_update_url = url
        self.root.after(0, lambda: self._show_update_banner(version, url))

    def _show_update_banner(self, version, url):
        self.update_label.config(
            text=f"Update available: v{version} — click to download in background")
        self.update_btn.config(command=lambda: self._do_update(version, url))
        self.update_banner.pack(fill="x", after=self.root.winfo_children()[0])

    def _do_update(self, version, url):
        self.update_btn.config(text="Updating...", state="disabled")
        def on_progress(msg):
            self.root.after(0, lambda: self.update_label.config(text=msg))
        def on_done(v, error=None):
            if error:
                self.root.after(0, lambda: self.update_label.config(text=f"Update failed: {error}"))
            else:
                self.root.after(0, lambda: self.update_label.config(
                    text=f"Updated to v{v} \u2014 close and reopen FileGuard to apply"))
        threading.Thread(
            target=download_and_install,
            args=(url, version),
            kwargs={"on_progress": on_progress, "on_done": on_done},
            daemon=True
        ).start()

    # ── Queue polling ─────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]

                if kind == "scan_progress":
                    _, done, total, current = msg
                    pct = int(done / total * 100) if total else 0
                    self.scan_progress["value"] = pct
                    self.scan_status.config(text=f"{done}/{total} files \u2014 {os.path.basename(current)}")

                elif kind == "scan_done":
                    results = msg[1]
                    self.scan_running = False
                    self.scan_btn.config(text="Scan Now", state="normal")
                    self.scan_progress["value"] = 100

                    all_r = (results["critical"] + results["high"] +
                             results["medium"] + results["low"] + results["safe"])
                    self.scan_results = all_r

                    # Report unknown formats
                    for r in all_r:
                        check_and_report(r)

                    s = results
                    total = s["scanned"]
                    self.scan_status.config(text=f"Done \u2014 {total} files scanned")
                    self.scan_summary.config(
                        text=f"  {total} files scanned  |  "
                             f"Critical: {len(s['critical'])}  "
                             f"High: {len(s['high'])}  "
                             f"Medium: {len(s['medium'])}  "
                             f"Low: {len(s['low'])}  "
                             f"Safe: {len(s['safe'])}"
                    )

                    for i, r in enumerate(all_r):
                        risk = r["risk"]
                        v = r.get("verdict", {})
                        vt = v.get("verdict", "YES")
                        vtag = {"YES":"verdict_yes","NO":"verdict_no","CAUTION":"verdict_caution"}.get(vt,"verdict_yes")
                        vals = (vt, RISK_LABELS[risk], r["name"], f"{r['size_kb']} KB", r["real_type"], str(i))
                        self.scan_tree.insert("", "end", values=vals, tags=(risk, vtag))

                elif kind == "diag_done":
                    r = msg[1]
                    rt = r["real_type"].upper()
                    risk = r["risk"]
                    if r["real_type"] == "unknown":
                        msg_text = f"Unknown format — will attempt recovery. Extension: .{r['claimed_ext'] or '(none)'}"
                        fg = MUTED
                    elif risk == "safe" and not r["warnings"] and not r["threats"]:
                        msg_text = f"This is a {rt} file — structure looks healthy — click Repair to optimize/rebuild it."
                        fg = GREEN
                    else:
                        issues = []
                        for t in r["threats"]: issues.append(t)
                        for w in r["warnings"]: issues.append(w)
                        issue_str = "; ".join(issues[:2])
                        msg_text = f"This is a {rt} file — {issue_str or 'issues detected'} — click Repair to fix."
                        fg = YELLOW if risk in ("low","medium") else RED
                    self.diag_label.config(text=msg_text, fg=fg, bg=BG2)

                elif kind == "repair_log":
                    msg_text = msg[1]
                    self.repair_log.config(state="normal")
                    self.repair_log.insert("end", msg_text + "\n")
                    self.repair_log.tag_add("green", "1.0", "end")
                    self.repair_log.tag_config("green", foreground="#58d68d")
                    self.repair_log.see("end")
                    self.repair_log.config(state="disabled")

                elif kind == "repair_done":
                    result = msg[1]
                    self.repair_btn.config(text="Repair File", state="normal")
                    if result["ok"]:
                        self.repair_result_label.config(text=f"\u2713  {result['message']}", fg=GREEN)
                        self.repaired_output = result.get("output")
                        if self.repaired_output:
                            self.repair_open_btn.pack(side="left", padx=8)
                        self.q.put(("repair_log", f"\nSaved to: {result.get('output','')}"))
                    else:
                        self.repair_result_label.config(text=f"\u2717  {result['message']}", fg=RED)
                    self.q.put(("repair_log", "\n--- Done ---"))

                elif kind == "dl_progress":
                    _, pct, status_text = msg
                    self.dl_progress["value"] = min(pct, 100)
                    self.dl_status.config(text=status_text)

                elif kind == "dl_log":
                    self.dl_log.config(state="normal")
                    self.dl_log.insert("end", msg[1] + "\n")
                    self.dl_log.tag_add("green", "1.0", "end")
                    self.dl_log.tag_config("green", foreground="#58d68d")
                    self.dl_log.see("end")
                    self.dl_log.config(state="disabled")

                elif kind == "dl_done_file":
                    self.dl_output_path = msg[1]

                elif kind == "dl_finished":
                    self.download_running = False
                    self.dl_btn.config(text="Download", state="normal")
                    self.dl_cancel_btn.config(state="disabled")
                    self.dl_progress["value"] = 100
                    self.dl_status.config(text="Download complete!")
                    self.dl_result_label.config(text="\u2713  Download complete", fg=GREEN)
                    if self.dl_output_path:
                        self.dl_open_btn.pack(side="left", padx=8)
                    if self.dl_output_path and os.path.exists(self.dl_output_path):
                        r = scan_file(self.dl_output_path)
                        check_and_report(r)
                        if r["risk"] in ("safe","low"):
                            self.q.put(("dl_log", f"\nScan result: SAFE \u2014 {r['real_type'].upper()} file"))
                        else:
                            self.q.put(("dl_log", f"\nSCAN WARNING: {r['risk'].upper()} risk detected!"))
                            for t in r["threats"]: self.q.put(("dl_log", f"  \u2022 {t}"))

                elif kind == "dl_error":
                    self.download_running = False
                    self.dl_btn.config(text="Download", state="normal")
                    self.dl_cancel_btn.config(state="disabled")
                    err = msg[1]
                    self.dl_result_label.config(text="\u2717  Download failed", fg=RED)
                    self.q.put(("dl_log", f"\nError: {err}"))
                    if "not supported" in err.lower():
                        self.q.put(("dl_log", "This site may not be supported by yt-dlp."))
                    elif "network" in err.lower() or "connection" in err.lower():
                        self.q.put(("dl_log", "Check your internet connection."))

                elif kind == "new_download_scanned":
                    result = msg[1]
                    risk = result['risk']
                    name = result['name']
                    v = result.get('verdict', {})
                    self._downloads_scanned_today += 1
                    self._update_status(f"Watching Downloads \u2014 {self._downloads_scanned_today} files scanned today")
                    if risk in ('high', 'critical'):
                        reason = v.get('reason', 'suspicious content')
                        try:
                            subprocess.run(['osascript', '-e',
                                f'display notification "{name}: DO NOT OPEN - {reason}" with title "FileGuard Warning" sound name "Basso"'])
                        except Exception:
                            pass
                    elif risk == 'safe':
                        try:
                            subprocess.run(['osascript', '-e',
                                f'display notification "{name}: Safe to open" with title "FileGuard"'])
                        except Exception:
                            pass

                elif kind == "conv_log":
                    if hasattr(self, 'conv_log'):
                        self.conv_log.config(state="normal")
                        self.conv_log.insert("end", msg[1] + "\n")
                        self.conv_log.tag_add("g", "1.0", "end")
                        self.conv_log.tag_config("g", foreground="#58d68d")
                        self.conv_log.see("end")
                        self.conv_log.config(state="disabled")

                elif kind == "conv_done":
                    result = msg[1]
                    if hasattr(self, 'conv_btn'):
                        self.conv_btn.config(state="normal", text="Convert Now")
                        self.conv_progress.stop()
                        if result.get("ok"):
                            self.conv_output_path = result.get("output")
                            self.conv_result_label.config(
                                text=f"\u2713 {result.get('message', 'Done')}", fg="#2d7a2d")
                            if self.conv_output_path:
                                self.conv_open_btn.pack(side="left", padx=8)
                            self.conv_status_lbl.config(
                                text=f"Saved: {self.conv_output_path or ''}")
                        else:
                            self.conv_result_label.config(
                                text=f"\u2717 {result.get('message', 'Failed')}", fg="#cc2200")

                elif kind == "ocr_done":
                    if hasattr(self, 'ocr_btn'):
                        self.ocr_btn.config(text="Extract Text", state="normal")
                        self.ocr_result.config(state="normal")
                        self.ocr_result.delete("1.0", "end")
                        self.ocr_result.insert("1.0", msg[1] if msg[1] else "(No text found)")
                        self.ocr_result.config(state="disabled", fg="black", bg="white")

                elif kind == "ocr_error":
                    if hasattr(self, 'ocr_btn'):
                        self.ocr_btn.config(text="Extract Text", state="normal")
                        self.ocr_result.delete("1.0", "end")
                        self.ocr_result.insert("1.0", f"Error: {msg[1]}")

                elif kind == "dup_progress":
                    _, done, total, _ = msg
                    pct = int(done / total * 100) if total else 0
                    if hasattr(self, 'dup_progress'):
                        self.dup_progress["value"] = pct

                elif kind == "dup_done":
                    groups = msg[1]
                    if hasattr(self, 'dup_btn'):
                        self.dup_btn.config(text="Find Duplicates", state="normal")
                        self.dup_tree.delete(*self.dup_tree.get_children())
                        self._dup_groups = {}
                        total_wasted = 0
                        for h, files in groups.items():
                            sz = files[0].stat().st_size
                            total_wasted += sz * (len(files) - 1)
                            gid = self.dup_tree.insert("", "end", values=(
                                "", f"Group \u2014 {len(files)} identical files", f"{human_size(sz)} each"))
                            self._dup_groups[gid] = files
                            for fp in files:
                                self.dup_tree.insert(gid, "end",
                                    values=("", str(fp), human_size(fp.stat().st_size)))
                        self.dup_summary.config(
                            text=f"Found {len(groups)} duplicate groups \u2014 {human_size(total_wasted)} wasted",
                            bg="#fff9e6" if groups else BG2)

                elif kind == "privacy_progress":
                    _, done, total, _ = msg
                    pct = int(done / total * 100) if total else 0
                    if hasattr(self, 'privacy_folder_progress'):
                        self.privacy_folder_progress["value"] = pct

                elif kind == "privacy_folder_done":
                    result = msg[1]
                    if hasattr(self, 'privacy_results'):
                        self.privacy_results.config(state="normal")
                        self.privacy_results.insert("end",
                            f"\n\u2713 Done \u2014 cleaned {result['cleaned']} photos, "
                            f"removed GPS from {result['gps_found']}.\n"
                            f"Saved to: {result['out_dir']}")
                        self.privacy_results.config(state="disabled")

                elif kind == "disk_done":
                    sizes = msg[1]
                    if hasattr(self, '_draw_disk_chart'):
                        self._draw_disk_chart(sizes)

                elif kind == "tool_msg":
                    _, label_widget, text, color = msg
                    label_widget.config(text=text, fg=color)

        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ── STATUS BAR ─────────────────────────────────────────────────────────

    def _build_status_bar(self):
        bar = tk.Frame(self.root, bg=BG2)
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=BORDER, height=1).pack(fill="x")
        inner = tk.Frame(bar, bg=BG2)
        inner.pack(fill="x", padx=12, pady=4)
        self.status_left = tk.Label(inner,
            text="FileGuard ready \u2014 drag any file onto the window to analyze it",
            font=FONT_SM, bg=BG2, fg=MUTED, anchor="w")
        self.status_left.pack(side="left")
        tk.Label(inner, text=f"FileGuard v{get_current_version()}",
                 font=FONT_SM, bg=BG2, fg=MUTED).pack(side="right")

    def _update_status(self, text):
        if hasattr(self, 'status_left'):
            self.root.after(0, lambda t=text: self.status_left.config(text=t))

    # ── DOWNLOADS WATCHER ──────────────────────────────────────────────────

    def _start_downloads_watcher(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
            import time as _time

            app = self

            class DownloadHandler(FileSystemEventHandler):
                def on_created(self, event):
                    if event.is_directory:
                        return
                    _time.sleep(2)
                    path = event.src_path
                    if not os.path.exists(path):
                        return
                    try:
                        result = scan_file(path)
                        app.q.put(("new_download_scanned", result))
                    except Exception:
                        pass

            downloads = str(Path.home() / "Downloads")
            handler = DownloadHandler()
            observer = Observer()
            observer.schedule(handler, downloads, recursive=False)
            observer.daemon = True
            observer.start()
            self.downloads_observer = observer
            self._update_status("Watching Downloads folder \u2014 0 files scanned today")
        except ImportError:
            pass

    # ── PREVIEW TAB ────────────────────────────────────────────────────────

    def _build_preview_tab(self):
        f = self.tab_preview
        top = tk.Frame(f, bg=BG)
        top.pack(fill="x", padx=20, pady=(12,4))
        tk.Label(top, text="Preview any file:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w")
        row = tk.Frame(top, bg=BG)
        row.pack(fill="x", pady=4)
        self.preview_path = tk.StringVar()
        tk.Entry(row, textvariable=self.preview_path, font=FONT, width=55,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_preview_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        tk.Button(row, text="Open File", font=FONT, command=self._open_preview_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))

        preview_area = tk.Frame(f, bg="#222222", relief="solid", bd=1)
        preview_area.pack(fill="both", expand=True, padx=20, pady=(0,4))
        self.preview_canvas = tk.Canvas(preview_area, bg="#222222", highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_text = scrolledtext.ScrolledText(preview_area, font=("Helvetica", 13),
                                                       bg="white", fg="#1a1a1a",
                                                       insertbackground="black",
                                                       relief="flat", bd=0,
                                                       padx=20, pady=20, wrap="word",
                                                       spacing1=2, spacing3=2,
                                                       state="disabled", height=20)

        self.preview_info = tk.Label(f, text="Select a file to preview", font=FONT_SM,
                                      bg=BG2, relief="flat", padx=16, pady=6, anchor="w")
        self.preview_info.pack(fill="x", padx=20, pady=(0,8))

        if HAS_DND:
            self.preview_canvas.drop_target_register(DND_FILES)
            self.preview_canvas.dnd_bind('<<Drop>>', lambda e: self._on_preview_drop(e.data))

    def _browse_preview_file(self):
        p = filedialog.askopenfilename(title="Select file to preview")
        if p:
            self.preview_path.set(p)
            self._show_preview(p)

    def _on_preview_drop(self, data):
        path = data.strip().strip('{}')
        self.preview_path.set(path)
        self._show_preview(path)

    def _open_preview_file(self):
        p = self.preview_path.get().strip()
        if p and os.path.exists(p):
            self._open_path(p)

    def _show_preview(self, path):
        if not os.path.exists(path):
            return
        ext = Path(path).suffix.lower()
        image_exts = {'.jpg','.jpeg','.png','.gif','.bmp','.webp','.tiff'}
        audio_exts = {'.mp3','.wav','.flac','.ogg','.m4a','.aac'}
        video_exts = {'.mp4','.avi','.mkv','.mov','.wmv','.flv'}
        text_exts  = {'.txt','.py','.js','.html','.css','.json','.xml',
                      '.csv','.md','.sh','.bat','.log','.yaml','.toml'}
        archive_exts = {'.zip','.rar','.7z','.tar','.gz','.bz2'}
        doc_exts = {'.docx', '.xlsx', '.pptx', '.epub'}
        size_kb = round(os.path.getsize(path) / 1024, 1)
        self.preview_canvas.pack(fill="both", expand=True)
        self.preview_text.pack_forget()
        if ext in image_exts:
            self._preview_image(path)
            self.preview_info.config(text=f"Image \u2014 {size_kb} KB \u2014 {path}")
        elif ext == '.pdf':
            self._preview_pdf(path)
        elif ext == '.docx':
            self._preview_docx(path)
            self.preview_info.config(text=f"Word document \u2014 {size_kb} KB \u2014 {path}")
        elif ext == '.doc':
            self._preview_message(
                f"Legacy Word Document (.doc)\n{'─'*50}\n"
                f"File: {os.path.basename(path)}\n"
                f"Size: {size_kb} KB\n\n"
                "This is an older Office format (pre-2007).\n"
                "Click 'Open File' to view in Word, Pages, or LibreOffice.\n\n"
                "Use the Repair tab to check file integrity.")
            self.preview_info.config(text=f".doc (legacy Word) \u2014 {size_kb} KB \u2014 {path}")
        elif ext in doc_exts:
            self._preview_docx(path)
            self.preview_info.config(text=f"Document \u2014 {size_kb} KB \u2014 {path}")
        elif ext in audio_exts or ext in video_exts:
            self._preview_media(path)
            self.preview_info.config(text=f"Media file \u2014 {size_kb} KB \u2014 {path}")
        elif ext in text_exts:
            self._preview_text_file(path)
            self.preview_info.config(text=f"Text file \u2014 {size_kb} KB \u2014 {path}")
        elif ext in archive_exts:
            self._preview_archive(path)
            self.preview_info.config(text=f"Archive \u2014 {size_kb} KB \u2014 {path}")
        else:
            self._preview_hex(path)
            self.preview_info.config(text=f"Unknown format \u2014 hex dump \u2014 {size_kb} KB")

    def _preview_image(self, path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            orig_size = img.size
            self.preview_canvas.update_idletasks()
            cw = max(self.preview_canvas.winfo_width(), 400)
            ch = max(self.preview_canvas.winfo_height(), 300)
            img.thumbnail((cw, ch))
            photo = ImageTk.PhotoImage(img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(cw//2, ch//2, image=photo, anchor="center")
            self.preview_canvas._photo = photo
            self.preview_info.config(text=f"Image \u2014 {orig_size[0]}x{orig_size[1]} px \u2014 {path}")
        except Exception as e:
            self._preview_message(f"Could not preview image:\n{e}")

    def _preview_pdf(self, path):
        try:
            import pikepdf
            with pikepdf.open(path) as pdf:
                pages = len(pdf.pages)
            try:
                from pdf2image import convert_from_path
                imgs = convert_from_path(path, first_page=1, last_page=1, dpi=90,
                                         poppler_path='/opt/homebrew/bin')
                if imgs:
                    from PIL import ImageTk
                    self.preview_canvas.pack(fill="both", expand=True)
                    self.preview_text.pack_forget()
                    self.preview_canvas.update_idletasks()
                    cw = max(self.preview_canvas.winfo_width(), 400)
                    ch = max(self.preview_canvas.winfo_height(), 300)
                    imgs[0].thumbnail((cw, ch))
                    photo = ImageTk.PhotoImage(imgs[0])
                    self.preview_canvas.delete("all")
                    self.preview_canvas.create_image(cw//2, ch//2, image=photo, anchor="center")
                    self.preview_canvas._photo = photo
                    self.preview_info.config(text=f"PDF \u2014 {pages} pages \u2014 {path}")
                    return
            except Exception:
                pass
            # Fallback: show PDF info text
            size_kb = round(os.path.getsize(path) / 1024, 1)
            self._preview_message(
                f"PDF Document\n{'='*40}\n"
                f"Pages:  {pages}\n"
                f"Size:   {size_kb} KB\n"
                f"Path:   {path}\n\n"
                "Click 'Open File' to view in Preview app")
            self.preview_info.config(text=f"PDF \u2014 {pages} pages \u2014 {path}")
        except Exception as e:
            self._preview_message(f"PDF preview error:\n{e}")

    def _preview_media(self, path):
        info = get_media_info(path)
        lines = ["Media File Info\n", "="*40]
        for k, v in info.items():
            lines.append(f"{k:<20}  {v}")
        lines.append("\nClick 'Open File' to play with system default player")
        self._preview_message("\n".join(lines))

    def _preview_text_file(self, path):
        self.preview_canvas.pack_forget()
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.config(state="normal")
        self.preview_text.delete("1.0", "end")
        try:
            with open(path, 'r', errors='replace') as f:
                content = f.read(50000)
            self.preview_text.insert("1.0", content)
            if os.path.getsize(path) > 50000:
                self.preview_text.insert("end", "\n\n... (showing first 50KB) ...")
        except Exception as e:
            self.preview_text.insert("1.0", f"Error reading file: {e}")
        self.preview_text.config(state="disabled")

    def _preview_archive(self, path):
        try:
            import zipfile
            with zipfile.ZipFile(path) as z:
                items = z.infolist()
            lines = [f"Archive contents ({len(items)} files):\n", "="*50]
            for item in items[:100]:
                lines.append(f"  {item.filename}  ({item.file_size:,} bytes)")
            if len(items) > 100:
                lines.append(f"\n... and {len(items)-100} more files")
            self._preview_message("\n".join(lines))
        except Exception:
            self._preview_message("Archive file\n\nCould not list contents.\nUse the Repair tab to extract.")

    def _preview_hex(self, path):
        try:
            with open(path, 'rb') as f:
                data = f.read(512)
            lines = ["Hex dump (first 512 bytes):\n"]
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_part   = ' '.join(f'{b:02x}' for b in chunk)
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
                lines.append(f"{i:04x}  {hex_part:<47}  {ascii_part}")
            self._preview_message("\n".join(lines))
        except Exception as e:
            self._preview_message(f"Cannot read file: {e}")

    def _preview_message(self, text):
        """Show text message in the preview pane."""
        # Hide canvas, show text widget
        if hasattr(self, 'preview_canvas'):
            self.preview_canvas.pack_forget()
        if hasattr(self, 'preview_text'):
            self.preview_text.pack(fill="both", expand=True, padx=6, pady=6)
            self.preview_text.config(state="normal", bg="white", fg="black")
            self.preview_text.delete("1.0", "end")
            self.preview_text.insert("1.0", text)
            self.preview_text.config(state="disabled")

    def _preview_docx(self, path):
        try:
            import zipfile, xml.etree.ElementTree as ET
            size = os.path.getsize(path)
            size_str = f"{round(size/1024/1024,1)} MB" if size > 1e6 else f"{round(size/1024,1)} KB"

            with zipfile.ZipFile(path) as z:
                if 'word/document.xml' not in z.namelist():
                    self._preview_message(f"DOCX: {os.path.basename(path)}\nSize: {size_str}\n\nCould not read document XML.\nClick 'Open File' to view in Word/Pages.")
                    return

                xml_data = z.read('word/document.xml')
                root = ET.fromstring(xml_data)

                lines = []
                for para in root.iter():
                    if para.tag.endswith('}p'):
                        words = [elem.text for elem in para.iter()
                                 if elem.tag.endswith('}t') and elem.text]
                        if words:
                            lines.append(''.join(words))

                content = '\n'.join(lines)
                if not content.strip():
                    self._preview_message(f"DOCX: {os.path.basename(path)}\nSize: {size_str}\n\nDocument appears empty.\nClick 'Open File' to view.")
                    return

                header = f"DOCUMENT — {os.path.basename(path)} ({size_str})\n{'─'*60}\n\n"
                preview = content[:8000] + ("\n\n[... continues ...]" if len(content) > 8000 else "")
                self._preview_message(header + preview)
        except Exception as e:
            self._preview_message(f"DOCX preview error: {e}\n\nClick 'Open File' to view.")

    def _preview_pdf_info(self, path):
        try:
            size = os.path.getsize(path)
            size_str = f"{round(size/1024/1024,1)} MB" if size > 1e6 else f"{round(size/1024,1)} KB"

            # Try pdf2image first for visual preview
            try:
                from pdf2image import convert_from_path
                imgs = convert_from_path(path, first_page=1, last_page=1, dpi=100, poppler_path='/opt/homebrew/bin')
                if imgs:
                    self._preview_image_pil(imgs[0])
                    return
            except Exception:
                pass

            # Fallback: info text
            import pikepdf
            with pikepdf.open(path) as pdf:
                pages = len(pdf.pages)

            self._preview_message(
                f"PDF DOCUMENT\n{'─'*60}\n"
                f"File:  {os.path.basename(path)}\n"
                f"Pages: {pages}\n"
                f"Size:  {size_str}\n\n"
                f"Click 'Open File' to view in Preview app.")
        except Exception as e:
            self._preview_message(f"PDF: {os.path.basename(path)}\n\nError: {e}\n\nClick 'Open File' to open.")

    def _preview_image_pil(self, pil_img):
        """Show a PIL image object in the preview canvas."""
        try:
            from PIL import ImageTk
            self.preview_canvas.pack(fill="both", expand=True)
            self.preview_text.pack_forget()
            self.preview_canvas.update_idletasks()
            cw = max(self.preview_canvas.winfo_width(), 400)
            ch = max(self.preview_canvas.winfo_height(), 300)
            pil_img.thumbnail((cw, ch))
            photo = ImageTk.PhotoImage(pil_img)
            self.preview_canvas.delete("all")
            self.preview_canvas.create_image(cw//2, ch//2, image=photo, anchor="center")
            self.preview_canvas._photo = photo
        except Exception as e:
            self._preview_message(f"Could not display image: {e}")

    # ── CONVERT TAB ────────────────────────────────────────────────────────

    def _build_convert_tab(self):
        f = self.tab_convert

        try:
            from converter import CATEGORIES, detect_category, get_output_formats
        except ImportError:
            tk.Label(f, text="converter.py not found", font=FONT_B,
                     bg=BG, fg="#cc2200").pack(pady=20)
            return

        # File input row
        tk.Label(f, text="File to Convert:", font=FONT_B,
                 bg=BG, fg="black").pack(anchor="w", padx=20, pady=(16,4))

        row1 = tk.Frame(f, bg=BG)
        row1.pack(fill="x", padx=20, pady=(0,4))

        self.conv_path = tk.StringVar()
        self.conv_path.trace("w", self._on_conv_file_change)

        conv_entry = tk.Entry(row1, textvariable=self.conv_path,
                              font=FONT, relief="solid", bd=1,
                              bg="white", fg="black")
        conv_entry.pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row1, text="Browse", font=FONT,
                  command=self._browse_conv_file,
                  relief="solid", bd=1, padx=12,
                  bg="#e8e8e8", fg="black", cursor="hand2"
                  ).pack(side="left", padx=(8,0))

        self.conv_category_label = tk.Label(f, text="Select a file to begin",
            font=FONT_SM, bg=BG, fg="#888888")
        self.conv_category_label.pack(anchor="w", padx=20, pady=(0,8))

        # Format row
        fmt_row = tk.Frame(f, bg=BG)
        fmt_row.pack(fill="x", padx=20, pady=(0,8))
        tk.Label(fmt_row, text="Convert to:", font=FONT_B,
                 bg=BG, fg="black").pack(side="left")

        self.conv_format = tk.StringVar()
        self.conv_format_menu = ttk.Combobox(fmt_row, textvariable=self.conv_format,
                                              font=FONT, width=30, state="readonly")
        self.conv_format_menu.pack(side="left", padx=(8,0))
        self.conv_format_desc_lbl = tk.Label(fmt_row, text="",
            font=FONT_SM, bg=BG, fg="#666666")
        self.conv_format_desc_lbl.pack(side="left", padx=(12,0))
        self.conv_format.trace("w", self._on_conv_format_change)

        # Quality slider
        self.conv_quality_var = tk.IntVar(value=92)
        self.conv_quality_frame = tk.Frame(f, bg=BG)
        tk.Label(self.conv_quality_frame, text="Quality:", font=FONT_SM,
                 bg=BG, fg="black").pack(side="left")
        tk.Scale(self.conv_quality_frame, from_=10, to=100,
                 variable=self.conv_quality_var, orient="horizontal",
                 length=180, bg=BG, fg="black",
                 highlightthickness=0).pack(side="left", padx=4)
        self.conv_qlabel = tk.Label(self.conv_quality_frame, text="92",
            font=FONT_SM, bg=BG, fg="black", width=3)
        self.conv_qlabel.pack(side="left")
        self.conv_quality_var.trace("w",
            lambda *a: self.conv_qlabel.config(text=str(self.conv_quality_var.get())))

        # Output dir
        out_row = tk.Frame(f, bg=BG)
        out_row.pack(fill="x", padx=20, pady=(0,8))
        tk.Label(out_row, text="Save to:", font=FONT_B,
                 bg=BG, fg="black").pack(side="left")
        self.conv_out_dir = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Entry(out_row, textvariable=self.conv_out_dir,
                 font=FONT, relief="solid", bd=1,
                 bg="white", fg="black", width=38).pack(side="left", padx=(8,4), ipady=4)
        tk.Button(out_row, text="Browse", font=FONT_SM,
                  command=self._browse_conv_out,
                  relief="solid", bd=1, padx=6,
                  bg="#e8e8e8", fg="black", cursor="hand2"
                  ).pack(side="left")

        # Convert button
        self.conv_btn = tk.Button(f, text="Convert Now",
            font=FONT_B, bg=BLUE, fg="white",
            command=self._start_convert,
            relief="flat", padx=24, pady=8, cursor="hand2")
        self.conv_btn.pack(pady=(4,4))

        # Progress
        self.conv_progress = ttk.Progressbar(f, mode="indeterminate", length=500)
        self.conv_progress.pack(fill="x", padx=20, pady=(0,4))

        self.conv_status_lbl = tk.Label(f, text="", font=FONT_SM, bg=BG, fg="#444444")
        self.conv_status_lbl.pack(anchor="w", padx=20)

        # Log
        self.conv_log = scrolledtext.ScrolledText(f, font=("Courier", 12), height=7,
            bg="#0d1117", fg="#58d68d", insertbackground="#58d68d",
            relief="solid", bd=1, state="disabled", padx=10, pady=8, wrap="word")
        self.conv_log.pack(fill="both", expand=True, padx=20, pady=(4,4))

        # Result row
        self.conv_result_row = tk.Frame(f, bg=BG)
        self.conv_result_row.pack(fill="x", padx=20, pady=(0,12))
        self.conv_result_label = tk.Label(self.conv_result_row, text="",
            font=FONT_B, bg=BG, fg="#2d7a2d", wraplength=600, justify="left")
        self.conv_result_label.pack(side="left")
        self.conv_open_btn = tk.Button(self.conv_result_row, text="Open in Finder",
            font=FONT, command=self._open_conv_result,
            relief="solid", bd=1, padx=10, bg="#e8e8e8", fg="black", cursor="hand2")
        self.conv_output_path = None

    def _on_conv_file_change(self, *args):
        try:
            from converter import detect_category, get_output_formats, CATEGORIES
        except ImportError:
            return
        path = self.conv_path.get().strip()
        if not path or not os.path.exists(path):
            return
        cat = detect_category(path)
        if cat:
            self.conv_category_label.config(
                text=f"Detected: {cat} file", fg="#1a5fa8")
            fmts = get_output_formats(cat)
            self.conv_format_menu["values"] = fmts
            if fmts:
                self.conv_format.set(fmts[0])
            if cat in ("Image", "Video", "Audio"):
                self.conv_quality_frame.pack(anchor="w", padx=20, pady=(0,4))
            else:
                self.conv_quality_frame.pack_forget()
        else:
            self.conv_category_label.config(text="Unknown file type", fg="#cc2200")
            self.conv_format_menu["values"] = []

    def _on_conv_format_change(self, *args):
        try:
            from converter import CATEGORIES, detect_category
        except ImportError:
            return
        path = self.conv_path.get().strip()
        fmt = self.conv_format.get()
        if not path:
            return
        cat = detect_category(path)
        if cat and fmt:
            desc = CATEGORIES.get(cat, {}).get("outputs", {}).get(fmt, {}).get("desc", "")
            self.conv_format_desc_lbl.config(text=desc)

    def _browse_conv_file(self):
        path = filedialog.askopenfilename(
            title="Select file to convert",
            filetypes=[
                ("All supported", "*.jpg *.jpeg *.png *.gif *.bmp *.webp *.tiff "
                 "*.mp4 *.avi *.mkv *.mov *.mp3 *.wav *.flac *.ogg "
                 "*.docx *.doc *.pdf *.txt *.md *.xlsx *.csv *.json *.yaml "
                 "*.ipynb *.xml *.py *.js *.pptx *.epub"),
                ("All files", "*.*"),
            ])
        if path:
            self.conv_path.set(path)

    def _browse_conv_out(self):
        d = filedialog.askdirectory(title="Save converted file to")
        if d:
            self.conv_out_dir.set(d)

    def _start_convert(self):
        try:
            from converter import convert, detect_category
        except ImportError as e:
            messagebox.showerror("Missing", f"converter.py not found: {e}")
            return

        src = self.conv_path.get().strip()
        fmt = self.conv_format.get().strip()
        out_dir = self.conv_out_dir.get().strip() or str(Path.home() / "Downloads")

        if not src or not os.path.exists(src):
            messagebox.showerror("No file", "Select a file to convert first")
            return
        if not fmt:
            messagebox.showerror("No format", "Select output format")
            return

        self.conv_btn.config(state="disabled", text="Converting...")
        self.conv_progress.start(10)
        self.conv_log.config(state="normal")
        self.conv_log.delete("1.0", "end")
        self.conv_log.config(state="disabled")
        self.conv_result_label.config(text="")
        self.conv_open_btn.pack_forget()
        self.conv_output_path = None

        options = {"quality": self.conv_quality_var.get()}

        def log_fn(msg):
            self.q.put(("conv_log", msg))

        def run():
            result = convert(src, fmt, out_dir, options, log_fn)
            self.q.put(("conv_done", result))

        threading.Thread(target=run, daemon=True).start()

    def _open_conv_result(self):
        if self.conv_output_path:
            self._reveal_in_finder(self.conv_output_path)

    # ── PRIVACY TAB ────────────────────────────────────────────────────────

    def _build_privacy_tab(self):
        f = self.tab_privacy
        tk.Label(f, text="Strip hidden metadata from files before sharing:",
                 font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14,4))
        mode_row = tk.Frame(f, bg=BG)
        mode_row.pack(fill="x", padx=20, pady=(0,8))
        self.privacy_mode = tk.StringVar(value="single")
        tk.Radiobutton(mode_row, text="Single file", variable=self.privacy_mode,
                       value="single", font=FONT_B, bg=BG, fg=TEXT, cursor="hand2",
                       command=self._toggle_privacy_mode).pack(side="left")
        tk.Radiobutton(mode_row, text="Entire folder", variable=self.privacy_mode,
                       value="folder", font=FONT_B, bg=BG, fg=TEXT, cursor="hand2",
                       command=self._toggle_privacy_mode).pack(side="left", padx=20)

        self.privacy_single_frame = tk.Frame(f, bg=BG)
        self.privacy_single_frame.pack(fill="x", padx=20)
        self.privacy_path = tk.StringVar()
        row = tk.Frame(self.privacy_single_frame, bg=BG)
        row.pack(fill="x", pady=(0,6))
        tk.Entry(row, textvariable=self.privacy_path, font=FONT, width=45,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_privacy_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        tk.Button(row, text="Scan for Metadata", font=FONT_B, bg=BLUE, fg="white",
                  command=self._scan_privacy_file, relief="flat", padx=10, cursor="hand2").pack(side="left", padx=(8,0))

        self.privacy_folder_frame = tk.Frame(f, bg=BG)
        self.privacy_fpath = tk.StringVar()
        row2 = tk.Frame(self.privacy_folder_frame, bg=BG)
        row2.pack(fill="x", pady=(0,6))
        tk.Entry(row2, textvariable=self.privacy_fpath, font=FONT, width=45,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row2, text="Browse", font=FONT, command=self._browse_privacy_folder,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        tk.Button(row2, text="Clean All Photos", font=FONT_B, bg=BLUE, fg="white",
                  command=self._clean_privacy_folder, relief="flat", padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        self.privacy_folder_progress = ttk.Progressbar(self.privacy_folder_frame, mode="determinate", length=400)
        self.privacy_folder_progress.pack(fill="x", pady=(0,4))

        tk.Label(f, text="Metadata found:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(8,2))
        self.privacy_results = scrolledtext.ScrolledText(f, font=FONT_SM, height=10,
                                                          bg=BG2, relief="solid", bd=1,
                                                          state="disabled", padx=10, pady=8, wrap="word")
        self.privacy_results.pack(fill="both", expand=True, padx=20, pady=(0,6))

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,8))
        self.privacy_clean_btn = tk.Button(btn_row, text="Clean and Save", font=FONT_B,
                                            bg=BLUE, fg="white", command=self._clean_privacy_file,
                                            relief="flat", padx=14, cursor="hand2", state="disabled")
        self.privacy_clean_btn.pack(side="left")
        self.privacy_result_lbl = tk.Label(btn_row, text="", font=FONT_B, bg=BG, fg=GREEN)
        self.privacy_result_lbl.pack(side="left", padx=12)

    def _toggle_privacy_mode(self):
        if self.privacy_mode.get() == "single":
            self.privacy_folder_frame.pack_forget()
            self.privacy_single_frame.pack(fill="x", padx=20)
        else:
            self.privacy_single_frame.pack_forget()
            self.privacy_folder_frame.pack(fill="x", padx=20)

    def _browse_privacy_file(self):
        p = filedialog.askopenfilename(title="Select image file",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tiff *.bmp *.heic")])
        if p: self.privacy_path.set(p)

    def _browse_privacy_folder(self):
        d = filedialog.askdirectory(title="Select folder with photos")
        if d: self.privacy_fpath.set(d)

    def _scan_privacy_file(self):
        path = self.privacy_path.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        meta = get_all_metadata(path)
        self.privacy_results.config(state="normal")
        self.privacy_results.delete("1.0", "end")
        if not meta:
            self.privacy_results.insert("1.0", "No metadata found in this file.")
        else:
            for k, v in meta.items():
                if k == 'GPS_Decimal':
                    self.privacy_results.insert("end",
                        f"\u26a0  GPS LOCATION: {v} \u2014 this photo reveals your physical location!\n", "gps")
                elif k == 'GPS':
                    continue
                else:
                    self.privacy_results.insert("end", f"  {k}: {v}\n")
        self.privacy_results.tag_configure("gps", foreground=RED, font=FONT_B)
        self.privacy_results.config(state="disabled")
        self.privacy_clean_btn.config(state="normal")

    def _clean_privacy_file(self):
        path = self.privacy_path.get().strip()
        if not os.path.exists(path): return
        out_dir = str(Path(path).parent / "cleaned")
        result = strip_exif(path, out_dir)
        if result['ok']:
            self.privacy_result_lbl.config(text=f"\u2713 Cleaned \u2014 saved to {result['output']}", fg=GREEN)
        else:
            self.privacy_result_lbl.config(text=f"\u2717 Failed: {result.get('error','unknown')}", fg=RED)

    def _clean_privacy_folder(self):
        folder = self.privacy_fpath.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Not found", f"Folder not found:\n{folder}")
            return
        out_dir = str(Path(folder) / "cleaned")
        self.privacy_folder_progress["value"] = 0
        self.privacy_results.config(state="normal")
        self.privacy_results.delete("1.0", "end")
        self.privacy_results.insert("1.0", "Processing...\n")
        self.privacy_results.config(state="disabled")

        def run():
            result = strip_exif_folder(folder, out_dir,
                on_progress=lambda d,t,p: self.q.put(("privacy_progress", d, t, p)))
            self.q.put(("privacy_folder_done", result))

        threading.Thread(target=run, daemon=True).start()

    # ── OCR TAB ────────────────────────────────────────────────────────────

    def _build_ocr_tab(self):
        f = self.tab_ocr
        if not check_tesseract():
            warn = tk.Frame(f, bg="#fff0f0", relief="solid", bd=1)
            warn.pack(fill="x", padx=20, pady=(14,0))
            tk.Label(warn, text="Tesseract not found in app bundle — please report at github.com/s1meer/FileGuard/issues",
                     font=FONT_SM, bg="#fff0f0", fg=RED, padx=14, pady=8).pack(side="left")

        tk.Label(f, text="Extract text from any image or screenshot:",
                 font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14,6))

        drop_zone = tk.Frame(f, bg="#e8f4fd", relief="solid", bd=2, height=80)
        drop_zone.pack(fill="x", padx=20, pady=(0,8))
        drop_zone.pack_propagate(False)
        tk.Label(drop_zone, text="Drop image here  OR  use Browse",
                 font=FONT_B, bg="#e8f4fd", fg=BLUE).pack(expand=True)
        if HAS_DND:
            drop_zone.drop_target_register(DND_FILES)
            drop_zone.dnd_bind('<<Drop>>', lambda e: self.ocr_path.set(e.data.strip().strip('{}')))

        row = tk.Frame(f, bg=BG)
        row.pack(fill="x", padx=20, pady=(0,6))
        self.ocr_path = tk.StringVar()
        tk.Entry(row, textvariable=self.ocr_path, font=FONT, width=50,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row, text="Browse", font=FONT, command=self._browse_ocr_file,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))

        lang_row = tk.Frame(f, bg=BG)
        lang_row.pack(fill="x", padx=20, pady=(0,6))
        tk.Label(lang_row, text="Language:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        langs = [("English","eng"),("Hindi","hin"),("Arabic","ara"),
                 ("Chinese Simplified","chi_sim"),("Nepali","nep")]
        lang_display = [f"{n} ({c})" for n, c in langs]
        self._ocr_lang_codes = {f"{n} ({c})": c for n, c in langs}
        self.ocr_lang_display = tk.StringVar(value="English (eng)")
        ttk.Combobox(lang_row, textvariable=self.ocr_lang_display,
                     values=lang_display, font=FONT, width=24, state="readonly").pack(side="left", padx=(8,16))
        self.ocr_btn = tk.Button(lang_row, text="Extract Text", font=FONT_B, bg=BLUE, fg="white",
                                  command=self._run_ocr, relief="flat", padx=14, cursor="hand2")
        self.ocr_btn.pack(side="left")

        tk.Label(f, text="Extracted text:", font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(8,2))
        self.ocr_result = scrolledtext.ScrolledText(f, font=FONT_SM, height=10,
                                                     bg="white", fg="black", insertbackground="black",
                                                     relief="solid", bd=1,
                                                     padx=10, pady=8, wrap="word")
        self.ocr_result.pack(fill="both", expand=True, padx=20, pady=(0,8))

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,10))
        tk.Button(btn_row, text="Copy All Text", font=FONT, command=self._copy_ocr_text,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="Save as .txt", font=FONT, command=self._save_ocr_text,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=8)

    def _browse_ocr_file(self):
        p = filedialog.askopenfilename(title="Select image for OCR",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.bmp *.tiff *.gif *.webp")])
        if p: self.ocr_path.set(p)

    def _run_ocr(self):
        path = self.ocr_path.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("Not found", "Select an image first")
            return

        lang = self._ocr_lang_codes.get(self.ocr_lang_display.get(), "eng")

        self.ocr_btn.config(text="Extracting...", state="disabled")
        self.ocr_result.config(state="normal")
        self.ocr_result.delete("1.0", "end")
        self.ocr_result.insert("1.0", "Extracting text...")
        self.ocr_result.config(state="disabled", fg="black", bg="white")

        def run_thread():
            try:
                import pytesseract
                from PIL import Image, ImageEnhance

                # Set tesseract path
                for tp in ['/opt/homebrew/bin/tesseract', '/usr/local/bin/tesseract',
                           '/usr/bin/tesseract']:
                    if os.path.exists(tp):
                        pytesseract.pytesseract.tesseract_cmd = tp
                        break
                else:
                    tess_path = get_tesseract()
                    if tess_path:
                        pytesseract.pytesseract.tesseract_cmd = tess_path

                # Set tessdata
                for td in [os.path.join(os.path.dirname(__file__), 'tessdata'),
                           '/opt/homebrew/share/tessdata', '/usr/share/tessdata']:
                    if os.path.exists(td):
                        os.environ['TESSDATA_PREFIX'] = td
                        break
                else:
                    tessdata = get_tessdata()
                    if tessdata:
                        os.environ['TESSDATA_PREFIX'] = tessdata

                img = Image.open(path)
                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')

                # Scale up small images for better accuracy
                w, h = img.size
                if w < 1000 or h < 1000:
                    scale = max(2.0, 1500.0 / min(w, h))
                    img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

                # Enhance contrast
                img = ImageEnhance.Contrast(img).enhance(1.5)

                cfg = r'--oem 3 --psm 3 -c preserve_interword_spaces=1'
                text = pytesseract.image_to_string(img, lang=lang, config=cfg)

                result = text.strip() or (
                    "No text found.\n\nTips:\n"
                    "• Use a clear, high-resolution image\n"
                    "• Select the correct language\n"
                    "• Make sure text is not blurry")

                self.q.put(("ocr_done", result))
            except ImportError:
                self.q.put(("ocr_done", "pytesseract not installed.\nRun: pip3 install pytesseract"))
            except Exception as e:
                self.q.put(("ocr_done", f"OCR error: {e}"))

        threading.Thread(target=run_thread, daemon=True).start()

    def _copy_ocr_text(self):
        text = self.ocr_result.get("1.0", "end").strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("Copied", "Text copied to clipboard.")

    def _save_ocr_text(self):
        text = self.ocr_result.get("1.0", "end").strip()
        if not text:
            messagebox.showinfo("Empty", "No text to save.")
            return
        out = filedialog.asksaveasfilename(defaultextension=".txt",
            filetypes=[("Text files", "*.txt")])
        if out:
            with open(out, 'w', encoding='utf-8') as wf:
                wf.write(text)
            messagebox.showinfo("Saved", f"Saved to:\n{out}")

    # ── DUPLICATES TAB ──────────────────────────────────────────────────────

    def _build_duplicates_tab(self):
        f = self.tab_duplicates
        tk.Label(f, text="Find and delete duplicate files:",
                 font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14,4))
        row1 = tk.Frame(f, bg=BG)
        row1.pack(fill="x", padx=20, pady=(0,6))
        self.dup_folder = tk.StringVar(value=str(Path.home() / "Downloads"))
        tk.Entry(row1, textvariable=self.dup_folder, font=FONT, width=50,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row1, text="Browse", font=FONT, command=self._browse_dup_folder,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        row2 = tk.Frame(f, bg=BG)
        row2.pack(fill="x", padx=20, pady=(0,8))
        tk.Label(row2, text="File type:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        self.dup_filter = tk.StringVar(value="All files")
        ttk.Combobox(row2, textvariable=self.dup_filter,
                     values=["All files","Images","Videos","Documents"],
                     font=FONT, width=16, state="readonly").pack(side="left", padx=(8,16))
        self.dup_btn = tk.Button(row2, text="Find Duplicates", font=FONT_B, bg=BLUE, fg="white",
                                  command=self._start_dup_scan, relief="flat", padx=14, cursor="hand2")
        self.dup_btn.pack(side="left")
        self.dup_progress = ttk.Progressbar(f, mode="determinate", length=400)
        self.dup_progress.pack(fill="x", padx=20, pady=(0,4))
        self.dup_summary = tk.Label(f, text="", font=FONT_SM, bg=BG2, padx=16, pady=6, anchor="w")
        self.dup_summary.pack(fill="x", padx=20, pady=(0,4))

        list_frame = tk.Frame(f, bg=BG, relief="solid", bd=1)
        list_frame.pack(fill="both", expand=True, padx=20, pady=(0,4))
        self.dup_tree = ttk.Treeview(list_frame, columns=("keep","path","size"),
                                      show="tree headings", selectmode="extended", height=12)
        self.dup_tree.heading("keep", text="Keep?")
        self.dup_tree.heading("path", text="File Path")
        self.dup_tree.heading("size", text="Size")
        self.dup_tree.column("#0",   width=20)
        self.dup_tree.column("keep", width=60,  anchor="center")
        self.dup_tree.column("path", width=450)
        self.dup_tree.column("size", width=80,  anchor="e")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.dup_tree.yview)
        self.dup_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.dup_tree.pack(fill="both", expand=True)

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,10))
        tk.Button(btn_row, text="Auto-select: Keep Newest", font=FONT,
                  command=lambda: self._dup_auto_select("newest"),
                  relief="solid", bd=1, padx=8, cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="Auto-select: Keep Largest", font=FONT,
                  command=lambda: self._dup_auto_select("largest"),
                  relief="solid", bd=1, padx=8, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="Delete Selected (Trash)", font=FONT_B, bg="#ffeeee",
                  command=self._delete_dups, relief="solid", bd=1, padx=8, cursor="hand2").pack(side="left")

    def _browse_dup_folder(self):
        d = filedialog.askdirectory(title="Scan folder for duplicates")
        if d: self.dup_folder.set(d)

    def _start_dup_scan(self):
        folder = self.dup_folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Not found", f"Folder not found:\n{folder}")
            return
        self.dup_btn.config(text="Scanning...", state="disabled")
        self.dup_progress["value"] = 0
        self.dup_tree.delete(*self.dup_tree.get_children())
        self._dup_groups = {}

        def run():
            groups = find_duplicates(folder, file_filter=self.dup_filter.get(),
                on_progress=lambda d,t,p: self.q.put(("dup_progress", d, t, p)))
            self.q.put(("dup_done", groups))

        threading.Thread(target=run, daemon=True).start()

    def _dup_auto_select(self, mode):
        for group_id, paths in self._dup_groups.items():
            children = self.dup_tree.get_children(group_id)
            if not children: continue
            if mode == "newest":
                keep_idx = max(range(len(paths)), key=lambda i: paths[i].stat().st_mtime)
            else:
                keep_idx = max(range(len(paths)), key=lambda i: paths[i].stat().st_size)
            for i, child in enumerate(children):
                self.dup_tree.set(child, "keep", "KEEP" if i == keep_idx else "DELETE")

    def _delete_dups(self):
        try:
            from send2trash import send2trash
        except ImportError:
            messagebox.showerror("Missing", "send2trash not installed.\npip3 install send2trash")
            return
        to_delete = []
        for group_id, paths in self._dup_groups.items():
            for i, child in enumerate(self.dup_tree.get_children(group_id)):
                if self.dup_tree.set(child, "keep") == "DELETE" and i < len(paths):
                    to_delete.append(str(paths[i]))
        if not to_delete:
            messagebox.showinfo("Nothing selected", "Use Auto-select to mark files for deletion first.")
            return
        if messagebox.askyesno("Confirm", f"Move {len(to_delete)} files to Trash?"):
            for p in to_delete:
                try: send2trash(p)
                except Exception: pass
            messagebox.showinfo("Done", f"{len(to_delete)} files moved to Trash.\nUndo with Cmd+Z in Finder.")
            self._start_dup_scan()

    # ── RENAME TAB ─────────────────────────────────────────────────────────

    def _build_rename_tab(self):
        f = self.tab_rename
        tk.Label(f, text="Batch rename files with patterns:",
                 font=FONT_B, bg=BG, fg=TEXT).pack(anchor="w", padx=20, pady=(14,4))
        row1 = tk.Frame(f, bg=BG)
        row1.pack(fill="x", padx=20, pady=(0,6))
        self.ren_folder = tk.StringVar()
        tk.Entry(row1, textvariable=self.ren_folder, font=FONT, width=50,
                 relief="solid", bd=1).pack(side="left", fill="x", expand=True, ipady=5)
        tk.Button(row1, text="Browse", font=FONT, command=self._browse_ren_folder,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left", padx=(8,0))
        row2 = tk.Frame(f, bg=BG)
        row2.pack(fill="x", padx=20, pady=(0,6))
        tk.Label(row2, text="Filter:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        self.ren_filter = tk.StringVar(value="*")
        tk.Entry(row2, textvariable=self.ren_filter, font=FONT, width=14,
                 relief="solid", bd=1).pack(side="left", padx=(8,20), ipady=4)
        tk.Label(row2, text="Pattern:", font=FONT_B, bg=BG, fg=TEXT).pack(side="left")
        self.ren_pattern = tk.StringVar(value="{name}_{number:03d}")
        tk.Entry(row2, textvariable=self.ren_pattern, font=FONT, width=28,
                 relief="solid", bd=1).pack(side="left", padx=(8,0), ipady=4)
        tk.Label(f, text="Tokens: {name} {ext} {date} {number} {number:02d} {number:03d} {number:04d}",
                 font=("Helvetica", 11), bg=BG, fg=MUTED).pack(anchor="w", padx=20, pady=(0,6))
        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=20, pady=(0,6))
        tk.Button(btn_row, text="Preview", font=FONT_B, command=self._preview_rename,
                  relief="solid", bd=1, padx=12, cursor="hand2").pack(side="left")
        self.ren_apply_btn = tk.Button(btn_row, text="Rename All Files", font=FONT_B,
                                        bg=BLUE, fg="white", command=self._apply_rename,
                                        relief="flat", padx=14, cursor="hand2", state="disabled")
        self.ren_apply_btn.pack(side="left", padx=8)
        tk.Button(btn_row, text="Undo Last", font=FONT, command=self._undo_rename,
                  relief="solid", bd=1, padx=10, cursor="hand2").pack(side="left")

        tbl_frame = tk.Frame(f, bg=BG, relief="solid", bd=1)
        tbl_frame.pack(fill="both", expand=True, padx=20, pady=(0,4))
        self.ren_tree = ttk.Treeview(tbl_frame, columns=("before","after"), show="headings", height=16)
        self.ren_tree.heading("before", text="Before")
        self.ren_tree.heading("after",  text="After")
        self.ren_tree.column("before", width=340)
        self.ren_tree.column("after",  width=340)
        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self.ren_tree.yview)
        self.ren_tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.ren_tree.pack(fill="both", expand=True)
        self.ren_result = tk.Label(f, text="", font=FONT_B, bg=BG, fg=GREEN)
        self.ren_result.pack(anchor="w", padx=20, pady=(0,8))

    def _browse_ren_folder(self):
        d = filedialog.askdirectory(title="Select folder to rename files in")
        if d: self.ren_folder.set(d)

    def _preview_rename(self):
        folder = self.ren_folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Not found", f"Folder not found:\n{folder}")
            return
        pairs = preview_rename(folder, self.ren_filter.get(), self.ren_pattern.get())
        self.ren_tree.delete(*self.ren_tree.get_children())
        for old, new in pairs[:20]:
            self.ren_tree.insert("", "end", values=(old, new))
        if len(pairs) > 20:
            self.ren_tree.insert("", "end", values=(f"... and {len(pairs)-20} more", ""))
        self.rename_previewed = True
        self.ren_apply_btn.config(state="normal")
        self.ren_result.config(text=f"Preview: {len(pairs)} files will be renamed", fg=MUTED)

    def _apply_rename(self):
        if not self.rename_previewed:
            messagebox.showinfo("Preview first", "Click Preview before renaming.")
            return
        folder = self.ren_folder.get().strip()
        count = do_rename(folder, self.ren_filter.get(), self.ren_pattern.get(),
                          undo_file=self._rename_undo_file)
        self.ren_result.config(text=f"\u2713 Renamed {count} files", fg=GREEN)
        self.rename_previewed = False
        self.ren_apply_btn.config(state="disabled")

    def _undo_rename(self):
        count = undo_rename(self._rename_undo_file)
        if count:
            messagebox.showinfo("Undone", f"Reversed {count} renames.")
        else:
            messagebox.showinfo("Nothing to undo", "No previous rename found.")

    # ── TOOLS TAB ──────────────────────────────────────────────────────────

    def _build_tools_tab(self):
        f = self.tab_tools
        tk.Label(f, text="Utility tools:", font=FONT_B, bg=BG, fg=TEXT).pack(
            anchor="w", padx=20, pady=(12,8))
        grid = tk.Frame(f, bg=BG)
        grid.pack(fill="both", expand=True, padx=16, pady=(0,16))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        self._build_tool_hash(grid, 0, 0)
        self._build_tool_unarchive(grid, 0, 1)
        self._build_tool_qr(grid, 1, 0)
        self._build_tool_splitter(grid, 1, 1)
        self._build_tool_disk(grid, 2, 0)
        self._build_tool_diff(grid, 2, 1)

    def _tool_card(self, parent, row, col, title):
        card = tk.Frame(parent, bg=BG2, relief="solid", bd=1)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        tk.Label(card, text=title, font=FONT_B, bg=BG2, fg=TEXT,
                 anchor="w", padx=12, pady=8).pack(fill="x")
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x")
        inner = tk.Frame(card, bg=BG2)
        inner.pack(fill="both", expand=True, padx=10, pady=8)
        return inner

    def _build_tool_hash(self, parent, row, col):
        c = self._tool_card(parent, row, col, "Hash Verifier")
        self.hash_file = tk.StringVar()
        r1 = tk.Frame(c, bg=BG2); r1.pack(fill="x", pady=(0,4))
        tk.Entry(r1, textvariable=self.hash_file, font=FONT_SM, width=26,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(r1, text="Browse", font=FONT_SM, relief="solid", bd=1, padx=6, cursor="hand2",
                  bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                  command=lambda: self.hash_file.set(filedialog.askopenfilename() or self.hash_file.get())
                  ).pack(side="left", padx=(4,0))
        self.hash_expected = tk.StringVar()
        tk.Entry(c, textvariable=self.hash_expected, font=FONT_SM, width=42,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(fill="x", pady=(0,2), ipady=3)
        tk.Label(c, text="Paste expected SHA-256 hash above", font=("Helvetica",10), bg=BG2, fg=MUTED).pack(anchor="w")
        self.hash_result = tk.Label(c, text="", font=FONT_B, bg=BG2, fg=TEXT, anchor="w", wraplength=270)
        self.hash_result.pack(fill="x", pady=(4,0))
        tk.Button(c, text="Verify", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_hash_verify).pack(pady=(4,0), anchor="w")

    def _run_hash_verify(self):
        path = self.hash_file.get().strip()
        expected = self.hash_expected.get().strip()
        if not path or not expected:
            messagebox.showinfo("Missing", "Select a file and enter the expected hash.")
            return
        match, actual = verify_hash(path, expected)
        if match:
            self.hash_result.config(text="\u2713 MATCH \u2014 file is genuine", fg=GREEN)
        else:
            self.hash_result.config(text=f"\u2717 MISMATCH\nActual: {actual[:40]}...", fg=RED)

    def _build_tool_unarchive(self, parent, row, col):
        c = self._tool_card(parent, row, col, "Smart Unarchiver")
        self.arch_file = tk.StringVar()
        r1 = tk.Frame(c, bg=BG2); r1.pack(fill="x", pady=(0,4))
        tk.Entry(r1, textvariable=self.arch_file, font=FONT_SM, width=26,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(r1, text="Browse", font=FONT_SM, relief="solid", bd=1, padx=6, cursor="hand2",
                  bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                  command=lambda: self.arch_file.set(filedialog.askopenfilename() or self.arch_file.get())
                  ).pack(side="left", padx=(4,0))
        self.arch_result = tk.Label(c, text="", font=FONT_SM, bg=BG2, fg=TEXT,
                                     anchor="w", wraplength=270)
        self.arch_result.pack(fill="x", pady=(4,0))
        tk.Button(c, text="Extract", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_unarchive).pack(pady=(4,0), anchor="w")

    def _run_unarchive(self):
        path = self.arch_file.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        out_dir = str(Path(path).parent / (Path(path).stem + "_extracted"))
        self.arch_result.config(text="Extracting...")
        def run():
            try:
                extract_any(path, out_dir)
                self.q.put(("tool_msg", self.arch_result, f"\u2713 Extracted to:\n{out_dir}", GREEN))
            except Exception as e:
                self.q.put(("tool_msg", self.arch_result, f"\u2717 {e}", RED))
        threading.Thread(target=run, daemon=True).start()

    def _build_tool_qr(self, parent, row, col):
        c = self._tool_card(parent, row, col, "QR Code Reader")
        self.qr_file = tk.StringVar()
        r1 = tk.Frame(c, bg=BG2); r1.pack(fill="x", pady=(0,4))
        tk.Entry(r1, textvariable=self.qr_file, font=FONT_SM, width=26,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(r1, text="Browse", font=FONT_SM, relief="solid", bd=1, padx=6, cursor="hand2",
                  bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                  command=lambda: self.qr_file.set(
                      filedialog.askopenfilename(filetypes=[("Images","*.jpg *.jpeg *.png *.bmp")]) or self.qr_file.get())
                  ).pack(side="left", padx=(4,0))
        self.qr_result = tk.Label(c, text="", font=FONT_SM, bg=BG2, fg=TEXT,
                                   anchor="w", wraplength=270, justify="left")
        self.qr_result.pack(fill="x", pady=(4,0))
        tk.Button(c, text="Read QR", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_qr).pack(pady=(4,0), anchor="w")

    def _run_qr(self):
        path = self.qr_file.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        results = read_qr(path)
        if results:
            text = "\n".join(results)
            self.qr_result.config(text=text, fg=TEXT)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        else:
            self.qr_result.config(text="No QR codes found.", fg=MUTED)

    def _build_tool_splitter(self, parent, row, col):
        c = self._tool_card(parent, row, col, "File Splitter / Joiner")
        self.split_mode = tk.StringVar(value="split")
        mr = tk.Frame(c, bg=BG2); mr.pack(fill="x", pady=(0,4))
        tk.Radiobutton(mr, text="Split", variable=self.split_mode, value="split",
                       font=FONT_SM, bg=BG2, fg=TEXT, cursor="hand2").pack(side="left")
        tk.Radiobutton(mr, text="Join", variable=self.split_mode, value="join",
                       font=FONT_SM, bg=BG2, fg=TEXT, cursor="hand2").pack(side="left", padx=12)
        self.split_file_var = tk.StringVar()
        r1 = tk.Frame(c, bg=BG2); r1.pack(fill="x", pady=(0,4))
        tk.Entry(r1, textvariable=self.split_file_var, font=FONT_SM, width=22,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(r1, text="Browse", font=FONT_SM, relief="solid", bd=1, padx=6, cursor="hand2",
                  bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                  command=lambda: self.split_file_var.set(filedialog.askopenfilename() or self.split_file_var.get())
                  ).pack(side="left", padx=(4,0))
        sr = tk.Frame(c, bg=BG2); sr.pack(fill="x", pady=(0,4))
        tk.Label(sr, text="Chunk size:", font=FONT_SM, bg=BG2, fg=TEXT).pack(side="left")
        self.split_size = tk.StringVar(value="50")
        ttk.Combobox(sr, textvariable=self.split_size, values=["10","25","50","100","200"],
                     font=FONT_SM, width=6, state="readonly").pack(side="left", padx=(4,4))
        tk.Label(sr, text="MB", font=FONT_SM, bg=BG2, fg=TEXT).pack(side="left")
        self.split_result = tk.Label(c, text="", font=FONT_SM, bg=BG2, fg=TEXT, anchor="w", wraplength=270)
        self.split_result.pack(fill="x", pady=(4,0))
        tk.Button(c, text="Go", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_split_join).pack(pady=(4,0), anchor="w")

    def _run_split_join(self):
        path = self.split_file_var.get().strip()
        if not os.path.exists(path):
            messagebox.showerror("Not found", f"File not found:\n{path}")
            return
        mode = self.split_mode.get()
        self.split_result.config(text="Working...")
        def run():
            try:
                if mode == "split":
                    n = split_file(path, int(self.split_size.get()))
                    self.q.put(("tool_msg", self.split_result, f"\u2713 Split into {n} parts", GREEN))
                else:
                    out = join_files(path)
                    self.q.put(("tool_msg", self.split_result, f"\u2713 Joined \u2192 {os.path.basename(out)}", GREEN))
            except Exception as e:
                self.q.put(("tool_msg", self.split_result, f"\u2717 {e}", RED))
        threading.Thread(target=run, daemon=True).start()

    def _build_tool_disk(self, parent, row, col):
        c = self._tool_card(parent, row, col, "Disk Analyzer")
        self.disk_folder = tk.StringVar(value=str(Path.home()))
        r1 = tk.Frame(c, bg=BG2); r1.pack(fill="x", pady=(0,4))
        tk.Entry(r1, textvariable=self.disk_folder, font=FONT_SM, width=22,
                 relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(r1, text="Browse", font=FONT_SM, relief="solid", bd=1, padx=6, cursor="hand2",
                  bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                  command=lambda: self.disk_folder.set(filedialog.askdirectory() or self.disk_folder.get())
                  ).pack(side="left", padx=(4,0))
        self.disk_canvas = tk.Canvas(c, bg=BG2, height=110, highlightthickness=0)
        self.disk_canvas.pack(fill="x", pady=(4,0))
        tk.Button(c, text="Analyze", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_disk_analyze).pack(pady=(4,0), anchor="w")

    def _run_disk_analyze(self):
        folder = self.disk_folder.get().strip()
        if not os.path.isdir(folder): return
        self.disk_canvas.delete("all")
        self.disk_canvas.create_text(10, 10, text="Analyzing...", anchor="nw", font=FONT_SM, fill=MUTED)
        def run():
            sizes = get_folder_sizes(folder)
            self.q.put(("disk_done", sizes))
        threading.Thread(target=run, daemon=True).start()

    def _draw_disk_chart(self, sizes):
        c = self.disk_canvas
        c.delete("all")
        if not sizes:
            c.create_text(10, 10, text="No subdirectories found.", anchor="nw", font=FONT_SM, fill=MUTED)
            return
        max_sz = sizes[0][1] if sizes else 1
        bar_h = 13
        gap = 3
        label_w = 100
        right_pad = 70
        c.update_idletasks()
        cw = c.winfo_width() or 300
        for i, (name, sz) in enumerate(sizes[:8]):
            y = i * (bar_h + gap) + 4
            bar_max = max(cw - label_w - right_pad - 10, 20)
            bar_w = max(4, int(bar_max * sz / max_sz))
            color = "#cc2200" if sz > 1e9 else ("#b8860b" if sz > 1e8 else "#2d7a2d")
            c.create_text(label_w - 4, y + bar_h//2, text=name[:13], anchor="e",
                          font=("Helvetica", 10), fill=TEXT)
            c.create_rectangle(label_w, y, label_w + bar_w, y + bar_h, fill=color, outline="")
            c.create_text(label_w + bar_w + 4, y + bar_h//2, text=human_size(sz),
                          anchor="w", font=("Helvetica", 10), fill=MUTED)

    def _build_tool_diff(self, parent, row, col):
        c = self._tool_card(parent, row, col, "File Diff")
        self.diff_a = tk.StringVar()
        self.diff_b = tk.StringVar()
        for var, label in [(self.diff_a, "File A:"), (self.diff_b, "File B:")]:
            rf = tk.Frame(c, bg=BG2); rf.pack(fill="x", pady=(0,3))
            tk.Label(rf, text=label, font=FONT_SM, bg=BG2, fg=TEXT, width=7, anchor="w").pack(side="left")
            tk.Entry(rf, textvariable=var, font=FONT_SM, width=18,
                     relief="solid", bd=1, bg="white", fg="black", insertbackground="black").pack(side="left", fill="x", expand=True, ipady=3)
            tk.Button(rf, text="Browse", font=("Helvetica",10), relief="solid", bd=1, padx=4, cursor="hand2",
                      bg="#e8e8e8", fg="black", activebackground="#d0d0d0", activeforeground="black",
                      command=lambda v=var: v.set(filedialog.askopenfilename() or v.get())
                      ).pack(side="left", padx=(3,0))
        self.diff_result = scrolledtext.ScrolledText(c, font=("Courier", 10), height=6,
                                                      bg="white", fg="black", relief="solid", bd=1)
        self.diff_result.pack(fill="both", expand=True, pady=(4,0))
        tk.Button(c, text="Compare", font=FONT_B, bg=BLUE, fg="white", relief="flat",
                  activebackground="#1248a0", activeforeground="white",
                  cursor="hand2", command=self._run_diff).pack(pady=(4,0), anchor="w")

    def _run_diff(self):
        a = self.diff_a.get().strip()
        b = self.diff_b.get().strip()
        if not os.path.exists(a) or not os.path.exists(b):
            messagebox.showerror("Not found", "Both files must exist.")
            return
        self.diff_result.delete("1.0", "end")
        try:
            open(a).read(100); open(b).read(100)
            is_text = True
        except Exception:
            is_text = False
        lines = diff_text_files(a, b) if is_text else diff_binary_files(a, b)
        self.diff_result.tag_configure("add", background="#e6ffe6")
        self.diff_result.tag_configure("rem", background="#ffe6e6")
        for line in lines:
            if line.startswith('+') and not line.startswith('+++'):
                self.diff_result.insert("end", line, "add")
            elif line.startswith('-') and not line.startswith('---'):
                self.diff_result.insert("end", line, "rem")
            else:
                self.diff_result.insert("end", line)

    # ── Utilities ─────────────────────────────────────────

    def _do_direct_download(self, url, out_dir):
        """Download any direct file URL with progress."""
        import ssl, urllib.request

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        fname = url.split('/')[-1].split('?')[0]
        if not fname or '.' not in fname:
            fname = 'download'
        save_path = os.path.join(out_dir, fname)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': '*/*',
        }

        req = urllib.request.Request(url, headers=headers)
        self.q.put(("dl_log", "Connecting..."))

        with urllib.request.urlopen(req, context=ctx, timeout=60) as response:
            cd = response.headers.get('Content-Disposition', '')
            if 'filename=' in cd:
                import re
                m = re.search(r'filename=["\']?([^"\';\s]+)', cd)
                if m:
                    fname = m.group(1)
                    save_path = os.path.join(out_dir, fname)

            total = int(response.headers.get('Content-Length', 0))
            size_str = f"{round(total/1024/1024,1)} MB" if total > 1e6 else f"{round(total/1024,1)} KB" if total else "unknown size"
            self.q.put(("dl_log", f"File: {fname}  ({size_str})"))

            downloaded = 0
            with open(save_path, 'wb') as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 100)
                        done_mb = round(downloaded/1024/1024, 1)
                        total_mb = round(total/1024/1024, 1)
                        self.q.put(("dl_progress", pct, f"{fname} — {done_mb}/{total_mb} MB"))

        self.dl_output_path = save_path
        self.q.put(("dl_log", f"Saved: {save_path}"))
        self.q.put(("dl_finished", True))

    def _open_path(self, path):
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.call(["open", path])
            elif system == "Windows":
                os.startfile(path)
            else:
                subprocess.call(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open file:\n{e}")

    def _download_magnet(self, magnet_url, out_dir):
        import subprocess, shutil

        self.q.put(("dl_log", "Magnet link detected"))
        self.q.put(("dl_log", "Checking available torrent clients..."))

        # Try libtorrent
        try:
            import libtorrent as lt
            import time
            self.q.put(("dl_log", "Using libtorrent"))
            ses = lt.session({'listen_interfaces': '0.0.0.0:6881'})
            params = lt.parse_magnet_uri(magnet_url)
            params.save_path = out_dir
            handle = ses.add_torrent(params)
            self.q.put(("dl_log", "Fetching torrent metadata (may take 60s)..."))
            timeout = 120
            start = time.time()
            while not handle.has_metadata():
                if not getattr(self, 'download_running', True):
                    ses.remove_torrent(handle)
                    return
                if time.time() - start > timeout:
                    raise Exception("Timeout — no seeders found")
                time.sleep(1)
            info = handle.get_torrent_info()
            name = info.name()
            total = info.total_size()
            size_str = f"{round(total/1024/1024/1024,2)} GB" if total > 1e9 else f"{round(total/1024/1024,1)} MB"
            self.q.put(("dl_log", f"Torrent: {name}"))
            self.q.put(("dl_log", f"Size: {size_str}"))
            while not handle.is_seed():
                if not getattr(self, 'download_running', True):
                    ses.remove_torrent(handle)
                    return
                s = handle.status()
                pct = int(s.progress * 100)
                speed = round(s.download_rate / 1024, 1)
                peers = s.num_peers
                self.q.put(("dl_progress", pct, f"{name[:35]} | {speed} KB/s | {peers} peers"))
                time.sleep(2)
            self.dl_output_path = os.path.join(out_dir, name)
            self.q.put(("dl_finished", True))
            return
        except ImportError:
            self.q.put(("dl_log", "libtorrent not available"))
        except Exception as e:
            self.q.put(("dl_log", f"libtorrent: {e}"))

        # Try aria2c (bundled)
        try:
            from binaries import get_aria2c
            aria2c = get_aria2c()
        except Exception:
            aria2c = shutil.which('aria2c')

        if aria2c:
            self.q.put(("dl_log", f"Using aria2c: {aria2c}"))
            self.q.put(("dl_log", "Connecting to DHT network..."))
            cmd = [
                aria2c,
                '--dir', out_dir,
                '--seed-time=0',
                '--max-connection-per-server=4',
                '--enable-dht=true',
                '--bt-enable-lpd=true',
                '--follow-torrent=mem',
                '--summary-interval=5',
                magnet_url
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1)
            import re as _re
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue
                if not getattr(self, 'download_running', True):
                    proc.terminate()
                    return
                self.q.put(("dl_log", line))
                m = _re.search(r'\((\d+)%\)', line)
                if m:
                    self.q.put(("dl_progress", int(m.group(1)), line))
            proc.wait()
            if proc.returncode == 0:
                self.q.put(("dl_finished", True))
                self.dl_output_path = out_dir
            else:
                self.q.put(("dl_error", "aria2c failed — torrent may have no seeders"))
            return

        # Try webtorrent
        webtorrent = shutil.which('webtorrent')
        if webtorrent:
            self.q.put(("dl_log", f"Using webtorrent: {webtorrent}"))
            proc = subprocess.Popen(
                [webtorrent, 'download', magnet_url, '--out', out_dir],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if line:
                    self.q.put(("dl_log", line))
                if not getattr(self, 'download_running', True):
                    proc.terminate()
                    return
            proc.wait()
            if proc.returncode == 0:
                self.q.put(("dl_finished", True))
            else:
                self.q.put(("dl_error", "webtorrent failed"))
            return

        self.q.put(("dl_error",
            "No torrent client found.\n\n"
            "Install aria2: brew install aria2\n"
            "Or use a torrent app like Transmission."))


def main():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = FileGuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
