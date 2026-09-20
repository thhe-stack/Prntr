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

import numpy as np
from flask import Flask, request, jsonify, send_file, render_template
from PIL import Image, ImageOps, ImageDraw, ImageFont
from escpos.printer import Network

# ---------------------------------------------------------------- config
PRINTER_HOST = os.environ.get("PRINTER_HOST", "192.168.1.73")
PRINTER_PORT = int(os.environ.get("PRINTER_PORT", "9100"))
PRINT_WIDTH = int(os.environ.get("PRINT_WIDTH", "576"))   # TM-m30II @ 80mm
COLS = PRINT_WIDTH // 12                                    # Font A columns (12-dot glyph)
DOTS_PER_MM = 8                                            # 203 dpi ≈ 8 dots/mm
# Blank leading feed so the cutter's non-printable top zone doesn't clip line 1.
TOP_MARGIN_DOTS = int(os.environ.get("TOP_MARGIN_DOTS", "40"))  # ≈ 5 mm

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")
FONT_PATH = os.path.join(_ASSETS, "PatrickHand-Regular.ttf")   # handwritten (captions, checklist)
BANNER_FONT_PATH = os.path.join(_ASSETS, "Anton-Regular.ttf")  # bold display (banners, headings)

app = Flask(__name__)

# ---------------------------------------------------------------- helpers
_measure = ImageDraw.Draw(Image.new("L", (8, 8)))


def load_font(size):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


def load_banner_font(size):
    try:
        return ImageFont.truetype(BANNER_FONT_PATH, size)
    except OSError:
        return load_font(size)


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


def feed_top(p):
    """Feed a small blank top margin so line 1 clears the cutter's dead zone."""
    n = max(0, min(255, TOP_MARGIN_DOTS))
    if n:
        try:
            p._raw(b"\x1b\x4a" + bytes([n]))   # ESC J n — print buffer + feed n dots
        except Exception:  # noqa: BLE001 — fall back to a line feed
            p.text("\n")


def print_raster(bw):
    """Send a finished 1-bit image to the printer with a top margin and cut."""
    p = connect()
    feed_top(p)
    p.image(bw, impl="bitImageRaster")
    p.cut(mode="PART")
    p.close()


def png_response(bw):
    buf = io.BytesIO()
    bw.save(buf, "PNG")
    buf.seek(0)
    resp = send_file(buf, mimetype="image/png")
    resp.headers["X-Print-Length-Mm"] = str(round(bw.height / DOTS_PER_MM))
    return resp


# ---------------------------------------------------------------- 1-bit renderers
_BAYER8 = np.array([
    [0, 48, 12, 60, 3, 51, 15, 63], [32, 16, 44, 28, 35, 19, 47, 31],
    [8, 56, 4, 52, 11, 59, 7, 55], [40, 24, 36, 20, 43, 27, 39, 23],
    [2, 50, 14, 62, 1, 49, 13, 61], [34, 18, 46, 30, 33, 17, 45, 29],
    [10, 58, 6, 54, 9, 57, 5, 53], [42, 26, 38, 22, 41, 25, 37, 21],
], dtype=np.float32)


def dither_atkinson(gray):
    """Atkinson error diffusion — sparser dots than Floyd–Steinberg, ideal for thermal."""
    a = np.asarray(gray, dtype=np.float32).copy()
    h, w = a.shape
    for y in range(h):
        for x in range(w):
            old = a[y, x]
            new = 255.0 if old >= 128.0 else 0.0
            a[y, x] = new
            err = (old - new) / 8.0
            if x + 1 < w:
                a[y, x + 1] += err
            if x + 2 < w:
                a[y, x + 2] += err
            if y + 1 < h:
                if x - 1 >= 0:
                    a[y + 1, x - 1] += err
                a[y + 1, x] += err
                if x + 1 < w:
                    a[y + 1, x + 1] += err
            if y + 2 < h:
                a[y + 2, x] += err
    out = (a >= 128).astype(np.uint8) * 255
    return Image.fromarray(out, "L").convert("1")


