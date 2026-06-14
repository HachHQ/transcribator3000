#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/transcribator3000}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required."
  exit 1
fi

mkdir -p "$APP_DIR"
rsync -a --delete ./ "$APP_DIR/"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created $APP_DIR/.env — fill in your tokens before starting."
  exit 0
fi

docker compose up -d --build
docker compose ps
echo "Deployed to $APP_DIR"
