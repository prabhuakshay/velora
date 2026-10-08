#!/bin/sh
# Runs on every start because the lockfile and migrations live in the
# bind-mounted tree: pulling a branch shouldn't require an image rebuild.
set -eu

uv sync --frozen
python manage.py migrate --noinput

exec "$@"
