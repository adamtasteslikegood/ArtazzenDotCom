# Upscaler service

A separate Railway service that turns gallery artwork into print masters
(300 DPI) and seamless pattern tiles using Real-ESRGAN on Replicate. It lives
in this repo but deploys apart from the gallery, and it works only on explicit
copies kept in the `wrapped-stand` bucket. The gallery never upscales, and
nothing here walks the gallery's image folder.

**Status:** import and library. Prepare, confirm, Replicate jobs and progress
come in the next change.

## Pages

- **Import** (`/import`): one importer with three sources. Each one only saves
  a copy to `imports/`:
  1. **From gallery**: pending and approved images, read through the gallery's
     admin API (`/admin/api/new-files`, `/admin/image/{name}`).
  2. **Upload**: files from the system file dialog.
  3. **Server path**: a path relative to `UPSCALER_IMPORT_ROOT`. It must be
     relative, contain no `..`, and resolve inside the root; symlinks out of
     the root are skipped. One import takes at most 50 files.
- **Library** (`/library`): the imported copies.

Every import is checked for an allowed extension, size, megapixels and that
Pillow can read it. Identical bytes are stored once (sha256).

## Bucket layout

```
imports/<id>-<name>.<ext>     the copy, unchanged
imports/<id>.json             record: source, size, sha256, dimensions, time
imports/by-sha/<sha256>.json  de-duplication index
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

On the gallery service, set `UPSCALER_URL` to this service's public URL to
show the "Upscaler" link in the admin.

Railway settings: root directory `services/upscaler`, watch paths
`services/upscaler/**`. The start command is in the `Procfile`.

## Local run and tests

```bash
cd services/upscaler
pip install -r requirements-dev.txt
pytest
ADMIN_PASSWORD=... BUCKET=... ENDPOINT=... ACCESS_KEY_ID=... SECRET_ACCESS_KEY=... \
  UPSCALER_BUCKET_PREFIX=dev uvicorn upscaler.app:create_app --factory --reload
```

Tests use moto for the bucket and an `httpx.MockTransport` for the gallery.
