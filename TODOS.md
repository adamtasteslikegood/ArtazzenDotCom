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
- **Replace the placeholder copy on `/join`.** High, content. Four benefit
  lines and the terms line still carry bracketed drafts (`[price]`,
  `[Members-only updates]`, and so on) in `templates/join.html`. Needs the
  real benefits, price and early-access terms before the page is promoted.
  From the 2026-11-22 design QA.
- **Make breadcrumb links easier to tap on a phone.** Medium, interaction.
  They are 18px tall; DESIGN.md asks for 44px touch targets. Taller links
  make a wrapped three-line trail much taller, so the layout needs a decision.
- **Link the title under each grid thumbnail to the artwork, and mark it up
  as a heading.** Medium, interaction. Only the image is a link today, and
  the titles are `<p>` elements, so they are missing from heading navigation.
- **Give the artwork page image `width` and `height`.** Polish, performance.
  Without them the details below the image can shift on a phone as it loads.
- **Theme the keyboard focus ring.** Polish. It is the browser default.

## Completed
