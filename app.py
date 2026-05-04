#!/usr/bin/env python3
import os
import queue
import re
import signal
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.request import urlopen

APP_TITLE = "YT Endeavour Downloader"
COLORS = {
    "bg": "#120a2d",
    "panel": "#1e1244",
    "panel2": "#241957",
    "blue": "#38a5ff",
    "pink": "#ff4daa",
    "magenta": "#c852ff",
    "text": "#f8f6ff",
    "muted": "#c8bde7",
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
    downloaded: str = "-"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class DownloaderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1280x760")
        self.root.configure(bg=COLORS["bg"])

        self.tasks: list[DownloadTask] = []
        self.task_queue: queue.Queue[int] = queue.Queue()
        self.current_task_index: int | None = None
        self.current_proc: subprocess.Popen | None = None
        self.paused = False
        self.thumbnail_refs = []

        self.output_dir = Path.home() / "Descargas"
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

        self._build_ui()

    def _build_ui(self):
        self._build_menu()

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=28)
        style.configure("Treeview.Heading", background=COLORS["magenta"], foreground="white")

        toolbar = tk.Frame(self.root, bg=COLORS["panel"], padx=10, pady=8)
        toolbar.pack(fill="x", padx=10, pady=(10, 6))
        tk.Button(toolbar, text="Nuevo", command=self.add_task, bg=COLORS["blue"], fg="white").pack(side="left", padx=4)
        tk.Button(toolbar, text="Descargar todo", command=self.start_all, bg=COLORS["magenta"], fg="white").pack(side="left", padx=4)
        tk.Button(toolbar, text="Pausar todo", command=self.pause_all, bg="#7351d4", fg="white").pack(side="left", padx=4)
        tk.Button(toolbar, text="Detener todo", command=self.stop_all, bg="#d3345f", fg="white").pack(side="left", padx=4)
        tk.Button(toolbar, text="Reanudar", command=self.resume_all, bg="#2f7cba", fg="white").pack(side="left", padx=4)

        config = tk.Frame(self.root, bg=COLORS["panel2"], padx=10, pady=8)
        config.pack(fill="x", padx=10, pady=(0, 8))

        self.url_var = tk.StringVar()
        tk.Label(config, text="Ingresar URL:", bg=COLORS["panel2"], fg=COLORS["text"]).grid(row=0, column=0, sticky="w")
        tk.Entry(config, textvariable=self.url_var, width=70, bg="#2f2160", fg=COLORS["text"], insertbackground="white").grid(row=0, column=1, columnspan=4, padx=8, sticky="we")

        self.kind_var = tk.StringVar(value="video")
        tk.Checkbutton(config, text="Video", variable=self.kind_var, onvalue="video", offvalue="audio", bg=COLORS["panel2"], fg=COLORS["text"], selectcolor=COLORS["blue"]).grid(row=1, column=1, sticky="w")
        tk.Checkbutton(config, text="Música", variable=self.kind_var, onvalue="audio", offvalue="video", bg=COLORS["panel2"], fg=COLORS["text"], selectcolor=COLORS["blue"]).grid(row=1, column=2, sticky="w")

        self.quality_var = tk.StringVar(value="best")
        tk.Label(config, text="Calidad:", bg=COLORS["panel2"], fg=COLORS["text"]).grid(row=1, column=3, sticky="e")
        ttk.Combobox(config, textvariable=self.quality_var, width=12,
                     values=["best", "2160", "1440", "1080", "720", "480", "360", "mp3"]).grid(row=1, column=4, padx=6)

        tk.Button(config, text="Seleccionar carpeta", command=self.select_output_dir, bg=COLORS["blue"], fg="white").grid(row=1, column=5, padx=8)
        self.dir_label = tk.Label(config, text=f"Guardando en: {self.output_dir}", bg=COLORS["panel2"], fg=COLORS["muted"])
        self.dir_label.grid(row=2, column=1, columnspan=5, sticky="w", pady=(4, 0))

        body = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body, bg=COLORS["panel"])
        right = tk.Frame(body, bg=COLORS["panel"])
        body.add(left, minsize=280)
        body.add(right)

        tk.Label(left, text="Imagen de video/música", bg=COLORS["panel"], fg=COLORS["text"]).pack(anchor="w", padx=8, pady=8)
        self.thumb_label = tk.Label(left, text="Sin miniatura", bg="#0f0a22", fg=COLORS["muted"], width=34, height=18)
        self.thumb_label.pack(padx=8, pady=8, fill="both", expand=True)

        cols = ("titulo", "tipo", "estado", "progreso", "velocidad", "eta", "peso", "fecha")
        self.tree = ttk.Treeview(right, columns=cols, show="headings")
        for col, txt, w in [
            ("titulo", "Título", 280), ("tipo", "Tipo", 80), ("estado", "Estado", 110),
            ("progreso", "Progreso", 90), ("velocidad", "Velocidad", 100), ("eta", "ETA", 90),
            ("peso", "Peso", 90), ("fecha", "Fecha", 160)
        ]:
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        self.status_var = tk.StringVar(value="Listo")
        tk.Label(self.root, textvariable=self.status_var, bg=COLORS["panel"], fg=COLORS["text"], anchor="w").pack(fill="x")

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_archivo = tk.Menu(menubar, tearoff=0)
        m_archivo.add_command(label="Nuevo", command=self.add_task)
        m_archivo.add_command(label="Seleccionar carpeta", command=self.select_output_dir)
        m_archivo.add_separator()
        m_archivo.add_command(label="Salir", command=self.root.destroy)

        m_descarga = tk.Menu(menubar, tearoff=0)
        m_descarga.add_command(label="Descargar todo", command=self.start_all)
        m_descarga.add_command(label="Pausar todo", command=self.pause_all)
        m_descarga.add_command(label="Reanudar", command=self.resume_all)
        m_descarga.add_command(label="Detener todo", command=self.stop_all)

        m_calidad = tk.Menu(m_descarga, tearoff=0)
        for q in ["2160", "1440", "1080", "720", "480", "360", "best", "mp3"]:
            m_calidad.add_radiobutton(label=q, value=q, variable=self.quality_var)
        m_descarga.add_cascade(label="Calidad", menu=m_calidad)

        m_ayuda = tk.Menu(menubar, tearoff=0)
        m_ayuda.add_command(label="Acerca de", command=lambda: messagebox.showinfo(APP_TITLE, "Descargador para EndeavourOS"))

        menubar.add_cascade(label="Archivo", menu=m_archivo)
        menubar.add_cascade(label="Descargas", menu=m_descarga)
        menubar.add_cascade(label="Ayuda", menu=m_ayuda)
        self.root.config(menu=menubar)

    def add_task(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Falta URL", "Ingresa una URL.")
            return
        kind = self.kind_var.get()
        quality = self.quality_var.get().lower()
        meta = self._fetch_metadata(url)
        task = DownloadTask(url=url, kind=kind, quality=quality, output_dir=self.output_dir, title=meta.get("title", "-"), thumbnail_url=meta.get("thumbnail", ""))
        self.tasks.append(task)
        idx = len(self.tasks) - 1
        self.tree.insert("", "end", iid=str(idx), values=(task.title, kind, task.status, "0%", task.speed, task.eta, task.size, task.created_at))
        self.url_var.set("")
        self.status_var.set(f"Añadido: {task.title}")

    def _fetch_metadata(self, url: str) -> dict:
        cmd = ["yt-dlp", "-J", "--no-playlist", url]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            import json
            data = json.loads(p.stdout)
            return {"title": data.get("title", "-"), "thumbnail": data.get("thumbnail", "")}
        except Exception:
            return {"title": url, "thumbnail": ""}

    def start_all(self):
        for i, t in enumerate(self.tasks):
            if t.status in ("Pendiente", "Pausada", "Error", "Detenida"):
                self.task_queue.put(i)
        self.status_var.set("Descargas en cola")

    def pause_all(self):
        if self.current_proc and self.current_proc.poll() is None:
            os.kill(self.current_proc.pid, signal.SIGSTOP)
            self.paused = True
            self._set_status(self.current_task_index, "Pausada")

    def resume_all(self):
        if self.current_proc and self.paused:
            os.kill(self.current_proc.pid, signal.SIGCONT)
            self.paused = False
            self._set_status(self.current_task_index, "En progreso")

    def stop_all(self):
        while not self.task_queue.empty():
            self.task_queue.get_nowait()
        if self.current_proc and self.current_proc.poll() is None:
            self.current_proc.terminate()
        for i, t in enumerate(self.tasks):
            if t.status in ("Pendiente", "En progreso", "Pausada"):
                self._set_status(i, "Detenida")
        self.status_var.set("Detenido")

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
            if self.tasks[idx].status == "Completada":
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
            if task.quality in {"2160", "1440", "1080", "720", "480", "360"}:
                fmt = f"bestvideo[height<={task.quality}]+bestaudio/best[height<={task.quality}]"
            else:
                fmt = "bestvideo+bestaudio/best"
            cmd = ["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--newline", "-o", out_tpl, task.url]

        self.current_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for raw in self.current_proc.stdout:
            line = raw.strip()
            if "[download]" in line:
                self._parse_progress(idx, line)

        code = self.current_proc.wait()
        self._set_status(idx, "Completada" if code == 0 else "Error")
        if code == 0:
            self.tasks[idx].progress = 100.0
            self._refresh_row(idx)

    def _parse_progress(self, idx: int, line: str):
        task = self.tasks[idx]
        m = re.search(r"(\d+\.\d+)%", line)
        if m:
            task.progress = float(m.group(1))
        p = line.split()
        if "of" in p and p.index("of") + 1 < len(p):
            task.size = p[p.index("of") + 1]
        if "at" in p and p.index("at") + 1 < len(p):
            task.speed = p[p.index("at") + 1]
        if "ETA" in p and p.index("ETA") + 1 < len(p):
            task.eta = p[p.index("ETA") + 1]
        self._refresh_row(idx)

    def _set_status(self, idx: int | None, status: str):
        if idx is None:
            return
        self.tasks[idx].status = status
        self._refresh_row(idx)

    def _refresh_row(self, idx: int):
        t = self.tasks[idx]
        self.tree.item(str(idx), values=(t.title, t.kind, t.status, f"{t.progress:.1f}%", t.speed, t.eta, t.size, t.created_at))

    def on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        thumb = self.tasks[idx].thumbnail_url
        if not thumb:
            self.thumb_label.configure(text="Sin miniatura", image="")
            return
        try:
            raw = urlopen(thumb, timeout=10).read()
            img = tk.PhotoImage(data=BytesIO(raw).getvalue())
            self.thumbnail_refs.append(img)
            self.thumb_label.configure(image=img, text="")
        except Exception:
            self.thumb_label.configure(text="No se pudo cargar miniatura", image="")


if __name__ == "__main__":
    root = tk.Tk()
    DownloaderApp(root)
    root.mainloop()
