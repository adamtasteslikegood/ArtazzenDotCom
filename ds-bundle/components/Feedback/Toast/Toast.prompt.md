# Toast

## Classes

- `.feedback` -- fixed position (top-right), Clash Grotesk, semibold, shadow-md
- `.feedback.success` -- teal background (#0D9488), white text
- `.feedback.error` -- orange background (#F97316), white text

## Markup

```html
<div class="feedback success">Message here</div>
<div class="feedback error">Error message</div>
```

## Behavior

Positioned fixed at top: 2rem, right: 2rem. Add/remove via JS. z-index: 1000.
