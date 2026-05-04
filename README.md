# YT Endeavour Downloader

Ahora incluye:
- Cabecera estilo boceto: icono izquierda, título, menú hamburguesa y botones ventana a la derecha.
- Botones: Nuevo, Reanudar, Pausar todo, Detener todo.
- Ventana emergente al pulsar **Nuevo** para añadir URL.
- Selección dinámica: si eliges Música salen calidades/formato de audio; si eliges Video salen resoluciones (incluido 4K/2160).
- Soporte playlists: agrega una fila/tarea por cada elemento.
- Miniaturas funcionales usando Pillow.

## Requisitos
```bash
sudo pacman -S python python-pip python-tk ffmpeg
pip install yt-dlp pillow
```

## Ejecutar
```bash
python app.py
```
