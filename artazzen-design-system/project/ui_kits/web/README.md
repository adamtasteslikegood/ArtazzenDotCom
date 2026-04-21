# Artazzen Web UI Kit

Interactive click-through prototype of the ArtazzenDotCom gallery web app.

## Surfaces Covered
- **Gallery view** — responsive artwork grid with hover states, click-through to detail
- **Artwork detail** — full image, metadata, inline edit flow, badge states
- **Admin dashboard** — upload dropzone, pending review queue, AI config panel

## Components
| File | Exports | Notes |
|---|---|---|
| `ArtworkCard.jsx` | `ArtworkCard` | Gallery grid card with hover lift |
| `GalleryGrid.jsx` | `GalleryGrid` | Auto-fill CSS grid of ArtworkCards |
| `Header.jsx` | `ArtazzenHeader` | Sticky header with nav tabs |
| `AdminDashboard.jsx` | `AdminDashboard` | Upload + pending review + AI config |
| `index.html` | — | Full interactive prototype |

## Fonts (Google Fonts)
- **DM Serif Display** — hero titles, artwork names
- **DM Sans** — all UI chrome, body, labels
- **JetBrains Mono** — filenames, timestamps, code

## Design Notes
- Colors: `#F7F4EE` gallery wall background; `#E8820A` amber accent
- Cards: 8px radius, `0 4px 8px rgba(0,0,0,.05)` shadow, `-5px` translateY on hover
- No icon library used yet — Lucide recommended for production
- Tweaks panel: bottom-right floating panel for live color/radius changes

## Usage
Open `index.html` directly in a browser. No build step needed.
The prototype uses sample artwork from `../../assets/`.
