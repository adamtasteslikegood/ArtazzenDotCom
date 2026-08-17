# Button

## Classes
- `.button` -- primary filled button (dark bg, light text)
- `.button.secondary` -- ghost/outline variant
- `.button.danger` -- destructive action (orange)

## Markup
```html
<button class="button">Primary</button>
<button class="button secondary">Secondary</button>
<button class="button danger">Delete</button>
<a href="#" class="button">Link as button</a>
```

## Behavior
- Hover inverts fill/outline on primary and secondary
- Danger fills solid orange on hover
- Uses Clash Grotesk, uppercase, 0.75rem, letter-spacing 0.05em
- Small size in `.admin-card-actions`: 0.65rem, tighter padding

## Notes
- Supports both `<button>` and `<a>` elements
- Uses `display: inline-flex` for alignment
