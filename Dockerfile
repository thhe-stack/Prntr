FROM python:3.12-slim

# Pillow wheels are self-contained; no apt packages needed for PNG/JPEG.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PRINTER_HOST=192.168.1.73 \
    PRINTER_PORT=9100 \
    PRINT_WIDTH=576 \
    APP_PORT=7666
EXPOSE 7666

# 2 workers is plenty for a LAN print box; long timeout for big images.
CMD ["sh","-c","gunicorn -b 0.0.0.0:${APP_PORT} -w 2 --timeout 120 app:app"]
