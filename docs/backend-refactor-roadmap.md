# Backend Refactor Roadmap

Status: proposal, 2026-10-09. Nothing here is implemented yet.

This roadmap takes the backend from "routes that do everything" to three
separated layers: a versioned JSON API package (the "API blueprint"; in FastAPI
this is an `APIRouter` package), typed contracts for every request and
response, and a service layer that owns the business rules.

## Where the backend is today

| Fact                                                                                                               | Evidence                                      |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| One 788-line module holds all 19 admin routes: HTML pages, JSON endpoints, upload, import, AI regeneration.        | `app/routes_admin.py`                         |
| No typed request or response models. Four routes parse `await request.json()` by hand; one takes 11 `Form` fields. | `app/routes_admin.py:152,195,237,285,604-614` |
| JSON endpoints are spread over three URL shapes: `/admin/api/*`, `/admin/config`, `/admin/<verb>/{name}`.          | route decorators in `app/routes_admin.py`     |
| The iOS app (ArtazzenMobile) calls these admin endpoints with Basic auth. They are an external contract already.   | paths found in the ArtazzenMobile source      |
| Business rules live inside route handlers (approve, unapprove, delete, upload conflict handling).                  | `app/routes_admin.py:600-735`                 |
| "Is this artwork public?" is answered in several places with slightly different checks.                            | `app/curation.py:245`, `app/sidecars.py:396`  |
| The public artwork page has no status check at all.                                                                | `app/routes_public.py:174-200`                |
| Every gallery request lists the image directory and reads every sidecar.                                           | `app/sidecars.py:386-402`                     |
| Errors are raised ad hoc: 29 `HTTPException` sites, 13 broad `except Exception`.                                   | `app/`                                        |
| `sentry-sdk` is installed but never initialised. There is no health endpoint.                                      | `requirements.txt:57`; no import in `app/`    |
| All 101 tests are in one 2,195-line file with 176 monkeypatches; `main.py` re-exports internals for them.          | `tests/test_main.py`, `main.py`               |
| A separate `mypy app` run reports 3 errors on `dev`; CI currently checks only `main.py`.                           | PR #170 dev check; `.github/workflows/ci.yml` |

## Target shape

```
app/
  api/                 # the API blueprint: APIRouter(prefix="/api/v1")
    __init__.py        # api_router that includes the routers below
    deps.py            # auth, pagination, idempotency key
    errors.py          # error envelope and exception handlers
    artworks.py        # list, get, update, approve, unapprove, hide, delete
    uploads.py         # upload, import
    collections.py
    series.py
    ai.py              # regenerate, preview, config
  contracts/           # Pydantic models; no FastAPI or filesystem imports
    artwork.py         # Artwork, ArtworkStatus, ArtworkUpdate, ArtworkList
    curation.py        # Collection, Series and their mutations
    ai.py              # AIConfig, RegenerateRequest, RegenerateResult
    errors.py          # ErrorResponse
  services/            # business rules; no FastAPI imports
    artworks.py
    uploads.py
    curation.py
    ai.py
  storage/             # sidecars, registries, media files (today's sidecars.py, parts of curation.py)
  web/                 # Jinja pages (public and admin); call services, never storage
  config.py  security.py  watcher.py  factory.py
```

Dependency rule: `web` and `api` → `services` → `storage`. `contracts` is
imported by all three and imports none of them.

## Business contracts

These are the rules the service layer must enforce in one place. Each gets a
test that does not go through HTTP.

**Artwork lifecycle**

```
            approve                 hide
 pending ───────────► approved ◄──────────► hidden
    ▲                    │   unapprove
    └────────────────────┘
 any state ──delete──► trashed (moved to .trash/, not listed, not served)
```

- Only `approved` artwork is public: image files, thumbnails, the artwork
  page, collection pages, sitemap, social-card metadata. One function,
  `services.artworks.is_public()`, answers this everywhere.
- Leaving `approved` purges the image from the CDN.
- An admin edit always wins over a concurrent AI result.

**Sidecars and registries**