def dither_ordered(gray):
    """Bayer 8×8 ordered dither — a stable retro halftone that never smears."""
    a = np.asarray(gray, dtype=np.float32)
    h, w = a.shape
    thr = (np.tile(_BAYER8, (h // 8 + 1, w // 8 + 1))[:h, :w] + 0.5) * (255.0 / 64.0)
    out = (a > thr).astype(np.uint8) * 255
    return Image.fromarray(out, "L").convert("1")


def render_edge(gray, threshold):
    """Sobel edge trace — a coloring-book outline; ink-light and crisp."""
    a = np.asarray(gray, dtype=np.float32)
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    tl, tc, tr = p[0:h, 0:w], p[0:h, 1:w + 1], p[0:h, 2:w + 2]
    ml, mr = p[1:h + 1, 0:w], p[1:h + 1, 2:w + 2]
    bl, bc, br = p[2:h + 2, 0:w], p[2:h + 2, 1:w + 1], p[2:h + 2, 2:w + 2]
    gx = (tr + 2 * mr + br) - (tl + 2 * ml + bl)
    gy = (bl + 2 * bc + br) - (tl + 2 * tc + tr)
    mag = np.hypot(gx, gy)
    mag = mag / (mag.max() + 1e-6) * 255.0
    out = np.where(mag >= float(threshold), 0, 255).astype(np.uint8)  # black edges on white
    return Image.fromarray(out, "L").convert("1")


def render_halftone(gray, cell):
    """Newspaper-style halftone: one black dot per cell, sized by darkness."""
    a = np.asarray(gray, dtype=np.float32)
    h, w = a.shape
    cell = max(4, min(16, int(cell)))
    canvas = Image.new("1", (w, h), 1)
    d = ImageDraw.Draw(canvas)
    for cy in range(0, h, cell):
        for cx in range(0, w, cell):
            darkness = 1.0 - (a[cy:cy + cell, cx:cx + cell].mean() / 255.0)
            if darkness <= 0.02:
                continue
            r = (cell / 2.0) * (darkness ** 0.5)   # dot area ∝ darkness
            ccx, ccy = cx + cell / 2.0, cy + cell / 2.0
            d.ellipse((ccx - r, ccy - r, ccx + r, ccy + r), fill=0)
    return canvas


def reduce_1bit(gray, method, threshold, cell):
    if method == "atkinson":
        return dither_atkinson(gray)
    if method == "ordered":
        return dither_ordered(gray)
    if method == "threshold":
        t = int(threshold)
        return gray.point(lambda v: 255 if v >= t else 0).convert("1")
    if method == "edge":
        return render_edge(gray, threshold)
    if method == "halftone":
        return render_halftone(gray, cell)
    return gray.convert("1")                       # floyd (default)


# ---------------------------------------------------------------- image modes
def flatten(img):
    """Drop alpha onto white so transparency doesn't print as black."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def render_photo(img, target_width, orientation, method, threshold, cell):
    """Fit an image to `target_width` dots and reduce it to 1-bit via `method`."""
    img = ImageOps.exif_transpose(flatten(img))
    w, h = img.size
    if orientation == "landscape" or (orientation == "auto" and w > h):
        img = img.rotate(90, expand=True)
        w, h = img.size
    new_h = max(1, round(h * target_width / w))
    img = img.resize((target_width, new_h), Image.LANCZOS)
    return reduce_1bit(ImageOps.grayscale(img), method, threshold, cell)


def make_plain(img, orientation, method, threshold, cell):
    return render_photo(img, PRINT_WIDTH, orientation, method, threshold, cell)


def make_polaroid(img, caption, orientation, method, threshold, cell):
    """A framed photo with a handwritten caption in the wide bottom border."""
    side, top, gap, bottom = 26, 26, 18, 34
    photo = render_photo(img, PRINT_WIDTH - 2 * side, orientation, method, threshold, cell)

    caption = (caption or "").strip()
    lines, font = (fit_font(caption, PRINT_WIDTH - 2 * side, load_font, 46, 22, 2)
                   if caption else ([], None))
    line_h = (font.getbbox("Ag")[3] + 8) if font else 0
    cap_h = (len(lines) * line_h + 20) if lines else 46

    total_h = top + photo.height + gap + cap_h + bottom
    canvas = Image.new("1", (PRINT_WIDTH, total_h), 1)
    canvas.paste(photo, (side, top))
    if lines:
        canvas.paste(_text_block(lines, font, cap_h, "center"),
                     (0, top + photo.height + gap))
    return canvas


def build_image(file_storage, form):
    img = Image.open(file_storage.stream)
    orientation = form.get("orientation", "auto")
    method = form.get("method", "floyd")
    threshold = int(form.get("threshold", "128"))
    cell = int(form.get("cell", "7"))
    if form.get("polaroid", "0") == "1":
        return make_polaroid(img, form.get("caption", ""), orientation, method, threshold, cell)
    return make_plain(img, orientation, method, threshold, cell)


# ---------------------------------------------------------------- text layout
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


def fit_font(text, max_w, loader, big, small, max_lines):
    """Pick the largest font (from `loader`) that wraps `text` within the box."""
    for size in range(big, small - 1, -2):
        font = loader(size)
        lines = wrap_pixels(text, font, max_w)
        widest = max(_measure.textlength(ln, font=font) for ln in lines)
        if widest <= max_w and len(lines) <= max_lines:
            return lines, font
    font = loader(small)
    return wrap_pixels(text, font, max_w), font


def _text_block(lines, font, height, align):
    """Render centered/left lines to a crisp 1-bit strip of the given height."""
    layer = Image.new("L", (PRINT_WIDTH, height), 255)
    d = ImageDraw.Draw(layer)
    line_h = font.getbbox("Ag")[3] + 8
    y = 8
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font)
        tw = bb[2] - bb[0]
        x = (PRINT_WIDTH - tw) // 2 - bb[0] if align == "center" else 18 - bb[0]
        d.text((x, y - bb[1]), ln, font=font, fill=0)
        y += line_h
    return layer.point(lambda v: 255 if v >= 128 else 0).convert("1")


# ---------------------------------------------------------------- banner + checklist
def build_banner(text):
    """One or more lines of huge bold display type, filling the paper width."""
    margin = 18
    max_w = PRINT_WIDTH - 2 * margin
    lines, font = fit_font((text or "").strip() or " ", max_w, load_banner_font, 190, 16, 6)
    asc, desc = font.getmetrics()
    line_h = asc + desc + 10
    total_h = margin + line_h * len(lines) + margin
    canvas = Image.new("L", (PRINT_WIDTH, total_h), 255)
    d = ImageDraw.Draw(canvas)
    y = margin
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font)
        tw = bb[2] - bb[0]
        d.text(((PRINT_WIDTH - tw) // 2 - bb[0], y - bb[1]), ln, font=font, fill=0)
        y += line_h
    return canvas.point(lambda v: 255 if v >= 128 else 0).convert("1")


def build_checklist(title, items):
    """A title plus a list of items, each with an empty ☐ checkbox to tick by hand."""
    if isinstance(items, str):
        items = items.split("\n")
    items = [it.strip() for it in items if it and it.strip()]

    margin, box, box_gap, item_gap = 22, 30, 16, 16
    item_font = load_font(34)
    title_font = load_banner_font(46)
    ia, idc = item_font.getmetrics()
    il = ia + idc + 6
    cbb = _measure.textbbox((0, 0), "M", font=item_font)
    cap_h = cbb[3] - cbb[1]                                # cap height, for box alignment
    text_x = margin + box + box_gap
    max_w = PRINT_WIDTH - text_x - margin

    title = (title or "").strip()
    ta, tdc = title_font.getmetrics()
    title_h = (ta + tdc + 22) if title else 0

    wrapped = [wrap_pixels(it, item_font, max_w) for it in items]
    blocks = [max(box, len(w) * il) for w in wrapped]
    total_h = margin + title_h + sum(b + item_gap for b in blocks) + margin
    total_h = max(total_h, margin + title_h + margin)

    canvas = Image.new("L", (PRINT_WIDTH, total_h), 255)
    d = ImageDraw.Draw(canvas)
    y = margin
    if title:
        bb = d.textbbox((0, 0), title, font=title_font)
        d.text(((PRINT_WIDTH - (bb[2] - bb[0])) // 2 - bb[0], y - bb[1]), title,
               font=title_font, fill=0)
        y += title_h

    for lines, block_h in zip(wrapped, blocks):
        # first line's ink top is forced to y, so centre the box on the cap band —
        # centring on the full line-advance would sit it too low.
        box_top = y + (cap_h - box) // 2
        d.rectangle((margin, box_top, margin + box, box_top + box), outline=0, width=3)
        ty = y
        for ln in lines:
            bb = d.textbbox((0, 0), ln, font=item_font)
            d.text((text_x - bb[0], ty - bb[1]), ln, font=item_font, fill=0)
            ty += il
        y += block_h + item_gap

    return canvas.point(lambda v: 255 if v >= 128 else 0).convert("1")


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
    return png_response(build_image(request.files["image"], request.form))


@app.route("/api/print/image", methods=["POST"])
def print_image():
    try:
        bw = build_image(request.files["image"], request.form)
        print_raster(bw)
        return jsonify(ok=True, length_mm=round(bw.height / DOTS_PER_MM))
    except Exception as e:  # noqa: BLE001 — surface any failure to the UI
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/preview/banner", methods=["POST"])
def preview_banner():
    return png_response(build_banner(request.get_json(force=True).get("text", "")))


@app.route("/api/print/banner", methods=["POST"])
def print_banner():
    try:
        bw = build_banner(request.get_json(force=True).get("text", ""))
        print_raster(bw)
        return jsonify(ok=True, length_mm=round(bw.height / DOTS_PER_MM))
    except Exception as e:  # noqa: BLE001
        return jsonify(ok=False, error=str(e)), 500


@app.route("/api/preview/checklist", methods=["POST"])
def preview_checklist():
    data = request.get_json(force=True)
    return png_response(build_checklist(data.get("title", ""), data.get("items", "")))


@app.route("/api/print/checklist", methods=["POST"])
def print_checklist():
    try:
        data = request.get_json(force=True)
        bw = build_checklist(data.get("title", ""), data.get("items", ""))
        print_raster(bw)
        return jsonify(ok=True, length_mm=round(bw.height / DOTS_PER_MM))
    except Exception as e:  # noqa: BLE001
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
        feed_top(p)
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
