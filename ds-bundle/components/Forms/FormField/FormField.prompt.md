# Form Field

## Classes

- `.form-field` — wrapper, adds bottom margin
- `.form-field label` — JetBrains Mono, 0.7rem, uppercase, opacity 0.6
- `.form-field input/textarea/select` — transparent bg, 1px border, Instrument Sans
- `.checkbox` — flex row with gap, cursor pointer
- `.admin-search` — relative wrapper with magnifying glass pseudo-element

## Markup

```html
<div class="form-field">
  <label>Field Name</label>
  <input type="text" placeholder="..." />
</div>
```

## Behavior

- Focus: outline none, border darkens to --text-main
- Transparent background blends with any surface