- The sidecar is the source of truth for an artwork; `ImageSidecar.schema.json`
  stays authoritative and the Pydantic model is tested against it.
- A sidecar's `collections` array is the membership record.
- A series belongs to exactly one collection; the series registry wins over
  sidecar mirrors.
- Deleting a collection re-parents its children and removes the slug from
  every sidecar.

**AI metadata**

- AI fills only empty fields unless the caller forces regeneration.
- `ai_fields` records which fields AI wrote.
- Automatic retries are bounded (cooldown from PR #170). Manual regeneration
  is never throttled.

**Uploads and imports**

- Allowed extensions and size limit are checked before anything is written.
- Filenames are sanitised; an existing file is never overwritten without
  `force`.
- Imports read only from `IMPORT_ROOT`.

**API behaviour**

- Every error has one shape: `{"error": {"code": "...", "message": "...", "details": {...}}}`.
- Mutations accept an `Idempotency-Key`. The service atomically reserves each
  key scoped to the authenticated principal and operation, stores a request
  fingerprint plus the completed response/status with a TTL, replays matching
  requests, and rejects reuse with a different payload using `409`. The
  mutation and idempotency record commit as one operation so concurrent
  requests, restarts, and multiple workers cannot apply it twice.
- Lists are paginated and state their total.

## API v1 surface

| v1                                             | Replaces                                    |
| ---------------------------------------------- | ------------------------------------------- |
| `GET /api/v1/artworks?status=`                 | `GET /admin/api/new-files`                  |
| `GET /api/v1/artworks/{name}`                  | `GET /admin/api/sidecar/{name}`             |
| `PATCH /api/v1/artworks/{name}`                | `POST /admin/metadata/{name}`               |
| `POST /api/v1/artworks/{name}/approve`         | `POST /admin/metadata/{name}` with `action` |
| `POST /api/v1/artworks/{name}/unapprove`       | `POST /admin/unapprove/{name}`              |
| `POST /api/v1/artworks/{name}/hide`            | new explicit lifecycle operation            |
| `DELETE /api/v1/artworks/{name}`               | `POST /admin/delete/{name}`                 |
| `POST /api/v1/artworks:approve-pending`        | `POST /admin/api/accept-all`                |
| `POST /api/v1/uploads`                         | `POST /admin/upload`                        |
| `POST /api/v1/imports`                         | `POST /admin/import-path`                   |
| `GET/POST/PATCH/DELETE /api/v1/collections`    | `GET/POST /admin/api/collections`           |
| `GET/POST/PATCH/DELETE /api/v1/series`         | `GET/POST /admin/api/series`                |
| `GET/PUT/DELETE /api/v1/ai/config`             | `/admin/config`, `/admin/config/reset`      |
| `POST /api/v1/ai/regenerations`                | `POST /admin/ai/regenerate`                 |
| `GET /api/v1/artworks/{name}/image` (no-store) | pending previews loaded from `/images/`     |

Old paths stay as compatibility adapters until the iOS app has moved, then
are removed in phase 5. Each adapter preserves the exact legacy transport
contract (form or multipart parsing, status codes, redirects, and response
wrappers) while delegating to the same service functions as v1. Contract tests
cover both surfaces until removal.

## Phases

Each phase is one or more pull requests to `dev` and leaves the app releasable.

### Phase 0: safety net

- Contract tests that pin the current JSON of every endpoint the iOS app
  calls (`/admin/api/new-files`, `/admin/config`, `/admin/upload`,
  `/admin/api/collections`, `/admin/ai/regenerate`, `/admin/unapprove/`,
  `/admin/metadata/`, `/admin/delete/`).
- Split `tests/test_main.py` by area without changing any test body.
- Broaden CI from `mypy main.py` to `mypy app` (or the whole project), then fix
  the 3 errors exposed by that check.

Exit: suite green, type check clean, a snapshot exists for each endpoint above.

### Phase 1: contracts

- Add `app/contracts/`. A test proves the `Artwork` model and
  `ImageSidecar.schema.json` accept and reject the same documents.
- Replace hand parsing in the four JSON routes and the 11-field form with
  request models. Responses unchanged byte for byte (phase 0 tests prove it).

Exit: no `await request.json()` left in route code.

### Phase 2: services

- Move lifecycle, upload, import and AI orchestration out of
  `routes_admin.py` into `app/services/`. Routes shrink to parse, call, render.
- `is_public()` becomes the single approval check. Replace the plain `/images`
  `StaticFiles` mount with a status-aware public image handler so pending and
  hidden originals cannot bypass that check; pending previews remain available
  only through the authenticated no-store preview route.
- Service tests call functions directly; HTTP tests stop monkeypatching
  internals.

Exit: `routes_admin.py` has no filesystem or `shutil` calls; no route file
imports `storage` directly.

### Phase 3: API package

- Add `app/api/` mounted at `/api/v1` with the table above, the error
  envelope, pagination and the durable idempotency contract. Every v1 route
  reuses the existing admin-auth dependency from its first release; phase 4
  replaces that credential mechanism rather than introducing authentication.
- Old endpoints remain compatibility adapters and return a `Deprecation`
  header while preserving their exact legacy request and response shapes.
- Disable FastAPI's default `/openapi.json`, `/docs`, and `/redoc` endpoints.
  Serve the schema and documentation through explicitly authenticated admin
  routes; hand the generated client or spec file to the ArtazzenMobile repo.

Exit: every iOS call has a v1 equivalent covered by tests.

### Phase 4: production hardening

- API token authentication for `/api/v1` (Basic auth stays for the HTML
  admin); throttle repeated auth failures.
- Initialise Sentry; add request IDs and structured logs.
- `GET /healthz` for Railway health checks.
- Settings object validated at startup (fail fast on a missing
  `ADMIN_PASSWORD` in production).
- Watcher exposes its last run, queue length and failures to the admin page.

Exit: a failed OpenAI call, a failed CDN purge and a failed scan are each
visible in Sentry and on the admin page.

### Phase 5: remove the old surface

- Delete alias routes once the iOS release using v1 is live.
- Reduce `main.py` to the app object; delete the re-exports kept for tests.
- Move HTML routes under `app/web/`.

Exit: one way to do each thing; `main.py` under 15 lines.

### Later, only if measurements ask for it

- An in-memory or SQLite index of sidecars so gallery requests stop scanning
  the directory.
- Object storage (R2) behind the `storage` interface.

## How this fits work already planned

- PR #170 (watcher retry cooldown) and the image caching and thumbnail work
  go first. The image work adds `app/media.py`; in phase 2 its purge and
  approval calls move behind `services.artworks`.
- The approved-only decision for `/images` breaks pending previews in the iOS
  app, which loads them from `/images/`. The authenticated preview route must
  ship, and the app must use it, before approved-only reaches production.

## Decisions needed before phase 1

1. API prefix: `/api/v1` (recommended; clean separation from HTML admin) or
   `/admin/api/v1` (keeps everything under the existing `/admin` robots and
   auth rules).
2. Source of truth for the artwork shape: keep `ImageSidecar.schema.json`
   authoritative with a parity test (recommended; no migration), or generate
   the JSON schema from the Pydantic model.
3. API authentication for the iOS app: prefer per-device scoped credentials or
   short-lived sessions issued after admin login. If a static bearer token is
   used for a single admin, generate a high-entropy value, provision it out of
   band to both Railway and the device, store it only in iOS Keychain, never
   bundle or log it, and provide explicit rotation and revocation. Basic auth
   remains the fallback during migration.

## Risks

| Risk                                                 | Mitigation                                                      |
| ---------------------------------------------------- | --------------------------------------------------------------- |
| Breaking the iOS app mid-refactor                    | Phase 0 snapshots; aliases until phase 5                        |
| Behaviour drift while moving logic into services     | Move first, change later; one behaviour change per pull request |
| Test rewrite hides regressions                       | Phase 0 splits files without editing test bodies                |
| Two schemas (JSON schema and Pydantic) drifting      | Parity test in phase 1                                          |
| Long-lived refactor branch conflicting with features | Each phase lands on `dev` separately; no umbrella branch        |