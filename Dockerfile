# Torque application image (Module 11 — Tech Stack & Infra).
#
# ONE image, reused by all three application processes — the FastAPI API, the
# Celery worker, and the Celery beat scheduler — which differ only by the
# `command:` docker-compose gives them. Postgres and Redis run from their own
# official images (see docker-compose.yml); this image is the Torque code only.
#
# Free-tier / self-hosted only (Blueprint v7 build constraint): a slim CPython
# base, `uv` for a lockfile-reproducible install, no build tools left behind.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN pip install --no-cache-dir "uv>=0.4" \
    && groupadd --system torque \
    && useradd --system --gid torque --home-dir /app torque

# Dependency layer first — cached until pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Application code.
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev \
    && chown -R torque:torque /app

USER torque

# uvicorn default; docker-compose overrides for the worker / beat services.
EXPOSE 8000
CMD ["python", "-m", "torque"]
