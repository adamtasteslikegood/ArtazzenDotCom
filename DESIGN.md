# Design System — Artazzen

## Product Context
- **What this is:** An artwork gallery and curation platform for high-end digital and physical art.
- **Who it's for:** Collectors, curators, and the artist.
- **Space/industry:** Digital Art, AI Art, Botanical Illustration.
- **Project type:** Web App + Admin Dashboard.

## Aesthetic Direction
- **Direction:** Techno-Botanical
- **Decoration level:** Intentional (Canvas textures, noise shaders, architectural offsets).
- **Mood:** Sophisticated, high-contrast, precise, and organic.

## Typography
- **Display/Hero:** Clash Grotesk — Bold and architectural to match the art's sharp lines.
- **Body:** Instrument Sans — Professional and highly legible.
- **Data/Tables:** JetBrains Mono — For the JSON-based admin workflow.
- **Scale:** Modular 8px scale.

## Color
- **Approach:** Balanced (Monochrome base with dynamic accents).
- **Primary:** #121212 (Carbon)
- **Secondary:** #F9F7F2 (Parchment)
- **Accents:** Dynamic violet, orange, and teal pulled from the artwork.
- **Dark mode:** Redesign surfaces to pure Carbon with reduced saturation for accents.

### Dynamic Accent Algorithm

To ensure brand consistency and accessibility, dynamic accent colors are chosen from artwork using a defined algorithm:

1.  **Extraction:** On processing a new artwork, the backend will extract a palette of 5-8 dominant colors using a k-means clustering algorithm on the image's pixels.
2.  **Selection:** From this palette, the algorithm will select the color that is:
    a. Not too dark or too light (e.g., filter out colors near black or white).
    b. Has the highest saturation.
