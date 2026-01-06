FROM python:3.13-slim

# Safer, leaner defaults for containers
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Install dependencies first (better layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy project files
COPY . /app

# Ensure application directory is owned by the non-root user so logs,
# sidecars, and other runtime files can be written.
RUN chown -R app:app /app

# Run as non-root
USER app

EXPOSE 8000

# Allow tuning via environment, defaulting to a small multi-worker setup.
# uvloop + httptools are enabled by requirements.txt and improve prod performance.
ENV PORT=8000 \
    UVICORN_WORKERS=4

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --loop uvloop --http httptools --workers ${UVICORN_WORKERS:-4}"]
