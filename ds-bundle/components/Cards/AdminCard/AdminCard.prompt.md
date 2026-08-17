# Admin Card

## Classes

- `.admin-card` — bg-panel, 1px border, radius-sm, hover darkens border
- `.admin-card img` — square (1:1), cover, full width
- `.admin-card-info` — 1rem padding
- `.admin-card-info h3` — Clash Grotesk, 0.875rem, truncate with ellipsis
- `.admin-card-actions` — flex row, 0.5rem gap, wraps
- `.filename` — JetBrains Mono, 0.7rem, opacity 0.5

## Layout

Use inside `.admin-grid` (auto-fill, minmax 240px, gap 1.5rem).

## Markup

```html
<div class="admin-card">
  <img src="..." alt="..." />
  <div class="admin-card-info">
    <h3>Title</h3>
    <p class="filename">filename.jpg</p>
    <div class="admin-card-actions">
      <button class="button">Review</button>
      <button class="button danger">Delete</button>
    </div>
  </div>
</div>
```
