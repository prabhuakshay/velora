# syntax=docker/dockerfile:1
#
#   docker compose up                              dev: runserver + tailwind watcher
#   docker compose -f compose.prod.yaml up -d      prod: gunicorn, assets baked in
#
# Dev stages hold a toolchain and no source (the tree is bind-mounted). The prod
# stage holds source, venv and compiled assets, and no toolchain.

ARG PYTHON_VERSION=3.14
ARG NODE_VERSION=25
ARG UV_VERSION=0.12

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv


FROM node:${NODE_VERSION}-slim AS tailwind

ARG DOCKER_UID=1000
ARG DOCKER_GID=1000

WORKDIR /app

# Docker seeds the anonymous node_modules volume from the image, ownership
# included; without this it arrives root-owned and npm can't write to it.
RUN mkdir -p /app/node_modules && chown -R ${DOCKER_UID}:${DOCKER_GID} /app

CMD ["sh", "-c", "npm install --no-audit --no-fund && npm run watch"]


FROM python:${PYTHON_VERSION}-slim AS dev

COPY --from=uv /uv /usr/local/bin/

# The venv lives outside the bind mount so the host's .venv can't collide with
# it. Copy mode because the cache volume and venv are different filesystems.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/cache/uv \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/opt/venv/bin:$PATH"

ARG DOCKER_UID=1000
ARG DOCKER_GID=1000

RUN mkdir -p /opt/venv /cache/uv /app/staticfiles \
    && chown -R ${DOCKER_UID}:${DOCKER_GID} /opt/venv /cache/uv /app/staticfiles

WORKDIR /app

COPY docker/dev-entrypoint.sh /usr/local/bin/dev-entrypoint

ENTRYPOINT ["dev-entrypoint"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


FROM node:${NODE_VERSION}-slim AS assets

WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# Tailwind only emits classes it finds, so every directory that can name one
# must be here; a missing one silently ships unstyled pages.
COPY assets/ assets/
COPY templates/ templates/
COPY apps/ apps/
RUN npm run build


FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=uv /uv /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/cache/uv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/cache/uv \
    uv sync --frozen --no-dev --no-install-project


FROM python:${PYTHON_VERSION}-slim AS prod

# Bytecode is precompiled below and the root filesystem is read-only, so
# workers must not retry writing .pyc files on every import.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app

WORKDIR /app

# Owned by root and only readable by app, so a compromised worker can't
# rewrite the code it runs.
COPY --from=builder /opt/venv /opt/venv
COPY manage.py ./
COPY config/ config/
COPY apps/ apps/
COPY templates/ templates/
COPY --from=assets /app/static/ static/
COPY docker/gunicorn.conf.py docker/

# Settings require these at import time; they exist for this command only and
# the database is never connected to.
RUN SECRET_KEY=collectstatic \
    DATABASE_URL=sqlite:///collectstatic \
    python manage.py collectstatic --noinput \
    && python -m compileall -q config apps manage.py

# A fresh named volume copies this directory's ownership, which is the only
# way the app user can write uploads on a read-only root filesystem.
RUN install -d -o app -g app -m 750 /app/media

USER app

EXPOSE 8000

CMD ["gunicorn", "--config", "docker/gunicorn.conf.py", "config.wsgi:application"]
