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

| Branch                                 | Purpose                   | Deploys To                        | Protected                               |
| -------------------------------------- | ------------------------- | --------------------------------- | --------------------------------------- |
| `main`                                 | Production-ready code     | Railway production                | Yes — PR required, all threads resolved |
| `dev`                                  | Integration and staging   | Railway staging (when configured) | Yes — PR required                       |
| `feat/*`, `fix/*`, `docs/*`, `chore/*` | Short-lived work branches | Railway PR previews               | No                                      |

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
- `IMAGES_DIR` is inherited from the base environment (`/data/images`). Each preview gets its own volume, which starts empty: the repository holds no artwork. See [Seeding preview images](#seeding-preview-images)
- `IMPORT_ROOT` limits admin filesystem imports to one approved staging directory; keep the default ephemeral `imports/` directory or set an explicit preview path
- `MY_OPENAI_API_KEY` — use a separate key with lower rate limits for previews, or leave unset to disable AI features in previews
- Preview URLs are temporary — don't use them for anything persistent

### Environment Variable Matrix

| Variable                      | Production                                                   | PR Preview                   |
| ----------------------------- | ------------------------------------------------------------ | ---------------------------- |
| `IMAGES_DIR`                  | `/data/images` (volume)                                      | `/data/images` (own volume)  |
| `IMPORT_ROOT`                 | `/data/images/imports` or another approved staging directory | unset (uses `imports/`)      |
| `ADMIN_USERNAME`              | `admin`                                                      | `admin`                      |
| `ADMIN_PASSWORD`              | production secret                                            | shared test password         |
| `MY_OPENAI_API_KEY`           | production key                                               | test key or unset            |
| `OPENAI_IMAGE_METADATA_MODEL` | `gpt-6-luna`                                                 | `gpt-6-luna`                 |
| `MAX_UPLOAD_SIZE_MB`          | `50`                                                         | `50`                         |
| `CLOUDFLARE_API_TOKEN`        | Cache Purge token                                            | unset (no purge)             |
| `CLOUDFLARE_ZONE_ID`          | artazzen.com zone id                                         | unset                        |
| `FIRE_OPAL_PAYLINK_URL`       | GoDaddy/PayPal pay link                                      | unset or same link           |
| `SUPPORT_LINKS`               | sponsorship links                                            | unset or same links          |
| `JOIN_FEATURE_IMAGE`          | file name of an approved image                               | unset (first artwork)        |
| `SEED_ARCHIVE_URL`            | unset                                                        | inherited from `staging-dev` |
| `SEED_S3_*`                   | unset                                                        | unset (never on Railway)     |
| `PORT`                        | set by Railway                                               | set by Railway               |

### Seeding preview images

A new preview's image volume is empty. Two ways to fill it:

**Automatically, from a seed archive.** `railway.json` gives pull-request
environments (and only those) the start command
`python scripts/seed_images.py start`. It downloads one archive, unpacks it
into `IMAGES_DIR` and then runs the `Procfile`'s web command. It runs in the
start command because Railway does not mount volumes during a pre-deploy
command. Files already on the volume are never overwritten, so edits made in a
preview survive its next deploy. The one exception: while the volume still has
no artwork, an empty collection or series registry that the app created on its
first start is replaced, under the app's registry lock, because it would
otherwise hide the seeded one.
An artwork image is unpacked only if its sidecar is in the archive or already
on the volume. Without the variable below it logs one line and starts the app;
a failed download logs a warning and starts the app.

The archive lives in the `staging-dev` environment's storage bucket. A bucket
has no file path or mount: it is reached over HTTPS, with credentials. Previews
do not get those credentials. They get a presigned link:

| Variable           | Set on                | Value                                |
| ------------------ | --------------------- | ------------------------------------ |
| `SEED_ARCHIVE_URL` | `staging-dev` service | the link printed by `push` or `link` |

- The link can read that one archive and nothing else. It cannot write, delete
  or list, so code running in a preview cannot change the seed. Anyone who has
  the link can download the archive until it expires.
- **The link expires after at most 90 days** (Railway's limit). After that a
  preview logs `the seed link answered HTTP 403` and starts empty. Run
  `python scripts/seed_images.py link` and update the variable.
- Do not seal it. Sealed variables are not copied into PR environments.
- Never set the bucket's keys (`SEED_S3_*`, below) on a Railway environment.
  Railway has no read-only bucket keys, so those keys can overwrite the seed.
  The seeder warns when it finds them in an environment.
- The seeder refuses to run when `RAILWAY_ENVIRONMENT_NAME` starts with `prod`
  or the environment is the production one. `start` also copies nothing unless
  the name ends in `-pr-<number>`, which is how Railway names pull-request
  environments, so it is safe as the start command of any environment.
- **`railway.json` stops being read on 2026-12-01** (Railway has deprecated
  Config as Code). Its replacement, `.railway/railway.ts`, is applied to one
  environment at a time and has no pull-request override. See `TODOS.md` for
  the two ways to keep automatic seeding after that date.

Upload or refresh the archive from a machine that has the local seed set
(`test_data/images`, never committed). This is the only place the bucket's
keys are used. Export them in that shell, from the Credentials tab of the
`staging-dev` bucket: `SEED_S3_ENDPOINT`, `SEED_S3_BUCKET` (the S3 name, not
the display name), `SEED_S3_ACCESS_KEY_ID` and `SEED_S3_SECRET_ACCESS_KEY`.
`push` and `link` need `boto3`, which the app does not install.

```bash
pip install boto3
python scripts/seed_images.py push test_data/images --dry-run
python scripts/seed_images.py push test_data/images   # prints the link
python scripts/seed_images.py link                    # a new link, no upload
```

**By hand, over `railway ssh`.** `scripts/seed-env-images.sh <environment>`
sends a local folder to the environment's volume and overwrites same-named
files. `scripts/seed-env-images.sh --from-archive <environment>` makes a
running environment download and unpack its seed archive again. Both refuse
production; see `--help`.

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
merge to dev ──► prepare release PR to main
       │
       ▼
bump VERSION + pyproject.toml, roll CHANGELOG [Unreleased] → [X.Y.Z]
       │
       ▼
open PR targeting main ──► release-gate CI validates version bump
       │
       ▼
merge to main ──► release workflow tags vX.Y.Z + creates GitHub release
       │              ──► Railway production auto-deploys
       ▼
delete feat/thing branch
```

## Release Process

Releases use semantic versioning (`X.Y.Z`) with GitHub tagged releases.

### Version Files

- `VERSION` — single source of truth, contains `X.Y.Z` (no `v` prefix)
- `pyproject.toml` `version` field — must match `VERSION` exactly

### Release Workflow

1. Accumulate changes on `dev` with entries in the `[Unreleased]` section of `CHANGELOG.md`
2. When ready to release, create a PR from `dev` to `main`:
   - Bump `VERSION` to the next semver (exactly one of: major+1.0.0, minor+1, patch+1)
   - Update `pyproject.toml` version to match
   - Roll `[Unreleased]` into `## [X.Y.Z] - YYYY-MM-DD` in `CHANGELOG.md`
3. The `release-gate` CI check validates:
   - `VERSION` is valid `X.Y.Z` semver
   - Version is exactly one increment from `main`'s current version
   - Tag `vX.Y.Z` does not already exist
   - `CHANGELOG.md` contains a `## [X.Y.Z]` entry
   - `pyproject.toml` version matches `VERSION`
4. On merge to `main`, the `release` workflow:
   - Creates git tag `vX.Y.Z`
   - Creates a GitHub release with the changelog section as notes
5. Railway auto-deploys from `main`

### CI Workflows

| Workflow       | Trigger              | Purpose                                         |
| -------------- | -------------------- | ----------------------------------------------- |
| `ci.yml`       | Push/PR to dev, main | Lint, typecheck, test, prettier, security scan  |
| `release-gate` | PR to main           | Validate version bump, changelog, tag freshness |
| `release`      | Push to main         | Auto-create git tag + GitHub release            |
