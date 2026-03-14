"""
fileguard_app.py - FileGuard Desktop Application
Real working GUI for Mac M1 using Python Tkinter + tkinterdnd2.
Tabs: SCAN | REPAIR | DOWNLOAD | INFO
Features: drag-drop repair, auto-diagnose, unknown format reporting, auto-update
"""

import os
import sys
import platform
import subprocess
import threading
import queue
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from pathlib import Path

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
        self.root.geometry("900x700")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(750, 580)

        self.q = queue.Queue()
        self.scan_running = False
        self.download_running = False
        self.scan_results = []
        self._pending_update_url = None
        self.repaired_output = None
        self.dl_output_path = None
        self.dl_process = None

        self._build_update_banner()
        self._build_header()
        self._build_tabs()
        self._poll_queue()

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
        nb.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        style = ttk.Style()
        style.configure("TNotebook.Tab", font=FONT_B, padding=[16, 8])

        self.tab_scan     = tk.Frame(nb, bg=BG)
        self.tab_repair   = tk.Frame(nb, bg=BG)
        self.tab_download = tk.Frame(nb, bg=BG)
        self.tab_info     = tk.Frame(nb, bg=BG)

        nb.add(self.tab_scan,     text="  Scan  ")
        nb.add(self.tab_repair,   text="  Repair  ")
        nb.add(self.tab_download, text="  Download  ")
        nb.add(self.tab_info,     text="  File Info  ")

        self._build_scan_tab()
        self._build_repair_tab()
        self._build_download_tab()
        self._build_info_tab()

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

        cols = ("risk", "name", "size", "type")
        self.scan_tree = ttk.Treeview(list_frame, columns=cols, show="headings",
                                       selectmode="browse", height=12)
        self.scan_tree.heading("risk", text="Risk")
        self.scan_tree.heading("name", text="File Name")
        self.scan_tree.heading("size", text="Size")
        self.scan_tree.heading("type", text="Type")
        self.scan_tree.column("risk", width=100, anchor="center")
        self.scan_tree.column("name", width=350)
        self.scan_tree.column("size", width=80, anchor="right")
        self.scan_tree.column("type", width=80, anchor="center")

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
        if len(vals) < 5:
            return
        idx = vals[4]
        r = self.scan_results[int(idx)]
        lines = [f"File: {r['path']}", f"Real type: {r['real_type'].upper()}  |  Size: {r['size_kb']} KB  |  Hash: {r['hash']}"]
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
                                                     bg=BG2, relief="solid", bd=1,
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
        self.dl_quality = tk.StringVar(value="Best quality (video+audio)")
        quality_opts = [
            "Best quality (video+audio)",
            "Audio only (MP3)",
            "720p",
            "480p",
            "360p (small file)",
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
                                                 bg=BG2, relief="solid", bd=1,
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
                import yt_dlp
                opts = {
                    "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
                    "progress_hooks": [progress_hook],
                    "quiet": True,
                    "no_warnings": True,
                }
                q_map = {
                    "Audio only (MP3)":           ("bestaudio/best", True),
                    "720p":                       ("bestvideo[height<=720]+bestaudio/best[height<=720]", False),
                    "480p":                       ("bestvideo[height<=480]+bestaudio/best[height<=480]", False),
                    "360p (small file)":          ("bestvideo[height<=360]+bestaudio/best[height<=360]", False),
                    "Best quality (video+audio)": ("bestvideo+bestaudio/best", False),
                }
                fmt, is_audio = q_map.get(quality, ("bestvideo+bestaudio/best", False))
                opts["format"] = fmt
                if is_audio:
                    opts["postprocessors"] = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3"}]
                self.q.put(("dl_log", f"Downloading from: {url}"))
                self.q.put(("dl_log", f"Quality: {quality}"))
                self.q.put(("dl_log", f"Saving to: {out_dir}"))
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

    def _open_downloaded_file(self):
        if self.dl_output_path:
            self._open_path(self.dl_output_path)

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
                        vals = (RISK_LABELS[risk], r["name"], f"{r['size_kb']} KB", r["real_type"], str(i))
                        self.scan_tree.insert("", "end", values=vals, tags=(risk,))

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

        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ── Utilities ─────────────────────────────────────────

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


def main():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = FileGuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
