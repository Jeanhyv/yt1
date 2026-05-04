# YT Endeavour Downloader

Descargador simple para EndeavourOS (Linux) basado en tus esquemas:

- Colores oscuros con acentos rosa/azul/magenta.
- Botones: **Nuevo**, **Descargar todo**, **Pausar todo**, **Detener todo**.
- Cola de tareas con estado, progreso, velocidad, ETA, peso y fecha.
- Modo **Video** o **Música**.
- Selector de carpeta de salida.

## Requisitos

```bash
sudo pacman -S python python-pip ffmpeg
pip install yt-dlp
```

## Ejecutar

```bash
python app.py
```

## Notas

- Usa `yt-dlp` + `ffmpeg` para que funcione bien con YouTube.
- **Pausar** usa `SIGSTOP` (Linux), pensado para EndeavourOS.
- Spotify: no incluido por temas legales/técnicos.
