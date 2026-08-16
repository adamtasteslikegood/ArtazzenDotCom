# Artazzen Design System

## Overview

**Artazzen** is an art gallery and curation platform that pairs bold, graphic paintings with AI-generated titles and descriptions. The artist's work — flat-color, hard-edge paintings of florals, landscapes, and architectural forms — is the visual heart of the brand. Everything else (typography, UI chrome, color) is a quiet frame around it.

The name "Artazzen" appears to combine "Art" + a personal suffix; the works are titled under the series **"Rising Artazzen"**. Maintainers: Adam Schoen, Allison Lunn (+ AI collaborators Gemini 2.5, Claude 3.5 Sonnet).

---

## Sources & Resources

| Resource | Location |
|---|---|
| **Codebase** | GitHub: `adamtasteslikegood/ArtazzenDotCom` (FastAPI + Jinja2) |
| **Main stylesheet** | `Static/css/styles.css` in repo |
| **Markdown color themes** | `Static/css/markdown plugin themes/` (4 themes) |
| **Artwork photos** | `uploads/artara (shared album ) - *.jpeg` |
| **App screenshots** | `uploads/IMG_*.PNG` |
| **Google Photos albums** | https://photos.app.goo.gl/yBWWKr5urRAE5QGg7 · https://photos.app.goo.gl/pzfuSS5AXBA45cdF8 |

---

## Products / Surfaces

1. **Public Gallery** (`/`) — Responsive masonry-style grid of artwork thumbnails with title + AI description. Primary user surface.
2. **Artwork Detail** (`/artwork/<name>`) — Full image view with metadata.
3. **Admin Dashboard** (`/admin`) — Upload, review queue, metadata editing, AI config panel.

---

## CONTENT FUNDAMENTALS

### Voice & Tone
- **Third-person curatorial** — descriptions speak *about* the work, not to the viewer directly. "The composition draws…" not "You'll notice…"
- **Precise yet evocative** — art language without jargon overload. Titles are short, imagistic, proper-noun-feeling: *"Rising Artazzen"*, *"Garden Ink"*, *"Neon Ember"*.
- **Minimal UI copy** — buttons say "OK", "Cancel", "Back to pending list". No cheerful microcopy. The art is the voice.
- **Lowercase preferred** in labels and nav. Title Case for artwork titles and series names.
- **No emoji** — the favicon uses 🎨 as a placeholder only; it is not part of the brand voice.
- **AI-generated text is flagged** — the admin UI shows "AI generated" / "AI pending" badges. Transparency about AI involvement is explicit.

### Casing & Punctuation
- Gallery title: plain text, no tagline
- Form labels: Sentence case (`Title`, `Description`)
- Action labels: Imperative, minimal (`Save`, `Cancel`, `Upload`)
- Descriptions: Full sentences, proper punctuation, no fragments.

### Example Copy
> *"Describe the story, medium, or inspiration for this piece."* — placeholder in description field
> *"No artwork images found in the 'Static/images' folder."* — empty state

---

## VISUAL FOUNDATIONS

### Core Aesthetic
The Artazzen visual language takes its cue from the paintings: **bold flat-color fields, hard edges, graphic clarity, and a sense of monumental calm**. The UI acts as a gallery wall — white, recessive, clean — so the art commands attention.

### Color System
Drawn directly from the paintings and the four AI-generated markdown themes:

**Artwork Palette (primary source of truth):**
| Token | Value | Description |
|---|---|---|
| `--art-black` | `#0E0C0C` | Velvet painting ground |
| `--art-amber` | `#E8820A` | Warm amber — most recurring hue |
| `--art-sky` | `#5BA3C9` | Atmospheric sky blue |
| `--art-earth` | `#5C3A1E` | Deep earth brown |
| `--art-ivory` | `#F7F4EE` | Gallery wall — near-white |
| `--art-crimson` | `#C7231B` | Bold field red |
| `--art-sage` | `#4A7C59` | Botanical green |
| `--art-gold` | `#F2B824` | Golden straw/sunlight |
| `--art-lotus` | `#F0EAE0` | Soft lotus petal off-white |
| `--art-navy` | `#0A1633` | Deep night navy (Kinetic Primary) |
| `--art-rose` | `#D8527D` | Blossom pink (Garden Ink) |
| `--art-chartreuse` | `#9EEA2F` | Acid meadow pop |

**Four Named Themes (from AI analysis of specific paintings):**
1. **Neon Ember** — cream ground, deep violet text, orange accent, violet blockquote
2. **Garden Ink** — paper white, deep teal text, blossom pink accent, tangerine border
3. **Kinetic Primary** — clean white, deep navy text, signal red accent, lemon/mint pops
4. **Acid Meadow** — pale green-white, charcoal text, hazard orange accent, neon chartreuse

