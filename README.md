# Prntr

A tiny, fast, **beautiful LAN web GUI** for sending text and images to one specific
printer — the **Epson TM-m30II** (80 mm, 203 dpi, 576-dot width). Anyone on the
network opens it in a browser and prints.

![width 576](https://img.shields.io/badge/paper-576px%20%C2%B7%2080mm-orange)

## Features
- **Text** — title + body, live-wrapped at the printer's real 48 columns, align & size.
- **Image** — drag/drop a photo; auto-fits the 576-dot width in portrait or landscape,
  with a choice of renderer:
  - **Floyd–Steinberg** dither (default, for photos)
  - **Atkinson** dither — sparser dots, cleaner whites; best on thermal paper
  - **Ordered (Bayer)** dither — stable retro halftone, never smears
  - **Threshold** — hard black/white for line art (with slider)
  - **Edge trace (Sobel)** — coloring-book outline; ink-light (sensitivity slider)
  - **Halftone dots** — newspaper-style dot screen (dot-size slider)
- **Polaroid mode** 📸 — frames the photo with a handwritten caption (bundled Patrick
  Hand font). Reliable, because it's just image compositing.
- **Banner** 🔠 — one or more lines of huge bold display type (bundled Anton font),
  auto-sized to fill the paper width.
- **Checklist** ☑️ — a title plus items, each with an empty ☐ box to tick by hand.
- **Poster / rasterbation** 🧩 — tile an image across *N* paper-width strips you tape
  together (2–6 strips ≈ 13–40 cm wide). Artwork sits **flush left** with a blank
  **glue gap** on the right of each strip to lap the next one over. The whole poster
  is dithered *before* slicing, so the dot pattern is continuous and the joins are
  seamless. Halftone is the default here — big dots read well from a distance.
- **Printer status** — live online/offline plus **paper OK / low / out**, cover-open
  and error detection via ESC/POS real-time status (`DLE EOT`). Thermal rolls have no
  length encoder, so this is sensor-based: it reports "low" (near-end), not a %.
- **Live WYSIWYG preview** — the server runs the *exact* print pipeline and streams the
  1-bit result back, so what you see is bit-for-bit what the thermal head prints.

## Configuration (env vars)
| var | default | meaning |
|-----|---------|---------|
| `PRINTER_HOST` | `192.168.1.73` | the TM-m30II's IP (reserve it in your router!) |
| `PRINTER_PORT` | `9100` | raw ESC/POS port |
| `PRINT_WIDTH`  | `576` | printable dots — leave at 576 for the m30II |
| `APP_PORT`     | `7666` | web UI port |

## Run locally (dev)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PRINTER_HOST=192.168.1.73 python app.py
# open http://localhost:7666
```

## Deploy on the ThinkSmart (Portainer + GitHub image)
1. **Push this repo to GitHub.** The included Action
   (`.github/workflows/docker-publish.yml`) builds a multi-arch image
   (amd64 + arm64) and publishes it to **GHCR** on every push to `main`.
2. **Make the image pullable:** GitHub → your profile → Packages → `prntr`
   (or repo name) → Package settings → set visibility to **Public**
   *(or, if you keep it private, add GHCR registry credentials in Portainer)*.
3. In **Portainer → Stacks → Add stack**, paste `docker-compose.yml`, then:
   - set `image:` to `ghcr.io/thhe-stack/prntr:latest`
   - set `PRINTER_HOST` to your printer's reserved IP
   - **Deploy**.
4. Open **http://<thinksmart-ip>:7666** from any device on the LAN.

## Notes
- **Version badge** — the header shows `v<version> · <commit>`. `GIT_SHA` and
  `BUILD_DATE` are baked into the image at build time by the Actions workflow, so the
  badge tells you *which build is actually running* — handy for confirming a redeploy
  really picked up the new image. Running locally it shows `dev`. Bump `APP_VERSION`
  in `app.py` for releases.
- **No authentication by design** — it's meant for a trusted LAN. Don't expose port
  7666 to the internet.
- The printer needs a **stable IP**. Reserve `192.168.1.73` (or whatever it is) as a
  DHCP reservation in your router so the address never drifts.
- Fonts: Patrick Hand is bundled under the SIL Open Font License (`assets/PatrickHand-OFL.txt`).
