#!/usr/bin/env bash
set -euo pipefail

HOST="${DEPLOY_HOST:-root@94.249.203.188}"
REMOTE_DIR="/opt/voice-to-obsidian"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Copying project to $HOST:$REMOTE_DIR"
ssh "$HOST" "mkdir -p $REMOTE_DIR"
scp -r "$LOCAL_DIR/bot" "$LOCAL_DIR/Dockerfile" "$LOCAL_DIR/docker-compose.yml" "$LOCAL_DIR/requirements.txt" "$HOST:$REMOTE_DIR/"

if [[ -f "$LOCAL_DIR/.env" ]]; then
  echo "==> Uploading .env"
  scp "$LOCAL_DIR/.env" "$HOST:$REMOTE_DIR/.env"
else
  echo "==> No local .env — keeping existing remote .env if present"
fi

echo "==> Installing Docker (if needed) and starting bot"
ssh "$HOST" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/voice-to-obsidian

if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

if [[ ! -f .env ]]; then
  echo "ERROR: /opt/voice-to-obsidian/.env not found. Create it with your tokens."
  exit 1
fi

docker compose up -d --build
docker compose ps
docker compose logs --tail=30
REMOTE

echo "==> Done"
