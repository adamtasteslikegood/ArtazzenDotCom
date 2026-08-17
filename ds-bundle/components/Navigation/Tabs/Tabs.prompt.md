# Tabs

## Classes
- `.admin-tabs` — flex container, border-bottom, no gap
- `.admin-tab` — Clash Grotesk, 0.75rem, uppercase, transparent bg, 2px bottom border
- `.admin-tab.active` — text-main color, visible bottom border
- `.tab-content` — hidden by default (display: none)
- `.tab-content.active` — visible (display: block)

## Admin Nav
- `.admin-nav` — flex, centered, 1rem gap. Contains `.button` links.

## Markup
```html
<div class="admin-tabs">
  <button class="admin-tab active">Tab 1</button>
  <button class="admin-tab">Tab 2</button>
</div>
<div class="tab-content active" id="tab1">...</div>
<div class="tab-content" id="tab2">...</div>
```

## Behavior
Tab switching is handled via JavaScript toggling `.active` class.
