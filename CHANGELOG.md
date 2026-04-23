# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-22

### Added
- Direct order CTA and inquiry form on artwork detail pages to capture leads.
- Reusable `_get_artwork_data` helper in backend to consolidate metadata extraction.
- Atomic append-only logging of order requests to `data/orders.jsonl`.
- `TODOS.md` file for tracking future feature phases and technical debt.
- Basic test plan artifact generation for structured QA testing.

### Changed
- Switched default runtime requirement to Python 3.13 via `uv`.
- Refactored `artwork_detail` route to leverage unified metadata extraction.

### Security
- Excluded `data/` directory via `.gitignore` to prevent committing customer inquiry information.

