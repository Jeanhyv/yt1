#!/usr/bin/env python3
import json, os, queue, re, signal, subprocess, threading, time, tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.request import urlopen
from PIL import Image, ImageTk
import io

APP_TITLE="YT Endeavour Downloader"
COLORS={"bg":"#120a2d","panel":"#1e1244","panel2":"#241957","blue":"#38a5ff","magenta":"#c852ff","text":"#f8f6ff","muted":"#c8bde7"}

@dataclass
class DownloadTask:
    url:str; kind:str; quality:str; output_dir:Path; title:str='-'; thumbnail_url:str=''; batch_mode:str='uno';status:str='Pendiente';progress:float=0.0;speed:str='-';eta:str='-';size:str='-';created_at:str=field(default_factory=lambda:time.strftime('%Y-%m-%d %H:%M:%S'))

class DownloaderApp:
    def __init__(self,root):
        self.root=root; self.root.title(APP_TITLE); self.root.geometry('1280x760'); self.root.configure(bg=COLORS['bg'])
        self.tasks=[]; self.task_queue=queue.Queue(); self.current_proc=None; self.current_task_index=None; self.thumbnail_ref=None
        self.output_dir=Path.home()/ 'Descargas'
        threading.Thread(target=self._worker,daemon=True).start()
        self._ui()

    def _ui(self):
        h=tk.Frame(self.root,bg=COLORS['panel']); h.pack(fill='x',padx=6,pady=(6,0))
        tk.Label(h,text='◉',bg=COLORS['panel'],fg=COLORS['blue'],font=('Arial',14,'bold')).pack(side='left',padx=8)
        tk.Label(h,text=APP_TITLE,bg=COLORS['panel'],fg=COLORS['text'],font=('Arial',11,'bold')).pack(side='left')
        mb=tk.Menubutton(h,text='☰',bg=COLORS['panel2'],fg=COLORS['text'],relief='flat'); m=tk.Menu(mb,tearoff=0); m.add_command(label='Preferencias',command=self.select_output_dir); m.add_command(label='Salir',command=self.root.destroy); mb.configure(menu=m); mb.pack(side='right',padx=4)
        tk.Button(h,text='✕',command=self.root.destroy,bg=COLORS['panel2'],fg=COLORS['text'],bd=0,width=3).pack(side='right',padx=2)
        tk.Button(h,text='□',command=self._toggle_max,bg=COLORS['panel2'],fg=COLORS['text'],bd=0,width=3).pack(side='right',padx=2)
        tk.Button(h,text='—',command=self.root.iconify,bg=COLORS['panel2'],fg=COLORS['text'],bd=0,width=3).pack(side='right',padx=2)

        tb=tk.Frame(self.root,bg=COLORS['panel2']); tb.pack(fill='x',padx=10,pady=8)
        tk.Button(tb,text='Nuevo',command=self.open_new_dialog,bg=COLORS['blue'],fg='white').pack(side='left',padx=4)
        tk.Button(tb,text='Reanudar',command=self.start_all,bg=COLORS['magenta'],fg='white').pack(side='left',padx=4)
        tk.Button(tb,text='Pausar todo',command=self.pause_all,bg='#7351d4',fg='white').pack(side='left',padx=4)
        tk.Button(tb,text='Detener todo',command=self.stop_all,bg='#d3345f',fg='white').pack(side='left',padx=4)

        pan=tk.PanedWindow(self.root,orient='horizontal',bg=COLORS['bg']); pan.pack(fill='both',expand=True,padx=10,pady=8)
        l=tk.Frame(pan,bg=COLORS['panel']); r=tk.Frame(pan,bg=COLORS['panel']); pan.add(l,minsize=320); pan.add(r)
        self.thumb=tk.Label(l,text='Miniatura',bg='#0f0a22',fg=COLORS['muted']); self.thumb.pack(fill='both',expand=True,padx=8,pady=8)

        style=ttk.Style(); style.theme_use('clam'); style.configure('Treeview',background=COLORS['panel'],fieldbackground=COLORS['panel'],foreground=COLORS['text'],rowheight=28)
        cols=('titulo','tipo','modo','calidad','estado','progreso','eta','fecha')
        self.tree=ttk.Treeview(r,columns=cols,show='headings')
        for c,t,w in [('titulo','Título',280),('tipo','Tipo',70),('modo','Descargar',85),('calidad','Calidad',80),('estado','Estado',100),('progreso','Progreso',90),('eta','ETA',80),('fecha','Fecha',160)]: self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor='w')
        self.tree.pack(fill='both',expand=True,padx=8,pady=8); self.tree.bind('<<TreeviewSelect>>',self.on_select)
        self.status=tk.StringVar(value='Listo'); tk.Label(self.root,textvariable=self.status,bg=COLORS['panel'],fg=COLORS['text'],anchor='w').pack(fill='x')

    def _toggle_max(self):
        self.root.state('normal' if self.root.state()=='zoomed' else 'zoomed')

    def open_new_dialog(self):
        d=tk.Toplevel(self.root); d.title('Nuevo'); d.geometry('700x360'); d.configure(bg=COLORS['panel2']); d.transient(self.root)
        head=tk.Frame(d,bg=COLORS['panel']); head.pack(fill='x')
        tk.Label(head,text='◉',bg=COLORS['panel'],fg=COLORS['blue']).pack(side='left',padx=6)
        tk.Label(head,text='Nueva descarga',bg=COLORS['panel'],fg=COLORS['text']).pack(side='left')
        tk.Button(head,text='✕',command=d.destroy,bg=COLORS['panel2'],fg=COLORS['text'],bd=0,width=3).pack(side='right',padx=4)
        url=tk.StringVar(); kind=tk.StringVar(value='video'); quality=tk.StringVar(value='best'); mode=tk.StringVar(value='uno')
        thumb_lbl=tk.Label(d,text='Sin carátula',bg='#0f0a22',fg=COLORS['muted'],width=35,height=8); thumb_lbl.pack(padx=8,pady=8)
        tk.Label(d,text='Ingresar URL video/música:',bg=COLORS['panel2'],fg=COLORS['text']).pack(anchor='w',padx=12)
        tk.Entry(d,textvariable=url,width=90).pack(padx=12)
        frm=tk.Frame(d,bg=COLORS['panel2']); frm.pack(fill='x',padx=12,pady=6)
        tk.Radiobutton(frm,text='Video',variable=kind,value='video',bg=COLORS['panel2'],fg=COLORS['text'],command=lambda:self._dlg_quality(combo,quality,kind.get())).pack(side='left')
        tk.Radiobutton(frm,text='Música',variable=kind,value='audio',bg=COLORS['panel2'],fg=COLORS['text'],command=lambda:self._dlg_quality(combo,quality,kind.get())).pack(side='left')
        combo=ttk.Combobox(frm,textvariable=quality,width=12); combo.pack(side='left',padx=8); self._dlg_quality(combo,quality,'video')
        tk.Radiobutton(frm,text='Solo uno',variable=mode,value='uno',bg=COLORS['panel2'],fg=COLORS['text']).pack(side='left',padx=8)
        tk.Radiobutton(frm,text='Todos',variable=mode,value='todos',bg=COLORS['panel2'],fg=COLORS['text']).pack(side='left')

        def preview():
            metas=self._fetch_entries(url.get().strip());
            if not metas: return
            m=metas[0]
            try:
                raw=urlopen(m.get('thumbnail',''),timeout=10).read(); img=Image.open(io.BytesIO(raw)).resize((260,140)); ph=ImageTk.PhotoImage(img); thumb_lbl.image=ph; thumb_lbl.configure(image=ph,text='')
            except Exception: thumb_lbl.configure(text='Sin carátula',image='')
        tk.Button(frm,text='Previsualizar',command=lambda:threading.Thread(target=preview,daemon=True).start(),bg=COLORS['blue'],fg='white').pack(side='right')

        def aceptar():
            d.destroy(); threading.Thread(target=lambda:self._add_from_dialog(url.get().strip(),kind.get(),quality.get(),mode.get()),daemon=True).start()
        b=tk.Frame(d,bg=COLORS['panel2']); b.pack(pady=10)
        tk.Button(b,text='Aceptar',command=aceptar,bg=COLORS['magenta'],fg='white').pack(side='left',padx=6)
        tk.Button(b,text='Cancelar',command=d.destroy,bg='#555',fg='white').pack(side='left',padx=6)

    def _dlg_quality(self,combo,qvar,kind):
        vals=['best','2160','1440','1080','720','480','360'] if kind=='video' else ['mp3','m4a','wav']
        combo['values']=vals
        if qvar.get() not in vals: qvar.set(vals[0])

    def _add_from_dialog(self,url,kind,quality,mode):
        if not url: return
        entries=self._fetch_entries(url)
        if mode=='uno' and entries: entries=[entries[0]]
        for e in entries:
            t=DownloadTask(url=e['url'],kind=kind,quality=quality,output_dir=self.output_dir,title=e['title'],thumbnail_url=e.get('thumbnail',''),batch_mode=mode)
            self.root.after(0,lambda tt=t:self._insert_task(tt))

    def _insert_task(self,t):
        self.tasks.append(t); i=len(self.tasks)-1
        self.tree.insert('', 'end', iid=str(i), values=(t.title,t.kind,t.batch_mode,t.quality,t.status,'0%',t.eta,t.created_at)); self.status.set('Elemento(s) añadido(s)')

    def _fetch_entries(self,url):
        try:
            d=json.loads(subprocess.run(['yt-dlp','-J',url],capture_output=True,text=True,check=True).stdout)
            if d.get('entries'):
                return [{'url':(x.get('webpage_url') or x.get('url')),'title':x.get('title','-'),'thumbnail':x.get('thumbnail','')} for x in d['entries'] if x]
            return [{'url':url,'title':d.get('title',url),'thumbnail':d.get('thumbnail','')}]
        except Exception:
            return [{'url':url,'title':url,'thumbnail':''}]

    def start_all(self):
        for i,t in enumerate(self.tasks):
            if t.status in ('Pendiente','Pausada','Detenida','Error'): self.task_queue.put(i)

    def pause_all(self):
        if self.current_proc and self.current_proc.poll() is None: os.kill(self.current_proc.pid,signal.SIGSTOP); self._set_status(self.current_task_index,'Pausada')
    def stop_all(self):
        while not self.task_queue.empty(): self.task_queue.get_nowait()
        if self.current_proc and self.current_proc.poll() is None: self.current_proc.terminate()
    def select_output_dir(self):
        s=filedialog.askdirectory(initialdir=str(self.output_dir));
        if s: self.output_dir=Path(s)

    def _worker(self):
        while True:
            idx=self.task_queue.get();
            if idx < len(self.tasks): self._run_task(idx)

    def _run_task(self,idx):
        t=self.tasks[idx]; self.current_task_index=idx; self._set_status(idx,'En progreso')
        out=str(t.output_dir/'%(title).120s.%(ext)s')
        if t.kind=='audio': cmd=['yt-dlp','-x','--audio-format',t.quality if t.quality in ['mp3','m4a','wav'] else 'mp3','--newline','-o',out,t.url]
        else:
            fmt=f"bestvideo[height<={t.quality}]+bestaudio/best[height<={t.quality}]" if t.quality.isdigit() else 'bestvideo+bestaudio/best'
            cmd=['yt-dlp','-f',fmt,'--merge-output-format','mp4','--newline','-o',out,t.url]
        self.current_proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        for line in self.current_proc.stdout:
            if '[download]' in line: self._parse_progress(idx,line)
        self._set_status(idx,'Completada' if self.current_proc.wait()==0 else 'Error')

    def _parse_progress(self,idx,line):
        t=self.tasks[idx]; m=re.search(r'(\d+\.\d+)%',line)
        if m: t.progress=float(m.group(1)); self._refresh_row(idx)

    def _set_status(self,idx,s):
        if idx is None:return
        self.tasks[idx].status=s; self._refresh_row(idx)
    def _refresh_row(self,idx):
        t=self.tasks[idx]; self.tree.item(str(idx),values=(t.title,t.kind,t.batch_mode,t.quality,t.status,f"{t.progress:.1f}%",t.eta,t.created_at))

    def on_select(self,_=None):
        sel=self.tree.selection();
        if not sel:return
        th=self.tasks[int(sel[0])].thumbnail_url
        if not th: self.thumb.config(text='Sin miniatura',image=''); return
        try:
            raw=urlopen(th,timeout=10).read(); img=Image.open(io.BytesIO(raw)).resize((300,180)); self.thumbnail_ref=ImageTk.PhotoImage(img); self.thumb.config(image=self.thumbnail_ref,text='')
        except Exception: self.thumb.config(text='No se pudo cargar miniatura',image='')

if __name__=='__main__':
    root=tk.Tk(); DownloaderApp(root); root.mainloop()
