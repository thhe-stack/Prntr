# Prntr

A tiny, fast, **beautiful LAN web GUI** for sending text and images to one specific
printer — the **Epson TM-m30II** (80 mm, 203 dpi, 576-dot width). Anyone on the
network opens it in a browser and prints.

![width 576](https://img.shields.io/badge/paper-576px%20%C2%B7%2080mm-orange)

## Features
- **Text** — title + body, live-wrapped at the printer's real 48 columns, align & size.
- **Image** — drag/drop a photo; auto-fits the 576-dot width in portrait or landscape,
  with Floyd–Steinberg **dithering** (photos) or a **threshold** slider (line art).
- **Polaroid mode** 📸 — frames the photo with a handwritten caption (bundled Patrick
  Hand font). The little gimmick, done reliably: it's just image compositing.
- **Live WYSIWYG preview** — the server runs the *exact* print pipeline and streams the
  1-bit result back, so what you see is bit-for-bit what the thermal head prints.
- **Online/offline indicator** for the printer.

## Configuration (env vars)
| var | default | meaning |
|-----|---------|---------|
| `PRINTER_HOST` | `192.168.1.73` | the TM-m30II's IP (reserve it in your router!) |
| `PRINTER_PORT` | `9100` | raw ESC/POS port |
| `PRINT_WIDTH`  | `576` | printable dots — leave at 576 for the m30II |
| `APP_PORT`     | `8080` | web UI port |

## Run locally (dev)
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PRINTER_HOST=192.168.1.73 python app.py
# open http://localhost:8080
```

## Deploy on the ThinkSmart (Portainer + GitHub image)
1. **Push this repo to GitHub.** The included Action
   (`.github/workflows/docker-publish.yml`) builds a multi-arch image
   (amd64 + arm64) and publishes it to **GHCR** on every push to `main`.
2. **Make the image pullable:** GitHub → your profile → Packages → `prntr`
   (or repo name) → Package settings → set visibility to **Public**
   *(or, if you keep it private, add GHCR registry credentials in Portainer)*.
3. In **Portainer → Stacks → Add stack**, paste `docker-compose.yml`, then:
   - set `image:` to `ghcr.io/<your-user>/<your-repo>:latest`
   - set `PRINTER_HOST` to your printer's reserved IP
   - **Deploy**.
4. Open **http://<thinksmart-ip>:8080** from any device on the LAN.

## Notes
- **No authentication by design** — it's meant for a trusted LAN. Don't expose port
  8080 to the internet.
- The printer needs a **stable IP**. Reserve `192.168.1.73` (or whatever it is) as a
  DHCP reservation in your router so the address never drifts.
- Fonts: Patrick Hand is bundled under the SIL Open Font License (`assets/PatrickHand-OFL.txt`).
