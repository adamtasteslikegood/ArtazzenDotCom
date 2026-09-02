# Gallery Grid

## Classes

- `.gallery-grid` -- CSS grid, auto-fill minmax(300px, 1fr), 4rem gap
- Even `.artwork-item` children get 4rem top margin for asymmetric editorial feel
- Collapses to single column below 600px (margin offset removed)

## Markup

```html
<div class="gallery-grid">
  <div class="artwork-item">...</div>
  <div class="artwork-item">...</div>
</div>
```
