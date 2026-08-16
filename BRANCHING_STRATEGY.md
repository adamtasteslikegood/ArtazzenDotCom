# Branching Strategy

## Branch Model

```
main (production)          ← deployed to Railway production environment
  └── dev (integration)    ← default working branch, all feature branches start here
       ├── feat/...        ← new features
       ├── fix/...         ← bug fixes
       ├── docs/...        ← documentation changes
       └── chore/...       ← maintenance, deps, CI config
```

### Branch Roles

| Branch | Purpose | Deploys To | Protected |
|--------|---------|------------|-----------|
| `main` | Production-ready code | Railway production | Yes — PR required, all threads resolved |
| `dev` | Integration and staging | Railway staging (when configured) | Yes — PR required |
| `feat/*`, `fix/*`, `docs/*`, `chore/*` | Short-lived work branches | Railway PR previews (when configured) | No |

### Rules

- **Always branch from `dev`**, never from `main`.
- PRs from feature branches target `dev`. `dev` is promoted to `main` for production releases.
- Direct pushes to `dev` and `main` are blocked by GitHub rulesets.
- Force-push and branch deletion are blocked on `dev` and `main`.
- Keep branches short-lived — merge or close within days, not weeks.

## GitHub Rulesets

Two rulesets enforce branch protection:

### `dev` (targets default branch)

- No direct push, no force-push, no deletion
- Pull request required (0 approvals minimum)
- Copilot code review on push and drafts
- CodeQL security scanning (high+ security, errors threshold)
- Code quality checks (errors threshold)

### `main_railway_production` (targets `main`, `production`, `prod`)

- Everything in the `dev` ruleset, plus:
- **Required review thread resolution** — every PR comment thread must be resolved before merge
- Allowed merge methods: rebase or merge commit (no squash)

## PR Lifecycle

1. **Branch** — `git checkout dev && git pull origin dev && git checkout -b feat/my-thing dev`
2. **Develop** — make changes, commit with clear messages.
3. **Push** — `git push -u origin feat/my-thing`
4. **Open PR** — target `dev`. Open as draft if still in progress; ready for review if mergeable. Write a summary and test plan.
5. **Automated checks** — wait for CodeQL, Copilot review, and code quality to pass.
6. **Review** — request review if needed. Read every comment carefully.
7. **Respond** — reply to each review thread. Push fix commits (don't force-push).
8. **Resolve threads** — all comment threads must be marked resolved (enforced by ruleset on `main`).
9. **Merge** — use rebase or merge commit. Delete the feature branch after merge.

### Check Branch Status

```bash
bash scripts/ahead-behind.sh              # all branches vs repo default
bash scripts/ahead-behind.sh --base dev   # all branches vs dev
bash scripts/ahead-behind.sh 5 --newest   # 5 most recently updated branches
```

## Railway Environments

Railway supports multiple environments tied to branches. Each environment has its own service instances, variables, and (optionally) volumes.

### Production (`main`)

- **URL**: https://artazzen.com (canonical apex domain)
- **Branch**: `main` — auto-deploys on push/merge
- **Hosting**: Dedicated Railway project
- **DNS**: Cloudflare nameservers. `www.artazzen.com` → 301 redirect to apex via Cloudflare rule. `www` uses a proxied DNS record that resolves through Cloudflare edge IPs.
- **CDN/Proxy**: Cloudflare proxy on apex — SSL termination, DDoS protection, caching
- **Volume**: persistent storage mounted at `/data/images` (`IMAGES_DIR=/data/images`)
- **Variables**: `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `MY_OPENAI_API_KEY`, and other production secrets set in Railway dashboard

### PR Deploy Previews (planned)

Railway can spin up isolated environments for each pull request, giving reviewers a live preview before merging.

**What PR previews provide:**
- Temporary environment created automatically when a PR is opened
- Own service instance with the PR's code deployed
- Isolated variables (can inherit from production or use test values)
- Unique preview URL for each PR
- Auto-teardown when the PR is merged or closed

**Setup steps (after initial PRs are merged):**
1. Enable "PR Deploy Previews" in the Railway service settings
2. Connect the GitHub repo if not already linked
3. Configure environment variables for preview environments (use test API keys, separate admin credentials)
4. Decide on volume strategy — previews can share a read-only volume snapshot or use ephemeral storage
5. Set a base environment to inherit variables from

**Considerations for this project:**
- Preview environments will need their own `ADMIN_PASSWORD` (set a shared test password in Railway's PR environment config)
- `IMAGES_DIR` can be left unset (defaults to `Static/images/` with bundled test images) or pointed at a preview volume
- `IMPORT_ROOT` limits admin filesystem imports to one approved staging directory; keep the default ephemeral `imports/` directory or set an explicit preview path
- `MY_OPENAI_API_KEY` — use a separate key with lower rate limits for previews, or leave unset to disable AI features in previews
- Preview URLs are temporary — don't use them for anything persistent

### Environment Variable Matrix

| Variable | Production | PR Preview |
|----------|-----------|------------|
| `IMAGES_DIR` | `/data/images` (volume) | unset (uses `Static/images/`) |
| `IMPORT_ROOT` | `/data/images/imports` or another approved staging directory | unset (uses `imports/`) |
| `ADMIN_USERNAME` | `admin` | `admin` |
| `ADMIN_PASSWORD` | production secret | shared test password |
| `MY_OPENAI_API_KEY` | production key | test key or unset |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-4o-mini` | `gpt-4o-mini` |
| `MAX_UPLOAD_SIZE_MB` | `50` | `50` |
| `PORT` | set by Railway | set by Railway |

## Workflow Summary

```
developer creates feat/thing from dev
       │
       ▼
push to origin/feat/thing
       │
       ▼
open PR targeting dev ──► Railway PR preview spins up (when enabled)
       │
       ▼
automated checks run (CodeQL, Copilot, code quality)
       │
       ▼
code review ◄──► fix and respond to comments
       │
       ▼
all threads resolved, checks pass
       │
       ▼
merge to dev ──► dev promoted to main for production release
       │
       ▼
merge to main ──► Railway production auto-deploys
       │
       ▼
delete feat/thing branch
```