### Typography
- **Display / Hero**: `DM Serif Display` (Google Fonts) — classical gallery serif, confident and spacious. Substitutes for an ideal custom typeface.
- **Body / UI**: `DM Sans` (Google Fonts) — clean, neutral, large x-height for legibility at small sizes.
- **Monospace / Code / Filenames**: `JetBrains Mono` (Google Fonts) — used in admin panels, filename displays, and the markdown themes.
- ⚠️ **Font substitution note**: The codebase uses `ui-monospace` system fallbacks everywhere; the markdown themes use `ui-monospace` as body font. `DM Serif Display` + `DM Sans` are proposed for the gallery brand upgrade.

### Spacing
- Base unit: `8px`
- Scale: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96`
- Gallery grid gap: `24px` (desktop), `16px` (mobile)
- Card padding: `16px`
- Section padding: `48–96px`

### Backgrounds
- Public gallery: `--art-ivory` (`#F7F4EE`) — the gallery wall
- Admin: `#f8f9fa` — neutral utility grey (current)
- Dark contexts: `--art-black` (`#0E0C0C`) or `--art-navy` (`#0A1633`)
- No gradients. No textures. Flat color or white.

### Cards
- White (`#ffffff`) background
- `1px solid #dee2e6` border (light mode)
- `border-radius: 8px`
- `box-shadow: 0 4px 8px rgba(0,0,0,0.05)` at rest; `0 6px 12px rgba(0,0,0,0.10)` on hover
- Hover: `transform: translateY(-5px)` — gentle lift

### Imagery
- Artwork is always shown full-bleed within its card container, `object-fit: cover`, `aspect-ratio: 4/3` in grid
- Color vibe: warm, saturated, high-contrast — the paintings are their own world
- No filters applied to artwork images; let them breathe

### Animation & Motion
- Transitions: `0.2s ease-in-out` on hover/focus states (transform + box-shadow)
- Hover lift on cards: `translateY(-5px)`
- No complex animations; the art is the visual event
- Drag/drop zone: `translateY(-2px)` + color shift to signal state

### Borders & Radius
- UI radius: `6px` (buttons, inputs), `8px` (cards, panels), `10px` (large cards), `12px` (dropzones), `999px` (badges/pills)
- No sharp corners in UI chrome; the sharp edges live in the paintings

### Buttons
- Primary: `background #495057`, white text, `border-radius: 6px`, hover darkens to `#343a40`
- Secondary: `background #ced4da`, dark text, hover to `#adb5bd`
- No outlines or ghost buttons in current system

### Hover States
- Cards: lift + shadow deepen
- Buttons: background darkens + `translateY(-1px)`
- Links: color shift to `--accent-hover` + underline
- Images in gallery: no filter treatment

### Iconography
See ICONOGRAPHY section below.

### Transparency & Blur
- No blur effects (no backdrop-filter) in current codebase
- Shadows are always subtle (low opacity, small spread)

### Corner Radii Summary
`4px` image corners · `6px` buttons/inputs · `8px` cards · `10px` preview image · `12px` dropzone · `999px` badges

---

## ICONOGRAPHY

The current codebase has **no icon system**. Observations:
- The favicon is an inline SVG emoji (🎨) — a placeholder
- The dropzone uses an inline SVG icon (upload arrow, `48×48px`, `color: #339af0`)
- No icon font, no sprite sheet, no icon library imported
- Admin uses text labels + buttons for all actions (no icon-only controls)

**Recommendation**: Adopt **Lucide Icons** (CDN: `https://unpkg.com/lucide@latest`) — stroke-based, minimal, pairs well with DM Sans. Stroke weight 1.5px at 20px size. See `ui_kits/web/index.html` for usage.

**Usage rules:**
- Icons always paired with text labels (no icon-only buttons except at ≥48px targets)
- Stroke color inherits from text
- Never filled icons
- Never emoji as UI chrome

---

## FILES IN THIS DESIGN SYSTEM

```
README.md                       ← This file
SKILL.md                        ← Agent skill definition
colors_and_type.css             ← CSS custom properties: color + type tokens
assets/
  artwork-1.jpeg                ← Sample artwork (bold floral/arch, amber+black)
  artwork-2.jpeg                ← Sample artwork (geometric landscape, primary colors)
  artwork-3.jpeg                ← Sample artwork (botanical, red+green)
  artwork-4.jpeg                ← Sample artwork (atmospheric, blue+earth)
  artwork-5.jpeg                ← Sample artwork (geometric abstract)
preview/
  colors-artwork-palette.html   ← Artwork color swatches
  colors-themes.html            ← Four named color themes
  colors-semantic.html          ← Semantic color tokens
  type-scale.html               ← Display + body type scale
  type-specimens.html           ← Type specimens in context
  spacing-tokens.html           ← Spacing + radius tokens
  components-buttons.html       ← Button states
  components-cards.html         ← Card variants
  components-badges.html        ← Badge + pill variants
  components-forms.html         ← Form inputs + fields
  brand-themes.html             ← Four color theme previews
ui_kits/
  web/
    README.md                   ← Web UI kit notes
    index.html                  ← Interactive gallery prototype
    GalleryGrid.jsx             ← Gallery grid component
    ArtworkCard.jsx             ← Artwork card component
    AdminDashboard.jsx          ← Admin dashboard component
    Header.jsx                  ← Site header component
```
