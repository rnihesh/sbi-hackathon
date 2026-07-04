#!/usr/bin/env bash
# Sarathi VPS deploy: pull latest main, rebuild images, migrate, restart.
# Run on the server from anywhere: /opt/sarathi/infra/deploy.sh
set -euo pipefail

REPO_DIR="${SARATHI_DIR:-/opt/sarathi}"
COMPOSE="docker compose -f $REPO_DIR/infra/docker-compose.vps.yml"

cd "$REPO_DIR"
echo "==> pulling main"
git fetch origin main
git reset --hard origin/main

echo "==> building images"
$COMPOSE build

echo "==> running migrations"
$COMPOSE run --rm migrate

echo "==> restarting services"
$COMPOSE up -d backend worker frontend

echo "==> pruning dangling images"
docker image prune -f >/dev/null

echo "==> health"
sleep 5
curl -fsS http://127.0.0.1:8100/healthz && echo
curl -fsS -o /dev/null -w "frontend %{http_code}\n" http://127.0.0.1:3100/
echo "deploy done"
