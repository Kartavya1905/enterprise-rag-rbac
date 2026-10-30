# =============================================================================
# FILE:         Dockerfile
# WHAT IT DOES: Recipe for packaging the API into a container image.
# WHERE IT FITS: Phase 1. docker-compose.yml builds this image for the "api" service.
# RESULT:       An image that runs `uvicorn app.main:app` on port 8000.
# =============================================================================

# --- STEP 1: start from a small official Python 3.12 image ---
FROM python:3.12-slim

# Don't write .pyc files; print logs immediately; don't keep pip's download cache.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# --- STEP 2: install dependencies FIRST (cached layer) ---
# Only pyproject.toml is copied here, with an empty placeholder app package, so this slow
# step is re-run only when dependencies change - not on every code edit.
COPY pyproject.toml README.md ./
# pip itself is upgraded first: the base image's copy can have known vulnerabilities.
RUN pip install --upgrade pip \
    && mkdir app && touch app/__init__.py \
    && pip install . \
    && rm -rf app

# --- STEP 3: copy the real application code ---
COPY app ./app
RUN pip install --no-deps .
# Setup and check tools (Phase 12), so a server needs only Docker, not Python:
#   docker compose exec api python -m scripts.bootstrap     seed users, ingest, index
#   docker compose exec api python -m scripts.smoke_test    check the running API
# (.dockerignore leaves out the dataset generator and the evals: they're dev-only.)
COPY scripts ./scripts

# --- STEP 4: security - run as a normal user, not root ---
# data/models is pre-created so the model-cache volume mounted there is writable by appuser.
RUN useradd --create-home appuser && mkdir -p /srv/data/models && chown -R appuser /srv/data
USER appuser

# --- STEP 5: start the web server ---
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
