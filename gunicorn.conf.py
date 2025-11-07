"""
Gunicorn configuration for ArtazzenDotCom

This file is pure Python. All settings include:
- The effective DEFAULT (as used here)
- How to override via environment variables
- How to reset to Gunicorn’s own default (unset env var or remove override)

Run:
  gunicorn main:app --config gunicorn.conf.py

Notes:
- Binds to 0.0.0.0 so other LAN devices can access the app.
- Uses Uvicorn workers for FastAPI.
- Writes access/error logs to ./logs/ by default.
"""

import os
from pathlib import Path


# --- Paths / Logs ---
# DEFAULT: create ./logs directory (you can change with GUNICORN_LOGDIR)
LOG_DIR = Path(os.getenv("GUNICORN_LOGDIR", "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)


# --- Binding / Network ---
# DEFAULT: 0.0.0.0:8000 (so LAN devices can reach it)
# Override: set env GUNICORN_BIND (e.g., "127.0.0.1:8000" to restrict to localhost)
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")


# --- Concurrency ---
# DEFAULT: 4 workers (Override via WEB_CONCURRENCY)
# Reset to Gunicorn default by unsetting WEB_CONCURRENCY (Gunicorn default is 1)
workers = int(os.getenv("WEB_CONCURRENCY", "4"))

# DEFAULT: Uvicorn worker class for ASGI/FastAPI
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# DEFAULT: no threads for uvicorn workers (threads are ignored with this worker class)
threads = int(os.getenv("GUNICORN_THREADS", "1"))

# DEFAULT: do not preload the app (helps avoid double-start side effects)
preload_app = os.getenv("GUNICORN_PRELOAD", "false").lower() == "true"


# --- Timeouts / Keepalive ---
# DEFAULT: 120s worker timeout to tolerate slow AI enrichment
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))

# DEFAULT: 30s graceful timeout for worker shutdowns
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))

# DEFAULT: 5s HTTP keep-alive
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))


# --- Request cycling (optional) ---
# DEFAULT: disabled (0)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "0"))


# --- Logging ---
# DEFAULT: write access and error logs to files under ./logs
# Reset to Gunicorn's defaults by unsetting these env vars (errorlog= '-', accesslog=None)
errorlog = os.getenv("GUNICORN_ERRORLOG", str(LOG_DIR / "gunicorn_error.log"))
accesslog = os.getenv("GUNICORN_ACCESSLOG", str(LOG_DIR / "gunicorn_access.log"))

# DEFAULT: info
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")

# DEFAULT: capture stdout/stderr from workers into error log
capture_output = os.getenv("GUNICORN_CAPTURE_OUTPUT", "true").lower() == "true"

# DEFAULT: common combined format with referer and user-agent
access_log_format = os.getenv(
    "GUNICORN_ACCESS_FORMAT",
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"',
)


# --- Dev convenience ---
# DEFAULT: auto-reload disabled. Enable for local dev with GUNICORN_RELOAD=true
reload = os.getenv("GUNICORN_RELOAD", "false").lower() == "true"


# --- Proxies / TLS (advanced, optional) ---
# DEFAULTS: leave disabled unless deploying behind a proxy that sets X-Forwarded-For
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
proxy_protocol = os.getenv("GUNICORN_PROXY_PROTOCOL", "false").lower() == "true"


# How to reset to defaults:
# - Remove/ignore this file OR unset the env vars above to let Gunicorn use its own defaults.
# - Example to revert binding to localhost: export GUNICORN_BIND=127.0.0.1:8000

