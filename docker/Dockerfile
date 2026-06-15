# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Mantle Alpha Agent - application image (shared by api / bot / worker / celery)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

# Faster, quieter, predictable Python.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: build tools for any C extensions, libpq for psycopg2, curl for healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code.
COPY backend ./backend
COPY alembic ./alembic
COPY alembic.ini pyproject.toml ./

# Run as a non-root user.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default command runs the API; compose overrides this for bot/worker/celery.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
