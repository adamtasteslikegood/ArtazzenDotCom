# ArtazZen Studio: Technical Upscaling & Print Workflow

**Purpose:** Process original 72 DPI Procreate Pocket exports into fine-art
300 DPI master files for large-format physical printing — and generate those
masters automatically from the gallery's admin pipeline.

---

## 1. The Core Technical Problem

- **Original files** were created/exported at 72 DPI (phone screen resolution).
- **Procreate stretch:** re-importing 72 DPI artwork onto a 300 DPI canvas in
  Procreate resizes the image container but stretches existing pixels without
  generating new visual detail.
- **Result:** images are 100% fine for mobile screens, email pitches, and
  iPads, but need proper AI pixel interpolation for large physical prints
  (24" × 36"+ canvas / murals).

---

## 2. In-App Print Masters (the integrated bridge)

The gallery now generates print masters itself. Uploading artwork through the
admin page (or importing via path) can opt in to an AI upscaling step that
produces a **4× upscaled PNG tagged at 300 DPI** alongside the web-resolution
original. Masters land in `print_masters/` inside the images directory (kept
out of the public gallery listing) and are recorded in the image's `.json`
sidecar under `print_master`:

```json
"print_master": {
  "status": "done",
  "file": "print_masters/sunset_master300.png",
  "url_path": "/static/images/print_masters/sunset_master300.png",
  "width": 4680, "height": 6240, "dpi": 300,
  "scale": 4, "model": "general", "backend": "replicate",
  "created": 1765900000.0, "error": ""
}
```

### Controls

- **Automatic on upload** — set `upscale_enabled` in the admin config
  (`POST /admin/config {"upscale_enabled": true}`) or env `UPSCALE_ENABLED=1`.
  Off by default (opt-in), matching the AI-metadata opt-out philosophy.
- **À la carte** — every admin review page has a _Generate print master_
  button (with regenerate), backed by:
  - `POST /admin/print-master/{image}` (form field `force=true` to redo)
  - `GET  /admin/print-master/{image}` (status polling)
- **Model choice** — `upscale_model`: `general` (painterly / photographic
  layer density) or `digital` (flat digital art / heavy linework; ~2.5×
  faster). `upscale_scale`: 2–4 (default 4).

### Backends (auto-selected, or forced via `UPSCALE_BACKEND`)

| Backend     | When it's used                                      | Best for                                                  |
| ----------- | --------------------------------------------------- | --------------------------------------------------------- |
| `replicate` | `REPLICATE_API_TOKEN` set                           | **Railway production** — no heavy deps, pennies per image |
| `binary`    | `REALESRGAN_BIN` points at `realesrgan-ncnn-vulkan` | Self-hosting with the Upscayl engine                      |
| `torch`     | `requirements-upscale.txt` installed                | Desktop batch runs, GPU boxes                             |

All backends run Real-ESRGAN — the same models Upscayl uses
(`RealESRGAN_x4plus` = general, `RealESRGAN_x4plus_anime_6B` = digital) — and
finish by tagging the output at 300 DPI with the original's ICC profile
preserved.

> **Railway note:** do NOT add `requirements-upscale.txt` to the web deploy;
> PyTorch inference is too heavy for the dyno. Set `REPLICATE_API_TOKEN` and
> the app uses the hosted backend. Generation runs as a background task, so
> uploads stay fast; the sidecar `status` moves `processing → done`.

---

## 3. Back-Catalog Batch Upscaling

Two equivalent paths for the existing 72 DPI archive:

### A. Repo CLI (no GUI needed)

```bash
# one-time, on a desktop / workstation
pip install -r requirements-upscale.txt

python3 scripts/upscale_batch.py \
  --src ~/ArtazZen/Originals_72DPI \
  --dst ~/ArtazZen/Master_300DPI_Upscaled \
  --model general --scale 4
```

Outputs `<name>_master300.png` files at 300 DPI. Use `--backend replicate`
(with `REPLICATE_API_TOKEN`) to run the same batch without installing torch.

### B. Upscayl GUI (per the original studio doc)

1. Collect originals into `/ArtazZen/Originals_72DPI`.
2. Open **Upscayl** → **Batch Upscayl**.
3. Model: **Digital Art** (or **General Photo** for photographic layer density).
4. Scale factor: **4×** (≈4000 × 6000 px+ at 300 DPI).
5. Output: `/ArtazZen/Master_300DPI_Upscaled`.
6. Upscayl does not set the DPI tag — masters print fine regardless, but to
   tag them run: `python3 scripts/upscale_batch.py` output already includes
   the 300 DPI tag, or re-save via any image tool at 300 DPI.

---

## 4. Two-Tier Asset Distribution Strategy

```
                          [ Original 72 DPI Artwork ]
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
[ Screen / Digital Pitches ]                       [ Large Physical Prints ]
• Web-resolution original (gallery)                • AI print master (print_masters/)
• Served on artazzen.com                           • 4x Real-ESRGAN, 300 DPI tagged
• Used for Emails, Web, Lookbooks                  • Fine Art Canvas, Murals, Prints
```

---

## 5. Procreate Master Canvas Settings (Future Artwork)

Default canvas preset for Procreate Pocket so all future artwork is natively
print-ready (no upscaling needed):

- **Dimensions:** 4000 × 6000 px (or 3600 × 4800 px if layer count limits hit)
- **DPI:** 300
- **Color profile:** sRGB IEC61966-2.1
- **Master storage:** export final revisions as uncompressed **PNG** or
  **TIFF** to cloud storage; send **JPEG** for pitch emails.

Natively 300 DPI uploads can skip the upscale step (leave the sidecar's
`print_master` empty or point buyers at the original).
