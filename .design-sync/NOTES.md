# Design Sync Notes

## Shape: Hand-Authored CSS-Only

This project is a **Python/FastAPI + Jinja2** application — not a JavaScript/React component library.
The automated converter pipeline (package-build.mjs, resync.mjs) does not apply.

Preview cards are hand-authored HTML files that `<link>` the project's `styles.css` and
demonstrate each CSS class pattern. There is no `_ds_bundle.js` (no React components to bundle)
and no `_ds_sync.json` (no converter ran — omitting is the honest choice).

## Token Source Decision

- **Canonical**: `Static/css/styles.css` (the live deployed app)
- The old `artazzen-design-system/project/colors_and_type.css` has extended tokens
  (neutral ramp, type scale, spacing scale, motion tokens, 4 named themes) that are
  pulled in **only when reconciled to the live app's hex values and naming**.
- Key conflicts resolved in favor of live app:
  - `--accent-orange`: `#F97316` (live) wins over `#E8820A` (old)
  - `--accent-violet`: `#8B5CF6` (live) wins over `#6E3FD6` (old)
  - `--accent-teal`: `#0D9488` (live) wins over `#1A9490` (old)
  - Font variable: `--font-heading` (live) wins over `--font-display` (old)

## Component Idiom

CSS classes + `var(--*)` tokens. No importable React components.
The design agent should build with the documented CSS vocabulary:
`.button`, `.button.secondary`, `.button.danger`, `.gallery-grid`, `.artwork-item`,
`.admin-card`, `.admin-tab`, `.badge`, `.dropzone`, `.feedback`, etc.
