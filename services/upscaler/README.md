# Upscaler service

A separate Railway service that turns gallery artwork into print masters
(300 DPI) and seamless pattern tiles using Real-ESRGAN on Replicate. It lives
in this repo but deploys apart from the gallery, and it works only on explicit
copies kept in the `wrapped-stand` bucket. The gallery never upscales, and
nothing here walks the gallery's image folder.

**Status:** import, library, and jobs (prepare, confirm, run on Replicate,
progress, results). Run it as **one replica**: the job runner, the import
de-duplication lock and the log writer are in-process (see issue #226).

## Pages

- **Import** (`/import`): one importer with three sources. Each one only saves
  a copy to `imports/`:
  1. **From gallery**: pending and approved images, read through the gallery's
     admin API (`/admin/api/new-files`, `/admin/image/{name}`).
  2. **Upload**: files from the system file dialog.
  3. **Server path**: a path relative to `UPSCALER_IMPORT_ROOT`. It must be
     relative, contain no `..`, and resolve inside the root; symlinks out of
     the root are skipped. One import takes at most 50 files.
- **Library** (`/library`): the imported copies. Each row has a **Prepare**
  form: pick a job type and a scale (4× or 2×).
- **Job** (`/jobs/{id}`): Prepare copies the import to `staging/<job>/` and
  analyses the copy. The page shows pixel size, megapixels, the DPI tag,
  whether there is an ICC profile, the seam verdict, the master size and its
  print size at 300 DPI, what Replicate will receive, and a time and cost
  estimate. Nothing is sent to Replicate until **Start upscale**. **Cancel**
  deletes the staged copy. Once started, the page polls `/api/jobs/{id}`
  every 3 s and shows the state, elapsed time against the estimate, and
  Replicate's log; finished jobs link the master (a presigned URL) and, for
  pattern jobs, a 2×2 tiling proof.
- **Jobs** (`/jobs`): every job and its state.

Job types:

| Type                    | What is sent                                      | Master                                       |
| ----------------------- | ------------------------------------------------- | -------------------------------------------- |
| Print master            | the copy as-is (PNG if not JPEG/PNG/WebP)         | the upscale                                  |
| Seamless pattern        | the copy wrap-padded by 32 px                     | padding cropped off, so the edges still wrap |
| Pattern → seamless tile | a 3×3 grid of the repeat found by the seam search | the centre tile                              |

Every master is a PNG tagged at `UPSCALER_PRINT_DPI` (300) with the source's
ICC profile. Prepare refuses a tile job when no repeat is found, and any job
whose Replicate input exceeds `UPSCALER_REPLICATE_MAX_INPUT_MP`. A
seamless-pattern job on an image whose edges do not wrap gets a warning.

Estimates: seconds per input megapixel × `UPSCALER_PRICE_PER_SECOND`. The rate
is `UPSCALER_SECONDS_PER_MP` until a job finishes, then the median of finished
jobs (Replicate's `predict_time` where it reports one).

On start-up the service re-attaches to jobs that were running when it stopped
(it polls the saved prediction instead of starting a new one) and restarts
queued ones. A job interrupted before Replicate returned a prediction id is
marked as an error rather than retried, so it is never billed twice.

Every import is checked for an allowed extension, size, megapixels and that
Pillow can read it. Identical bytes are stored once (sha256).

## Bucket layout

```
imports/<id>-<name>.<ext>     the copy, unchanged
imports/<id>.json             record: source, size, sha256, dimensions, time
imports/by-sha/<sha256>.json  de-duplication index
staging/<job>/source.<ext>    copy made by Prepare (deleted on cancel/done)
staging/<job>/input.png       what Replicate receives, when it differs
staging/<job>/tile.png        extracted repeat, plus proof.jpg (tile jobs)
results/<job>/master.png      the 300 DPI master
results/<job>/proof.jpg       2x2 tiling proof (pattern jobs)
jobs/<job>.json               state, analysis, estimate, timings, error
logs/<YYYY-MM-DD>.jsonl       one line per job event
```

## Configuration

| Variable                                                             | Purpose                                                                                                                |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`                                   | Same login as the gallery admin. Reference the gallery service's variables.                                            |
| `BUCKET`, `ENDPOINT`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `REGION` | Bucket credentials. Reference `wrapped-stand`'s variables.                                                             |
| `GALLERY_URL`                                                        | Gallery base URL the service calls, e.g. `http://${{ArtazzenDotCom.RAILWAY_PRIVATE_DOMAIN}}:${{ArtazzenDotCom.PORT}}`. |
| `GALLERY_ADMIN_URL`                                                  | Public gallery admin URL, for the back link.                                                                           |
| `UPSCALER_BUCKET_PREFIX`                                             | Optional key prefix, e.g. `dev`, for local runs against a shared bucket.                                               |
| `UPSCALER_IMPORT_ROOT`                                               | Root for server-path imports (default `services/upscaler/imports`).                                                    |
| `UPSCALER_MAX_UPLOAD_MB`, `UPSCALER_MAX_MEGAPIXELS`                  | Intake limits (defaults 50 and 100).                                                                                   |
| `REPLICATE_API_TOKEN`                                                | Replicate API token. Set on this service only.                                                                         |
| `REPLICATE_UPSCALE_MODEL`, `REPLICATE_UPSCALE_VERSION`               | Model (default `nightmareai/real-esrgan`, latest version) and an optional pinned version id.                           |
| `UPSCALER_REPLICATE_MAX_INPUT_MP`                                    | Largest input sent to Replicate (default 4). Assumed from the model's "1440p recommended" note; check it.              |
| `UPSCALER_SECONDS_PER_MP`, `UPSCALER_PRICE_PER_SECOND`               | Estimate until jobs finish (defaults 10 s and $0.000225/s). Assumed; check the model's pricing.                        |
| `UPSCALER_MAX_CONCURRENT_JOBS`                                       | Jobs on Replicate at once (default 1).                                                                                 |
| `UPSCALER_MAX_OUTPUT_MEGAPIXELS`                                     | Largest output post-processing decodes (default 400).                                                                  |
| `REPLICATE_TIMEOUT_SECONDS`, `UPSCALER_POLL_SECONDS`                 | Give up after (default 1800 s); poll interval (default 3 s).                                                           |
| `UPSCALER_PRINT_DPI`                                                 | DPI tag on masters (default 300).                                                                                      |

On the gallery service, set `UPSCALER_URL` to this service's public URL to
show the "Upscaler" link in the admin.

Railway settings: root directory `services/upscaler`, watch paths
`services/upscaler/**`. The start command is in the `Procfile`.

**To confirm when the Railway service is created** (not yet verified against
Railway):

- the variable names the `wrapped-stand` bucket exposes for references (the
  table above assumes `BUCKET`, `ENDPOINT`, `ACCESS_KEY_ID`,
  `SECRET_ACCESS_KEY`, `REGION`);
- that `${{ArtazzenDotCom.PORT}}` resolves, i.e. `PORT` is a defined variable
  on the gallery service, and that the gallery is reachable on the private
  network while it binds `0.0.0.0` (private networking may need an IPv6
  bind);
- that uploads and presigned URLs work against the real bucket with
  `region=auto` and virtual-hosted addressing. Tests use moto, which does not
  prove this.

## Local run and tests

```bash
cd services/upscaler
pip install -r requirements-dev.txt
pytest
ADMIN_PASSWORD=... BUCKET=... ENDPOINT=... ACCESS_KEY_ID=... SECRET_ACCESS_KEY=... \
  UPSCALER_BUCKET_PREFIX=dev uvicorn upscaler.app:create_app --factory --reload
```

Tests use moto for the bucket and `httpx.MockTransport` for the gallery and
for Replicate. The fake Replicate reads the presigned input from the mocked
bucket and resizes it, so crops and sizes are checked, but the real model's
input names (`image`, `scale`, `face_enhance`, taken from PR #130), its
limits and its output format are not.
