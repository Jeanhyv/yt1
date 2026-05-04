#!/usr/bin/env python3
import json
import os
import queue
import signal
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "YT Endeavour Downloader"
COLORS = {
    "bg": "#140a2e",
    "panel": "#1c1240",
    "blue": "#37a5ff",
    "pink": "#ff4faf",
    "magenta": "#d349ff",
    "text": "#f8f7ff",
    "muted": "#c9bee8",
}


@dataclass
class DownloadTask:
    url: str
    kind: str
    quality: str
    output_dir: Path
    status: str = "Pendiente"
    progress: float = 0.0
    speed: str = "-"
    eta: str = "-"
    size: str = "-"
    downloaded: str = "-"
    title: str = "-"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1080x700")
        self.root.configure(bg=COLORS["bg"])

        self.tasks: list[DownloadTask] = []
        self.task_queue: queue.Queue[int] = queue.Queue()
        self.current_task_index: int | None = None
        self.current_proc: subprocess.Popen | None = None
        self.paused = False
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

        self.output_dir = Path.home() / "Descargas"

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=28)
        style.configure("Treeview.Heading", background=COLORS["magenta"], foreground="white")

        top = tk.Frame(self.root, bg=COLORS["panel"], padx=10, pady=8)
        top.pack(fill="x", padx=12, pady=12)

        self.url_var = tk.StringVar()
        tk.Label(top, text="URL:", bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
        tk.Entry(top, textvariable=self.url_var, width=58, bg="#241a4d", fg=COLORS["text"], insertbackground="white").pack(side="left", padx=8)

        self.kind_var = tk.StringVar(value="video")
        tk.Radiobutton(top, text="Video", variable=self.kind_var, value="video", bg=COLORS["panel"], fg=COLORS["text"], selectcolor=COLORS["blue"]).pack(side="left", padx=(6, 0))
        tk.Radiobutton(top, text="Música", variable=self.kind_var, value="audio", bg=COLORS["panel"], fg=COLORS["text"], selectcolor=COLORS["blue"]).pack(side="left", padx=(4, 10))

        self.quality_var = tk.StringVar(value="best")
        ttk.Combobox(top, textvariable=self.quality_var, width=14, values=["best", "1080", "720", "480", "360", "mp3"]).pack(side="left", padx=4)

        self.add_btn = tk.Button(top, text="Nuevo", command=self.add_task, bg=COLORS["blue"], fg="white")
        self.add_btn.pack(side="left", padx=4)

        controls = tk.Frame(self.root, bg=COLORS["bg"])
        controls.pack(fill="x", padx=12)
        tk.Button(controls, text="Descargar todo", command=self.start_all, bg=COLORS["magenta"], fg="white").pack(side="left", padx=4)
        tk.Button(controls, text="Pausar todo", command=self.pause_all, bg="#7351d4", fg="white").pack(side="left", padx=4)
        tk.Button(controls, text="Detener todo", command=self.stop_all, bg="#da2b53", fg="white").pack(side="left", padx=4)
        tk.Button(controls, text="Seleccionar carpeta", command=self.select_output_dir, bg="#2f7cba", fg="white").pack(side="left", padx=4)

        self.dir_label = tk.Label(controls, text=f"Guardando en: {self.output_dir}", bg=COLORS["bg"], fg=COLORS["muted"])
        self.dir_label.pack(side="left", padx=18)

        cols = ("titulo", "tipo", "estado", "progreso", "velocidad", "eta", "peso", "fecha")
        self.tree = ttk.Treeview(self.root, columns=cols, show="headings")
        for col, txt, w in [
            ("titulo", "Título", 230), ("tipo", "Tipo", 70), ("estado", "Estado", 100),
            ("progreso", "Progreso", 100), ("velocidad", "Velocidad", 90), ("eta", "ETA", 70),
            ("peso", "Peso", 90), ("fecha", "Fecha", 150)
        ]:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=12)

        self.status_var = tk.StringVar(value="Listo.")
        tk.Label(self.root, textvariable=self.status_var, bg=COLORS["panel"], fg=COLORS["text"], anchor="w").pack(fill="x", side="bottom")

    def add_task(self):
        url = self.url_var.get().strip()
        if not url:
            return
        kind = self.kind_var.get()
        quality = self.quality_var.get().strip().lower()
        task = DownloadTask(url=url, kind=kind, quality=quality, output_dir=self.output_dir)
        self.tasks.append(task)
        self.tree.insert("", "end", iid=str(len(self.tasks)-1), values=(task.title, kind, task.status, "0%", task.speed, task.eta, task.size, task.created_at))
        self.url_var.set("")

    def start_all(self):
        for i, t in enumerate(self.tasks):
            if t.status in ("Pendiente", "Pausada", "Error"):
                self.task_queue.put(i)
        self.status_var.set("Descargas en cola.")

    def pause_all(self):
        if self.current_proc and self.current_proc.poll() is None:
            os.kill(self.current_proc.pid, signal.SIGSTOP)
            self.paused = True
            self._set_status(self.current_task_index, "Pausada")

    def stop_all(self):
        while not self.task_queue.empty():
            self.task_queue.get_nowait()
        if self.current_proc and self.current_proc.poll() is None:
            self.current_proc.terminate()
        for i, t in enumerate(self.tasks):
            if t.status in ("Pendiente", "En progreso", "Pausada"):
                self._set_status(i, "Detenida")
        self.status_var.set("Descargas detenidas.")

    def select_output_dir(self):
        selected = filedialog.askdirectory(initialdir=str(self.output_dir))
        if selected:
            self.output_dir = Path(selected)
            self.dir_label.config(text=f"Guardando en: {self.output_dir}")

    def _worker(self):
        while True:
            idx = self.task_queue.get()
            if idx >= len(self.tasks):
                continue
            task = self.tasks[idx]
            if task.status == "Completada":
                continue
            self.current_task_index = idx
            self._run_task(idx)

    def _run_task(self, idx: int):
        task = self.tasks[idx]
        self._set_status(idx, "En progreso")
        out_tpl = str(task.output_dir / "%(title).120s.%(ext)s")

        if task.kind == "audio" or task.quality == "mp3":
            cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "--newline", "-o", out_tpl, task.url]
        else:
            if task.quality in {"1080", "720", "480", "360"}:
                fmt = f"bestvideo[height<={task.quality}]+bestaudio/best[height<={task.quality}]"
            else:
                fmt = "bestvideo+bestaudio/best"
            cmd = ["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--newline", "-o", out_tpl, task.url]

        self.current_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        for raw in self.current_proc.stdout:
            line = raw.strip()
            if "[download]" in line:
                self._parse_progress(idx, line)
            elif line.startswith("[Merger]"):
                self.status_var.set("Uniendo video y audio...")
            elif "Destination" in line or "Writing video description" in line:
                pass
            elif line.startswith("[ExtractAudio]"):
                self.status_var.set("Extrayendo audio...")

        code = self.current_proc.wait()
        if code == 0:
            self._set_status(idx, "Completada")
            self.tasks[idx].progress = 100.0
            self._refresh_row(idx)
        else:
            self._set_status(idx, "Error")

    def _parse_progress(self, idx: int, line: str):
        task = self.tasks[idx]
        try:
            # formato tipico: [download]  12.3% of 50.30MiB at 1.20MiB/s ETA 00:30
            parts = line.replace("[download]", "").strip().split()
            if parts and parts[0].endswith("%"):
                task.progress = float(parts[0].replace("%", ""))
            if "of" in parts:
                task.size = parts[parts.index("of") + 1]
            if "at" in parts:
                task.speed = parts[parts.index("at") + 1]
            if "ETA" in parts:
                task.eta = parts[parts.index("ETA") + 1]
            self._refresh_row(idx)
        except Exception:
            return

    def _set_status(self, idx: int | None, status: str):
        if idx is None:
            return
        self.tasks[idx].status = status
        self._refresh_row(idx)

    def _refresh_row(self, idx: int):
        task = self.tasks[idx]
        prog = f"{task.progress:.1f}%"
        self.tree.item(str(idx), values=(task.title if task.title != "-" else task.url[:45], task.kind, task.status, prog, task.speed, task.eta, task.size, task.created_at))


if __name__ == "__main__":
    root = tk.Tk()
    app = DownloaderApp(root)
    root.mainloop()
