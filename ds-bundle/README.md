# Artazzen Techno-Botanical Design System

## What this is

A CSS-only design system for the Artazzen artwork gallery and curation platform. There are no importable React components — designs are built with **CSS classes** and **`var(--*)` custom property tokens**.

## Aesthetic Direction

**Techno-Botanical** — sophisticated, high-contrast, precise, and organic. Carbon (#121212) and Parchment (#F9F7F2) as the primary palette, with dynamic accents pulled from artwork.

## Font Stack

| Role         | Family                                | Use                                   |
| ------------ | ------------------------------------- | ------------------------------------- |
| Display/Hero | `var(--font-heading)` — Clash Grotesk | Headings, buttons, tabs, hero text    |
| Body         | `var(--font-body)` — Instrument Sans  | Body copy, descriptions, form inputs  |
| Data         | `var(--font-mono)` — JetBrains Mono   | Timestamps, filenames, badges, labels |

## Component Vocabulary

### Gallery

- `.gallery-grid` — asymmetric editorial grid (auto-fill, 300px min, 4rem gap)
- `.artwork-item` — card with hover lift, even-child offset
- `.artwork-title` — Clash Grotesk, uppercase, 1.25rem
- `.artwork-description` — muted, max-width 30ch

### Admin

- `.admin-card` — bordered card with image + info section
- `.admin-tabs` / `.admin-tab` — tab navigation bar
- `.admin-panel` — bordered content panel with section heading
- `.admin-grid` — card grid (auto-fill, 240px min)
- `.admin-search` — search input with magnifying glass icon
- `.admin-nav` — centered button row

### Controls

- `.button` — primary filled (dark bg, inverts on hover)
- `.button.secondary` — ghost/outline variant
- `.button.danger` — orange destructive action
- `.form-field` — input wrapper with mono label
- `.checkbox` — inline checkbox with label
- `.dropzone` / `.dropzone.is-dragover` — file upload area

### Utility

- `.badge` — mono font, uppercase, bordered tag
- `.filename` — mono, 0.7rem, muted
- `.timestamp` — mono, 0.65rem, muted
- `.feedback.success` / `.feedback.error` — toast notifications
- `.shader-bg` — fractal noise overlay (fixed, low opacity)

## Token Scale

- **Spacing**: `--space-1` (4px) through `--space-10` (128px)
- **Type**: `--text-xs` (11px) through `--text-5xl` (96px)
- **Radius**: `--radius-sm` (2px), `--radius-md` (4px), `--radius-lg` (8px)
- **Shadow**: `--shadow-sm`, `--shadow-md`, `--shadow-lg`
- **Motion**: `--ease-bloom-in` (ease-out), `--ease-bloom-out` (ease-in), `--duration-short` (250ms), `--duration-med` (400ms)

## Dark Mode

Automatic via `prefers-color-scheme: dark`. Carbon and Parchment swap roles; panel and border opacities invert.

## Named Themes

Four artwork-derived themes applicable via class on `<html>` or `<body>`:

- `.theme-neon-ember` — warm amber/violet
- `.theme-garden-ink` — botanical rose/teal
- `.theme-kinetic-primary` — bold red/blue
- `.theme-acid-meadow` — acid green/orange
