#!/usr/bin/env bash
# Run on the VPS from the AMS project directory.
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BRANCH="${DEPLOY_BRANCH:-main}"

cd "$APP_DIR"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Missing $COMPOSE_FILE in $APP_DIR" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.production.example and fill in DB + SECRET_KEY + ALLOWED_HOSTS" >&2
  exit 1
fi

echo "==> Pull latest code ($BRANCH)"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "==> Build and start containers"
docker compose -f "$COMPOSE_FILE" up --build -d

echo "==> Seed PMS permissions (idempotent)"
docker compose -f "$COMPOSE_FILE" exec -T web python manage.py seed_pms_permissions || true

echo "==> Deploy complete"
docker compose -f "$COMPOSE_FILE" ps
