# Colors

## Primitive palette
Use CSS custom properties for all colors. Never hardcode hex values.

### Core
- `var(--carbon)` — #121212, primary dark
- `var(--parchment)` — #F9F7F2, primary light

### Accents
- `var(--accent-violet)` — #8B5CF6
- `var(--accent-orange)` — #F97316
- `var(--accent-teal)` — #0D9488
- `var(--accent-crimson)` — #C7231B
- `var(--accent-gold)` — #F2B824
- `var(--accent-rose)` — #D8527D
- `var(--accent-mint)` — #13D672

### Neutrals
10-step scale from `var(--n0)` (#FFFFFF) to `var(--n900)` (#121212).

## Semantic tokens
- `var(--text-main)`, `var(--text-muted)` — text colors
- `var(--bg-main)`, `var(--bg-panel)` — backgrounds
- `var(--border-color)` — borders
- Dark mode swaps automatically via `prefers-color-scheme: dark`.
