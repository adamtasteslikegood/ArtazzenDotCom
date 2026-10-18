---
applyTo: "**"
---

# Code Review Instructions

## Scope

Review only application code. Skip these paths entirely — do not read, analyze, or comment on them:

- `.claude/**`
- `.copilot/**`
- `.github/instructions/**`
- `artazzen-design-system/**`
- `AGENTS.md`

## Efficiency Rules

Every push triggers a review, and each finding costs a fix-and-re-review round. Follow these rules:

1. **Report everything in the first review.** Read the whole diff and list every finding at SUGGESTION or above in one pass. Do not hold findings back for later passes.
2. **Re-reviews cover only what changed.** On a later pass, comment only on lines changed since your last review. Raise a new finding on unchanged code only if it is CRITICAL; otherwise leave it out, including "previously missed" items.
3. **No repeat comments.** Do not re-raise feedback that was answered in a resolved thread, whether by a fix or by a rebuttal.
4. **No drive-by nitpicks.** Do not comment on style, whitespace, import order, or formatting; ruff, black and prettier handle those.
5. **One comment per issue.** If a pattern appears in several places, post one comment listing the locations.

## Calibration

- **Scale.** One admin, one process, tens to hundreds of images. Do not flag unbounded growth, multi-worker races, or high-traffic concerns unless you can state a realistic scenario at this scale; if you cannot, it is at most a SUGGESTION.
- **Scope.** Judge the change against what the PR says it does. A gap in behaviour the PR does not touch is at most a SUGGESTION, and belongs in an issue, not this PR.
- **Evidence.** Quote the code line or the documentation sentence a finding relies on. Do not say behaviour "contradicts the documentation" without quoting the text. Do not assert facts about external services (model names, API parameters) unless the diff, the repository, or current vendor documentation supports them; quote or link the source.
- **Planning documents.** Files under `docs/` that describe proposals or roadmaps are not specifications. Flag factual errors about the current code and internal contradictions. Do not ask for more implementation detail, and do not flag approximate or slightly stale counts.
- **Intended fallbacks.** A conservative failure mode (fewer retries, a delayed attempt, a fallback to a default) is not a defect unless it loses data or breaks a documented guarantee.

## Priority Levels

Use these priority tags in comment headers:

- **CRITICAL** — blocks merge: security vulnerabilities (injection, auth bypass, secrets in code), data loss risks, race conditions, broken error handling that silently swallows failures.
- **IMPORTANT** — requires discussion before merge: logic errors, missing validation at system boundaries, API contract violations, incorrect schema usage.
- **SUGGESTION** — non-blocking: performance improvements, readability, better error messages, test coverage gaps.

Do not post comments below SUGGESTION level. If a file has no issues worth a SUGGESTION or higher, leave no comment on that file.

## Project-Specific Checks

- Sidecar JSON must conform to `ImageSidecar.schema.json`. Required fields: `title`, `description`, `ai_generated`, `ai_details`, `status`, `detected_at`.
- `Static/` directory capitalisation must be preserved in all references.
- Application code belongs in the `app/` package, not in `main.py`.
- Module layering must be respected: `config → sidecars → media → ai_metadata → curation → watcher → security/routes → factory → main`. No cycles.
- Atomic file writes for sidecars (write temp → rename).
- No `print()` in production paths — use `logging.getLogger(__name__)`.

## Comment Format

```
**[PRIORITY]** Summary of the issue

Why this matters: [one sentence impact]

Suggested fix: [concrete code or approach]
```
