# TODOs

## Open

- **Replace `railway.json` before 2026-12-01.** Railway stops reading Config as
  Code files on that date, and with it the pull-request-only start command
  that seeds preview images. `scripts/seed_images.py start` already copies
  nothing outside a `-pr-<number>` environment, so either of these keeps
  seeding automatic: (a) change the `Procfile` web line to
  `python scripts/seed_images.py start` and give the script the uvicorn
  command, which keeps everything in the repository but puts the script on
  production's start path; or (b) set that start command on the `staging-dev`
  service in Railway, which previews inherit, with a fallback for branches
  that do not have the script yet. Then delete `railway.json`.

- **Move originals to Cloudflare R2 or use Cloudflare Image Transformations.**
  Trigger: web egress from Railway above 10 GB/month after the image caching
  and thumbnail work. Until then pre-generated WebP derivatives and edge
  caching are enough. See the 2026-10-09 engineering review (decision D7).

## Completed
