# TODOs

## Open

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
