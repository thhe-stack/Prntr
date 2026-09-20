"""
Prntr — a tiny LAN GUI for the Epson TM-m30II thermal printer.

Everything here is written for exactly one printer: 80 mm paper, 203 dpi,
576-dot printable width. That single assumption is what lets the whole thing
stay small and reliable.
"""
import io
import os
import socket
import textwrap

from flask import Flask, request, jsonify, send_file, render_template
from PIL import Image, ImageOps, ImageDraw, ImageFont
from escpos.printer import Network

# ---------------------------------------------------------------- config
PRINTER_HOST = os.environ.get("PRINTER_HOST", "192.168.1.73")
PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "9100"))
PRINT_WIDTH = int(os.environ.get("PRINT_WIDTH", "576"))   # TM-m30II @ 80mm
COLS = PRINT_WIDTH // 12                                    # Font A columns (12-dot glyph)
DOTS_PER_MM = 8                                            # 203 dpi ≈ 8 dots/mm
FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "PatrickHand-Regular.ttf")

app = Flask(__name__)

# ---------------------------------------------------------------- helpers
_measure = ImageDraw.Draw(Image.new("L", (8, 8)))


def load_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def printer_online():
    try:
        socket.create_connection((PRINTER_HOST, PRINTER_PORT), timeout=2).close()
        return True
    except OSError:
        return False


def connect():
    p = Network(PRINTER_HOST, port=PRINTER_PORT, timeout=20)
    # The m30II isn't in python-escpos' database; teach its profile the 576-dot width
    # so raster sizing is model-accurate (and it stops warning about media width).
    try:
        p.profile.profile_data["media"]["width"] = {"pixels": PRINT_WIDTH, "mm": 72}
    except Exception:  # noqa: BLE001 — best-effort; printing works regardless
        pass
    return p


def flatten(img):
    """Drop alpha onto white so transparency doesn't print as black."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def render_photo(img, target_width, orientation, dither, threshold):
    """Fit an image to `target_width` dots and reduce it to crisp 1-bit."""
    img = ImageOps.exif_transpose(flatten(img))          # respect phone rotation
    w, h = img.size
    if orientation == "landscape" or (orientation == "auto" and w > h):
        img = img.rotate(90, expand=True)
        w, h = img.size
    new_h = max(1, round(h * target_width / w))
    img = img.resize((target_width, new_h), Image.LANCZOS)
    g = ImageOps.grayscale(img)
    if dither:
        return g.convert("1")                            # Floyd–Steinberg
    t = int(threshold)
    return g.point(lambda p: 255 if p >= t else 0).convert("1")


def wrap_pixels(text, font, max_w):
    words = " ".join(text.split()).split(" ")
    lines, cur = [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if _measure.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines or [""]


def fit_caption(text, max_w, max_lines=2):
    for size in range(46, 21, -2):
        font = load_font(size)
        lines = wrap_pixels(text, font, max_w)
        if len(lines) <= max_lines:
            return lines, font
    font = load_font(22)
    return wrap_pixels(text, font, max_w)[:max_lines], font


def make_plain(img, orientation, dither, threshold):
    return render_photo(img, PRINT_WIDTH, orientation, dither, threshold)


def make_polaroid(img, caption, orientation, dither, threshold):
    """A framed photo with a handwritten caption in the wide bottom border."""
    side, top, gap, bottom = 26, 26, 18, 34
    photo = render_photo(img, PRINT_WIDTH - 2 * side, orientation, dither, threshold)

    caption = (caption or "").strip()
    lines, font = (fit_caption(caption, PRINT_WIDTH - 2 * side) if caption else ([], None))
    line_h = (font.getbbox("Ag")[3] + 8) if font else 0
    cap_h = (len(lines) * line_h + 20) if lines else 46

    total_h = top + photo.height + gap + cap_h + bottom
    canvas = Image.new("1", (PRINT_WIDTH, total_h), 1)   # 1 = white
    canvas.paste(photo, (side, top))

    if lines:
        layer = Image.new("L", (PRINT_WIDTH, cap_h), 255)
        d = ImageDraw.Draw(layer)
        y = 8
        for ln in lines:
            bb = d.textbbox((0, 0), ln, font=font)
            tw = bb[2] - bb[0]
            d.text(((PRINT_WIDTH - tw) // 2 - bb[0], y - bb[1]), ln, font=font, fill=0)
            y += line_h
        crisp = layer.point(lambda p: 255 if p >= 128 else 0).convert("1")
        canvas.paste(crisp, (0, top + photo.height + gap))
    return canvas


def build_image(file_storage, form):
    img = Image.open(file_storage.stream)
    orientation = form.get("orientation", "auto")
    dither = form.get("dither", "1") == "1"
    threshold = int(form.get("threshold", "128"))
    if form.get("polaroid", "0") == "1":
        return make_polaroid(img, form.get("caption", ""), orientation, dither, threshold)
    return make_plain(img, orientation, dither, threshold)


# ---------------------------------------------------------------- routes
@app.route("/")
def index():
    return render_template("index.html", cols=COLS, width=PRINT_WIDTH,
                           host=PRINTER_HOST, port=PRINTER_PORT)


@app.route("/api/status")
def status():
    return jsonify(online=printer_online(), host=PRINTER_HOST, port=PRINTER_PORT,
                   width=PRINT_WIDTH, cols=COLS)


@app.route("/api/preview/image", methods=["POST"])
def preview_image():
    bw = build_image(request.files["image"], request.form)
    buf = io.BytesIO()
    bw.save(buf, "PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    resp.headers["X-Print-Length-Mm"] = str(round(bw.height / DOTS_PER_MM))
    return resp


@app.route("/api/print/image", methods=["POST"])
def print_image():
    try:
        bw = build_image(request.files["image"], request.form)
        p = connect()
        p.image(bw, impl="bitImageRaster")
        p.cut(mode="PART")
        p.close()
        return jsonify(ok=True, length_mm=round(bw.height / DOTS_PER_MM))
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/print/text", methods=["POST"])
def print_text():
    data = request.get_json(force=True)
    text = data.get("text", "")
    align = data.get("align", "left")
    size = 2 if str(data.get("size", "1")) == "2" else 1
    title = (data.get("title") or "").strip()
    try:
        p = connect()
        if title:
            p.set(align="center", bold=True, width=2, height=2)
            for ln in textwrap.wrap(title, width=max(1, COLS // 2)) or [""]:
                p.text(ln + "\n")
            p.set(align="left", bold=False, width=1, height=1)
            p.text("\n")
        p.set(align=align, width=size, height=size)
        cols = max(1, COLS // size)
        for para in text.split("\n"):
            if not para.strip():
                p.text("\n")
                continue
            for ln in textwrap.wrap(para, width=cols, break_long_words=True,
                                    replace_whitespace=False, drop_whitespace=True):
                p.text(ln + "\n")
        p.set(align="left", width=1, height=1)
        p.cut(mode="PART")
        p.close()
        return jsonify(ok=True)
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8080")))
