#!/usr/bin/env python3
import json
import os
import queue
import re
import signal
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.request import urlopen

from PIL import Image, ImageTk

APP_TITLE = "YT Endeavour Downloader"
COLORS = {
    "bg": "#120a2d", "panel": "#1e1244", "panel2": "#241957",
    "blue": "#38a5ff", "pink": "#ff4daa", "magenta": "#c852ff",
    "text": "#f8f6ff", "muted": "#c8bde7",
}


@dataclass
class DownloadTask:
    url: str
    kind: str
    quality: str
    output_dir: Path
    title: str = "-"
    thumbnail_url: str = ""
    status: str = "Pendiente"
    progress: float = 0.0
    speed: str = "-"
    eta: str = "-"
    size: str = "-"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x760")
        self.root.configure(bg=COLORS["bg"])

        self.tasks = []
        self.task_queue = queue.Queue()
        self.current_task_index = None
        self.current_proc = None
        self.paused = False
        self.thumbnail_ref = None

        self.output_dir = Path.home() / "Descargas"
        self.kind_var = tk.StringVar(value="video")
        self.quality_var = tk.StringVar(value="best")
        self.url_var = tk.StringVar()

        threading.Thread(target=self._worker, daemon=True).start()
        self._build_ui()

    def _build_ui(self):
        self._build_custom_header()
        self._build_toolbar()
        self._build_config()
        self._build_body()
        self.status_var = tk.StringVar(value="Listo")
        tk.Label(self.root, textvariable=self.status_var, bg=COLORS["panel"], fg=COLORS["text"], anchor="w").pack(fill="x")

    def _build_custom_header(self):
        hdr = tk.Frame(self.root, bg=COLORS["panel"], height=36)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        tk.Label(hdr, text="◉", fg=COLORS["blue"], bg=COLORS["panel"], font=("Arial", 14, "bold")).pack(side="left", padx=8)
        tk.Label(hdr, text=APP_TITLE, fg=COLORS["text"], bg=COLORS["panel"], font=("Arial", 11, "bold")).pack(side="left")

        menu_btn = tk.Menubutton(hdr, text="☰", bg=COLORS["panel2"], fg=COLORS["text"], relief="flat")
        m = tk.Menu(menu_btn, tearoff=0)
        m.add_command(label="Nuevo", command=self.open_new_dialog)
        m.add_command(label="Pausar todo", command=self.pause_all)
        m.add_command(label="Detener todo", command=self.stop_all)
        m.add_separator()
        m.add_command(label="Salir", command=self.root.destroy)
        menu_btn.configure(menu=m)
        for text, cmd in [("—", self.root.iconify), ("□", self._toggle_max), ("✕", self.root.destroy)]:
            tk.Button(hdr, text=text, command=cmd, bg=COLORS["panel2"], fg=COLORS["text"], bd=0, width=3).pack(side="right", padx=2)
        menu_btn.pack(side="right", padx=4)

    def _toggle_max(self):
        if self.root.state() == "zoomed":
            self.root.state("normal")
        else:
            self.root.state("zoomed")

    def _build_toolbar(self):
        tb = tk.Frame(self.root, bg=COLORS["panel2"], padx=10, pady=8)
        tb.pack(fill="x", padx=10, pady=8)
        tk.Button(tb, text="Nuevo", command=self.open_new_dialog, bg=COLORS["blue"], fg="white").pack(side="left", padx=4)
        tk.Button(tb, text="Reanudar", command=self.start_all, bg=COLORS["magenta"], fg="white").pack(side="left", padx=4)
        tk.Button(tb, text="Pausar todo", command=self.pause_all, bg="#7351d4", fg="white").pack(side="left", padx=4)
        tk.Button(tb, text="Detener todo", command=self.stop_all, bg="#d3345f", fg="white").pack(side="left", padx=4)

    def _build_config(self):
        cfg = tk.Frame(self.root, bg=COLORS["panel2"], padx=10, pady=8)
        cfg.pack(fill="x", padx=10)
        tk.Label(cfg, text="URL:", bg=COLORS["panel2"], fg=COLORS["text"]).grid(row=0, column=0)
        tk.Entry(cfg, textvariable=self.url_var, width=84, bg="#2f2160", fg=COLORS["text"], insertbackground="white").grid(row=0, column=1, columnspan=5, padx=6)

        tk.Radiobutton(cfg, text="Video", value="video", variable=self.kind_var, command=self._refresh_quality_options, bg=COLORS["panel2"], fg=COLORS["text"], selectcolor=COLORS["blue"]).grid(row=1, column=1, sticky="w")
        tk.Radiobutton(cfg, text="Música", value="audio", variable=self.kind_var, command=self._refresh_quality_options, bg=COLORS["panel2"], fg=COLORS["text"], selectcolor=COLORS["blue"]).grid(row=1, column=2, sticky="w")
        tk.Label(cfg, text="Calidad:", bg=COLORS["panel2"], fg=COLORS["text"]).grid(row=1, column=3)
        self.quality_combo = ttk.Combobox(cfg, textvariable=self.quality_var, width=14)
        self.quality_combo.grid(row=1, column=4)
        self._refresh_quality_options()
        tk.Button(cfg, text="Carpeta", command=self.select_output_dir, bg=COLORS["blue"], fg="white").grid(row=1, column=5, padx=6)

    def _refresh_quality_options(self):
        if self.kind_var.get() == "audio":
            vals = ["mp3", "m4a", "wav"]
            if self.quality_var.get() not in vals:
                self.quality_var.set("mp3")
        else:
            vals = ["best", "2160", "1440", "1080", "720", "480", "360"]
            if self.quality_var.get() not in vals:
                self.quality_var.set("best")
        self.quality_combo["values"] = vals

    def _build_body(self):
        body = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=8)
        left, right = tk.Frame(body, bg=COLORS["panel"]), tk.Frame(body, bg=COLORS["panel"])
        body.add(left, minsize=320)
        body.add(right)
        self.thumb_label = tk.Label(left, text="Miniatura", bg="#0f0a22", fg=COLORS["muted"])
        self.thumb_label.pack(fill="both", expand=True, padx=8, pady=8)

        cols = ("titulo", "tipo", "estado", "progreso", "velocidad", "eta", "peso", "fecha")
        self.tree = ttk.Treeview(right, columns=cols, show="headings")
        for c, t, w in [("titulo", "Título", 280), ("tipo", "Tipo", 80), ("estado", "Estado", 100), ("progreso", "Progreso", 90), ("velocidad", "Velocidad", 100), ("eta", "ETA", 80), ("peso", "Peso", 90), ("fecha", "Fecha", 160)]:
            self.tree.heading(c, text=t); self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def open_new_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Nueva descarga")
        d.geometry("560x180")
        d.configure(bg=COLORS["panel2"])
        tk.Label(d, text="Pega URL (video o playlist):", bg=COLORS["panel2"], fg=COLORS["text"]).pack(anchor="w", padx=12, pady=(12, 4))
        v = tk.StringVar(value=self.url_var.get())
        tk.Entry(d, textvariable=v, width=70).pack(padx=12)
        tk.Button(d, text="Agregar", command=lambda: (self.url_var.set(v.get().strip()), self.add_task(), d.destroy()), bg=COLORS["magenta"], fg="white").pack(pady=14)

    def add_task(self):
        url = self.url_var.get().strip()
        if not url:
            return
        entries = self._fetch_entries(url)
        for e in entries:
            task = DownloadTask(url=e["url"], kind=self.kind_var.get(), quality=self.quality_var.get(), output_dir=self.output_dir, title=e["title"], thumbnail_url=e.get("thumbnail", ""))
            self.tasks.append(task)
            i = len(self.tasks)-1
            self.tree.insert("", "end", iid=str(i), values=(task.title, task.kind, task.status, "0%", task.speed, task.eta, task.size, task.created_at))
        self.status_var.set(f"Añadidos {len(entries)} elemento(s)")

    def _fetch_entries(self, url):
        cmd = ["yt-dlp", "-J", url]
        try:
            data = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)
            if data.get("entries"):
                out = []
                for x in data["entries"]:
                    if not x:
                        continue
                    page = x.get("webpage_url") or x.get("url")
                    out.append({"url": page, "title": x.get("title", page), "thumbnail": x.get("thumbnail", "")})
                return out
            return [{"url": url, "title": data.get("title", url), "thumbnail": data.get("thumbnail", "")}]
        except Exception:
            return [{"url": url, "title": url, "thumbnail": ""}]

    def start_all(self):
        for i, t in enumerate(self.tasks):
            if t.status in ("Pendiente", "Pausada", "Detenida", "Error"):
                self.task_queue.put(i)

    def pause_all(self):
        if self.current_proc and self.current_proc.poll() is None:
            os.kill(self.current_proc.pid, signal.SIGSTOP)
            self.paused = True
            self._set_status(self.current_task_index, "Pausada")

    def stop_all(self):
        while not self.task_queue.empty(): self.task_queue.get_nowait()
        if self.current_proc and self.current_proc.poll() is None: self.current_proc.terminate()

    def select_output_dir(self):
        s = filedialog.askdirectory(initialdir=str(self.output_dir))
        if s: self.output_dir = Path(s)

    def _worker(self):
        while True:
            idx = self.task_queue.get()
            if idx < len(self.tasks): self._run_task(idx)

    def _run_task(self, idx):
        t = self.tasks[idx]
        self.current_task_index = idx
        self._set_status(idx, "En progreso")
        out = str(t.output_dir / "%(title).120s.%(ext)s")
        if t.kind == "audio":
            cmd = ["yt-dlp", "-x", "--audio-format", t.quality if t.quality in ["mp3", "m4a", "wav"] else "mp3", "--newline", "-o", out, t.url]
        else:
            fmt = f"bestvideo[height<={t.quality}]+bestaudio/best[height<={t.quality}]" if t.quality.isdigit() else "bestvideo+bestaudio/best"
            cmd = ["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--newline", "-o", out, t.url]
        self.current_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in self.current_proc.stdout:
            if "[download]" in line: self._parse_progress(idx, line)
        self._set_status(idx, "Completada" if self.current_proc.wait() == 0 else "Error")

    def _parse_progress(self, idx, line):
        t = self.tasks[idx]
        m = re.search(r"(\d+\.\d+)%", line)
        if m: t.progress = float(m.group(1))
        p = line.split()
        if "of" in p and p.index("of")+1 < len(p): t.size = p[p.index("of")+1]
        if "at" in p and p.index("at")+1 < len(p): t.speed = p[p.index("at")+1]
        if "ETA" in p and p.index("ETA")+1 < len(p): t.eta = p[p.index("ETA")+1]
        self._refresh_row(idx)

    def _set_status(self, idx, s):
        if idx is None: return
        self.tasks[idx].status = s
        self._refresh_row(idx)

    def _refresh_row(self, idx):
        t = self.tasks[idx]
        self.tree.item(str(idx), values=(t.title, t.kind, t.status, f"{t.progress:.1f}%", t.speed, t.eta, t.size, t.created_at))

    def on_select(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        th = self.tasks[int(sel[0])].thumbnail_url
        if not th:
            self.thumb_label.config(text="Sin miniatura", image="")
            return
        try:
            data = urlopen(th, timeout=12).read()
            img = Image.open(__import__('io').BytesIO(data)).resize((300, 180))
            self.thumbnail_ref = ImageTk.PhotoImage(img)
            self.thumb_label.config(image=self.thumbnail_ref, text="")
        except Exception:
            self.thumb_label.config(text="No se pudo cargar miniatura", image="")


if __name__ == "__main__":
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