3.  **Accessibility Check:** The selected color will be checked for a minimum WCAG AA contrast ratio (4.5:1) against the primary backgrounds (#F9F7F2 and #121212). If it fails, the next most saturated color is chosen until one passes. If no color passes, a default accent color (e.g., `--accent-violet`) will be used.
4.  **Storage:** The chosen accent color is stored in the artwork's JSON sidecar file.

**Implementation Note:** The parameters for this algorithm (e.g., number of clusters for k-means, brightness/saturation thresholds) should be kept in the application's configuration code and not exposed through an admin UI, to ensure portability and consistency.

## Spacing & Layout
- **Base unit:** 8px
- **Density:** Hybrid (Spacious for gallery, compact for admin).
- **Layout:** Asymmetric editorial overlap for gallery; strict grid for admin.
- **Border radius:** sm: 2px, md: 4px, lg: 8px.

## Information Architecture

### Page Structure & Flow

The application has two primary areas: the public-facing **Gallery** and the private **Admin Dashboard**.

**1. Public Gallery Flow**

The public gallery follows a simple, two-level hierarchy:

1.  **Gallery (Home):** The main entry point, displaying a curated collection of all artworks.
2.  **Artwork Detail:** A dedicated page for each artwork, accessed from the gallery.

```ascii
[ / (Gallery) ]
      |
      +--> [ /artwork/{id_1} (Detail) ]
      |
      +--> [ /artwork/{id_2} (Detail) ]
      |
      ...
```

**2. Admin Dashboard Flow**

The admin dashboard provides tools for content management and system configuration.

```ascii
[ /admin (Dashboard) ]
      |
      +--> [ /admin/review (Review Queue) ]
      |      |
      |      +--> [ /admin/review/{id} (Review Detail) ]
      |
      +--> [ /admin/config (Configuration) ]
```

### Content Hierarchy (per page)

#### Gallery Page (`/`)
1.  **Primary:** The visual grid of artwork thumbnails. The user's primary focus is browsing art.
2.  **Secondary:** Artwork titles.
3.  **Tertiary:** Artwork descriptions.

#### Artwork Detail Page (`/artwork/{id}`)
1.  **Primary:** The main artwork image.
2.  **Secondary:** The artwork description/text.
...
3.  **Tertiary:** Navigation back to the gallery.

## Interaction States

| FEATURE                 | LOADING                                           | EMPTY                                                                    | ERROR                                                                          | SUCCESS                             | PARTIAL |
| ----------------------- | ------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ----------------------------------- | ------- |
| Gallery Grid            | Show skeleton placeholders for each artwork item. | Display a message with a call to action (e.g., "No artwork yet.") | Display a generic error message.                                               | Artworks are displayed in the grid. | N/A     |
| Artwork Image (in grid) | Skeleton placeholder.                             | N/A                                                                      | `onerror` handler shows a 'Not Found' placeholder.                             | Image is displayed.                 | N/A     |
...
| Artwork Detail Page     | Show skeleton placeholders for image and text.    | N/A                                                                      | If artwork not found, the server should return a standard 404 error page. | Artwork details are displayed.      | N/A     |

## User Journey & Emotional Arc

This storyboard maps the user's path through the gallery, ensuring the design supports the intended emotional arc of discovery and appreciation.

| STEP | USER DOES | USER FEELS | PLAN SPECIFIES? |
|---|---|---|---|
| 1 | Lands on the gallery page | **Intrigued, Curious.** The high-contrast, architectural layout creates a sense of entering a special, curated space. | Asymmetric grid, hero typography. |
| 2 | Scrolls through the artwork | **Engaged, Exploring.** The "bloom" animations and editorial layout make browsing feel like a deliberate, paced experience, not an endless scroll. | Motion system, layout rules. |
| 3 | Clicks on an artwork | **Anticipation.** The user has found something that resonates and wants to see more. | "Zoom & Bloom" page transition. |
| 4 | Views the artwork detail | **Focused, Appreciative.** The minimal layout with the large image and focused text allows the user to immerse themselves in the artwork without distraction. | Detail page layout, typography. |
...
| 5 | Returns to the gallery | **Satisfied, Ready for more.** The easy navigation encourages further exploration. | Back navigation. |

## Responsive & Accessibility (A11y)

### Responsive Design
The layout should adapt fluidly to different screen sizes. Key breakpoints are:
- **Desktop ( > 900px):** Full asymmetric grid layout.
- **Tablet (601px - 900px):** Simplified grid, possibly single-column for admin areas.
- **Mobile (<= 600px):** Single-column layout for the gallery grid. All touch targets should be at least 44x44px.

### Accessibility
Accessibility is a primary concern. The application must be usable for everyone.
- **Semantic HTML:** Use appropriate HTML5 tags (`<main>`, `<header>`, `<nav>`, etc.) to give structure to the page.
- **ARIA Roles:** Where necessary, use ARIA roles to enhance semantics for screen readers (e.g., `role="button"` on non-button elements that act as buttons).
- **Keyboard Navigation:** All interactive elements must be focusable and operable via the keyboard. Focus order must be logical. A visible focus indicator is required.
- **Image Alt Text:** All images must have descriptive `alt` text. Decorative images should have an empty `alt=""`.
- **Color Contrast:** All text must meet WCAG AA contrast ratios (4.5:1 for normal text, 3:1 for large text). The current Carbon/Parchment palette has excellent contrast.

## Motion
- **Approach:** Intentional "Bloom" animations.
- **Easing:** ease-out for entrances (blooming), ease-in for exits.
- **Duration:** 250ms short, 400ms medium.
- **Page Transitions:** Use a "Zoom & Bloom" animation when navigating from the gallery to the artwork detail page. This should be implemented using the **View Transitions API**.
  - The clicked artwork thumbnail should be the origin of the transition.
  - For browsers that do not support the View Transitions API, a simple CSS fade-in/fade-out should be used as a fallback.
  - All transitions must respect the `prefers-reduced-motion` media query and be disabled (or reduced to a simple fade) when it is active.
|------|----------|-----------|
| 2026-04-20 | Initial design system created | Tailored to "Techno-Botanical" art style and Claude Design workflow. |

> @artazzen-design-system/ theses got cut off before claude design got too implment our DESIGN.md right int he middle
