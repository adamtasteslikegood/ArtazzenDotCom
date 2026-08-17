# Artwork Card

## Classes

- `.artwork-item` — flex column, hover lifts -10px
- `.artwork-item a` — block link wrapper with bg-panel background
- `.artwork-item img` — 4:5 aspect ratio, grayscale(20%) default, full color on hover
- `.artwork-title` — Clash Grotesk, 1.25rem, uppercase, semibold
- `.artwork-description` — 0.9rem, muted color, max-width 30ch

## Asymmetric layout

Even children get `margin-top: 4rem` for editorial offset effect.
Use inside `.gallery-grid` (auto-fill, minmax 300px, gap 4rem).

## Markup

```html
<div class="artwork-item">
  <a href="/artwork/filename">
    <img src="..." alt="Title" loading="lazy" />
  </a>
  <p class="artwork-title">Title</p>
  <p class="artwork-description">Description text</p>
</div>
```
