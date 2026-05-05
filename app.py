#!/usr/bin/env python3
import io, json, os, queue, re, signal, subprocess, threading, time, tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, ttk
from urllib.request import urlopen
from PIL import Image, ImageTk

APP_TITLE='YT Endeavour Downloader'
C={'bg':'#120a2d','panel':'#1e1244','panel2':'#241957','blue':'#38a5ff','mag':'#c852ff','text':'#f8f6ff'}

@dataclass
class DownloadTask:
    url:str; kind:str; quality:str; output_dir:Path; title:str='-'; thumbnail_url:str=''; batch_mode:str='uno';status:str='Pendiente';progress:float=0.0;eta:str='-';created_at:str=field(default_factory=lambda:time.strftime('%Y-%m-%d %H:%M:%S'))

class App:
    def __init__(self,r):
        self.r=r; r.title(APP_TITLE); r.geometry('1200x760'); r.configure(bg=C['bg'])
        self.tasks=[]; self.q=queue.Queue(); self.proc=None; self.idx=None; self.img_refs={}
        self.output=Path.home()/'Descargas'
        threading.Thread(target=self.worker,daemon=True).start(); self.ui()

    def ui(self):
        h=tk.Frame(self.r,bg=C['panel']); h.pack(fill='x',padx=6,pady=6)
        tk.Label(h,text='◉ '+APP_TITLE,bg=C['panel'],fg=C['text']).pack(side='left',padx=8)
        tk.Button(h,text='✕',command=self.r.destroy,bg=C['panel2'],fg=C['text'],bd=0,width=3).pack(side='right',padx=2)
        tk.Button(h,text='□',command=self.toggle_max,bg=C['panel2'],fg=C['text'],bd=0,width=3).pack(side='right',padx=2)
        tk.Button(h,text='—',command=self.r.iconify,bg=C['panel2'],fg=C['text'],bd=0,width=3).pack(side='right',padx=2)
        mb=tk.Menubutton(h,text='☰',bg=C['panel2'],fg=C['text'],relief='flat'); m=tk.Menu(mb,tearoff=0); m.add_command(label='Preferencias',command=self.sel_dir); m.add_command(label='Salir',command=self.r.destroy); mb.configure(menu=m); mb.pack(side='right',padx=2)

        tb=tk.Frame(self.r,bg=C['panel2']); tb.pack(fill='x',padx=10,pady=6)
        for t,cmd,col in [('Nuevo',self.new_dialog,C['blue']),('Reanudar',self.start,C['mag']),('Pausar todo',self.pause,'#7351d4'),('Detener todo',self.stop,'#d3345f')]:
            tk.Button(tb,text=t,command=cmd,bg=col,fg='white').pack(side='left',padx=4)

        style=ttk.Style(); style.theme_use('clam'); style.configure('Treeview',rowheight=42,background=C['panel'],fieldbackground=C['panel'],foreground=C['text'])
        cols=('tipo','modo','calidad','estado','progreso','eta','fecha')
        self.tree=ttk.Treeview(self.r,columns=cols,show='tree headings')
        self.tree.heading('#0',text='Título'); self.tree.column('#0',width=380)
        for c,t,w in [('tipo','Tipo',70),('modo','Descargar',80),('calidad','Calidad',80),('estado','Estado',90),('progreso','Prog.',70),('eta','ETA',70),('fecha','Fecha',150)]:
            self.tree.heading(c,text=t); self.tree.column(c,width=w,anchor='w')
        self.tree.pack(fill='both',expand=True,padx=10,pady=8)
        self.status=tk.StringVar(value='Listo'); tk.Label(self.r,textvariable=self.status,bg=C['panel'],fg=C['text'],anchor='w').pack(fill='x')


    def toggle_max(self):
        try:
            st=self.r.state()
            self.r.state('normal' if st=='zoomed' else 'zoomed')
        except Exception:
            # fallback para wm sin soporte zoomed
            if getattr(self,'_maxed',False):
                self.r.geometry('1200x760')
                self._maxed=False
            else:
                self.r.geometry(f"{self.r.winfo_screenwidth()}x{self.r.winfo_screenheight()}+0+0")
                self._maxed=True
    def new_dialog(self):
        d=tk.Toplevel(self.r); d.title('Nueva descarga'); d.geometry('760x320'); d.configure(bg=C['panel2'])
        # sin transient para que hyprland la trate normal
        url=tk.StringVar(); title=tk.StringVar(value='-'); thumb=[None]
        kind=tk.StringVar(value='video'); quality=tk.StringVar(value='best'); mode=tk.StringVar(value='uno')
        tk.Label(d,text='URL:',bg=C['panel2'],fg=C['text']).pack(anchor='w',padx=10,pady=(10,2)); e=tk.Entry(d,textvariable=url,width=95); e.pack(padx=10)
        tk.Label(d,textvariable=title,bg=C['panel2'],fg=C['text']).pack(anchor='w',padx=10,pady=4)
        row=tk.Frame(d,bg=C['panel2']); row.pack(fill='x',padx=10,pady=6)
        rb1=tk.Radiobutton(row,text='Video',variable=kind,value='video',indicatoron=True,bg=C['panel2'],fg='white',selectcolor=C['blue'],command=lambda:self.qvals(cb,quality,kind.get()))
        rb2=tk.Radiobutton(row,text='Música',variable=kind,value='audio',indicatoron=True,bg=C['panel2'],fg='white',selectcolor=C['blue'],command=lambda:self.qvals(cb,quality,kind.get()))
        rb1.pack(side='left'); rb2.pack(side='left')
        cb=ttk.Combobox(row,textvariable=quality,width=10); cb.pack(side='left',padx=8); self.qvals(cb,quality,'video')
        tk.Radiobutton(row,text='Solo uno',variable=mode,value='uno',bg=C['panel2'],fg='white',selectcolor=C['blue']).pack(side='left',padx=8)
        tk.Radiobutton(row,text='Todos',variable=mode,value='todos',bg=C['panel2'],fg='white',selectcolor=C['blue']).pack(side='left')

        prev=tk.Label(d,text='Sin carátula',bg='#0f0a22',fg='white',width=36,height=7); prev.pack(padx=10,pady=4)
        debounce={'id':None}
        def detect(*_):
            if debounce['id']: d.after_cancel(debounce['id'])
            def run():
                u=url.get().strip();
                if not u: return
                meta=self.fetch(u)[0]; title.set(meta['title']);
                try:
                    raw=urlopen(meta.get('thumbnail',''),timeout=10).read(); im=Image.open(io.BytesIO(raw)).resize((280,140)); ph=ImageTk.PhotoImage(im); thumb[0]=ph; prev.configure(image=ph,text='')
                except Exception: prev.configure(image='',text='Sin carátula')
            debounce['id']=d.after(500, lambda: threading.Thread(target=run,daemon=True).start())
        url.trace_add('write', detect)

        def descargar():
            d.destroy(); threading.Thread(target=lambda:self.add_tasks(url.get().strip(),kind.get(),quality.get(),mode.get(),True),daemon=True).start()
        b=tk.Frame(d,bg=C['panel2']); b.pack(pady=8)
        tk.Button(b,text='Descargar',command=descargar,bg=C['mag'],fg='white').pack(side='left',padx=6)
        tk.Button(b,text='Cancelar',command=d.destroy,bg='#666',fg='white').pack(side='left',padx=6)

    def qvals(self,cb,q,k):
        vals=['best','2160','1440','1080','720','480','360'] if k=='video' else ['mp3','m4a','wav']
        cb['values']=vals
        if q.get() not in vals: q.set(vals[0])

    def add_tasks(self,url,kind,quality,mode,autostart=False):
        if not url:return
        es=self.fetch(url); es=es[:1] if mode=='uno' else es
        for e in es:
            t=DownloadTask(url=e['url'],kind=kind,quality=quality,output_dir=self.output,title=e['title'],thumbnail_url=e.get('thumbnail',''),batch_mode=mode)
            self.r.after(0, lambda tt=t,auto=autostart:self.insert(tt,auto))

    def insert(self,t,autostart=False):
        i=len(self.tasks); self.tasks.append(t)
        img=''
        try:
            raw=urlopen(t.thumbnail_url,timeout=8).read(); ph=ImageTk.PhotoImage(Image.open(io.BytesIO(raw)).resize((64,36))); self.img_refs[i]=ph; img=ph
        except Exception: pass
        self.tree.insert('', 'end', iid=str(i), text=t.title, image=img, values=(t.kind,t.batch_mode,t.quality,t.status,'0%',t.eta,t.created_at))
        if autostart:
            self.q.put(i)

    def fetch(self,url):
        try:
            d=json.loads(subprocess.run(['yt-dlp','-J',url],capture_output=True,text=True,check=True).stdout)
            if d.get('entries'): return [{'url':x.get('webpage_url') or x.get('url'),'title':x.get('title','-'),'thumbnail':x.get('thumbnail','')} for x in d['entries'] if x]
            return [{'url':url,'title':d.get('title',url),'thumbnail':d.get('thumbnail','')}]
        except Exception: return [{'url':url,'title':url,'thumbnail':''}]

    def start(self):
        for i,t in enumerate(self.tasks):
            if t.status in ('Pendiente','Pausada','Error','Detenida'): self.q.put(i)

    def pause(self):
        if self.proc and self.proc.poll() is None: os.kill(self.proc.pid,signal.SIGSTOP); self.sets(self.idx,'Pausada')
    def stop(self):
        while not self.q.empty(): self.q.get_nowait()
        if self.proc and self.proc.poll() is None: self.proc.terminate()
    def sel_dir(self):
        s=filedialog.askdirectory(initialdir=str(self.output));
        if s: self.output=Path(s)
    def worker(self):
        while True:
            i=self.q.get();
            if i < len(self.tasks): self.run_task(i)
    def run_task(self,i):
        t=self.tasks[i]; self.idx=i; self.sets(i,'En progreso'); out=str(t.output_dir/'%(title).120s.%(ext)s')
        if t.kind=='audio': cmd=['yt-dlp','-x','--audio-format',t.quality,'--newline','-o',out,t.url]
        else:
            f=f"bestvideo[height<={t.quality}]+bestaudio/best[height<={t.quality}]" if t.quality.isdigit() else 'bestvideo+bestaudio/best'
            cmd=['yt-dlp','-f',f,'--merge-output-format','mp4','--newline','-o',out,t.url]
        self.proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        for ln in self.proc.stdout:
            m=re.search(r'(\d+\.\d+)%',ln)
            if m: t.progress=float(m.group(1)); self.refresh(i)
        self.sets(i,'Completada' if self.proc.wait()==0 else 'Error')
    def sets(self,i,s): self.tasks[i].status=s; self.refresh(i)
    def refresh(self,i):
        t=self.tasks[i]; self.tree.item(str(i),values=(t.kind,t.batch_mode,t.quality,t.status,f"{t.progress:.1f}%",t.eta,t.created_at))

if __name__=='__main__':
    r=tk.Tk(); App(r); r.mainloop()
